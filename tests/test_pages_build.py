"""Published bundles must contain current code and invalidate an older worker."""

import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path

from scripts import build_browser_demo as pages


def test_pages_bundle_versions_follow_application_changes(tmp_path, monkeypatch):
    root = tmp_path / "source"
    (root / "psm/data").mkdir(parents=True)
    (root / "psm/templates").mkdir()
    (root / "psm/__pycache__").mkdir()
    (root / "psm/__pycache__/stale.pyc").write_bytes(b"stale")
    (root / "psm/data/damage_mechanisms.json").write_text('{"items":["new mechanism"]}')
    template = root / "psm/templates/mi.html"
    template.write_text("Original inspection form")
    scripts = root / "scripts"
    shutil.copytree(pages.ROOT / "scripts/pages", scripts / "pages")
    shutil.copy2(pages.ROOT / "scripts/browser_bridge.py", scripts / "browser_bridge.py")
    for relative in ("data/demo_cases/hf-incident.sqlite", "data/demo_cases/petrochemical-complete.sqlite", "data/psm_demo_hf.sqlite"):
        seed = root / relative
        seed.parent.mkdir(parents=True, exist_ok=True)
        seed.write_bytes(b"fixture database")
    monkeypatch.setattr(pages, "ROOT", root)
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    lock = {"packages": {name: {"file_name": name + ".whl", "sha256": "fixture", "depends": []}
                         for name in ("pydantic", "anyio", "sqlite3", "markupsafe", "micropip")}}

    def download(url, target, checksum=None):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(json.dumps(lock).encode() if target.name == "pyodide-lock.json" else b"fixture runtime")

    def release(url, timeout):
        name = url.split("/")[-3]
        return io.BytesIO(json.dumps({"urls": [{"filename": name + "-test-py3-none-any.whl",
                                               "url": "https://fixture.test/wheel", "digests": {"sha256": "fixture"}}]}).encode())

    monkeypatch.setattr(pages, "download", download)
    monkeypatch.setattr(pages.urllib.request, "urlopen", release)
    first, second = tmp_path / "first", tmp_path / "second"
    pages.build(first, tmp_path / "cache")
    template.write_text("Updated multi-material inspection form")
    pages.build(second, tmp_path / "cache")
    versions = [json.loads((output / "version.json").read_text()) for output in (first, second)]
    assert versions[0]["application_sha256"] != versions[1]["application_sha256"]
    for output, version in zip((first, second), versions):
        digest = hashlib.sha256((output / "application.zip").read_bytes()).hexdigest()
        assert version["source_commit"] == "a" * 40 and version["application_sha256"] == digest
        build_id = version["build_id"]
        assert digest in (output / "sw.js").read_text(encoding="utf-8")
        assert build_id in (output / "sw.js").read_text(encoding="utf-8")
        assert "__PSM_APP_SHA256__" not in (output / "sw.js").read_text(encoding="utf-8")
        assert "start.js?v=" + build_id in (output / "index.html").read_text(encoding="utf-8")
        assert 'name="psm-build" content="' + build_id in (output / "index.html").read_text(encoding="utf-8")
        assert (output / "update.js").is_file()
        assert "/psm-demo/" in (output / "404.html").read_text(encoding="utf-8")
    with zipfile.ZipFile(second / "application.zip") as bundle:
        assert bundle.read("psm/templates/mi.html") == b"Updated multi-material inspection form"
        assert "psm/data/damage_mechanisms.json" in bundle.namelist()
        assert all("__pycache__" not in name for name in bundle.namelist())
    # Bootstrap-only fixes must also invalidate clients, even if Python is unchanged.
    updater = scripts / "pages/update.js"
    updater.write_text(updater.read_text(encoding="utf-8") + "\n// changed bootstrap\n", encoding="utf-8")
    third = tmp_path / "third"
    pages.build(third, tmp_path / "cache")
    latest = json.loads((third / "version.json").read_text())
    assert latest["application_sha256"] == versions[1]["application_sha256"]
    assert latest["build_id"] != versions[1]["build_id"]
