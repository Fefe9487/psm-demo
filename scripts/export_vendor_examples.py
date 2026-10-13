"""Export the three teaching cases into a folder an IT vendor can open.

The output is static HTML, CSV, and the sample attachment texts. It does not
change the source databases.
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from psm.db import connect, init_schema  # noqa: E402
from psm.report_v83 import SECTIONS, render_report_v83  # noqa: E402

OUT = ROOT / "交付-資訊廠商"
SITE_ID = "FILL-SITE"

CASES = (
    {
        "folder": "01-石化業HF催化烷基化-全表範例",
        "db": ROOT / "data" / "demo_cases" / "petrochemical-complete.sqlite",
        "why": "主例。進料、反應、分離各有製程與設備，十四章表格有連貫的示範列。",
    },
    {
        "folder": "02-HF密閉供料-含承攬虛驚",
        "db": ROOT / "data" / "demo_cases" / "hf-incident.sqlite",
        "why": "同一套 HF 供料背景，另有一筆承攬虛驚。用來對照事故列如何被承攬管理引用。",
    },
    {
        "folder": "03-HF密閉供料-零事故仍須承攬名冊",
        "db": ROOT / "data" / "demo_cases" / "zero-accident-contractors.sqlite",
        "why": "近五年沒有事故，但仍登錄承攬商。零事故聲明不能拿掉名冊。",
    },
)

SECTION_TITLES = {
    code: title
    for sections in SECTIONS.values()
    for code, title in sections
}
SECTION_TITLES["mix"] = "表1.0-4 配方成分、相態與列管數量"
SECTION_TITLES["6.1"] = "舊式承攬列-正式名冊見主檔"

SKIP_TABLES = {"sqlite_sequence", "app_meta", "filing_row"}


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "；".join(_cell(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def _table_csv(conn: sqlite3.Connection, table: str, dest: Path) -> int:
    info = list(conn.execute(f"PRAGMA table_info({table})"))
    headers = [col[1] for col in info]
    rows = [
        [_cell(value) for value in row]
        for row in conn.execute(f"SELECT * FROM {table}")
    ]
    if not rows:
        return 0
    _write_csv(dest, headers, rows)
    return len(rows)


def _section_csvs(conn: sqlite3.Connection, dest_dir: Path) -> list[tuple[str, str, int]]:
    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    for row in conn.execute(
        "SELECT row_id, section, payload FROM filing_row WHERE site_id=? ORDER BY row_id",
        (SITE_ID,),
    ):
        section = row[1]
        try:
            payload = json.loads(row[2] or "{}")
        except json.JSONDecodeError:
            payload = {"_raw": row[2]}
        item = {"row_id": row[0], **payload}
        if section not in grouped:
            order.append(section)
            grouped[section] = []
        grouped[section].append(item)
    written = []
    for section in order:
        items = grouped[section]
        headers: list[str] = []
        for item in items:
            for key in item:
                if key not in headers:
                    headers.append(key)
        title = SECTION_TITLES.get(section, section)
        safe = title.replace("/", "／").replace("\\", "／")
        path = dest_dir / f"{section}-{safe}.csv"
        _write_csv(
            path,
            headers,
            [[_cell(item.get(key, "")) for key in headers] for item in items],
        )
        written.append((section, title, len(items)))
    return written


def _copy_attachments(conn: sqlite3.Connection, dest_dir: Path) -> list[dict]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    copied = []
    rows = conn.execute(
        """SELECT kind, original_name, attachment_path, note
           FROM unstructured_attachment ORDER BY attachment_id"""
    ).fetchall()
    for kind, original_name, attachment_path, note in rows:
        source = Path(attachment_path) if attachment_path else None
        exists = bool(source and source.is_file())
        saved = ""
        if exists:
            name = original_name or source.name
            stem = Path(name).stem
            suffix = Path(name).suffix or source.suffix
            candidate = f"{stem}{suffix}"
            n = 2
            while candidate in used:
                candidate = f"{stem}-{n}{suffix}"
                n += 1
            used.add(candidate)
            shutil.copy2(source, dest_dir / candidate)
            saved = candidate
        copied.append({
            "kind": kind or "",
            "name": original_name or "",
            "note": note or "",
            "copied": saved,
            "status": "已附上原稿" if saved else "只有檔名或路徑，沒有實體檔",
        })
    if copied:
        _write_csv(
            dest_dir / "附件清單.csv",
            ["kind", "name", "note", "status", "copied"],
            [[item[k] for k in ("kind", "name", "note", "status", "copied")] for item in copied],
        )
    return copied


def export_case(spec: dict) -> dict:
    folder = OUT / spec["folder"]
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    # 匯出前先在複本上補齊目前欄位，不改原本的示範庫。
    scratch = Path(tempfile.mkdtemp(prefix="psm-vendor-"))
    copied = scratch / "case.sqlite"
    shutil.copy2(spec["db"], copied)
    conn = connect(copied)
    init_schema(conn)
    try:
        site = conn.execute(
            "SELECT company_name, site_name, scope FROM site WHERE site_id=?",
            (SITE_ID,),
        ).fetchone()
        (folder / "填報預覽.html").write_text(
            render_report_v83(conn, SITE_ID), encoding="utf-8"
        )
        master_dir = folder / "主檔"
        masters = []
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        for table in tables:
            if table in SKIP_TABLES or table.startswith("sqlite_"):
                continue
            count = _table_csv(conn, table, master_dir / f"{table}.csv")
            if count:
                masters.append((table, count))
        sections = _section_csvs(conn, folder / "填報列")
        attachments = _copy_attachments(conn, folder / "附件")
        return {
            "folder": spec["folder"],
            "why": spec["why"],
            "company": site["company_name"] if site else "",
            "site": site["site_name"] if site else "",
            "scope": site["scope"] if site else "",
            "masters": masters,
            "sections": sections,
            "attachments": attachments,
        }
    finally:
        conn.close()
        shutil.rmtree(scratch, ignore_errors=True)


def _rewrite_local_paths(folder: Path) -> None:
    """把本機絕對路徑改成資料夾內的相對附件，避免把開發機路徑交出去。"""
    attach_dir = folder / "附件"
    attach_dir.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}

    def relocate(value: str) -> str:
        text = value.strip().strip('"')
        if not text or text.startswith("placeholder://") or text.startswith("附件/"):
            return value
        path = Path(text)
        if not path.is_file():
            return value
        resolved = str(path.resolve())
        name = copied.get(resolved)
        if name is None:
            payload = path.read_bytes()
            same = next(
                (
                    child.name for child in attach_dir.iterdir()
                    if child.is_file() and child.name != "附件清單.csv" and child.read_bytes() == payload
                ),
                "",
            )
            name = same or path.name
            stem, suffix = Path(name).stem, Path(name).suffix
            n = 2
            while (attach_dir / name).exists() and (attach_dir / name).read_bytes() != payload:
                name = f"{stem}-{n}{suffix}"
                n += 1
            target = attach_dir / name
            if not target.exists():
                shutil.copy2(path, target)
            copied[resolved] = name
        return f"附件/{name}"

    for csv_path in folder.rglob("*.csv"):
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        if not rows:
            continue
        changed = False
        rewritten = []
        for row in rows:
            new_row = []
            for cell in row:
                updated = relocate(cell)
                if updated != cell:
                    changed = True
                new_row.append(updated)
            rewritten.append(new_row)
        if changed:
            _write_csv(csv_path, rewritten[0], rewritten[1:])

    if not copied:
        return
    listing = attach_dir / "附件清單.csv"
    rows: list[list[str]] = []
    if listing.exists():
        with listing.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
    headers = ["kind", "name", "note", "status", "copied"]
    body = rows[1:] if rows else []
    known = {row[4] for row in body if len(row) > 4}
    for name in copied.values():
        if name not in known:
            body.append(["", name, "由填報列路徑帶出的示範原稿", "已附上原稿", name])
    _write_csv(listing, headers, body)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    summary = [export_case(spec) for spec in CASES]
    for item in summary:
        _rewrite_local_paths(OUT / item["folder"])
    print(OUT)
    for item in summary:
        print(item["folder"], item["site"], "tables", len(item["masters"]), "sections", len(item["sections"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
