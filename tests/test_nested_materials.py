import json
from contextlib import closing

import pytest

from psm import materials, services as svc
from psm.db import connect, init_schema
from psm.enums import WIZARD_SITE_ID
from psm.report_v83 import render_report_v83
from tests.test_wizard import _client, _walk


@pytest.fixture
def client_db(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "nested.sqlite")
    _walk(client, 1)
    return client, tmp_path / "nested.sqlite"


def _rows():
    return [{"material_category": "碳鋼(CS)", "material": "CS A283", "part": "殼體"},
            {"material_category": "400系不銹鋼", "material": "403/404 不銹鋼", "part": "內襯"}]


def _save(client, equipment_id, rows):
    return client.post("/wizard/1/materials", data={"equipment_id": equipment_id, "materials_json": json.dumps(rows, ensure_ascii=False)}, follow_redirects=True)


def test_material_rows_round_trip_update_remove_and_mi(client_db):
    client, path = client_db
    response = _save(client, "T-101", _rows())
    assert "err=" not in str(response.url)
    with closing(connect(path)) as conn:
        rows = materials.rows_for_equipment(conn, "T-101")
        assert len(rows) == 2 and [r["part"] for r in rows] == ["殼體", "內襯"]
        bound = svc.material_for_mi(conn, "T-101")
        assert bound["material_category"] == "碳鋼(CS),400系不銹鋼"
        assert [r["material"] for r in bound["material_rows"]] == ["CS A283", "403/404 不銹鋼"]
        report = render_report_v83(conn, WIZARD_SITE_ID)
        assert "表1.6-1 設備材質明細" in report and "403/404 不銹鋼" in report and "內襯" in report
    rows[1]["material"] = "SUS410"
    _save(client, "T-101", rows[1:])
    with closing(connect(path)) as conn:
        saved = materials.rows_for_equipment(conn, "T-101")
        assert len(saved) == 1 and saved[0]["material_id"] == rows[1]["material_id"]
        assert saved[0]["material"] == "SUS410"
        assert svc.material_for_mi(conn, "T-101")["material_category"] == "400系不銹鋼"


def test_equipment_creation_accepts_multiple_material_rows(client_db):
    client, path = client_db
    data = {"equipment_id": "NEST-NEW", "name": "複合材質設備", "process_id": "P-TANK",
            "maint_dept_id": "D-MAINT", "equipment_type": "壓力容器與儲槽", "phase_class": "液體",
            "materials_json": json.dumps(_rows(), ensure_ascii=False)}
    result = client.post("/wizard/1/equipment", data=data, headers={"X-PSM-Partial": "1"}).json()
    assert result["ok"] and len(result["row"]["material_rows"]) == 2
    with closing(connect(path)) as conn:
        assert len(materials.rows_for_equipment(conn, "NEST-NEW")) == 2


def test_schema_upgrade_preserves_legacy_row_and_does_not_resurrect_deleted_rows(client_db):
    client, path = client_db
    with closing(connect(path)) as conn:
        old = dict(conn.execute("SELECT * FROM equipment_material WHERE equipment_id='T-101'").fetchone())
        conn.execute("DROP TABLE equipment_material_detail")
        init_schema(conn)
        init_schema(conn)
        rows = materials.rows_for_equipment(conn, "T-101")
        assert len(rows) == 1 and rows[0]["material"] == old["material"]
        assert rows[0]["material_category"] == old["material_category"]
    _save(client, "T-101", [])
    with closing(connect(path)) as conn:
        init_schema(conn)
        assert not materials.rows_for_equipment(conn, "T-101")
        assert not conn.execute("SELECT 1 FROM equipment_material WHERE equipment_id='T-101'").fetchone()
        assert conn.execute("SELECT material FROM equipment WHERE equipment_id='T-101'").fetchone()[0] is None


def test_design_code_uses_equipment_rows_without_flattening(client_db):
    client, path = client_db
    _save(client, "T-101", _rows())
    response = client.post("/wizard/1/design-code", data={"process_id": "P-TANK", "equipment_ids": "T-101", "spec": "NEST-ASME"}, follow_redirects=True)
    assert "err=" not in str(response.url)
    with closing(connect(path)) as conn:
        assert len(materials.rows_for_equipment(conn, "T-101")) == 2
    rejected = client.post("/wizard/1/design-code", data={"process_id": "P-TANK", "equipment_ids": "T-101", "spec": "WRONG", "material": "SS316", "material_category": "300系不銹鋼"}, follow_redirects=True)
    assert "err=" in str(rejected.url)
    with closing(connect(path)) as conn:
        assert len(materials.rows_for_equipment(conn, "T-101")) == 2
        assert not conn.execute("SELECT 1 FROM design_code WHERE code='WRONG'").fetchone()


@pytest.mark.parametrize("rows", [[{"material_category": "碳鋼(CS)", "material": ""}], [{"material_category": "不存在", "material": "SS316"}], _rows()[:1] * 2])
def test_invalid_material_rows_leave_previous_values_intact(client_db, rows):
    client, path = client_db
    _save(client, "T-101", _rows())
    response = _save(client, "T-101", rows)
    assert "err=" in str(response.url)
    with closing(connect(path)) as conn:
        assert [r["material"] for r in materials.rows_for_equipment(conn, "T-101")] == ["CS A283", "403/404 不銹鋼"]


def test_material_row_id_cannot_be_moved_between_equipment(client_db):
    client, path = client_db
    _save(client, "T-101", _rows())
    with closing(connect(path)) as conn:
        rows = materials.rows_for_equipment(conn, "T-101")
        before = materials.rows_for_equipment(conn, "P-101")
    assert "err=" in str(_save(client, "P-101", rows).url)
    with closing(connect(path)) as conn:
        assert materials.rows_for_equipment(conn, "P-101") == before


def test_advanced_psi_material_endpoint_keeps_nested_rows(client_db):
    client, path = client_db
    response = client.post("/psi/material", data={"equipment_id": "T-101", "materials_json": json.dumps(_rows(), ensure_ascii=False)}, follow_redirects=True)
    assert "err=" not in str(response.url) and response.status_code == 200
    with closing(connect(path)) as conn:
        assert [row["part"] for row in materials.rows_for_equipment(conn, "T-101")] == ["殼體", "內襯"]


def test_limit_editor_places_equipment_before_four_native_choices(client_db):
    client, _ = client_db
    html = client.get("/wizard/1").text.split('id="form-limit-review"', 1)[1].split("</form>", 1)[0]
    assert html.index('id="limit-eq"') < html.index('class="limit-choice-grid"')
    assert html.count('name="review_parameter"') == 4
    for key in ("p", "t", "f", "c"):
        assert f'id="limit-panel-{key}"' in html
        assert f'name="{key}_design_high"' in html and f'name="{key}_safety_low"' in html
