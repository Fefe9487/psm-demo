"""Deletion keeps wizard tables, references, and completion state in sync."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from psm.enums import WIZARD_SITE_ID
from psm.filing import LABOR_ITEMS
from psm import filing as fil
from psm import services as svc
from psm.web import app


def client_for(tmp_path, monkeypatch):
    path = tmp_path / "deletion.sqlite"
    monkeypatch.setattr("psm.db.db_path", lambda: path)
    monkeypatch.setattr("psm.web.db_path", lambda: path)
    monkeypatch.setattr("psm.wizard.db_path", lambda: path)
    client = TestClient(app)
    response = client.post("/wizard/defaults", data={"step": "1"}, follow_redirects=True)
    assert response.status_code == 200
    return client, path


def test_equipment_delete_clears_dependents_and_completion(tmp_path, monkeypatch):
    client, path = client_for(tmp_path, monkeypatch)
    response = client.post("/wizard/item/delete", data={"kind": "equipment", "equipment_id": "T-101"}, follow_redirects=True)
    assert response.status_code == 200
    with sqlite3.connect(path) as conn:
        assert not conn.execute("SELECT 1 FROM equipment WHERE equipment_id='T-101'").fetchone()
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    assert "核心清單" in response.text or "尚待補齊" in response.text


def test_table_104_can_delete_pure_component_and_whole_mixture(tmp_path, monkeypatch):
    client, path = client_for(tmp_path, monkeypatch)
    page = client.get("/wizard/1").text
    assert 'action="/wizard/1/mix/delete"' in page
    assert 'aria-label="刪除成分' in page
    assert "SDS-HF-001" in page
    assert "本章尚待補齊" in page
    assert "1.5 設備" in page

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    svc.save_sds(conn, {
        "sds_id": "SDS-TEST-PURE", "site_id": WIZARD_SITE_ID,
        "substance_or_mixture_name": "測試純物質",
        "file_path": "placeholder://test-pure.pdf",
    })
    svc.save_chemical(conn, {
        "cas": "7664-93-9", "process_id": "P-TANK", "sds_id": "SDS-TEST-PURE",
        "name": "測試純物質", "role": "原物料", "h_codes": "H314",
        "purity_or_mixture": "純物質", "phase_state": "液態",
    })
    assert 'aria-label="刪除純物質' in client.get("/wizard/1").text
    svc.save_chemical(conn, {
        "cas": "71-43-2", "process_id": "P-TANK", "sds_id": "SDS-HF-001",
        "name": "苯", "role": "原物料", "h_codes": "H225",
        "purity_or_mixture": "混合物", "mixture_name": "無水氟化氫（氣態供料）",
        "phase_state": "液態",
    })
    component_id = fil.add_row(conn, WIZARD_SITE_ID, "mix", {
        "mix_name": "無水氟化氫（氣態供料）", "sds_id": "SDS-HF-001",
        "process_id": "P-TANK", "cas": "71-43-2", "phase_state": "液態",
    })
    group_id = conn.execute(
        """SELECT row_id FROM filing_row WHERE site_id=? AND section='mix'
           AND json_extract(payload, '$.process_id')='P-TANK'
           AND json_extract(payload, '$.cas')='7664-39-3'""",
        (WIZARD_SITE_ID,),
    ).fetchone()[0]
    conn.close()

    component = client.post("/wizard/row/delete", data={"step": 1, "row_id": component_id}, follow_redirects=False)
    assert component.status_code == 303 and "err=" not in component.headers["location"]
    conn = sqlite3.connect(path)
    assert not conn.execute("SELECT 1 FROM chemical WHERE process_id='P-TANK' AND cas='71-43-2'").fetchone()
    assert conn.execute("SELECT 1 FROM chemical WHERE process_id='P-TANK' AND cas='7664-39-3'").fetchone()
    conn.row_factory = sqlite3.Row
    svc.save_chemical(conn, {
        "cas": "71-43-2", "process_id": "P-TANK", "sds_id": "SDS-HF-001",
        "name": "苯", "role": "原物料", "h_codes": "H225",
        "purity_or_mixture": "混合物", "mixture_name": "無水氟化氫（氣態供料）",
        "phase_state": "液態",
    })
    second_component_id = fil.add_row(conn, WIZARD_SITE_ID, "mix", {
        "mix_name": "無水氟化氫（氣態供料）", "sds_id": "SDS-HF-001",
        "process_id": "P-TANK", "cas": "71-43-2", "phase_state": "液態",
    })
    conn.close()

    mixture = client.post("/wizard/1/mix/delete", data={"row_id": group_id}, follow_redirects=False)
    assert mixture.status_code == 303 and "err=" not in mixture.headers["location"]
    conn = sqlite3.connect(path)
    assert not conn.execute("SELECT 1 FROM chemical WHERE process_id='P-TANK' AND cas='7664-39-3'").fetchone()
    assert not conn.execute("SELECT 1 FROM chemical WHERE process_id='P-TANK' AND cas='71-43-2'").fetchone()
    assert conn.execute("SELECT 1 FROM chemical WHERE process_id='P-LOAD' AND cas='7664-39-3'").fetchone()
    assert not conn.execute("SELECT 1 FROM filing_row WHERE row_id IN (?, ?, ?)", (group_id, component_id, second_component_id)).fetchone()
    assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.close()

    pure = client.post("/wizard/item/delete", data={
        "kind": "chemical", "process_id": "P-TANK", "sds_id": "SDS-TEST-PURE", "cas": "7664-93-9",
    }, follow_redirects=False)
    assert pure.status_code == 303 and "err=" not in pure.headers["location"]
    with sqlite3.connect(path) as conn:
        assert not conn.execute("SELECT 1 FROM chemical WHERE process_id='P-TANK' AND cas='7664-93-9'").fetchone()
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


def test_table_104_group_delete_keeps_same_cas_in_another_sds(tmp_path, monkeypatch):
    client, path = client_for(tmp_path, monkeypatch)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    svc.save_sds(conn, {
        "sds_id": "SDS-HF-OTHER", "site_id": WIZARD_SITE_ID,
        "substance_or_mixture_name": "另一批氟化氫", "file_path": "placeholder://other.pdf",
    })
    svc.save_chemical(conn, {
        "cas": "7664-39-3", "process_id": "P-TANK", "sds_id": "SDS-HF-OTHER",
        "name": "氟化氫", "role": "原物料", "h_codes": "H225",
        "purity_or_mixture": "混合物", "mixture_name": "另一批氟化氫",
        "phase_state": "液態",
    })
    other_id = fil.add_row(conn, WIZARD_SITE_ID, "mix", {
        "mix_name": "另一批氟化氫", "sds_id": "SDS-HF-OTHER",
        "process_id": "P-TANK", "cas": "7664-39-3", "phase_state": "液態",
    })
    original_id = conn.execute(
        """SELECT row_id FROM filing_row WHERE site_id=? AND section='mix'
           AND json_extract(payload, '$.process_id')='P-TANK'
           AND json_extract(payload, '$.sds_id')='SDS-HF-001'""",
        (WIZARD_SITE_ID,),
    ).fetchone()[0]
    conn.close()
    removed = client.post("/wizard/1/mix/delete", data={"row_id": original_id}, follow_redirects=False)
    assert removed.status_code == 303 and "err=" not in removed.headers["location"]
    with sqlite3.connect(path) as conn:
        assert not conn.execute("SELECT 1 FROM chemical WHERE process_id='P-TANK' AND sds_id='SDS-HF-001' AND cas='7664-39-3'").fetchone()
        assert conn.execute("SELECT 1 FROM chemical WHERE process_id='P-TANK' AND sds_id='SDS-HF-OTHER' AND cas='7664-39-3'").fetchone()
        assert conn.execute("SELECT 1 FROM filing_row WHERE row_id=?", (other_id,)).fetchone()
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("kind, table, columns", [
    ("department", "department", ("dept_id",)),
    ("process", "process", ("process_id",)),
    ("chemical", "chemical", ("process_id", "sds_id", "cas")),
    ("area", "area", ("area_code",)),
    ("drawing", "pid_drawing", ("drawing_no", "revision")),
    ("limit", "equipment_limit", ("limit_id",)),
])
def test_master_item_delete_preserves_foreign_keys(tmp_path, monkeypatch, kind, table, columns):
    client, path = client_for(tmp_path, monkeypatch)
    with sqlite3.connect(path) as conn:
        row = conn.execute(f"SELECT {', '.join(columns)} FROM {table} LIMIT 1").fetchone()
    assert row, table
    payload = {"kind": kind, **dict(zip(columns, row))}
    response = client.post("/wizard/item/delete", data=payload, follow_redirects=False)
    assert response.status_code == 303
    assert "err=" not in response.headers["location"]
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        clause = " AND ".join(f"{column}=?" for column in columns)
        assert not conn.execute(f"SELECT 1 FROM {table} WHERE {clause}", row).fetchone()
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


def test_labor_row_can_be_deleted_and_readded(tmp_path, monkeypatch):
    client, path = client_for(tmp_path, monkeypatch)
    item = LABOR_ITEMS[0]
    client.post("/wizard/3/labor", data={"item": item, "how": "每月參與檢查", "who": "D-OPS"})
    with sqlite3.connect(path) as conn:
        row_id = conn.execute("SELECT row_id FROM filing_row WHERE section='3.1'").fetchone()[0]
    removed = client.post("/wizard/row/delete", data={"step": 3, "row_id": row_id}, follow_redirects=True)
    assert removed.status_code == 200
    assert "每月參與檢查" not in removed.text
    with sqlite3.connect(path) as conn:
        assert not conn.execute("SELECT 1 FROM filing_row WHERE row_id=?", (row_id,)).fetchone()
    restored = client.post("/wizard/3/labor", data={"item": item, "how": "每週參與檢查"}, follow_redirects=True)
    assert "每週參與檢查" in restored.text


def test_contractor_delete_removes_parallel_filing_row(tmp_path, monkeypatch):
    client, path = client_for(tmp_path, monkeypatch)
    client.post("/wizard/row", data={"step": 6, "section": "6.1", "vendor": "示範承攬商", "period": "2026", "summary": "近五年無事故"})
    with sqlite3.connect(path) as conn:
        incident_id = conn.execute("SELECT incident_id FROM contractor_incident WHERE contractor_name='示範承攬商'").fetchone()[0]
    response = client.post("/wizard/item/delete", data={"kind": "contractor", "incident_id": incident_id}, follow_redirects=True)
    assert response.status_code == 200
    with sqlite3.connect(path) as conn:
        assert not conn.execute("SELECT 1 FROM contractor_incident WHERE incident_id=?", (incident_id,)).fetchone()
        assert not conn.execute("SELECT 1 FROM filing_row WHERE section='6.1'").fetchone()


def test_sop_last_row_can_be_deleted(tmp_path, monkeypatch):
    client, path = client_for(tmp_path, monkeypatch)
    with sqlite3.connect(path) as conn:
        sop_id = conn.execute("""SELECT s.sop_id FROM sop s JOIN equipment e ON e.equipment_id=s.equipment_id
            GROUP BY e.equipment_type HAVING COUNT(*)=1 LIMIT 1""").fetchone()[0]
    response = client.post("/wizard/4/sop/delete", data={"sop_id": sop_id}, follow_redirects=True)
    assert response.status_code == 200
    assert "本章尚待補齊" in response.text
    with sqlite3.connect(path) as conn:
        assert not conn.execute("SELECT 1 FROM sop WHERE sop_id=?", (sop_id,)).fetchone()
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("kind, attachment_kind", [
    ("pha_upload", "pha"), ("mi_upload", "mi"), ("secret_upload", "trade_secret"),
])
def test_attachment_rows_can_be_deleted(tmp_path, monkeypatch, kind, attachment_kind):
    client, path = client_for(tmp_path, monkeypatch)
    with sqlite3.connect(path) as conn:
        cur = conn.execute("""INSERT INTO unstructured_attachment(site_id, process_id, kind, original_name, attachment_path)
            VALUES (?, ?, ?, ?, ?)""", (WIZARD_SITE_ID, "P-TANK" if attachment_kind == "mi" else None, attachment_kind, "QA 文件", "qa.pdf"))
        attachment_id = cur.lastrowid
    response = client.post("/wizard/item/delete", data={"kind": kind, "attachment_id": attachment_id}, follow_redirects=False)
    assert response.status_code == 303
    assert "err=" not in response.headers["location"]
    with sqlite3.connect(path) as conn:
        assert not conn.execute("SELECT 1 FROM unstructured_attachment WHERE attachment_id=?", (attachment_id,)).fetchone()


def test_course_hotwork_and_failure_rows_can_be_deleted(tmp_path, monkeypatch):
    client, path = client_for(tmp_path, monkeypatch)
    client.post("/wizard/defaults", data={"step": 5})
    with sqlite3.connect(path) as conn:
        course_id = conn.execute("SELECT course_id FROM training_course LIMIT 1").fetchone()[0]
    course = client.post("/wizard/item/delete", data={"kind": "course", "course_id": course_id}, follow_redirects=False)
    assert course.status_code == 303 and "err=" not in course.headers["location"]
    zone = client.post("/wizard/row", data={"step": 9, "section": "9.1z", "area_code": "AREA-A", "protection_reason": "維修動火"}, follow_redirects=False)
    assert zone.status_code == 303 and "err=" not in zone.headers["location"]
    removed = client.post("/wizard/item/delete", data={"kind": "hotwork_zone", "area_code": "AREA-A"}, follow_redirects=False)
    assert removed.status_code == 303 and "err=" not in removed.headers["location"]
    client.post("/wizard/defaults", data={"step": 8})
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT detail_id FROM mi_inspection_detail LIMIT 1").fetchone()
        assert row
        detail_id = row[0]
    client.post("/wizard/8/detail/delete", data={"detail_id": detail_id})
    with sqlite3.connect(path) as conn:
        assert not conn.execute("SELECT 1 FROM mi_inspection_detail WHERE detail_id=?", (detail_id,)).fetchone()
        assert not conn.execute("SELECT 1 FROM mi_failure WHERE equipment_id='T-101'").fetchone()
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


def test_equipment_delete_updates_multi_equipment_design_code(tmp_path, monkeypatch):
    client, path = client_for(tmp_path, monkeypatch)
    created = client.post("/wizard/1/design-code", data={
        "process_id": "P-TANK", "equipment_ids": ["T-101", "P-101"],
        "material": "QA 材質", "material_category": "碳鋼(CS)",
        "spec": "QA-STD", "scope": "測試",
    }, follow_redirects=False)
    assert created.status_code == 303 and "err=" not in created.headers["location"]
    with sqlite3.connect(path) as conn:
        code_id = conn.execute("SELECT code_id FROM design_code WHERE code='QA-STD'").fetchone()[0]
    client.post("/wizard/item/delete", data={"kind": "equipment", "equipment_id": "P-101"}, follow_redirects=False)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT equipment_id FROM design_code_equipment WHERE code_id=?", (code_id,)).fetchall() == [("T-101",)]
        payload = conn.execute("SELECT payload FROM filing_row WHERE section='1.6' AND json_extract(payload, '$.code_id')=?", (code_id,)).fetchone()[0]
        assert '"equipment_ids": ["T-101"]' in payload
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    client.post("/wizard/item/delete", data={"kind": "equipment", "equipment_id": "T-101"}, follow_redirects=False)
    with sqlite3.connect(path) as conn:
        assert not conn.execute("SELECT 1 FROM design_code WHERE code_id=?", (code_id,)).fetchone()
        assert not conn.execute("SELECT 1 FROM filing_row WHERE section='1.6' AND json_extract(payload, '$.code_id')=?", (code_id,)).fetchone()
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


def test_audit_followup_rows_show_delete_control(tmp_path, monkeypatch):
    client, path = client_for(tmp_path, monkeypatch)
    client.post("/wizard/flags", data={"step": 13, "audit_first": "否"})
    client.post("/wizard/row", data={"step": 13, "section": "13.1",
        "when": "2026-09-01T09:00", "dept_id": "D-OPS",
        "unit": "製程安全資訊", "auditor": "測試稽核員"})
    client.post("/wizard/row", data={"step": 13, "section": "13.2",
        "plan_when": "2026-09-01T09:00", "finding": "防護紀錄未更新",
        "action": "更新紀錄", "dept_id": "D-OPS", "due": "2026-10-01"})
    page = client.get("/wizard/13").text
    assert "防護紀錄未更新" in page
    assert "自願登錄稽核改善進度" in page
    with sqlite3.connect(path) as conn:
        row_id = conn.execute("SELECT row_id FROM filing_row WHERE section='13.2'").fetchone()[0]
    client.post("/wizard/row/delete", data={"step": 13, "row_id": row_id})
    with sqlite3.connect(path) as conn:
        assert not conn.execute("SELECT 1 FROM filing_row WHERE row_id=?", (row_id,)).fetchone()
