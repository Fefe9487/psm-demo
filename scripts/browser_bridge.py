"""Run the unchanged FastAPI application inside one browser's Python runtime.

This adapter has no network server and no shared database. Requests arrive from
the site's service worker and use an IndexedDB-backed filesystem.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import unquote


def rewrite_paths(text: str, prefix: str) -> str:
    # Rewrite DOM attributes, JS URLs and JS attribute selectors together so the
    # original UI selectors continue to match the original event handlers.
    routes = "wizard|static|api|demo|report|site|departments|processes|areas|equipment|chemicals|map|pid|psi|checks|hazop|labor|sop|training|contractor|pssr|mi|hotwork|moc|incident|emergency|audit|secret|floor"
    # A quote inside /"/g is part of a regular expression, not a URL literal.
    # Limit rewriting to real application route prefixes and the root URL.
    return re.sub(r'''(["'])/(?=(?:''' + routes + r''')(?=[/?#"']|$)|["'])''',
                  lambda m: m[1] + prefix + "/", text)


def rewrite_html(text: str, prefix: str) -> str:
    def attribute(match):
        start, value = match.groups()
        return start + (value if value == prefix or value.startswith(prefix + "/") else prefix + value)

    text = re.sub(r'''(\b(?:href|src|action)=["'])(/(?!/)[^"']*)''', attribute, text)
    def script(match):
        opening, source, closing = match.groups()
        if re.search(r'''type=["']application/(?:ld\+)?json''', opening):
            return match[0]
        return opening + rewrite_paths(source, prefix) + closing

    return re.sub(r"(<script\b[^>]*>)(.*?)(</script\s*>)", script, text, flags=re.S | re.I)


class BrowserApp:
    def __init__(self, bundle: Path, storage: Path, prefix: str):
        self.bundle, self.storage, self.prefix = bundle, storage, prefix
        storage.mkdir(parents=True, exist_ok=True)
        self.cookie_path = storage / "cookies.json"
        self.cookies = json.loads(self.cookie_path.read_text()) if self.cookie_path.exists() else {}
        self.cookies.setdefault("psm_mode", "wizard")
        self.cookies.setdefault("psm_wizard_case", "hf")
        for name in ("hf.sqlite", "petrochemical.sqlite", "demo.sqlite"):
            if not (storage / name).exists():
                shutil.copy2(bundle / "seed" / name, storage / name)

        # Emscripten has no native worker threads. Keep sync endpoints and file
        # operations on this service worker's Python event loop instead.
        import anyio.to_thread

        async def inline(function, *args, **options):
            return function(*args)

        anyio.to_thread.run_sync = inline
        from psm import db, web, wizard

        def browser_db_path():
            if db.db_mode.get() != "wizard":
                return storage / "demo.sqlite"
            case = "petrochemical" if db.wizard_case.get() == "petrochemical" else "hf"
            return storage / f"{case}.sqlite"

        db.db_path = web.db_path = wizard.db_path = browser_db_path
        self.app = web.app

    async def request(self, method: str, path: str, query: str, headers: list, body: bytes) -> dict:
        if path == "/__demo/restore" and method == "POST":
            case = self.cookies.get("psm_wizard_case", "hf")
            shutil.copy2(self.bundle / "seed" / f"{case}.sqlite", self.storage / f"{case}.sqlite")
            return {"status": 303, "headers": [["location", self.prefix + "/wizard/1"]], "body": b""}
        incoming = [(key.lower().encode(), value.encode("latin-1")) for key, value in headers
                    if key.lower() not in {"cookie", "host", "content-length"}]
        incoming += [(b"host", b"browser.local"), (b"cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()).encode())]
        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": method, "scheme": "https",
            "path": unquote(path), "raw_path": path.encode(), "query_string": query.encode(),
            "root_path": "", "headers": incoming, "server": ("browser.local", 443),
            "client": ("127.0.0.1", 0),
        }
        received = False
        completed = asyncio.Event()
        result = {"status": 500, "headers": [], "body": bytearray()}

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": body, "more_body": False}
            await completed.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.start":
                result["status"] = message["status"]
                result["headers"] = [[k.decode("latin-1"), v.decode("latin-1")] for k, v in message.get("headers", [])]
            elif message["type"] == "http.response.body":
                result["body"].extend(message.get("body", b""))
                if not message.get("more_body", False):
                    completed.set()

        await self.app(scope, receive, send)
        outgoing = []
        content_type = ""
        for key, value in result["headers"]:
            if key.lower() == "set-cookie":
                cookie = SimpleCookie(value)
                for name, item in cookie.items():
                    self.cookies[name] = item.value
            elif key.lower() not in {"content-length", "content-encoding", "etag"}:
                if key.lower() == "location" and value.startswith("/"):
                    value = self.prefix + value
                outgoing.append([key, value])
            if key.lower() == "content-type":
                content_type = value
        self.cookie_path.write_text(json.dumps(self.cookies), encoding="utf-8")
        content = bytes(result["body"])
        if "text/html" in content_type or "javascript" in content_type:
            text = (rewrite_html if "text/html" in content_type else rewrite_paths)(content.decode("utf-8"), self.prefix)
            if "text/html" in content_type and "<body" in text:
                notice = ('<aside style="padding:12px 18px;background:#e8f1ed;border-bottom:1px solid #b8cec2">'
                          '<strong>互動展示</strong>　可新增、編輯、刪除及上傳；資料儲存在此瀏覽器。'
                          f'<form action="{self.prefix}/__demo/restore" method="post" '
                          'onsubmit="return confirm(\'恢復目前案例的預設資料？此瀏覽器的修改將被取代。\')" style="display:inline">'
                          '<button type="submit" style="margin-left:12px">恢復預設案例</button></form></aside>')
                text = re.sub(r"(<body[^>]*>)", lambda m: m[1] + notice, text, count=1)
            content = text.encode("utf-8")
        return {"status": result["status"], "headers": outgoing, "body": content}


def boot(bundle: str, storage: str, prefix: str):
    return BrowserApp(Path(bundle), Path(storage), prefix)
