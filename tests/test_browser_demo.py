"""Exercise the same browser adapter against real routes, isolated fixture copies."""

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlencode

import anyio.to_thread
import httpx
import pytest

from psm import db, web, wizard
from scripts.browser_bridge import BrowserApp, rewrite_html, rewrite_paths

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def browser(tmp_path, monkeypatch):
    # BrowserApp patches these for its single Python runtime. Restore them at
    # teardown so native-server tests keep their normal threadpool and paths.
    monkeypatch.setattr(anyio.to_thread, "run_sync", anyio.to_thread.run_sync)
    for module in (db, web, wizard):
        monkeypatch.setattr(module, "db_path", module.db_path)
    bundle = tmp_path / "bundle"
    (bundle / "seed").mkdir(parents=True)
    for source, target in (
        ("data/demo_cases/hf-incident.sqlite", "hf.sqlite"),
        ("data/demo_cases/petrochemical-complete.sqlite", "petrochemical.sqlite"),
        ("data/psm_demo_hf.sqlite", "demo.sqlite"),
    ):
        shutil.copy2(ROOT / source, bundle / "seed" / target)
    return BrowserApp(bundle, tmp_path / "storage", "/psm-demo/app")


def request(browser, method, path, data=None, files=None):
    if files:
        native = httpx.Request(method, "https://browser.local" + path, data=data, files=files)
        body = native.read()
        headers = list(native.headers.items())
    else:
        body = urlencode(data or {}).encode()
        headers = [["content-type", "application/x-www-form-urlencoded"]]
    return asyncio.run(browser.request(method, path, "", headers, body))


def test_actual_fourteen_chapter_routes_and_case_selection(browser):
    for case, title in (("hf", "HF 密閉供料"), ("petrochemical", "HF 催化烷基化")):
        assert request(browser, "GET", "/wizard/sample/" + case)["status"] == 303
        for chapter in range(1, 15):
            page = request(browser, "GET", f"/wizard/{chapter}")
            assert page["status"] == 200
            assert b"<form" in page["body"]
            assert b'/psm-demo/app/static/wizard.js' in page["body"]
        report = request(browser, "GET", "/report")
        assert report["status"] == 200 and title.encode() in report["body"]
    # Selecting a case is a GET redirect and still has to survive runtime restart.
    reopened = BrowserApp(browser.bundle, browser.storage, browser.prefix)
    assert reopened.cookies["psm_wizard_case"] == "petrochemical"


def test_create_persists_and_restore_only_replaces_current_case(browser):
    before = (browser.storage / "petrochemical.sqlite").read_bytes()
    created = request(browser, "POST", "/wizard/1/dept", {"dept_id": "D-BROWSER", "name": "Browser department", "headcount": "3"})
    assert created["status"] == 303
    reopened = BrowserApp(browser.bundle, browser.storage, browser.prefix)
    assert b"Browser department" in request(reopened, "GET", "/wizard/1")["body"]
    assert request(reopened, "POST", "/__demo/restore")["status"] == 303
    assert b"Browser department" not in request(reopened, "GET", "/wizard/1")["body"]
    assert (browser.storage / "petrochemical.sqlite").read_bytes() == before


def test_file_upload_reuse_and_update_use_real_backend(browser):
    values = {"step": "9", "purpose": "hotwork_procedure", "document_no": "BROWSER-DOC", "title": "Browser upload", "revision_date": "2026-10-19"}
    result = request(browser, "POST", "/wizard/document/create", values,
                     {"file": ("demo.pdf", b"%PDF-1.4\nbrowser upload", "application/pdf")})
    assert result["status"] == 303
    conn = db.connect(browser.storage / "hf.sqlite")
    try:
        doc = conn.execute("SELECT * FROM filing_document WHERE document_no='BROWSER-DOC'").fetchone()
        assert Path(doc["attachment_path"]).read_bytes() == b"%PDF-1.4\nbrowser upload"
        doc_id = doc["document_id"]
    finally:
        conn.close()
    assert request(browser, "POST", "/wizard/document/link", {"step": "10", "purpose": "moc_plan", "document_id": doc_id})["status"] == 303
    result = request(browser, "POST", "/wizard/document/create", {**values, "document_id": doc_id, "title": "Updated browser upload"})
    assert result["status"] == 303
    assert b"Updated browser upload" in request(browser, "GET", "/report")["body"]


def test_partial_requests_return_application_validation(browser):
    response = asyncio.run(browser.request("POST", "/wizard/1/dept", "", [
        ["content-type", "application/x-www-form-urlencoded"], ["x-psm-partial", "1"],
    ], b"dept_id=D-BROWSER&name=Browser&headcount=1"))
    assert response["status"] == 200 and json.loads(response["body"])["ok"]


def test_prefix_rewrites_urls_and_selectors_without_corrupting_user_values():
    page = '''<form action="/wizard/1"><input value="/my value"></form><a href="https://example.org/a">external</a><script>fetch("/wizard/core-status");document.querySelector('form[action="/wizard/1"]')</script><script type="application/json">{"name":"/unchanged"}</script>'''
    rewritten = rewrite_html(page, "/psm-demo/app")
    assert 'action="/psm-demo/app/wizard/1"' in rewritten
    assert 'fetch("/psm-demo/app/wizard/core-status")' in rewritten
    assert 'value="/my value"' in rewritten
    assert '"name":"/unchanged"' in rewritten
    assert 'href="https://example.org/a"' in rewritten
    assert rewrite_paths("'/' '/wizard' '//cdn.example'", "/psm-demo/app") == "'/psm-demo/app/' '/psm-demo/app/wizard' '//cdn.example'"
    assert rewrite_paths('value.replace(/"/g, "x")', "/psm-demo/app") == 'value.replace(/"/g, "x")'
    assert "/psm-demo/app/psm-demo/app" not in rewritten


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for JavaScript syntax verification")
def test_all_rewritten_frontend_scripts_still_parse():
    for path in (ROOT / "psm/static").glob("*.js"):
        script = rewrite_paths(path.read_text(encoding="utf-8"), "/psm-demo/app")
        subprocess.run(["node", "--check"], input=script, encoding="utf-8", check=True, capture_output=True)
