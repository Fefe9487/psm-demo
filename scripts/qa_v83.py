"""Read-only V8.3 QA smoke check against copies of the local demo databases."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from psm import db, filing, wizard  # noqa: E402


def check_copy(source: Path, target: Path) -> list[str]:
    shutil.copy2(source, target)
    conn = db.connect(target)
    problems: list[str] = []
    try:
        db.init_schema(conn)
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            problems.append(f"外鍵錯誤 {len(fk)} 筆")
        legacy = conn.execute(
            "SELECT COUNT(*) FROM filing_row WHERE section='11.2'"
        ).fetchone()[0]
        if legacy:
            problems.append(f"尚有 {legacy} 筆舊版 11.2 事故列未轉入共通事故表")
        for section in ("8.1", "8.2"):
            active_legacy = conn.execute(
                "SELECT COUNT(*) FROM filing_row WHERE section=?", (section,)
            ).fetchone()[0]
            if active_legacy:
                problems.append(f"尚有 {active_legacy} 筆舊版 {section} 列未移入共通來源或封存")
        for row in conn.execute(
            """SELECT d.detail_id,d.equipment_id,s.is_critical FROM mi_inspection_detail d
               LEFT JOIN mi_screen s ON s.equipment_id=d.equipment_id
               WHERE s.equipment_id IS NULL OR s.is_critical<>1"""
        ):
            problems.append(f"8.1 檢查項目 {row['detail_id']} 的設備 {row['equipment_id']} 未判定為安全關鍵")
        for row in conn.execute(
            """SELECT f.equipment_id,s.is_critical FROM mi_failure f
               LEFT JOIN mi_screen s ON s.equipment_id=f.equipment_id
               WHERE s.equipment_id IS NULL OR s.is_critical<>1"""
        ):
            problems.append(f"8.2 設備 {row['equipment_id']} 有失效率但未判定為安全關鍵")
        for row in conn.execute(
            """SELECT c.incident_id, c.site_id, i.site_id AS incident_site
               FROM contractor_incident c LEFT JOIN incident i
                 ON i.incident_id=c.linked_incident_id
               WHERE c.linked_incident_id IS NOT NULL AND c.linked_incident_id<>''"""
        ):
            if row["site_id"] != row["incident_site"]:
                problems.append(f"承攬事故 {row['incident_id']} 引用其他場所或不存在的事故")
        for row in conn.execute(
            """SELECT r.site_id, r.step, d.site_id AS document_site, d.attachment_path
               FROM filing_document_ref r JOIN filing_document d
                 ON d.document_id=r.document_id"""
        ):
            if row["site_id"] != row["document_site"]:
                problems.append(f"第 {row['step']} 章引用其他場所文件")
            if not wizard.has_uploaded_file(row["attachment_path"]):
                problems.append(f"第 {row['step']} 章引用的文件檔案不存在")
        for site in conn.execute("SELECT site_id FROM site ORDER BY site_id"):
            sid = site["site_id"]
            pending = {str(n): wizard.step_missing(conn, sid, n) for n in range(1, 15)}
            print(json.dumps({
                "database": source.name,
                "site_id": sid,
                "completed_chapters": [int(n) for n, gaps in pending.items() if not gaps],
                "pending_chapters": {n: gaps for n, gaps in pending.items() if gaps},
            }, ensure_ascii=False, indent=2))
            for row in filing.list_rows(conn, sid, "2.4"):
                record_id = str(row.get("assessment_id") or "")
                if record_id and not conn.execute(
                    "SELECT 1 FROM pha_record WHERE record_id=? AND site_id=?", (record_id, sid)
                ).fetchone():
                    problems.append(f"{sid} 表2.4-1 引用不存在的評估紀錄 {record_id}")
    finally:
        conn.close()
    return problems


def main() -> int:
    sources = [ROOT / "data" / name for name in ("psm_demo_hf.sqlite", "psm_fill_hf.sqlite")]
    sources.extend(ROOT / "data/demo_cases" / name for name in (
        "hf-incident.sqlite", "zero-accident-contractors.sqlite", "petrochemical-complete.sqlite",
    ))
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="psm-v83-qa-") as tmp:
        for source in sources:
            if not source.is_file():
                failures.append(f"資料庫不存在：{source}")
                continue
            failures.extend(check_copy(source, Path(tmp) / source.name))
    if failures:
        print("\n結構或關聯問題：")
        for item in failures:
            print(f"- {item}")
        return 1
    print("\n資料庫副本外鍵與跨章關聯檢查通過；待補欄位詳見上方清單。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
