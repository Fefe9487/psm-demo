"""PSI quantity decisions must distinguish phase, aqueous form and legal thresholds."""
import pytest

from psm import filing as fil
from psm.db import connect, init_schema
from psm.enums import WIZARD_SITE_ID
from psm.report_v83 import render_report_v83
from tests.test_wizard import _client, _walk


@pytest.mark.parametrize("cas,limit", [("7647-01-0", 5000), ("7664-39-3", 1000)])
def test_hcl_hf_phase_and_aqueous_decisions(cas, limit):
    def check(**kwargs):
        return fil.annex_qty_check(cas=cas, op_kg=str(limit * 2), wt_pct="100", **kwargs)

    gas = check(phase="氣態", is_aqueous=False)
    assert gas["counted"] and gas["exceeds"] and not gas["needs_review"]
    aqueous = check(phase="液態", is_aqueous=True)
    assert not aqueous["counted"] and not aqueous["needs_review"]
    for kwargs in ({"phase": "液態", "is_aqueous": False}, {"phase": "液態"}, {},
                   {"phase": "氣態", "is_aqueous": True}):
        result = check(**kwargs)
        assert result["needs_review"] and not result["counted"]
        assert "待確認" in result["note"]
        assert "未達" not in result["note"]


def test_legacy_inferred_aqueous_flag_does_not_exclude_liquid_hf():
    row = fil.attach_annex_check({
        "cas": "7664-39-3", "total_kg": "2000", "pct_hi": "100",
        "phase_state": "液態", "is_aqueous": "1",
    })
    assert row["needs_review"]
    assert "不列入甲類" not in row["annex_note"]
    merged = fil.merge_annex_qty([row])
    assert merged["7664-39-3"]["needs_review"]


def test_incomplete_same_cas_sum_preserves_known_exceedance_and_pending():
    rows = [
        {"cas": "7664-39-3", "phase_state": "氣態", "total_kg": "1200", "pct_hi": "100"},
        {"cas": "7664-39-3", "phase_state": "液態", "total_kg": "2000", "pct_hi": "100"},
    ]
    merged = fil.merge_annex_qty(rows)["7664-39-3"]
    assert merged["pure_kg"] == 1200
    assert merged["exceeds"] and merged["needs_review"]


@pytest.mark.parametrize("quantity,percent", [("10 L", "50"), ("NaN", "50"), ("100", "101"), ("100", "")])
def test_non_kg_and_invalid_quantities_cannot_be_treated_as_below_threshold(quantity, percent):
    row = fil.attach_annex_check({"cas": "7722-84-1", "total_kg": quantity, "pct_hi": percent})
    assert row["needs_review"] and not row["counted"]


def test_zero_kg_is_a_valid_known_quantity():
    row = fil.attach_annex_check({"cas": "7722-84-1", "total_kg": 0, "pct_hi": "100"})
    assert row["counted"] and not row["needs_review"] and row["pure_kg"] == "0"


def test_existing_database_adds_unknown_aqueous_status_idempotently():
    with connect(":memory:") as conn:
        init_schema(conn)
        conn.execute("ALTER TABLE chemical DROP COLUMN aqueous_status")
        init_schema(conn)
        init_schema(conn)
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(chemical)")]
        assert columns.count("aqueous_status") == 1
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


def test_same_cas_different_sds_preserves_gas_and_aqueous_components(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "multi-sds.sqlite")
    _walk(client, 1)
    gas = client.post("/wizard/1/chemical", data={
        "kind": "純物質", "cas": "7647-01-0", "name": "氯化氫", "process_id": "P-TANK",
        "file_name": "hcl-gas-qa.pdf", "h_codes": "H314,H331", "role": "原物料",
        "phase_state": "氣態", "aqueous_status": "0", "attributed_qty": "6000",
    }, follow_redirects=True)
    assert "err=" not in str(gas.url)
    aqueous = client.post("/wizard/1/chemical", data={
        "kind": "混合物", "process_id": "P-TANK", "mix_name": "鹽酸試填",
        "file_name": "hcl-aq-qa.pdf", "total_kg": "40000", "comp_cas": "7647-01-0",
        "comp_name": "氯化氫", "comp_role": "原物料", "comp_h": "H314,H331",
        "comp_phase": "液態", "comp_aqueous_status": "1", "comp_pct_hi": "20",
    }, follow_redirects=True)
    assert "err=" not in str(aqueous.url)
    with connect(tmp_path / "multi-sds.sqlite") as conn:
        rows = [r for r in fil.chemical_quantity_rows(conn, WIZARD_SITE_ID) if r["cas"] == "7647-01-0"]
        assert len(rows) == 2 and len({r["sds_id"] for r in rows}) == 2
        assert fil.merge_annex_qty(rows)["7647-01-0"]["pure_kg"] == 6000
        facts = fil.psi_chemical_facts(conn, WIZARD_SITE_ID)["7647-01-0|P-TANK"]
        assert "氣態" in facts["phase_state"] and "液態" in facts["phase_state"]
        assert "達規定數量" in facts["annex_note"] and "水溶液" in facts["annex_note"]


def test_psi_saved_rows_and_report_follow_current_master_facts(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "psi-sync.sqlite")
    _walk(client, 1)
    chemical = {
        "kind": "純物質", "cas": "7664-39-3", "process_id": "P-TANK",
        "file_name": "psi-sync.pdf", "name": "無水氟化氫",
        "role": "原物料", "h_codes": "H314,H330", "phase_state": "氣態",
        "aqueous_status": "0", "attributed_qty": "1200",
    }
    created = client.post("/wizard/1/chemical", data=chemical, follow_redirects=True)
    assert created.status_code == 200 and "err=" not in str(created.url)
    response = client.post("/wizard/row", data={
        "step": "1", "section": "1.2", "cas": "7664-39-3|P-TANK",
        "ctrl_qty": "999999", "state": "液體", "phase_state": "液態",
    }, follow_redirects=True)
    assert response.status_code == 200
    with connect(tmp_path / "psi-sync.sqlite") as conn:
        saved = fil.list_rows(conn, WIZARD_SITE_ID, "1.2")[-1]
        assert saved["ctrl_qty"] == "1000"
        assert saved["phase_state"] == "氣態"
        assert "state" not in saved
        assert "達規定數量" in saved["annex_note"]

    # Changing the master must update existing 1.2 rows and the report without resaving them.
    chemical.update(phase_state="液態", aqueous_status="0")
    client.post("/wizard/1/chemical", data=chemical, follow_redirects=True)
    with connect(tmp_path / "psi-sync.sqlite") as conn:
        facts = fil.psi_chemical_facts(conn, WIZARD_SITE_ID)
        assert "待確認" in facts["7664-39-3|P-TANK"]["annex_note"]
        report = render_report_v83(conn, WIZARD_SITE_ID)
        table12 = report.split("表1.2-1 高度危害化學品", 1)[1].split("<h3>", 1)[0]
        assert "法定門檻（kg）" in table12 and "待確認" in table12
        assert "<dt>state</dt>" not in table12
    page = client.get("/wizard/1").text
    for label in ("最大存量（kg）", "月用量（kg）", "法定門檻（kg）", "Nm³", "÷100"):
        assert label in page
    assert 'name="ctrl_qty" readonly' in page


def test_mixture_aqueous_status_is_explicit_and_round_trips(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "aqueous.sqlite")
    _walk(client, 1)
    data = {
        "kind": "混合物", "process_id": "P-TANK", "mix_name": "氫氟酸試填",
        "file_name": "aqueous.pdf", "total_kg": "4000",
        "comp_cas": "7664-39-3", "comp_name": "氟化氫", "comp_h": "H314,H330",
        "comp_role": "原物料", "comp_pct_hi": "50", "comp_phase": "液態",
        "comp_aqueous_status": "1",
    }
    created = client.post("/wizard/1/chemical", data=data, follow_redirects=True)
    assert "err=" not in str(created.url)
    with connect(tmp_path / "aqueous.sqlite") as conn:
        row = next(r for r in fil.list_rows(conn, WIZARD_SITE_ID, "mix") if r.get("mix_name") == data["mix_name"])
        assert row["aqueous_status"] == "1" and not row["counted"] and not row["needs_review"]
        assert conn.execute("SELECT aqueous_status FROM chemical WHERE mixture_name=?", (data["mix_name"],)).fetchone()[0] == "1"

    data["comp_aqueous_status"] = "0"
    client.post("/wizard/1/chemical", data=data, follow_redirects=True)
    with connect(tmp_path / "aqueous.sqlite") as conn:
        row = next(r for r in fil.list_rows(conn, WIZARD_SITE_ID, "mix") if r.get("mix_name") == data["mix_name"])
        assert row["aqueous_status"] == "0" and row["needs_review"]
        assert len([r for r in fil.list_rows(conn, WIZARD_SITE_ID, "mix") if r.get("mix_name") == data["mix_name"]]) == 1
