"""Build two isolated, repeatable first-filing demonstrations."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from psm import db, filing, services, wizard  # noqa: E402
from psm.enums import WIZARD_SITE_ID  # noqa: E402

OUT = ROOT / "data" / "demo_cases"
CASES = ("hf-incident", "zero-accident-contractors")


def build_case(case: str, *, force: bool = False) -> Path:
    if case not in CASES:
        raise ValueError(case)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{case}.sqlite"
    if path.exists():
        if not force:
            return path
        path.unlink()
    conn = db.connect(path)
    try:
        db.init_schema(conn)
        for step in range(1, 15):
            wizard.apply_step_defaults(conn, WIZARD_SITE_ID, step)
        if case == "zero-accident-contractors":
            conn.execute("DELETE FROM contractor_incident WHERE site_id=?", (WIZARD_SITE_ID,))
            conn.execute("DELETE FROM incident WHERE site_id=?", (WIZARD_SITE_ID,))
            conn.execute(
                "DELETE FROM filing_row WHERE site_id=? AND section='6.1'",
                (WIZARD_SITE_ID,),
            )
            conn.execute(
                "UPDATE site SET site_name='HF 零事故承攬示範場所' WHERE site_id=?",
                (WIZARD_SITE_ID,),
            )
            conn.commit()
            services.save_contractor(conn, {
                "site_id": WIZARD_SITE_ID,
                "name": "永安管線工程有限公司",
                "contract_period": "2025-01-01 至 2025-12-31",
                "work_description": "管線保養與臨時維修",
            })
            filing.set_flag(conn, WIZARD_SITE_ID, "c_no_accident", "1")
            filing.set_flag(conn, WIZARD_SITE_ID, "inc_zero", "1")
            filing.set_flag(conn, WIZARD_SITE_ID, "c_roster_complete", "1")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError(f"{case}: 外鍵檢查失敗")
        if case == "zero-accident-contractors":
            assert conn.execute(
                "SELECT COUNT(*) FROM contractor WHERE site_id=?", (WIZARD_SITE_ID,)
            ).fetchone()[0] >= 2
            assert conn.execute(
                "SELECT COUNT(*) FROM incident WHERE site_id=?", (WIZARD_SITE_ID,)
            ).fetchone()[0] == 0
        else:
            assert conn.execute(
                "SELECT COUNT(*) FROM contractor_incident WHERE site_id=?", (WIZARD_SITE_ID,)
            ).fetchone()[0] >= 1
    finally:
        conn.close()
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="重建固定的兩個示範資料庫")
    args = parser.parse_args()
    for case in CASES:
        print(build_case(case, force=args.force))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
