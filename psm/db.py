"""關聯式 schema。子表只存 ID，禁止複製父表名稱欄。"""

from __future__ import annotations

import contextvars
import json
import os
import sqlite3
from datetime import date
from math import isfinite
from pathlib import Path

# demo = HF 示範廠；wizard = 首次填報場所。V8.3 HF 案例使用獨立檔案保留舊案例資料。
db_mode: contextvars.ContextVar[str] = contextvars.ContextVar("psm_db_mode", default="demo")
wizard_case: contextvars.ContextVar[str] = contextvars.ContextVar("psm_wizard_case", default="hf")

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS site (
    site_id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    site_name TEXT NOT NULL,
    scope TEXT NOT NULL,
    applicant_name TEXT NOT NULL,
    assessment_base_date TEXT NOT NULL,
    worker_count INTEGER NOT NULL DEFAULT 0,
    declare_no_contractor INTEGER NOT NULL DEFAULT 0,
    declare_no_hotwork INTEGER NOT NULL DEFAULT 0,
    declare_no_equipment_types TEXT NOT NULL DEFAULT '',
    declare_no_incident_5y INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS department (
    dept_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES site(site_id),
    name TEXT NOT NULL,
    parent_dept_id TEXT REFERENCES department(dept_id),
    headcount INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS process (
    process_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES site(site_id),
    name TEXT NOT NULL,
    overview TEXT NOT NULL DEFAULT '',
    operating_dept_id TEXT NOT NULL REFERENCES department(dept_id),
    mode TEXT NOT NULL CHECK (mode IN ('continuous', 'batch')),
    has_chemical_reaction INTEGER NOT NULL,
    has_overpressure INTEGER NOT NULL,
    is_special INTEGER NOT NULL,
    is_loading INTEGER NOT NULL DEFAULT 0,
    is_downstream INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS area (
    area_code TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES site(site_id),
    name TEXT NOT NULL,
    drawing_no TEXT NOT NULL,
    revision TEXT NOT NULL,
    issue_date TEXT NOT NULL,
    process_id TEXT REFERENCES process(process_id),
    attachment_path TEXT NOT NULL,
    is_assembly_point INTEGER NOT NULL DEFAULT 0,
    is_control_room INTEGER NOT NULL DEFAULT 0,
    is_fire_system INTEGER NOT NULL DEFAULT 0,
    worker_count INTEGER NOT NULL DEFAULT 0,
    contractor_count INTEGER NOT NULL DEFAULT 0,
    visitor_count INTEGER NOT NULL DEFAULT 0,
    linked_cas TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sds (
    sds_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES site(site_id),
    substance_or_mixture_name TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '1',
    revise_date TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL,
    component_cas_list TEXT NOT NULL DEFAULT '',
    ppe_level TEXT,
    filter_type TEXT
);

CREATE TABLE IF NOT EXISTS chemical_cite (
    cas TEXT NOT NULL,
    process_id TEXT NOT NULL REFERENCES process(process_id),
    PRIMARY KEY (cas, process_id)
);

CREATE TABLE IF NOT EXISTS equipment (
    equipment_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES site(site_id),
    process_id TEXT NOT NULL REFERENCES process(process_id),
    maint_dept_id TEXT NOT NULL REFERENCES department(dept_id),
    name TEXT NOT NULL,
    alias TEXT,
    equipment_type TEXT NOT NULL CHECK (equipment_type IN (
        '壓力容器與儲槽','管線系統','釋放及排放系統','緊急停車系統',
        '控制系統','動力來源','裝卸及輸送','其他'
    )),
    power_kind TEXT CHECK (power_kind IS NULL OR power_kind IN ('泵浦','氣動','其他')),
    phase_class TEXT NOT NULL CHECK (phase_class IN ('粉狀固體','粒狀固體','液體','氣體','後段處理')),
    is_safety_critical INTEGER NOT NULL,
    is_regulated_machinery INTEGER NOT NULL DEFAULT 0,
    is_high_pressure_gas INTEGER NOT NULL DEFAULT 0,
    area_code TEXT REFERENCES area(area_code),
    material TEXT,
    material_category TEXT,
    legal_cert_type TEXT
);

CREATE TABLE IF NOT EXISTS chemical (
    cas TEXT NOT NULL,
    process_id TEXT NOT NULL REFERENCES process(process_id),
    sds_id TEXT NOT NULL REFERENCES sds(sds_id),
    name TEXT NOT NULL,
    name_en TEXT,
    role TEXT NOT NULL CHECK (role IN ('原物料','原料','中間產物','產物','副產物','觸媒','清洗劑')),
    un_number TEXT,
    transport_hazard_class TEXT,
    concentration_range TEXT,
    h_codes TEXT NOT NULL DEFAULT '',
    purity_or_mixture TEXT NOT NULL DEFAULT '純物質',
    mixture_name TEXT,
    pct_low REAL,
    pct_high REAL,
    pct_basis TEXT,
    mixture_qty REAL,
    attributed_qty REAL,
    phase_state TEXT NOT NULL DEFAULT '',
    aqueous_status TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (process_id, sds_id, cas),
    FOREIGN KEY (cas, process_id) REFERENCES chemical_cite(cas, process_id)
);

CREATE TABLE IF NOT EXISTS area_process (
    area_code TEXT NOT NULL REFERENCES area(area_code),
    process_id TEXT NOT NULL REFERENCES process(process_id),
    PRIMARY KEY (area_code, process_id)
);

CREATE TABLE IF NOT EXISTS area_equipment (
    area_code TEXT NOT NULL REFERENCES area(area_code),
    equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
    PRIMARY KEY (area_code, equipment_id)
);

CREATE TABLE IF NOT EXISTS area_chemical (
    area_code TEXT NOT NULL REFERENCES area(area_code),
    process_id TEXT NOT NULL,
    sds_id TEXT NOT NULL,
    cas TEXT NOT NULL,
    PRIMARY KEY (area_code, process_id, sds_id, cas),
    FOREIGN KEY (process_id, sds_id, cas) REFERENCES chemical(process_id, sds_id, cas)
);

CREATE TABLE IF NOT EXISTS pec_map (
    process_id TEXT NOT NULL REFERENCES process(process_id),
    equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
    cas TEXT NOT NULL DEFAULT '',
    sds_id TEXT NOT NULL DEFAULT '',
    no_process_chemical INTEGER NOT NULL DEFAULT 0,
    h_codes TEXT NOT NULL DEFAULT '',
    material TEXT,
    may_remain INTEGER NOT NULL DEFAULT 0,
    review_notes TEXT,
    confirmed INTEGER NOT NULL DEFAULT 0,
    na_reason TEXT,
    PRIMARY KEY (process_id, equipment_id, cas, sds_id)
);

CREATE TABLE IF NOT EXISTS prompt_event (
    prompt_id TEXT PRIMARY KEY,
    rule_id TEXT NOT NULL,
    process_id TEXT NOT NULL REFERENCES process(process_id),
    equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
    cas TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL CHECK (stage IN ('pha', 'mi')),
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'accepted', 'not_applicable')),
    na_reason TEXT,
    UNIQUE (rule_id, process_id, equipment_id, cas, stage)
);

CREATE TABLE IF NOT EXISTS pid_drawing (
    drawing_no TEXT NOT NULL,
    revision TEXT NOT NULL,
    process_id TEXT NOT NULL REFERENCES process(process_id),
    name TEXT NOT NULL,
    issue_date TEXT NOT NULL,
    is_as_built INTEGER NOT NULL,
    attachment_path TEXT NOT NULL,
    eval_record_no TEXT,
    diagram_kind TEXT NOT NULL DEFAULT 'P&ID' CHECK (diagram_kind IN ('PFD','P&ID')),
    PRIMARY KEY (drawing_no, revision)
);

CREATE TABLE IF NOT EXISTS pid_covering (
    drawing_no TEXT NOT NULL,
    revision TEXT NOT NULL,
    equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
    PRIMARY KEY (drawing_no, revision, equipment_id),
    FOREIGN KEY (drawing_no, revision) REFERENCES pid_drawing(drawing_no, revision)
);

CREATE TABLE IF NOT EXISTS unstructured_attachment (
    attachment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    process_id TEXT REFERENCES process(process_id),
    kind TEXT NOT NULL,
    original_name TEXT,
    attachment_path TEXT NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS filing_document (
    document_id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL REFERENCES site(site_id),
    document_no TEXT NOT NULL,
    title TEXT NOT NULL,
    revision_date TEXT NOT NULL,
    attachment_path TEXT NOT NULL,
    UNIQUE(site_id, document_no, revision_date)
);

CREATE TABLE IF NOT EXISTS filing_document_ref (
    site_id TEXT NOT NULL REFERENCES site(site_id),
    step INTEGER NOT NULL CHECK(step BETWEEN 1 AND 14),
    purpose TEXT NOT NULL,
    document_id INTEGER NOT NULL REFERENCES filing_document(document_id),
    PRIMARY KEY(site_id, step, purpose, document_id)
);

CREATE TABLE IF NOT EXISTS pha_record (
    record_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES site(site_id),
    method TEXT NOT NULL,
    question_count INTEGER NOT NULL CHECK (question_count >= 0),
    record_date TEXT NOT NULL,
    attachment_id INTEGER NOT NULL REFERENCES unstructured_attachment(attachment_id)
);

CREATE TABLE IF NOT EXISTS esd_scenario (
    scenario_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL REFERENCES process(process_id),
    esd_equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
    name TEXT NOT NULL,
    trigger_conditions TEXT NOT NULL,
    maint_dept_id TEXT REFERENCES department(dept_id)
);

CREATE TABLE IF NOT EXISTS esd_action (
    scenario_id TEXT NOT NULL REFERENCES esd_scenario(scenario_id),
    equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
    PRIMARY KEY (scenario_id, equipment_id)
);

CREATE TABLE IF NOT EXISTS sop (
    sop_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL REFERENCES process(process_id),
    title TEXT NOT NULL,
    procedure_no TEXT,
    body TEXT,
    op_kind TEXT NOT NULL DEFAULT 'process' CHECK (op_kind IN ('process', 'equipment')),
    equipment_id TEXT REFERENCES equipment(equipment_id),
    updated_on TEXT
);

CREATE TABLE IF NOT EXISTS sop_equipment (
    sop_id TEXT NOT NULL REFERENCES sop(sop_id) ON DELETE CASCADE,
    equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id) ON DELETE CASCADE,
    confirmed INTEGER NOT NULL DEFAULT 0 CHECK (confirmed IN (0, 1)),
    PRIMARY KEY (sop_id, equipment_id)
);

CREATE TABLE IF NOT EXISTS assessment (
    assessment_id TEXT PRIMARY KEY,
    process_id TEXT REFERENCES process(process_id),
    method TEXT NOT NULL,
    matrix_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','complete')),
    assessment_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assessment_scope (
    assessment_id TEXT NOT NULL REFERENCES assessment(assessment_id),
    process_id TEXT NOT NULL REFERENCES process(process_id),
    PRIMARY KEY (assessment_id, process_id)
);

CREATE TABLE IF NOT EXISTS node (
    node_id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES assessment(assessment_id),
    process_id TEXT NOT NULL REFERENCES process(process_id),
    description TEXT NOT NULL,
    deviation TEXT NOT NULL,
    cause TEXT NOT NULL,
    drawing_no TEXT,
    drawing_revision TEXT,
    considers_location INTEGER NOT NULL DEFAULT 0,
    considers_human INTEGER NOT NULL DEFAULT 0,
    considers_control_failure INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS node_equipment (
    node_id TEXT NOT NULL REFERENCES node(node_id),
    equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
    PRIMARY KEY (node_id, equipment_id)
);

CREATE TABLE IF NOT EXISTS node_chemical (
    node_id TEXT NOT NULL REFERENCES node(node_id),
    cas TEXT NOT NULL,
    process_id TEXT NOT NULL,
    PRIMARY KEY (node_id, cas, process_id),
    FOREIGN KEY (cas, process_id) REFERENCES chemical_cite(cas, process_id)
);

CREATE TABLE IF NOT EXISTS consequence (
    consequence_id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL REFERENCES node(node_id),
    description TEXT NOT NULL,
    disaster_type TEXT NOT NULL,
    area_code TEXT REFERENCES area(area_code)
);

CREATE TABLE IF NOT EXISTS safeguard (
    safeguard_id TEXT PRIMARY KEY,
    consequence_id TEXT NOT NULL REFERENCES consequence(consequence_id),
    equipment_id TEXT REFERENCES equipment(equipment_id),
    scenario_id TEXT REFERENCES esd_scenario(scenario_id),
    sop_id TEXT REFERENCES sop(sop_id),
    CHECK (
        (equipment_id IS NOT NULL AND scenario_id IS NULL AND sop_id IS NULL)
        OR (equipment_id IS NULL AND scenario_id IS NOT NULL AND sop_id IS NULL)
        OR (equipment_id IS NULL AND scenario_id IS NULL AND sop_id IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS risk_score (
    risk_id TEXT PRIMARY KEY,
    consequence_id TEXT NOT NULL REFERENCES consequence(consequence_id),
    matrix_version TEXT NOT NULL,
    severity INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 5),
    likelihood INTEGER NOT NULL CHECK (likelihood BETWEEN 1 AND 5),
    rank_label TEXT NOT NULL,
    rank_value INTEGER NOT NULL,
    lopa_freq TEXT,
    pfd TEXT,
    stale INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS inventory (
    cas TEXT NOT NULL,
    process_id TEXT NOT NULL,
    max_kg REAL NOT NULL,
    area_code TEXT NOT NULL REFERENCES area(area_code),
    calc_note TEXT,
    PRIMARY KEY (cas, process_id),
    FOREIGN KEY (cas, process_id) REFERENCES chemical_cite(cas, process_id)
);

CREATE TABLE IF NOT EXISTS equipment_limit (
    limit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
    parameter TEXT NOT NULL,
    unit TEXT,
    design_high TEXT,
    design_low TEXT,
    safety_high TEXT,
    safety_low TEXT,
    high_na_reason TEXT NOT NULL DEFAULT '',
    low_na_reason TEXT NOT NULL DEFAULT '',
    note TEXT
);

CREATE TABLE IF NOT EXISTS equipment_operating_review (
    equipment_id TEXT PRIMARY KEY REFERENCES equipment(equipment_id),
    selected_parameters TEXT NOT NULL DEFAULT '[]',
    no_parameter_reason TEXT NOT NULL DEFAULT '',
    batch_quantity REAL,
    batch_unit TEXT NOT NULL DEFAULT '',
    batch_na_reason TEXT NOT NULL DEFAULT '',
    no_content_reason TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS equipment_material (
    equipment_id TEXT PRIMARY KEY REFERENCES equipment(equipment_id),
    material TEXT NOT NULL,
    material_category TEXT NOT NULL DEFAULT '',
    spec TEXT,
    corrosion_allowance TEXT
);

CREATE TABLE IF NOT EXISTS relief_device (
    equipment_id TEXT PRIMARY KEY REFERENCES equipment(equipment_id),
    device_type TEXT NOT NULL,
    set_pressure TEXT,
    design_capacity TEXT,
    pid_drawing_no TEXT,
    pid_revision TEXT,
    released_cas TEXT,
    released_process_id TEXT
);

CREATE TABLE IF NOT EXISTS interlock (
    interlock_id TEXT PRIMARY KEY,
    process_id TEXT REFERENCES process(process_id),
    equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
    name TEXT NOT NULL,
    function_desc TEXT NOT NULL,
    scenario_id TEXT REFERENCES esd_scenario(scenario_id),
    setpoint TEXT
);

CREATE TABLE IF NOT EXISTS chem_hazard_check (
    cas TEXT NOT NULL,
    process_id TEXT NOT NULL,
    sds_id TEXT NOT NULL,
    state TEXT,
    fire INTEGER NOT NULL DEFAULT 0,
    explosion INTEGER NOT NULL DEFAULT 0,
    static INTEGER NOT NULL DEFAULT 0,
    reactivity TEXT,
    toxicity TEXT,
    pel_twa TEXT,
    flash_point TEXT,
    boiling_point TEXT,
    note TEXT,
    PRIMARY KEY (process_id, sds_id, cas),
    FOREIGN KEY (process_id, sds_id, cas) REFERENCES chemical(process_id, sds_id, cas)
);

CREATE TABLE IF NOT EXISTS chem_compatibility (
    compat_id INTEGER PRIMARY KEY AUTOINCREMENT,
    cas_a TEXT NOT NULL,
    process_id_a TEXT NOT NULL,
    cas_b TEXT,
    process_id_b TEXT,
    equipment_id TEXT REFERENCES equipment(equipment_id),
    compatible INTEGER NOT NULL,
    hazard_note TEXT,
    FOREIGN KEY (cas_a, process_id_a) REFERENCES chemical_cite(cas, process_id)
);

CREATE TABLE IF NOT EXISTS chem_handling (
    cas TEXT NOT NULL,
    process_id TEXT NOT NULL,
    storage_notes TEXT,
    process_conditions TEXT,
    emergency_notes TEXT,
    PRIMARY KEY (cas, process_id),
    FOREIGN KEY (cas, process_id) REFERENCES chemical_cite(cas, process_id)
);

CREATE TABLE IF NOT EXISTS explosion_area (
    area_code TEXT NOT NULL REFERENCES area(area_code),
    cas TEXT NOT NULL,
    process_id TEXT NOT NULL,
    sds_id TEXT NOT NULL,
    zone_class TEXT NOT NULL,
    PRIMARY KEY (area_code, process_id, sds_id, cas),
    FOREIGN KEY (process_id, sds_id, cas) REFERENCES chemical(process_id, sds_id, cas)
);

CREATE TABLE IF NOT EXISTS ventilation (
    vent_id INTEGER PRIMARY KEY AUTOINCREMENT,
    area_code TEXT REFERENCES area(area_code),
    equipment_id TEXT REFERENCES equipment(equipment_id),
    vent_type TEXT NOT NULL,
    standard TEXT
);

CREATE TABLE IF NOT EXISTS design_code (
    code_id INTEGER PRIMARY KEY AUTOINCREMENT,
    process_id TEXT REFERENCES process(process_id),
    equipment_id TEXT REFERENCES equipment(equipment_id),
    item TEXT NOT NULL,
    code TEXT NOT NULL,
    material_category TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS design_code_process (
    code_id INTEGER NOT NULL REFERENCES design_code(code_id) ON DELETE CASCADE,
    process_id TEXT NOT NULL REFERENCES process(process_id),
    PRIMARY KEY (code_id, process_id)
);

CREATE TABLE IF NOT EXISTS design_code_equipment (
    code_id INTEGER NOT NULL REFERENCES design_code(code_id) ON DELETE CASCADE,
    equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
    PRIMARY KEY (code_id, equipment_id)
);

CREATE TABLE IF NOT EXISTS design_code_chemical (
    code_id INTEGER NOT NULL REFERENCES design_code(code_id) ON DELETE CASCADE,
    process_id TEXT NOT NULL,
    cas TEXT NOT NULL,
    PRIMARY KEY (code_id, process_id, cas),
    FOREIGN KEY (cas, process_id) REFERENCES chemical_cite(cas, process_id)
);

CREATE TABLE IF NOT EXISTS reaction_info (
    process_id TEXT PRIMARY KEY REFERENCES process(process_id),
    summary TEXT NOT NULL,
    formula TEXT,
    heat TEXT,
    kinds TEXT
);

CREATE TABLE IF NOT EXISTS inspection (
    inspection_id TEXT PRIMARY KEY,
    equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
    inspect_date TEXT NOT NULL,
    inspector TEXT NOT NULL,
    method TEXT NOT NULL,
    result TEXT NOT NULL,
    overdue INTEGER NOT NULL DEFAULT 0,
    defect_open INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS change_request (
    change_id TEXT PRIMARY KEY,
    target_table TEXT NOT NULL CHECK (target_table IN ('Process','Equipment','Chemical')),
    target_pk TEXT NOT NULL,
    description TEXT NOT NULL,
    change_type TEXT,
    status TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    impact_json TEXT
);

CREATE TABLE IF NOT EXISTS incident (
    incident_id TEXT PRIMARY KEY,
    site_id TEXT REFERENCES site(site_id),
    process_id TEXT REFERENCES process(process_id),
    equipment_id TEXT REFERENCES equipment(equipment_id),
    cas TEXT,
    sds_id TEXT REFERENCES sds(sds_id),
    incident_date TEXT,
    summary TEXT NOT NULL,
    is_near_miss INTEGER NOT NULL DEFAULT 0,
    included_in_assessment INTEGER NOT NULL DEFAULT 0,
    casualty TEXT,
    lost_days INTEGER,
    cause TEXT,
    corrective TEXT,
    characteristics TEXT
);

CREATE TABLE IF NOT EXISTS loading_occupancy (
    occupancy_id TEXT PRIMARY KEY,
    equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
    process_id TEXT NOT NULL REFERENCES process(process_id),
    cas TEXT NOT NULL,
    plate_or_container TEXT NOT NULL,
    start_ts TEXT NOT NULL,
    end_ts TEXT,
    FOREIGN KEY (cas, process_id) REFERENCES chemical_cite(cas, process_id)
);

CREATE TABLE IF NOT EXISTS recommendation (
    rec_id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES assessment(assessment_id),
    consequence_id TEXT REFERENCES consequence(consequence_id),
    target_table TEXT,
    target_pk TEXT,
    description TEXT NOT NULL,
    marked_improved INTEGER NOT NULL DEFAULT 0,
    master_updated INTEGER NOT NULL DEFAULT 0,
    reassessed_or_waiver INTEGER NOT NULL DEFAULT 0,
    waiver_by TEXT,
    closed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS worker_activity (
    activity_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL REFERENCES process(process_id),
    activity_type TEXT NOT NULL,
    activity_date TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS training_course (
    course_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL REFERENCES process(process_id),
    name TEXT NOT NULL,
    hours REAL,
    audience TEXT,
    kind TEXT NOT NULL,
    op_kind TEXT NOT NULL DEFAULT 'process' CHECK (op_kind IN ('process', 'equipment')),
    equipment_id TEXT REFERENCES equipment(equipment_id),
    sop_id TEXT REFERENCES sop(sop_id),
    is_moc_related INTEGER NOT NULL DEFAULT 0,
    no_sop_reason TEXT
);

CREATE TABLE IF NOT EXISTS training_course_sop (
    course_id TEXT NOT NULL REFERENCES training_course(course_id),
    sop_id TEXT NOT NULL REFERENCES sop(sop_id),
    PRIMARY KEY (course_id, sop_id)
);

CREATE TABLE IF NOT EXISTS training_record (
    record_id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES training_course(course_id),
    trainee TEXT NOT NULL,
    train_date TEXT NOT NULL,
    tested INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS hotwork_permit (
    permit_id TEXT PRIMARY KEY,
    equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
    area_code TEXT REFERENCES area(area_code),
    permit_date TEXT NOT NULL,
    measures TEXT
);

CREATE TABLE IF NOT EXISTS contractor_incident (
    incident_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES site(site_id),
    contractor_id INTEGER REFERENCES contractor(contractor_id),
    contractor_name TEXT NOT NULL,
    contract_period TEXT,
    occur_date TEXT,
    incident_type TEXT NOT NULL CHECK (incident_type IN ('職業災害','虛驚')),
    summary TEXT NOT NULL,
    casualty TEXT,
    lost_days INTEGER,
    cause TEXT,
    process_id TEXT REFERENCES process(process_id),
    equipment_id TEXT REFERENCES equipment(equipment_id),
    corrective TEXT,
    linked_incident_id TEXT REFERENCES incident(incident_id)
);

CREATE TABLE IF NOT EXISTS contractor (
    contractor_id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL REFERENCES site(site_id),
    name TEXT NOT NULL,
    contract_period TEXT NOT NULL,
    work_description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS hotwork_zone (
    area_code TEXT PRIMARY KEY REFERENCES area(area_code),
    is_explosion_zone INTEGER NOT NULL DEFAULT 0,
    explosion_note TEXT,
    protection_reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS process_route (
    route_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES site(site_id),
    note TEXT
);

CREATE TABLE IF NOT EXISTS process_route_block (
    route_id TEXT NOT NULL REFERENCES process_route(route_id),
    seq_no INTEGER NOT NULL,
    process_id TEXT NOT NULL REFERENCES process(process_id),
    note TEXT,
    PRIMARY KEY (route_id, seq_no)
);

CREATE TABLE IF NOT EXISTS process_route_equipment (
    route_id TEXT NOT NULL,
    seq_no INTEGER NOT NULL,
    equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
    PRIMARY KEY (route_id, seq_no, equipment_id),
    FOREIGN KEY (route_id, seq_no) REFERENCES process_route_block(route_id, seq_no)
);

CREATE TABLE IF NOT EXISTS process_route_chemical (
    route_id TEXT NOT NULL,
    seq_no INTEGER NOT NULL,
    process_id TEXT NOT NULL,
    cas TEXT NOT NULL,
    PRIMARY KEY (route_id, seq_no, process_id, cas),
    FOREIGN KEY (route_id, seq_no) REFERENCES process_route_block(route_id, seq_no),
    FOREIGN KEY (cas, process_id) REFERENCES chemical_cite(cas, process_id)
);

CREATE TABLE IF NOT EXISTS pssr (
    pssr_id TEXT PRIMARY KEY,
    equipment_id TEXT REFERENCES equipment(equipment_id),
    process_id TEXT REFERENCES process(process_id),
    change_id TEXT REFERENCES change_request(change_id),
    pssr_date TEXT NOT NULL,
    findings TEXT
);

CREATE TABLE IF NOT EXISTS emergency_org (
    site_id TEXT PRIMARY KEY REFERENCES site(site_id),
    org_summary TEXT NOT NULL,
    command_center TEXT
);

CREATE TABLE IF NOT EXISTS drill (
    drill_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL REFERENCES process(process_id),
    consequence_id TEXT REFERENCES consequence(consequence_id),
    drill_date TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS audit_plan (
    site_id TEXT PRIMARY KEY REFERENCES site(site_id),
    first_done INTEGER NOT NULL DEFAULT 0,
    planned_date TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS audit_checklist (
    item_no INTEGER PRIMARY KEY,
    unit_no INTEGER NOT NULL,
    prompt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trade_secret (
    doc_id TEXT PRIMARY KEY,
    process_id TEXT REFERENCES process(process_id),
    drawing_no TEXT,
    title TEXT NOT NULL,
    ids_selectable INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS meeting (
    meeting_id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES assessment(assessment_id),
    process_id TEXT NOT NULL REFERENCES process(process_id),
    meeting_date TEXT NOT NULL,
    notes TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signoff (
    signoff_id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id TEXT NOT NULL REFERENCES assessment(assessment_id),
    person_name TEXT NOT NULL,
    role TEXT NOT NULL,
    qualified INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS unit_procedure (
    unit_no INTEGER PRIMARY KEY,
    procedure_no TEXT,
    attachment_path TEXT
);

CREATE TABLE IF NOT EXISTS info_access (
    access_id INTEGER PRIMARY KEY AUTOINCREMENT,
    process_id TEXT REFERENCES process(process_id),
    channel TEXT NOT NULL,
    known INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS site_basic_doc (
    site_id TEXT NOT NULL REFERENCES site(site_id),
    item_no INTEGER NOT NULL,
    title TEXT,
    doc_date TEXT,
    file_path TEXT,
    not_applicable INTEGER NOT NULL DEFAULT 0,
    see_also TEXT,
    PRIMARY KEY (site_id, item_no)
);

CREATE TABLE IF NOT EXISTS app_meta (
    k TEXT PRIMARY KEY,
    v TEXT
);

CREATE TABLE IF NOT EXISTS filing_flag (
    site_id TEXT NOT NULL REFERENCES site(site_id),
    k TEXT NOT NULL,
    v TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (site_id, k)
);

CREATE TABLE IF NOT EXISTS filing_row (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL REFERENCES site(site_id),
    section TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS equipment_content (
    equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
    cas TEXT NOT NULL DEFAULT '',
    no_process_chemical INTEGER NOT NULL DEFAULT 0,
    sds_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (equipment_id, cas, sds_id)
);

CREATE TABLE IF NOT EXISTS mi_screen (
    equipment_id TEXT PRIMARY KEY REFERENCES equipment(equipment_id),
    is_critical INTEGER NOT NULL,
    basis TEXT NOT NULL,
    mi_type TEXT NOT NULL DEFAULT '',
    mi_type_confirmed INTEGER NOT NULL DEFAULT 0,
    damage_mechanism TEXT,
    inspect_method TEXT,
    inspect_frequency TEXT,
    procedure_ref TEXT,
    pid_drawing_no TEXT
);

CREATE TABLE IF NOT EXISTS mi_inspection_detail (
    detail_id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
    damage_mechanism TEXT NOT NULL DEFAULT '',
    inspection_item TEXT NOT NULL DEFAULT '',
    inspect_method TEXT NOT NULL DEFAULT '',
    inspect_frequency TEXT NOT NULL DEFAULT '',
    procedure_ref TEXT NOT NULL DEFAULT '',
    pid_drawing_no TEXT NOT NULL DEFAULT '',
    confirmed INTEGER NOT NULL DEFAULT 0,
    legacy_row_id INTEGER UNIQUE,
    CHECK (damage_mechanism<>'' OR inspection_item<>'')
);

CREATE TABLE IF NOT EXISTS mi_failure (
    equipment_id TEXT PRIMARY KEY REFERENCES equipment(equipment_id),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    run_hours REAL NOT NULL,
    failure_count INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    confirmed INTEGER NOT NULL DEFAULT 0,
    legacy_row_id INTEGER UNIQUE
);

CREATE TABLE IF NOT EXISTS mi_failure_gap (
    equipment_id TEXT PRIMARY KEY REFERENCES equipment(equipment_id) ON DELETE CASCADE,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    reason TEXT NOT NULL,
    CHECK (length(trim(reason)) > 0)
);
"""


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _add_col(conn: sqlite3.Connection, table: str, col: str, decl: str) -> None:
    if col not in _table_cols(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def _pk_names(conn: sqlite3.Connection, table: str) -> list[str]:
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [name for _, name in sorted((r[5], r[1]) for r in info if r[5])]


def _repair_stale_parent_names(conn: sqlite3.Connection) -> None:
    """換主鍵時若外鍵開著，子表會改指 table__old。舊表刪掉後，任何寫入都會崩潰。"""
    rows = list(
        conn.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE sql LIKE '%__old%'"
        )
    )
    if not rows:
        return
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("PRAGMA writable_schema=ON")
    try:
        for typ, name, sql in rows:
            fixed = (
                sql.replace(
                    'REFERENCES "chemical__old"(cas, process_id)',
                    "REFERENCES chemical_cite(cas, process_id)",
                )
                .replace(
                    'REFERENCES "chemical__old"(process_id, sds_id, cas)',
                    "REFERENCES chemical(process_id, sds_id, cas)",
                )
                .replace('REFERENCES "assessment__old"', "REFERENCES assessment")
                .replace('REFERENCES "chemical__old"', "REFERENCES chemical")
            )
            if fixed != sql:
                conn.execute(
                    "UPDATE sqlite_master SET sql=? WHERE type=? AND name=?",
                    (fixed, typ, name),
                )
        version = int(conn.execute("PRAGMA schema_version").fetchone()[0])
        conn.execute(f"PRAGMA schema_version={version + 1}")
    finally:
        conn.execute("PRAGMA writable_schema=OFF")
        conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()


def _rebuild_table(conn: sqlite3.Connection, table: str, create_sql: str, select_sql: str) -> None:
    """既有庫的主鍵無法 ALTER，整表換掉。外鍵先關，失敗則把舊表改回。"""
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(f"ALTER TABLE {table} RENAME TO {table}__old")
    try:
        conn.execute(create_sql)
        conn.execute(select_sql)
        conn.execute(f"DROP TABLE {table}__old")
    except Exception:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute(f"ALTER TABLE {table}__old RENAME TO {table}")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _ensure_component_sds(conn: sqlite3.Connection) -> None:
    """舊庫化學品可能只存檔案路徑。先補出 SDS 頂點，再建新主鍵。"""
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "chemical" not in names or "sds" not in names:
        return
    cols = _table_cols(conn, "chemical")
    if "sds_id" not in cols:
        return
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        _fill_component_sds_rows(conn, cols)
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _fill_component_sds_rows(conn: sqlite3.Connection, cols: set[str]) -> None:
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    file_expr = "c.sds_file" if "sds_file" in cols else "''"
    rows = conn.execute(
        f"""SELECT c.rowid AS rid, c.cas, c.process_id, c.name, c.sds_id,
                   {file_expr} AS sds_file, p.site_id
            FROM chemical c
            LEFT JOIN process p ON p.process_id=c.process_id"""
    ).fetchall()
    for r in rows:
        sds_id = (r["sds_id"] or "").strip()
        path = (r["sds_file"] or "").strip()
        if not sds_id:
            if path:
                base = path.replace("\\", "/").rsplit("/", 1)[-1]
                stem = base.rsplit(".", 1)[0] if "." in base else base
                sds_id = stem.replace("placeholder://", "") or f"SDS-{r['cas']}-{r['process_id']}"
            else:
                sds_id = f"SDS-{r['cas']}-{r['process_id']}"
            conn.execute("UPDATE chemical SET sds_id=? WHERE rowid=?", (sds_id, r["rid"]))
        site_id = r["site_id"]
        if not site_id:
            site = conn.execute("SELECT site_id FROM site LIMIT 1").fetchone()
            site_id = site["site_id"] if site else None
        if site_id and not conn.execute("SELECT 1 FROM sds WHERE sds_id=?", (sds_id,)).fetchone():
            conn.execute(
                """INSERT INTO sds(
                    sds_id, site_id, substance_or_mixture_name, file_path, component_cas_list)
                   VALUES (?,?,?,?,?)""",
                (
                    sds_id,
                    site_id,
                    r["name"] or r["cas"],
                    path or f"placeholder://{sds_id}",
                    r["cas"],
                ),
            )
    if "chemical_cite" in names:
        conn.execute(
            """INSERT OR IGNORE INTO chemical_cite(cas, process_id)
               SELECT cas, process_id FROM chemical WHERE cas<>''"""
        )
    if "equipment_content" in names and "sds_id" in _table_cols(conn, "equipment_content"):
        conn.execute(
            """UPDATE equipment_content
               SET sds_id=COALESCE((
                    SELECT c.sds_id FROM chemical c
                    JOIN equipment e ON e.equipment_id=equipment_content.equipment_id
                     AND e.process_id=c.process_id
                    WHERE c.cas=equipment_content.cas AND TRIM(COALESCE(c.sds_id,''))<>''
                    ORDER BY c.sds_id LIMIT 1
               ), '')
               WHERE cas<>'' AND TRIM(COALESCE(sds_id,''))=''"""
        )


def _recover_stranded_tables(conn: sqlite3.Connection) -> None:
    """升級中斷時，資料會留在 table__old，正式表卻是空的。先接回去再換主鍵。"""
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for old in sorted(n for n in names if n.endswith("__old")):
            live = old[: -len("__old")]
            if live not in names:
                conn.execute(f"ALTER TABLE {old} RENAME TO {live}")
                continue
            n_live = conn.execute(f"SELECT COUNT(*) FROM {live}").fetchone()[0]
            n_old = conn.execute(f"SELECT COUNT(*) FROM {old}").fetchone()[0]
            if n_live == 0 and n_old > 0:
                conn.execute(f"DROP TABLE {live}")
                conn.execute(f"ALTER TABLE {old} RENAME TO {live}")
            elif n_old == 0 or n_live >= n_old:
                conn.execute(f"DROP TABLE {old}")
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _align_v83_keys(conn: sqlite3.Connection) -> None:
    """V8.3：化學品列主鍵含 SDS；濃度敏感關聯留 sds_id；2.2 製程可空。"""
    _recover_stranded_tables(conn)
    _ensure_component_sds(conn)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "chemical" in names and _pk_names(conn, "chemical") != ["process_id", "sds_id", "cas"]:
        _rebuild_table(
            conn,
            "chemical",
            """CREATE TABLE chemical (
                cas TEXT NOT NULL,
                process_id TEXT NOT NULL REFERENCES process(process_id),
                sds_id TEXT NOT NULL REFERENCES sds(sds_id),
                name TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('原物料','原料','中間產物','產物','副產物','觸媒','清洗劑')),
                un_number TEXT,
                transport_hazard_class TEXT,
                concentration_range TEXT,
                h_codes TEXT NOT NULL DEFAULT '',
                purity_or_mixture TEXT NOT NULL DEFAULT '純物質',
                mixture_name TEXT,
                pct_low REAL,
                pct_high REAL,
                pct_basis TEXT,
                mixture_qty REAL,
                attributed_qty REAL,
                phase_state TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (process_id, sds_id, cas),
                FOREIGN KEY (cas, process_id) REFERENCES chemical_cite(cas, process_id)
            )""",
            """INSERT INTO chemical(
                cas, process_id, sds_id, name, role, un_number, transport_hazard_class,
                concentration_range, h_codes, purity_or_mixture, mixture_name,
                pct_low, pct_high, pct_basis, mixture_qty, attributed_qty)
               SELECT cas, process_id, sds_id, name, role, un_number, transport_hazard_class,
                concentration_range, COALESCE(h_codes,''), COALESCE(purity_or_mixture,'純物質'),
                mixture_name, pct_low, pct_high, pct_basis, mixture_qty, attributed_qty
               FROM chemical__old""",
        )
    if "pec_map" in names and _pk_names(conn, "pec_map") != [
        "process_id",
        "equipment_id",
        "cas",
        "sds_id",
    ]:
        _rebuild_table(
            conn,
            "pec_map",
            """CREATE TABLE pec_map (
                process_id TEXT NOT NULL REFERENCES process(process_id),
                equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
                cas TEXT NOT NULL DEFAULT '',
                sds_id TEXT NOT NULL DEFAULT '',
                no_process_chemical INTEGER NOT NULL DEFAULT 0,
                h_codes TEXT NOT NULL DEFAULT '',
                material TEXT,
                may_remain INTEGER NOT NULL DEFAULT 0,
                review_notes TEXT,
                confirmed INTEGER NOT NULL DEFAULT 0,
                na_reason TEXT,
                PRIMARY KEY (process_id, equipment_id, cas, sds_id)
            )""",
            """INSERT INTO pec_map(
                process_id, equipment_id, cas, sds_id, no_process_chemical, h_codes,
                material, may_remain, review_notes, confirmed, na_reason)
               SELECT p.process_id, p.equipment_id, p.cas,
                COALESCE(NULLIF(p.sds_id,''), (
                    SELECT c.sds_id FROM chemical c
                    WHERE c.cas=p.cas AND c.process_id=p.process_id AND p.cas<>''
                    ORDER BY c.sds_id LIMIT 1
                ), ''),
                p.no_process_chemical, COALESCE(p.h_codes,''), p.material, p.may_remain,
                p.review_notes, p.confirmed, p.na_reason
               FROM pec_map__old p""",
        )
    if "area_chemical" in names and "sds_id" not in _pk_names(conn, "area_chemical"):
        _rebuild_table(
            conn,
            "area_chemical",
            """CREATE TABLE area_chemical (
                area_code TEXT NOT NULL REFERENCES area(area_code),
                process_id TEXT NOT NULL,
                sds_id TEXT NOT NULL,
                cas TEXT NOT NULL,
                PRIMARY KEY (area_code, process_id, sds_id, cas),
                FOREIGN KEY (process_id, sds_id, cas) REFERENCES chemical(process_id, sds_id, cas)
            )""",
            """INSERT INTO area_chemical(area_code, process_id, sds_id, cas)
               SELECT a.area_code, a.process_id,
                COALESCE(NULLIF(a.sds_id,''), (
                    SELECT c.sds_id FROM chemical c
                    WHERE c.cas=a.cas AND c.process_id=a.process_id
                    ORDER BY c.sds_id LIMIT 1
                )),
                a.cas
               FROM area_chemical__old a
               WHERE COALESCE(NULLIF(a.sds_id,''), (
                    SELECT c.sds_id FROM chemical c
                    WHERE c.cas=a.cas AND c.process_id=a.process_id
                    ORDER BY c.sds_id LIMIT 1
               )) IS NOT NULL""",
        )
    if "equipment_content" in names and _pk_names(conn, "equipment_content") != [
        "equipment_id",
        "cas",
        "sds_id",
    ]:
        _rebuild_table(
            conn,
            "equipment_content",
            """CREATE TABLE equipment_content (
                equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
                cas TEXT NOT NULL DEFAULT '',
                no_process_chemical INTEGER NOT NULL DEFAULT 0,
                sds_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (equipment_id, cas, sds_id)
            )""",
            """INSERT INTO equipment_content(equipment_id, cas, no_process_chemical, sds_id)
               SELECT equipment_id, cas, no_process_chemical, COALESCE(sds_id,'')
               FROM equipment_content__old""",
        )
    if "chem_hazard_check" in names and "sds_id" not in _pk_names(conn, "chem_hazard_check"):
        _rebuild_table(
            conn,
            "chem_hazard_check",
            """CREATE TABLE chem_hazard_check (
                cas TEXT NOT NULL,
                process_id TEXT NOT NULL,
                sds_id TEXT NOT NULL,
                state TEXT,
                fire INTEGER NOT NULL DEFAULT 0,
                explosion INTEGER NOT NULL DEFAULT 0,
                static INTEGER NOT NULL DEFAULT 0,
                reactivity TEXT,
                toxicity TEXT,
                pel_twa TEXT,
                flash_point TEXT,
                boiling_point TEXT,
                note TEXT,
                PRIMARY KEY (process_id, sds_id, cas),
                FOREIGN KEY (process_id, sds_id, cas) REFERENCES chemical(process_id, sds_id, cas)
            )""",
            """INSERT INTO chem_hazard_check(
                cas, process_id, sds_id, state, fire, explosion, static, reactivity,
                toxicity, pel_twa, flash_point, boiling_point, note)
               SELECT h.cas, h.process_id,
                COALESCE(NULLIF(h.sds_id,''), (
                    SELECT c.sds_id FROM chemical c
                    WHERE c.cas=h.cas AND c.process_id=h.process_id
                    ORDER BY c.sds_id LIMIT 1
                )),
                h.state, h.fire, h.explosion, h.static, h.reactivity, h.toxicity,
                h.pel_twa, h.flash_point, h.boiling_point, h.note
               FROM chem_hazard_check__old h
               WHERE COALESCE(NULLIF(h.sds_id,''), (
                    SELECT c.sds_id FROM chemical c
                    WHERE c.cas=h.cas AND c.process_id=h.process_id
                    ORDER BY c.sds_id LIMIT 1
               )) IS NOT NULL""",
        )
    if "explosion_area" in names and "sds_id" not in _pk_names(conn, "explosion_area"):
        _rebuild_table(
            conn,
            "explosion_area",
            """CREATE TABLE explosion_area (
                area_code TEXT NOT NULL REFERENCES area(area_code),
                cas TEXT NOT NULL,
                process_id TEXT NOT NULL,
                sds_id TEXT NOT NULL,
                zone_class TEXT NOT NULL,
                PRIMARY KEY (area_code, process_id, sds_id, cas),
                FOREIGN KEY (process_id, sds_id, cas) REFERENCES chemical(process_id, sds_id, cas)
            )""",
            """INSERT INTO explosion_area(area_code, cas, process_id, sds_id, zone_class)
               SELECT e.area_code, e.cas, e.process_id,
                COALESCE(NULLIF(e.sds_id,''), (
                    SELECT c.sds_id FROM chemical c
                    WHERE c.cas=e.cas AND c.process_id=e.process_id
                    ORDER BY c.sds_id LIMIT 1
                )),
                e.zone_class
               FROM explosion_area__old e
               WHERE COALESCE(NULLIF(e.sds_id,''), (
                    SELECT c.sds_id FROM chemical c
                    WHERE c.cas=e.cas AND c.process_id=e.process_id
                    ORDER BY c.sds_id LIMIT 1
               )) IS NOT NULL""",
        )
    if "assessment" in names:
        info = {r[1]: r for r in conn.execute("PRAGMA table_info(assessment)")}
        proc = info.get("process_id")
        if proc is not None and proc[3]:
            _rebuild_table(
                conn,
                "assessment",
                """CREATE TABLE assessment (
                    assessment_id TEXT PRIMARY KEY,
                    process_id TEXT REFERENCES process(process_id),
                    method TEXT NOT NULL,
                    matrix_version TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','complete')),
                    assessment_date TEXT NOT NULL
                )""",
                """INSERT INTO assessment(
                    assessment_id, process_id, method, matrix_version, status, assessment_date)
                   SELECT assessment_id, process_id, method, matrix_version, status, assessment_date
                   FROM assessment__old""",
            )


def migrate_schema(conn: sqlite3.Connection) -> None:
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "site" in names:
        _add_col(conn, "site", "worker_count", "INTEGER NOT NULL DEFAULT 0")
    if "department" in names:
        _add_col(conn, "department", "headcount", "INTEGER NOT NULL DEFAULT 0")
    if "area" in names:
        _add_col(conn, "area", "is_control_room", "INTEGER NOT NULL DEFAULT 0")
        _add_col(conn, "area", "is_fire_system", "INTEGER NOT NULL DEFAULT 0")
        _add_col(conn, "area", "worker_count", "INTEGER NOT NULL DEFAULT 0")
        _add_col(conn, "area", "contractor_count", "INTEGER NOT NULL DEFAULT 0")
        _add_col(conn, "area", "visitor_count", "INTEGER NOT NULL DEFAULT 0")
        _add_col(conn, "area", "linked_cas", "TEXT NOT NULL DEFAULT ''")
    if "process" in names:
        _add_col(conn, "process", "overview", "TEXT NOT NULL DEFAULT ''")
    if "equipment" in names:
        _add_col(conn, "equipment", "is_regulated_machinery", "INTEGER NOT NULL DEFAULT 0")
        _add_col(conn, "equipment", "is_high_pressure_gas", "INTEGER NOT NULL DEFAULT 0")
        _add_col(conn, "equipment", "material_category", "TEXT")
    if "interlock" in names:
        _add_col(conn, "interlock", "process_id", "TEXT")
    if "equipment_material" in names:
        _add_col(conn, "equipment_material", "material_category", "TEXT NOT NULL DEFAULT ''")
    if "chemical" in names:
        _add_col(conn, "chemical", "h_codes", "TEXT NOT NULL DEFAULT ''")
        _add_col(conn, "chemical", "sds_id", "TEXT")
        _add_col(conn, "chemical", "purity_or_mixture", "TEXT NOT NULL DEFAULT '純物質'")
        _add_col(conn, "chemical", "mixture_name", "TEXT")
        _add_col(conn, "chemical", "pct_low", "REAL")
        _add_col(conn, "chemical", "pct_high", "REAL")
        _add_col(conn, "chemical", "pct_basis", "TEXT")
        _add_col(conn, "chemical", "mixture_qty", "REAL")
        _add_col(conn, "chemical", "attributed_qty", "REAL")
        _add_col(conn, "chemical", "phase_state", "TEXT NOT NULL DEFAULT ''")
        _add_col(conn, "chemical", "aqueous_status", "TEXT NOT NULL DEFAULT ''")
        _add_col(conn, "chemical", "name_en", "TEXT")
    if "pec_map" in names:
        _add_col(conn, "pec_map", "sds_id", "TEXT NOT NULL DEFAULT ''")
    if "area_chemical" in names:
        _add_col(conn, "area_chemical", "sds_id", "TEXT NOT NULL DEFAULT ''")
    if "chem_hazard_check" in names:
        _add_col(conn, "chem_hazard_check", "sds_id", "TEXT NOT NULL DEFAULT ''")
    if "explosion_area" in names:
        _add_col(conn, "explosion_area", "sds_id", "TEXT NOT NULL DEFAULT ''")
    if "training_course" in names:
        _add_col(conn, "training_course", "is_moc_related", "INTEGER NOT NULL DEFAULT 0")
    if "sop" in names:
        _add_col(conn, "sop", "updated_on", "TEXT")
    if "incident" in names:
        _add_col(conn, "incident", "casualty", "TEXT")
        _add_col(conn, "incident", "lost_days", "INTEGER")
        _add_col(conn, "incident", "cause", "TEXT")
        _add_col(conn, "incident", "corrective", "TEXT")
        _add_col(conn, "incident", "characteristics", "TEXT")
        _add_col(conn, "incident", "sds_id", "TEXT")
    if "contractor_incident" in names:
        _add_col(conn, "contractor_incident", "linked_incident_id", "TEXT")
    if "pid_drawing" in names:
        _add_col(conn, "pid_drawing", "eval_record_no", "TEXT")
        _add_col(conn, "pid_drawing", "diagram_kind", "TEXT NOT NULL DEFAULT 'P&ID'")
    if "equipment_content" in names:
        _add_col(conn, "equipment_content", "sds_id", "TEXT")
    if "sop" in names:
        _add_col(conn, "sop", "op_kind", "TEXT NOT NULL DEFAULT 'process'")
        _add_col(conn, "sop", "equipment_id", "TEXT")
        conn.execute("""INSERT OR IGNORE INTO sop_equipment(sop_id,equipment_id,confirmed)
            SELECT s.sop_id,s.equipment_id,0 FROM sop s
            JOIN equipment e ON e.equipment_id=s.equipment_id
            WHERE s.equipment_id IS NOT NULL AND e.process_id=s.process_id""")
    if "training_course" in names:
        _add_col(conn, "training_course", "op_kind", "TEXT NOT NULL DEFAULT 'process'")
        _add_col(conn, "training_course", "equipment_id", "TEXT")
        _add_col(conn, "training_course", "sop_id", "TEXT")
        _add_col(conn, "training_course", "refresh_hours", "REAL")
        _add_col(conn, "training_course", "refresh_every", "TEXT")
        _add_col(conn, "training_course", "no_sop_reason", "TEXT")
    conn.execute("""CREATE TABLE IF NOT EXISTS training_course_sop (
        course_id TEXT NOT NULL REFERENCES training_course(course_id),
        sop_id TEXT NOT NULL REFERENCES sop(sop_id),
        PRIMARY KEY (course_id, sop_id)
    )""")
    conn.execute("""INSERT OR IGNORE INTO training_course_sop(course_id,sop_id)
        SELECT t.course_id,t.sop_id FROM training_course t JOIN sop s ON s.sop_id=t.sop_id
        WHERE t.sop_id IS NOT NULL AND t.sop_id<>''""")
    if "reaction_info" in names:
        _add_col(conn, "reaction_info", "formula", "TEXT")
        _add_col(conn, "reaction_info", "heat", "TEXT")
        _add_col(conn, "reaction_info", "kinds", "TEXT")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sds (
            sds_id TEXT PRIMARY KEY,
            site_id TEXT NOT NULL REFERENCES site(site_id),
            substance_or_mixture_name TEXT NOT NULL,
            version TEXT NOT NULL DEFAULT '1',
            revise_date TEXT NOT NULL DEFAULT '',
            file_path TEXT NOT NULL,
            component_cas_list TEXT NOT NULL DEFAULT '',
            ppe_level TEXT,
            filter_type TEXT
        );
        CREATE TABLE IF NOT EXISTS chemical_cite (
            cas TEXT NOT NULL,
            process_id TEXT NOT NULL REFERENCES process(process_id),
            PRIMARY KEY (cas, process_id)
        );
        CREATE TABLE IF NOT EXISTS area_process (
            area_code TEXT NOT NULL REFERENCES area(area_code),
            process_id TEXT NOT NULL REFERENCES process(process_id),
            PRIMARY KEY (area_code, process_id)
        );
        CREATE TABLE IF NOT EXISTS area_equipment (
            area_code TEXT NOT NULL REFERENCES area(area_code),
            equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
            PRIMARY KEY (area_code, equipment_id)
        );
        CREATE TABLE IF NOT EXISTS area_chemical (
            area_code TEXT NOT NULL REFERENCES area(area_code),
            process_id TEXT NOT NULL,
            sds_id TEXT NOT NULL,
            cas TEXT NOT NULL,
            PRIMARY KEY (area_code, process_id, sds_id, cas),
            FOREIGN KEY (process_id, sds_id, cas) REFERENCES chemical(process_id, sds_id, cas)
        );
        CREATE TABLE IF NOT EXISTS filing_flag (
            site_id TEXT NOT NULL REFERENCES site(site_id),
            k TEXT NOT NULL,
            v TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (site_id, k)
        );
        CREATE TABLE IF NOT EXISTS filing_row (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id TEXT NOT NULL REFERENCES site(site_id),
            section TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS equipment_content (
            equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
            cas TEXT NOT NULL DEFAULT '',
            no_process_chemical INTEGER NOT NULL DEFAULT 0,
            sds_id TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (equipment_id, cas, sds_id)
        );
        CREATE TABLE IF NOT EXISTS contractor_incident (
            incident_id TEXT PRIMARY KEY,
            site_id TEXT NOT NULL REFERENCES site(site_id),
            contractor_name TEXT NOT NULL,
            contract_period TEXT,
            occur_date TEXT,
            incident_type TEXT NOT NULL CHECK (incident_type IN ('職業災害','虛驚')),
            summary TEXT NOT NULL,
            casualty TEXT,
            lost_days INTEGER,
            cause TEXT,
            process_id TEXT REFERENCES process(process_id),
            equipment_id TEXT REFERENCES equipment(equipment_id),
            corrective TEXT
        );
        CREATE TABLE IF NOT EXISTS hotwork_zone (
            area_code TEXT PRIMARY KEY REFERENCES area(area_code),
            is_explosion_zone INTEGER NOT NULL DEFAULT 0,
            explosion_note TEXT,
            protection_reason TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS process_route (
            route_id TEXT PRIMARY KEY,
            site_id TEXT NOT NULL REFERENCES site(site_id),
            note TEXT
        );
        CREATE TABLE IF NOT EXISTS process_route_block (
            route_id TEXT NOT NULL REFERENCES process_route(route_id),
            seq_no INTEGER NOT NULL,
            process_id TEXT NOT NULL REFERENCES process(process_id),
            note TEXT,
            PRIMARY KEY (route_id, seq_no)
        );
        CREATE TABLE IF NOT EXISTS process_route_equipment (
            route_id TEXT NOT NULL,
            seq_no INTEGER NOT NULL,
            equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
            PRIMARY KEY (route_id, seq_no, equipment_id),
            FOREIGN KEY (route_id, seq_no) REFERENCES process_route_block(route_id, seq_no)
        );
        CREATE TABLE IF NOT EXISTS process_route_chemical (
            route_id TEXT NOT NULL,
            seq_no INTEGER NOT NULL,
            process_id TEXT NOT NULL,
            cas TEXT NOT NULL,
            PRIMARY KEY (route_id, seq_no, process_id, cas),
            FOREIGN KEY (route_id, seq_no) REFERENCES process_route_block(route_id, seq_no),
            FOREIGN KEY (cas, process_id) REFERENCES chemical_cite(cas, process_id)
        );
        """
    )
    if "site" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(site)")}
        if "declare_no_contractor" in cols and "declare_no_hotwork" in cols:
            conn.execute(
                "UPDATE site SET declare_no_contractor=0, declare_no_hotwork=0"
            )
    if "unstructured_attachment" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        _add_col(conn, "unstructured_attachment", "site_id", "TEXT")
    if "incident" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        _add_col(conn, "incident", "site_id", "TEXT REFERENCES site(site_id)")
        conn.execute("""UPDATE incident SET site_id=(
            SELECT p.site_id FROM process p WHERE p.process_id=incident.process_id
        ) WHERE site_id IS NULL AND process_id IS NOT NULL""")
        conn.execute("""UPDATE incident SET site_id=(
            SELECT c.site_id FROM contractor_incident c
            WHERE c.linked_incident_id=incident.incident_id LIMIT 1
        ) WHERE site_id IS NULL""")
    if "contractor_incident" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        _add_col(conn, "contractor_incident", "contractor_id", "INTEGER REFERENCES contractor(contractor_id)")
    if "equipment_limit" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        _add_col(conn, "equipment_limit", "high_na_reason", "TEXT NOT NULL DEFAULT ''")
        _add_col(conn, "equipment_limit", "low_na_reason", "TEXT NOT NULL DEFAULT ''")
    if "mi_screen" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        _add_col(conn, "mi_screen", "mi_type", "TEXT NOT NULL DEFAULT ''")
        _add_col(conn, "mi_screen", "mi_type_confirmed", "INTEGER NOT NULL DEFAULT 0")
    if "mi_failure" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        _add_col(conn, "mi_failure", "note", "TEXT NOT NULL DEFAULT ''")
        _add_col(conn, "mi_failure", "confirmed", "INTEGER NOT NULL DEFAULT 0")
        _add_col(conn, "mi_failure", "legacy_row_id", "INTEGER")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS mi_failure_legacy_row_uq ON mi_failure(legacy_row_id)")
    if "filing_row" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        conn.execute("UPDATE filing_row SET section='4.4' WHERE section='4.5'")
    if "design_code" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        _add_col(conn, "design_code", "material_category", "TEXT NOT NULL DEFAULT ''")
        _add_col(conn, "design_code", "scope", "TEXT NOT NULL DEFAULT ''")
    _align_v83_keys(conn)
    if "chemical" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        _add_col(conn, "chemical", "name_en", "TEXT")
    _repair_stale_parent_names(conn)
    _migrate_wizard_incidents(conn)
    _migrate_wizard_contractors(conn)
    _migrate_mi_screen(conn)
    _migrate_mi_details(conn)
    _migrate_mi_failure(conn)
    conn.commit()


def _migrate_wizard_incidents(conn: sqlite3.Connection) -> None:
    """Move old 11.2 JSON rows to the shared incident source once."""
    for row in conn.execute(
        "SELECT row_id, site_id, payload FROM filing_row WHERE section='11.2'"
    ).fetchall():
        try:
            data = json.loads(row["payload"] or "{}")
        except (TypeError, ValueError):
            continue
        incident_id = str(data.get("incident_id") or f"INC-LEGACY-{row['row_id']}").strip()
        summary = str(data.get("summary") or "").strip()
        if not summary:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO incident(
                incident_id, site_id, process_id, equipment_id, cas, incident_date,
                summary, is_near_miss, casualty, lost_days, cause, corrective, characteristics
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                incident_id, row["site_id"], data.get("process_id") or None,
                data.get("equipment_id") or None, data.get("cas") or None,
                data.get("when") or None, summary,
                int(data.get("incident_type") == "虛驚"), data.get("casualty") or None,
                int(data["lost_days"]) if str(data.get("lost_days") or "").isdigit() else None,
                data.get("cause") or None, data.get("corrective") or None,
                data.get("traits") or None,
            ),
        )
        if conn.execute(
            "SELECT 1 FROM incident WHERE incident_id=? AND site_id=?",
            (incident_id, row["site_id"]),
        ).fetchone():
            conn.execute("DELETE FROM filing_row WHERE row_id=?", (row["row_id"],))


def _migrate_wizard_contractors(conn: sqlite3.Connection) -> None:
    """Give existing contractor incidents a roster parent."""
    for row in conn.execute(
        """SELECT incident_id, site_id, contractor_name, contract_period FROM contractor_incident
           WHERE contractor_id IS NULL"""
    ).fetchall():
        name = (row["contractor_name"] or "").strip()
        period = (row["contract_period"] or "").strip()
        if not name or not period:
            continue
        roster = conn.execute(
            """SELECT contractor_id FROM contractor WHERE site_id=?
               AND name=? AND contract_period=? LIMIT 1""", (row["site_id"], name, period)
        ).fetchone()
        if roster:
            contractor_id = roster["contractor_id"]
        else:
            contractor_id = conn.execute(
                """INSERT INTO contractor(site_id,name,contract_period)
                   VALUES (?,?,?)""", (row["site_id"], name, period)
            ).lastrowid
        conn.execute(
            "UPDATE contractor_incident SET contractor_id=? WHERE incident_id=?",
            (contractor_id, row["incident_id"]),
        )


def _migrate_mi_screen(conn: sqlite3.Connection) -> None:
    """Existing 8.1 detail rows represent confirmed critical equipment."""
    for row in conn.execute(
        "SELECT site_id, payload FROM filing_row WHERE section='8.1'"
    ).fetchall():
        try:
            data = json.loads(row["payload"] or "{}")
        except (TypeError, ValueError):
            continue
        eid = str(data.get("equipment_id") or "").strip()
        if not eid or not conn.execute(
            "SELECT 1 FROM equipment WHERE equipment_id=? AND site_id=?", (eid, row["site_id"])
        ).fetchone():
            continue
        conn.execute(
            """INSERT OR IGNORE INTO mi_screen(equipment_id,is_critical,basis)
               VALUES (?,1,'表8.1-1既有安全關鍵設備紀錄')""",
            (eid,),
        )


def _migrate_mi_details(conn: sqlite3.Connection) -> None:
    """Keep old 8.1 payloads, but require a person to confirm each item mapping."""
    for row in conn.execute(
        "SELECT row_id,site_id,payload FROM filing_row WHERE section='8.1'"
    ).fetchall():
        try:
            data = json.loads(row["payload"] or "{}")
        except (TypeError, ValueError):
            continue
        eid = str(data.get("equipment_id") or "").strip()
        if not conn.execute(
            "SELECT 1 FROM equipment WHERE equipment_id=? AND site_id=?", (eid, row["site_id"])
        ).fetchone():
            continue
        damage = str(data.get("damage") or "").strip()
        item = str(data.get("inspection_item") or "").strip()
        if not damage and not item:
            item = "舊版未分類檢查項目，待確認"
        conn.execute(
            """INSERT OR IGNORE INTO mi_inspection_detail
               (equipment_id,damage_mechanism,inspection_item,inspect_method,
                inspect_frequency,procedure_ref,pid_drawing_no,confirmed,legacy_row_id)
               VALUES (?,?,?,?,?,?,?,0,?)""",
            (eid, damage, item, str(data.get("method") or "").strip(),
             str(data.get("freq") or "").strip(), str(data.get("proc_no") or "").strip(),
             str(data.get("pid_no") or "").strip(), row["row_id"]),
        )
        if str(data.get("mi_type") or "").strip():
            conn.execute(
                """UPDATE mi_screen SET mi_type=? WHERE equipment_id=? AND mi_type=''""",
                (str(data["mi_type"]).strip(), eid),
            )
        conn.execute("UPDATE filing_row SET section='8.1-legacy' WHERE row_id=?", (row["row_id"],))
    for screen in conn.execute(
        """SELECT * FROM mi_screen WHERE COALESCE(damage_mechanism,'')<>''
           OR COALESCE(inspect_method,'')<>'' OR COALESCE(inspect_frequency,'')<>''
           OR COALESCE(procedure_ref,'')<>'' OR COALESCE(pid_drawing_no,'')<>''"""
    ).fetchall():
        eid = screen["equipment_id"]
        if not conn.execute(
            "SELECT 1 FROM mi_inspection_detail WHERE equipment_id=?", (eid,)
        ).fetchone():
            conn.execute(
                """INSERT INTO mi_inspection_detail
                   (equipment_id,damage_mechanism,inspection_item,inspect_method,
                    inspect_frequency,procedure_ref,pid_drawing_no,confirmed)
                   VALUES (?,?,?,?,?,?,?,0)""",
                (eid, str(screen["damage_mechanism"] or "").strip(),
                 "" if str(screen["damage_mechanism"] or "").strip() else "舊版未分類檢查項目，待確認",
                 str(screen["inspect_method"] or "").strip(),
                 str(screen["inspect_frequency"] or "").strip(),
                 str(screen["procedure_ref"] or "").strip(),
                 str(screen["pid_drawing_no"] or "").strip()),
            )
        conn.execute(
            """UPDATE mi_screen SET damage_mechanism=NULL,inspect_method=NULL,
               inspect_frequency=NULL,procedure_ref=NULL,pid_drawing_no=NULL
               WHERE equipment_id=?""", (eid,)
        )


def _migrate_mi_failure(conn: sqlite3.Connection) -> None:
    """Archive old JSON rows and only transfer real numeric statistics for review."""
    for row in conn.execute(
        "SELECT row_id,site_id,payload FROM filing_row WHERE section='8.2'"
    ).fetchall():
        try:
            data = json.loads(row["payload"] or "{}")
        except (TypeError, ValueError):
            data = {}
        eid = str(data.get("equipment_id") or "").strip()
        exists = conn.execute(
            "SELECT 1 FROM equipment WHERE equipment_id=? AND site_id=?", (eid, row["site_id"])
        ).fetchone()
        try:
            hours = float(data.get("hours"))
            count = float(data.get("repair"))
            start = str(data.get("period_start") or "")
            end = str(data.get("period_end") or "")
            valid = (isfinite(hours) and isfinite(count) and hours >= 0 and
                     count >= 0 and count.is_integer() and date.fromisoformat(start) <= date.fromisoformat(end))
        except (TypeError, ValueError):
            valid = False
        if valid and exists and not conn.execute(
            "SELECT 1 FROM mi_failure WHERE equipment_id=?", (eid,)
        ).fetchone():
            conn.execute(
                """INSERT INTO mi_failure(equipment_id,period_start,period_end,run_hours,
                   failure_count,note,confirmed,legacy_row_id) VALUES (?,?,?,?,?,?,0,?)""",
                (eid, start, end, hours, int(count), str(data.get("note") or ""), row["row_id"]),
            )
        conn.execute("UPDATE filing_row SET section='8.2-legacy' WHERE row_id=?", (row["row_id"],))


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    migrate_schema(conn)
    conn.commit()


def db_path() -> Path:
    root = Path(__file__).resolve().parent.parent
    data = root / "data"
    data.mkdir(exist_ok=True)
    if db_mode.get() == "wizard":
        if wizard_case.get() == "petrochemical":
            return Path(os.environ.get("PSM_WIZARD_PETRO_DB_PATH") or data / "demo_cases" / "petrochemical-complete.sqlite").resolve()
        case_db = os.environ.get("PSM_WIZARD_DB_PATH")
        if case_db:
            return Path(case_db).resolve()
        return data / "psm_fill_hf.sqlite"
    return data / "psm_demo_hf.sqlite"
