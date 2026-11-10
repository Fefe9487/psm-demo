import json
from contextlib import closing

import pytest

from psm import materials, mi_plans
from psm.damage_mechanisms import CATALOG, DAMAGE_BY_CODE
from psm.db import connect
from psm.enums import WIZARD_SITE_ID
from psm.report_v83 import render_report_v83
from tests.test_wizard import _client, _walk


@pytest.fixture
def mi_client(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "mi-plans.sqlite")
    _walk(client, 1)
    path = tmp_path / "mi-plans.sqlite"
    client.post("/wizard/1/materials", data={"equipment_id": "T-101", "materials_json": json.dumps([
        {"material_category": "碳鋼(CS)", "material": "CS A283", "part": "殼體"},
        {"material_category": "400系不銹鋼", "material": "403/404 不銹鋼", "part": "內襯"},
    ], ensure_ascii=False)})
    client.post("/wizard/8/screen", data={"equipment_id": "T-101", "is_critical": "1", "basis": "測試承壓設備"})
    with closing(connect(path)) as conn:
        rows = materials.rows_for_equipment(conn, "T-101")
    return client, path, rows


def _plan(material_id, code="01", **updates):
    return {"material_id": material_id, "damage_code": code, "damage": "", "inspection_item": "",
            "method": "超音波測厚", "freq": "每年", "proc_no": "MI-T-101", "pid_no": "PID-TANK-001", **updates}


def _save(client, rows, deleted=None):
    return client.post("/wizard/8/details", data={"equipment_id": "T-101", "mi_type": "壓力容器與儲槽",
        "mi_rows_json": json.dumps(rows, ensure_ascii=False), "mi_deleted_json": json.dumps(deleted or [])}, follow_redirects=True)


def test_official_catalog_contains_66_unique_mechanisms():
    assert len(CATALOG["items"]) == 66
    assert [int(row["code"]) for row in CATALOG["items"]] == list(range(1, 67))
    assert len({row["name"] for row in CATALOG["items"]}) == 66
    assert "listAllDamageMechanism.action" in CATALOG["source_url"]


def test_bulk_mi_keeps_material_mechanism_and_inspection_mapping(mi_client):
    client, path, materials_rows = mi_client
    plans = [_plan(materials_rows[0]["material_id"]), _plan(materials_rows[1]["material_id"], "25", freq="每季", proc_no="MI-LINING"),
             _plan(None, "", inspection_item="高液位警報功能", method="功能測試", freq="每月", proc_no="MI-ALARM")]
    assert "err=" not in str(_save(client, plans).url)
    with closing(connect(path)) as conn:
        rows = mi_plans.list_details(conn, WIZARD_SITE_ID)
        assert len(rows) == 3
        assert rows[0]["damage_mechanism"] == DAMAGE_BY_CODE["01"]["name"] and rows[0]["material_part"] == "殼體"
        assert rows[1]["damage_code"] == "25" and rows[1]["material"] == "403/404 不銹鋼" and rows[1]["inspect_frequency"] == "每季"
        assert rows[2]["inspection_item"] == "高液位警報功能" and rows[2]["material_id"] is None and rows[2]["material"] == ""
        report = render_report_v83(conn, WIZARD_SITE_ID)
        assert "403/404 不銹鋼" in report and DAMAGE_BY_CODE["25"]["name"] in report and "MI-LINING" in report
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


def test_explicit_delete_retains_other_rows_and_concurrent_append(mi_client):
    client, path, material_rows = mi_client
    first, second = _plan(material_rows[0]["material_id"]), _plan(material_rows[1]["material_id"], "25")
    _save(client, [first, second])
    with closing(connect(path)) as conn:
        ids = [row[0] for row in conn.execute("SELECT detail_id FROM mi_inspection_detail ORDER BY detail_id")]
    # Another editor appends a third record after this form was loaded.
    client.post("/wizard/row", data={"step": "8", "section": "8.1", "equipment_id": "T-101", "mi_type": "壓力容器與儲槽",
        "inspection_item": "緊急切斷功能", "method": "功能測試", "freq": "每月", "proc_no": "MI-NEW", "pid_no": "PID-TANK-001"})
    first.update(detail_id=ids[0], freq="每兩年")
    _save(client, [first], [ids[1]])
    with closing(connect(path)) as conn:
        rows = list(conn.execute("SELECT * FROM mi_inspection_detail ORDER BY detail_id"))
        assert len(rows) == 2 and rows[0]["detail_id"] == ids[0]
        assert rows[0]["inspect_frequency"] == "每兩年" and rows[1]["procedure_ref"] == "MI-NEW"


@pytest.mark.parametrize("change", [{"damage_code": "99"}, {"material_id": "999999"}, {"material_id": ""},
                                   {"pid_no": "NOT-THIS-PROCESS"}, {"freq": ""}, {"inspection_item": "不可同時填功能"}])
def test_invalid_row_rejects_whole_bulk_save(mi_client, change):
    client, path, material_rows = mi_client
    original = _plan(material_rows[0]["material_id"])
    _save(client, [original])
    with closing(connect(path)) as conn:
        row_id = conn.execute("SELECT detail_id FROM mi_inspection_detail").fetchone()[0]
    bad = {**_plan(material_rows[1]["material_id"], "25"), **change}
    response = _save(client, [bad], [row_id])
    assert "err=" in str(response.url)
    with closing(connect(path)) as conn:
        saved = list(conn.execute("SELECT * FROM mi_inspection_detail"))
        assert len(saved) == 1 and saved[0]["detail_id"] == row_id and saved[0]["damage_code"] == "01"


def test_material_change_or_removal_marks_only_linked_plan_pending(mi_client):
    client, path, material_rows = mi_client
    _save(client, [_plan(material_rows[0]["material_id"]), _plan(material_rows[1]["material_id"], "25")])
    material_rows[1]["material"] = "SUS410"
    client.post("/wizard/1/materials", data={"equipment_id": "T-101", "materials_json": json.dumps(material_rows, ensure_ascii=False)})
    with closing(connect(path)) as conn:
        states = {row["damage_code"]: row["confirmed"] for row in conn.execute("SELECT * FROM mi_inspection_detail")}
        assert states == {"01": 1, "25": 0}
    client.post("/wizard/1/materials", data={"equipment_id": "T-101", "materials_json": json.dumps(material_rows[1:], ensure_ascii=False)})
    with closing(connect(path)) as conn:
        rows = mi_plans.list_details(conn, WIZARD_SITE_ID)
        removed = next(row for row in rows if row["damage_code"] == "01")
        assert removed["material_id"] is None and removed["confirmed"] == 0
        assert removed["material_missing"] and removed["material"] == "CS A283"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


def test_mi_interface_has_searchable_catalog_nested_rows_and_upload_label(mi_client):
    client, _, _ = mi_client
    html = client.get("/wizard/8").text
    assert html.count("data-mi-catalog-check") == 66
    assert "data-mi-damage-search" in html and "data-mi-rows-body" in html
    assert 'data-add-label="上傳附件"' in html and ">上傳附件</button>" in html
    assert "登錄附件" not in html
