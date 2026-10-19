"""V8.3 first-filing relationships that a preseeded demo cannot verify."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from psm import db, filing as fil, wizard
from psm.enums import WIZARD_SITE_ID
from psm.web import app


def _client(tmp_path, monkeypatch):
    path = tmp_path / "v83-cross-chapter.sqlite"
    monkeypatch.setattr("psm.db.db_path", lambda: path)
    monkeypatch.setattr("psm.web.db_path", lambda: path)
    monkeypatch.setattr("psm.wizard.db_path", lambda: path)
    client = TestClient(app)
    client.post("/wizard/defaults", data={"step": "1"})
    return client, path


def test_incident_created_in_chapter_11_can_be_linked_in_chapter_6(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    created = client.post(
        "/wizard/row",
        data={
            "step": "11", "section": "11.2", "incident_id": "INC-QA-001",
            "when": "2026-09-01", "incident_type": "虛驚", "summary": "承攬吊裝虛驚",
            "process_id": "P-TANK", "equipment_id": "T-101",
        },
        follow_redirects=False,
    )
    assert "err=" not in created.headers["location"]
    conn = db.connect(path)
    try:
        assert conn.execute(
            "SELECT site_id FROM incident WHERE incident_id='INC-QA-001'"
        ).fetchone()[0] == WIZARD_SITE_ID
        assert not conn.execute(
            "SELECT 1 FROM filing_row WHERE site_id=? AND section='11.2'",
            (WIZARD_SITE_ID,),
        ).fetchone()
    finally:
        conn.close()
    assert "INC-QA-001" in client.get("/wizard/6").text

    client.post("/wizard/6/contractor", data={
        "name": "測試承攬商", "contract_period": "2026 全年", "work_description": "吊裝"
    })
    client.post("/wizard/flags", data={"step": "6", "c_roster_complete": "1"})
    conn = db.connect(path)
    try:
        contractor_id = conn.execute(
            "SELECT contractor_id FROM contractor WHERE name='測試承攬商'"
        ).fetchone()[0]
    finally:
        conn.close()
    linked = client.post("/wizard/6/incident", data={
        "contractor_id": contractor_id, "linked_incident_id": "INC-QA-001"
    }, follow_redirects=False)
    assert "err=" not in linked.headers["location"]
    conn = db.connect(path)
    try:
        assert conn.execute(
            "SELECT linked_incident_id FROM contractor_incident WHERE contractor_id=?",
            (contractor_id,),
        ).fetchone()[0] == "INC-QA-001"
        assert wizard.step_missing(conn, WIZARD_SITE_ID, 6) == wizard.document_gaps(conn, WIZARD_SITE_ID, 6)
    finally:
        conn.close()
    blocked = client.post("/wizard/11/incident/delete", data={
        "incident_id": "INC-QA-001"
    }, follow_redirects=False)
    assert "err=" in blocked.headers["location"]


def test_zero_accidents_still_requires_contractor_roster(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    client.post("/wizard/flags", data={"step": "6", "c_no_accident": "1"})
    conn = db.connect(path)
    try:
        assert any("承攬商" in item for item in wizard.step_missing(conn, WIZARD_SITE_ID, 6))
    finally:
        conn.close()
    client.post("/wizard/6/contractor", data={
        "name": "無事故承攬商", "contract_period": "2025-01 至 2026-01"
    })
    client.post("/wizard/flags", data={"step": "6", "c_roster_complete": "1"})
    conn = db.connect(path)
    try:
        assert wizard.step_missing(conn, WIZARD_SITE_ID, 6) == wizard.document_gaps(conn, WIZARD_SITE_ID, 6)
    finally:
        conn.close()


def test_emergency_unperformed_drill_stays_pending_with_plan_and_reason(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    client.post("/wizard/defaults", data={"step": "12"})
    saved = client.post("/wizard/row", data={
        "step": "12", "section": "12.1s", "situation": "停電",
        "description": "公用電力中斷", "process_ids": ["P-TANK"],
        "area_codes": ["AREA-A"], "muster": "AREA-M",
        "no_equipment_reason": "全區供電中斷", "no_chemical_reason": "不以特定化學品區分",
        "drill_plan_scope": "應變計畫第 5 節停電演練", "drill_status": "尚未執行",
        "drill_due": "2027-03-01", "drill_no_reason": "首次填報前尚未排到本情境",
    }, follow_redirects=False)
    assert "err=" not in saved.headers["location"]
    conn = db.connect(path)
    try:
        row = next(r for r in fil.list_rows(conn, WIZARD_SITE_ID, "12.1s") if r["situation"] == "停電")
        assert row["drill_due"] == "2027-03-01"
        assert any("停電" in item and "待人工確認" in item
                   for item in wizard.step_missing(conn, WIZARD_SITE_ID, 12))
    finally:
        conn.close()


def test_training_requires_each_sop_and_valid_retraining_details(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    client.post("/wizard/defaults", data={"step": "4"})
    client.post("/wizard/defaults", data={"step": "5"})
    conn = db.connect(path)
    try:
        missing = wizard.step_missing(conn, WIZARD_SITE_ID, 5)
        assert any("複訓" in item for item in missing)
        assert any("SOP" in item for item in missing)
        sop_ids = [r[0] for r in conn.execute(
            "SELECT sop_id FROM sop WHERE process_id='P-TANK' ORDER BY sop_id LIMIT 2"
        )]
        assert len(sop_ids) == 2
    finally:
        conn.close()

    created = client.post("/wizard/5/course", data={
        "course_id": "COURSE-MULTI-QA", "name": "同製程 SOP 聯合訓練",
        "kind": "initial", "audience": "員工", "process_id": "P-TANK",
        "hours": "2", "refresh_every": "每年", "refresh_hours": "1",
        "sop_ids": sop_ids,
    }, follow_redirects=False)
    assert "err=" not in created.headers["location"]
    conn = db.connect(path)
    try:
        linked = {r[0] for r in conn.execute(
            "SELECT sop_id FROM training_course_sop WHERE course_id='COURSE-MULTI-QA'")}
        assert linked == set(sop_ids)
        other = conn.execute("""SELECT s.sop_id FROM sop s JOIN process p ON p.process_id=s.process_id
            WHERE p.site_id=? AND s.sop_id NOT IN (SELECT sop_id FROM training_course_sop)
            LIMIT 1""", (WIZARD_SITE_ID,)).fetchone()
        assert other is not None
    finally:
        conn.close()
    exception = client.post("/wizard/row", data={
        "step": "5", "section": "5.1e", "sop_id": other[0],
        "reason": "該程序由獨立資格訓練涵蓋，佐證待上傳",
    }, follow_redirects=False)
    assert "err=" not in exception.headers["location"]
    assert "COURSE-MULTI-QA" in client.get("/report").text


def test_pssr_requires_per_equipment_applicability_and_na_reason(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    client.post("/wizard/defaults", data={"step": "7"})
    conn = db.connect(path)
    try:
        assert len(fil.list_rows(conn, WIZARD_SITE_ID, "7.0")) >= 2
        scope = fil.list_rows(conn, WIZARD_SITE_ID, "7.0")[0]
        fil.delete_row(conn, WIZARD_SITE_ID, scope["row_id"])
        assert any(scope["equipment_id"] in item and "適用性" in item
                   for item in wizard.step_missing(conn, WIZARD_SITE_ID, 7))
    finally:
        conn.close()
    invalid = client.post("/wizard/row", data={
        "step": "7", "section": "7.0", "equipment_id": scope["equipment_id"],
        "applicable": "0", "reason": "",
    }, follow_redirects=False)
    assert "err=" in invalid.headers["location"]
    restored = client.post("/wizard/row", data={
        "step": "7", "section": "7.0", "equipment_id": scope["equipment_id"],
        "applicable": "1", "reason": "首次啟動檢查",
    }, follow_redirects=False)
    assert "err=" not in restored.headers["location"]
    client.post("/wizard/flags", data={"step": "7", "pssr_na": "1"})
    conn = db.connect(path)
    try:
        missing = wizard.step_missing(conn, WIZARD_SITE_ID, 7)
        assert any("須填理由" in item for item in missing)
        assert any("不得同時聲明" in item for item in missing)
        scope = fil.list_rows(conn, WIZARD_SITE_ID, "7.0")[0]
        fil.delete_row(conn, WIZARD_SITE_ID, scope["row_id"])
        assert any(scope["equipment_id"] in item and "適用性" in item
                   for item in wizard.step_missing(conn, WIZARD_SITE_ID, 7))
    finally:
        conn.close()


def test_emergency_scenario_confirms_multiple_processes_and_linked_scope(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    client.post("/wizard/defaults", data={"step": "12"})
    conn = db.connect(path)
    try:
        scenarios = fil.list_rows(conn, WIZARD_SITE_ID, "12.1s")
        assert len(scenarios) == 2
        assert all(isinstance(r.get("process_ids"), list) for r in scenarios)
        chemical_refs = [r[0] for r in conn.execute("""SELECT process_id||'|'||COALESCE(sds_id,'')||'|'||cas
            FROM chemical WHERE process_id IN ('P-TANK','P-LOAD') AND cas='7664-39-3'
            ORDER BY process_id""")]
        assert len(chemical_refs) >= 2
    finally:
        conn.close()
    invalid = client.post("/wizard/row", data={
        "step": "12", "section": "12.1s", "situation": "火災",
        "description": "跨區域供料火災", "process_ids": ["P-TANK"],
        "equipment_ids": ["LA-101"], "chemical_refs": [chemical_refs[0]],
        "area_codes": ["AREA-A"], "muster": "AREA-M",
    }, follow_redirects=False)
    assert "err=" in invalid.headers["location"]
    valid = client.post("/wizard/row", data={
        "step": "12", "section": "12.1s", "situation": "火災",
        "description": "跨區域供料火災", "process_ids": ["P-TANK", "P-LOAD"],
        "equipment_ids": ["T-101", "LA-101"], "chemical_refs": chemical_refs[:2],
        "area_codes": ["AREA-A", "AREA-B"], "muster": "AREA-M",
        "scope_note": "同一情境跨兩個製程",
        "drill_plan_scope": "應變計畫第 4 節火災演練", "drill_status": "已執行",
        "drill_date": "2026-06-01",
    }, files={"drill_file": ("fire-drill.pdf", b"%PDF-1.4\nQA drill record", "application/pdf")}, follow_redirects=False)
    assert "err=" not in valid.headers["location"]
    conn = db.connect(path)
    try:
        row = next(r for r in fil.list_rows(conn, WIZARD_SITE_ID, "12.1s") if r["situation"] == "火災")
        assert set(row["process_ids"]) == {"P-TANK", "P-LOAD"}
        assert set(row["area_codes"]) == {"AREA-A", "AREA-B"}
        assert row["drill_status"] == "已執行"
        assert wizard.has_uploaded_file(row["drill_record_path"])
        assert not any("火災" in item for item in wizard.step_missing(conn, WIZARD_SITE_ID, 12))
    finally:
        conn.close()


def test_first_filing_audit_followups_are_optional_but_must_link_if_entered(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    client.post("/wizard/flags", data={"step": "13", "audit_first": "否"})
    plan = client.post("/wizard/row", data={
        "step": "13", "section": "13.1", "when": "2026-09-01T09:00",
        "dept_id": "D-OPS", "unit": "製程安全資訊", "auditor": "測試稽核員",
    }, follow_redirects=False)
    assert "err=" not in plan.headers["location"]
    conn = db.connect(path)
    try:
        assert wizard.step_missing(conn, WIZARD_SITE_ID, 13) == wizard.document_gaps(conn, WIZARD_SITE_ID, 13)
    finally:
        conn.close()
    invalid = client.post("/wizard/row", data={
        "step": "13", "section": "13.2", "plan_when": "2025-01-01T09:00",
        "finding": "應變紀錄缺漏", "action": "補正", "dept_id": "D-OPS", "due": "2026-10-01",
    }, follow_redirects=False)
    assert "err=" in invalid.headers["location"]
    valid = client.post("/wizard/row", data={
        "step": "13", "section": "13.2", "plan_when": "2026-09-01T09:00",
        "finding": "應變紀錄缺漏", "action": "補正", "dept_id": "D-OPS", "due": "2026-10-01",
    }, follow_redirects=False)
    assert "err=" not in valid.headers["location"]
    client.post("/wizard/flags", data={"step": "13", "audit_first": "是"})
    conn = db.connect(path)
    try:
        assert any("不得" in item or "但仍有" in item for item in wizard.step_missing(conn, WIZARD_SITE_ID, 13))
    finally:
        conn.close()


def test_legacy_first_filing_incident_migrates_once(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    conn = db.connect(path)
    try:
        conn.execute(
            "INSERT INTO filing_row(site_id,section,payload) VALUES (?,?,?)",
            (WIZARD_SITE_ID, "11.2", json.dumps({
                "incident_id": "INC-OLD-001", "when": "2025-01-01",
                "incident_type": "虛驚", "summary": "舊版事故", "process_id": "P-TANK"
            }, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()
    client.get("/wizard/11")
    conn = db.connect(path)
    try:
        assert conn.execute(
            "SELECT summary FROM incident WHERE incident_id='INC-OLD-001'"
        ).fetchone()[0] == "舊版事故"
        assert not conn.execute(
            "SELECT 1 FROM filing_row WHERE site_id=? AND section='11.2'",
            (WIZARD_SITE_ID,),
        ).fetchone()
    finally:
        conn.close()


def test_pha_scenario_requires_uploaded_record_and_same_process_equipment(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    client.post("/wizard/flags", data={
        "step": "2", "pha_methods_present": "1", "pha_methods": "hazop",
        "consider:hazop": "依製程複雜度採用",
    })
    invalid = client.post("/wizard/row", data={
        "step": "2", "section": "2.4", "assessment_id": "MISSING",
        "process_id": "P-TANK", "equipment_id": "T-101",
        "scenario": "檢驗情境", "safeguard": "現有隔離",
    }, follow_redirects=False)
    assert "err=" in invalid.headers["location"]

    uploaded = client.post("/wizard/2/upload", data={
        "record_id": "PHA-QA-001", "method": "hazop", "question_count": "12",
        "record_date": "2026-09-01",
    }, files={"file": ("pha-qa.pdf", b"%PDF-1.4\n", "application/pdf")}, follow_redirects=False)
    assert "err=" not in uploaded.headers["location"]
    wrong_process = client.post("/wizard/row", data={
        "step": "2", "section": "2.4", "assessment_id": "PHA-QA-001",
        "process_id": "P-TANK", "equipment_id": "LA-101",
        "scenario": "檢驗情境", "safeguard": "現有隔離",
    }, follow_redirects=False)
    assert "err=" in wrong_process.headers["location"]
    valid = client.post("/wizard/row", data={
        "step": "2", "section": "2.4", "assessment_id": "PHA-QA-001",
        "process_id": "P-TANK", "equipment_id": "T-101",
        "scenario": "檢驗情境", "safeguard": "現有隔離",
    }, follow_redirects=False)
    assert "err=" not in valid.headers["location"]
    conn = db.connect(path)
    try:
        record = conn.execute("SELECT method,question_count FROM pha_record WHERE record_id='PHA-QA-001'").fetchone()
        assert (record["method"], record["question_count"]) == ("hazop", 12)
        scenario = conn.execute("SELECT payload FROM filing_row WHERE section='2.4'").fetchone()
        assert json.loads(scenario[0])["equipment_ids"] == ["T-101"]
    finally:
        conn.close()


def test_mi_requires_real_failure_statistics_for_every_critical_equipment(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    client.post("/wizard/defaults", data={"step": "8"})
    conn = db.connect(path)
    try:
        assert any("8.2-1" in item for item in wizard.step_missing(conn, WIZARD_SITE_ID, 8))
        detail_id = conn.execute("SELECT detail_id FROM mi_inspection_detail WHERE equipment_id='T-101'").fetchone()[0]
    finally:
        conn.close()
    confirmed = client.post("/wizard/row", data={
        "step": "8", "section": "8.1", "detail_id": detail_id,
        "equipment_id": "T-101", "mi_type": "壓力容器與儲槽", "damage": "材質相容性",
        "method": "測厚", "freq": "每年", "proc_no": "MI-T-101",
        "pid_no": "PID-TANK-001",
    }, follow_redirects=False)
    assert "err=" not in confirmed.headers["location"]
    saved = client.post("/wizard/8/fail", data={
        "equipment_id": "T-101", "period_start": "2025-01-01",
        "period_end": "2025-12-31", "hours": "0", "repair": "0",
        "note": "2025 年未運行",
    }, follow_redirects=False)
    assert "err=" not in saved.headers["location"]
    conn = db.connect(path)
    try:
        other_equipment = [r[0] for r in conn.execute(
            "SELECT equipment_id FROM equipment WHERE site_id=? AND equipment_id<>'T-101'",
            (WIZARD_SITE_ID,),
        )]
    finally:
        conn.close()
    for eid in other_equipment:
        screened = client.post("/wizard/8/screen", data={
            "equipment_id": eid, "is_critical": "0", "basis": "示範篩選依據，待現場核對",
        }, follow_redirects=False)
        assert "err=" not in screened.headers["location"]
    conn = db.connect(path)
    try:
        assert wizard.step_missing(conn, WIZARD_SITE_ID, 8) == wizard.document_gaps(conn, WIZARD_SITE_ID, 8)
        failure = conn.execute("SELECT run_hours,failure_count,note,confirmed FROM mi_failure WHERE equipment_id='T-101'").fetchone()
        assert (failure["run_hours"], failure["failure_count"], failure["note"], failure["confirmed"]) == (0, 0, "2025 年未運行", 1)
        assert not fil.list_rows(conn, WIZARD_SITE_ID, "8.2")
    finally:
        conn.close()


def test_mi_data_insufficiency_is_saved_without_fabricated_rate(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    client.post("/wizard/defaults", data={"step": "8"})
    conn = db.connect(path)
    try:
        detail_id = conn.execute(
            "SELECT detail_id FROM mi_inspection_detail WHERE equipment_id='T-101'"
        ).fetchone()[0]
    finally:
        conn.close()
    client.post("/wizard/row", data={
        "step": "8", "section": "8.1", "detail_id": detail_id,
        "equipment_id": "T-101", "mi_type": "壓力容器與儲槽",
        "damage": "材質相容性", "method": "測厚", "freq": "每年",
        "proc_no": "MI-T-101", "pid_no": "PID-TANK-001",
    })
    saved = client.post("/wizard/8/fail/gap", data={
        "equipment_id": "T-101", "period_start": "2025-01-01",
        "period_end": "2025-12-31", "reason": "舊系統沒有逐台運轉時數",
    }, follow_redirects=False)
    assert "err=" not in saved.headers["location"]
    conn = db.connect(path)
    try:
        assert conn.execute("SELECT 1 FROM mi_failure_gap WHERE equipment_id='T-101'").fetchone()
        assert not conn.execute("SELECT 1 FROM mi_failure WHERE equipment_id='T-101'").fetchone()
        assert any("T-101" in item and "待人工確認" in item
                   for item in wizard.step_missing(conn, WIZARD_SITE_ID, 8))
        assert all(r["hours"] > 0 for r in wizard.page_extra(conn, WIZARD_SITE_ID, 8)["mi_category_rates"])
    finally:
        conn.close()
    assert "資料不足已註明原因" in client.get("/report").text or "資料不足待人工確認" in client.get("/report").text
    numeric = client.post("/wizard/8/fail", data={
        "equipment_id": "T-101", "period_start": "2025-01-01",
        "period_end": "2025-12-31", "hours": "100", "repair": "1", "note": "原始資料已核對",
    }, follow_redirects=False)
    assert "err=" not in numeric.headers["location"]
    conn = db.connect(path)
    try:
        assert not conn.execute("SELECT 1 FROM mi_failure_gap WHERE equipment_id='T-101'").fetchone()
        assert conn.execute("SELECT run_hours FROM mi_failure WHERE equipment_id='T-101'").fetchone()[0] == 100
    finally:
        conn.close()


def test_mi_maps_each_damage_or_function_item_to_its_own_inspection(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    client.post("/wizard/8/screen", data={
        "equipment_id": "T-101", "is_critical": "1", "basis": "承壓設備",
    })
    for fields in (
        {"damage": "均勻腐蝕", "method": "測厚", "freq": "每年"},
        {"inspection_item": "液位警報功能", "method": "功能測試", "freq": "每季"},
    ):
        response = client.post("/wizard/row", data={
            "step": "8", "section": "8.1", "equipment_id": "T-101",
            "mi_type": "壓力容器與儲槽",
            "proc_no": "MI-T-101", "pid_no": "PID-TANK-001", **fields,
        }, follow_redirects=False)
        assert "err=" not in response.headers["location"]
    mixed = client.post("/wizard/row", data={
        "step": "8", "section": "8.1", "equipment_id": "T-101",
        "mi_type": "壓力容器與儲槽",
        "damage": "均勻腐蝕,局部腐蝕", "method": "測厚", "freq": "每年",
        "proc_no": "MI-T-101", "pid_no": "PID-TANK-001",
    }, follow_redirects=False)
    assert "err=" in mixed.headers["location"]
    missing_category = client.post("/wizard/row", data={
        "step": "8", "section": "8.1", "equipment_id": "T-101",
        "inspection_item": "緊急切斷功能", "method": "功能測試", "freq": "每季",
        "proc_no": "MI-T-101", "pid_no": "PID-TANK-001",
    }, follow_redirects=False)
    assert "err=" in missing_category.headers["location"]
    rejected_false = client.post("/wizard/8/screen", data={
        "equipment_id": "T-101", "is_critical": "0", "basis": "改判理由",
    }, follow_redirects=False)
    assert "err=" in rejected_false.headers["location"]
    conn = db.connect(path)
    try:
        category = conn.execute("SELECT mi_type,mi_type_confirmed FROM mi_screen WHERE equipment_id='T-101'").fetchone()
        assert tuple(category) == ("壓力容器與儲槽", 1)
        first_detail_id = conn.execute("SELECT MIN(detail_id) FROM mi_inspection_detail WHERE equipment_id='T-101'").fetchone()[0]
        rows = conn.execute("""SELECT damage_mechanism,inspection_item,inspect_method,
            inspect_frequency FROM mi_inspection_detail WHERE equipment_id='T-101'
            ORDER BY detail_id""").fetchall()
        assert [tuple(r) for r in rows] == [
            ("均勻腐蝕", "", "測厚", "每年"),
            ("", "液位警報功能", "功能測試", "每季"),
        ]
        assert not conn.execute("SELECT 1 FROM filing_row WHERE section='8.1'").fetchone()
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()
    client.post("/wizard/8/screen", data={
        "equipment_id": "P-101", "is_critical": "1", "basis": "設備功能",
    })
    moved = client.post("/wizard/row", data={
        "step": "8", "section": "8.1", "detail_id": first_detail_id,
        "equipment_id": "P-101", "mi_type": "泵浦(轉動設備)",
        "damage": "均勻腐蝕", "method": "測厚", "freq": "每年",
        "proc_no": "MI-P-101", "pid_no": "PID-TANK-001",
    }, follow_redirects=False)
    assert "err=" in moved.headers["location"]


def test_mi_legacy_rows_are_preserved_and_require_confirmation(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    conn = db.connect(path)
    try:
        row_id = fil.add_row(conn, WIZARD_SITE_ID, "8.1", {
            "equipment_id": "T-101", "damage": "腐蝕,振動", "method": "測厚",
            "freq": "每年", "proc_no": "MI-T-101", "pid_no": "PID-TANK-001",
        })
        db.init_schema(conn)
        migrated = conn.execute("SELECT * FROM mi_inspection_detail WHERE legacy_row_id=?", (row_id,)).fetchone()
        assert migrated and migrated["confirmed"] == 0
        assert migrated["damage_mechanism"] == "腐蝕,振動"
        assert conn.execute("SELECT section FROM filing_row WHERE row_id=?", (row_id,)).fetchone()[0] == "8.1-legacy"
        db.init_schema(conn)
        assert conn.execute("SELECT COUNT(*) FROM mi_inspection_detail WHERE legacy_row_id=?", (row_id,)).fetchone()[0] == 1
        assert any("逐項確認" in item or "分列確認" in item for item in wizard.step_missing(conn, WIZARD_SITE_ID, 8))
    finally:
        conn.close()


def test_mi_legacy_failure_rows_keep_source_and_require_review(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    conn = db.connect(path)
    try:
        valid_id = fil.add_row(conn, WIZARD_SITE_ID, "8.2", {
            "equipment_id": "T-101", "period_start": "2025-01-01",
            "period_end": "2025-12-31", "hours": "8000", "repair": "2", "note": "故障紀錄",
        })
        placeholder_id = fil.add_row(conn, WIZARD_SITE_ID, "8.2", {
            "equipment_id": "P-101", "hours": "待由運轉紀錄填入",
            "repair": "待由維修紀錄填入", "note": "示範占位",
        })
        db.init_schema(conn)
        failure = conn.execute("SELECT * FROM mi_failure WHERE equipment_id='T-101'").fetchone()
        assert (failure["run_hours"], failure["failure_count"], failure["confirmed"], failure["legacy_row_id"]) == (8000, 2, 0, valid_id)
        assert not conn.execute("SELECT 1 FROM mi_failure WHERE equipment_id='P-101'").fetchone()
        assert [r[0] for r in conn.execute(
            "SELECT section FROM filing_row WHERE row_id IN (?,?) ORDER BY row_id",
            (valid_id, placeholder_id),
        )] == ["8.2-legacy", "8.2-legacy"]
        db.init_schema(conn)
        assert conn.execute("SELECT COUNT(*) FROM mi_failure WHERE equipment_id='T-101'").fetchone()[0] == 1
    finally:
        conn.close()


def test_mi_category_rate_uses_total_failures_and_hours(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    conn = db.connect(path)
    try:
        for eid in ("T-101", "V-101"):
            conn.execute("""INSERT INTO mi_screen(equipment_id,is_critical,basis,mi_type,mi_type_confirmed)
                VALUES (?,1,'QA','壓力容器與儲槽',1)""", (eid,))
        conn.execute("""INSERT INTO mi_failure(equipment_id,period_start,period_end,run_hours,failure_count,confirmed)
            VALUES ('T-101','2025-01-01','2025-12-31',100,1,1)""")
        conn.execute("""INSERT INTO mi_failure(equipment_id,period_start,period_end,run_hours,failure_count,confirmed)
            VALUES ('V-101','2025-01-01','2025-12-31',900,1,1)""")
        conn.commit()
        category = wizard.page_extra(conn, WIZARD_SITE_ID, 8)["mi_category_rates"]
        assert len(category) == 1
        assert (category[0]["failures"], category[0]["hours"], category[0]["rate"]) == (2, 1000, 2000)
    finally:
        conn.close()
def test_hotwork_answers_cannot_replace_controlled_area(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    conn = db.connect(path)
    try:
        for key, _ in fil.YN9:
            fil.set_flag(conn, WIZARD_SITE_ID, key, "是")
        assert any("9.1-1" in item for item in wizard.step_missing(conn, WIZARD_SITE_ID, 9))
    finally:
        conn.close()


def test_sop_chapter_checks_all_subtables_and_actual_equipment_types(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    conn = db.connect(path)
    try:
        conn.execute("UPDATE site SET declare_no_equipment_types='壓力容器與儲槽' WHERE site_id=?", (WIZARD_SITE_ID,))
        conn.execute("DELETE FROM sop WHERE sop_id='SOP-VESSEL-01'")
        conn.commit()
        assert any("壓力容器與儲槽" in item for item in wizard.sop_type_gaps(conn, WIZARD_SITE_ID))
    finally:
        conn.close()
    client.post("/wizard/defaults", data={"step": "4"})
    conn = db.connect(path)
    try:
        missing = wizard.step_missing(conn, WIZARD_SITE_ID, 4)
        assert any("4.4-1" in item for item in missing)
        fil.set_flag(conn, WIZARD_SITE_ID, "sop_no_temp", "0")
        assert any("4.2-1" in item for item in wizard.step_missing(conn, WIZARD_SITE_ID, 4))
    finally:
        conn.close()


def test_operating_limits_keep_upper_and_lower_deviations_separate(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    conn = db.connect(path)
    try:
        limit_id = conn.execute("""SELECT l.limit_id FROM equipment_limit l
            JOIN equipment e ON e.equipment_id=l.equipment_id
            WHERE e.site_id=? AND l.parameter='壓力' LIMIT 1""", (WIZARD_SITE_ID,)).fetchone()[0]
        assert any("1.5" in item and "數值" in item for item in wizard.step_missing(conn, WIZARD_SITE_ID, 1))
        conn.execute("""UPDATE equipment_limit SET design_high='9',design_low='1',
            safety_high='10',safety_low='0.5' WHERE limit_id=?""", (limit_id,))
        conn.commit()
    finally:
        conn.close()
    combined = client.post("/wizard/row", data={
        "step": "4", "section": "4.4", "equipment_id": "T-101",
        "limits": "高／低", "consequence": "偏移", "correct": "處置",
    }, follow_redirects=False)
    assert "err=" in combined.headers["location"]
    one_side = client.post("/wizard/row", data={
        "step": "4", "section": "4.4", "limit_id": str(limit_id),
        "high_consequence": "壓力過高", "high_correct": "隔離供料",
    }, follow_redirects=False)
    assert "err=" in one_side.headers["location"]
    valid = client.post("/wizard/row", data={
        "step": "4", "section": "4.4", "limit_id": str(limit_id),
        "high_consequence": "壓力過高", "high_correct": "隔離供料",
        "low_na_reason": "此教學條件不設低壓警戒；須現場核對",
    }, follow_redirects=False)
    assert "err=" not in valid.headers["location"]
    conn = db.connect(path)
    try:
        row = next(r for r in fil.list_rows(conn, WIZARD_SITE_ID, "4.4")
                   if str(r.get("limit_id")) == str(limit_id))
        assert row["high_consequence"] == "壓力過高"
        assert row["low_na_reason"]
        assert any("4.4-1" in item for item in wizard.step_missing(conn, WIZARD_SITE_ID, 4))
    finally:
        conn.close()


def test_15_requires_each_equipment_review_and_preserves_limit_identity(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    conn = db.connect(path)
    try:
        missing = wizard.step_missing(conn, WIZARD_SITE_ID, 1)
        assert any("1.5 設備 P-101 尚未確認" in gap for gap in missing)
        conn.execute("DELETE FROM equipment_limit WHERE equipment_id='T-101' AND parameter='溫度'")
        conn.commit()
    finally:
        conn.close()
    payload = {
        "equipment_id": "T-101", "review_parameter": "壓力",
        "p_unit": "bar(g)", "p_design_high": "8", "p_safety_high": "10",
        "p_design_low": "1", "p_safety_low": "0.5",
        "batch_na_reason": "連續供料，無單次批次",
        "cas": "7664-39-3|P-TANK|SDS-HF-001",
    }
    response = client.post("/wizard/1/limit", data=payload, follow_redirects=False)
    assert "err=" not in response.headers["location"]
    conn = db.connect(path)
    try:
        first_id = conn.execute("SELECT limit_id FROM equipment_limit WHERE equipment_id='T-101' AND parameter='壓力'").fetchone()[0]
        review = conn.execute("SELECT * FROM equipment_operating_review WHERE equipment_id='T-101'").fetchone()
        assert json.loads(review["selected_parameters"]) == ["壓力"]
        assert review["batch_na_reason"] == "連續供料，無單次批次"
        assert conn.execute("SELECT sds_id FROM equipment_content WHERE equipment_id='T-101' AND cas='7664-39-3'").fetchone()[0] == "SDS-HF-001"
        assert not any("1.5 設備 T-101" in gap for gap in wizard.operating_review_gaps(conn, WIZARD_SITE_ID))
    finally:
        conn.close()
    response = client.post("/wizard/1/limit", data={**payload, "p_safety_high": "11"}, follow_redirects=False)
    assert "err=" not in response.headers["location"]
    conn = db.connect(path)
    try:
        rows = conn.execute("SELECT limit_id,safety_high FROM equipment_limit WHERE equipment_id='T-101' AND parameter='壓力'").fetchall()
        assert [tuple(r) for r in rows] == [(first_id, "11")]
    finally:
        conn.close()


def test_15_rejects_partial_boundary_and_cross_process_content(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    base = {
        "equipment_id": "P-101", "review_parameter": "壓力",
        "p_design_high": "8", "p_safety_high": "10",
        "batch_na_reason": "連續操作",
        "cas": "7664-39-3|P-TANK|SDS-HF-001",
    }
    incomplete = client.post("/wizard/1/limit", data=base, follow_redirects=False)
    assert "err=" in incomplete.headers["location"]
    cross = client.post("/wizard/1/limit", data={
        **base, "p_low_na_reason": "僅需上限", "cas": "7664-39-3|P-LOAD|SDS-HF-001",
    }, follow_redirects=False)
    assert "err=" in cross.headers["location"]
    conn = db.connect(path)
    try:
        assert not conn.execute("SELECT 1 FROM equipment_operating_review WHERE equipment_id='P-101'").fetchone()
        assert not conn.execute("SELECT 1 FROM equipment_limit WHERE equipment_id='P-101' AND parameter='壓力'").fetchone()
    finally:
        conn.close()


def test_15_all_parameters_na_still_records_batch_and_content_decisions(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    response = client.post("/wizard/1/limit", data={
        "equipment_id": "P-101", "no_parameter_reason": "此設備僅作功能測試，無操作上下限",
        "batch_na_reason": "連續操作，無批次", "no_process_chemical": "1",
        "no_content_reason": "不接觸製程物料",
    }, follow_redirects=False)
    assert "err=" not in response.headers["location"]
    conn = db.connect(path)
    try:
        assert not any("1.5 設備 P-101" in gap for gap in wizard.operating_review_gaps(conn, WIZARD_SITE_ID))
        assert conn.execute("SELECT no_process_chemical FROM equipment_content WHERE equipment_id='P-101'").fetchone()[0] == 1
    finally:
        conn.close()


def test_document_version_upload_once_and_reuse_across_chapters(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    client.post("/wizard/defaults", data={"step": "9"})
    created = client.post("/wizard/document/create", data={
        "step": "9", "purpose": "hotwork_procedure", "document_no": "SAFE-001",
        "title": "動火與變更共用安全程序", "revision_date": "2026-08-01",
    }, files={"file": ("procedure.pdf", b"%PDF-1.4\n", "application/pdf")}, follow_redirects=False)
    assert "err=" not in created.headers["location"]
    conn = db.connect(path)
    try:
        doc_id = conn.execute("SELECT document_id FROM filing_document WHERE document_no='SAFE-001'").fetchone()[0]
        assert not wizard.document_gaps(conn, WIZARD_SITE_ID, 9)
        assert conn.execute("SELECT COUNT(*) FROM filing_document").fetchone()[0] == 1
    finally:
        conn.close()
    duplicate = client.post("/wizard/document/create", data={
        "step": "9", "purpose": "hotwork_procedure", "document_no": "SAFE-001",
        "title": "重複", "revision_date": "2026-08-01",
    }, files={"file": ("duplicate.pdf", b"%PDF-1.4\n", "application/pdf")}, follow_redirects=False)
    assert "err=" in duplicate.headers["location"]
    linked = client.post("/wizard/document/link", data={
        "step": "10", "purpose": "moc_plan", "document_id": doc_id,
    }, follow_redirects=False)
    assert "err=" not in linked.headers["location"]
    conn = db.connect(path)
    try:
        assert not wizard.document_gaps(conn, WIZARD_SITE_ID, 10)
        assert conn.execute("SELECT COUNT(*) FROM filing_document").fetchone()[0] == 1
    finally:
        conn.close()
    report = client.get("/report")
    assert "SAFE-001" in report.text


def test_empty_attachment_does_not_pass_upload_check(tmp_path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    assert not wizard.has_uploaded_file(str(empty))


def test_editing_shared_document_preserves_existing_chapter_references(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    fields = {
        "step": "9", "purpose": "hotwork_procedure", "document_no": "SHARED-EDIT",
        "title": "共用程序", "revision_date": "2026-08-01",
    }
    created = client.post("/wizard/document/create", data=fields,
                          files={"file": ("old.pdf", b"%PDF-1.4\nold", "application/pdf")},
                          follow_redirects=False)
    assert "err=" not in created.headers["location"]
    conn = db.connect(path)
    try:
        document_id = conn.execute("SELECT document_id FROM filing_document WHERE document_no='SHARED-EDIT'").fetchone()[0]
    finally:
        conn.close()
    linked = client.post("/wizard/document/link", data={
        "step": "10", "purpose": "moc_plan", "document_id": document_id,
    }, follow_redirects=False)
    assert "err=" not in linked.headers["location"]
    for files in ({}, {"file": ("replacement.pdf", b"%PDF-1.4\nnew", "application/pdf")}):
        updated = client.post("/wizard/document/create", data={
            **fields, "document_id": str(document_id), "title": "更新的共用程序",
        }, files=files, follow_redirects=False)
        assert updated.status_code == 303
        assert "err=" not in updated.headers["location"]
    conn = db.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM filing_document").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM filing_document_ref WHERE document_id=?", (document_id,)).fetchone()[0] == 2
        stored = conn.execute("SELECT title,attachment_path FROM filing_document WHERE document_id=?", (document_id,)).fetchone()
        assert stored["title"] == "更新的共用程序"
        assert Path(stored["attachment_path"]).read_bytes() == b"%PDF-1.4\nnew"
        assert not wizard.document_gaps(conn, WIZARD_SITE_ID, 9)
        assert not wizard.document_gaps(conn, WIZARD_SITE_ID, 10)
    finally:
        conn.close()


def test_first_filing_moc_without_cases_still_requires_one_procedure(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    client.post("/wizard/flags", data={"step": "10", "moc_none": "是"})
    conn = db.connect(path)
    try:
        missing = wizard.step_missing(conn, WIZARD_SITE_ID, 10)
        assert len(missing) == 1 and "變更管理程序書" in missing[0]
    finally:
        conn.close()

    created = client.post("/wizard/document/create", data={
        "step": "10", "purpose": "moc_plan", "document_no": "MOC-PROC-01",
        "title": "變更管理運作程序", "revision_date": "2026-09-01",
    }, files={"file": ("moc.pdf", b"%PDF-1.4\n", "application/pdf")}, follow_redirects=False)
    assert "err=" not in created.headers["location"]
    conn = db.connect(path)
    try:
        assert not wizard.step_missing(conn, WIZARD_SITE_ID, 10)
        assert conn.execute("SELECT COUNT(*) FROM filing_document").fetchone()[0] == 1
        fil.add_row(conn, WIZARD_SITE_ID, "10.1", {"change_id": "MOC-01"})
        conn.commit()
        assert any("不得同時列變更" in s for s in wizard.step_missing(conn, WIZARD_SITE_ID, 10))
        fil.set_flag(conn, WIZARD_SITE_ID, "moc_none", "否")
        fil.set_flag(conn, WIZARD_SITE_ID, "moc_def", "是")
        fil.set_flag(conn, WIZARD_SITE_ID, "moc_no_case", "1")
        assert any("不得同時聲明尚無案件" in s for s in wizard.step_missing(conn, WIZARD_SITE_ID, 10))
    finally:
        conn.close()


def test_moc_case_links_multiple_processes_and_rejects_cross_process_targets(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    conn = db.connect(path)
    try:
        conn.execute("DELETE FROM filing_row WHERE site_id=? AND section='10.1'", (WIZARD_SITE_ID,))
        fil.set_flag(conn, WIZARD_SITE_ID, "moc_none", "否")
        fil.set_flag(conn, WIZARD_SITE_ID, "moc_def", "是")
        fil.set_flag(conn, WIZARD_SITE_ID, "moc_no_case", "0")
        conn.commit()
        chemical_refs = [
            f"{r['cas']}|{r['process_id']}|{r['sds_id']}"
            for r in conn.execute(
                "SELECT cas,process_id,sds_id FROM chemical WHERE process_id IN ('P-TANK','P-LOAD') ORDER BY process_id"
            )
        ]
    finally:
        conn.close()
    common = {
        "step": "10", "section": "10.1", "change_id": "MOC-MULTI-01",
        "name": "兩製程隔離邏輯調整", "description": "共同隔離程序調整",
        "process_ids": ["P-TANK", "P-LOAD"],
        "equipment_ids": ["P-101", "LA-101"], "chemical_refs": chemical_refs,
    }
    saved = client.post("/wizard/row", data=common, follow_redirects=False)
    assert "err=" not in saved.headers["location"]
    conn = db.connect(path)
    try:
        rows = fil.list_rows(conn, WIZARD_SITE_ID, "10.1")
        assert len(rows) == 1
        assert rows[0]["process_ids"] == ["P-TANK", "P-LOAD"]
        assert rows[0]["equipment_ids"] == ["P-101", "LA-101"]
        assert rows[0]["chemical_refs"] == chemical_refs
        assert wizard.step_missing(conn, WIZARD_SITE_ID, 10) == wizard.document_gaps(conn, WIZARD_SITE_ID, 10)
    finally:
        conn.close()
    bad = dict(common, change_id="MOC-BAD-01", process_ids=["P-TANK"])
    blocked = client.post("/wizard/row", data=bad, follow_redirects=False)
    assert "err=" in blocked.headers["location"]
    duplicate = client.post("/wizard/row", data=common, follow_redirects=False)
    assert "err=" in duplicate.headers["location"]
    conn = db.connect(path)
    try:
        assert len(fil.list_rows(conn, WIZARD_SITE_ID, "10.1")) == 1
    finally:
        conn.close()

def test_emergency_gear_quantity_and_unit_are_separate_and_grouped_safely(tmp_path, monkeypatch):
    client, path = _client(tmp_path, monkeypatch)
    bad = client.post("/wizard/row", data={
        "step": "12", "section": "12.2", "name": "吸附材",
        "area_code": "AREA-A", "qty": "4 具", "unit": "具", "freq": "每月",
    }, follow_redirects=False)
    assert "err=" in bad.headers["location"]
    for qty, unit in (("4", "具"), ("2", "具"), ("3", "箱")):
        saved = client.post("/wizard/row", data={
            "step": "12", "section": "12.2", "name": "吸附材",
            "area_code": "AREA-A", "qty": qty, "unit": unit, "freq": "每月",
        }, follow_redirects=False)
        assert "err=" not in saved.headers["location"]
    conn = db.connect(path)
    try:
        totals = wizard.page_extra(conn, WIZARD_SITE_ID, 12)["gear_totals"]
        assert {(row["unit"], row["quantity"]) for row in totals} == {("具", "6"), ("箱", "3")}
    finally:
        conn.close()
