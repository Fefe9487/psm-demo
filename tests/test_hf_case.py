"""The published demo and wizard defaults describe one coherent HF filing case."""

import sqlite3

from psm import filing, services, wizard
from psm.db import init_schema
from psm.enums import SITE_ID
from psm.seed import seed_hf_demo


def hf_demo():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_schema(conn)
    seed_hf_demo(conn)
    return conn


def test_hf_demo_phase_gate_and_chapter_links():
    conn = hf_demo()
    try:
        site = conn.execute("SELECT * FROM site WHERE site_id=?", (SITE_ID,)).fetchone()
        assert "氟化氫" in site["scope"]
        assert "甲苯" not in site["scope"]
        chemicals = conn.execute(
            """SELECT c.cas, c.process_id, c.phase_state, c.sds_id
               FROM chemical c JOIN process p ON p.process_id=c.process_id
               WHERE p.site_id=? ORDER BY c.process_id""", (SITE_ID,)
        ).fetchall()
        assert {row["cas"] for row in chemicals} == {"7664-39-3", "1310-73-2"}
        hf_phases = {
            row["process_id"]: row["phase_state"]
            for row in chemicals if row["cas"] == "7664-39-3"
        }
        assert hf_phases == {"P-LOAD": "液態", "P-TANK": "氣態"}
        assert {row["sds_id"] for row in chemicals} == {"SDS-HF-001", "SDS-NAOH-001"}

        mix = {row["process_id"]: row for row in filing.list_rows(conn, SITE_ID, "mix")}
        assert mix["P-TANK"]["counted"] is True
        assert mix["P-TANK"]["exceeds"] is True
        assert int(mix["P-TANK"]["limit_kg"]) == 1000
        assert mix["P-LOAD"]["counted"] is False
        assert "相態不符" in mix["P-LOAD"]["annex_note"]

        for step in range(1, 15):
            missing = wizard.step_missing(conn, SITE_ID, step)
            if step == 1:
                assert any("1.5" in item and "數值" in item for item in missing), missing
                assert any("上傳" in item for item in missing), missing
            elif step in (2, 3, 14):
                assert missing and all("上傳" in item or "文件" in item or "SDS" in item or "圖" in item for item in missing), (step, missing)
            elif 4 <= step <= 13:
                assert wizard.document_gaps(conn, SITE_ID, step), (step, missing)
                if step == 4:
                    assert any("4.4-1" in item for item in missing), missing
                if step == 8:
                    assert any("8.2-1" in item for item in missing), missing
            else:
                assert not missing, (step, missing)
        assert conn.execute("SELECT 1 FROM incident WHERE site_id=?", (SITE_ID,)).fetchone()
        assert conn.execute("SELECT 1 FROM filing_row WHERE site_id=? AND section='13.2'", (SITE_ID,)).fetchone()
        assert conn.execute("SELECT 1 FROM unstructured_attachment WHERE site_id=? AND kind='trade_secret'", (SITE_ID,)).fetchone()
        assert conn.execute("SELECT COUNT(*) FROM node").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM consequence").fetchone()[0] == 2
        report = services.generate_report_html(conn, SITE_ID)
        assert "V8.3 填報預覽" in report
        assert "表1.0-4 配方成分、相態與列管數量" in report
        assert "無水氟化氫（氣態供料）" in report
        assert "無水氟化氫（液態接收）" in report
        assert "相態不符不列入管制量" in report
        assert "HF 供料管線破損" in report
        assert "T-101 材質相容性" in report
        assert "近五年事故 0 件" not in report
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()


def test_hf_wizard_defaults_have_no_legacy_solvent_case():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_schema(conn)
    try:
        for step in range(1, 15):
            wizard.apply_step_defaults(conn, SITE_ID, step)
        visible = " ".join(
            str(value)
            for row in conn.execute("SELECT payload FROM filing_row WHERE site_id=?", (SITE_ID,))
            for value in row
        )
        assert "甲苯" not in visible
        assert "過氧化氫" not in visible
        assert "HF" in visible or "氟化氫" in visible
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()
