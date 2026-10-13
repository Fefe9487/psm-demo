"""Independent, editable teaching case for a refinery HF alkylation unit.

The case extends the existing HF handling example. Every number and record is
fictional. It is never seeded into the user's original wizard database.
Process background: https://www.osha.gov/publications/hib19931119
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from psm import filing as fil
from psm import services as svc
from psm import wizard as wiz
from psm.sample_flow import PETRO_FLOW_ROWS


DOCS = Path(__file__).resolve().parent / "sample_docs"
SAMPLE_NOTE = "教學假設；正式設計、SDS、數量與核准文件須由現場重新確認，不可據此操作。"


def _row(conn: sqlite3.Connection, site_id: str, section: str, payload: dict) -> None:
    fil.add_row(conn, site_id, section, payload)


def _chemical(conn: sqlite3.Connection, *, process: str, cas: str, sds: str,
              name: str, role: str, h_codes: str, phase: str, un: str = "") -> None:
    svc.save_chemical(conn, {
        "process_id": process, "cas": cas, "sds_id": sds, "name": name,
        "role": role, "h_codes": h_codes, "phase_state": phase,
        "un_number": un, "concentration_range": "依供應商 SDS",
    })


def seed_petrochemical_sample(conn: sqlite3.Connection, site_id: str) -> None:
    """Create the full teaching case once in its own SQLite file."""
    if conn.execute("SELECT 1 FROM site WHERE site_id=?", (site_id,)).fetchone():
        return
    for step in range(1, wiz.N_STEPS + 1):
        wiz.apply_step_defaults(conn, site_id, step)
    conn.execute("""DELETE FROM unstructured_attachment WHERE site_id=?
        AND kind='trade_secret'""", (site_id,))
    conn.execute("""INSERT INTO unstructured_attachment
        (site_id,process_id,kind,original_name,attachment_path,note)
        VALUES (?,NULL,'trade_secret',?,?,?)""",
        (site_id, "石化業-商業機密管理程序-示範草稿.txt",
         str(DOCS / "petro_trade_secret_demo.txt"), "示範草稿，不可作正式申報佐證"))
    conn.execute("""DELETE FROM unstructured_attachment WHERE kind='pha'
        AND original_name='PHA-評估紀錄.pdf' AND process_id='P-TANK'""")

    conn.execute("""UPDATE site SET company_name=?,site_name=?,scope=?,worker_count=?,
        declare_no_equipment_types='',declare_no_incident_5y=0 WHERE site_id=?""",
        ("海灣石化股份有限公司（虛構）", "HF 催化烷基化示範單元",
         "異丁烷與丁烯進料、HF 催化烷基化、產品分離與含氟尾氣鹼洗；全部數值為教學假設",
         28, site_id))
    conn.execute("UPDATE department SET headcount=20 WHERE dept_id='D-OPS'")
    conn.execute("UPDATE department SET headcount=8 WHERE dept_id='D-MAINT'")
    conn.execute("UPDATE process SET name=?,overview=? WHERE process_id='P-TANK'",
                 ("HF 催化劑循環供料", "HF 催化劑密閉供料並回收循環至烷基化反應器；尾氣進入鹼洗系統。"))
    conn.commit()

    for pid, name, overview, reaction, downstream in (
        ("P-FEED", "異丁烷與丁烯進料", "異丁烷與丁烯經密閉輸送與配比後送至反應器。", False, False),
        ("P-REACT", "HF 催化烷基化反應", "異丁烷與丁烯在 HF 催化劑存在下反應生成烷基化油，酸相密閉回收。", True, False),
        ("P-PRODUCT", "烷基化油分離與暫存", "反應產物分離未反應輕烴後，產品送至密閉暫存槽。", False, True),
    ):
        svc.save_process(conn, {
            "process_id": pid, "site_id": site_id, "name": name, "overview": overview,
            "operating_dept_id": "D-OPS", "mode": "continuous",
            "has_chemical_reaction": reaction, "has_overpressure": True,
            "is_special": False, "is_loading": False, "is_downstream": downstream,
        })
    for code, name, pid in (
        ("AREA-F", "輕烴進料區", "P-FEED"),
        ("AREA-R", "HF 烷基化反應區", "P-REACT"),
        ("AREA-P", "產品分離與暫存區", "P-PRODUCT"),
    ):
        svc.save_area(conn, {
            "area_code": code, "site_id": site_id, "name": name,
            "drawing_no": "PLOT-ALK-001", "revision": "A", "issue_date": "2026-01-15",
            "process_id": pid, "attachment_path": "placeholder://PLOT-ALK-001-A",
            "worker_count": 6, "contractor_count": 2,
        })

    equipment = (
        ("V-301", "輕烴進料緩衝槽", "P-FEED", "AREA-F", "壓力容器與儲槽", "液體", "碳鋼"),
        ("P-301", "輕烴進料泵", "P-FEED", "AREA-F", "動力來源", "液體", "碳鋼"),
        ("R-301", "HF 烷基化反應器", "P-REACT", "AREA-R", "壓力容器與儲槽", "液體", "材質與 HF 相容性待核對"),
        ("ESD-301", "反應區緊急停車系統", "P-REACT", "AREA-R", "緊急停車系統", "液體", "控制盤"),
        ("PSV-301", "反應器釋壓閥", "P-REACT", "AREA-R", "釋放及排放系統", "液體", "材質待核對"),
        ("C-301", "產品分離塔", "P-PRODUCT", "AREA-P", "壓力容器與儲槽", "液體", "碳鋼"),
        ("T-301", "烷基化油暫存槽", "P-PRODUCT", "AREA-P", "壓力容器與儲槽", "液體", "碳鋼"),
    )
    for eid, name, pid, area, kind, phase, material in equipment:
        svc.save_equipment(conn, {
            "equipment_id": eid, "site_id": site_id, "name": name,
            "process_id": pid, "area_code": area, "maint_dept_id": "D-MAINT",
            "equipment_type": kind, "phase_class": phase,
            "power_kind": "泵浦" if eid == "P-301" else None,
            "material": material, "is_safety_critical": False,
            "is_regulated_machinery": eid == "R-301",
        })
    for sds, name, cas in (
        ("SDS-IB-001", "異丁烷", "75-28-5"),
        ("SDS-BUT-001", "反式-2-丁烯", "624-64-6"),
        ("SDS-ISO-001", "2,2,4-三甲基戊烷（產品代表組分）", "540-84-1"),
    ):
        svc.save_sds(conn, {
            "sds_id": sds, "site_id": site_id, "substance_or_mixture_name": name,
            "file_path": f"placeholder://{sds}.pdf", "component_cas_list": cas,
        })
    for pid in ("P-FEED", "P-REACT"):
        _chemical(conn, process=pid, cas="75-28-5", sds="SDS-IB-001",
                  name="異丁烷", role="原物料", h_codes="H220,H280", phase="氣態", un="UN 1969")
        _chemical(conn, process=pid, cas="624-64-6", sds="SDS-BUT-001",
                  name="反式-2-丁烯", role="原物料", h_codes="H220,H280", phase="氣態", un="UN 1012")
    _chemical(conn, process="P-REACT", cas="7664-39-3", sds="SDS-HF-001",
              name="無水氟化氫", role="觸媒", h_codes="H314,H330", phase="液態", un="UN 1052")
    for pid in ("P-REACT", "P-PRODUCT"):
        _chemical(conn, process=pid, cas="540-84-1", sds="SDS-ISO-001",
                  name="2,2,4-三甲基戊烷（烷基化油代表組分）", role="產物",
                  h_codes="H225,H304,H315", phase="液態", un="UN 1262")
    fill_petro_area_links(conn)

    for cas, pid, name, area, max_kg, monthly, codes in (
        ("75-28-5", "P-FEED", "異丁烷", "AREA-F", "18000", "120000", "H220,H280"),
        ("624-64-6", "P-FEED", "反式-2-丁烯", "AREA-F", "9000", "70000", "H220,H280"),
        ("7664-39-3", "P-REACT", "無水氟化氫", "AREA-R", "2500", "8000", "H314,H330"),
        ("540-84-1", "P-PRODUCT", "2,2,4-三甲基戊烷（代表組分）", "AREA-P", "24000", "150000", "H225,H304,H315"),
    ):
        flags = fil.h_code_flags(codes)
        _row(conn, site_id, "1.1", {
            "cas": cas, "process_id": pid, "name": name, "dept_id": "D-OPS",
            "max_kg": max_kg, "monthly_kg": monthly, "area_code": area,
            "regulation": SAMPLE_NOTE,
            **{key: flags[key] for key in ("is_danger", "is_harmful", "is_high_flammable", "is_high_toxic")},
        })
        conn.execute("""INSERT OR REPLACE INTO inventory(cas,process_id,max_kg,area_code,calc_note)
            VALUES (?,?,?,?,?)""", (cas, pid, float(max_kg), area, SAMPLE_NOTE))
        _row(conn, site_id, "1.2", {
            "cas": cas, "process_id": pid, "name": name,
            "name_en": {"75-28-5": "Isobutane", "624-64-6": "trans-2-Butene",
                        "7664-39-3": "Hydrogen fluoride", "540-84-1": "2,2,4-Trimethylpentane"}[cas],
            "conc": "依供應商 SDS", "ctrl_qty": "依現行公告核對",
            "state": "氣" if cas in ("75-28-5", "624-64-6") else "液",
            "odor": "依供應商 SDS", "vp": "依供應商 SDS", "bp": "依供應商 SDS",
            "fp": "依供應商 SDS", "expl": "依供應商 SDS",
            "twa": "依現行法定限值核對", "physical": "易燃" if cas != "7664-39-3" else "腐蝕性",
            "health": "依供應商 SDS", "incompat": "是",
            "incompat_note": "氧化劑及不相容介質，依 SDS 與設計文件核對",
            "stable": "是", "stable_note": SAMPLE_NOTE,
        })
    conn.commit()

    fil.replace_section(conn, site_id, "1.3b", PETRO_FLOW_ROWS)
    _row(conn, site_id, "1.4", {
        "process_id": "P-REACT", "kinds": "烷基化",
        "formula": "C₄H₁₀（異丁烷）＋ C₄H₈（丁烯）→ C₈H₁₈（烷基化油代表式）",
        "heat": "放熱反應；反應熱與移熱負荷須由核准熱平衡文件確認",
    })
    conn.execute("""INSERT OR REPLACE INTO reaction_info(process_id,summary,formula,heat,kinds)
        VALUES (?,?,?,?,?)""", ("P-REACT", "HF 催化異丁烷與丁烯烷基化",
        "C4H10 + C4H8 → C8H18", "放熱；數值待核准設計文件", "烷基化"))
    fil.set_flag(conn, site_id, "overview:P-FEED", "異丁烷與丁烯密閉進料並配比。")
    fil.set_flag(conn, site_id, "overview:P-REACT", "HF 催化烷基化反應及酸相循環。")
    fil.set_flag(conn, site_id, "overview:P-PRODUCT", "烷基化油分離及暫存。")

    svc.save_pid_drawing(conn, {
        "drawing_no": "PID-ALK-301", "revision": "A", "process_id": "P-REACT",
        "name": "HF 烷基化反應區管線儀表圖", "issue_date": "2026-01-15",
        "is_as_built": True, "attachment_path": "placeholder://PID-ALK-301-A",
        "eval_record_no": "PHA-ALK-001",
    }, covering_ids=["R-301", "ESD-301", "PSV-301"])
    for eid in ("R-301", "V-301", "C-301", "T-301"):
        svc.save_equipment_material(conn, {
            "equipment_id": eid, "material": "材質待核准設備資料表確認",
            "material_category": "其他", "spec": SAMPLE_NOTE,
        })
        _row(conn, site_id, "1.6", {
            "equipment_id": eid, "scope": "HF 烷基化單元",
            "material": "材質待核准設備資料表確認", "material_category": "其他",
            "spec": SAMPLE_NOTE,
        })
    _row(conn, site_id, "1.9", {
        "equipment_id": "PSV-301", "device_type": "安全閥",
        "calc_no": "REL-R301-DEMO", "spec_no": "依核准設計規範",
        "pid_no": "PID-ALK-301", "area_code": "AREA-R", "cas": "7664-39-3",
        "process_id": "P-REACT", "phase": "液", "set_p": "待設計核對",
        "capacity": "待設計核對", "nozzle": "待設計核對",
        "scenario": "反應熱移除失效或出口堵塞致超壓",
        "basis": SAMPLE_NOTE,
    })
    _row(conn, site_id, "1.10", {
        "equipment_id": "ESD-301", "name": "反應器高高壓與 HF 偵測連鎖",
        "kind": "硬體", "function": "隔離輕烴進料並啟動安全處理路徑",
        "normal": "依核准設計", "warn": "依警報設定表",
        "alarm": "依連鎖邏輯圖", "reset": "手動核准後復歸",
    })
    _row(conn, site_id, "1.11", {
        "equipment_id": "R-301", "category": "危險性設備",
        "expire": "2027-12-31", "cert_no": "DEMO-PV-301",
    })
    for area, pid, cas, sds in (
        ("AREA-F", "P-FEED", "75-28-5", "SDS-IB-001"),
        ("AREA-R", "P-REACT", "624-64-6", "SDS-BUT-001"),
        ("AREA-P", "P-PRODUCT", "540-84-1", "SDS-ISO-001"),
    ):
        conn.execute("""INSERT OR IGNORE INTO explosion_area
            (area_code,cas,process_id,sds_id,zone_class) VALUES (?,?,?,?,'2')""",
            (area, cas, pid, sds))
        _row(conn, site_id, "1.8", {
            "area_code": area, "floor": "地面層", "cas": cas,
            "process_id": pid, "comp": "指標化學品；詳依現場 SDS",
            "fp": "依 SDS", "bp": "依 SDS", "sg": "依 SDS",
            "expl": "依 SDS", "ait": "依 SDS",
            "vent_type": "N", "vent_level": "VM", "vent_avail": "B",
            "leak": "S", "zone": "2", "eq_group": "依核准防爆分區圖選用",
        })
    fil.set_flag(conn, site_id, "no_explosion", "0")
    conn.commit()

    _fill_operating_tables(conn, site_id)
    fill_design_codes(conn, site_id)
    _fill_management_tables(conn, site_id)
    conn.commit()


def fill_petro_area_links(conn: sqlite3.Connection) -> None:
    for area, pid, cas_list in (
        ("AREA-F", "P-FEED", ("75-28-5", "624-64-6")),
        ("AREA-R", "P-REACT", ("75-28-5", "624-64-6", "7664-39-3", "540-84-1")),
        ("AREA-P", "P-PRODUCT", ("540-84-1",)),
    ):
        conn.execute("UPDATE area SET linked_cas=? WHERE area_code=?",
                     (",".join(f"{cas}|{pid}" for cas in cas_list), area))
        for cas in cas_list:
            for chemical in conn.execute("SELECT sds_id FROM chemical WHERE process_id=? AND cas=?",
                                         (pid, cas)):
                conn.execute("""INSERT OR IGNORE INTO area_chemical
                    (area_code,process_id,sds_id,cas) VALUES (?,?,?,?)""",
                    (area, pid, chemical["sds_id"], cas))
    conn.commit()


def fill_design_codes(conn: sqlite3.Connection, site_id: str) -> None:
    """Populate the current, editable 1.6 table, including its relation tables."""
    if conn.execute("SELECT 1 FROM design_code_process LIMIT 1").fetchone():
        return
    for eq in conn.execute("""SELECT equipment_id,process_id,material,material_category
        FROM equipment WHERE site_id=? ORDER BY process_id,equipment_id""", (site_id,)):
        eid, pid = eq["equipment_id"], eq["process_id"]
        material = eq["material"] or "材質待核准設備資料表確認"
        category = eq["material_category"] or "其他"
        spec = "教學範例：設計規範與材料證明須逐台依核准文件確認"
        cursor = conn.execute("""INSERT INTO design_code
            (process_id,equipment_id,item,code,material_category,scope)
            VALUES (?,?,?,?,?,?)""", (pid, eid, material, spec, category, "單台設備；不可作正式設計依據"))
        code_id = cursor.lastrowid
        conn.execute("INSERT INTO design_code_process(code_id,process_id) VALUES (?,?)", (code_id, pid))
        conn.execute("INSERT INTO design_code_equipment(code_id,equipment_id) VALUES (?,?)", (code_id, eid))
        cas_list = [r[0] for r in conn.execute(
            "SELECT DISTINCT cas FROM equipment_content WHERE equipment_id=? AND no_process_chemical=0",
            (eid,))]
        for cas in cas_list:
            conn.execute("INSERT INTO design_code_chemical(code_id,process_id,cas) VALUES (?,?,?)",
                         (code_id, pid, cas))
        _row(conn, site_id, "1.6", {
            "code_id": code_id, "process_id": pid, "equipment_ids": [eid],
            "cas_list": cas_list, "material": material,
            "material_category": category, "spec": spec, "scope": "單台設備；不可作正式設計依據",
        })


def _fill_operating_tables(conn: sqlite3.Connection, site_id: str) -> None:
    contents = {
        "V-301": [("75-28-5", "SDS-IB-001"), ("624-64-6", "SDS-BUT-001")],
        "P-301": [("75-28-5", "SDS-IB-001")],
        "R-301": [("75-28-5", "SDS-IB-001"), ("624-64-6", "SDS-BUT-001"),
                  ("7664-39-3", "SDS-HF-001")],
        "PSV-301": [("7664-39-3", "SDS-HF-001")],
        "C-301": [("540-84-1", "SDS-ISO-001")],
        "T-301": [("540-84-1", "SDS-ISO-001")],
    }
    for eid, chemicals in contents.items():
        for cas, sds in chemicals:
            conn.execute("""INSERT OR IGNORE INTO equipment_content(equipment_id,cas,no_process_chemical,sds_id)
                VALUES (?,?,0,?)""", (eid, cas, sds))
    for eq in conn.execute("SELECT equipment_id FROM equipment WHERE site_id=?", (site_id,)):
        eid = eq["equipment_id"]
        has_content = bool(conn.execute(
            "SELECT 1 FROM equipment_content WHERE equipment_id=? AND no_process_chemical=0", (eid,)
        ).fetchone())
        if not has_content:
            conn.execute("""INSERT OR IGNORE INTO equipment_content(equipment_id,cas,no_process_chemical,sds_id)
                VALUES (?,'',1,'')""", (eid,))
        selected = ["壓力", "溫度"] if eid in ("T-101", "R-301") else []
        conn.execute("""INSERT OR REPLACE INTO equipment_operating_review
            (equipment_id,selected_parameters,no_parameter_reason,batch_quantity,batch_unit,
             batch_na_reason,no_content_reason) VALUES (?,?,?,?,?,?,?)""",
            (eid, json.dumps(selected, ensure_ascii=False),
             "" if selected else "本教學設備的數值界限未由核准設計文件提供，待逐台確認。",
             None, "", "連續操作，不以單批量表示。",
             "控制、緊急停車或處理設備無直接操作化學品。" if not has_content else ""))
    # The values below are deliberately fictional and identified as such in every row.
    for eid, pressure, temperature in (
        ("T-101", (12, 1, 10, 2), (45, 0, 40, 5)),
        ("R-301", (20, 2, 18, 3), (80, 0, 70, 5)),
    ):
        for parameter, unit, values in (("壓力", "bar(g)", pressure), ("溫度", "℃", temperature)):
            conn.execute("DELETE FROM equipment_limit WHERE equipment_id=? AND parameter=?", (eid, parameter))
            cursor = conn.execute("""INSERT INTO equipment_limit
                (equipment_id,parameter,unit,design_high,design_low,safety_high,safety_low,note)
                VALUES (?,?,?,?,?,?,?,?)""", (eid, parameter, unit, *map(str, values), SAMPLE_NOTE))
            _row(conn, site_id, "4.4", {
                "limit_id": str(cursor.lastrowid), "equipment_id": eid,
                "parameter": parameter, "unit": unit,
                "safety_high": str(values[2]), "safety_low": str(values[3]),
                "high_consequence": "超限可能導致失去密閉或設備損傷；情境由 PHA 核對",
                "high_correct": "依核准程序隔離進料、確認連鎖並通報值班主管",
                "low_consequence": "低於界限可能影響控制穩定與分離效果",
                "low_correct": "依核准程序調整進料與控制，必要時安全停車",
                "high_na_reason": "", "low_na_reason": "",
            })


def _fill_management_tables(conn: sqlite3.Connection, site_id: str) -> None:
    fil.set_flag(conn, site_id, "sop_no_temp", "0")
    fil.set_flag(conn, site_id, "pha_consider",
                 "HF 烷基化反應放熱、輕烴火災爆炸、HF 洩漏及尾氣處理失效；以 HAZOP 檢討偏離。")
    fil.set_flag(conn, site_id, "consider:hazop",
                 "反應器移熱、進料比、壓力控制及 HF 酸相密閉循環。")
    fil.set_flag(conn, site_id, "qty:hazop", "8")
    doc = DOCS / "petro_pha_demo.txt"
    cur = conn.execute("""INSERT INTO unstructured_attachment(site_id,process_id,kind,original_name,attachment_path,note)
        VALUES (?,?,'pha',?,?,?)""",
        (site_id, "P-REACT", "PHA-ALK-001-教學紀錄.txt", str(doc), "HAZOP 教學假設，不可作正式評估紀錄"))
    conn.execute("""INSERT INTO pha_record(record_id,site_id,method,question_count,record_date,attachment_id)
        VALUES ('PHA-ALK-001',?,'hazop',8,'2026-01-20',?)""", (site_id, cur.lastrowid))
    _row(conn, site_id, "2.4", {
        "assessment_id": "PHA-ALK-001", "process_id": "P-REACT",
        "equipment_id": "R-301,ESD-301", "equipment_ids": ["R-301", "ESD-301"],
        "scenario": "反應器移熱不足，溫壓上升並可能觸發洩漏",
        "safeguard": "高高溫／壓警報、進料隔離、釋壓至安全處理路徑",
        "improvement": "確認獨立保護層測試及 HF 洩漏演練紀錄",
        "due": "2026-10-31", "track": "教學追蹤中",
    })
    _row(conn, site_id, "4.2", {
        "equipment_id": "R-301", "equipment_name": "HF 烷基化反應器",
        "equipment_type": "壓力容器與儲槽", "process_id": "P-REACT",
        "item": "進料泵切換與低負荷暫態操作；須依核准程序執行",
    })
    _row(conn, site_id, "4.3", {
        "equipment_id": "ESD-301", "equipment_name": "反應區緊急停車系統",
        "equipment_type": "緊急停車系統", "process_id": "P-REACT",
        "item": "反應器高高壓、HF 偵測異常或手動急停",
        "emergency": "停止輕烴進料、隔離酸相並導入核准安全處理系統",
    })
    # Add a procedure and training row for the newly introduced reactor.
    svc.save_sop(conn, {
        "sop_id": "SOP-ALK-301", "process_id": "P-REACT", "title": "HF 烷基化反應器操作",
        "procedure_no": "DEMO-SOP-ALK-301", "updated_on": "2026-01-15",
        "body": "確認密閉、冷卻與連鎖；依核准程序啟動、巡檢、隔離及緊急停車。" + SAMPLE_NOTE,
        "op_kind": "equipment", "equipment_id": "R-301", "equipment_ids": ["R-301"],
    })
    svc.save_training_course(conn, {
        "course_id": "COURSE-ALK-301", "process_id": "P-REACT",
        "name": "HF 烷基化操作與異常應變", "hours": 8,
        "audience": "反應區操作與維護人員", "kind": "initial",
        "op_kind": "process", "sop_ids": ["SOP-ALK-301"],
        "refresh_hours": 4, "refresh_every": "每年",
    })
    for course in conn.execute("SELECT course_id FROM training_course"):
        conn.execute("""UPDATE training_course SET refresh_hours=COALESCE(refresh_hours,2),
            refresh_every=COALESCE(NULLIF(refresh_every,''),'每年') WHERE course_id=?""",
            (course["course_id"],))
    for sop in conn.execute("SELECT sop_id,process_id FROM sop"):
        conn.execute("""UPDATE sop SET procedure_no=COALESCE(NULLIF(procedure_no,''),?),
            updated_on=COALESCE(NULLIF(updated_on,''),'2026-01-15') WHERE sop_id=?""",
            (f"DEMO-{sop['sop_id']}", sop["sop_id"]))
        linked = conn.execute("SELECT 1 FROM training_course_sop WHERE sop_id=?", (sop["sop_id"],)).fetchone()
        if not linked:
            course = conn.execute("SELECT course_id FROM training_course WHERE process_id=? LIMIT 1",
                                  (sop["process_id"],)).fetchone()
            if course:
                conn.execute("INSERT OR IGNORE INTO training_course_sop(course_id,sop_id) VALUES (?,?)",
                             (course["course_id"], sop["sop_id"]))
            else:
                _row(conn, site_id, "5.1e", {"sop_id": sop["sop_id"],
                                            "reason": "另有設備專項訓練待文件化核對"})
    conn.execute("UPDATE training_course SET no_sop_reason=? WHERE course_id='COURSE-JOB-01'",
                 ("跨程序在職複訓，涵蓋共通安全要求",))
    for eq in conn.execute("SELECT equipment_id,name,process_id FROM equipment WHERE site_id=?", (site_id,)):
        eid = eq["equipment_id"]
        if eid not in {r.get("equipment_id") for r in fil.list_rows(conn, site_id, "7.0")}:
            _row(conn, site_id, "7.0", {"equipment_id": eid, "applicable": "1",
                                          "reason": "教學案例逐台檢查"})
            _row(conn, site_id, "7.1", {
                "equipment_id": eid, "equipment_name": eq["name"],
                "process_id": eq["process_id"], "when": "2026-01-20",
                "rec": "無", "due": "", "track": "完成", "change_id": "",
            })
        critical = eid in ("T-101", "R-301")
        conn.execute("""INSERT INTO mi_screen(equipment_id,is_critical,basis,mi_type,mi_type_confirmed)
            VALUES (?,?,?,?,1) ON CONFLICT(equipment_id) DO UPDATE SET
            is_critical=excluded.is_critical,basis=excluded.basis,
            mi_type=excluded.mi_type,mi_type_confirmed=1""",
            (eid, int(critical), "失去密閉可能造成 HF 暴露" if critical else "經教學篩選為非本例關鍵設備",
             "壓力容器與儲槽" if critical else ""))
    conn.execute("""UPDATE mi_inspection_detail SET damage_mechanism='密封與壁厚劣化',
        inspection_item='',confirmed=1 WHERE equipment_id='T-101'""")
    conn.execute("""INSERT INTO mi_inspection_detail
        (equipment_id,damage_mechanism,inspection_item,inspect_method,inspect_frequency,
         procedure_ref,pid_drawing_no,confirmed)
        VALUES ('R-301','材質相容性與局部腐蝕','','壁厚檢測及洩漏確認','每年',
                'DEMO-MI-R301','PID-ALK-301',1)""")
    for eid in ("T-101", "R-301"):
        conn.execute("""INSERT OR REPLACE INTO mi_failure
            (equipment_id,period_start,period_end,run_hours,failure_count,note,confirmed)
            VALUES (?,'2025-01-01','2025-12-31',8000,0,?,1)""",
            (eid, "教學模擬運轉時數與事件數；須以實際維修資料替換"))
    svc.save_hotwork_zone(conn, {"area_code": "AREA-R",
        "protection_reason": "維修動火前停止進料、隔離 HF 與輕烴、氣體檢測並依許可程序監護。"})
    _row(conn, site_id, "12.1s", {
        "situation": "反應區輕烴火災與 HF 洩漏",
        "description": "R-301 失去密閉，兼具易燃蒸氣與 HF 暴露風險",
        "process_ids": ["P-REACT"], "equipment_ids": ["R-301", "ESD-301"],
        "chemical_refs": ["P-REACT|SDS-HF-001|7664-39-3",
                          "P-REACT|SDS-IB-001|75-28-5"],
        "area_codes": ["AREA-R"], "muster": "AREA-M",
        "scope_note": "依風向選擇集合點",
        "drill_plan_scope": "反應區隔離、通報、疏散及外部支援",
        "drill_status": "已執行", "drill_date": "2026-06-10",
        "drill_record_path": str(DOCS / "petro_drill_demo.txt"),
        "drill_record_name": "petro_drill_demo.txt",
    })
    for scenario in fil.list_rows(conn, site_id, "12.1s"):
        if scenario.get("drill_status"):
            continue
        scenario.update({"drill_plan_scope": "隔離、通報、風向疏散及集合點確認",
                         "drill_status": "已執行", "drill_date": "2026-06-10",
                         "drill_record_path": str(DOCS / "petro_drill_demo.txt"),
                         "drill_record_name": "petro_drill_demo.txt"})
        fil.update_payload(conn, int(scenario["row_id"]), scenario)
    _row(conn, site_id, "12.2", {
        "name": "可燃氣體偵測器", "area_code": "AREA-R",
        "qty": "4", "unit": "具", "total": "4", "freq": "每月",
        "cas": "75-28-5",
    })
