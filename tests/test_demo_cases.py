"""Demonstration databases must be isolated and tell different incident stories."""

from psm import db
from psm.enums import WIZARD_SITE_ID
from scripts import build_demo_cases


def test_demonstration_cases_are_reproducible_and_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(build_demo_cases, "OUT", tmp_path)
    incident = build_demo_cases.build_case("hf-incident")
    zero = build_demo_cases.build_case("zero-accident-contractors")
    assert incident != zero
    assert build_demo_cases.build_case("hf-incident") == incident
    for path, expected_incidents in ((incident, 1), (zero, 0)):
        conn = db.connect(path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM incident WHERE site_id=?", (WIZARD_SITE_ID,)).fetchone()[0] == expected_incidents
            assert not conn.execute("PRAGMA foreign_key_check").fetchall()
            if path == zero:
                assert conn.execute("SELECT COUNT(*) FROM contractor WHERE site_id=?", (WIZARD_SITE_ID,)).fetchone()[0] >= 2
                assert conn.execute(
                    "SELECT COUNT(*) FROM filing_row WHERE site_id=? AND section='6.1'",
                    (WIZARD_SITE_ID,),
                ).fetchone()[0] == 0
        finally:
            conn.close()
