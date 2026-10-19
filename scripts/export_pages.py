"""Export curated examples as an inert, portable GitHub Pages site.

Only HTML and an explicit CSS allowlist are published. Database migrations and
report generation run against temporary copies, never the saved examples.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bs4 import BeautifulSoup  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from psm import db  # noqa: E402
from psm.enums import WIZARD_SITE_ID  # noqa: E402
from psm.web import app  # noqa: E402

CASES = {
    "hf": ("HF 密閉供料", "hf-incident.sqlite"),
    "petrochemical": ("石化業 HF 催化烷基化", "petrochemical-complete.sqlite"),
}


def relative(target: str, page: str) -> str:
    return posixpath.relpath(target, posixpath.dirname(page) or ".")


def flow_page(case: str, process: str) -> str:
    # Hashes prevent path traversal and collisions for arbitrary process IDs.
    digest = hashlib.sha256(process.encode()).hexdigest()[:16]
    return f"{case}/flows/{digest}.html"


def link_target(url: str, case: str, processes: list[str]) -> str:
    parsed = urlsplit(url)
    path = parsed.path
    if path == "/":
        return "index.html"
    if path.startswith("/wizard/sample/"):
        sample = path.rsplit("/", 1)[-1]
        if sample in CASES:
            return f"{sample}/wizard/1.html"
    if path in {"/wizard", "/wizard/start", "/demo", "/floor"}:
        return f"{case}/wizard/1.html"
    if path in {"/report", "/report/file"}:
        return f"{case}/report.html"
    if re.fullmatch(r"/wizard/(?:[1-9]|1[0-4])", path):
        process = parse_qs(parsed.query).get("block_process", [""])[0]
        if process:
            if path != "/wizard/1" or process not in processes:
                raise ValueError(f"Unknown flow reference: {url}")
            return flow_page(case, process)
        return f"{case}{path}.html"
    raise ValueError(f"Unexported internal reference: {url}")


def add_link(soup, parent, label: str, target: str):
    anchor = soup.new_tag("a", href=target)
    anchor.string = label
    parent.append(anchor)
    return anchor


def render_flow(soup, case: str, page: str):
    """Replace the JavaScript editor with the saved steps and their references."""
    seed = soup.select_one("#flow-seed")
    editor = soup.select_one("#flow-save")
    if not seed or not editor:
        return
    nodes = [n for n in json.loads(seed.string or "[]") if any(n.get(k) for k in ("name", "equipment_id", "desc"))]
    section = soup.new_tag("div", attrs={"class": "card readonly-flow", "id": "flow-canvas"})
    title = soup.new_tag("h4")
    title.string = "製程步驟與連接"
    section.append(title)
    listing = soup.new_tag("ol")
    for node in nodes:
        item = soup.new_tag("li")
        label = soup.new_tag("strong")
        label.string = f"{node.get('seq', '')}　{node.get('name') or node.get('equipment_id') or '未命名步驟'}"
        item.append(label)
        paragraph = soup.new_tag("p")
        paragraph.string = " · ".join(str(node[k]) for k in ("equipment_id", "desc") if node.get(k))
        item.append(paragraph)
        if node.get("next"):
            item.append(f"接往步驟 {node['next']}")
        elif node.get("next_process_id"):
            add_link(soup, item, f"接往製程 {node['next_process_id']}", relative(flow_page(case, node["next_process_id"]), page) + "#flow-canvas")
        else:
            item.append("流程終點")
        if node.get("branch_from"):
            item.append(f" · 從步驟 {node['branch_from']} 分出")
        listing.append(item)
    section.append(listing)
    if not nodes:
        section.append("此製程尚無已儲存步驟。")
    editor.replace_with(section)
    seed.decompose()


def transform(source: str, case: str, page: str, processes: list[str]) -> str:
    soup = BeautifulSoup(source, "html.parser")
    if not soup.body:
        raise ValueError(f"Missing page body: {page}")
    for tag in soup.select("script, .sidebar-tools, .sample-tools, .data-fold"):
        tag.decompose()
    # The flow seed is needed before scripts are removed, so obtain it anew.
    original = BeautifulSoup(source, "html.parser")
    if original.select_one("#flow-seed") and soup.select_one("#flow-save"):
        soup.select_one("#flow-save").insert_after(original.select_one("#flow-seed"))
        render_flow(soup, case, page)

    for tag in soup.find_all(True):
        # The live UI reveals these panels in JavaScript. Make their stored
        # values inspectable even when the exporter removes that JavaScript.
        if tag.has_attr("data-panel"):
            tag.attrs.pop("hidden", None)
        for key in list(tag.attrs):
            if key.lower().startswith("on") or key.startswith("data-") or key == "contenteditable":
                del tag[key]
    for form in list(soup.select("form")):
        # Flow selection is navigation; pre-render every process, without GET forms.
        if form.get("id") == "flow-load":
            nav = soup.new_tag("nav", attrs={"class": "readonly-processes", "aria-label": "製程流程"})
            for option in form.select("option[value]"):
                add_link(soup, nav, option.get_text(" ", strip=True),
                         relative(flow_page(case, option["value"]), page) + "#flow-canvas")
            form.replace_with(nav)
            continue
        # Preserve existing values and declarations; remove submission semantics.
        form.name = "div"
        for attribute in ("method", "action", "enctype"):
            form.attrs.pop(attribute, None)
        form["class"] = form.get("class", []) + ["readonly-fields"]
    for control in soup.select("input, select, textarea, button"):
        control["disabled"] = ""
    for control in soup.select('input[type="hidden"], button'):
        control.decompose()
    for tag in soup.select("[hidden]"):
        # Keep deliberately hidden editors hidden. Server-rendered tables remain visible.
        if tag.get("id") == "chapter-index":
            tag.attrs.pop("hidden", None)
    for index, heading in enumerate(soup.select(".wizard h3"), 1):
        heading["id"] = heading.get("id") or f"chapter-section-{index}"
        toc = soup.select_one("#chapter-index")
        if toc:
            add_link(soup, toc, heading.get_text(" ", strip=True), "#" + heading["id"])
    for table in soup.select("table"):
        if not table.parent or "table-wrap" in table.parent.get("class", []):
            continue
        wrapper = soup.new_tag("div", attrs={"class": "table-wrap"})
        table.wrap(wrapper)
    for anchor in soup.select("a[href]"):
        value = anchor["href"]
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or value.startswith("#"):
            continue
        # Links created by the exporter are already relative to this page.
        if not value.startswith("/"):
            continue
        anchor["href"] = relative(link_target(value, case, processes), page)
        if parsed.fragment:
            anchor["href"] += "#" + parsed.fragment
        if parsed.path == "/report/file":
            anchor["download"] = f"psm-{case}-report.html"
    for stylesheet in soup.select('link[rel="stylesheet"]'):
        if urlsplit(stylesheet["href"]).path != "/static/style.css":
            raise ValueError(f"Unapproved stylesheet: {stylesheet['href']}")
        stylesheet["href"] = relative("static/style.css", page)
    extra_css = soup.new_tag("link", rel="stylesheet", href=relative("static/readonly.css", page))
    soup.head.append(extra_css)
    banner = soup.new_tag("aside", attrs={"class": "readonly-banner", "aria-label": "唯讀示範"})
    strong = soup.new_tag("strong")
    strong.string = f"唯讀示範｜{CASES[case][0]}"
    banner.append(strong)
    paragraph = soup.new_tag("p")
    paragraph.string = "可瀏覽十四章與範例報告；填寫與儲存請使用本機版。範例數值與文件供教學參考。"
    banner.append(paragraph)
    nav = soup.new_tag("nav", attrs={"aria-label": "範例切換"})
    add_link(soup, nav, "示範首頁", relative("index.html", page))
    step = re.search(r"/wizard/(\d+)\.html$", page)
    for slug, (label, _) in CASES.items():
        target = f"{slug}/wizard/{step.group(1) if step else '1'}.html"
        add_link(soup, nav, label, relative(target, page))
    add_link(soup, nav, "十四章報告", relative(f"{case}/report.html", page))
    banner.append(nav)
    main = soup.select_one("main") or soup.body
    main.insert(0, banner)
    for anchor in soup.select('.sidebar nav a'):
        if anchor.get_text(strip=True) == "繼續精靈":
            anchor.string = "十四章範例"
        if anchor.get_text(strip=True) == "首次填報":
            anchor.string = "示範首頁"
    return str(soup)


def validate_site(output: Path) -> dict:
    """Fail the export on a broken local file, asset, anchor or active form."""
    if not (output / "index.html").is_file():
        raise ValueError(f"Missing site entry point: {output / 'index.html'}")
    pages = sorted(output.rglob("*.html"))
    parsed = {p.resolve(): BeautifulSoup(p.read_text(encoding="utf-8"), "html.parser") for p in pages}
    references = 0
    for page, soup in parsed.items():
        if soup.select("form, script, button, [contenteditable]"):
            raise ValueError(f"Interactive content escaped export: {page}")
        if soup.select("input:not([disabled]), select:not([disabled]), textarea:not([disabled])"):
            raise ValueError(f"Editable control escaped export: {page}")
        for tag in soup.find_all(True):
            if any(key.lower().startswith("on") for key in tag.attrs):
                raise ValueError(f"Inline event handler: {page}")
            for attr in ("href", "src"):
                value = tag.get(attr)
                if not value:
                    continue
                url = urlsplit(value)
                if url.scheme in {"http", "https", "mailto"} or url.netloc:
                    continue
                if url.scheme or value.startswith("/") or url.query:
                    raise ValueError(f"Nonportable reference {page}: {value}")
                target = (page.parent / unquote(url.path)).resolve() if url.path else page
                if not target.is_relative_to(output.resolve()) or not target.is_file():
                    raise ValueError(f"Broken reference {page}: {value}")
                if url.fragment and target in parsed and not parsed[target].find(id=unquote(url.fragment)):
                    raise ValueError(f"Broken anchor {page}: {value}")
                references += 1
    return {"pages": len(pages), "local_references_checked": references}


def export_site(output: Path) -> dict:
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Output must be empty (nothing was deleted): {output}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "static").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "psm/static/style.css", output / "static/style.css")
    shutil.copy2(ROOT / "scripts/pages/readonly.css", output / "static/readonly.css")
    (output / ".nojekyll").touch()
    with tempfile.TemporaryDirectory(prefix="psm-pages-") as temporary:
        for case, (_, database) in CASES.items():
            copy = Path(temporary) / database
            shutil.copy2(ROOT / "data/demo_cases" / database, copy)
            conn = db.connect(copy)
            try:
                db.init_schema(conn)
                if conn.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError(f"Foreign key errors in {database}")
                processes = [r[0] for r in conn.execute("SELECT process_id FROM process WHERE site_id=? ORDER BY process_id", (WIZARD_SITE_ID,))]
            finally:
                conn.close()
            with patch("psm.web.db_path", return_value=copy), TestClient(app) as client:
                client.cookies.set("psm_mode", "wizard")
                client.cookies.set("psm_wizard_case", case)
                routes = [(f"/wizard/{n}", f"{case}/wizard/{n}.html") for n in range(1, 15)]
                routes += [("/wizard/1?" + urlencode({"block_process": process}), flow_page(case, process)) for process in processes]
                routes.append(("/report", f"{case}/report.html"))
                for route, page in routes:
                    response = client.get(route, follow_redirects=False)
                    if response.status_code != 200:
                        raise ValueError(f"{case} {route}: HTTP {response.status_code}")
                    dest = output / page
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(transform(response.text, case, page, processes), encoding="utf-8")
    (output / "index.html").write_text((ROOT / "scripts/pages/index.html").read_text(encoding="utf-8"), encoding="utf-8")
    result = validate_site(output)
    (output / "build-info.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "_site")
    parser.add_argument("--check", action="store_true", help="Validate an existing export without rebuilding")
    args = parser.parse_args()
    result = validate_site(args.output) if args.check else export_site(args.output)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
