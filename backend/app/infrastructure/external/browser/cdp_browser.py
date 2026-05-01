"""CDP-based browser engine — single, resilient, no fallback layers.

Replaces the prior `browser_use_browser` and `playwright_browser` engines.
Designed by porting the patterns proven out in /Users/hebin/oss/browser-agent
(see Manager / Snapshot / Actions split).

Resilience properties:
  * Every CDP send is wrapped in `asyncio.wait_for` — chrome going dark
    surfaces as a clear `TimeoutError` immediately, instead of a silent
    CLOSE_WAIT spin loop. The agent's per-tool timeout then closes the
    loop with a structured ToolResult error.
  * No "reconnect retries" hidden in the implementation. If chrome dies,
    `view_page` / `click` / etc. fail fast and the model can call
    `restart()` to drop+rebuild the connection.
  * Page-stability waits are MutationObserver-based, not fixed sleeps.

Snapshot strategy:
  * Pure CDP — `DOMSnapshot.captureSnapshot` + `Accessibility.getFullAXTree`.
    No `page.evaluate` for snapshotting, so we never inject JS that could
    blur the focused field or mutate page state.
  * Element index → backendNodeId. Indexes are stable for the LIFE of one
    snapshot only; the agent must `view_page()` again after navigation.

Action strategies (mirrors browser-agent reference):
  * click — scrollIntoView + fresh rect + mouse.click → snapshot-rect mouse
    click → CDP `Runtime.callFunctionOn(this.click())`.
  * type — DOM.focus → keyboard.type → native value setter via
    `Runtime.callFunctionOn` so React/Vue controlled inputs sync state.

Connection model: connects to an existing chrome over CDP (sandbox provides
the URL). We never `chromium.launch()` ourselves — chrome's lifecycle is
the sandbox's responsibility.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import (
    async_playwright,
    Browser as PlaywrightBrowser,
    BrowserContext,
    CDPSession,
    Page,
    Playwright,
)

from app.domain.models.tool_result import ToolResult


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Hard cap on every CDP `send`. Keeps us out of CLOSE_WAIT spin loops if the
# upstream chrome dies. Tuned generously so a slow Accessibility tree on
# a heavy page doesn't trip it.
CDP_CALL_TIMEOUT_SECONDS: float = 15.0

# Cap on initial connect / reconnect to chrome.
CONNECT_TIMEOUT_SECONDS: float = 10.0

# Page navigation timeout (Playwright accepts ms here).
NAVIGATION_TIMEOUT_MS: int = 30_000

# Wait-for-stable: declares the DOM settled when there are no mutations for
# `idle_ms` consecutive milliseconds, with `timeout_ms` as a hard cap.
DEFAULT_STABLE_TIMEOUT_MS: int = 3_000
DEFAULT_STABLE_IDLE_MS: int = 200

# Cap on how much page-text we return in a snapshot. Large pages get
# head+tail truncation so the LLM context doesn't balloon.
MAX_TEXT_CONTENT_CHARS: int = 6_000

# Console message ring buffer size (per CDPBrowser instance).
CONSOLE_BUFFER_MAX: int = 200


# ---------------------------------------------------------------------------
# CSS / role constants — used to filter the DOM tree down to what the
# agent can actually interact with.
# ---------------------------------------------------------------------------

IGNORED_TAGS = frozenset({
    "script", "style", "noscript", "meta", "link", "head", "br", "hr",
})

INTERACTIVE_TAGS = frozenset({
    "a", "button", "input", "select", "textarea", "details", "summary",
    "label", "option", "dialog", "menu", "menuitem",
})

EDITABLE_TAGS = frozenset({"input", "textarea", "select"})

INTERACTIVE_ROLES = frozenset({
    "button", "link", "checkbox", "radio", "tab", "menuitem", "option",
    "switch", "slider", "spinbutton", "combobox", "listbox", "searchbox",
    "textbox", "treeitem", "menuitemcheckbox", "menuitemradio",
})

COMPUTED_STYLES: Tuple[str, ...] = (
    "display", "visibility", "opacity", "pointer-events",
)


# ---------------------------------------------------------------------------
# Element model
# ---------------------------------------------------------------------------


@dataclass
class ElementInfo:
    index: int  # 1-based display index, what the model references
    backend_node_id: int  # stable CDP id for actually operating on the node
    tag: str
    role: str
    name: str
    attrs: Dict[str, str]
    input_value: str
    checked: bool
    description: str  # one-line LLM-facing summary
    rect_x: float
    rect_y: float
    rect_w: float
    rect_h: float
    is_clickable: bool
    is_editable: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _cdp(
    session: CDPSession,
    method: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    timeout: float = CDP_CALL_TIMEOUT_SECONDS,
) -> Any:
    """Wrap every CDP send with a hard timeout. If chrome stops responding,
    surface a clear TimeoutError instead of letting the asyncio task hang."""
    try:
        return await asyncio.wait_for(session.send(method, params or {}), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(
            f"CDP {method} timed out after {timeout:.0f}s — chrome may be unresponsive"
        ) from exc


# ---------------------------------------------------------------------------
# Snapshot — pure CDP, no JS injection
# ---------------------------------------------------------------------------


class _SnapshotBuilder:
    """Turns the raw DOMSnapshot + Accessibility tree CDP responses into a
    flat list of ElementInfo + a textual page summary the LLM can read.

    Kept inline (not a public class) because it owns no state beyond the
    two responses passed to the constructor."""

    def __init__(self, dom_snapshot: Dict[str, Any], ax_tree: Dict[str, Any]):
        self._dom = dom_snapshot
        self._strs: List[str] = dom_snapshot.get("strings") or []
        self._ax_by_backend: Dict[int, Dict[str, Any]] = {}
        for n in ax_tree.get("nodes") or []:
            bid = n.get("backendDOMNodeId")
            if bid is not None and not n.get("ignored"):
                self._ax_by_backend[bid] = n

    def build(self) -> Tuple[List[ElementInfo], str]:
        docs = self._dom.get("documents") or []
        if not docs:
            return [], ""
        doc = docs[0]
        elements = self._extract_elements(doc)
        text = self._extract_text(doc)
        return elements, text

    def _str(self, idx: int) -> str:
        if 0 <= idx < len(self._strs):
            return self._strs[idx]
        return ""

    def _extract_elements(self, doc: Dict[str, Any]) -> List[ElementInfo]:
        nodes = doc.get("nodes") or {}
        layout = doc.get("layout") or {}

        node_types: List[int] = nodes.get("nodeType") or []
        node_names: List[int] = nodes.get("nodeName") or []
        backend_ids: List[int] = nodes.get("backendNodeId") or []
        attributes: List[List[int]] = nodes.get("attributes") or []
        clickable_idx = set((nodes.get("isClickable") or {}).get("index") or [])
        checked_idx = set((nodes.get("inputChecked") or {}).get("index") or [])

        # inputValue is encoded as parallel index/value arrays of string-ids.
        input_value_map: Dict[int, str] = {}
        iv = nodes.get("inputValue") or {}
        for ni, vi in zip(iv.get("index") or [], iv.get("value") or []):
            input_value_map[ni] = self._str(vi)

        layout_node_idx: List[int] = layout.get("nodeIndex") or []
        layout_styles: List[List[int]] = layout.get("styles") or []
        layout_bounds: List[List[float]] = layout.get("bounds") or []
        layout_map: Dict[int, int] = {ni: li for li, ni in enumerate(layout_node_idx)}

        out: List[ElementInfo] = []
        display_index = 0

        for ni in range(len(node_types)):
            if node_types[ni] != 1:  # only DOM elements (not text/comment)
                continue
            tag = self._str(node_names[ni]).lower()
            if tag in IGNORED_TAGS:
                continue

            li = layout_map.get(ni)
            if li is None:
                continue
            bounds = layout_bounds[li] if li < len(layout_bounds) else None
            if not bounds or len(bounds) < 4:
                continue
            x, y, w, h = bounds[:4]
            if w < 0.5 or h < 0.5:
                continue

            # Visible-style filter — drop elements whose layout is in the tree
            # but which won't receive a click (display:none can't happen here
            # because layout entries imply rendered; we still filter the rest).
            style_indices = layout_styles[li] if li < len(layout_styles) else None
            if style_indices and len(style_indices) == len(COMPUTED_STYLES):
                display = self._str(style_indices[0])
                visibility = self._str(style_indices[1])
                opacity = self._str(style_indices[2])
                pointer_events = self._str(style_indices[3])
                if (
                    display == "none"
                    or visibility == "hidden"
                    or opacity == "0"
                    or pointer_events == "none"
                ):
                    continue

            # Single pass through attributes — collect role/tabindex/contenteditable
            # signals AND the dict of all attrs in one shot.
            raw_attrs = attributes[ni] if ni < len(attributes) else []
            attrs: Dict[str, str] = {}
            role = ""
            has_tabindex = False
            has_contenteditable = False
            for ai in range(0, len(raw_attrs), 2):
                k = self._str(raw_attrs[ai])
                v = self._str(raw_attrs[ai + 1]) if ai + 1 < len(raw_attrs) else ""
                if not k or k in ("class", "style"):
                    continue
                attrs[k] = v
                if k == "role":
                    role = v
                elif k == "tabindex":
                    has_tabindex = True
                elif k == "contenteditable" and v == "true":
                    has_contenteditable = True

            is_browser_clickable = ni in clickable_idx
            is_interactive_tag = tag in INTERACTIVE_TAGS
            is_interactive_role = role in INTERACTIVE_ROLES
            is_interactive = (
                is_browser_clickable
                or is_interactive_tag
                or is_interactive_role
                or has_tabindex
                or has_contenteditable
            )
            if not is_interactive:
                continue

            backend_id = backend_ids[ni] if ni < len(backend_ids) else 0
            ax = self._ax_by_backend.get(backend_id) or {}
            ax_role = (ax.get("role") or {}).get("value") or role or tag
            ax_name = (ax.get("name") or {}).get("value") or ""

            input_value = input_value_map.get(ni, "")
            checked = ni in checked_idx
            is_editable = tag in EDITABLE_TAGS or has_contenteditable

            description = self._build_description(
                tag, ax_role, ax_name, attrs, input_value, checked,
            )

            display_index += 1
            out.append(ElementInfo(
                index=display_index,
                backend_node_id=backend_id,
                tag=tag,
                role=ax_role,
                name=ax_name,
                attrs=attrs,
                input_value=input_value,
                checked=checked,
                description=description,
                rect_x=float(x), rect_y=float(y),
                rect_w=float(w), rect_h=float(h),
                is_clickable=True,
                is_editable=is_editable,
            ))

        return out

    @staticmethod
    def _build_description(
        tag: str, role: str, name: str,
        attrs: Dict[str, str], value: str, checked: bool,
    ) -> str:
        parts: List[str] = []
        if role and role != tag:
            parts.append(f"[{role}]")
        else:
            parts.append(f"<{tag}>")
        if tag == "input" and attrs.get("type"):
            parts.append(f'type="{attrs["type"]}"')
        if name:
            parts.append(f'"{name[:60]}"')
        if value:
            parts.append(f'value="{value[:40]}"')
        if checked:
            parts.append("[checked]")
        if attrs.get("aria-checked"):
            parts.append(f"aria-checked={attrs['aria-checked']}")
        if attrs.get("aria-selected") == "true":
            parts.append("[selected]")
        ae = attrs.get("aria-expanded")
        if ae is not None and ae != "":
            parts.append(f"aria-expanded={ae}")
        if attrs.get("aria-disabled") == "true":
            parts.append("[disabled]")
        if tag == "a" and attrs.get("href"):
            parts.append(f"→ {attrs['href'][:50]}")
        return " ".join(parts)

    def _extract_text(self, doc: Dict[str, Any]) -> str:
        """Pull the visible text out of `layout.text` (string-ids of laid-out
        text nodes). De-dupes consecutive identical entries and truncates."""
        layout = doc.get("layout") or {}
        text_indices: List[int] = layout.get("text") or []
        parts: List[str] = []
        last = ""
        for ti in text_indices:
            if ti < 0:
                continue
            t = self._str(ti).strip()
            if t and len(t) > 1 and t != last:
                parts.append(t)
                last = t
        joined = "\n".join(parts)
        if len(joined) > MAX_TEXT_CONTENT_CHARS:
            head = MAX_TEXT_CONTENT_CHARS // 2
            tail = MAX_TEXT_CONTENT_CHARS - head
            joined = joined[:head] + "\n... [truncated] ...\n" + joined[-tail:]
        return joined


# ---------------------------------------------------------------------------
# CDPBrowser — the externally-exposed Browser implementation.
# ---------------------------------------------------------------------------


class CDPBrowser:
    """Browser engine that connects to an existing chrome over CDP and
    exposes the `Browser` Protocol expected by `BrowserToolkit`."""

    def __init__(self, cdp_url: str):
        self.cdp_url = cdp_url
        self._lock = asyncio.Lock()
        self._pw: Optional[Playwright] = None
        self._browser: Optional[PlaywrightBrowser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._cdp: Optional[CDPSession] = None
        # Index → ElementInfo from the most recent view() call. Cleared on
        # navigation / cleanup. Not carried across snapshots — the agent
        # must call view_page() again to refresh indexes.
        self._elements: Dict[int, ElementInfo] = {}
        # Console-message ring buffer fed by Playwright's `console` event.
        # Bounded so a chatty page doesn't grow this without limit.
        self._console_buffer: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _ensure(self) -> None:
        """Connect on first use, reconnect after a cleanup. Idempotent."""
        async with self._lock:
            if self._page and not self._page.is_closed() and self._cdp is not None:
                return
            await self._connect_locked()

    async def _connect_locked(self) -> None:
        # Always do a clean slate before reconnecting. Partial-state
        # reconnects accumulate stale CDP sessions and CLOSE_WAIT sockets.
        await self._cleanup_locked()
        try:
            self._pw = await async_playwright().start()
            self._browser = await asyncio.wait_for(
                self._pw.chromium.connect_over_cdp(self.cdp_url),
                timeout=CONNECT_TIMEOUT_SECONDS,
            )
            self._context = self._pick_context(self._browser)
            self._page = await self._pick_or_create_page(self._context)
            self._page.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
            self._page.on("console", self._on_console)
            self._cdp = await self._context.new_cdp_session(self._page)
            await asyncio.gather(
                _cdp(self._cdp, "DOM.enable"),
                _cdp(self._cdp, "DOMSnapshot.enable"),
                _cdp(self._cdp, "Accessibility.enable"),
            )
        except Exception:
            await self._cleanup_locked()
            raise

    @staticmethod
    def _pick_context(browser: PlaywrightBrowser) -> BrowserContext:
        contexts = browser.contexts
        if contexts:
            return contexts[0]
        # CDP-attached chrome should always have a default context. If not,
        # something upstream is wrong — fail loud rather than mask it.
        raise RuntimeError(
            "Connected chrome has no contexts — sandbox not ready or DevTools session lost."
        )

    @staticmethod
    async def _pick_or_create_page(context: BrowserContext) -> Page:
        # Prefer an already-open user-visible tab so the screenshot reflects
        # what the human can see in the VNC stream.
        for page in context.pages:
            try:
                url = page.url
            except Exception:
                continue
            if url and not url.startswith("chrome://") and url != "about:blank":
                return page
        if context.pages:
            return context.pages[0]
        return await context.new_page()

    async def cleanup(self) -> None:
        async with self._lock:
            await self._cleanup_locked()

    async def _cleanup_locked(self) -> None:
        # Detach CDP first so any pending sends drain cleanly. Wrap each
        # step — we tolerate every error here, the goal is to drop refs.
        if self._cdp is not None:
            try:
                await self._cdp.detach()
            except Exception:
                pass
            self._cdp = None
        if self._page is not None:
            try:
                self._page.remove_listener("console", self._on_console)
            except Exception:
                pass
            # Don't close the page — the sandbox owns chrome's tab lifecycle.
            self._page = None
        self._context = None
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None
        self._elements = {}

    # ------------------------------------------------------------------
    # Browser Protocol — public methods
    # ------------------------------------------------------------------

    async def view_page(self) -> ToolResult:
        try:
            await self._ensure()
            elements, text = await self._snapshot()
            self._elements = {e.index: e for e in elements}
            interactive = [f"[{e.index}] {e.description}" for e in elements]
            return ToolResult(success=True, data={
                "url": self._page.url if self._page else "",
                "title": await self._safe_title(),
                "interactive_elements": interactive,
                "content": text,
            })
        except Exception as exc:
            return self._fail("view_page", exc)

    async def navigate(self, url: str) -> ToolResult:
        try:
            await self._ensure()
            await self._page.goto(url, wait_until="domcontentloaded")
            await self._wait_for_stable()
            elements, _text = await self._snapshot()
            self._elements = {e.index: e for e in elements}
            return ToolResult(success=True, data={
                "url": self._page.url,
                "interactive_elements": [
                    f"[{e.index}] {e.description}" for e in elements
                ],
            })
        except Exception as exc:
            return self._fail("navigate", exc)

    async def restart(self, url: str) -> ToolResult:
        await self.cleanup()
        return await self.navigate(url)

    async def click(
        self,
        index: Optional[int] = None,
        coordinate_x: Optional[float] = None,
        coordinate_y: Optional[float] = None,
    ) -> ToolResult:
        try:
            await self._ensure()
            if coordinate_x is not None and coordinate_y is not None:
                await self._page.mouse.click(coordinate_x, coordinate_y)
                await self._wait_for_stable()
                return ToolResult(success=True)
            if index is None:
                return ToolResult(
                    success=False,
                    message="click requires either `index` or `coordinate_x`/`coordinate_y`.",
                )
            element = self._elements.get(index)
            if element is None:
                return ToolResult(
                    success=False,
                    message=f"No element at [{index}]; call view_page() to refresh indexes.",
                )
            return await self._click_element(element)
        except Exception as exc:
            return self._fail("click", exc)

    async def input(
        self,
        text: str,
        press_enter: bool,
        index: Optional[int] = None,
        coordinate_x: Optional[float] = None,
        coordinate_y: Optional[float] = None,
    ) -> ToolResult:
        try:
            await self._ensure()
            if coordinate_x is not None and coordinate_y is not None:
                # Coordinate-based: click to focus, then plain keyboard typing.
                # No native-setter sync available without a DOM handle.
                await self._page.mouse.click(coordinate_x, coordinate_y)
                await self._page.wait_for_timeout(80)
                await self._page.keyboard.press("Control+a")
                await self._page.keyboard.type(text, delay=10)
            elif index is not None:
                element = self._elements.get(index)
                if element is None:
                    return ToolResult(
                        success=False,
                        message=f"No element at [{index}]; call view_page() to refresh.",
                    )
                if not element.is_editable:
                    return ToolResult(
                        success=False,
                        message=f"Element [{index}] is not editable: {element.description}",
                    )
                await self._type_into_element(element, text)
            else:
                return ToolResult(
                    success=False,
                    message="input requires either `index` or coordinates.",
                )

            if press_enter:
                await self._page.keyboard.press("Enter")
                await self._wait_for_stable()
            return ToolResult(success=True)
        except Exception as exc:
            return self._fail("input", exc)

    async def move_mouse(self, coordinate_x: float, coordinate_y: float) -> ToolResult:
        try:
            await self._ensure()
            await self._page.mouse.move(coordinate_x, coordinate_y)
            return ToolResult(success=True)
        except Exception as exc:
            return self._fail("move_mouse", exc)

    async def press_key(self, key: str) -> ToolResult:
        try:
            await self._ensure()
            await self._page.keyboard.press(key)
            await self._wait_for_stable()
            return ToolResult(success=True)
        except Exception as exc:
            return self._fail("press_key", exc)

    async def select_option(self, index: int, option: int) -> ToolResult:
        try:
            await self._ensure()
            element = self._elements.get(index)
            if element is None:
                return ToolResult(
                    success=False,
                    message=f"No element at [{index}]; call view_page() to refresh.",
                )
            if element.tag != "select":
                return ToolResult(
                    success=False,
                    message=f"Element [{index}] is <{element.tag}>, not a <select>.",
                )
            object_id = await self._resolve_node(element.backend_node_id)
            await _cdp(self._cdp, "Runtime.callFunctionOn", {
                "objectId": object_id,
                "functionDeclaration": (
                    "function(idx){"
                    "  if (idx < 0 || idx >= this.options.length)"
                    "    throw new Error('select option index out of range');"
                    "  this.selectedIndex = idx;"
                    "  this.dispatchEvent(new Event('input', {bubbles: true}));"
                    "  this.dispatchEvent(new Event('change', {bubbles: true}));"
                    "}"
                ),
                "arguments": [{"value": int(option)}],
                "returnByValue": True,
            })
            await self._wait_for_stable()
            return ToolResult(success=True)
        except Exception as exc:
            return self._fail("select_option", exc)

    async def scroll_up(self, to_top: Optional[bool] = None) -> ToolResult:
        return await self._scroll(direction=-1, to_extreme=bool(to_top))

    async def scroll_down(self, to_bottom: Optional[bool] = None) -> ToolResult:
        return await self._scroll(direction=+1, to_extreme=bool(to_bottom))

    async def _scroll(self, direction: int, to_extreme: bool) -> ToolResult:
        try:
            await self._ensure()
            if to_extreme:
                target = "0" if direction < 0 else "document.body.scrollHeight"
                await self._page.evaluate(f"window.scrollTo(0, {target})")
            else:
                # 0.85 of viewport height keeps a slim overlap so the model
                # can re-acquire visual context across scrolls.
                await self._page.evaluate(
                    f"window.scrollBy(0, {direction} * window.innerHeight * 0.85)"
                )
            await self._wait_for_stable()
            return ToolResult(success=True)
        except Exception as exc:
            return self._fail("scroll", exc)

    async def screenshot(self, full_page: Optional[bool] = False) -> bytes:
        await self._ensure()
        return await self._page.screenshot(
            type="jpeg", quality=70, full_page=bool(full_page),
        )

    async def console_exec(self, javascript: str) -> ToolResult:
        try:
            await self._ensure()
            js = javascript.strip()
            # Wrap bare statements in an IIFE so things like `let x = ...;
            # x.toString()` work. Already-an-expression and explicit IIFEs
            # are detected and left alone.
            if js.startswith("(") or js.startswith("function") or js.startswith("()"):
                wrapped = js
            else:
                wrapped = f"(()=>{{ {js} }})()"
            result = await self._page.evaluate(wrapped)
            return ToolResult(success=True, data={"result": result})
        except Exception as exc:
            return self._fail("console_exec", exc)

    async def console_view(self, max_lines: Optional[int] = None) -> ToolResult:
        try:
            await self._ensure()
            entries = list(self._console_buffer)
            if max_lines is not None:
                entries = entries[-int(max_lines):]
            return ToolResult(success=True, data={"logs": entries})
        except Exception as exc:
            return self._fail("console_view", exc)

    # ------------------------------------------------------------------
    # Internal mechanics
    # ------------------------------------------------------------------

    def _on_console(self, msg) -> None:
        """Playwright `console` event handler. Feeds the ring buffer.

        Listener is sync — keep it minimal. Any exception here is swallowed;
        a broken console listener should never break browser ops."""
        try:
            entry = {"type": msg.type, "text": msg.text}
            self._console_buffer.append(entry)
            if len(self._console_buffer) > CONSOLE_BUFFER_MAX:
                self._console_buffer = self._console_buffer[-CONSOLE_BUFFER_MAX:]
        except Exception:
            pass

    async def _safe_title(self) -> str:
        try:
            return await self._page.title()
        except Exception:
            return ""

    async def _snapshot(self) -> Tuple[List[ElementInfo], str]:
        """Capture DOMSnapshot + AXTree in parallel, build ElementInfo list."""
        dom_snapshot, ax_tree = await asyncio.gather(
            _cdp(self._cdp, "DOMSnapshot.captureSnapshot", {
                "computedStyles": list(COMPUTED_STYLES),
                "includeDOMRects": True,
            }),
            _cdp(self._cdp, "Accessibility.getFullAXTree", {}),
        )
        return _SnapshotBuilder(dom_snapshot, ax_tree).build()

    async def _resolve_node(self, backend_node_id: int) -> str:
        result = await _cdp(self._cdp, "DOM.resolveNode", {
            "backendNodeId": backend_node_id,
        })
        return result["object"]["objectId"]

    async def _get_fresh_rect(self, backend_node_id: int) -> Optional[Dict[str, float]]:
        """Scroll the element into view, then read its current bounding rect.
        Returns None if the element no longer exists or is invisible."""
        try:
            await _cdp(self._cdp, "DOM.scrollIntoViewIfNeeded", {
                "backendNodeId": backend_node_id,
            })
            object_id = await self._resolve_node(backend_node_id)
            res = await _cdp(self._cdp, "Runtime.callFunctionOn", {
                "objectId": object_id,
                "functionDeclaration": (
                    "function(){"
                    "  const r = this.getBoundingClientRect();"
                    "  return {x: r.x, y: r.y, width: r.width, height: r.height};"
                    "}"
                ),
                "returnByValue": True,
            })
            value = (res or {}).get("result", {}).get("value")
            if value and value.get("width", 0) > 0 and value.get("height", 0) > 0:
                return value
        except Exception:
            return None
        return None

    async def _click_element(self, element: ElementInfo) -> ToolResult:
        """Three-strategy click — give the framework every chance to receive
        a real synthetic event before falling back to programmatic click."""
        url_before = self._page.url
        # Strategy 1: scroll into view + fresh rect + mouse click. Triggers
        # full hover/focus/click sequence so React onClick handlers fire.
        rect = await self._get_fresh_rect(element.backend_node_id)
        if rect:
            cx = rect["x"] + rect["width"] / 2
            cy = rect["y"] + rect["height"] / 2
            try:
                await self._page.mouse.click(cx, cy)
                await self._wait_for_stable()
                return self._click_postprocess(element, url_before)
            except Exception:
                pass
        # Strategy 2: snapshot rect (may be stale but often correct).
        try:
            cx = element.rect_x + element.rect_w / 2
            cy = element.rect_y + element.rect_h / 2
            await self._page.mouse.click(cx, cy)
            await self._wait_for_stable()
            return self._click_postprocess(
                element, url_before, suffix=" (via snapshot coords)",
            )
        except Exception:
            pass
        # Strategy 3: programmatic click via CDP. Last-resort — won't trigger
        # framework synthetic events for `onClick`-only handlers.
        try:
            object_id = await self._resolve_node(element.backend_node_id)
            await _cdp(self._cdp, "Runtime.callFunctionOn", {
                "objectId": object_id,
                "functionDeclaration": "function(){ this.click(); }",
                "returnByValue": True,
            })
            await self._wait_for_stable()
            return self._click_postprocess(element, url_before, suffix=" (via CDP)")
        except Exception as exc:
            return ToolResult(
                success=False,
                message=f"All click strategies failed for [{element.index}]: {exc}",
            )

    def _click_postprocess(
        self, element: ElementInfo, url_before: str, suffix: str = "",
    ) -> ToolResult:
        """Build the success message, noting if we navigated as a side-effect
        (helps the model reason about whether to call view_page next)."""
        navigated = self._page.url != url_before
        msg = f"Clicked [{element.index}] {element.description}{suffix}"
        if navigated:
            msg += f"; navigated → {self._page.url}"
        return ToolResult(success=True, message=msg)

    async def _type_into_element(self, element: ElementInfo, text: str) -> None:
        """Focus the element, type via keyboard, then sync the value back to
        any framework-controlled state via the native value setter.

        The native-setter step is critical for React/Vue controlled inputs:
        keyboard typing alone updates the DOM, but the framework's onChange
        only fires when the *prototype* setter runs. Without this step the
        UI looks correct visually but the form state never updates."""
        focused = False
        try:
            await _cdp(self._cdp, "DOM.focus", {"backendNodeId": element.backend_node_id})
            focused = True
        except Exception:
            pass

        if not focused:
            rect = await self._get_fresh_rect(element.backend_node_id)
            if rect:
                cx = rect["x"] + rect["width"] / 2
                cy = rect["y"] + rect["height"] / 2
                await self._page.mouse.click(cx, cy)
                await self._page.wait_for_timeout(60)

        # Select-all + type clears existing content and lets a human watching
        # the VNC stream see the agent typing in real time.
        await self._page.keyboard.press("Control+a")
        await self._page.keyboard.type(text, delay=10)

        # Native value setter — guarantees React/Vue see the new value.
        try:
            object_id = await self._resolve_node(element.backend_node_id)
            await _cdp(self._cdp, "Runtime.callFunctionOn", {
                "objectId": object_id,
                "functionDeclaration": (
                    "function(text){"
                    "  var proto = this.nodeName === 'TEXTAREA'"
                    "    ? HTMLTextAreaElement.prototype"
                    "    : HTMLInputElement.prototype;"
                    "  var setter = Object.getOwnPropertyDescriptor(proto, 'value');"
                    "  if (setter && setter.set) setter.set.call(this, text);"
                    "  this.dispatchEvent(new Event('input', {bubbles: true}));"
                    "  this.dispatchEvent(new Event('change', {bubbles: true}));"
                    "}"
                ),
                "arguments": [{"value": text}],
                "returnByValue": True,
            })
        except Exception:
            # If the native-setter sync fails the keyboard typing already
            # deposited characters — we let the action succeed and rely on
            # the agent's next view_page() to detect any divergence.
            pass

        await self._wait_for_stable()

    async def _wait_for_stable(
        self,
        timeout_ms: int = DEFAULT_STABLE_TIMEOUT_MS,
        idle_ms: int = DEFAULT_STABLE_IDLE_MS,
    ) -> None:
        """MutationObserver-based DOM-idle wait. Resolves as soon as the DOM
        sees no mutations for `idle_ms`, with `timeout_ms` as a hard ceiling.

        Falls back to a 300ms fixed wait when `evaluate` fails (typically
        because the page is mid-navigation and the evaluation context was
        torn down — we don't want this to be fatal)."""
        try:
            await self._page.evaluate(
                """({timeout, idleMs}) => new Promise((resolve) => {
                    if (!document.body) { resolve(); return; }
                    let timer = null;
                    let done = false;
                    const finish = () => {
                        if (done) return;
                        done = true;
                        observer.disconnect();
                        resolve();
                    };
                    const observer = new MutationObserver(() => {
                        if (timer) clearTimeout(timer);
                        timer = setTimeout(finish, idleMs);
                    });
                    observer.observe(document.body, {
                        childList: true,
                        subtree: true,
                        attributes: false,
                    });
                    timer = setTimeout(finish, idleMs);
                    setTimeout(finish, timeout);
                })""",
                {"timeout": timeout_ms, "idleMs": idle_ms},
            )
        except Exception:
            try:
                await self._page.wait_for_timeout(300)
            except Exception:
                pass

    @staticmethod
    def _fail(op: str, exc: Exception) -> ToolResult:
        msg = f"{op} failed: {type(exc).__name__}: {exc}"
        logger.warning(msg)
        return ToolResult(success=False, message=msg)
