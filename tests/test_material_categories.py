"""複選材質經表單儲存、更新與 MI 帶入，並相容既有單選資料。"""

import html
import json
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from psm import services as svc
from psm.errors import PsmError
from psm.web import app


@pytest.fixture
def materials_client(tmp_path, monkeypatch):
    path = tmp_path / "materials.sqlite"
    for module in ("psm.db", "psm.web", "psm.wizard"):
        monkeypatch.setattr(module + ".db_path", lambda: path)
    client = TestClient(app)
    client.post("/wizard/defaults", data={"step": "1"})
    return client, path


def test_equipment_multiple_materials_update_and_mi(materials_client):
    client, path = materials_client
    data = {
        "equipment_id": "V-MULTI", "name": "複合材質設備",
        "process_id": "P-TANK", "maint_dept_id": "D-MAINT",
        "equipment_type": "壓力容器與儲槽", "phase_class": "液體",
        "material": "403/404 不銹鋼及碳鋼",
        "material_category": ["碳鋼(CS)", "400系不銹鋼", "碳鋼(CS)"],
    }
    response = client.post("/wizard/1/equipment", data=data, headers={"X-PSM-Partial": "1"})
    assert response.json()["ok"]
    assert response.json()["row"]["material_category"] == "碳鋼(CS),400系不銹鋼"
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        assert svc.material_for_mi(conn, "V-MULTI")["material_category"] == "碳鋼(CS),400系不銹鋼"
    page = client.get("/wizard/1").text
    row = re.search(r'<tr data-edit="equipment" data-json="([^"]*V-MULTI[^"]*)"', page)
    assert json.loads(html.unescape(row.group(1)))["material_category"] == "碳鋼(CS),400系不銹鋼"
    assert "設備材質明細" in page
    assert 'placeholder="如 403/404 不銹鋼"' in page
    equipment_form = page.split('id="form-equipment"', 1)[1].split("</form>", 1)[0]
    assert equipment_form.index("data-material-category") < equipment_form.index("data-material-name")
    material_form = page.split('id="form-equipment-materials"', 1)[1].split("</form>", 1)[0]
    assert material_form.index("data-material-equipment") < material_form.index("data-material-category") < material_form.index("data-material-name")
    data["material_category"] = ["400系不銹鋼"]
    updated = client.post("/wizard/1/equipment", data=data, headers={"X-PSM-Partial": "1"})
    assert updated.json()["row"]["material_category"] == "400系不銹鋼"
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        assert svc.material_for_mi(conn, "V-MULTI")["material_category"] == "400系不銹鋼"


def test_design_code_multiple_materials_and_invalid_rejection(materials_client):
    client, path = materials_client
    data = {
        "process_id": "P-TANK", "equipment_ids": ["T-101", "P-101"],
        "material": "403/404 不銹鋼及碳鋼", "spec": "MULTI-TEST",
        "material_category": ["碳鋼(CS)", "400系不銹鋼"],
    }
    response = client.post("/wizard/1/design-code", data=data, follow_redirects=True)
    assert response.status_code == 200
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        code_id, category = conn.execute("SELECT code_id, material_category FROM design_code WHERE code='MULTI-TEST'").fetchone()
        assert category == "碳鋼(CS),400系不銹鋼"
        for eid in data["equipment_ids"]:
            assert svc.material_for_mi(conn, eid)["material_category"] == category
    data.update(code_id=str(code_id), material_category=["400系不銹鋼"])
    client.post("/wizard/1/design-code", data=data)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT material_category FROM design_code WHERE code_id=?", (code_id,)).fetchone()[0] == "400系不銹鋼"
    data.update(material_category=["碳鋼(CS)", "無效類別"], spec="INVALID-TEST")
    rejected = client.post("/wizard/1/design-code", data=data, follow_redirects=True)
    assert "須為本署劣化機制查詢選項" in rejected.text
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT code FROM design_code WHERE code_id=?", (code_id,)).fetchone()[0] == "MULTI-TEST"


def test_material_category_normalization_keeps_legacy_values():
    assert svc.normalize_material_categories("300系不銹鋼") == "300系不銹鋼"
    assert svc.normalize_material_categories("碳鋼(CS), 400系不銹鋼,碳鋼(CS)") == "碳鋼(CS),400系不銹鋼"
    assert svc.normalize_material_categories([]) == ""
    with pytest.raises(PsmError):
        svc.normalize_material_categories(["碳鋼(CS)", "無效類別"])
