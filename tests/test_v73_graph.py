"""V7.3 手冊實體圖：先定通過條件，再要求 demo schema 同構於必要邊。"""

from __future__ import annotations

import sqlite3

import pytest

from psm.db import connect, init_schema
from psm.errors import PsmError
from psm.seed import seed_demo
from psm import services as svc
from psm.enums import PHASE_CLASSES, SITE_ID
from psm.graph_spec import handbook_graph_audit


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = connect(":memory:")
    init_schema(c)
    return c


@pytest.fixture()
def seeded(conn: sqlite3.Connection) -> sqlite3.Connection:
    seed_demo(conn)
    return conn


def test_handbook_entity_graph_is_sound():
    report = handbook_graph_audit()
    assert report["fail"] == []
    assert "sds" in report["vertices"]
    assert ("chemical_component", "sds") in report["edges"]
    assert ("area_equipment", "equipment") in report["edges"]
    assert ("pec_map", "chemical_component") in report["edges"]
    assert ("inventory", "chemical_cite") in report["edges"]
    assert ("contractor_incident", "incident") in report["edges"]
    assert ("mi_failure", "mi_screen") in report["edges"]
    assert ("pec_map", "chemical_cite") not in report["edges"]
    assert ("assessment", "process") not in report["edges"]
    assert ("interlock", "process") not in report["edges"]


def test_sds_is_independent_vertex(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "sds" in names
    assert "chemical_cite" in names
    assert "area_equipment" in names
    assert "area_process" in names
    assert "area_chemical" in names


def test_same_cas_two_processes_share_one_sds(seeded):
    rows = list(
        seeded.execute(
            "SELECT process_id, sds_id FROM chemical WHERE cas='108-88-3' ORDER BY process_id"
        )
    )
    assert len(rows) == 2
    assert rows[0]["sds_id"] == rows[1]["sds_id"]
    sds_id = rows[0]["sds_id"]
    sds = seeded.execute("SELECT * FROM sds WHERE sds_id=?", (sds_id,)).fetchone()
    assert sds is not None
    assert sds["file_path"]
    cols = {r[1] for r in seeded.execute("PRAGMA table_info(chemical)")}
    assert "sds_id" in cols
    assert "sds_file" not in cols


def test_chemical_cite_covers_pec_and_inventory(seeded):
    cites = {
        (r["cas"], r["process_id"])
        for r in seeded.execute("SELECT cas, process_id FROM chemical_cite")
    }
    chems = {
        (r["cas"], r["process_id"])
        for r in seeded.execute("SELECT cas, process_id FROM chemical")
    }
    assert chems <= cites
    for r in seeded.execute("SELECT cas, process_id FROM pec_map WHERE cas != ''"):
        assert (r["cas"], r["process_id"]) in cites
    fks = list(seeded.execute("PRAGMA foreign_key_list(inventory)"))
    parents = {fk[2] for fk in fks}
    assert "chemical_cite" in parents


def test_area_equipment_not_function_on_equipment(seeded):
    n = seeded.execute("SELECT COUNT(*) FROM area_equipment").fetchone()[0]
    assert n >= 7
    t101 = [
        r["area_code"]
        for r in seeded.execute(
            "SELECT area_code FROM area_equipment WHERE equipment_id='T-101'"
        )
    ]
    assert "AREA-A" in t101
    notnull = {
        r[1]: r[3] for r in seeded.execute("PRAGMA table_info(equipment)")
    }
    assert notnull["area_code"] == 0


def test_equipment_can_belong_to_two_areas(conn):
    svc.save_site(
        conn,
        {
            "site_id": SITE_ID,
            "company_name": "甲",
            "site_name": "場",
            "scope": "x",
            "applicant_name": "a",
            "assessment_base_date": "2026-01-01",
            "worker_count": 1,
        },
    )
    svc.save_department(
        conn, {"dept_id": "D-OPS", "site_id": SITE_ID, "name": "操作課"}
    )
    svc.save_process(
        conn,
        {
            "process_id": "P-TANK",
            "site_id": SITE_ID,
            "name": "儲槽",
            "operating_dept_id": "D-OPS",
            "mode": "continuous",
            "has_chemical_reaction": False,
            "has_overpressure": False,
            "is_special": False,
        },
    )
    for code, name in (("AREA-A", "儲槽區"), ("AREA-B", "裝卸場")):
        svc.save_area(
            conn,
            {
                "area_code": code,
                "site_id": SITE_ID,
                "name": name,
                "drawing_no": "PLOT-001",
                "revision": "A",
                "issue_date": "2026-01-01",
                "attachment_path": "placeholder://p",
            },
        )
    svc.save_equipment(
        conn,
        {
            "equipment_id": "T-101",
            "site_id": SITE_ID,
            "process_id": "P-TANK",
            "maint_dept_id": "D-OPS",
            "name": "儲槽",
            "equipment_type": "壓力容器與儲槽",
            "phase_class": "液體",
            "is_safety_critical": True,
        },
    )
    svc.assign_area_equipment(conn, "AREA-A", ["T-101"])
    svc.assign_area_equipment(conn, "AREA-B", ["T-101"])
    areas = {
        r[0]
        for r in conn.execute(
            "SELECT area_code FROM area_equipment WHERE equipment_id='T-101'"
        )
    }
    assert areas == {"AREA-A", "AREA-B"}


def test_save_chemical_requires_sds_vertex(conn):
    svc.save_site(
        conn,
        {
            "site_id": SITE_ID,
            "company_name": "甲",
            "site_name": "場",
            "scope": "x",
            "applicant_name": "a",
            "assessment_base_date": "2026-01-01",
            "worker_count": 1,
        },
    )
    svc.save_department(
        conn, {"dept_id": "D-OPS", "site_id": SITE_ID, "name": "操作課"}
    )
    svc.save_process(
        conn,
        {
            "process_id": "P-TANK",
            "site_id": SITE_ID,
            "name": "儲槽",
            "operating_dept_id": "D-OPS",
            "mode": "continuous",
            "has_chemical_reaction": False,
            "has_overpressure": False,
            "is_special": False,
        },
    )
    with pytest.raises(PsmError, match="SDS"):
        svc.save_chemical(
            conn,
            {
                "cas": "108-88-3",
                "process_id": "P-TANK",
                "name": "甲苯",
                "role": "原物料",
                "h_codes": "H225",
            },
        )
    svc.save_sds(
        conn,
        {
            "sds_id": "SDS-TOL-001",
            "site_id": SITE_ID,
            "substance_or_mixture_name": "甲苯",
            "file_path": "placeholder://SDS-toluene.pdf",
            "component_cas_list": "108-88-3",
        },
    )
    svc.save_chemical(
        conn,
        {
            "cas": "108-88-3",
            "process_id": "P-TANK",
            "name": "甲苯",
            "role": "原物料",
            "h_codes": "H225",
            "sds_id": "SDS-TOL-001",
        },
    )
    cite = conn.execute(
        "SELECT 1 FROM chemical_cite WHERE cas='108-88-3' AND process_id='P-TANK'"
    ).fetchone()
    assert cite


def test_prompt_event_and_sop_edges_declared(conn):
    fks_pe = {fk[2] for fk in conn.execute("PRAGMA foreign_key_list(prompt_event)")}
    assert "process" in fks_pe
    assert "equipment" in fks_pe
    sop_fks = [fk for fk in conn.execute("PRAGMA foreign_key_list(safeguard)") if fk[3] == "sop_id"]
    assert sop_fks and sop_fks[0][2] == "sop"
    tr_fks = [fk for fk in conn.execute("PRAGMA foreign_key_list(training_course)") if fk[3] == "sop_id"]
    assert tr_fks and tr_fks[0][2] == "sop"


def test_16_material_syncs_to_equipment_and_mi(seeded):
    cols = {r[1] for r in seeded.execute("PRAGMA table_info(equipment_material)")}
    assert "material_category" in cols
    row = seeded.execute(
        "SELECT material, material_category, spec FROM equipment_material WHERE equipment_id='T-101'"
    ).fetchone()
    assert row["material"] == "CS A283"
    assert row["material_category"] == "碳鋼(CS)"
    eq = seeded.execute(
        "SELECT material, material_category FROM equipment WHERE equipment_id='T-101'"
    ).fetchone()
    assert eq["material"] == row["material"]
    assert eq["material_category"] == row["material_category"]
    svc.save_equipment_material(
        seeded,
        {
            "equipment_id": "T-101",
            "material": "SS316L",
            "material_category": "300系不銹鋼",
            "spec": "ASME VIII",
        },
    )
    bound = svc.material_for_mi(seeded, "T-101")
    assert bound["material"] == "SS316L"
    assert bound["material_category"] == "300系不銹鋼"
    eq2 = seeded.execute(
        "SELECT material, material_category FROM equipment WHERE equipment_id='T-101'"
    ).fetchone()
    assert eq2["material"] == "SS316L"
    assert eq2["material_category"] == "300系不銹鋼"


def test_mi_query_ready_needs_category_temp_content(seeded):
    flags = svc.mi_query_ready(seeded, "T-101")
    assert flags["material_category"] == "碳鋼(CS)"
    assert flags["has_temperature"]
    assert flags["has_contents"]
    assert flags["ready"]
    flags_esd = svc.mi_query_ready(seeded, "ESD-101")
    assert flags_esd["ready"] is False
    assert "材質類別（表1.6-1）" in flags_esd["missing"]


def test_mi_cannot_override_16_material(seeded):
    bound = svc.material_for_mi(seeded, "T-101")
    assert bound["material_category"] == "碳鋼(CS)"
    with pytest.raises(PsmError):
        svc.save_equipment_material(
            seeded,
            {
                "equipment_id": "T-101",
                "material": "SS316L",
                "material_category": "不是查詢選項",
            },
        )


def test_demo_does_not_declare_no_contractor_or_hotwork(seeded):
    site = seeded.execute(
        "SELECT declare_no_contractor, declare_no_hotwork FROM site WHERE site_id=?",
        (SITE_ID,),
    ).fetchone()
    assert site["declare_no_contractor"] == 0
    assert site["declare_no_hotwork"] == 0
    assert seeded.execute("SELECT COUNT(*) FROM contractor_incident").fetchone()[0] >= 1
    assert seeded.execute("SELECT COUNT(*) FROM hotwork_zone").fetchone()[0] >= 1
    n_ov = seeded.execute(
        "SELECT COUNT(*) FROM process WHERE TRIM(overview)<>''"
    ).fetchone()[0]
    assert n_ov >= 4
    area_a = seeded.execute(
        "SELECT contractor_count FROM area WHERE area_code='AREA-A'"
    ).fetchone()
    assert area_a["contractor_count"] > 0
    assert "粉狀固體" in PHASE_CLASSES
    assert "粒狀固體" in PHASE_CLASSES
    doc9 = seeded.execute(
        "SELECT not_applicable FROM site_basic_doc WHERE item_no=9"
    ).fetchone()
    assert doc9["not_applicable"] == 0


def test_v83_demo_follows_handbook_sources(seeded):
    """V8.3：事故只登 11.2、6.2 只關聯；材質在 1.6；安全關鍵在 8.1；無反應不填 1.4。"""
    site = seeded.execute(
        "SELECT declare_no_incident_5y FROM site WHERE site_id=?", (SITE_ID,)
    ).fetchone()
    assert site["declare_no_incident_5y"] == 0
    inc = seeded.execute(
        "SELECT summary, is_near_miss, characteristics FROM incident WHERE incident_id='INC-2025-001'"
    ).fetchone()
    assert inc["is_near_miss"] == 1
    assert "吊索" in inc["summary"]
    ctr = seeded.execute(
        "SELECT summary, linked_incident_id, contractor_name FROM contractor_incident WHERE incident_id='CTR-2025-001'"
    ).fetchone()
    assert ctr["linked_incident_id"] == "INC-2025-001"
    assert ctr["contractor_name"] == "大興機械工程有限公司"
    assert (ctr["summary"] or "") == ""
    tol = seeded.execute(
        "SELECT mixture_qty, attributed_qty, purity_or_mixture FROM chemical WHERE cas='108-88-3' AND process_id='P-TANK'"
    ).fetchone()
    assert tol["purity_or_mixture"] == "純物質"
    assert tol["mixture_qty"] is None
    assert tol["attributed_qty"] == 50000
    hcl = seeded.execute(
        "SELECT attributed_qty FROM chemical WHERE cas='7647-01-0'"
    ).fetchone()
    assert hcl["attributed_qty"] == 700
    h2o2 = seeded.execute(
        "SELECT max_kg FROM inventory WHERE cas='7722-84-1'"
    ).fetchone()
    assert h2o2["max_kg"] == 7000
    rxn = {
        r[0]
        for r in seeded.execute("SELECT process_id FROM reaction_info")
    }
    assert rxn == {"P-SCRUB"}
    flags = {
        r[0]: r[1]
        for r in seeded.execute("SELECT equipment_id, is_safety_critical FROM equipment")
    }
    assert all(v == 0 for v in flags.values())
    screen = {
        r[0]: r[1]
        for r in seeded.execute("SELECT equipment_id, is_critical FROM mi_screen")
    }
    assert screen["T-101"] == 1
    assert screen["P-101"] == 0
    assert screen["PSV-101"] == 1
    assert "P-101" not in {
        r[0] for r in seeded.execute("SELECT equipment_id FROM mi_failure")
    }
    asm = seeded.execute(
        "SELECT process_id, is_assembly_point FROM area WHERE area_code='AREA-M'"
    ).fetchone()
    assert asm["process_id"] is None
    assert asm["is_assembly_point"] == 1
    pk = [
        name
        for _, name in sorted(
            (r[5], r[1]) for r in seeded.execute("PRAGMA table_info(chemical)") if r[5]
        )
    ]
    assert pk == ["process_id", "sds_id", "cas"]
    pec = seeded.execute(
        "SELECT sds_id FROM pec_map WHERE equipment_id='T-101' AND cas='108-88-3'"
    ).fetchone()
    assert pec["sds_id"] == "SDS-TOL-001"
    area_chem = seeded.execute(
        "SELECT sds_id FROM area_chemical WHERE cas='108-88-3' AND process_id='P-TANK'"
    ).fetchone()
    assert area_chem["sds_id"] == "SDS-TOL-001"
    hazard = seeded.execute(
        "SELECT sds_id FROM chem_hazard_check WHERE cas='108-88-3' AND process_id='P-TANK'"
    ).fetchone()
    assert hazard["sds_id"] == "SDS-TOL-001"
    expl = seeded.execute(
        "SELECT sds_id FROM explosion_area WHERE area_code='AREA-A' AND cas='108-88-3'"
    ).fetchone()
    assert expl["sds_id"] == "SDS-TOL-001"
    pha = seeded.execute(
        "SELECT process_id FROM assessment WHERE assessment_id='PHA-2026-001'"
    ).fetchone()
    assert pha["process_id"] is None
    node = seeded.execute(
        "SELECT process_id FROM node WHERE node_id='N-01'"
    ).fetchone()
    assert node["process_id"] == "P-TANK"
    asm_link = seeded.execute(
        "SELECT 1 FROM area_process WHERE area_code='AREA-M'"
    ).fetchone()
    assert asm_link is None
    kind = seeded.execute(
        "SELECT diagram_kind FROM pid_drawing WHERE drawing_no='PFD-TANK-001'"
    ).fetchone()
    assert kind["diagram_kind"] == "PFD"


def test_two_sds_same_cas_stay_separate_from_cite(seeded):
    svc.save_sds(
        seeded,
        {
            "sds_id": "SDS-TOL-002",
            "site_id": SITE_ID,
            "substance_or_mixture_name": "回收甲苯",
            "file_path": "placeholder://SDS-toluene-recovered.pdf",
            "component_cas_list": "108-88-3",
        },
    )
    svc.save_chemical(
        seeded,
        {
            "cas": "108-88-3",
            "process_id": "P-TANK",
            "sds_id": "SDS-TOL-002",
            "name": "回收甲苯",
            "role": "原物料",
            "h_codes": "H225",
            "purity_or_mixture": "混合物",
            "mixture_name": "回收溶劑",
            "pct_low": 90,
            "pct_high": 95,
            "pct_basis": "重量比",
            "mixture_qty": 1000,
            "attributed_qty": 950,
        },
    )
    rows = list(
        seeded.execute(
            "SELECT sds_id FROM chemical WHERE cas='108-88-3' AND process_id='P-TANK' ORDER BY sds_id"
        )
    )
    assert [r["sds_id"] for r in rows] == ["SDS-TOL-001", "SDS-TOL-002"]
    cites = seeded.execute(
        "SELECT COUNT(*) FROM chemical_cite WHERE cas='108-88-3' AND process_id='P-TANK'"
    ).fetchone()[0]
    assert cites == 1
    with pytest.raises(PsmError, match="SDS"):
        svc.save_pec_map(
            seeded,
            {
                "process_id": "P-TANK",
                "equipment_id": "T-101",
                "cas": "108-88-3",
            },
        )
    svc.save_pec_map(
        seeded,
        {
            "process_id": "P-TANK",
            "equipment_id": "T-101",
            "cas": "108-88-3",
            "sds_id": "SDS-TOL-002",
        },
    )
    rows_pec = [
        r["sds_id"]
        for r in seeded.execute(
            """SELECT sds_id FROM pec_map
               WHERE equipment_id='T-101' AND cas='108-88-3' ORDER BY sds_id"""
        )
    ]
    assert rows_pec == ["SDS-TOL-001", "SDS-TOL-002"]


def test_phase_class_accepts_solids(conn):
    svc.save_site(
        conn,
        {
            "site_id": SITE_ID,
            "company_name": "甲",
            "site_name": "場",
            "scope": "x",
            "applicant_name": "a",
            "assessment_base_date": "2026-01-01",
            "worker_count": 1,
        },
    )
    svc.save_department(
        conn, {"dept_id": "D-OPS", "site_id": SITE_ID, "name": "操作課"}
    )
    svc.save_process(
        conn,
        {
            "process_id": "P-TANK",
            "site_id": SITE_ID,
            "name": "儲槽",
            "operating_dept_id": "D-OPS",
            "mode": "continuous",
            "has_chemical_reaction": False,
            "has_overpressure": False,
            "is_special": False,
            "overview": "試驗概述",
        },
    )
    svc.save_equipment(
        conn,
        {
            "equipment_id": "S-SOLID",
            "site_id": SITE_ID,
            "process_id": "P-TANK",
            "maint_dept_id": "D-OPS",
            "name": "粉倉",
            "equipment_type": "壓力容器與儲槽",
            "phase_class": "粉狀固體",
            "is_safety_critical": False,
        },
    )
    row = conn.execute(
        "SELECT phase_class FROM equipment WHERE equipment_id='S-SOLID'"
    ).fetchone()
    assert row["phase_class"] == "粉狀固體"
