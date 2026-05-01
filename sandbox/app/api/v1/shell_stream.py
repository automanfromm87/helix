"""Interactive shell over WebSocket — pty-backed.

Distinct from `shell.py` which exposes the polling exec/view/wait API
used by the agent's `shell_exec` tool. This endpoint serves the chat-UI's
xterm.js terminal: a real pty, real-time bidirectional stream.

Wire protocol:
  client → server  binary frames  raw stdin (keystrokes from xterm.js)
  client → server  text frames    JSON control: {"type":"resize","cols":N,"rows":M}
  server → client  binary frames  raw stdout/stderr from the pty
  server → client  text frames    JSON status (errors, ready), if needed

The pty + child process are owned by the WS connection — when the WS
closes, the bash exits. No session-id reuse: each terminal panel is its
own pty for simplicity. Existing polling shell sessions (used by
`shell_exec`) are unaffected.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import pty
import signal
import struct
import subprocess
import termios
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()


# Buffer size for each pty read. Large enough to absorb bursty output
# (e.g. `ls -R /` style dumps) without dozens of tiny WS frames per second.
PTY_READ_BUFFER = 4096


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    """ioctl(TIOCSWINSZ) on the pty master to propagate terminal geometry
    to the child process. Without this, the child's $LINES/$COLUMNS stay
    at the default 80x24 and tools like vim render off-screen."""
    rows = max(1, min(rows, 1000))
    cols = max(1, min(cols, 1000))
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except OSError as exc:
        logger.warning("TIOCSWINSZ failed: %s", exc)


def _spawn_bash(rows: int, cols: int, cwd: Optional[str]) -> tuple[subprocess.Popen, int]:
    """Open a pty pair, spawn bash with the slave end as stdio, return
    (popen, master_fd). Caller owns master_fd and must close it.

    `setsid` puts the child in its own session so signals (Ctrl+C, etc)
    sent through the pty hit the foreground job in the shell, not us."""
    master_fd, slave_fd = pty.openpty()
    _set_winsize(master_fd, rows, cols)

    env = os.environ.copy()
    # Make sure the shell knows it's interactive — some prompts and
    # completion features only enable on TERM != "dumb".
    env.setdefault("TERM", "xterm-256color")

    proc = subprocess.Popen(
        ["/bin/bash", "-il"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=cwd or os.path.expanduser("~"),
        env=env,
        preexec_fn=os.setsid,
        close_fds=True,
    )
    # Parent only needs the master end; close the slave so EOF propagates
    # cleanly when bash exits.
    os.close(slave_fd)
    return proc, master_fd


@router.websocket("/stream")
async def shell_stream(
    ws: WebSocket,
    cols: int = 80,
    rows: int = 24,
    cwd: Optional[str] = None,
) -> None:
    """One pty per connection. Outlives nothing — close == kill."""
    await ws.accept()

    try:
        proc, master_fd = _spawn_bash(rows=rows, cols=cols, cwd=cwd)
    except Exception as exc:
        logger.exception("Failed to spawn pty bash")
        await ws.send_text(json.dumps({"type": "error", "message": str(exc)}))
        await ws.close(code=1011, reason="pty spawn failed")
        return

    logger.info("Shell stream opened pid=%s master_fd=%s", proc.pid, master_fd)

    loop = asyncio.get_running_loop()
    pty_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)

    def _pty_readable() -> None:
        # Called by the event loop when master_fd has bytes ready. We
        # read non-blocking up to PTY_READ_BUFFER and push to a queue
        # for the WS sender task to drain. Keeping this callback
        # synchronous keeps loop scheduling simple.
        try:
            data = os.read(master_fd, PTY_READ_BUFFER)
        except OSError:
            data = b""
        if not data:
            # EOF — child exited (or pty closed). Push a sentinel so the
            # sender wakes up and closes the WS.
            pty_queue.put_nowait(b"")
            try:
                loop.remove_reader(master_fd)
            except (ValueError, KeyError):
                pass
            return
        try:
            pty_queue.put_nowait(data)
        except asyncio.QueueFull:
            # Drop output rather than block the event loop. A flooding
            # producer (`yes`) shouldn't pin the whole connection.
            logger.warning("pty output queue full — dropping %d bytes", len(data))

    # Make master_fd non-blocking and wire it into the loop.
    os.set_blocking(master_fd, False)
    loop.add_reader(master_fd, _pty_readable)

    async def _send_loop() -> None:
        """Drain pty_queue → WS as binary frames. Returns when EOF or WS
        is closed by the client."""
        while True:
            data = await pty_queue.get()
            if not data:
                # EOF sentinel
                return
            try:
                await ws.send_bytes(data)
            except (WebSocketDisconnect, RuntimeError):
                return

    async def _recv_loop() -> None:
        """Receive WS frames → write to pty. Binary frames are raw stdin;
        text frames are JSON control (resize, etc.)."""
        while True:
            try:
                msg = await ws.receive()
            except WebSocketDisconnect:
                return
            mtype = msg.get("type")
            if mtype == "websocket.disconnect":
                return
            data = msg.get("bytes")
            if data is not None:
                try:
                    os.write(master_fd, data)
                except OSError:
                    return
                continue
            text = msg.get("text")
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                # Treat unrecognised text as raw stdin — convenient for
                # debugging via `wscat` etc.
                try:
                    os.write(master_fd, text.encode())
                except OSError:
                    return
                continue
            kind = payload.get("type")
            if kind == "resize":
                _set_winsize(
                    master_fd,
                    int(payload.get("rows", 24)),
                    int(payload.get("cols", 80)),
                )
            elif kind == "input":
                try:
                    os.write(master_fd, payload.get("data", "").encode())
                except OSError:
                    return

    try:
        send_task = asyncio.create_task(_send_loop(), name="shell_stream.send")
        recv_task = asyncio.create_task(_recv_loop(), name="shell_stream.recv")
        done, pending = await asyncio.wait(
            {send_task, recv_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
    except Exception:
        logger.exception("shell_stream forwarding loop crashed")
    finally:
        try:
            loop.remove_reader(master_fd)
        except (ValueError, KeyError):
            pass
        # Best-effort kill the child. SIGHUP is the polite first try
        # (lets the shell tear down its job table); SIGKILL if it lingers.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGHUP)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=2)
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                await asyncio.to_thread(proc.wait)
            except Exception:
                pass
        try:
            os.close(master_fd)
        except OSError:
            pass
        if ws.client_state.value != 3:  # 3 == DISCONNECTED
            try:
                await ws.close()
            except Exception:
                pass
        logger.info("Shell stream closed pid=%s", proc.pid)


