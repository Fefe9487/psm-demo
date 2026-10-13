"""開站 SPEC §8 與 demo 第 7 節驗收。"""

from __future__ import annotations

import sqlite3

import pytest

from psm.db import connect, init_schema
from psm.enums import MATRIX_VERSION, SITE_ID
from psm.errors import PsmError
from psm.seed import seed_demo
from psm import services as svc


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = connect(":memory:")
    init_schema(c)
    return c


@pytest.fixture()
def seeded(conn: sqlite3.Connection) -> sqlite3.Connection:
    seed_demo(conn)
    return conn


def _dept(conn, dept_id="D-OPS", name="操作課"):
    svc.save_department(
        conn,
        {
            "dept_id": dept_id,
            "site_id": SITE_ID,
            "name": name,
            "parent_dept_id": None,
        },
    )


def _process(conn, process_id="P-TANK", name="儲槽"):
    svc.save_process(
        conn,
        {
            "process_id": process_id,
            "site_id": SITE_ID,
            "name": name,
            "operating_dept_id": "D-OPS",
            "mode": "continuous",
            "has_chemical_reaction": False,
            "has_overpressure": True,
            "is_special": False,
            "is_loading": False,
            "is_downstream": False,
        },
    )


def _area(conn, area_code="AREA-A"):
    svc.save_area(
        conn,
        {
            "area_code": area_code,
            "site_id": SITE_ID,
            "name": "儲槽區",
            "drawing_no": "PLOT-001",
            "revision": "A",
            "issue_date": "2026-01-01",
            "process_id": "P-TANK",
            "attachment_path": "placeholder://AREA-A",
            "is_assembly_point": True,
        },
    )


def _minimal_site_depts_process_area(conn):
    svc.save_site(
        conn,
        {
            "site_id": SITE_ID,
            "company_name": "示範事業股份有限公司",
            "site_name": "測試場所",
            "scope": "測試",
            "applicant_name": "王大明",
            "assessment_base_date": "2026-08-21",
            "declare_no_contractor": True,
            "declare_no_hotwork": True,
            "declare_no_equipment_types": "管線系統,控制系統,其他",
            "declare_no_incident_5y": True,
        },
    )
    _dept(conn, "D-OPS", "操作課")
    _dept(conn, "D-MAINT", "保養課")
    _process(conn)
    _area(conn)


def test_equipment_without_process_id_cannot_save(conn):
    _minimal_site_depts_process_area(conn)
    with pytest.raises(PsmError) as ei:
        svc.save_equipment(
            conn,
            {
                "equipment_id": "T-101",
                "site_id": SITE_ID,
                "process_id": "",
                "maint_dept_id": "D-MAINT",
                "name": "儲槽",
                "alias": None,
                "equipment_type": "壓力容器與儲槽",
                "power_kind": None,
                "phase_class": "液體",
                "is_safety_critical": True,
                "area_code": "AREA-A",
                "material": "CS",
                "legal_cert_type": None,
            },
        )
    assert "process_id" in str(ei.value)


def test_power_source_without_power_kind_cannot_save(conn):
    _minimal_site_depts_process_area(conn)
    with pytest.raises(PsmError) as ei:
        svc.save_equipment(
            conn,
            {
                "equipment_id": "P-101",
                "site_id": SITE_ID,
                "process_id": "P-TANK",
                "maint_dept_id": "D-MAINT",
                "name": "泵浦",
                "alias": None,
                "equipment_type": "動力來源",
                "power_kind": None,
                "phase_class": "液體",
                "is_safety_critical": True,
                "area_code": "AREA-A",
                "material": None,
                "legal_cert_type": None,
            },
        )
    assert "動力" in str(ei.value)


def test_equipment_table_has_no_name_copies_of_parent(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(equipment)")}
    assert "process_name" not in cols
    assert "dept_name" not in cols
    assert "operating_dept_name" not in cols
    assert "maint_dept_name" not in cols
    assert "process_id" in cols
    assert "maint_dept_id" in cols


def test_rename_department_does_not_rewrite_equipment_rows(seeded):
    before = seeded.execute(
        "SELECT maint_dept_id FROM equipment WHERE equipment_id='T-101'"
    ).fetchone()[0]
    assert before == "D-MAINT"
    svc.rename_department(seeded, "D-MAINT", "保養課（更名）")
    after_id = seeded.execute(
        "SELECT maint_dept_id FROM equipment WHERE equipment_id='T-101'"
    ).fetchone()[0]
    assert after_id == "D-MAINT"
    joined = {r["equipment_id"]: r for r in svc.equipment_list_joined(seeded, SITE_ID)}
    assert joined["T-101"]["maint_dept_name"] == "保養課（更名）"
    assert joined["T-101"]["process_name"] == "儲槽"


def test_hazop_equipment_choices_empty_without_process(seeded):
    assert svc.equipment_choices(seeded, None) == []
    assert svc.chemical_choices(seeded, None) == []


def test_hazop_process_tank_cannot_select_la101(seeded):
    ids = [r["equipment_id"] for r in svc.equipment_choices(seeded, "P-TANK")]
    assert "T-101" in ids
    assert "P-101" in ids
    assert "LA-101" not in ids
    assert "PL-201" not in ids
    with pytest.raises(PsmError):
        svc.save_node(
            seeded,
            {
                "node_id": "N-BAD",
                "assessment_id": "PHA-2026-001",
                "process_id": "P-TANK",
                "description": "錯掛裝卸設備",
                "deviation": "誤選",
                "cause": "測試",
                "drawing_no": "PID-TANK-001",
                "drawing_revision": "B",
                "considers_location": True,
                "considers_human": True,
                "considers_control_failure": True,
            },
            equipment_ids=["LA-101"],
            cas_list=["108-88-3"],
        )


def test_pid_without_drawing_no_or_coverage_not_usable_for_hazop(conn):
    _minimal_site_depts_process_area(conn)
    svc.save_equipment(
        conn,
        {
            "equipment_id": "T-101",
            "site_id": SITE_ID,
            "process_id": "P-TANK",
            "maint_dept_id": "D-MAINT",
            "name": "儲槽",
            "alias": None,
            "equipment_type": "壓力容器與儲槽",
            "power_kind": None,
            "phase_class": "液體",
            "is_safety_critical": True,
            "area_code": "AREA-A",
            "material": "CS",
            "legal_cert_type": None,
        },
    )
    svc.save_pid_drawing(
        conn,
        {
            "drawing_no": "",
            "revision": "",
            "process_id": "P-TANK",
            "name": "未登錄圖檔",
            "issue_date": "2026-01-01",
            "is_as_built": True,
            "attachment_path": "uploads/scan.pdf",
        },
        covering_ids=[],
    )
    usable = svc.hazop_usable_drawings(conn, "P-TANK")
    assert usable == []


def test_seeded_pid_is_usable(seeded):
    usable = svc.hazop_usable_drawings(seeded, "P-TANK")
    nos = {(d["drawing_no"], d["revision"]) for d in usable}
    assert ("PID-TANK-001", "B") in nos


def test_esd_incomplete_without_scenario_or_actions(conn):
    _minimal_site_depts_process_area(conn)
    svc.save_equipment(
        conn,
        {
            "equipment_id": "ESD-101",
            "site_id": SITE_ID,
            "process_id": "P-TANK",
            "maint_dept_id": "D-MAINT",
            "name": "緊急停車系統",
            "alias": None,
            "equipment_type": "緊急停車系統",
            "power_kind": None,
            "phase_class": "液體",
            "is_safety_critical": True,
            "area_code": "AREA-A",
            "material": None,
            "legal_cert_type": None,
        },
    )
    st = svc.esd_status(conn, "P-TANK")
    assert st["complete"] is False
    assert "不完備" in st["label"]


def test_seeded_esd_complete(seeded):
    st = svc.esd_status(seeded, "P-TANK")
    assert st["complete"] is True


def test_loading_occupancy_does_not_create_equipment(seeded):
    n_before = seeded.execute("SELECT COUNT(*) FROM equipment").fetchone()[0]
    svc.save_loading_occupancy(
        seeded,
        {
            "occupancy_id": "LOAD-TEST-2",
            "equipment_id": "LA-101",
            "process_id": "P-LOAD",
            "cas": "108-88-3",
            "plate_or_container": "TEST-9999",
            "start_ts": "2026-08-20 08:00",
            "end_ts": "2026-08-20 10:00",
        },
    )
    n_after = seeded.execute("SELECT COUNT(*) FROM equipment").fetchone()[0]
    assert n_after == n_before
    plates = [
        r[0]
        for r in seeded.execute(
            "SELECT plate_or_container FROM loading_occupancy"
        )
    ]
    assert "TEST-9999" in plates
    assert seeded.execute(
        "SELECT COUNT(*) FROM equipment WHERE equipment_id='TEST-9999'"
    ).fetchone()[0] == 0


def test_cannot_score_or_complete_before_masters_ready(conn):
    svc.save_site(
        conn,
        {
            "site_id": SITE_ID,
            "company_name": "X",
            "site_name": "Y",
            "scope": "Z",
            "applicant_name": "A",
            "assessment_base_date": "2026-08-21",
            "declare_no_contractor": True,
            "declare_no_hotwork": True,
            "declare_no_equipment_types": "",
            "declare_no_incident_5y": True,
        },
    )
    ok, reasons = svc.masters_complete(conn, SITE_ID)
    assert ok is False
    assert reasons
    with pytest.raises(PsmError):
        svc.save_risk_score(
            conn,
            {
                "risk_id": "R-X",
                "consequence_id": "C-X",
                "matrix_version": MATRIX_VERSION,
                "severity": 2,
                "likelihood": 2,
            },
        )


def test_seeded_can_score(seeded):
    ok, reasons = svc.masters_complete(seeded, SITE_ID)
    assert ok is True, reasons


def test_recommendation_cannot_close_if_only_marked_improved(seeded):
    seeded.execute(
        """INSERT INTO recommendation
           (rec_id, assessment_id, consequence_id, target_table, target_pk,
            description, marked_improved, master_updated, reassessed_or_waiver, closed)
           VALUES ('REC-BAD', 'PHA-2026-001', 'C-N01-1', '', '',
                   '只勾已改善', 1, 0, 0, 0)"""
    )
    seeded.commit()
    with pytest.raises(PsmError) as ei:
        svc.close_recommendation(seeded, "REC-BAD")
    assert "關閉" in str(ei.value) or "主檔" in str(ei.value)


def test_safeguard_text_only_rejected(seeded):
    with pytest.raises(PsmError):
        svc.save_safeguard(
            seeded,
            {
                "safeguard_id": "SG-TEXT",
                "consequence_id": "C-N01-1",
                "kind": None,
                "equipment_id": None,
                "scenario_id": None,
                "sop_id": None,
                "free_text": "安全閥",
            },
        )


def test_coverage_gap_lists_uncovered_ptank_equipment(seeded):
    gaps = [r["equipment_id"] for r in svc.coverage_gaps(seeded, "P-TANK")]
    assert gaps, "應故意留至少一件未進節點的 P-TANK 設備"
    assert "T-101" not in gaps
    assert "P-101" not in gaps


def test_equipment_sop_must_match_equipment_process(seeded):
    with pytest.raises(PsmError):
        svc.save_sop(
            seeded,
            {
                "sop_id": "SOP-BAD",
                "op_kind": "equipment",
                "equipment_id": "LA-101",
                "process_id": "P-TANK",
                "title": "錯製程",
            },
        )


def test_sop_and_training_board_list_every_process(seeded):
    sop = svc.sop_board(seeded, SITE_ID)
    ids = [p["process_id"] for p in sop["processes"]]
    assert ids == ["P-ACID", "P-LOAD", "P-SCRUB", "P-TANK"]
    tank = next(p for p in sop["processes"] if p["process_id"] == "P-TANK")
    assert any(s["sop_id"] == "SOP-TANK-01" for s in tank["sops"])
    eq_ids = {e["equipment_id"] for e in tank["equipment"]}
    assert {"T-101", "P-101", "PSV-101", "ESD-101"} <= eq_ids
    assert any(s["sop_id"] == "SOP-EQ-T-101" for e in tank["equipment"] for s in e["sops"])
    train = svc.training_board(seeded, SITE_ID)
    assert {p["process_id"] for p in train["processes"]} == {"P-TANK", "P-LOAD", "P-SCRUB", "P-ACID"}
    load = next(p for p in train["processes"] if p["process_id"] == "P-LOAD")
    assert any(c["course_id"] == "COURSE-LOAD-01" for c in load["courses"])
    assert any(c["course_id"] == "COURSE-EQ-LA-101" for e in load["equipment"] for c in e["courses"])


def test_process_inspect_excludes_other_process_equipment(seeded):
    data = svc.process_inspect(seeded, "P-TANK", SITE_ID)
    assert data is not None
    assert {e["equipment_id"] for e in data["equipment"]} <= {"T-101", "P-101", "PSV-101", "ESD-101"}
    assert all(c["cas"] == "108-88-3" for c in data["chemicals"])
    assert svc.process_inspect(seeded, "NOPE", SITE_ID) is None


def test_no_transport_master_table(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "transport" not in names
    assert "vehicle" not in names
    assert "equipment" in names
    assert "process" in names
    assert "chemical" in names
    assert "department" in names


def test_report_has_fourteen_chapters_and_same_ids(seeded):
    html = svc.generate_report_html(seeded, SITE_ID)
    assert "T-101" in html
    assert "108-88-3" in html
    assert "本示範未納入程序書全文" in html
    for i in range(1, 15):
        assert f"3.{i} " in html or f"3.{i}　" in html
    assert "七階段" not in html or "正文空" in html or "未納入程序書" in html
    assert "ABC-1234" in html or "車牌" in html


def test_node_cas_must_belong_to_process(seeded):
    with pytest.raises(PsmError):
        svc.save_node(
            seeded,
            {
                "node_id": "N-CAS-BAD",
                "assessment_id": "PHA-2026-001",
                "process_id": "P-TANK",
                "description": "錯 CAS",
                "deviation": "x",
                "cause": "y",
                "drawing_no": "PID-TANK-001",
                "drawing_revision": "B",
                "considers_location": False,
                "considers_human": False,
                "considers_control_failure": False,
            },
            equipment_ids=["T-101"],
            cas_list=["64-17-5"],
        )


def test_esd_action_must_same_process(seeded):
    with pytest.raises(PsmError):
        svc.save_esd_action(seeded, "ESD-SC-TANK-01", "LA-101")


def test_ptank_hazop_choices_exclude_pl201(seeded):
    ids = [r["equipment_id"] for r in svc.equipment_choices(seeded, "P-TANK")]
    assert "PL-201" not in ids
    cas = [r["cas"] for r in svc.chemical_choices(seeded, "P-TANK")]
    assert "7647-01-0" not in cas


def test_acid_line_writes_prompt_and_leaves_sl_blank(seeded):
    pha = svc.prompt_events(seeded, process_id="P-ACID", stage="pha")
    mi = svc.prompt_events(seeded, process_id="P-ACID", stage="mi")
    assert pha and mi
    assert any("材質條件不相容" in p["message"] or "停車未排淨" in p["message"] for p in pha)
    assert any("碳鋼" in p["message"] or "腐蝕" in p["message"] for p in mi)
    toluene = svc.prompt_events(seeded, process_id="P-TANK")
    assert not any(p["rule_id"] == "R-H314-CS-REMAIN" for p in toluene)
    scores = [
        dict(r)
        for r in seeded.execute(
            """SELECT rs.severity, rs.likelihood FROM risk_score rs
               JOIN consequence c ON c.consequence_id=rs.consequence_id
               WHERE c.node_id='N-ACID-01'"""
        )
    ]
    assert scores == []


def test_incomplete_acid_map_cannot_score(seeded):
    seeded.execute("DELETE FROM prompt_event WHERE process_id='P-ACID'")
    seeded.execute("DELETE FROM pec_map WHERE process_id='P-ACID'")
    seeded.commit()
    with pytest.raises(PsmError):
        svc.save_risk_score(
            seeded,
            {
                "risk_id": "R-ACID-X",
                "consequence_id": "C-ACID-01",
                "matrix_version": MATRIX_VERSION,
                "severity": 3,
                "likelihood": 2,
            },
        )


def test_prompt_na_without_reason_rejected(seeded):
    row = seeded.execute(
        "SELECT prompt_id FROM prompt_event WHERE process_id='P-ACID' AND stage='pha'"
    ).fetchone()
    assert row
    with pytest.raises(PsmError):
        svc.set_prompt_status(seeded, row["prompt_id"], "not_applicable", "")


def test_no_bulk_map_generate_endpoint():
    from psm.web import app
    from fastapi.testclient import TestClient

    routes = {getattr(r, "path", "") for r in app.routes}
    assert "/map/generate" not in routes
    assert not any("generate" in (getattr(r, "path", "") or "") and "map" in (getattr(r, "path", "") or "") for r in app.routes)


def test_report_includes_map_and_prompts_not_as_scores(seeded):
    html = svc.generate_report_html(seeded, SITE_ID)
    assert "對應表" in html
    assert "PL-201" in html
    assert "7647-01-0" in html
    assert "提示事項" in html or "提示" in html
    assert "R-H314-CS-REMAIN" in html
    acid_block = html.split("N-ACID-01", 1)
    if len(acid_block) > 1:
        cell = acid_block[1][:400]
        assert "材質條件不相容" not in cell or "S" in cell

