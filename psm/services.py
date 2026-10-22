"""硬檢核與存取。畫面 JOIN 顯示名稱；儲存只存 ID。"""

from __future__ import annotations

import sqlite3
from datetime import date
from math import isfinite
from typing import Any

from psm.filing import PHASES, get_flag
from psm.enums import (
    CHEMICAL_ROLES,
    EQUIPMENT_TYPES,
    INCIDENT_TYPES,
    MATERIAL_CATEGORIES,
    MATRIX_ACCEPT_LINE,
    MATRIX_VERSION,
    OP_KINDS,
    PHASE_CLASSES,
    POWER_KINDS,
    PROCESS_MODES,
    RULE_H314_CS_REMAIN,
    RULE_MI_TEXT,
    RULE_PHA_TEXT,
    UNIT_TITLES,
    WIZARD_SITE_ID,
)
from psm.errors import PsmError
from psm.report import render_report_html
from psm.report_v83 import render_report_v83


def _b(v: Any) -> int:
    if v in (True, 1, "1", "true", "True", "on", "yes"):
        return 1
    return 0


def infer_material_category(material: str | None) -> str:
    """規格名稱歸入本署劣化機制查詢的材質類別。無法判斷時為「其他」。"""
    m = (material or "").upper()
    if "FRP" in m or "高分子" in m:
        return "高分子材料"
    if "SS" in m or "304" in m or "316" in m:
        return "300系不銹鋼"
    if "CS" in m or "碳鋼" in m or "A283" in m:
        return "碳鋼(CS)"
    return "其他" if (material or "").strip() else ""


def _nz(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def rank_of(severity: int, likelihood: int) -> tuple[int, str]:
    val = int(severity) * int(likelihood)
    if val <= 4:
        return val, "低"
    if val <= 9:
        return val, "中"
    if val <= 16:
        return val, "高"
    return val, "極高"


def save_site(conn: sqlite3.Connection, data: dict) -> None:
    site_id = _nz(data.get("site_id"))
    if not site_id:
        raise PsmError("site_id 必填")
    try:
        worker_count = int(data.get("worker_count") or 0)
    except (TypeError, ValueError):
        worker_count = 0
    conn.execute(
        """INSERT INTO site(
            site_id, company_name, site_name, scope, applicant_name,
            assessment_base_date, worker_count, declare_no_contractor, declare_no_hotwork,
            declare_no_equipment_types, declare_no_incident_5y
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(site_id) DO UPDATE SET
            company_name=excluded.company_name,
            site_name=excluded.site_name,
            scope=excluded.scope,
            applicant_name=excluded.applicant_name,
            assessment_base_date=excluded.assessment_base_date,
            worker_count=excluded.worker_count,
            declare_no_contractor=0,
            declare_no_hotwork=0,
            declare_no_equipment_types=excluded.declare_no_equipment_types,
            declare_no_incident_5y=excluded.declare_no_incident_5y
        """,
        (
            site_id,
            data["company_name"],
            data["site_name"],
            data["scope"],
            data["applicant_name"],
            data["assessment_base_date"],
            worker_count,
            0,
            0,
            data.get("declare_no_equipment_types") or "",
            _b(data.get("declare_no_incident_5y")),
        ),
    )
    conn.commit()


def save_department(conn: sqlite3.Connection, data: dict) -> None:
    dept_id = _nz(data.get("dept_id"))
    name = _nz(data.get("name"))
    site_id = _nz(data.get("site_id"))
    if not dept_id or not name or not site_id:
        raise PsmError("部門編號、名稱、場所必填")
    parent = _nz(data.get("parent_dept_id"))
    try:
        headcount = int(data.get("headcount") or 0)
    except (TypeError, ValueError):
        headcount = 0
    conn.execute(
        """INSERT INTO department(dept_id, site_id, name, parent_dept_id, headcount)
           VALUES (?,?,?,?,?)
           ON CONFLICT(dept_id) DO UPDATE SET name=excluded.name,
             parent_dept_id=excluded.parent_dept_id, site_id=excluded.site_id,
             headcount=excluded.headcount""",
        (dept_id, site_id, name, parent, headcount),
    )
    conn.commit()


def rename_department(conn: sqlite3.Connection, dept_id: str, new_name: str) -> None:
    if not _nz(new_name):
        raise PsmError("部門名稱必填")
    cur = conn.execute(
        "UPDATE department SET name=? WHERE dept_id=?", (new_name, dept_id)
    )
    if cur.rowcount == 0:
        raise PsmError("部門不存在")
    conn.commit()


def delete_department(conn: sqlite3.Connection, dept_id: str) -> None:
    used = conn.execute(
        """SELECT 1 FROM process WHERE operating_dept_id=?
           UNION SELECT 1 FROM equipment WHERE maint_dept_id=?""",
        (dept_id, dept_id),
    ).fetchone()
    if used:
        raise PsmError("部門仍有製程或設備參照，不得刪除")
    conn.execute("DELETE FROM department WHERE dept_id=?", (dept_id,))
    conn.commit()


def save_process(conn: sqlite3.Connection, data: dict) -> None:
    pid = _nz(data.get("process_id"))
    name = _nz(data.get("name"))
    op = _nz(data.get("operating_dept_id"))
    mode = _nz(data.get("mode"))
    if not pid or not name or not op:
        raise PsmError("製程編號、名稱、操作權責部門編號必填")
    if mode not in PROCESS_MODES:
        raise PsmError("連續或批次必選")
    if not conn.execute("SELECT 1 FROM department WHERE dept_id=?", (op,)).fetchone():
        raise PsmError("操作權責部門不存在")
    existing = conn.execute(
        "SELECT overview FROM process WHERE process_id=?", (pid,)
    ).fetchone()
    if "overview" in data:
        overview = data.get("overview") or ""
    else:
        overview = existing["overview"] if existing else ""
    conn.execute(
        """INSERT INTO process(
            process_id, site_id, name, overview, operating_dept_id, mode,
            has_chemical_reaction, has_overpressure, is_special,
            is_loading, is_downstream
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(process_id) DO UPDATE SET
            name=excluded.name, overview=excluded.overview,
            operating_dept_id=excluded.operating_dept_id,
            mode=excluded.mode, has_chemical_reaction=excluded.has_chemical_reaction,
            has_overpressure=excluded.has_overpressure, is_special=excluded.is_special,
            is_loading=excluded.is_loading, is_downstream=excluded.is_downstream
        """,
        (
            pid,
            data["site_id"],
            name,
            overview,
            op,
            mode,
            _b(data.get("has_chemical_reaction")),
            _b(data.get("has_overpressure")),
            _b(data.get("is_special")),
            _b(data.get("is_loading")),
            _b(data.get("is_downstream")),
        ),
    )
    conn.commit()


def delete_process(conn: sqlite3.Connection, process_id: str) -> None:
    used = conn.execute(
        """SELECT 1 FROM equipment WHERE process_id=?
           UNION SELECT 1 FROM chemical WHERE process_id=?
           UNION SELECT 1 FROM assessment WHERE process_id=?
           UNION SELECT 1 FROM assessment_scope WHERE process_id=?
           UNION SELECT 1 FROM node WHERE process_id=?""",
        (process_id, process_id, process_id, process_id, process_id),
    ).fetchone()
    if used:
        raise PsmError("製程仍有設備、化學品或評估參照，不得刪除")
    conn.execute("DELETE FROM process WHERE process_id=?", (process_id,))
    conn.commit()


def save_area(conn: sqlite3.Connection, data: dict) -> None:
    code = _nz(data.get("area_code"))
    if not code:
        raise PsmError("區域代碼必填")
    for k in ("name", "drawing_no", "revision", "issue_date", "attachment_path"):
        if not _nz(data.get(k)):
            raise PsmError("廠區位置圖須完成結構化登錄（名稱、圖號、版次、日期、附件）")
    conn.execute(
        """INSERT INTO area(area_code, site_id, name, drawing_no, revision,
            issue_date, process_id, attachment_path, is_assembly_point,
            is_control_room, is_fire_system, worker_count, contractor_count, visitor_count,
            linked_cas)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(area_code) DO UPDATE SET
             name=excluded.name, drawing_no=excluded.drawing_no,
             revision=excluded.revision, issue_date=excluded.issue_date,
             process_id=excluded.process_id, attachment_path=excluded.attachment_path,
             is_assembly_point=excluded.is_assembly_point,
             is_control_room=excluded.is_control_room,
             is_fire_system=excluded.is_fire_system,
             worker_count=excluded.worker_count,
             contractor_count=excluded.contractor_count,
             visitor_count=excluded.visitor_count,
             linked_cas=excluded.linked_cas""",
        (
            code,
            data["site_id"],
            data["name"],
            data["drawing_no"],
            data["revision"],
            data["issue_date"],
            _nz(data.get("process_id")),
            data["attachment_path"],
            _b(data.get("is_assembly_point")),
            _b(data.get("is_control_room")),
            _b(data.get("is_fire_system")),
            int(data.get("worker_count") or 0),
            int(data.get("contractor_count") or 0),
            int(data.get("visitor_count") or 0),
            _nz(data.get("linked_cas")) or "",
        ),
    )
    _sync_area_links(conn, code)
    conn.commit()


def _sync_area_links(conn: sqlite3.Connection, area_code: str) -> None:
    row = conn.execute(
        "SELECT site_id, process_id, linked_cas FROM area WHERE area_code=?", (area_code,)
    ).fetchone()
    if not row:
        return
    default_pid = _nz(row["process_id"])
    wanted: set[tuple[str, str, str]] = set()
    for raw in (row["linked_cas"] or "").split(","):
        token = raw.strip()
        if not token:
            continue
        cas, pid = (token.split("|", 1) if "|" in token else (token, default_pid))
        cas, pid = cas.strip(), pid.strip()
        if not cas or not pid:
            raise PsmError("關聯化學品須選已建立的 CAS 與製程")
        chemicals = conn.execute(
            """SELECT c.sds_id FROM chemical c
               JOIN process p ON p.process_id=c.process_id
               WHERE c.cas=? AND c.process_id=? AND p.site_id=?""",
            (cas, pid, row["site_id"]),
        ).fetchall()
        if not chemicals:
            raise PsmError(f"關聯化學品 {cas}／{pid} 不屬於本場所已建立的化學品")
        wanted.update((pid, chem["sds_id"], cas) for chem in chemicals)
    existing = {
        (r["process_id"], r["sds_id"], r["cas"])
        for r in conn.execute(
            "SELECT process_id,sds_id,cas FROM area_chemical WHERE area_code=?",
            (area_code,),
        )
    }
    for pid, sds_id, cas in existing - wanted:
        conn.execute(
            """DELETE FROM area_chemical WHERE area_code=? AND process_id=?
               AND sds_id=? AND cas=?""",
            (area_code, pid, sds_id, cas),
        )
    for pid, sds_id, cas in wanted - existing:
        conn.execute(
            """INSERT INTO area_chemical(area_code,process_id,sds_id,cas)
               VALUES (?,?,?,?)""",
            (area_code, pid, sds_id, cas),
        )
    process_ids = {pid for pid, _, _ in wanted}
    if default_pid:
        process_ids.add(default_pid)
    process_ids.update(
        r[0] for r in conn.execute(
            """SELECT DISTINCT e.process_id FROM area_equipment ae
               JOIN equipment e ON e.equipment_id=ae.equipment_id
               WHERE ae.area_code=?""", (area_code,)
        )
    )
    old_process_ids = {
        r[0] for r in conn.execute(
            "SELECT process_id FROM area_process WHERE area_code=?", (area_code,)
        )
    }
    for pid in old_process_ids - process_ids:
        conn.execute("DELETE FROM area_process WHERE area_code=? AND process_id=?", (area_code, pid))
    for pid in process_ids - old_process_ids:
        conn.execute("INSERT INTO area_process(area_code,process_id) VALUES (?,?)", (area_code, pid))


def assign_area_equipment(conn: sqlite3.Connection, area_code: str, equipment_ids: list[str]) -> None:
    """表1.0-5 關聯設備：寫入 area_equipment，不把設備從其他區域拔掉。"""
    code = _nz(area_code)
    if not code:
        return
    wanted = []
    for eid in equipment_ids:
        eid = _nz(eid)
        if eid:
            wanted.append(eid)
    existing = {
        r[0]
        for r in conn.execute(
            "SELECT equipment_id FROM area_equipment WHERE area_code=?", (code,)
        )
    }
    want_set = set(wanted)
    for eid in existing - want_set:
        conn.execute(
            "DELETE FROM area_equipment WHERE area_code=? AND equipment_id=?",
            (code, eid),
        )
    for eid in want_set - existing:
        conn.execute(
            "INSERT INTO area_equipment(area_code, equipment_id) VALUES (?,?)",
            (code, eid),
        )
    for eid in wanted:
        conn.execute(
            """UPDATE equipment SET area_code=COALESCE(area_code, ?)
               WHERE equipment_id=?""",
            (code, eid),
        )
    _sync_area_links(conn, code)
    conn.commit()


def save_equipment(conn: sqlite3.Connection, data: dict) -> None:
    eid = _nz(data.get("equipment_id"))
    process_id = _nz(data.get("process_id"))
    maint = _nz(data.get("maint_dept_id"))
    name = _nz(data.get("name"))
    etype = _nz(data.get("equipment_type"))
    phase = _nz(data.get("phase_class"))
    area = _nz(data.get("area_code"))
    if not eid:
        raise PsmError("equipment_id 必填")
    if not process_id:
        raise PsmError("設備必須有 process_id（所屬製程編號）")
    if not maint:
        raise PsmError("設備必須有 maint_dept_id（維護權責部門編號）")
    if not name:
        raise PsmError("設備名稱必填")
    if etype not in EQUIPMENT_TYPES:
        raise PsmError("設備類型須八選一（完整名稱）")
    if phase not in PHASE_CLASSES:
        raise PsmError("操作分類須為粉狀固體／粒狀固體／液體／氣體／後段處理")
    power = _nz(data.get("power_kind"))
    if etype == "動力來源":
        if power not in POWER_KINDS:
            raise PsmError("類型為動力來源時必填動力型式：泵浦／氣動／其他")
    else:
        power = None
    if not conn.execute("SELECT 1 FROM process WHERE process_id=?", (process_id,)).fetchone():
        raise PsmError("所屬製程不存在")
    if not conn.execute("SELECT 1 FROM department WHERE dept_id=?", (maint,)).fetchone():
        raise PsmError("維護權責部門不存在")
    material = _nz(data.get("material"))
    category = _nz(data.get("material_category")) or infer_material_category(material)
    conn.execute(
        """INSERT INTO equipment(
            equipment_id, site_id, process_id, maint_dept_id, name, alias,
            equipment_type, power_kind, phase_class, is_safety_critical,
            is_regulated_machinery, is_high_pressure_gas, area_code, material,
            material_category, legal_cert_type
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(equipment_id) DO UPDATE SET
            process_id=excluded.process_id, maint_dept_id=excluded.maint_dept_id,
            name=excluded.name, alias=excluded.alias,
            equipment_type=excluded.equipment_type, power_kind=excluded.power_kind,
            phase_class=excluded.phase_class, is_safety_critical=excluded.is_safety_critical,
            is_regulated_machinery=excluded.is_regulated_machinery,
            is_high_pressure_gas=excluded.is_high_pressure_gas,
            area_code=COALESCE(excluded.area_code, equipment.area_code),
            material=excluded.material,
            material_category=excluded.material_category,
            legal_cert_type=excluded.legal_cert_type
        """,
        (
            eid,
            data["site_id"],
            process_id,
            maint,
            name,
            _nz(data.get("alias")),
            etype,
            power,
            phase,
            _b(data.get("is_safety_critical")),
            _b(data.get("is_regulated_machinery")),
            _b(data.get("is_high_pressure_gas")),
            area,
            material,
            category,
            _nz(data.get("legal_cert_type")),
        ),
    )
    if area:
        conn.execute(
            "INSERT OR IGNORE INTO area_equipment(area_code, equipment_id) VALUES (?,?)",
            (area, eid),
        )
        if process_id:
            conn.execute(
                "INSERT OR IGNORE INTO area_process(area_code, process_id) VALUES (?,?)",
                (area, process_id),
            )
    if _b(data.get("is_regulated_machinery")) or _b(data.get("is_high_pressure_gas")):
        conn.execute(
            "UPDATE filing_flag SET v='0' WHERE site_id=? AND k='no_art16' AND v='1'",
            (data["site_id"],),
        )
    if material:
        _upsert_equipment_material(
            conn,
            {
                "equipment_id": eid,
                "material": material,
                "material_category": category or "",
            },
            sync_equipment=False,
        )
    _mark_stale(conn, "Equipment", eid)
    conn.commit()


def _upsert_equipment_material(
    conn: sqlite3.Connection, data: dict, *, sync_equipment: bool
) -> None:
    eid = _nz(data.get("equipment_id"))
    material = _nz(data.get("material"))
    if not eid:
        raise PsmError("設備編號必填")
    if not conn.execute("SELECT 1 FROM equipment WHERE equipment_id=?", (eid,)).fetchone():
        raise PsmError("設備須選已有編號")
    if not material:
        raise PsmError("表1.6-1 建造材料（規格名稱）必填")
    category = _nz(data.get("material_category")) or infer_material_category(material)
    if not category:
        raise PsmError("表1.6-1 須選材質類別，才能對本署劣化機制查詢")
    if category not in MATERIAL_CATEGORIES:
        raise PsmError("材質類別須為本署劣化機制查詢選項")
    spec = _nz(data.get("spec"))
    allow = _nz(data.get("corrosion_allowance"))
    existing = conn.execute(
        "SELECT spec, corrosion_allowance FROM equipment_material WHERE equipment_id=?",
        (eid,),
    ).fetchone()
    if existing:
        if spec is None:
            spec = existing["spec"]
        if allow is None:
            allow = existing["corrosion_allowance"]
    conn.execute(
        """INSERT INTO equipment_material(
            equipment_id, material, material_category, spec, corrosion_allowance
        ) VALUES (?,?,?,?,?)
        ON CONFLICT(equipment_id) DO UPDATE SET
            material=excluded.material,
            material_category=excluded.material_category,
            spec=COALESCE(excluded.spec, equipment_material.spec),
            corrosion_allowance=COALESCE(excluded.corrosion_allowance, equipment_material.corrosion_allowance)
        """,
        (eid, material, category, spec, allow),
    )
    if sync_equipment:
        conn.execute(
            "UPDATE equipment SET material=?, material_category=? WHERE equipment_id=?",
            (material, category, eid),
        )


def save_equipment_material(conn: sqlite3.Connection, data: dict) -> None:
    """表1.6-1：建造材料與材質類別。第八章帶出，不另填一套。"""
    _upsert_equipment_material(conn, data, sync_equipment=True)
    conn.commit()


def material_for_mi(conn: sqlite3.Connection, equipment_id: str) -> dict[str, str]:
    """表8.1-1 的材質只讀表1.6-1／設備清單，不以第八章表單覆寫。"""
    row = conn.execute(
        """SELECT COALESCE(m.material, e.material) AS material,
                  COALESCE(NULLIF(m.material_category, ''), e.material_category) AS material_category
           FROM equipment e
           LEFT JOIN equipment_material m ON m.equipment_id=e.equipment_id
           WHERE e.equipment_id=?""",
        (equipment_id,),
    ).fetchone()
    if not row:
        return {"material": "", "material_category": ""}
    return {
        "material": row["material"] or "",
        "material_category": row["material_category"] or "",
    }


def mi_query_ready(conn: sqlite3.Connection, equipment_id: str) -> dict:
    """劣化機制查詢必備：材質類別、操作溫度、內容物。介質／保溫仍在本署頁勾選。"""
    bound = material_for_mi(conn, equipment_id)
    has_temp = conn.execute(
        """SELECT 1 FROM equipment_limit
           WHERE equipment_id=? AND (parameter='溫度' OR parameter LIKE '%溫%')
           LIMIT 1""",
        (equipment_id,),
    ).fetchone()
    has_content = conn.execute(
        """SELECT 1 FROM equipment_content
           WHERE equipment_id=? AND (cas<>'' OR no_process_chemical=1)
           LIMIT 1""",
        (equipment_id,),
    ).fetchone()
    category = bound["material_category"]
    ready = bool(category) and bool(has_temp) and bool(has_content)
    missing = []
    if not category:
        missing.append("材質類別（表1.6-1）")
    if not has_temp:
        missing.append("操作溫度（表1.5）")
    if not has_content:
        missing.append("內容物")
    return {
        "ready": ready,
        "material": bound["material"],
        "material_category": category,
        "has_temperature": bool(has_temp),
        "has_contents": bool(has_content),
        "missing": missing,
    }


def save_sds(conn: sqlite3.Connection, data: dict) -> str:
    sds_id = _nz(data.get("sds_id"))
    site_id = _nz(data.get("site_id"))
    name = _nz(data.get("substance_or_mixture_name"))
    path = _nz(data.get("file_path"))
    if not sds_id or not site_id or not name or not path:
        raise PsmError("SDS 須有代號、場所、物質或混合物名稱、檔案路徑")
    conn.execute(
        """INSERT INTO sds(sds_id, site_id, substance_or_mixture_name, version,
            revise_date, file_path, component_cas_list, ppe_level, filter_type)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(sds_id) DO UPDATE SET
             substance_or_mixture_name=excluded.substance_or_mixture_name,
             version=excluded.version, revise_date=excluded.revise_date,
             file_path=excluded.file_path, component_cas_list=excluded.component_cas_list,
             ppe_level=excluded.ppe_level, filter_type=excluded.filter_type""",
        (
            sds_id,
            site_id,
            name,
            _nz(data.get("version")) or "1",
            _nz(data.get("revise_date")) or "",
            path,
            _nz(data.get("component_cas_list")) or "",
            _nz(data.get("ppe_level")),
            _nz(data.get("filter_type")),
        ),
    )
    conn.commit()
    return sds_id


def _sds_id_from_path(path: str, cas: str) -> str:
    base = path.replace("\\", "/").rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    stem = stem.replace("placeholder://", "")
    return stem or f"SDS-{cas}"


def save_chemical(conn: sqlite3.Connection, data: dict) -> None:
    cas = _nz(data.get("cas"))
    process_id = _nz(data.get("process_id"))
    name = _nz(data.get("name"))
    role = _nz(data.get("role"))
    if not cas or not process_id or not name or not role:
        raise PsmError("化學品須有 CAS、製程編號、名稱、角色")
    if role not in CHEMICAL_ROLES:
        raise PsmError("角色須為原物料／中間產物／產物／副產物／觸媒／清洗劑")
    sds_id = _nz(data.get("sds_id"))
    sds_file = _nz(data.get("sds_file"))
    if not sds_id and sds_file:
        proc = conn.execute(
            "SELECT site_id FROM process WHERE process_id=?", (process_id,)
        ).fetchone()
        if not proc:
            raise PsmError("所屬製程不存在")
        sds_id = _sds_id_from_path(sds_file, cas)
        if not conn.execute("SELECT 1 FROM sds WHERE sds_id=?", (sds_id,)).fetchone():
            save_sds(
                conn,
                {
                    "sds_id": sds_id,
                    "site_id": proc["site_id"],
                    "substance_or_mixture_name": name,
                    "file_path": sds_file,
                    "component_cas_list": cas,
                },
            )
    if not sds_id:
        raise PsmError("化學品須連 SDS 代號（獨立頂點，禁止只存檔路徑）")
    if not conn.execute("SELECT 1 FROM sds WHERE sds_id=?", (sds_id,)).fetchone():
        raise PsmError("SDS 代號不存在")
    conn.execute(
        "INSERT OR IGNORE INTO chemical_cite(cas, process_id) VALUES (?,?)",
        (cas, process_id),
    )
    purity = _nz(data.get("purity_or_mixture")) or _nz(data.get("kind")) or "純物質"
    phase_given = "phase_state" in data or "phase" in data
    phase = (_nz(data.get("phase_state")) or _nz(data.get("phase")) or "") if phase_given else ""
    if phase and phase not in PHASES:
        raise PsmError("常用狀況相態須為固態、液態或氣態")
    aqueous = str(data.get("aqueous_status") or "").strip()
    if aqueous not in ("", "0", "1"):
        raise PsmError("水溶液別須選待確認、水溶液或非水溶液")
    conn.execute(
        """INSERT INTO chemical(cas, process_id, sds_id, name, role, un_number,
            transport_hazard_class, concentration_range, h_codes,
            purity_or_mixture, mixture_name, pct_low, pct_high, pct_basis,
            mixture_qty, attributed_qty, phase_state, name_en, aqueous_status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(process_id, sds_id, cas) DO UPDATE SET
             name=excluded.name, name_en=excluded.name_en, role=excluded.role,
             un_number=excluded.un_number,
             transport_hazard_class=excluded.transport_hazard_class,
             concentration_range=excluded.concentration_range,
             h_codes=excluded.h_codes, purity_or_mixture=excluded.purity_or_mixture,
             mixture_name=excluded.mixture_name, pct_low=excluded.pct_low,
             pct_high=excluded.pct_high, pct_basis=excluded.pct_basis,
             mixture_qty=excluded.mixture_qty, attributed_qty=excluded.attributed_qty,
             phase_state=CASE WHEN ?=1 THEN excluded.phase_state ELSE chemical.phase_state END,
             aqueous_status=CASE WHEN ?=1 THEN excluded.aqueous_status ELSE chemical.aqueous_status END""",
        (
            cas,
            process_id,
            sds_id,
            name,
            role,
            _nz(data.get("un_number")),
            _nz(data.get("transport_hazard_class")),
            _nz(data.get("concentration_range")),
            _nz(data.get("h_codes")) or "",
            purity,
            _nz(data.get("mixture_name")) or _nz(data.get("mix_name")),
            _num_or_none(data.get("pct_low") if data.get("pct_low") is not None else data.get("pct_lo")),
            _num_or_none(data.get("pct_high") if data.get("pct_high") is not None else data.get("pct_hi")),
            _nz(data.get("pct_basis")) or _nz(data.get("basis")),
            _num_or_none(data.get("mixture_qty") if data.get("mixture_qty") is not None else data.get("total_kg")),
            _num_or_none(data.get("attributed_qty")),
            phase,
            _nz(data.get("name_en")),
            aqueous,
            1 if phase_given else 0,
            1 if "aqueous_status" in data else 0,
        ),
    )
    _mark_stale(conn, "Chemical", f"{cas}|{process_id}")
    conn.commit()


def _num_or_none(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _is_carbon_steel(material: str | None) -> bool:
    m = (material or "").upper()
    return "碳鋼" in (material or "") or "CS" in m or "CARBON STEEL" in m


def _has_h314(h_codes: str | None) -> bool:
    raw = (h_codes or "").upper().replace(" ", "")
    return "H314" in raw


def map_complete(conn: sqlite3.Connection, process_id: str) -> tuple[bool, list[str]]:
    eqs = [
        r["equipment_id"]
        for r in conn.execute(
            "SELECT equipment_id FROM equipment WHERE process_id=? ORDER BY equipment_id",
            (process_id,),
        )
    ]
    if not eqs:
        return True, []
    missing = []
    for eid in eqs:
        n = conn.execute(
            "SELECT COUNT(*) FROM pec_map WHERE process_id=? AND equipment_id=?",
            (process_id, eid),
        ).fetchone()[0]
        if n < 1:
            missing.append(eid)
    if missing:
        return False, [f"對應表尚未覆蓋設備：{','.join(missing)}"]
    return True, []


def site_map_complete(conn: sqlite3.Connection, site_id: str) -> tuple[bool, list[str]]:
    reasons = []
    for p in conn.execute("SELECT process_id FROM process WHERE site_id=?", (site_id,)):
        ok, miss = map_complete(conn, p["process_id"])
        if not ok:
            reasons.append(f"{p['process_id']} " + "；".join(miss))
    return (not reasons, reasons)


def _refresh_prompt_for_row(conn: sqlite3.Connection, row: dict) -> None:
    hit = (
        not row.get("no_process_chemical")
        and _has_h314(row.get("h_codes"))
        and _is_carbon_steel(row.get("material"))
        and bool(row.get("may_remain"))
    )
    key = (RULE_H314_CS_REMAIN, row["process_id"], row["equipment_id"], row.get("cas") or "")
    if not hit:
        conn.execute(
            """DELETE FROM prompt_event
               WHERE rule_id=? AND process_id=? AND equipment_id=? AND cas=?""",
            key,
        )
        return
    for stage, msg in (("pha", RULE_PHA_TEXT), ("mi", RULE_MI_TEXT)):
        pid = f"{RULE_H314_CS_REMAIN}-{stage}-{row['equipment_id']}-{row.get('cas') or 'NONE'}"
        existing = conn.execute(
            """SELECT prompt_id, status FROM prompt_event
               WHERE rule_id=? AND process_id=? AND equipment_id=? AND cas=? AND stage=?""",
            (*key, stage),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE prompt_event SET message=? WHERE prompt_id=?",
                (msg, existing["prompt_id"]),
            )
            continue
        conn.execute(
            """INSERT INTO prompt_event(prompt_id, rule_id, process_id, equipment_id, cas,
                stage, message, status)
               VALUES (?,?,?,?,?,?,?,'open')""",
            (pid, RULE_H314_CS_REMAIN, row["process_id"], row["equipment_id"], row.get("cas") or "", stage, msg),
        )


def resolve_component_sds(
    conn: sqlite3.Connection, process_id: str, cas: str, sds_id: str | None
) -> str:
    """濃度敏感列必須落到某一張 SDS。只有一列時可省略代號。"""
    wanted = _nz(sds_id) or ""
    rows = conn.execute(
        "SELECT sds_id FROM chemical WHERE cas=? AND process_id=? ORDER BY sds_id",
        (cas, process_id),
    ).fetchall()
    if wanted:
        if not any(r["sds_id"] == wanted for r in rows):
            raise PsmError("SDS 須為該製程此 CAS 的填報列")
        return wanted
    if len(rows) == 1:
        return rows[0]["sds_id"]
    if not rows:
        raise PsmError("化學品必須屬於同一製程，禁止把別製程化學品配到本設備")
    raise PsmError("同一 CAS 有多張 SDS，須指定 SDS 代號")


def save_pec_map(conn: sqlite3.Connection, data: dict) -> None:
    process_id = _nz(data.get("process_id"))
    eid = _nz(data.get("equipment_id"))
    cas = _nz(data.get("cas")) or ""
    none_chem = _b(data.get("no_process_chemical") or data.get("no_process_chemical"))
    if not process_id or not eid:
        raise PsmError("對應表須選製程編號與設備編號")
    eq = conn.execute(
        "SELECT process_id, material FROM equipment WHERE equipment_id=?", (eid,)
    ).fetchone()
    if not eq:
        raise PsmError("設備編號不存在")
    if eq["process_id"] != process_id:
        raise PsmError("對應表設備必須屬於所選製程，禁止跨製程配對")
    sds_id = ""
    if none_chem:
        cas = ""
    else:
        if not cas:
            raise PsmError("有製程化學品時須選化學品代號，或勾選本設備無製程化學品")
        sds_id = resolve_component_sds(conn, process_id, cas, data.get("sds_id"))
    h_codes = _nz(data.get("h_codes")) or ""
    if not h_codes and cas:
        ch = conn.execute(
            "SELECT h_codes FROM chemical WHERE cas=? AND process_id=? AND sds_id=?",
            (cas, process_id, sds_id),
        ).fetchone()
        h_codes = (ch["h_codes"] if ch else "") or ""
    material = _nz(data.get("material")) or eq["material"]
    may_remain = _b(data.get("may_remain") if data.get("may_remain") is not None else data.get("may_remain"))
    notes = _nz(data.get("review_notes")) or ""
    if (
        not notes
        and _has_h314(h_codes)
        and _is_carbon_steel(material)
        and may_remain
    ):
        notes = "材質條件不相容；停車未排淨"
    conn.execute(
        """INSERT INTO pec_map(process_id, equipment_id, cas, sds_id, no_process_chemical, h_codes,
            material, may_remain, review_notes, confirmed, na_reason)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(process_id, equipment_id, cas, sds_id) DO UPDATE SET
             no_process_chemical=excluded.no_process_chemical, h_codes=excluded.h_codes,
             material=excluded.material, may_remain=excluded.may_remain,
             review_notes=excluded.review_notes, confirmed=excluded.confirmed,
             na_reason=excluded.na_reason""",
        (
            process_id,
            eid,
            cas,
            sds_id,
            none_chem,
            h_codes,
            material,
            may_remain,
            notes,
            _b(data.get("confirmed")),
            _nz(data.get("na_reason")),
        ),
    )
    row = dict(
        conn.execute(
            """SELECT * FROM pec_map
               WHERE process_id=? AND equipment_id=? AND cas=? AND sds_id=?""",
            (process_id, eid, cas, sds_id),
        ).fetchone()
    )
    _refresh_prompt_for_row(conn, row)
    conn.commit()


def pec_map_rows(conn: sqlite3.Connection, site_id: str | None = None, process_id: str | None = None) -> list[dict]:
    sql = """SELECT m.*, p.name AS process_name, e.name AS equipment_name, c.name AS chemical_name
             FROM pec_map m
             JOIN process p ON p.process_id=m.process_id
             JOIN equipment e ON e.equipment_id=m.equipment_id
             LEFT JOIN chemical c ON c.cas=m.cas AND c.process_id=m.process_id
               AND c.sds_id=m.sds_id"""
    args: list = []
    if process_id:
        sql += " WHERE m.process_id=?"
        args.append(process_id)
    elif site_id:
        sql += " WHERE p.site_id=?"
        args.append(site_id)
    sql += " ORDER BY m.process_id, m.equipment_id, m.cas, m.sds_id"
    return [dict(r) for r in conn.execute(sql, args)]


def prompt_events(
    conn: sqlite3.Connection,
    *,
    process_id: str | None = None,
    equipment_id: str | None = None,
    stage: str | None = None,
) -> list[dict]:
    sql = "SELECT * FROM prompt_event WHERE 1=1"
    args: list = []
    if process_id:
        sql += " AND process_id=?"
        args.append(process_id)
    if equipment_id:
        sql += " AND equipment_id=?"
        args.append(equipment_id)
    if stage:
        sql += " AND stage=?"
        args.append(stage)
    sql += " ORDER BY equipment_id, stage"
    return [dict(r) for r in conn.execute(sql, args)]


def set_prompt_status(conn: sqlite3.Connection, prompt_id: str, status: str, na_reason: str = "") -> None:
    if status not in ("open", "accepted", "not_applicable"):
        raise PsmError("提示狀態須為待處理／已採納／不適用")
    if status == "not_applicable" and not _nz(na_reason):
        raise PsmError("標不適用時必須填理由，不得標為已處理")
    conn.execute(
        "UPDATE prompt_event SET status=?, na_reason=? WHERE prompt_id=?",
        (status, _nz(na_reason) if status == "not_applicable" else None, prompt_id),
    )
    conn.commit()


def save_pid_drawing(
    conn: sqlite3.Connection, data: dict, covering_ids: list[str]
) -> None:
    drawing_no = _nz(data.get("drawing_no"))
    revision = _nz(data.get("revision"))
    covering = [c for c in covering_ids if _nz(c)]
    process_id = _nz(data.get("process_id"))
    attachment = _nz(data.get("attachment_path")) or ""
    if not drawing_no or not revision or not covering:
        conn.execute(
            """INSERT INTO unstructured_attachment(
                process_id, kind, original_name, attachment_path, note
            ) VALUES (?,?,?,?,?)""",
            (
                process_id,
                "pid",
                _nz(data.get("name")),
                attachment or "(無路徑)",
                "僅上傳檔、未完成圖號／版次／涵蓋設備結構化登錄，不得供 HAZOP 勾稽",
            ),
        )
        conn.commit()
        return
    if not process_id:
        raise PsmError("P&ID 所屬製程編號必填")
    for eid in covering:
        row = conn.execute(
            "SELECT process_id FROM equipment WHERE equipment_id=?", (eid,)
        ).fetchone()
        if not row:
            raise PsmError(f"圖面涵蓋設備 {eid} 不存在於設備主檔")
        if row["process_id"] != process_id:
            raise PsmError(f"涵蓋設備 {eid} 不屬於製程 {process_id}")
    kind = _nz(data.get("diagram_kind")) or "P&ID"
    if kind not in ("PFD", "P&ID"):
        raise PsmError("圖資類型須為 PFD 或 P&ID")
    conn.execute(
        """INSERT INTO pid_drawing(drawing_no, revision, process_id, name,
            issue_date, is_as_built, attachment_path, eval_record_no, diagram_kind)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(drawing_no, revision) DO UPDATE SET
             process_id=excluded.process_id, name=excluded.name,
             issue_date=excluded.issue_date, is_as_built=excluded.is_as_built,
             attachment_path=excluded.attachment_path,
             eval_record_no=COALESCE(excluded.eval_record_no, pid_drawing.eval_record_no),
             diagram_kind=excluded.diagram_kind""",
        (
            drawing_no,
            revision,
            process_id,
            data.get("name") or drawing_no,
            data.get("issue_date") or "",
            _b(data.get("is_as_built")),
            attachment or "placeholder://pid",
            _nz(data.get("eval_record_no")),
            kind,
        ),
    )
    conn.execute(
        "DELETE FROM pid_covering WHERE drawing_no=? AND revision=?",
        (drawing_no, revision),
    )
    for eid in covering:
        conn.execute(
            "INSERT INTO pid_covering(drawing_no, revision, equipment_id) VALUES (?,?,?)",
            (drawing_no, revision, eid),
        )
    conn.commit()


def pid_is_usable(conn: sqlite3.Connection, drawing_no: str, revision: str) -> bool:
    dno, rev = _nz(drawing_no), _nz(revision)
    if not dno or not rev:
        return False
    row = conn.execute(
        "SELECT is_as_built, process_id FROM pid_drawing WHERE drawing_no=? AND revision=?",
        (dno, rev),
    ).fetchone()
    if not row or not row["is_as_built"]:
        return False
    n = conn.execute(
        "SELECT COUNT(*) FROM pid_covering WHERE drawing_no=? AND revision=?",
        (dno, rev),
    ).fetchone()[0]
    return n > 0


def hazop_usable_drawings(conn: sqlite3.Connection, process_id: str | None) -> list[dict]:
    if not _nz(process_id):
        return []
    rows = conn.execute(
        """SELECT d.* FROM pid_drawing d
           WHERE d.process_id=? AND d.is_as_built=1
             AND EXISTS (
               SELECT 1 FROM pid_covering c
               WHERE c.drawing_no=d.drawing_no AND c.revision=d.revision
             )""",
        (process_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def save_esd_scenario(conn: sqlite3.Connection, data: dict, action_ids: list[str]) -> None:
    sid = _nz(data.get("scenario_id"))
    process_id = _nz(data.get("process_id"))
    esd_eq = _nz(data.get("esd_equipment_id"))
    if not sid or not process_id or not esd_eq:
        raise PsmError("緊急停車方案須有方案編號、製程、系統設備編號")
    eq = conn.execute(
        "SELECT equipment_type, process_id FROM equipment WHERE equipment_id=?",
        (esd_eq,),
    ).fetchone()
    if not eq:
        raise PsmError("緊急停車系統設備不存在")
    if eq["equipment_type"] != "緊急停車系統":
        raise PsmError("esd_equipment_id 的設備類型必須是緊急停車系統")
    if eq["process_id"] != process_id:
        raise PsmError("緊急停車系統設備必須屬於該方案製程")
    conn.execute(
        """INSERT INTO esd_scenario(scenario_id, process_id, esd_equipment_id,
            name, trigger_conditions, maint_dept_id)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(scenario_id) DO UPDATE SET
             process_id=excluded.process_id, esd_equipment_id=excluded.esd_equipment_id,
             name=excluded.name, trigger_conditions=excluded.trigger_conditions,
             maint_dept_id=excluded.maint_dept_id""",
        (
            sid,
            process_id,
            esd_eq,
            data["name"],
            data["trigger_conditions"],
            _nz(data.get("maint_dept_id")),
        ),
    )
    conn.execute("DELETE FROM esd_action WHERE scenario_id=?", (sid,))
    for eid in action_ids:
        save_esd_action(conn, sid, eid, commit=False)
    conn.commit()


def save_esd_action(
    conn: sqlite3.Connection, scenario_id: str, equipment_id: str, commit: bool = True
) -> None:
    sc = conn.execute(
        "SELECT process_id FROM esd_scenario WHERE scenario_id=?", (scenario_id,)
    ).fetchone()
    if not sc:
        raise PsmError("方案不存在")
    eq = conn.execute(
        "SELECT process_id FROM equipment WHERE equipment_id=?", (equipment_id,)
    ).fetchone()
    if not eq:
        raise PsmError("動作設備不存在")
    if eq["process_id"] != sc["process_id"]:
        raise PsmError("EsdScenarioAction 的 equipment.process_id 必須等於 scenario.process_id")
    conn.execute(
        "INSERT OR IGNORE INTO esd_action(scenario_id, equipment_id) VALUES (?,?)",
        (scenario_id, equipment_id),
    )
    if commit:
        conn.commit()


def esd_status(conn: sqlite3.Connection, process_id: str) -> dict:
    esd_eqs = conn.execute(
        """SELECT equipment_id FROM equipment
           WHERE process_id=? AND equipment_type='緊急停車系統'""",
        (process_id,),
    ).fetchall()
    if not esd_eqs:
        return {"complete": True, "label": "本製程無緊急停車系統設備", "missing": []}
    missing = []
    for row in esd_eqs:
        eid = row["equipment_id"]
        sc = conn.execute(
            "SELECT scenario_id FROM esd_scenario WHERE process_id=? AND esd_equipment_id=?",
            (process_id, eid),
        ).fetchone()
        if not sc:
            missing.append(f"{eid} 無方案")
            continue
        n = conn.execute(
            "SELECT COUNT(*) FROM esd_action WHERE scenario_id=?", (sc["scenario_id"],)
        ).fetchone()[0]
        if n < 1:
            missing.append(f"{sc['scenario_id']} 無動作清單")
    if missing:
        return {
            "complete": False,
            "label": "緊急停車資料不完備：" + "；".join(missing),
            "missing": missing,
        }
    return {"complete": True, "label": "緊急停車資料完備", "missing": []}


def equipment_choices(conn: sqlite3.Connection, process_id: str | None) -> list[dict]:
    if not _nz(process_id):
        return []
    rows = conn.execute(
        """SELECT DISTINCT e.equipment_id, e.name, e.equipment_type, e.phase_class, e.area_code
           FROM pec_map m
           JOIN equipment e ON e.equipment_id=m.equipment_id
           WHERE m.process_id=?
           ORDER BY e.equipment_id""",
        (process_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def chemical_choices(conn: sqlite3.Connection, process_id: str | None) -> list[dict]:
    if not _nz(process_id):
        return []
    rows = conn.execute(
        """SELECT DISTINCT c.cas, c.name, c.role, c.sds_id
           FROM pec_map m
           JOIN chemical c ON c.cas=m.cas AND c.process_id=m.process_id AND c.sds_id=m.sds_id
           WHERE m.process_id=? AND m.no_process_chemical=0 AND m.cas<>''
           ORDER BY c.cas, c.sds_id""",
        (process_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def equipment_list_joined(conn: sqlite3.Connection, site_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT e.equipment_id, e.name, e.equipment_type, e.power_kind, e.phase_class,
                  e.process_id, p.name AS process_name,
                  p.operating_dept_id, od.name AS operating_dept_name,
                  e.maint_dept_id, md.name AS maint_dept_name,
                  e.area_code, e.is_safety_critical, e.is_regulated_machinery, e.is_high_pressure_gas,
                  e.alias, e.material, e.legal_cert_type
           FROM equipment e
           JOIN process p ON p.process_id = e.process_id
           JOIN department od ON od.dept_id = p.operating_dept_id
           JOIN department md ON md.dept_id = e.maint_dept_id
           WHERE e.site_id=?
           ORDER BY e.equipment_id""",
        (site_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def masters_complete(conn: sqlite3.Connection, site_id: str) -> tuple[bool, list[str]]:
    reasons = []
    if not conn.execute("SELECT 1 FROM site WHERE site_id=?", (site_id,)).fetchone():
        reasons.append("場所未建立")
    if not conn.execute("SELECT 1 FROM department WHERE site_id=?", (site_id,)).fetchone():
        reasons.append("部門主檔未建立")
    procs = conn.execute(
        "SELECT process_id, operating_dept_id FROM process WHERE site_id=?", (site_id,)
    ).fetchall()
    if not procs:
        reasons.append("製程主檔未建立")
    if not conn.execute(
        "SELECT 1 FROM equipment WHERE site_id=? AND process_id IS NOT NULL AND maint_dept_id IS NOT NULL",
        (site_id,),
    ).fetchone():
        reasons.append("設備主檔未建立")
    if not conn.execute(
        "SELECT 1 FROM chemical c JOIN process p ON p.process_id=c.process_id WHERE p.site_id=?",
        (site_id,),
    ).fetchone():
        reasons.append("化學品主檔未建立")
    areas = conn.execute(
        """SELECT 1 FROM area WHERE site_id=? AND drawing_no<>'' AND revision<>''
           AND attachment_path<>''""",
        (site_id,),
    ).fetchone()
    if not areas:
        reasons.append("廠區位置圖未完成結構化登錄")
    pid = conn.execute(
        """SELECT 1 FROM pid_drawing d
           JOIN process p ON p.process_id=d.process_id
           WHERE p.site_id=? AND d.is_as_built=1
             AND EXISTS (SELECT 1 FROM pid_covering c
                         WHERE c.drawing_no=d.drawing_no AND c.revision=d.revision)""",
        (site_id,),
    ).fetchone()
    if not pid:
        reasons.append("現況 P&ID 未完成結構化登錄（圖號／涵蓋設備）")
    n_asm = conn.execute(
        "SELECT COUNT(*) FROM area WHERE site_id=? AND is_assembly_point=1", (site_id,)
    ).fetchone()[0]
    if n_asm < 2:
        reasons.append("集合點須至少二處")
    ctrl = conn.execute(
        """SELECT 1 FROM area WHERE site_id=? AND is_control_room=1
           UNION
           SELECT 1 FROM equipment e JOIN process p ON p.process_id=e.process_id
           WHERE p.site_id=? AND e.equipment_type='控制系統'""",
        (site_id, site_id),
    ).fetchone()
    if not ctrl:
        reasons.append("場所未標示控制室區域，且無控制系統設備")
    fire = conn.execute(
        "SELECT 1 FROM area WHERE site_id=? AND is_fire_system=1", (site_id,)
    ).fetchone()
    if not fire:
        reasons.append("場所未標示消防系統區域")
    return (len(reasons) == 0, reasons)


def save_assessment(conn: sqlite3.Connection, data: dict) -> None:
    """附表2.2 不掛製程。有傳製程時只記入範圍，情境仍在節點另選。"""
    aid = _nz(data.get("assessment_id"))
    process_id = _nz(data.get("process_id"))
    if not aid:
        raise PsmError("評估識別必填")
    conn.execute(
        """INSERT INTO assessment(assessment_id, process_id, method, matrix_version,
            status, assessment_date)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(assessment_id) DO UPDATE SET
             process_id=excluded.process_id, method=excluded.method,
             matrix_version=excluded.matrix_version, assessment_date=excluded.assessment_date""",
        (
            aid,
            process_id,
            data.get("method") or "HAZOP",
            data.get("matrix_version") or MATRIX_VERSION,
            data.get("status") or "draft",
            data.get("assessment_date") or "",
        ),
    )
    if process_id:
        conn.execute(
            "INSERT OR IGNORE INTO assessment_scope(assessment_id, process_id) VALUES (?,?)",
            (aid, process_id),
        )
    conn.commit()


def save_node(
    conn: sqlite3.Connection,
    data: dict,
    equipment_ids: list[str],
    cas_list: list[str],
) -> None:
    nid = _nz(data.get("node_id"))
    aid = _nz(data.get("assessment_id"))
    process_id = _nz(data.get("process_id"))
    if not nid or not aid or not process_id:
        raise PsmError("節點須有編號、評估編號與製程編號")
    a = conn.execute(
        "SELECT assessment_id FROM assessment WHERE assessment_id=?", (aid,)
    ).fetchone()
    if not a:
        raise PsmError("評估不存在")
    dno, drev = _nz(data.get("drawing_no")), _nz(data.get("drawing_revision"))
    if dno or drev:
        if not pid_is_usable(conn, dno or "", drev or ""):
            raise PsmError("HAZOP 不得勾選未完成結構化登錄（圖號／涵蓋設備／現況版）之圖")
        dr = conn.execute(
            "SELECT process_id FROM pid_drawing WHERE drawing_no=? AND revision=?",
            (dno, drev),
        ).fetchone()
        if not dr or dr["process_id"] != process_id:
            raise PsmError("評估用圖之 process_id、drawing_no、revision 必須等於現況 as-built 登錄")
    conn.execute(
        """INSERT INTO node(node_id, assessment_id, process_id, description, deviation,
            cause, drawing_no, drawing_revision, considers_location, considers_human,
            considers_control_failure)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(node_id) DO UPDATE SET
             description=excluded.description, deviation=excluded.deviation,
             cause=excluded.cause, drawing_no=excluded.drawing_no,
             drawing_revision=excluded.drawing_revision,
             considers_location=excluded.considers_location,
             considers_human=excluded.considers_human,
             considers_control_failure=excluded.considers_control_failure""",
        (
            nid,
            aid,
            process_id,
            data.get("description") or "",
            data.get("deviation") or "",
            data.get("cause") or "",
            dno,
            drev,
            _b(data.get("considers_location")),
            _b(data.get("considers_human")),
            _b(data.get("considers_control_failure")),
        ),
    )
    conn.execute("DELETE FROM node_equipment WHERE node_id=?", (nid,))
    conn.execute("DELETE FROM node_chemical WHERE node_id=?", (nid,))
    for eid in equipment_ids:
        eid = _nz(eid)
        if not eid:
            continue
        eq = conn.execute(
            "SELECT process_id FROM equipment WHERE equipment_id=?", (eid,)
        ).fetchone()
        if not eq:
            raise PsmError(f"設備 {eid} 不存在")
        if eq["process_id"] != process_id:
            raise PsmError("Node.equipment_id 的 Equipment.process_id 必須等於該 Node 的 process_id")
        mapped = conn.execute(
            "SELECT 1 FROM pec_map WHERE process_id=? AND equipment_id=?",
            (process_id, eid),
        ).fetchone()
        if not mapped:
            raise PsmError("節點設備必須已出現在對應表（或已聲明無製程化學品）")
        conn.execute(
            "INSERT INTO node_equipment(node_id, equipment_id) VALUES (?,?)",
            (nid, eid),
        )
    for cas in cas_list:
        cas = _nz(cas)
        if not cas:
            continue
        ch = conn.execute(
            "SELECT 1 FROM chemical WHERE cas=? AND process_id=?", (cas, process_id)
        ).fetchone()
        if not ch:
            raise PsmError("Node.cas 必須存在 Chemical(cas, 該 process_id)")
        mapped = conn.execute(
            """SELECT 1 FROM pec_map WHERE process_id=? AND cas=? AND no_process_chemical=0""",
            (process_id, cas),
        ).fetchone()
        if not mapped:
            raise PsmError("節點化學品必須能對到對應表")
        conn.execute(
            "INSERT INTO node_chemical(node_id, cas, process_id) VALUES (?,?,?)",
            (nid, cas, process_id),
        )
    conn.commit()


def save_consequence(conn: sqlite3.Connection, data: dict) -> None:
    cid = _nz(data.get("consequence_id"))
    nid = _nz(data.get("node_id"))
    if not cid or not nid:
        raise PsmError("後果須掛節點")
    conn.execute(
        """INSERT INTO consequence(consequence_id, node_id, description, disaster_type, area_code)
           VALUES (?,?,?,?,?)
           ON CONFLICT(consequence_id) DO UPDATE SET
             description=excluded.description, disaster_type=excluded.disaster_type,
             area_code=excluded.area_code""",
        (
            cid,
            nid,
            data["description"],
            data.get("disaster_type") or "外洩",
            _nz(data.get("area_code")),
        ),
    )
    conn.commit()


def save_safeguard(conn: sqlite3.Connection, data: dict) -> None:
    if _nz(data.get("free_text")) and not (
        _nz(data.get("equipment_id")) or _nz(data.get("scenario_id")) or _nz(data.get("sop_id"))
    ):
        raise PsmError("Safeguard 禁止純文字；須選 equipment_id 或 scenario_id 或 sop_id")
    eid = _nz(data.get("equipment_id"))
    scid = _nz(data.get("scenario_id"))
    sop = _nz(data.get("sop_id"))
    kind = _nz(data.get("kind"))
    if kind == "equipment":
        scid = sop = None
    elif kind == "scenario":
        eid = sop = None
    elif kind == "sop":
        eid = scid = None
    n = sum(1 for x in (eid, scid, sop) if x)
    if n != 1:
        raise PsmError("防護須恰好選一：設備編號、緊急停車方案編號或 SOP 編號")
    cons = conn.execute(
        """SELECT n.process_id FROM consequence c
           JOIN node n ON n.node_id=c.node_id
           WHERE c.consequence_id=?""",
        (data["consequence_id"],),
    ).fetchone()
    if not cons:
        raise PsmError("後果不存在")
    process_id = cons["process_id"]
    if eid:
        eq = conn.execute(
            "SELECT process_id FROM equipment WHERE equipment_id=?", (eid,)
        ).fetchone()
        if not eq or eq["process_id"] != process_id:
            raise PsmError("防護設備須通過製程檢核")
    if scid:
        sc = conn.execute(
            "SELECT process_id FROM esd_scenario WHERE scenario_id=?", (scid,)
        ).fetchone()
        if not sc or sc["process_id"] != process_id:
            raise PsmError("防護方案須通過製程檢核")
    if sop:
        srow = conn.execute(
            "SELECT process_id FROM sop WHERE sop_id=?", (sop,)
        ).fetchone()
        if not srow or srow["process_id"] != process_id:
            raise PsmError("防護 SOP 須掛同一製程")
    conn.execute(
        """INSERT INTO safeguard(safeguard_id, consequence_id, equipment_id, scenario_id, sop_id)
           VALUES (?,?,?,?,?)
           ON CONFLICT(safeguard_id) DO UPDATE SET
             equipment_id=excluded.equipment_id, scenario_id=excluded.scenario_id,
             sop_id=excluded.sop_id""",
        (data["safeguard_id"], data["consequence_id"], eid, scid, sop),
    )
    conn.commit()


def save_risk_score(conn: sqlite3.Connection, data: dict) -> None:
    cons = conn.execute(
        """SELECT n.process_id, p.site_id FROM consequence c
           JOIN node n ON n.node_id=c.node_id
           JOIN process p ON p.process_id=n.process_id
           WHERE c.consequence_id=?""",
        (data.get("consequence_id"),),
    ).fetchone()
    site_id = cons["site_id"] if cons else None
    if site_id is None:
        site_row = conn.execute("SELECT site_id FROM site LIMIT 1").fetchone()
        site_id = site_row["site_id"] if site_row else None
    if not site_id:
        raise PsmError("場所未建立，不得評分")
    ok, reasons = masters_complete(conn, site_id)
    if not ok:
        raise PsmError("主檔未完備前不得評分：" + "；".join(reasons))
    if not cons:
        raise PsmError("後果不存在，不得評分")
    map_ok, map_reasons = map_complete(conn, cons["process_id"])
    if not map_ok:
        raise PsmError("該製程對應表未完備，不得評分：" + "；".join(map_reasons))
    sev, lik = int(data["severity"]), int(data["likelihood"])
    val, label = rank_of(sev, lik)
    conn.execute(
        """INSERT INTO risk_score(risk_id, consequence_id, matrix_version, severity,
            likelihood, rank_label, rank_value, lopa_freq, pfd, stale)
           VALUES (?,?,?,?,?,?,?,?,?,0)
           ON CONFLICT(risk_id) DO UPDATE SET
             severity=excluded.severity, likelihood=excluded.likelihood,
             rank_label=excluded.rank_label, rank_value=excluded.rank_value,
             stale=0""",
        (
            data["risk_id"],
            data["consequence_id"],
            data.get("matrix_version") or MATRIX_VERSION,
            sev,
            lik,
            label,
            val,
            _nz(data.get("lopa_freq")),
            _nz(data.get("pfd")),
        ),
    )
    conn.commit()


def assessments_touching_process(conn: sqlite3.Connection, process_id: str) -> list[dict]:
    """2.2 不篩製程。這裡只列出節點或範圍已經落到該製程的評估。"""
    return [
        dict(r)
        for r in conn.execute(
            """SELECT assessment_id, method, status, assessment_date, process_id
               FROM assessment a
               WHERE a.process_id=?
                  OR EXISTS (
                    SELECT 1 FROM assessment_scope s
                    WHERE s.assessment_id=a.assessment_id AND s.process_id=?
                  )
                  OR EXISTS (
                    SELECT 1 FROM node n
                    WHERE n.assessment_id=a.assessment_id AND n.process_id=?
                  )
               ORDER BY assessment_id""",
            (process_id, process_id, process_id),
        )
    ]


def assessment_id_for_process(conn: sqlite3.Connection, process_id: str) -> str | None:
    row = conn.execute(
        """SELECT a.assessment_id FROM assessment a
           WHERE a.process_id=?
              OR EXISTS (
                SELECT 1 FROM assessment_scope s
                WHERE s.assessment_id=a.assessment_id AND s.process_id=?
              )
              OR EXISTS (
                SELECT 1 FROM node n
                WHERE n.assessment_id=a.assessment_id AND n.process_id=?
              )
           ORDER BY CASE a.status WHEN 'complete' THEN 0 ELSE 1 END, a.assessment_id""",
        (process_id, process_id, process_id),
    ).fetchone()
    return row["assessment_id"] if row else None


def mark_assessment_complete(conn: sqlite3.Connection, assessment_id: str) -> None:
    exists = conn.execute(
        "SELECT 1 FROM assessment WHERE assessment_id=?", (assessment_id,)
    ).fetchone()
    if not exists:
        raise PsmError("評估不存在")
    procs = [
        r[0]
        for r in conn.execute(
            """SELECT DISTINCT process_id FROM (
                 SELECT process_id FROM assessment
                  WHERE assessment_id=? AND process_id IS NOT NULL
                 UNION
                 SELECT process_id FROM assessment_scope WHERE assessment_id=?
                 UNION
                 SELECT process_id FROM node WHERE assessment_id=?
               )""",
            (assessment_id, assessment_id, assessment_id),
        )
    ]
    if not procs:
        raise PsmError("評估尚未在情境掛到製程，不得標示完成")
    site = conn.execute(
        "SELECT site_id FROM process WHERE process_id=?", (procs[0],)
    ).fetchone()
    if not site:
        raise PsmError("評估所掛製程不存在")
    ok, reasons = masters_complete(conn, site["site_id"])
    if not ok:
        raise PsmError("主檔未完備前不能把評估標示完成：" + "；".join(reasons))
    for pid in procs:
        map_ok, map_reasons = map_complete(conn, pid)
        if not map_ok:
            raise PsmError("該製程對應表未完備，不得標示完成：" + "；".join(map_reasons))
    nodes = conn.execute(
        "SELECT COUNT(*) FROM node WHERE assessment_id=?", (assessment_id,)
    ).fetchone()[0]
    if nodes < 1:
        raise PsmError("無節點不得標示完成")
    naked = conn.execute(
        """SELECT s.safeguard_id FROM safeguard s
           JOIN consequence c ON c.consequence_id=s.consequence_id
           JOIN node n ON n.node_id=c.node_id
           WHERE n.assessment_id=?
             AND s.equipment_id IS NULL AND s.scenario_id IS NULL AND s.sop_id IS NULL""",
        (assessment_id,),
    ).fetchone()
    if naked:
        raise PsmError("存在純文字防護，評估未完成")
    conn.execute(
        "UPDATE assessment SET status='complete' WHERE assessment_id=?",
        (assessment_id,),
    )
    conn.commit()


def coverage_gaps(conn: sqlite3.Connection, process_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT e.equipment_id, e.name, e.equipment_type, e.phase_class
           FROM equipment e
           WHERE e.process_id=?
             AND e.equipment_id NOT IN (
               SELECT ne.equipment_id FROM node_equipment ne
               JOIN node n ON n.node_id=ne.node_id
               WHERE n.process_id=?
             )
           ORDER BY e.equipment_id""",
        (process_id, process_id),
    ).fetchall()
    return [dict(r) for r in rows]


def save_loading_occupancy(conn: sqlite3.Connection, data: dict) -> None:
    eid = _nz(data.get("equipment_id"))
    process_id = _nz(data.get("process_id"))
    cas = _nz(data.get("cas"))
    plate = _nz(data.get("plate_or_container"))
    if not eid or not process_id or not cas or not plate:
        raise PsmError("裝卸佔用須選設備、製程、CAS，並填車牌或容器號")
    eq = conn.execute(
        "SELECT equipment_type, process_id FROM equipment WHERE equipment_id=?", (eid,)
    ).fetchone()
    if not eq:
        raise PsmError("裝卸設備不存在")
    if eq["equipment_type"] != "裝卸及輸送":
        raise PsmError("裝卸佔用只能掛類型為裝卸及輸送之設備")
    if eq["process_id"] != process_id:
        raise PsmError("裝卸設備須屬於該製程")
    if not conn.execute(
        "SELECT 1 FROM chemical WHERE cas=? AND process_id=?", (cas, process_id)
    ).fetchone():
        raise PsmError("CAS 須存在於該製程化學品主檔")
    conn.execute(
        """INSERT INTO loading_occupancy(occupancy_id, equipment_id, process_id, cas,
            plate_or_container, start_ts, end_ts)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(occupancy_id) DO UPDATE SET
             plate_or_container=excluded.plate_or_container,
             start_ts=excluded.start_ts, end_ts=excluded.end_ts""",
        (
            data["occupancy_id"],
            eid,
            process_id,
            cas,
            plate,
            data["start_ts"],
            _nz(data.get("end_ts")),
        ),
    )
    conn.commit()


def _resolve_op_target(conn: sqlite3.Connection, data: dict) -> tuple[str, str, str | None]:
    """製程操作只掛 process_id；機械設備操作選設備編號，製程由設備帶出。"""
    op_kind = _nz(data.get("op_kind")) or "process"
    if op_kind not in OP_KINDS:
        raise PsmError("操作別須為製程操作或機械設備操作")
    eid = _nz(data.get("equipment_id"))
    if op_kind == "equipment":
        if not eid:
            raise PsmError("機械設備操作須選設備編號，不可手打設備名")
        eq = conn.execute(
            "SELECT process_id FROM equipment WHERE equipment_id=?", (eid,)
        ).fetchone()
        if not eq:
            raise PsmError("設備編號不存在")
        posted = _nz(data.get("process_id"))
        if posted and posted != eq["process_id"]:
            raise PsmError("所屬製程須與設備.所屬製程編號相同")
        return op_kind, eq["process_id"], eid
    if eid:
        raise PsmError("製程操作不要填設備編號")
    process_id = _nz(data.get("process_id"))
    if not process_id:
        raise PsmError("製程操作須選製程編號")
    if not conn.execute("SELECT 1 FROM process WHERE process_id=?", (process_id,)).fetchone():
        raise PsmError("製程編號不存在")
    return op_kind, process_id, None


def save_sop(conn: sqlite3.Connection, data: dict) -> None:
    op_kind, process_id, eid = _resolve_op_target(conn, data)
    raw_equipment_ids = data.get("equipment_ids")
    if raw_equipment_ids is None:
        raw_equipment_ids = [eid] if eid else []
    if isinstance(raw_equipment_ids, str):
        raw_equipment_ids = [raw_equipment_ids]
    equipment_ids = list(dict.fromkeys(
        str(value).strip() for value in raw_equipment_ids if str(value or "").strip()
    ))
    if eid and eid not in equipment_ids:
        raise PsmError("代表設備須包含在關聯設備中")
    for linked_id in equipment_ids:
        linked = conn.execute(
            "SELECT process_id FROM equipment WHERE equipment_id=?", (linked_id,)
        ).fetchone()
        if not linked or linked["process_id"] != process_id:
            raise PsmError("SOP 關聯設備須屬所選製程")
    old_site = conn.execute(
        """SELECT p.site_id FROM sop s JOIN process p ON p.process_id=s.process_id
           WHERE s.sop_id=?""", (data["sop_id"],)
    ).fetchone()
    new_site = conn.execute("SELECT site_id FROM process WHERE process_id=?", (process_id,)).fetchone()
    if old_site and new_site and old_site["site_id"] != new_site["site_id"]:
        raise PsmError("不可覆寫其他場所的 SOP 編號")
    conn.execute(
        """INSERT INTO sop(sop_id, process_id, title, procedure_no, body, op_kind, equipment_id, updated_on)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(sop_id) DO UPDATE SET title=excluded.title,
             procedure_no=excluded.procedure_no, body=excluded.body,
             process_id=excluded.process_id, op_kind=excluded.op_kind,
             equipment_id=excluded.equipment_id, updated_on=excluded.updated_on""",
        (
            data["sop_id"],
            process_id,
            data["title"],
            _nz(data.get("procedure_no")),
            data.get("body") or "",
            op_kind,
            eid,
            _nz(data.get("updated_on")),
        ),
    )
    conn.execute("DELETE FROM sop_equipment WHERE sop_id=?", (data["sop_id"],))
    conn.executemany(
        "INSERT INTO sop_equipment(sop_id,equipment_id,confirmed) VALUES (?,?,1)",
        [(data["sop_id"], linked_id) for linked_id in equipment_ids],
    )
    conn.commit()


def save_training_course(conn: sqlite3.Connection, data: dict) -> None:
    op_kind, process_id, eid = _resolve_op_target(conn, data)
    kind = _nz(data.get("kind")) or "initial"
    if kind not in ("initial", "refresher"):
        raise PsmError("訓練種類須為初次或在職")
    raw_sop_ids = data.get("sop_ids")
    if raw_sop_ids is None:
        raw_sop_ids = [data.get("sop_id")]
    if isinstance(raw_sop_ids, str):
        raw_sop_ids = [raw_sop_ids]
    sop_ids = list(dict.fromkeys(str(value).strip() for value in raw_sop_ids if str(value or "").strip()))
    for sop_id in sop_ids:
        sop = conn.execute("SELECT process_id FROM sop WHERE sop_id=?", (sop_id,)).fetchone()
        if not sop or sop["process_id"] != process_id:
            raise PsmError("關聯作業程序須屬於課程所選製程")
    conn.execute(
        """INSERT INTO training_course(
            course_id, process_id, name, hours, audience, kind, op_kind, equipment_id, sop_id,
            is_moc_related, refresh_hours, refresh_every, no_sop_reason)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(course_id) DO UPDATE SET
             process_id=excluded.process_id, name=excluded.name, hours=excluded.hours,
             audience=excluded.audience, kind=excluded.kind, op_kind=excluded.op_kind,
             equipment_id=excluded.equipment_id, sop_id=excluded.sop_id,
             is_moc_related=excluded.is_moc_related,
             refresh_hours=excluded.refresh_hours, refresh_every=excluded.refresh_every,
             no_sop_reason=excluded.no_sop_reason""",
        (
            data["course_id"],
            process_id,
            data["name"],
            float(data.get("hours") or 0),
            _nz(data.get("audience")),
            kind,
            op_kind,
            eid,
            sop_ids[0] if sop_ids else None,
            1 if str(data.get("is_moc_related") or "") in ("1", "on", "true", "是") else 0,
            _num_or_none(data.get("refresh_hours") if data.get("refresh_hours") is not None else data.get("retrain_hours")),
            _nz(data.get("refresh_every") or data.get("retrain_freq")),
            _nz(data.get("no_sop_reason")) if not sop_ids else None,
        ),
    )
    conn.execute("DELETE FROM training_course_sop WHERE course_id=?", (data["course_id"],))
    conn.executemany("INSERT INTO training_course_sop(course_id,sop_id) VALUES (?,?)",
                     [(data["course_id"], sop_id) for sop_id in sop_ids])
    conn.commit()


def process_inspect(conn: sqlite3.Connection, process_id: str, site_id: str) -> dict | None:
    row = conn.execute(
        """SELECT p.*, d.name AS operating_dept_name
           FROM process p JOIN department d ON d.dept_id=p.operating_dept_id
           WHERE p.process_id=? AND p.site_id=?""",
        (process_id, site_id),
    ).fetchone()
    if not row:
        return None
    equipment = [e for e in equipment_list_joined(conn, site_id) if e["process_id"] == process_id]
    eids = {e["equipment_id"] for e in equipment}
    chemicals = [
        dict(r)
        for r in conn.execute(
            """SELECT c.cas, c.process_id, c.name, c.role, c.un_number
               FROM chemical c WHERE c.process_id=? ORDER BY c.cas""",
            (process_id,),
        )
    ]
    sops = [
        dict(r)
        for r in conn.execute(
            """SELECT s.* FROM sop s WHERE s.process_id=? ORDER BY s.sop_id""",
            (process_id,),
        )
    ]
    courses = [
        dict(r)
        for r in conn.execute(
            """SELECT * FROM training_course WHERE process_id=? ORDER BY course_id""",
            (process_id,),
        )
    ]
    drawings = [
        dict(r)
        for r in conn.execute(
            """SELECT drawing_no, revision, name, issue_date, is_as_built
               FROM pid_drawing WHERE process_id=? ORDER BY drawing_no, revision""",
            (process_id,),
        )
    ]
    assessments = assessments_touching_process(conn, process_id)
    return {
        "process": dict(row),
        "equipment": equipment,
        "chemicals": chemicals,
        "process_sops": [s for s in sops if (s.get("op_kind") or "process") != "equipment"],
        "equipment_sops": [s for s in sops if s.get("op_kind") == "equipment" and s.get("equipment_id") in eids],
        "process_courses": [c for c in courses if (c.get("op_kind") or "process") != "equipment"],
        "equipment_courses": [c for c in courses if c.get("op_kind") == "equipment" and c.get("equipment_id") in eids],
        "drawings": drawings,
        "assessments": assessments,
        "pec_map": pec_map_rows(conn, process_id=process_id),
        "pha_prompts": prompt_events(conn, process_id=process_id, stage="pha"),
        "mi_prompts": prompt_events(conn, process_id=process_id, stage="mi"),
    }


def _group_ops_by_process(
    conn: sqlite3.Connection, site_id: str, items: list[dict], id_key: str
) -> dict:
    processes = [
        dict(r)
        for r in conn.execute(
            """SELECT p.*, d.name AS operating_dept_name
               FROM process p JOIN department d ON d.dept_id=p.operating_dept_id
               WHERE p.site_id=? ORDER BY p.process_id""",
            (site_id,),
        )
    ]
    equipment = equipment_list_joined(conn, site_id)
    proc_items: dict[str, list] = {}
    eq_items: dict[str, list] = {}
    for it in items:
        if (it.get("op_kind") or "process") == "equipment" and it.get("equipment_id"):
            eq_items.setdefault(it["equipment_id"], []).append(it)
        else:
            proc_items.setdefault(it["process_id"], []).append(it)
    for p in processes:
        p[id_key] = proc_items.get(p["process_id"], [])
        p["equipment"] = []
        for e in equipment:
            if e["process_id"] != p["process_id"]:
                continue
            row = dict(e)
            row[id_key] = eq_items.get(e["equipment_id"], [])
            p["equipment"].append(row)
    return {"processes": processes}


def sop_board(conn: sqlite3.Connection, site_id: str) -> dict:
    items = [
        dict(r)
        for r in conn.execute(
            """SELECT s.* FROM sop s
               JOIN process p ON p.process_id=s.process_id
               WHERE p.site_id=? ORDER BY s.sop_id""",
            (site_id,),
        )
    ]
    return _group_ops_by_process(conn, site_id, items, "sops")


def training_board(conn: sqlite3.Connection, site_id: str) -> dict:
    items = [
        dict(r)
        for r in conn.execute(
            """SELECT c.* FROM training_course c
               JOIN process p ON p.process_id=c.process_id
               WHERE p.site_id=? ORDER BY c.course_id""",
            (site_id,),
        )
    ]
    board = _group_ops_by_process(conn, site_id, items, "courses")
    board["records"] = [
        dict(r)
        for r in conn.execute(
            """SELECT r.*, c.process_id, c.name AS course_name, c.op_kind, c.equipment_id
               FROM training_record r
               JOIN training_course c ON c.course_id=r.course_id
               JOIN process p ON p.process_id=c.process_id
               WHERE p.site_id=?
               ORDER BY r.record_id""",
            (site_id,),
        )
    ]
    return board


def save_inspection(conn: sqlite3.Connection, data: dict) -> None:
    overdue = _b(data.get("overdue"))
    defect = _b(data.get("defect_open"))
    conn.execute(
        """INSERT INTO inspection(inspection_id, equipment_id, inspect_date, inspector,
            method, result, overdue, defect_open)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(inspection_id) DO UPDATE SET
             result=excluded.result, overdue=excluded.overdue, defect_open=excluded.defect_open""",
        (
            data["inspection_id"],
            data["equipment_id"],
            data["inspect_date"],
            data["inspector"],
            data["method"],
            data["result"],
            overdue,
            defect,
        ),
    )
    if overdue or defect:
        _stale_for_equipment_safeguard(conn, data["equipment_id"])
    conn.commit()


def save_change(conn: sqlite3.Connection, data: dict) -> None:
    table = _nz(data.get("target_table"))
    pk = _nz(data.get("target_pk"))
    if table not in ("Process", "Equipment", "Chemical"):
        raise PsmError("變更必須指明被改的主檔表名（Process／Equipment／Chemical）")
    if not pk:
        raise PsmError("變更必須指明被改列的 PK")
    if table == "Equipment":
        if not conn.execute("SELECT 1 FROM equipment WHERE equipment_id=?", (pk,)).fetchone():
            raise PsmError("被變更設備 PK 不存在")
    elif table == "Process":
        if not conn.execute("SELECT 1 FROM process WHERE process_id=?", (pk,)).fetchone():
            raise PsmError("被變更製程 PK 不存在")
    else:
        if "|" in pk:
            cas, process_id = pk.split("|", 1)
        else:
            raise PsmError("化學品 PK 須為 cas|process_id")
        if not conn.execute(
            "SELECT 1 FROM chemical WHERE cas=? AND process_id=?", (cas, process_id)
        ).fetchone():
            raise PsmError("被變更化學品 PK 不存在")
    conn.execute(
        """INSERT INTO change_request(change_id, target_table, target_pk, description,
            change_type, status, approved, impact_json)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(change_id) DO UPDATE SET
             description=excluded.description, status=excluded.status,
             approved=excluded.approved""",
        (
            data["change_id"],
            table,
            pk,
            data["description"],
            _nz(data.get("change_type")),
            data.get("status") or "approved",
            _b(data.get("approved")),
            _nz(data.get("impact_json")),
        ),
    )
    if _b(data.get("approved")):
        _mark_stale(conn, table, pk)
    conn.commit()


def close_recommendation(conn: sqlite3.Connection, rec_id: str) -> None:
    rec = conn.execute(
        "SELECT * FROM recommendation WHERE rec_id=?", (rec_id,)
    ).fetchone()
    if not rec:
        raise PsmError("改善建議不存在")
    if not _nz(rec["target_table"]) or not _nz(rec["target_pk"]):
        raise PsmError("改善關閉：須已指明主檔列（表名+PK），只勾「已改善」不得關")
    if rec["target_table"] not in ("Process", "Equipment", "Chemical"):
        raise PsmError("改善關閉：須指向 Process／Equipment／Chemical")
    if not rec["master_updated"]:
        raise PsmError("改善關閉：主檔尚未更新")
    if not rec["reassessed_or_waiver"]:
        raise PsmError("改善關閉：節點須已重評或合格人員記載無須重評")
    conn.execute("UPDATE recommendation SET closed=1 WHERE rec_id=?", (rec_id,))
    conn.commit()


def save_recommendation(conn: sqlite3.Connection, data: dict) -> None:
    conn.execute(
        """INSERT INTO recommendation(rec_id, assessment_id, consequence_id, target_table,
            target_pk, description, marked_improved, master_updated,
            reassessed_or_waiver, waiver_by, closed)
           VALUES (?,?,?,?,?,?,?,?,?,?,0)
           ON CONFLICT(rec_id) DO UPDATE SET
             target_table=excluded.target_table, target_pk=excluded.target_pk,
             description=excluded.description, marked_improved=excluded.marked_improved,
             master_updated=excluded.master_updated,
             reassessed_or_waiver=excluded.reassessed_or_waiver,
             waiver_by=excluded.waiver_by""",
        (
            data["rec_id"],
            data["assessment_id"],
            _nz(data.get("consequence_id")),
            _nz(data.get("target_table")),
            _nz(data.get("target_pk")),
            data["description"],
            _b(data.get("marked_improved")),
            _b(data.get("master_updated")),
            _b(data.get("reassessed_or_waiver")),
            _nz(data.get("waiver_by")),
        ),
    )
    conn.commit()


def _mark_stale(conn: sqlite3.Connection, table: str, pk: str) -> None:
    process_ids: list[str] = []
    equipment_ids: list[str] = []
    if table == "Process":
        process_ids = [pk]
    elif table == "Equipment":
        equipment_ids = [pk]
        row = conn.execute(
            "SELECT process_id FROM equipment WHERE equipment_id=?", (pk,)
        ).fetchone()
        if row:
            process_ids = [row["process_id"]]
    elif table == "Chemical":
        if "|" in pk:
            process_ids = [pk.split("|", 1)[1]]
    if process_ids:
        q = ",".join("?" * len(process_ids))
        conn.execute(
            f"""UPDATE risk_score SET stale=1
                WHERE consequence_id IN (
                  SELECT c.consequence_id FROM consequence c
                  JOIN node n ON n.node_id=c.node_id
                  WHERE n.process_id IN ({q})
                )""",
            process_ids,
        )
    if equipment_ids:
        q = ",".join("?" * len(equipment_ids))
        conn.execute(
            f"""UPDATE risk_score SET stale=1
                WHERE consequence_id IN (
                  SELECT c.consequence_id FROM consequence c
                  JOIN node n ON n.node_id=c.node_id
                  JOIN node_equipment ne ON ne.node_id=n.node_id
                  WHERE ne.equipment_id IN ({q})
                )""",
            equipment_ids,
        )


def _stale_for_equipment_safeguard(conn: sqlite3.Connection, equipment_id: str) -> None:
    conn.execute(
        """UPDATE risk_score SET stale=1
           WHERE consequence_id IN (
             SELECT s.consequence_id FROM safeguard s WHERE s.equipment_id=?
           )""",
        (equipment_id,),
    )


def generate_report_html(conn: sqlite3.Connection, site_id: str) -> str:
    if site_id == WIZARD_SITE_ID or get_flag(conn, site_id, "report_v83") == "1":
        return render_report_v83(conn, site_id)
    return render_report_html(conn, site_id)


def matrix_legend() -> str:
    return f"矩陣 {MATRIX_VERSION}（5×5）。可接受線：{MATRIX_ACCEPT_LINE}"


def unit_title(n: int) -> str:
    return UNIT_TITLES[n]


def save_site_basic_doc(conn: sqlite3.Connection, data: dict) -> None:
    site_id = _nz(data.get("site_id"))
    item_no = int(data.get("item_no") or 0)
    if not site_id or item_no < 1:
        raise PsmError("送審第二章附件須有場所與項次")
    conn.execute(
        """INSERT INTO site_basic_doc(site_id, item_no, title, doc_date, file_path,
            not_applicable, see_also)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(site_id, item_no) DO UPDATE SET
             title=excluded.title, doc_date=excluded.doc_date,
             file_path=excluded.file_path, not_applicable=excluded.not_applicable,
             see_also=excluded.see_also""",
        (
            site_id,
            item_no,
            _nz(data.get("title")),
            _nz(data.get("doc_date")),
            _nz(data.get("file_path")),
            _b(data.get("not_applicable")),
            _nz(data.get("see_also")),
        ),
    )
    conn.commit()


def save_incident(conn: sqlite3.Connection, data: dict) -> str:
    """附表11.2-1：事故共通資料只登在這裡。"""
    iid = _nz(data.get("incident_id"))
    summary = _nz(data.get("summary"))
    if not iid or not summary:
        raise PsmError("事故須有編號與摘要")
    lost = data.get("lost_days")
    try:
        lost_days = int(lost) if lost not in (None, "") else None
    except (TypeError, ValueError):
        lost_days = None
    cas = _nz(data.get("cas"))
    process_id = _nz(data.get("process_id"))
    sds_id = _nz(data.get("sds_id"))
    site_id = _nz(data.get("site_id"))
    if process_id:
        process = conn.execute("SELECT site_id FROM process WHERE process_id=?", (process_id,)).fetchone()
        if not process or (site_id and process["site_id"] != site_id):
            raise PsmError("事故製程須屬於本場所")
        site_id = process["site_id"]
    if not site_id or not conn.execute("SELECT 1 FROM site WHERE site_id=?", (site_id,)).fetchone():
        raise PsmError("事故須指定所屬場所")
    equipment_id = _nz(data.get("equipment_id"))
    if equipment_id:
        equipment = conn.execute(
            "SELECT site_id, process_id FROM equipment WHERE equipment_id=?", (equipment_id,)
        ).fetchone()
        if not equipment or equipment["site_id"] != site_id or (process_id and equipment["process_id"] != process_id):
            raise PsmError("事故設備須屬於所選場所及製程")
    existing = conn.execute("SELECT site_id FROM incident WHERE incident_id=?", (iid,)).fetchone()
    if existing and existing["site_id"] not in (None, site_id):
        raise PsmError("事故編號已由其他場所使用")
    if cas and process_id:
        sds_id = resolve_component_sds(conn, process_id, cas, sds_id)
    elif cas and not sds_id:
        raise PsmError("事故列了化學品時須指定 SDS")
    conn.execute(
        """INSERT INTO incident(
            incident_id, site_id, process_id, equipment_id, cas, sds_id, incident_date, summary,
            is_near_miss, included_in_assessment, casualty, lost_days, cause,
            corrective, characteristics
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(incident_id) DO UPDATE SET
            site_id=excluded.site_id,
            process_id=excluded.process_id,
            equipment_id=excluded.equipment_id,
            cas=excluded.cas,
            sds_id=excluded.sds_id,
            incident_date=excluded.incident_date,
            summary=excluded.summary,
            is_near_miss=excluded.is_near_miss,
            casualty=excluded.casualty,
            lost_days=excluded.lost_days,
            cause=excluded.cause,
            corrective=excluded.corrective,
            characteristics=excluded.characteristics
        """,
        (
            iid,
            site_id,
            process_id,
            equipment_id,
            cas,
            sds_id,
            _nz(data.get("incident_date") or data.get("occur_date")),
            summary,
            _b(data.get("is_near_miss")),
            _b(data.get("included_in_assessment")),
            _nz(data.get("casualty")),
            lost_days,
            _nz(data.get("cause")),
            _nz(data.get("corrective")),
            _nz(data.get("characteristics")),
        ),
    )
    conn.commit()
    return iid


def save_contractor(conn: sqlite3.Connection, data: dict) -> int:
    """A contractor remains on the roster even when there are no incidents."""
    site_id = _nz(data.get("site_id"))
    name = _nz(data.get("name"))
    period = _nz(data.get("contract_period"))
    if not site_id or not conn.execute("SELECT 1 FROM site WHERE site_id=?", (site_id,)).fetchone():
        raise PsmError("承攬商須有已建立的場所")
    if not name or not period:
        raise PsmError("承攬商名稱與承攬期間必填")
    contractor_id = data.get("contractor_id")
    if contractor_id:
        owned = conn.execute(
            "SELECT 1 FROM contractor WHERE contractor_id=? AND site_id=?", (contractor_id, site_id)
        ).fetchone()
        if not owned:
            raise PsmError("找不到本場所的承攬商")
        conn.execute(
            """UPDATE contractor SET name=?, contract_period=?, work_description=?
               WHERE contractor_id=?""",
            (name, period, _nz(data.get("work_description")) or "", contractor_id),
        )
        conn.commit()
        return int(contractor_id)
    cursor = conn.execute(
        """INSERT INTO contractor(site_id, name, contract_period, work_description)
           VALUES (?,?,?,?)""",
        (site_id, name, period, _nz(data.get("work_description")) or ""),
    )
    conn.commit()
    return int(cursor.lastrowid)


def save_mi_screen(conn: sqlite3.Connection, data: dict) -> None:
    """附表8.1-1。篩選結果不回寫設備主檔。"""
    eid = _nz(data.get("equipment_id"))
    basis = _nz(data.get("basis"))
    if not eid or not basis:
        raise PsmError("安全關鍵性篩選須有設備編號與依據")
    if not conn.execute("SELECT 1 FROM equipment WHERE equipment_id=?", (eid,)).fetchone():
        raise PsmError("設備須選已有編號")
    critical = _b(data.get("is_critical"))
    if not critical:
        if conn.execute("SELECT 1 FROM mi_inspection_detail WHERE equipment_id=?", (eid,)).fetchone():
            raise PsmError("該設備已有檢查明細，請先刪除後再改判為否")
        if conn.execute("SELECT 1 FROM mi_failure WHERE equipment_id=?", (eid,)).fetchone():
            raise PsmError("該設備已有失效率紀錄，請先刪除後再改判為否")
    conn.execute(
        """INSERT INTO mi_screen(equipment_id,is_critical,basis) VALUES (?,?,?)
           ON CONFLICT(equipment_id) DO UPDATE SET
           is_critical=excluded.is_critical,basis=excluded.basis""",
        (eid, critical, basis),
    )
    mi_type = _nz(data.get("mi_type")) or ""
    if mi_type:
        from psm.filing import MI_SIX
        if mi_type not in MI_SIX:
            raise PsmError("設備類型須選六大類之一")
        conn.execute("UPDATE mi_screen SET mi_type=?,mi_type_confirmed=1 WHERE equipment_id=?",
                     (mi_type, eid))
    damage = _nz(data.get("damage_mechanism")) or ""
    item = _nz(data.get("inspection_item")) or ""
    method = _nz(data.get("inspect_method")) or ""
    frequency = _nz(data.get("inspect_frequency")) or ""
    procedure = _nz(data.get("procedure_ref")) or ""
    pid = _nz(data.get("pid_drawing_no")) or ""
    if critical and (damage or item or method or frequency or procedure or pid):
        if damage and item:
            raise PsmError("每筆檢查明細請擇一填損壞機制或功能檢查項目")
        named_item = bool(damage or item)
        if not (damage or item):
            item = "待補檢查項目"
        existing = conn.execute(
            """SELECT detail_id FROM mi_inspection_detail WHERE equipment_id=?
               AND damage_mechanism=? AND inspection_item=? LIMIT 1""",
            (eid, damage, item),
        ).fetchone()
        pid_valid = bool(pid and conn.execute(
            """SELECT 1 FROM pid_drawing p JOIN equipment e ON e.process_id=p.process_id
               WHERE e.equipment_id=? AND p.drawing_no=?""", (eid, pid),
        ).fetchone())
        confirmed = int(bool(named_item and method and frequency and procedure and pid_valid))
        if existing:
            conn.execute(
                """UPDATE mi_inspection_detail SET inspect_method=?,inspect_frequency=?,
                   procedure_ref=?,pid_drawing_no=?,confirmed=? WHERE detail_id=?""",
                (method, frequency, procedure, pid, confirmed, existing["detail_id"]),
            )
        else:
            conn.execute(
                """INSERT INTO mi_inspection_detail
                   (equipment_id,damage_mechanism,inspection_item,inspect_method,
                    inspect_frequency,procedure_ref,pid_drawing_no,confirmed)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (eid, damage, item, method, frequency, procedure, pid, confirmed),
            )
    conn.commit()


def save_mi_failure(conn: sqlite3.Connection, data: dict) -> None:
    """附表8.2-1：只列附表8.1-1 確認為是的設備，逐台填運行時間與失效次數。"""
    eid = _nz(data.get("equipment_id"))
    if not eid:
        raise PsmError("設備編號必填")
    screen = conn.execute(
        "SELECT is_critical FROM mi_screen WHERE equipment_id=?", (eid,)
    ).fetchone()
    if not screen or not screen["is_critical"]:
        raise PsmError("失效率只填附表8.1-1 確認為安全關鍵性設備者")
    try:
        hours = float(data.get("run_hours"))
        count_number = float(data.get("failure_count"))
        if not isfinite(hours) or not isfinite(count_number) or not count_number.is_integer():
            raise ValueError
        count = int(count_number)
    except (TypeError, ValueError):
        raise PsmError("須填運行小時數與失效次數")
    if hours < 0 or count < 0:
        raise PsmError("運行時間與失效次數不得為負")
    start = _nz(data.get("period_start"))
    end = _nz(data.get("period_end"))
    try:
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise ValueError
    except ValueError:
        raise PsmError("須填有效的統計期間起訖")
    note = _nz(data.get("note")) or ""
    if hours == 0 and not note:
        raise PsmError("運行時間為零須填原因")
    conn.execute(
        """INSERT INTO mi_failure(
            equipment_id, period_start, period_end, run_hours, failure_count,note,confirmed
        ) VALUES (?,?,?,?,?,?,1)
        ON CONFLICT(equipment_id) DO UPDATE SET
            period_start=excluded.period_start, period_end=excluded.period_end,
            run_hours=excluded.run_hours, failure_count=excluded.failure_count,
            note=excluded.note,confirmed=1
        """,
        (eid, start, end, hours, count, note),
    )
    conn.commit()


def save_contractor_incident(conn: sqlite3.Connection, data: dict) -> str:
    site_id = _nz(data.get("site_id"))
    if not site_id:
        raise PsmError("場所必填")
    contractor_id = data.get("contractor_id")
    roster = None
    if contractor_id:
        roster = conn.execute(
            "SELECT * FROM contractor WHERE contractor_id=? AND site_id=?", (contractor_id, site_id)
        ).fetchone()
        if not roster:
            raise PsmError("承攬事故須選本場所已登錄的承攬商")
    name = roster["name"] if roster else _nz(data.get("contractor_name") or data.get("vendor"))
    if not name:
        raise PsmError("承攬人／廠商必填")
    linked = _nz(data.get("linked_incident_id"))
    summary = _nz(data.get("summary")) or ""
    if linked:
        if not conn.execute(
            "SELECT 1 FROM incident WHERE incident_id=? AND site_id=?", (linked, site_id)
        ).fetchone():
            raise PsmError("承攬列須關聯附表11.2-1 已存在的事故項次")
    elif not summary:
        raise PsmError("未關聯事故項次時，事故摘要必填")
    itype = _nz(data.get("incident_type")) or "虛驚"
    if itype not in INCIDENT_TYPES:
        raise PsmError("事故類型須為職業災害或虛驚")
    iid = _nz(data.get("incident_id"))
    if not iid:
        n = conn.execute(
            "SELECT COUNT(*) FROM contractor_incident WHERE site_id=?", (site_id,)
        ).fetchone()[0]
        iid = f"CTR-{n + 1:03d}"
    lost = data.get("lost_days")
    try:
        lost_days = int(lost) if lost not in (None, "") else None
    except (TypeError, ValueError):
        lost_days = None
    if linked:
        summary = ""
        lost_days = None
    conn.execute(
        """INSERT INTO contractor_incident(
            incident_id, site_id, contractor_id, contractor_name, contract_period, occur_date,
            incident_type, summary, casualty, lost_days, cause,
            process_id, equipment_id, corrective, linked_incident_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(incident_id) DO UPDATE SET
            contractor_id=excluded.contractor_id,
            contractor_name=excluded.contractor_name,
            contract_period=excluded.contract_period,
            occur_date=excluded.occur_date,
            incident_type=excluded.incident_type,
            summary=excluded.summary,
            casualty=excluded.casualty,
            lost_days=excluded.lost_days,
            cause=excluded.cause,
            process_id=excluded.process_id,
            equipment_id=excluded.equipment_id,
            corrective=excluded.corrective,
            linked_incident_id=excluded.linked_incident_id
        """,
        (
            iid,
            site_id,
            int(contractor_id) if contractor_id else None,
            name,
            roster["contract_period"] if roster else _nz(data.get("contract_period") or data.get("period")),
            None if linked else _nz(data.get("occur_date")),
            itype,
            summary,
            None if linked else _nz(data.get("casualty")),
            lost_days,
            None if linked else _nz(data.get("cause")),
            None if linked else _nz(data.get("process_id")),
            None if linked else _nz(data.get("equipment_id")),
            None if linked else _nz(data.get("corrective")),
            linked,
        ),
    )
    conn.commit()
    return iid


def save_hotwork_zone(conn: sqlite3.Connection, data: dict) -> None:
    area = _nz(data.get("area_code") or data.get("area_id"))
    if not area:
        raise PsmError("動火管制區域須選表1.0-5")
    if not conn.execute("SELECT 1 FROM area WHERE area_code=?", (area,)).fetchone():
        raise PsmError("區域不存在")
    reason = _nz(data.get("protection_reason"))
    if not reason:
        raise PsmError("須填列舉動火區域之防護原因")
    listed = conn.execute(
        "SELECT 1 FROM explosion_area WHERE area_code=?", (area,)
    ).fetchone()
    if data.get("is_explosion_zone") in (None, ""):
        is_ex = 1 if listed else 0
    else:
        is_ex = _b(data.get("is_explosion_zone"))
    note = _nz(data.get("explosion_note"))
    if not note:
        note = "已列防爆分區（表1.8-1）" if listed else "未列防爆分區"
    conn.execute(
        """INSERT INTO hotwork_zone(
            area_code, is_explosion_zone, explosion_note, protection_reason
        ) VALUES (?,?,?,?)
        ON CONFLICT(area_code) DO UPDATE SET
            is_explosion_zone=excluded.is_explosion_zone,
            explosion_note=excluded.explosion_note,
            protection_reason=excluded.protection_reason
        """,
        (area, is_ex, note, reason),
    )
    conn.commit()


def save_process_route(conn: sqlite3.Connection, data: dict) -> None:
    route_id = _nz(data.get("route_id"))
    site_id = _nz(data.get("site_id"))
    if not route_id or not site_id:
        raise PsmError("製造路線編號與場所必填")
    conn.execute(
        """INSERT INTO process_route(route_id, site_id, note) VALUES (?,?,?)
           ON CONFLICT(route_id) DO UPDATE SET note=excluded.note, site_id=excluded.site_id""",
        (route_id, site_id, _nz(data.get("note"))),
    )
    conn.execute("DELETE FROM process_route_chemical WHERE route_id=?", (route_id,))
    conn.execute("DELETE FROM process_route_equipment WHERE route_id=?", (route_id,))
    conn.execute("DELETE FROM process_route_block WHERE route_id=?", (route_id,))
    for block in data.get("blocks") or []:
        seq = int(block.get("seq_no") or 0)
        pid = _nz(block.get("process_id"))
        if seq < 1 or not pid:
            continue
        if not conn.execute("SELECT 1 FROM process WHERE process_id=?", (pid,)).fetchone():
            raise PsmError(f"路線方塊所選製程 {pid} 不存在")
        conn.execute(
            """INSERT INTO process_route_block(route_id, seq_no, process_id, note)
               VALUES (?,?,?,?)""",
            (route_id, seq, pid, _nz(block.get("note"))),
        )
        for eid in block.get("equipment_ids") or []:
            eid = _nz(eid)
            if not eid:
                continue
            row = conn.execute(
                "SELECT process_id FROM equipment WHERE equipment_id=?", (eid,)
            ).fetchone()
            if not row or row["process_id"] != pid:
                raise PsmError(f"設備 {eid} 不屬於製程 {pid}")
            conn.execute(
                """INSERT OR IGNORE INTO process_route_equipment(route_id, seq_no, equipment_id)
                   VALUES (?,?,?)""",
                (route_id, seq, eid),
            )
        for item in block.get("cas_list") or []:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                cpid, cas = _nz(item[0]), _nz(item[1])
            else:
                cpid, cas = pid, _nz(item)
            if not cas:
                continue
            if not conn.execute(
                "SELECT 1 FROM chemical_cite WHERE cas=? AND process_id=?",
                (cas, cpid),
            ).fetchone():
                raise PsmError(f"化學品 {cas}／{cpid} 未列於表1.0-4")
            conn.execute(
                """INSERT OR IGNORE INTO process_route_chemical(
                    route_id, seq_no, process_id, cas
                ) VALUES (?,?,?,?)""",
                (route_id, seq, cpid, cas),
            )
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT v FROM app_meta WHERE k=?", (key,)).fetchone()
    return row["v"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """INSERT INTO app_meta(k, v) VALUES (?,?)
           ON CONFLICT(k) DO UPDATE SET v=excluded.v""",
        (key, value),
    )
    conn.commit()
