"""來源存量只填一次，成分、SDS、地點與後續判定保持一致。"""

import json

import pytest

from psm import chemical_stock as stock, filing as fil
from psm.db import connect
from psm.enums import WIZARD_SITE_ID
from psm.report_v83 import render_report_v83
from tests.test_wizard import _client, _walk


@pytest.fixture
def setup_stock(tmp_path, monkeypatch):
    path = tmp_path / "stock.sqlite"
    client = _client(tmp_path, monkeypatch, path.name)
    _walk(client, 1)
    return client, path


def _mixture(client, name="測試溶劑", file="stock-mix.pdf", **updates):
    data = {
        "kind": "混合物", "process_id": "P-TANK", "mix_name": name, "file_name": file,
        "comp_cas": ["108-88-3", "67-64-1"], "comp_name": ["甲苯", "丙酮"],
        "comp_role": ["原物料", "原物料"], "comp_h": ["H225", "H225"],
        "comp_pct_hi": ["60", "20"], "comp_phase": ["液態", "液態"], **updates,
    }
    response = client.post("/wizard/1/chemical", data=data, follow_redirects=True)
    assert "err=" not in str(response.url)


def _source(path, name):
    with connect(path) as conn:
        return next(r for r in stock.source_catalog(conn, WIZARD_SITE_ID) if r["name"] == name)


def _save(client, source, **updates):
    return client.post("/wizard/1/stock", data={
        "source_key": source["source_key"], "max_kg": "1000", "monthly_kg": "2000",
        "area_code": "AREA-A", "dept_id": "D-OPS", **updates,
    }, follow_redirects=True)


def test_order_and_master_have_no_quantity_inputs(setup_stock):
    client, _ = setup_stock
    page = client.get("/wizard/1").text
    master = page.split('id="form-chemical"', 1)[1].split("</form>", 1)[0]
    assert 'name="attributed_qty"' not in master
    assert 'name="total_kg"' not in master
    assert 'name="comp_formula"' not in master
    assert page.index('id="form-chemical"') < page.index('id="form-stock-11"') < page.index('id="form-12"')
    assert 'id="form-11"' not in page


def test_mixture_is_filled_once_and_components_aggregate(setup_stock):
    client, path = setup_stock
    _mixture(client)
    source = _source(path, "測試溶劑")
    assert "err=" not in str(_save(client, source).url)
    # Retry an identical creation: one source at one location must remain one record.
    _save(client, source)
    with connect(path) as conn:
        saved = [r for r in fil.list_rows(conn, WIZARD_SITE_ID, stock.SECTION) if r["source_key"] == source["source_key"]]
        assert len(saved) == 1
        components = [r for r in fil.chemical_quantity_rows(conn, WIZARD_SITE_ID) if r["source_key"] == source["source_key"]]
        assert {r["cas"]: r["pure_kg"] for r in components} == {"108-88-3": "600", "67-64-1": "200"}
        assert {r["cas"]: r["monthly_kg"] for r in components} == {"108-88-3": "1200", "67-64-1": "400"}
        assert all(r["total_kg"] == "1000" for r in components)
        row_id = saved[0]["row_id"]
    _save(client, source, row_id=str(row_id), max_kg="500")
    with connect(path) as conn:
        summary = {r["cas"]: r for r in stock.inventory_summary(conn, WIZARD_SITE_ID)}
        assert summary["108-88-3"]["max_kg"] == "300"
        assert summary["67-64-1"]["max_kg"] == "100"


def test_different_sds_sources_and_locations_do_not_overwrite(setup_stock):
    client, path = setup_stock
    _mixture(client, "來源甲", "source-a.pdf")
    _mixture(client, "來源乙", "source-b.pdf")
    first, second = _source(path, "來源甲"), _source(path, "來源乙")
    _save(client, first, max_kg="1000")
    _save(client, second, max_kg="2000")
    with connect(path) as conn:
        conn.execute("""INSERT INTO area(area_code,site_id,name,drawing_no,revision,issue_date,worker_count,attachment_path)
                        SELECT 'STOCK-B',site_id,'第二存放地',drawing_no,revision,issue_date,worker_count,attachment_path
                        FROM area WHERE area_code='AREA-A'""")
        conn.commit()
    _save(client, first, area_code="STOCK-B", max_kg="500")
    with connect(path) as conn:
        summary = next(r for r in stock.inventory_summary(conn, WIZARD_SITE_ID) if r["cas"] == "108-88-3")
        assert summary["max_kg"] == "2100"
        assert "AREA-A" in summary["area_code"] and "STOCK-B" in summary["area_code"]
        assert len([r for r in fil.list_rows(conn, WIZARD_SITE_ID, stock.SECTION) if r["source_key"] in (first["source_key"], second["source_key"])]) == 3


def test_unknown_and_legacy_amounts_are_pending_not_zero(setup_stock):
    client, path = setup_stock
    _mixture(client, total_kg="99999")
    source = _source(path, "測試溶劑")
    with connect(path) as conn:
        pending = next(r for r in stock.stock_rows(conn, WIZARD_SITE_ID) if r["source_key"] == source["source_key"])
        assert pending["max_kg"] == "99999" and not pending["confirmed"]
        rows = [r for r in fil.chemical_quantity_rows(conn, WIZARD_SITE_ID) if r["source_key"] == source["source_key"]]
        assert all(r["needs_review"] and not r["counted"] and r["pure_kg"] == "" for r in rows)
    _save(client, source, max_kg="0", monthly_kg="")
    with connect(path) as conn:
        row = next(r for r in stock.inventory_summary(conn, WIZARD_SITE_ID) if r["cas"] == "108-88-3")
        assert row["max_kg"] == "0" and row["monthly_kg"] == ""
        assert json.loads(conn.execute("SELECT payload FROM filing_row WHERE section='mix' AND payload LIKE '%99999%'").fetchone()[0])["total_kg"] == "99999"


@pytest.mark.parametrize("value", ["-1", "NaN", "inf", "1e999", "10 L", ""])
def test_invalid_stock_is_rejected_without_writing(setup_stock, value):
    client, path = setup_stock
    _mixture(client)
    source = _source(path, "測試溶劑")
    response = _save(client, source, max_kg=value)
    assert "err=" in str(response.url)
    with connect(path) as conn:
        assert not fil.list_rows(conn, WIZARD_SITE_ID, stock.SECTION)


def test_composition_edit_recomputes_existing_stock_and_report(setup_stock):
    client, path = setup_stock
    _mixture(client)
    source = _source(path, "測試溶劑")
    _save(client, source)
    _mixture(client, comp_pct_hi=["40", "20"])
    with connect(path) as conn:
        summary = next(r for r in stock.inventory_summary(conn, WIZARD_SITE_ID) if r["cas"] == "108-88-3")
        assert summary["max_kg"] == "400"
        report = render_report_v83(conn, WIZARD_SITE_ID)
        assert report.index("表1.0-4 配方成分與相態") < report.index("表1.1-1 來源存量與使用量") < report.index("表1.2-1 高度危害化學品")
        assert "來源最大存量 kg" in report and "成分純物質量 kg" in report


def test_legacy_manual_total_cannot_override_source_total(setup_stock):
    client, path = setup_stock
    _mixture(client)
    source = _source(path, "測試溶劑")
    _save(client, source)
    response = client.post("/wizard/row", data={"step": "1", "section": "1.1", "cas": "108-88-3|P-TANK", "max_kg": "99999"}, follow_redirects=True)
    assert "err=" in str(response.url)
    with connect(path) as conn:
        assert next(r for r in stock.inventory_summary(conn, WIZARD_SITE_ID) if r["cas"] == "108-88-3")["max_kg"] == "600"


def test_unknown_second_source_preserves_known_amount_without_claiming_complete(setup_stock):
    client, path = setup_stock
    _mixture(client, "已填來源", "known.pdf")
    _mixture(client, "未填來源", "unknown.pdf")
    _save(client, _source(path, "已填來源"))
    with connect(path) as conn:
        row = next(r for r in stock.inventory_summary(conn, WIZARD_SITE_ID) if r["cas"] == "108-88-3")
        assert row["max_kg"] == "待確認" and row["confirmed_max_kg"] == "600"
        facts = fil.psi_chemical_facts(conn, WIZARD_SITE_ID)["108-88-3|P-TANK"]
        assert "待確認" in facts["annex_note"] and "未達規定數量" not in facts["annex_note"]


def test_stock_identity_and_location_validation_prevent_wrong_source_updates(setup_stock):
    client, path = setup_stock
    _mixture(client, "來源甲", "identity-a.pdf")
    _mixture(client, "來源乙", "identity-b.pdf")
    first, second = _source(path, "來源甲"), _source(path, "來源乙")
    _save(client, first)
    with connect(path) as conn:
        row_id = fil.list_rows(conn, WIZARD_SITE_ID, stock.SECTION)[0]["row_id"]
    assert "err=" in str(_save(client, second, row_id=str(row_id)).url)
    assert "err=" in str(_save(client, second, area_code="DOES-NOT-EXIST").url)
    assert "err=" in str(_save(client, second, row_id="999999").url)
    with connect(path) as conn:
        rows = fil.list_rows(conn, WIZARD_SITE_ID, stock.SECTION)
        assert len(rows) == 1 and rows[0]["source_key"] == first["source_key"] and rows[0]["max_kg"] == "1000"


def test_deleted_stock_does_not_reactivate_legacy_amount(setup_stock):
    client, path = setup_stock
    _mixture(client, total_kg="90000")
    source = _source(path, "測試溶劑")
    _save(client, source)
    with connect(path) as conn:
        row_id = fil.list_rows(conn, WIZARD_SITE_ID, stock.SECTION)[0]["row_id"]
    client.post("/wizard/row/delete", data={"step": "1", "row_id": str(row_id)})
    with connect(path) as conn:
        rows = [r for r in fil.chemical_quantity_rows(conn, WIZARD_SITE_ID) if r["source_key"] == source["source_key"]]
        assert all(not r["stock_confirmed"] and not r["counted"] and r["pure_kg"] == "" for r in rows)


def test_volume_ratio_is_not_treated_as_weight_percentage(setup_stock):
    client, path = setup_stock
    _mixture(client, basis="體積比")
    source = _source(path, "測試溶劑")
    _save(client, source)
    with connect(path) as conn:
        rows = [r for r in fil.chemical_quantity_rows(conn, WIZARD_SITE_ID) if r["source_key"] == source["source_key"]]
        assert all(r["stock_confirmed"] and r["pure_kg"] == "" and r["needs_review"] for r in rows)
        assert all("重量百分比" in r["annex_note"] for r in rows)
        assert next(r for r in stock.inventory_summary(conn, WIZARD_SITE_ID) if r["cas"] == "108-88-3")["max_kg"] == "待確認"
