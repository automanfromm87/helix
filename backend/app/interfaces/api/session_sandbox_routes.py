"""Sandbox-side session endpoints — split out of session_routes.py.

The big buckets here are:
  * View-only HTTP wrappers around sandbox file/shell snapshots.
  * Two interactive WebSocket proxies (VNC + shell-stream pty).
  * Signed-URL minters the FE uses to open those WS connections from
    the browser without an Authorization header.
  * Preview URL lookup for the iframe.
"""
import asyncio
import logging
from typing import Optional

import websockets
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.application.errors.exceptions import NotFoundError
from app.application.services.agent_service import AgentService
from app.application.services.token_service import TokenService
from app.domain.models.user import User
from app.interfaces.dependencies import (
    get_agent_service,
    get_current_user,
    get_token_service,
    verify_signature_websocket,
)
from app.interfaces.schemas.base import APIResponse
from app.interfaces.schemas.file import (
    FileListRequest,
    FileListResponse,
    FileViewRequest,
    FileViewResponse,
)
from app.interfaces.schemas.resource import AccessTokenRequest, SignedUrlResponse
from app.interfaces.schemas.session import ShellViewRequest, ShellViewResponse


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])


# ---------------------------------------------------------------------------
# View-only HTTP endpoints
# ---------------------------------------------------------------------------


@router.post("/{session_id}/shell")
async def view_shell(
    session_id: str,
    request: ShellViewRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[ShellViewResponse]:
    """One-shot snapshot of a shell session's accumulated output."""
    result = await agent_service.shell_view(session_id, request.session_id, current_user.id)
    return APIResponse.success(result)


@router.post("/{session_id}/file")
async def view_file(
    session_id: str,
    request: FileViewRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[FileViewResponse]:
    result = await agent_service.file_view(session_id, request.file, current_user.id)
    return APIResponse.success(result)


@router.post("/{session_id}/file/list", response_model=APIResponse[FileListResponse])
async def list_dir(
    session_id: str,
    request: FileListRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[FileListResponse]:
    """List one directory level inside the session's sandbox. Used by
    the FE explorer tree — dirs sorted first then alphabetical, with
    `.git` / `node_modules` etc. filtered by default."""
    data = await agent_service.file_list(
        session_id=session_id,
        dir_path=request.path,
        user_id=current_user.id,
        show_hidden=bool(request.show_hidden),
    )
    return APIResponse.success(FileListResponse(**data))


@router.get("/{session_id}/preview", response_model=APIResponse[dict])
async def get_session_preview_url(
    session_id: str,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[dict]:
    """Return the host-side `http://localhost:<port>` URL for the
    session's dev-server preview. Returns `{"url": null}` when no port
    is mapped — FE falls back to a placeholder."""
    session = await agent_service.get_session(session_id, current_user.id)
    if not session:
        raise NotFoundError("Session not found")
    url = await agent_service.get_preview_url(session_id)
    return APIResponse.success({"url": url})


# ---------------------------------------------------------------------------
# Signed-URL minters
# ---------------------------------------------------------------------------
#
# Browsers can't set Authorization on the WebSocket handshake, so the FE
# POSTs here for a short-lived signed URL and opens the WS with that.


@router.post("/{session_id}/vnc/signed-url", response_model=APIResponse[SignedUrlResponse])
async def create_vnc_signed_url(
    session_id: str,
    request_data: AccessTokenRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
    token_service: TokenService = Depends(get_token_service),
) -> APIResponse[SignedUrlResponse]:
    expire_minutes = min(request_data.expire_minutes, 15)
    session = await agent_service.get_session(session_id, current_user.id)
    if not session:
        raise NotFoundError("Session not found")
    ws_base_url = f"/api/v1/sessions/{session_id}/vnc"
    signed_url = token_service.create_signed_url(
        base_url=ws_base_url, expire_minutes=expire_minutes,
    )
    logger.info(
        "Created signed URL for VNC access for user %s, session %s",
        current_user.id, session_id,
    )
    return APIResponse.success(SignedUrlResponse(
        signed_url=signed_url, expires_in=expire_minutes * 60,
    ))


@router.post(
    "/{session_id}/shell/stream/signed-url",
    response_model=APIResponse[SignedUrlResponse],
)
async def create_shell_stream_signed_url(
    session_id: str,
    request_data: AccessTokenRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
    token_service: TokenService = Depends(get_token_service),
) -> APIResponse[SignedUrlResponse]:
    expire_minutes = min(request_data.expire_minutes, 15)
    session = await agent_service.get_session(session_id, current_user.id)
    if not session:
        raise NotFoundError("Session not found")
    ws_base_url = f"/api/v1/sessions/{session_id}/shell/stream"
    signed_url = token_service.create_signed_url(
        base_url=ws_base_url, expire_minutes=expire_minutes,
    )
    logger.info(
        "Created signed shell-stream URL for user %s, session %s",
        current_user.id, session_id,
    )
    return APIResponse.success(SignedUrlResponse(
        signed_url=signed_url, expires_in=expire_minutes * 60,
    ))


# ---------------------------------------------------------------------------
# WebSocket proxies
# ---------------------------------------------------------------------------


@router.websocket("/{session_id}/vnc")
async def vnc_websocket(
    websocket: WebSocket,
    session_id: str,
    signature: str = Depends(verify_signature_websocket),
    agent_service: AgentService = Depends(get_agent_service),
) -> None:
    """Bidirectional binary proxy to the sandbox's VNC WebSocket.
    Authenticated by the signature query param (signed-url scheme)."""
    await websocket.accept(subprotocol="binary")
    logger.info("Accepted WebSocket connection for session %s", session_id)
    try:
        sandbox_ws_url = await agent_service.get_vnc_url(session_id)
        logger.info("Connecting to VNC WebSocket at %s", sandbox_ws_url)
        async with websockets.connect(sandbox_ws_url) as sandbox_ws:
            logger.info("Connected to VNC WebSocket at %s", sandbox_ws_url)

            async def forward_to_sandbox() -> None:
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        await sandbox_ws.send(data)
                except WebSocketDisconnect:
                    logger.info("Web -> VNC connection closed")
                except Exception:
                    logger.exception("Error forwarding data to sandbox")

            async def forward_from_sandbox() -> None:
                try:
                    while True:
                        data = await sandbox_ws.recv()
                        await websocket.send_bytes(data)
                except websockets.exceptions.ConnectionClosed:
                    logger.info("VNC -> Web connection closed")
                except Exception:
                    logger.exception("Error forwarding data from sandbox")

            t1 = asyncio.create_task(forward_to_sandbox(), name="vnc.up")
            t2 = asyncio.create_task(forward_from_sandbox(), name="vnc.down")
            done, pending = await asyncio.wait(
                [t1, t2], return_when=asyncio.FIRST_COMPLETED,
            )
            logger.info("WebSocket connection closed")
            for task in pending:
                task.cancel()
    except ConnectionError:
        logger.exception("Unable to connect to sandbox VNC for %s", session_id)
        await websocket.close(code=1011, reason="Unable to connect to sandbox")
    except Exception:
        logger.exception("VNC WebSocket proxy crashed for %s", session_id)
        await websocket.close(code=1011, reason="proxy error")


@router.websocket("/{session_id}/shell/stream")
async def shell_stream_websocket(
    websocket: WebSocket,
    session_id: str,
    cols: int = 80,
    rows: int = 24,
    cwd: Optional[str] = None,
    signature: str = Depends(verify_signature_websocket),
    agent_service: AgentService = Depends(get_agent_service),
) -> None:
    """Interactive pty shell over WebSocket.

    Wire protocol:
      client → server  binary    raw stdin (xterm.js keystrokes)
      client → server  text      JSON control: {"type":"resize","cols":N,"rows":M}
      server → client  binary    raw pty stdout/stderr
    """
    await websocket.accept()
    logger.info("Accepted shell stream WS for session %s", session_id)
    try:
        sandbox_ws_url = await agent_service.get_shell_stream_url(
            session_id, cols=cols, rows=rows, cwd=cwd,
        )
    except NotFoundError as exc:
        await websocket.close(code=1008, reason=str(exc))
        return
    except Exception:
        logger.exception("shell-stream URL failed for %s", session_id)
        await websocket.close(code=1011, reason="sandbox unavailable")
        return

    try:
        async with websockets.connect(sandbox_ws_url) as sandbox_ws:
            logger.info("Connected to sandbox shell stream %s", sandbox_ws_url)

            async def upstream() -> None:
                # FE → sandbox: forward both binary (stdin) and text
                # (JSON control) frames untouched.
                try:
                    while True:
                        msg = await websocket.receive()
                        mtype = msg.get("type")
                        if mtype == "websocket.disconnect":
                            return
                        if "bytes" in msg and msg["bytes"] is not None:
                            await sandbox_ws.send(msg["bytes"])
                        elif "text" in msg and msg["text"] is not None:
                            await sandbox_ws.send(msg["text"])
                except WebSocketDisconnect:
                    return
                except Exception:
                    logger.warning("shell upstream forward error", exc_info=True)

            async def downstream() -> None:
                try:
                    async for data in sandbox_ws:
                        if isinstance(data, (bytes, bytearray)):
                            await websocket.send_bytes(data)
                        else:
                            await websocket.send_text(data)
                except websockets.exceptions.ConnectionClosed:
                    return
                except Exception:
                    logger.warning("shell downstream forward error", exc_info=True)

            t_up = asyncio.create_task(upstream(), name="shell.upstream")
            t_dn = asyncio.create_task(downstream(), name="shell.downstream")
            done, pending = await asyncio.wait(
                {t_up, t_dn}, return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
    except ConnectionError:
        logger.error("shell-stream sandbox connect failed", exc_info=True)
        try:
            await websocket.close(code=1011, reason="sandbox connection failed")
        except Exception:
            pass
    except Exception:
        logger.error("shell-stream proxy crashed", exc_info=True)
        try:
            await websocket.close(code=1011, reason="proxy error")
        except Exception:
            pass
