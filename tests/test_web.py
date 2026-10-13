"""畫面驗收：HAZOP 未選製程則設備欄關閉；選 P-TANK 看不到 LA-101。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from psm.web import app


def test_hazop_equipment_disabled_until_process_selected(tmp_path, monkeypatch):
    db = tmp_path / "web.sqlite"
    monkeypatch.setattr("psm.web.db_path", lambda: db)
    client = TestClient(app)
    r = client.get("/hazop")
    assert r.status_code == 200
    open_tag = r.text.split('id="hazop-equipment"', 1)[1].split(">", 1)[0]
    block = r.text.split('id="hazop-equipment"', 1)[1].split("</select>", 1)[0]
    assert "disabled" in open_tag
    assert "LA-101" not in block


def test_hazop_ptank_excludes_la101(tmp_path, monkeypatch):
    db = tmp_path / "web2.sqlite"
    monkeypatch.setattr("psm.web.db_path", lambda: db)
    client = TestClient(app)
    r = client.get("/hazop", params={"process_id": "P-TANK"})
    assert r.status_code == 200
    open_tag = r.text.split('id="hazop-equipment"', 1)[1].split(">", 1)[0]
    block = r.text.split('id="hazop-equipment"', 1)[1].split("</select>", 1)[0]
    assert "disabled" not in open_tag
    assert "T-101" in block
    assert "P-101" in block
    assert "LA-101" not in block
    assert "PL-201" not in block


def test_fourteen_unit_pages_and_report(tmp_path, monkeypatch):
    db = tmp_path / "web3.sqlite"
    monkeypatch.setattr("psm.web.db_path", lambda: db)
    client = TestClient(app)
    paths = [
        "/",
        "/site",
        "/departments",
        "/processes",
        "/areas",
        "/equipment",
        "/chemicals",
        "/map",
        "/pid",
        "/psi",
        "/checks",
        "/hazop",
        "/labor",
        "/sop",
        "/training",
        "/contractor",
        "/pssr",
        "/mi",
        "/hotwork",
        "/moc",
        "/incident",
        "/emergency",
        "/audit",
        "/secret",
        "/report",
    ]
    for p in paths:
        r = client.get(p)
        assert r.status_code == 200, p
    html = client.get("/report").text
    assert "T-101" in html and "7664-39-3" in html
    home = client.get("/").text
    assert "開始首次填報" in home
    assert 'id="plant-map"' not in home
    floor = client.get("/floor", follow_redirects=False)
    assert floor.status_code == 303
    assert "/processes" in floor.headers["location"]
    assert "示範廠現場" not in home
    assert "V8.3 填報預覽" in html
    assert "HF 供料管線破損" in html
    assert "近五年事故 0 件" not in html
    proc = client.get("/processes/P-TANK")
    assert proc.status_code == 200
    assert "T-101" in proc.text
    assert "SOP-TANK-01" in proc.text
    assert "SOP-EQ-T-101" in proc.text
    assert "COURSE-TANK-01" in proc.text
    assert "LA-101" not in proc.text
    assert 'href="/processes/P-TANK"' in client.get("/processes").text
    sop = client.get("/sop").text
    assert "製程操作" in sop and "機械設備操作" in sop
    assert "P-TANK" in sop and "P-LOAD" in sop and "P-SCRUB" in sop
    assert "SOP-EQ-LA-101" in sop
    assert 'href="/processes/P-LOAD"' in sop
    train = client.get("/training").text
    assert "製程操作" in train and "機械設備操作" in train
    assert "COURSE-LOAD-01" in train and "COURSE-SCRUB-01" in train
    assert "COURSE-EQ-LA-101" in train
    assert 'href="/processes/P-SCRUB"' in train
    assert "設備操作與隔離" in html
    assert "SOP-EQ-T-101" in html
    wiz = client.get("/wizard/1")
    assert wiz.status_code == 200
    assert "第 1 步" in wiz.text
    assert "為什麼" in wiz.text
    for i in range(1, 15):
        assert f"第 {i} 章" in html
