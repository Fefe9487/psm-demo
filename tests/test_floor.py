"""現場互動驗收：廠區圖、製程晶片、矩陣寫回、偏離晶片開節點。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from psm.web import app


def _client(tmp_path, monkeypatch, name="floor.sqlite"):
    monkeypatch.setattr("psm.web.db_path", lambda: tmp_path / name)
    return TestClient(app)


def test_process_list_replaces_floor(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "home.sqlite")
    gone = client.get("/floor", follow_redirects=False)
    assert gone.status_code == 303
    assert "/processes" in gone.headers["location"]
    r = client.get("/processes")
    assert r.status_code == 200
    assert "<table" in r.text
    assert "新增" in r.text
    assert "done-card" not in r.text
    assert 'id="plant-map"' not in r.text
    assert "P-TANK" in r.text
    assert "資料表" in r.text


def test_floor_json_join_names_and_layout(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    data = client.get("/api/floor").json()
    by_id = {e["equipment_id"]: e for e in data["equipment"]}
    t = by_id["T-101"]
    assert t["process_id"] == "P-TANK"
    assert t["process_name"] == "氣態 HF 供料"
    assert t["maint_dept_name"] == "保養課"
    assert t["operating_dept_name"] == "操作課"
    assert t["area_code"] == "AREA-A"
    assert by_id["LA-101"]["process_id"] == "P-LOAD"
    assert any(o["plate_or_container"] == "HF-TANKER-001" and o["equipment_id"] == "LA-101" for o in data["occupancy"])
    assert "PSV-101" in data["coverage"]["P-TANK"]


def test_score_writes_db_and_updates_rank(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "score.sqlite")
    r = client.post(
        "/api/score",
        json={"consequence_id": "C-HF-01", "severity": 5, "likelihood": 5},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    t = next(e for e in data["equipment"] if e["equipment_id"] == "T-101")
    assert t["max_rank_label"] == "極高"
    cons = None
    for n in data["nodes"]:
        for c in n["consequences"]:
            if c["consequence_id"] == "C-HF-01":
                cons = c
    assert cons["severity"] == 5 and cons["likelihood"] == 5


def test_node_chip_uses_equipment_id_not_typed_name(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "node.sqlite")
    r = client.post(
        "/api/node",
        json={"equipment_id": "T-101", "deviation": "洩漏", "process_id": "P-TANK"},
    )
    assert r.status_code == 200, r.text
    created = r.json()["created_node_id"]
    node = next(n for n in r.json()["nodes"] if n["node_id"] == created)
    assert node["equipment_ids"] == ["T-101"]
    assert node["deviation"] == "洩漏"
    assert "儲槽" not in node["equipment_ids"]


def test_ptank_filter_rejects_la101(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "filter.sqlite")
    r = client.post(
        "/api/node",
        json={"equipment_id": "LA-101", "deviation": "洩漏", "process_id": "P-TANK"},
    )
    assert r.status_code == 400
    assert "製程" in r.json()["error"]


def test_process_without_assessment_cannot_open_node(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "nopha.sqlite")
    r = client.post(
        "/api/node",
        json={"equipment_id": "LA-101", "deviation": "洩漏"},
    )
    assert r.status_code == 400
    assert "尚無評估" in r.json()["error"]
