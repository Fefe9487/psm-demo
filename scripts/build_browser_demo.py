"""Package the real FastAPI app plus a pinned, self-hosted browser Python runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CDN = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/"
WHEELS = {"fastapi": "0.115.12", "starlette": "0.46.2", "python-multipart": "0.0.20", "jinja2": "3.1.6"}


def download(url: str, target: Path, checksum: str | None = None):
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=60) as response:
            target.write_bytes(response.read())
    if checksum and hashlib.sha256(target.read_bytes()).hexdigest() != checksum:
        raise ValueError(f"Checksum mismatch: {target}")


def build(output: Path, cache: Path, base_path: str = "/psm-demo/"):
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Output must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    vendor = cache / "pyodide"
    for name in ("pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"):
        download(CDN + name, vendor / name)
    lock = json.loads((vendor / "pyodide-lock.json").read_text(encoding="utf-8"))
    visited = set()

    def package(name):
        name = name.lower().replace("_", "-")
        if name in visited:
            return
        visited.add(name)
        entry = lock["packages"][name]
        download(CDN + entry["file_name"], vendor / entry["file_name"], entry["sha256"])
        for dependency in entry["depends"]:
            package(dependency)

    for name in ("pydantic", "anyio", "sqlite3", "markupsafe", "micropip"):
        package(name)
    shutil.copytree(vendor, output / "vendor/pyodide")
    wheels = []
    for name, version in WHEELS.items():
        with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as response:
            release = json.load(response)
        wheel = next(item for item in release["urls"] if item["filename"].endswith("py3-none-any.whl"))
        cached = cache / "wheels" / wheel["filename"]
        download(wheel["url"], cached, wheel["digests"]["sha256"])
        dest = output / "vendor/wheels" / cached.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cached, dest)
        wheels.append(dest.relative_to(output).as_posix())
    (output / "wheels.json").write_text(json.dumps(wheels), encoding="utf-8")
    with zipfile.ZipFile(output / "application.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((ROOT / "psm").rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo"):
                archive.write(path, path.relative_to(ROOT).as_posix())
        archive.write(ROOT / "scripts/browser_bridge.py", "browser_bridge.py")
        for source, name in (
            ("data/demo_cases/hf-incident.sqlite", "hf.sqlite"),
            ("data/demo_cases/petrochemical-complete.sqlite", "petrochemical.sqlite"),
            ("data/psm_demo_hf.sqlite", "demo.sqlite"),
        ):
            archive.write(ROOT / source, "seed/" + name)
    for name in ("sw.js", "start.js", "update.js", "interactive.html", "interactive.css"):
        dest_name = "index.html" if name == "interactive.html" else name
        shutil.copy2(ROOT / "scripts/pages" / name, output / dest_name)
    digest = hashlib.sha256((output / "application.zip").read_bytes()).hexdigest()
    version_hash = hashlib.sha256(digest.encode())
    for name in ("sw.js", "start.js", "update.js", "interactive.html", "interactive.css"):
        version_hash.update((ROOT / "scripts/pages" / name).read_bytes())
    build_id = version_hash.hexdigest()
    source_commit = os.environ.get("GITHUB_SHA") or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    (output / "version.json").write_text(json.dumps({
        "source_commit": source_commit, "application_sha256": digest, "build_id": build_id,
    }, indent=2) + "\n", encoding="utf-8")
    worker = output / "sw.js"
    worker.write_text(worker.read_text(encoding="utf-8").replace("__PSM_APP_SHA256__", digest).replace("__PSM_BUILD_ID__", build_id), encoding="utf-8")
    home = output / "index.html"
    html = home.read_text(encoding="utf-8").replace('./start.js"', f'./start.js?v={build_id}"')
    html = html.replace("<head>", f'<head><meta name="psm-build" content="{build_id}">', 1)
    home.write_text(html.replace('./interactive.css"', f'./interactive.css?v={build_id}"'), encoding="utf-8")
    # A fresh visit to a deep link reaches GitHub's 404 page before a service
    # worker is installed. Boot at the real root, then resume that local route.
    fallback = '<!doctype html><meta charset="utf-8"><title>載入 PSM 互動展示</title><p>正在載入互動展示…</p><script>location.replace(' + json.dumps(base_path) + ' + "?v=' + build_id + '&next=" + encodeURIComponent(location.pathname + location.search + location.hash));</script>'
    (output / "404.html").write_text(fallback, encoding="utf-8")
    (output / "THIRD_PARTY.md").write_text(
        "Browser runtime: Pyodide 0.27.7 (MPL-2.0), https://github.com/pyodide/pyodide/tree/0.27.7\n"
        "Python packages are distributed as original wheels with their embedded license notices.\n"
        "Runtime files are unmodified, downloaded from the official Pyodide jsDelivr distribution.\n",
        encoding="utf-8",
    )
    (output / ".nojekyll").touch()
    size = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
    print(json.dumps({"output": str(output), "bytes": size, "pyodide": "0.27.7", "runtime_packages": sorted(visited)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "_site-interactive")
    parser.add_argument("--cache", type=Path, default=ROOT / ".browser-cache")
    parser.add_argument("--base-path", default="/psm-demo/", help="GitHub project path used for first-visit deep-link recovery")
    args = parser.parse_args()
    build(args.output.resolve(), args.cache.resolve(), args.base_path)
