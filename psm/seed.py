"""DEMO-SITE 寫死示範廠。打開即可點，不必從空白廠開始。"""

from __future__ import annotations

import sqlite3

from psm.enums import MATRIX_VERSION, PROCESS_OVERVIEWS, SITE_ID, UNIT_TITLES
from psm import filing as fil
from psm import services as svc


def apply_demo_pec_maps(conn: sqlite3.Connection) -> str:
    """只寫實際關係；未列到的設備改聲明無製程化學品。禁止設備×化學品全配對。"""
    planned = (
        {
            "process_id": "P-TANK",
            "equipment_id": "T-101",
            "cas": "108-88-3",
            "may_remain": False,
        },
        {
            "process_id": "P-TANK",
            "equipment_id": "P-101",
            "cas": "108-88-3",
            "may_remain": False,
        },
        {
            "process_id": "P-TANK",
            "equipment_id": "PSV-101",
            "cas": "108-88-3",
            "may_remain": False,
        },
        {
            "process_id": "P-TANK",
            "equipment_id": "ESD-101",
            "no_process_chemical": True,
        },
        {
            "process_id": "P-LOAD",
            "equipment_id": "LA-101",
            "cas": "108-88-3",
            "may_remain": False,
        },
        {
            "process_id": "P-SCRUB",
            "equipment_id": "S-201",
            "cas": "7722-84-1",
            "may_remain": False,
            "material": "FRP",
        },
        {
            "process_id": "P-ACID",
            "equipment_id": "PL-201",
            "cas": "7647-01-0",
            "may_remain": True,
            "material": "碳鋼",
        },
    )
    n = 0
    for row in planned:
        exists = conn.execute(
            "SELECT 1 FROM equipment WHERE equipment_id=? AND process_id=?",
            (row["equipment_id"], row["process_id"]),
        ).fetchone()
        if not exists:
            continue
        svc.save_pec_map(conn, row)
        n += 1
    leftovers = conn.execute(
        """SELECT e.process_id, e.equipment_id FROM equipment e
           WHERE NOT EXISTS (
             SELECT 1 FROM pec_map m
             WHERE m.process_id=e.process_id AND m.equipment_id=e.equipment_id
           )"""
    ).fetchall()
    for row in leftovers:
        svc.save_pec_map(
            conn,
            {
                "process_id": row["process_id"],
                "equipment_id": row["equipment_id"],
                "no_process_chemical": True,
            },
        )
        n += 1
    return f"已登錄 {n} 列實際對應（未配對者聲明無製程化學品）"


def seed_demo(conn: sqlite3.Connection) -> None:
    svc.save_site(
        conn,
        {
            "site_id": SITE_ID,
            "company_name": "示範事業股份有限公司",
            "site_name": "示範甲類工作場所（溶劑儲存及裝卸）",
            "scope": "甲苯儲槽區、裝卸場及廢氣洗滌",
            "applicant_name": "王大明",
            "assessment_base_date": "2026-08-21",
            "worker_count": 48,
            "declare_no_contractor": False,
            "declare_no_hotwork": False,
            "declare_no_equipment_types": "控制系統,其他",
            "declare_no_incident_5y": False,
        },
    )
    svc.save_department(
        conn, {"dept_id": "D-OPS", "site_id": SITE_ID, "name": "操作課", "parent_dept_id": None}
    )
    svc.save_department(
        conn, {"dept_id": "D-MAINT", "site_id": SITE_ID, "name": "保養課", "parent_dept_id": None}
    )
    for item_no, title, see_also in (
        (1, "事業單位組織系統圖", None),
        (3, "勞工作業環境監測計畫", None),
        (5, "勞工健康服務與管理措施", None),
        (6, "職業安全衛生組織、人員設置及運作", None),
        (7, "職業安全衛生管理規章", None),
        (8, "自動檢查計畫", None),
        (9, "承攬管理計畫", None),
        (10, "職業安全衛生教育訓練計畫", "附表五得參閱本項"),
        (11, "事故調查處理制度", "附表十一得參閱本項"),
    ):
        svc.save_site_basic_doc(
            conn,
            {
                "site_id": SITE_ID,
                "item_no": item_no,
                "title": title,
                "doc_date": "2026-01-15",
                "file_path": f"placeholder://ch2-item-{item_no}",
                "not_applicable": False,
                "see_also": see_also,
            },
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
            "has_overpressure": True,
            "is_special": False,
            "is_loading": False,
            "is_downstream": False,
            "overview": PROCESS_OVERVIEWS["P-TANK"],
        },
    )
    svc.save_process(
        conn,
        {
            "process_id": "P-LOAD",
            "site_id": SITE_ID,
            "name": "裝卸",
            "operating_dept_id": "D-OPS",
            "mode": "batch",
            "has_chemical_reaction": False,
            "has_overpressure": False,
            "is_special": False,
            "is_loading": True,
            "is_downstream": False,
            "overview": PROCESS_OVERVIEWS["P-LOAD"],
        },
    )
    svc.save_process(
        conn,
        {
            "process_id": "P-SCRUB",
            "site_id": SITE_ID,
            "name": "後段處理單元",
            "operating_dept_id": "D-OPS",
            "mode": "continuous",
            "has_chemical_reaction": True,
            "has_overpressure": False,
            "is_special": False,
            "is_loading": False,
            "is_downstream": True,
            "overview": PROCESS_OVERVIEWS["P-SCRUB"],
        },
    )
    svc.save_process(
        conn,
        {
            "process_id": "P-ACID",
            "site_id": SITE_ID,
            "name": "酸液輸送",
            "operating_dept_id": "D-OPS",
            "mode": "continuous",
            "has_chemical_reaction": False,
            "has_overpressure": False,
            "is_special": False,
            "is_loading": False,
            "is_downstream": False,
            "overview": PROCESS_OVERVIEWS["P-ACID"],
        },
    )
    svc.save_area(
        conn,
        {
            "area_code": "AREA-A",
            "site_id": SITE_ID,
            "name": "儲槽區",
            "drawing_no": "PLOT-001",
            "revision": "A",
            "issue_date": "2025-12-01",
            "process_id": "P-TANK",
            "attachment_path": "placeholder://PLOT-001-A",
            "is_assembly_point": False,
            "is_control_room": True,
            "is_fire_system": True,
            "worker_count": 6,
            "contractor_count": 4,
            "visitor_count": 0,
        },
    )
    svc.save_area(
        conn,
        {
            "area_code": "AREA-B",
            "site_id": SITE_ID,
            "name": "裝卸場",
            "drawing_no": "PLOT-001",
            "revision": "A",
            "issue_date": "2025-12-01",
            "process_id": "P-LOAD",
            "attachment_path": "placeholder://PLOT-001-A",
            "is_assembly_point": False,
            "is_control_room": False,
            "is_fire_system": False,
            "worker_count": 3,
            "contractor_count": 2,
            "visitor_count": 2,
        },
    )
    svc.save_area(
        conn,
        {
            "area_code": "AREA-M",
            "site_id": SITE_ID,
            "name": "廠界北側集合點",
            "drawing_no": "PLOT-001",
            "revision": "A",
            "issue_date": "2025-12-01",
            "process_id": None,
            "attachment_path": "placeholder://PLOT-001-A",
            "is_assembly_point": True,
            "is_control_room": False,
            "is_fire_system": False,
            "worker_count": 0,
            "contractor_count": 0,
            "visitor_count": 0,
        },
    )
    svc.save_area(
        conn,
        {
            "area_code": "AREA-S",
            "site_id": SITE_ID,
            "name": "廠界南側集合點",
            "drawing_no": "PLOT-001",
            "revision": "A",
            "issue_date": "2025-12-01",
            "process_id": None,
            "attachment_path": "placeholder://PLOT-001-A",
            "is_assembly_point": True,
            "is_control_room": False,
            "is_fire_system": False,
            "worker_count": 0,
            "contractor_count": 0,
            "visitor_count": 0,
        },
    )
    for row in (
        {
            "equipment_id": "T-101",
            "name": "儲槽",
            "equipment_type": "壓力容器與儲槽",
            "power_kind": None,
            "phase_class": "液體",
            "process_id": "P-TANK",
            "area_code": "AREA-A",
            "legal_cert_type": "危險性設備檢查合格證",
            "is_safety_critical": False,
            "is_regulated_machinery": True,
            "is_high_pressure_gas": False,
        },
        {
            "equipment_id": "P-101",
            "name": "泵浦",
            "equipment_type": "動力來源",
            "power_kind": "泵浦",
            "phase_class": "液體",
            "process_id": "P-TANK",
            "area_code": "AREA-A",
            "legal_cert_type": None,
            "is_safety_critical": False,
        },
        {
            "equipment_id": "PSV-101",
            "name": "安全閥",
            "equipment_type": "釋放及排放系統",
            "power_kind": None,
            "phase_class": "液體",
            "process_id": "P-TANK",
            "area_code": "AREA-A",
            "legal_cert_type": None,
            "is_safety_critical": False,
        },
        {
            "equipment_id": "ESD-101",
            "name": "緊急停車系統",
            "equipment_type": "緊急停車系統",
            "power_kind": None,
            "phase_class": "液體",
            "process_id": "P-TANK",
            "area_code": "AREA-A",
            "legal_cert_type": None,
            "is_safety_critical": False,
        },
        {
            "equipment_id": "LA-101",
            "name": "鶴管",
            "equipment_type": "裝卸及輸送",
            "power_kind": None,
            "phase_class": "液體",
            "process_id": "P-LOAD",
            "area_code": "AREA-B",
            "legal_cert_type": None,
            "is_safety_critical": False,
        },
        {
            "equipment_id": "S-201",
            "name": "洗滌塔",
            "equipment_type": "釋放及排放系統",
            "power_kind": None,
            "phase_class": "後段處理",
            "process_id": "P-SCRUB",
            "area_code": "AREA-A",
            "legal_cert_type": None,
            "is_safety_critical": False,
        },
        {
            "equipment_id": "PL-201",
            "name": "酸液輸送管線",
            "equipment_type": "管線系統",
            "power_kind": None,
            "phase_class": "液體",
            "process_id": "P-ACID",
            "area_code": "AREA-A",
            "legal_cert_type": None,
            "is_safety_critical": False,
        },
    ):
        row.update(
            {
                "site_id": SITE_ID,
                "maint_dept_id": "D-MAINT",
                "alias": None,
                "is_high_pressure_gas": row.get("is_high_pressure_gas", False),
            }
        )
        svc.save_equipment(conn, row)

    svc.save_sds(
        conn,
        {
            "sds_id": "SDS-TOL-001",
            "site_id": SITE_ID,
            "substance_or_mixture_name": "工業級甲苯",
            "version": "1",
            "revise_date": "2026-01-01",
            "file_path": "placeholder://SDS-toluene.pdf",
            "component_cas_list": "108-88-3",
        },
    )
    svc.save_sds(
        conn,
        {
            "sds_id": "SDS-HCL-001",
            "site_id": SITE_ID,
            "substance_or_mixture_name": "酸洗液",
            "version": "1",
            "revise_date": "2026-01-01",
            "file_path": "placeholder://SDS-HCL-001.pdf",
            "component_cas_list": "7647-01-0",
        },
    )
    svc.save_sds(
        conn,
        {
            "sds_id": "SDS-H2O2-001",
            "site_id": SITE_ID,
            "substance_or_mixture_name": "過氧化氫水溶液",
            "version": "1",
            "revise_date": "2026-01-01",
            "file_path": "placeholder://SDS-H2O2-001.pdf",
            "component_cas_list": "7722-84-1",
        },
    )
    svc.save_chemical(
        conn,
        {
            "cas": "108-88-3",
            "process_id": "P-TANK",
            "name": "甲苯",
            "role": "原物料",
            "un_number": "UN 1294",
            "transport_hazard_class": "3",
            "concentration_range": "≥99%",
            "sds_id": "SDS-TOL-001",
            "h_codes": "H225",
            "purity_or_mixture": "純物質",
            "attributed_qty": 50000,
            "phase_state": "液態",
        },
    )
    svc.save_chemical(
        conn,
        {
            "cas": "108-88-3",
            "process_id": "P-LOAD",
            "name": "甲苯",
            "role": "原物料",
            "un_number": "UN 1294",
            "transport_hazard_class": "3",
            "concentration_range": "≥99%",
            "sds_id": "SDS-TOL-001",
            "h_codes": "H225",
            "purity_or_mixture": "純物質",
            "attributed_qty": 8000,
            "phase_state": "液態",
        },
    )
    svc.save_chemical(
        conn,
        {
            "cas": "7647-01-0",
            "process_id": "P-ACID",
            "name": "氯化氫水溶液",
            "role": "原物料",
            "concentration_range": "30%–35%",
            "sds_id": "SDS-HCL-001",
            "h_codes": "H314,H335",
            "purity_or_mixture": "混合物",
            "mixture_name": "酸洗液",
            "pct_low": 30,
            "pct_high": 35,
            "pct_basis": "重量比",
            "mixture_qty": 2000,
            "attributed_qty": 700,
            "phase_state": "液態",
        },
    )
    svc.save_chemical(
        conn,
        {
            "cas": "7722-84-1",
            "process_id": "P-SCRUB",
            "name": "過氧化氫",
            "role": "原物料",
            "concentration_range": "35%",
            "sds_id": "SDS-H2O2-001",
            "h_codes": "H272,H314",
            "purity_or_mixture": "混合物",
            "mixture_name": "過氧化氫水溶液",
            "pct_low": 35,
            "pct_high": 35,
            "pct_basis": "重量比",
            "mixture_qty": 20000,
            "attributed_qty": 7000,
            "phase_state": "液態",
        },
    )
    apply_demo_pec_maps(conn)
    svc.save_pid_drawing(
        conn,
        {
            "drawing_no": "PID-TANK-001",
            "revision": "B",
            "process_id": "P-TANK",
            "name": "儲槽區管線儀表圖",
            "issue_date": "2026-02-01",
            "is_as_built": True,
            "attachment_path": "placeholder://PID-TANK-001-B",
            "diagram_kind": "P&ID",
        },
        covering_ids=["T-101", "P-101", "PSV-101", "ESD-101"],
    )
    svc.save_pid_drawing(
        conn,
        {
            "drawing_no": "PFD-TANK-001",
            "revision": "A",
            "process_id": "P-TANK",
            "name": "儲槽區製程流程圖",
            "issue_date": "2026-02-01",
            "is_as_built": True,
            "attachment_path": "placeholder://PFD-TANK-001-A",
            "diagram_kind": "PFD",
        },
        covering_ids=["T-101", "P-101", "PSV-101", "ESD-101"],
    )
    svc.save_esd_scenario(
        conn,
        {
            "scenario_id": "ESD-SC-TANK-01",
            "process_id": "P-TANK",
            "esd_equipment_id": "ESD-101",
            "name": "儲槽高液位緊急停車",
            "trigger_conditions": "T-101 高高液位或現場緊急按鈕",
            "maint_dept_id": "D-MAINT",
        },
        action_ids=["P-101"],
    )

    conn.execute(
        """INSERT INTO inventory(cas, process_id, max_kg, area_code, calc_note)
           VALUES ('108-88-3','P-TANK',50000,'AREA-A','純物質最大存量，人員確認；不另填混合物總量')
           ON CONFLICT(cas, process_id) DO NOTHING"""
    )
    conn.execute(
        """INSERT INTO inventory(cas, process_id, max_kg, area_code, calc_note)
           VALUES ('108-88-3','P-LOAD',8000,'AREA-B','槽車一次卸收量')
           ON CONFLICT(cas, process_id) DO NOTHING"""
    )
    conn.execute(
        """INSERT INTO inventory(cas, process_id, max_kg, area_code, calc_note)
           VALUES ('7647-01-0','P-ACID',700,'AREA-A','估算：混合物 2000 kg × 比例上限 35%；混合物總量不重複加總')
           ON CONFLICT(cas, process_id) DO NOTHING"""
    )
    conn.execute(
        """INSERT INTO inventory(cas, process_id, max_kg, area_code, calc_note)
           VALUES ('7722-84-1','P-SCRUB',7000,'AREA-A','成分歸屬量＝混合物 20000 kg × 35 wt%；混合物總量不重複加總')
           ON CONFLICT(cas, process_id) DO NOTHING"""
    )
    for r in conn.execute("SELECT cas, process_id, area_code FROM inventory"):
        for chem in conn.execute(
            "SELECT sds_id FROM chemical WHERE cas=? AND process_id=?",
            (r["cas"], r["process_id"]),
        ):
            conn.execute(
                """INSERT OR IGNORE INTO area_chemical(area_code, process_id, sds_id, cas)
                   VALUES (?,?,?,?)""",
                (r["area_code"], r["process_id"], chem["sds_id"], r["cas"]),
            )
        conn.execute(
            "INSERT OR IGNORE INTO area_process(area_code, process_id) VALUES (?,?)",
            (r["area_code"], r["process_id"]),
        )
    conn.execute(
        """INSERT INTO equipment_limit(equipment_id, parameter, unit, design_high,
            design_low, safety_high, safety_low, note)
           VALUES ('T-101','壓力','kgf/cm²','3.5','-0.05','3.0','-0.02','表壓。連續操作，單次操作量不適用。設計範圍，非品質界限'),
                  ('T-101','溫度','℃','60','-10','55','0',NULL),
                  ('T-101','液位','%','100','0','90','10',NULL)"""
    )
    for mat in (
        {"equipment_id": "T-101", "material": "CS A283", "spec": "API 650", "corrosion_allowance": "3 mm"},
        {"equipment_id": "P-101", "material": "CS", "spec": "API 610"},
        {"equipment_id": "PSV-101", "material": "SS304", "spec": "API 526"},
        {"equipment_id": "LA-101", "material": "SS304"},
        {"equipment_id": "S-201", "material": "FRP"},
        {"equipment_id": "PL-201", "material": "碳鋼"},
    ):
        svc.save_equipment_material(conn, mat)
    conn.execute(
        """INSERT INTO equipment_content(equipment_id, cas, no_process_chemical, sds_id)
           VALUES ('T-101','108-88-3',0,'SDS-TOL-001'),
                  ('P-101','108-88-3',0,'SDS-TOL-001'),
                  ('PSV-101','108-88-3',0,'SDS-TOL-001'),
                  ('LA-101','108-88-3',0,'SDS-TOL-001'),
                  ('S-201','7722-84-1',0,'SDS-H2O2-001'),
                  ('PL-201','7647-01-0',0,'SDS-HCL-001'),
                  ('ESD-101','',1,'')
           ON CONFLICT(equipment_id, cas, sds_id) DO UPDATE SET
             sds_id=excluded.sds_id,
             no_process_chemical=excluded.no_process_chemical"""
    )
    conn.execute(
        """INSERT INTO relief_device(equipment_id, device_type, set_pressure, design_capacity,
            pid_drawing_no, pid_revision, released_cas, released_process_id)
           VALUES ('PSV-101','彈簧式安全閥','1.5 kgf/cm²（表壓）','1200 m³/hr',
                   'PID-TANK-001','B','108-88-3','P-TANK')
           ON CONFLICT(equipment_id) DO NOTHING"""
    )
    conn.execute(
        """INSERT INTO interlock(interlock_id, process_id, equipment_id, name, function_desc, scenario_id, setpoint)
           VALUES ('I-HH-T101','P-TANK','ESD-101','T-101 高高液位連鎖','達 HH 時啟動緊急停車方案','ESD-SC-TANK-01','90%')
           ON CONFLICT(interlock_id) DO NOTHING"""
    )
    conn.execute(
        """INSERT INTO chem_hazard_check(cas, process_id, sds_id, state, fire, explosion, static,
            reactivity, toxicity, pel_twa, flash_point, boiling_point, note)
           VALUES ('108-88-3','P-TANK','SDS-TOL-001','液體',1,1,1,'安定','中樞神經抑制','50 ppm','4℃','110.6℃','引用 SDS')
           ON CONFLICT(process_id, sds_id, cas) DO NOTHING"""
    )
    conn.execute(
        """INSERT INTO chem_compatibility(cas_a, process_id_a, equipment_id, compatible, hazard_note)
           VALUES ('108-88-3','P-TANK','T-101',1,'與碳鋼相容')"""
    )
    conn.execute(
        """INSERT INTO chem_handling(cas, process_id, storage_notes, process_conditions, emergency_notes)
           VALUES ('108-88-3','P-TANK','氮封儲存、接地','常溫常壓儲存','外洩時隔絕火源、收集至污油槽')
           ON CONFLICT(cas, process_id) DO NOTHING"""
    )
    conn.execute(
        """INSERT INTO explosion_area(area_code, cas, process_id, sds_id, zone_class)
           VALUES ('AREA-A','108-88-3','P-TANK','SDS-TOL-001','Zone 1')
           ON CONFLICT(area_code, process_id, sds_id, cas) DO NOTHING"""
    )
    svc.save_hotwork_zone(
        conn,
        {
            "area_code": "AREA-A",
            "protection_reason": "甲苯儲槽區屬防爆 Zone 1，管線維修動火須許可、隔絕蒸氣並測爆。",
        },
    )
    svc.save_hotwork_zone(
        conn,
        {
            "area_code": "AREA-B",
            "protection_reason": "裝卸場卸收期間可能有蒸氣，動火僅限卸畢並吹驅後。",
        },
    )
    conn.execute(
        """INSERT INTO hotwork_permit(permit_id, equipment_id, area_code, permit_date, measures)
           VALUES ('HW-2026-001','T-101','AREA-A','2026-07-15','測爆合格、維持氮封、備滅火器')
           ON CONFLICT(permit_id) DO NOTHING"""
    )
    svc.save_incident(
        conn,
        {
            "incident_id": "INC-2025-001",
            "process_id": "P-TANK",
            "equipment_id": "P-101",
            "incident_date": "2025-08-12",
            "summary": "吊裝 P-101 時吊索偏擺，泵體差點撞擊甲苯管線。",
            "is_near_miss": True,
            "casualty": "無傷亡",
            "lost_days": 0,
            "cause": "直接：吊點未對中。間接：現場監工未先隔離管線。基本：吊裝許可未含管線隔離確認。",
            "corrective": "修訂吊裝作業許可，增加管線隔離確認。",
            "characteristics": "其他",
        },
    )
    svc.save_contractor_incident(
        conn,
        {
            "incident_id": "CTR-2025-001",
            "site_id": SITE_ID,
            "contractor_name": "大興機械工程有限公司",
            "contract_period": "2025-03-01～2025-12-31",
            "incident_type": "虛驚",
            "linked_incident_id": "INC-2025-001",
        },
    )
    svc.save_process_route(
        conn,
        {
            "route_id": "ROUTE-TOL",
            "site_id": SITE_ID,
            "note": "甲苯卸收、儲存及廢氣洗滌",
            "blocks": [
                {
                    "seq_no": 1,
                    "process_id": "P-LOAD",
                    "note": "槽車卸收",
                    "equipment_ids": ["LA-101"],
                    "cas_list": [("P-LOAD", "108-88-3")],
                },
                {
                    "seq_no": 2,
                    "process_id": "P-TANK",
                    "note": "儲存與送出",
                    "equipment_ids": ["T-101", "P-101"],
                    "cas_list": [("P-TANK", "108-88-3")],
                },
                {
                    "seq_no": 3,
                    "process_id": "P-SCRUB",
                    "note": "廢氣洗滌",
                    "equipment_ids": ["S-201"],
                    "cas_list": [("P-SCRUB", "7722-84-1")],
                },
            ],
        },
    )
    conn.execute(
        """INSERT INTO ventilation(area_code, vent_type, standard)
           VALUES ('AREA-A','自然通風','CNS 3376-10')"""
    )
    conn.execute(
        """INSERT INTO design_code(process_id, equipment_id, item, code)
           VALUES ('P-TANK','T-101','儲槽','API 650')"""
    )
    conn.execute(
        """INSERT INTO reaction_info(process_id, summary, formula, heat, kinds)
           VALUES ('P-SCRUB','過氧化氫於後段處理分解放熱','2 H2O2 → 2 H2O + O2','放熱，約 −98 kJ/mol（分解熱）','其他')
           ON CONFLICT(process_id) DO UPDATE SET
             summary=excluded.summary, formula=excluded.formula,
             heat=excluded.heat, kinds=excluded.kinds"""
    )

    for mix in (
        {
            "mix_name": "酸洗液",
            "sds_id": "SDS-HCL-001",
            "process_id": "P-ACID",
            "cas": "7647-01-0",
            "pct_lo": "30",
            "pct_hi": "35",
            "basis": "重量比",
            "total_kg": "2000",
            "is_aqueous": "1",
            "phase_state": "液態",
            "formula": "操作量×重量百分比＝純物質公斤；水溶液不列入",
        },
        {
            "mix_name": "過氧化氫水溶液",
            "sds_id": "SDS-H2O2-001",
            "process_id": "P-SCRUB",
            "cas": "7722-84-1",
            "pct_lo": "35",
            "pct_hi": "35",
            "basis": "重量比",
            "total_kg": "20000",
            "is_aqueous": "0",
            "phase_state": "液態",
            "formula": "操作量×重量百分比＝純物質公斤",
        },
    ):
        fil.add_row(conn, SITE_ID, "mix", fil.attach_annex_check(mix))
    fil.add_row(
        conn,
        SITE_ID,
        "1.4",
        {
            "process_id": "P-SCRUB",
            "kinds": "其他",
            "formula": "2 H2O2 → 2 H2O + O2",
            "heat": "放熱，約 −98 kJ/mol（分解熱）",
        },
    )

    svc.save_sop(conn, {"sop_id": "SOP-TANK-01", "process_id": "P-TANK", "title": "儲槽製程操作", "procedure_no": "SOP-TANK-01", "body": "", "op_kind": "process"})
    svc.save_sop(conn, {"sop_id": "SOP-LOAD-01", "process_id": "P-LOAD", "title": "裝卸製程操作", "procedure_no": "SOP-LOAD-01", "body": "", "op_kind": "process"})
    svc.save_sop(conn, {"sop_id": "SOP-SCRUB-01", "process_id": "P-SCRUB", "title": "後段處理製程操作", "procedure_no": "SOP-SCRUB-01", "body": "", "op_kind": "process"})
    svc.save_sop(conn, {"sop_id": "SOP-ACID-01", "process_id": "P-ACID", "title": "酸液輸送製程操作", "procedure_no": "SOP-ACID-01", "body": "", "op_kind": "process"})
    for eid, title in (
        ("T-101", "T-101 操作"),
        ("P-101", "P-101 操作"),
        ("PSV-101", "PSV-101 操作"),
        ("ESD-101", "ESD-101 操作"),
        ("LA-101", "LA-101 操作"),
        ("S-201", "S-201 操作"),
        ("PL-201", "PL-201 操作"),
    ):
        svc.save_sop(
            conn,
            {
                "sop_id": f"SOP-EQ-{eid}",
                "op_kind": "equipment",
                "equipment_id": eid,
                "title": title,
                "procedure_no": f"SOP-EQ-{eid}",
                "body": "",
            },
        )

    conn.execute(
        """UPDATE pid_drawing SET eval_record_no='PHA-2026-001'
           WHERE drawing_no='PID-TANK-001' AND revision='B'"""
    )
    for screen in (
        {
            "equipment_id": "T-101",
            "is_critical": True,
            "basis": "儲存易燃液體且製程勾選需超壓保護",
            "damage_mechanism": "均勻腐蝕",
            "inspect_method": "目視及測厚",
            "inspect_frequency": "每年",
            "procedure_ref": "MI-T-101",
            "pid_drawing_no": "PID-TANK-001",
        },
        {
            "equipment_id": "P-101",
            "is_critical": False,
            "basis": "泵浦故障由操作程序涵蓋，未列為安全關鍵",
        },
        {
            "equipment_id": "PSV-101",
            "is_critical": True,
            "basis": "釋壓裝置，不因篩選未完成而略過",
            "damage_mechanism": "不適用腐蝕機制",
            "inspect_method": "設定壓力查驗",
            "inspect_frequency": "每年",
            "procedure_ref": "MI-PSV-101",
            "pid_drawing_no": "PID-TANK-001",
        },
        {
            "equipment_id": "ESD-101",
            "is_critical": True,
            "basis": "緊急停車系統",
            "damage_mechanism": "不適用腐蝕機制",
            "inspect_method": "功能測試",
            "inspect_frequency": "每年",
            "procedure_ref": "MI-ESD-101",
            "pid_drawing_no": "PID-TANK-001",
        },
        {
            "equipment_id": "LA-101",
            "is_critical": False,
            "basis": "裝卸設備以許可與程序控制，未列為安全關鍵",
        },
        {
            "equipment_id": "S-201",
            "is_critical": True,
            "basis": "廢氣排放路徑",
            "damage_mechanism": "不適用金屬腐蝕機制",
            "inspect_method": "填料與壓差檢查",
            "inspect_frequency": "每半年",
            "procedure_ref": "MI-S-201",
        },
        {
            "equipment_id": "PL-201",
            "is_critical": True,
            "basis": "碳鋼輸送腐蝕性酸液，停車可能殘留",
            "damage_mechanism": "均勻腐蝕",
            "inspect_method": "測厚",
            "inspect_frequency": "每年",
            "procedure_ref": "MI-PL-201",
        },
    ):
        svc.save_mi_screen(conn, screen)
    for fail in (
        ("T-101", 8000, 0),
        ("PSV-101", 8760, 0),
        ("ESD-101", 8760, 0),
        ("S-201", 8000, 0),
        ("PL-201", 4000, 1),
    ):
        svc.save_mi_failure(
            conn,
            {
                "equipment_id": fail[0],
                "period_start": "2025-01-01",
                "period_end": "2025-12-31",
                "run_hours": fail[1],
                "failure_count": fail[2],
            },
        )
    svc.save_assessment(
        conn,
        {
            "assessment_id": "PHA-2026-001",
            "method": "HAZOP",
            "matrix_version": MATRIX_VERSION,
            "status": "draft",
            "assessment_date": "2026-03-15",
        },
    )
    svc.save_node(
        conn,
        {
            "node_id": "N-01",
            "assessment_id": "PHA-2026-001",
            "process_id": "P-TANK",
            "description": "T-101 儲槽液位",
            "deviation": "液位過高",
            "cause": "卸收未停／液位計失效",
            "drawing_no": "PID-TANK-001",
            "drawing_revision": "B",
            "considers_location": True,
            "considers_human": True,
            "considers_control_failure": True,
        },
        equipment_ids=["T-101"],
        cas_list=["108-88-3"],
    )
    svc.save_node(
        conn,
        {
            "node_id": "N-02",
            "assessment_id": "PHA-2026-001",
            "process_id": "P-TANK",
            "description": "P-101 輸送",
            "deviation": "出口閥誤關／無流量",
            "cause": "人員誤關出口閥",
            "drawing_no": "PID-TANK-001",
            "drawing_revision": "B",
            "considers_location": True,
            "considers_human": True,
            "considers_control_failure": True,
        },
        equipment_ids=["P-101", "ESD-101"],
        cas_list=["108-88-3"],
    )
    svc.save_consequence(
        conn,
        {
            "consequence_id": "C-N01-1",
            "node_id": "N-01",
            "description": "甲苯溢流，蒸氣雲遇火源火災／對勞工造成灼傷與吸入危害",
            "disaster_type": "火災／外洩",
            "area_code": "AREA-A",
        },
    )
    svc.save_consequence(
        conn,
        {
            "consequence_id": "C-N02-1",
            "node_id": "N-02",
            "description": "泵浦過熱損壞，軸封洩漏甲苯",
            "disaster_type": "外洩",
            "area_code": "AREA-A",
        },
    )
    svc.save_safeguard(
        conn,
        {
            "safeguard_id": "SG-N01-ESD",
            "consequence_id": "C-N01-1",
            "kind": "scenario",
            "scenario_id": "ESD-SC-TANK-01",
        },
    )
    svc.save_safeguard(
        conn,
        {
            "safeguard_id": "SG-N02-ESD",
            "consequence_id": "C-N02-1",
            "kind": "equipment",
            "equipment_id": "ESD-101",
        },
    )
    svc.save_risk_score(
        conn,
        {
            "risk_id": "R-N01-1",
            "consequence_id": "C-N01-1",
            "matrix_version": MATRIX_VERSION,
            "severity": 4,
            "likelihood": 2,
        },
    )
    svc.save_risk_score(
        conn,
        {
            "risk_id": "R-N02-1",
            "consequence_id": "C-N02-1",
            "matrix_version": MATRIX_VERSION,
            "severity": 3,
            "likelihood": 2,
        },
    )
    svc.save_recommendation(
        conn,
        {
            "rec_id": "REC-001",
            "assessment_id": "PHA-2026-001",
            "consequence_id": "C-N01-1",
            "target_table": "Equipment",
            "target_pk": "T-101",
            "description": "既有防範：高高液位緊急停車。改善建議：增設獨立高高液位開關。預計完成 2026-12-31。",
            "marked_improved": False,
            "master_updated": False,
            "reassessed_or_waiver": False,
        },
    )
    conn.execute(
        """INSERT INTO meeting(meeting_id, assessment_id, process_id, meeting_date, notes)
           VALUES ('M-2026-0315','PHA-2026-001','P-TANK','2026-03-15','完成 P-TANK 兩節點 HAZOP')
           ON CONFLICT(meeting_id) DO NOTHING"""
    )
    for name, role, q in (
        ("林評估", "製程安全評估合格人員", 1),
        ("張主管", "工作場所作業主管", 0),
        ("李場所", "工作場所負責人", 0),
        ("王職安", "職業安全衛生人員", 0),
        ("陳勞工", "熟悉該場所作業勞工", 0),
    ):
        conn.execute(
            "INSERT INTO signoff(assessment_id, person_name, role, qualified) VALUES (?,?,?,?)",
            ("PHA-2026-001", name, role, q),
        )

    svc.save_change(
        conn,
        {
            "change_id": "CHG-2026-001",
            "target_table": "Equipment",
            "target_pk": "T-101",
            "description": "更換 T-101 液位計（已核准）",
            "change_type": "製程修改／永久",
            "status": "approved",
            "approved": True,
            "impact_json": '{"nodes":["N-01"],"sop":["SOP-TANK-01"]}',
        },
    )
    svc.save_loading_occupancy(
        conn,
        {
            "occupancy_id": "LOAD-001",
            "equipment_id": "LA-101",
            "process_id": "P-LOAD",
            "cas": "108-88-3",
            "plate_or_container": "ABC-1234",
            "start_ts": "2026-08-18 09:00",
            "end_ts": "2026-08-18 11:30",
        },
    )
    svc.save_inspection(
        conn,
        {
            "inspection_id": "INS-001",
            "equipment_id": "T-101",
            "inspect_date": "2026-06-01",
            "inspector": "保養課／黃技師",
            "method": "目視及測厚",
            "result": "合格",
            "overdue": False,
            "defect_open": False,
        },
    )
    conn.execute(
        """INSERT INTO worker_activity(activity_id, process_id, activity_type, activity_date, description)
           VALUES ('ACT-001','P-TANK','HAZOP 參與','2026-03-15','操作課勞工陳勞工參與 P-TANK 評估會議')
           ON CONFLICT(activity_id) DO NOTHING"""
    )
    conn.execute(
        """INSERT INTO info_access(process_id, channel, known)
           VALUES ('P-TANK','內網製程安全資訊區／現場看板',1)"""
    )
    conn.execute(
        """INSERT INTO training_course(course_id, process_id, name, hours, audience, kind, op_kind, equipment_id)
           VALUES ('COURSE-TANK-01','P-TANK','儲槽製程操作','8','即將從事 P-TANK 操作勞工','initial','process',NULL),
                  ('COURSE-LOAD-01','P-LOAD','裝卸製程操作','8','即將從事 P-LOAD 操作勞工','initial','process',NULL),
                  ('COURSE-SCRUB-01','P-SCRUB','後段處理製程操作','8','即將從事 P-SCRUB 操作勞工','initial','process',NULL),
                  ('COURSE-ACID-01','P-ACID','酸液輸送製程操作','8','即將從事 P-ACID 操作勞工','initial','process',NULL)
           ON CONFLICT(course_id) DO UPDATE SET
             name=excluded.name, hours=excluded.hours, audience=excluded.audience,
             op_kind=excluded.op_kind, equipment_id=excluded.equipment_id"""
    )
    for eid, pid in (
        ("T-101", "P-TANK"),
        ("P-101", "P-TANK"),
        ("PSV-101", "P-TANK"),
        ("ESD-101", "P-TANK"),
        ("LA-101", "P-LOAD"),
        ("S-201", "P-SCRUB"),
        ("PL-201", "P-ACID"),
    ):
        conn.execute(
            """INSERT INTO training_course(course_id, process_id, name, hours, audience, kind, op_kind, equipment_id)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(course_id) DO UPDATE SET
                 process_id=excluded.process_id, name=excluded.name, hours=excluded.hours,
                 audience=excluded.audience, op_kind=excluded.op_kind, equipment_id=excluded.equipment_id""",
            (
                f"COURSE-EQ-{eid}",
                pid,
                f"{eid} 機械設備操作",
                4,
                f"操作／維護 {eid} 人員",
                "initial",
                "equipment",
                eid,
            ),
        )
    conn.execute(
        """INSERT INTO training_record(record_id, course_id, trainee, train_date, tested)
           VALUES ('TR-001','COURSE-TANK-01','陳小華','2026-02-10',1)
           ON CONFLICT(record_id) DO NOTHING"""
    )
    conn.execute(
        """UPDATE training_course
           SET refresh_hours=4, refresh_every='每年'
           WHERE kind='initial'"""
    )
    conn.execute(
        """INSERT INTO pssr(pssr_id, equipment_id, process_id, change_id, pssr_date, findings)
           VALUES ('PSSR-001','T-101','P-TANK','CHG-2026-001','2026-04-01','無影響安全缺失')
           ON CONFLICT(pssr_id) DO NOTHING"""
    )
    conn.execute(
        """INSERT INTO emergency_org(site_id, org_summary, command_center)
           VALUES (?, '現場指揮官—操作課主管；通報—職安；搶救—保養課', 'AREA-M 廠界北側集合點')
           ON CONFLICT(site_id) DO NOTHING""",
        (SITE_ID,),
    )
    conn.execute(
        """INSERT INTO drill(drill_id, process_id, consequence_id, drill_date, notes)
           VALUES ('DRILL-001','P-TANK','C-N01-1','2026-05-20','依 N-01 溢流火災後果演練疏散')
           ON CONFLICT(drill_id) DO NOTHING"""
    )
    conn.execute(
        """INSERT INTO audit_plan(site_id, first_done, planned_date, notes)
           VALUES (?, 0, '2026-12-01', '尚未第一次符合性稽核；預定計畫已列十四項')
           ON CONFLICT(site_id) DO NOTHING""",
        (SITE_ID,),
    )
    conn.execute("DELETE FROM audit_checklist")
    for n, title in UNIT_TITLES.items():
        conn.execute(
            "INSERT INTO audit_checklist(item_no, unit_no, prompt) VALUES (?,?,?)",
            (n, n, f"附表{n} {title}：是否正確掛載製程／設備／CAS 編號（不得另造名稱）"),
        )
    conn.execute(
        """INSERT INTO trade_secret(doc_id, process_id, drawing_no, title, ids_selectable)
           VALUES ('TS-001','P-TANK','PID-TANK-001','儲槽區 P&ID 細節',1)
           ON CONFLICT(doc_id) DO NOTHING"""
    )
    conn.execute("DELETE FROM unit_procedure")
    for n in range(1, 15):
        conn.execute(
            "INSERT INTO unit_procedure(unit_no, procedure_no, attachment_path) VALUES (?,?,?)",
            (n, None, None),
        )
    conn.execute(
        """UPDATE unit_procedure SET procedure_no=?, attachment_path=? WHERE unit_no=6""",
        ("CTR-P-001", "placeholder://contractor-mgmt.pdf"),
    )
    conn.execute(
        """UPDATE unit_procedure SET procedure_no=?, attachment_path=? WHERE unit_no=9""",
        ("HW-P-001", "placeholder://hotwork-permit.pdf"),
    )
    svc.save_assessment(
        conn,
        {
            "assessment_id": "PHA-ACID-001",
            "method": "HAZOP",
            "matrix_version": MATRIX_VERSION,
            "status": "draft",
            "assessment_date": "2026-08-21",
        },
    )
    svc.save_node(
        conn,
        {
            "node_id": "N-ACID-01",
            "assessment_id": "PHA-ACID-001",
            "process_id": "P-ACID",
            "description": "PL-201 酸液輸送管線",
            "deviation": "停車未排淨",
            "cause": "殘留酸液接觸碳鋼",
            "considers_location": True,
            "considers_human": True,
            "considers_control_failure": True,
        },
        equipment_ids=["PL-201"],
        cas_list=["7647-01-0"],
    )
    svc.save_consequence(
        conn,
        {
            "consequence_id": "C-ACID-01",
            "node_id": "N-ACID-01",
            "description": "碳鋼管線因殘留腐蝕性物質可能穿孔外洩",
            "disaster_type": "外洩",
            "area_code": "AREA-A",
        },
    )
    conn.commit()
    svc.mark_assessment_complete(conn, "PHA-2026-001")


def seed_hf_demo(conn: sqlite3.Connection) -> None:
    """Fill the public demo with the same HF case used by the fourteen-step wizard."""
    from psm.wizard import apply_step_defaults

    for step in range(1, 15):
        apply_step_defaults(conn, SITE_ID, step)
    fil.set_flag(conn, SITE_ID, "report_v83", "1")

    for process_id, suffix, title in (
        ("P-TANK", "TANK", "氣態 HF 供料"),
        ("P-LOAD", "LOAD", "無水 HF 密閉接收"),
        ("P-SCRUB", "SCRUB", "含氟尾氣鹼洗"),
        ("P-ACID", "ACID", "鹼液輸送"),
    ):
        svc.save_sop(conn, {
            "sop_id": f"SOP-{suffix}-01", "process_id": process_id,
            "title": f"{title}製程操作", "procedure_no": f"SOP-{suffix}-01",
            "body": f"示範摘要：{title}開始前確認核准操作界限、密閉狀態及 HF 監測；異常時依停車與應變程序隔離、通報。正式步驟依核准程序書。",
            "op_kind": "process",
        })
        svc.save_training_course(conn, {
            "course_id": f"COURSE-{suffix}-01", "process_id": process_id,
            "name": f"{title}與 HF 暴露防護", "hours": 8,
            "audience": "操作課", "kind": "initial", "op_kind": "process",
            "sop_id": f"SOP-{suffix}-01",
        })
    for equipment_id, process_id in (
        ("T-101", "P-TANK"), ("P-101", "P-TANK"),
        ("PSV-101", "P-TANK"), ("ESD-101", "P-TANK"),
        ("LA-101", "P-LOAD"), ("V-101", "P-LOAD"),
        ("S-201", "P-SCRUB"), ("PL-201", "P-ACID"),
    ):
        svc.save_sop(conn, {
            "sop_id": f"SOP-EQ-{equipment_id}", "equipment_id": equipment_id,
            "title": f"{equipment_id} 設備操作與隔離",
            "procedure_no": f"SOP-EQ-{equipment_id}",
            "body": "示範摘要：核對設備資料表、相容性、檢查與隔離狀態；異常立即停用並通報。正式程序由事業單位核准。",
            "op_kind": "equipment",
        })
        svc.save_training_course(conn, {
            "course_id": f"COURSE-EQ-{equipment_id}",
            "process_id": process_id,
            "equipment_id": equipment_id,
            "name": f"{equipment_id} 設備操作與異常通報",
            "hours": 4, "audience": "操作與維護人員",
            "kind": "initial", "op_kind": "equipment",
            "sop_id": f"SOP-EQ-{equipment_id}",
        })

    for mapping in (
        ("P-TANK", "T-101", "7664-39-3"),
        ("P-TANK", "P-101", "7664-39-3"),
        ("P-TANK", "PSV-101", "7664-39-3"),
        ("P-LOAD", "LA-101", "7664-39-3"),
        ("P-LOAD", "V-101", "7664-39-3"),
        ("P-SCRUB", "S-201", "1310-73-2"),
        ("P-ACID", "PL-201", "1310-73-2"),
    ):
        svc.save_pec_map(conn, {
            "process_id": mapping[0], "equipment_id": mapping[1],
            "cas": mapping[2], "may_remain": False,
        })
    svc.save_pec_map(conn, {
        "process_id": "P-TANK", "equipment_id": "ESD-101",
        "no_process_chemical": True,
    })
    svc.save_process_route(conn, {
        "route_id": "ROUTE-HF", "site_id": SITE_ID,
        "note": "無水 HF 密閉接收、氣態供料、含氟尾氣鹼洗",
        "blocks": [
            {
                "seq_no": 1, "process_id": "P-LOAD", "note": "液態無水 HF 密閉接收及汽化",
                "equipment_ids": ["LA-101", "V-101"],
                "cas_list": [("P-LOAD", "7664-39-3")],
            },
            {
                "seq_no": 2, "process_id": "P-TANK", "note": "氣態 HF 緩衝與密閉供料",
                "equipment_ids": ["T-101", "P-101", "ESD-101"],
                "cas_list": [("P-TANK", "7664-39-3")],
            },
            {
                "seq_no": 3, "process_id": "P-SCRUB", "note": "尾氣鹼洗",
                "equipment_ids": ["S-201"],
                "cas_list": [("P-SCRUB", "1310-73-2")],
            },
        ],
    })
    svc.save_loading_occupancy(conn, {
        "occupancy_id": "LOAD-HF-001", "equipment_id": "LA-101",
        "process_id": "P-LOAD", "cas": "7664-39-3",
        "plate_or_container": "HF-TANKER-001",
        "start_ts": "2026-08-18 09:00", "end_ts": "2026-08-18 11:30",
    })
    svc.save_assessment(conn, {
        "assessment_id": "PHA-HF-001", "method": "HAZOP",
        "matrix_version": MATRIX_VERSION, "status": "draft",
        "assessment_date": "2026-03-15",
    })
    svc.save_node(conn, {
        "node_id": "N-HF-01", "assessment_id": "PHA-HF-001",
        "process_id": "P-TANK", "description": "T-101 氣態 HF 緩衝與供料",
        "deviation": "壓力過高或失去密閉",
        "cause": "下游堵塞、密封失效或隔離閥誤動作",
        "drawing_no": "PID-TANK-001", "drawing_revision": "B",
        "considers_location": True, "considers_human": True,
        "considers_control_failure": True,
    }, equipment_ids=["T-101", "P-101", "ESD-101"], cas_list=["7664-39-3"])
    svc.save_consequence(conn, {
        "consequence_id": "C-HF-01", "node_id": "N-HF-01",
        "description": "HF 氣體外洩，可能造成吸入暴露及鄰近區域疏散",
        "disaster_type": "外洩", "area_code": "AREA-A",
    })
    svc.save_safeguard(conn, {
        "safeguard_id": "SG-HF-ESD", "consequence_id": "C-HF-01",
        "kind": "scenario", "scenario_id": "ESD-SC-TANK-01",
    })
    svc.save_node(conn, {
        "node_id": "N-HF-02", "assessment_id": "PHA-HF-001",
        "process_id": "P-TANK", "description": "P-101 HF 供氣壓送機",
        "deviation": "密封失效", "cause": "密封老化或材質不相容",
        "drawing_no": "PID-TANK-001", "drawing_revision": "B",
        "considers_location": True, "considers_human": True,
        "considers_control_failure": True,
    }, equipment_ids=["P-101"], cas_list=["7664-39-3"])
    svc.save_consequence(conn, {
        "consequence_id": "C-HF-02", "node_id": "N-HF-02",
        "description": "局部 HF 洩漏，維修人員可能吸入或接觸",
        "disaster_type": "外洩", "area_code": "AREA-A",
    })
    svc.save_safeguard(conn, {
        "safeguard_id": "SG-HF-DET", "consequence_id": "C-HF-02",
        "kind": "equipment", "equipment_id": "ESD-101",
    })
    svc.save_risk_score(conn, {
        "risk_id": "R-HF-01", "consequence_id": "C-HF-01",
        "matrix_version": MATRIX_VERSION, "severity": 4, "likelihood": 2,
    })
    svc.save_risk_score(conn, {
        "risk_id": "R-HF-02", "consequence_id": "C-HF-02",
        "matrix_version": MATRIX_VERSION, "severity": 4, "likelihood": 2,
    })
    svc.save_recommendation(conn, {
        "rec_id": "REC-HF-01", "assessment_id": "PHA-HF-001",
        "consequence_id": "C-HF-01", "target_table": "Equipment",
        "target_pk": "T-101",
        "description": "補齊 HF 偵測、密封材質與隔離連鎖的核准佐證；完成後由評估小組重新確認。",
        "marked_improved": False, "master_updated": False,
        "reassessed_or_waiver": False,
    })
    for equipment_id, basis, method in (
        ("T-101", "HF 緩衝容器，失去密閉可能造成暴露", "依核准計畫檢查密封與材質"),
        ("PSV-101", "HF 超壓保護裝置", "設定壓力與排放路徑查驗"),
        ("ESD-101", "HF 偵測及緊急隔離", "連鎖功能測試"),
        ("S-201", "含氟尾氣處理路徑", "吸收效能與設備完整性確認"),
    ):
        svc.save_mi_screen(conn, {
            "equipment_id": equipment_id, "is_critical": True,
            "basis": basis, "damage_mechanism": "由材質與介質條件確認",
            "inspect_method": method, "inspect_frequency": "依核准計畫",
            "procedure_ref": f"MI-{equipment_id}",
            "pid_drawing_no": "PID-TANK-001",
        })
    conn.execute(
        """INSERT INTO emergency_org(site_id, org_summary, command_center)
           VALUES (?, '現場指揮—操作課；通報與暴露處置—職安；隔離—受訓應變組',
                   'AREA-M 上風側集合點，依當日風向調整')
           ON CONFLICT(site_id) DO NOTHING""", (SITE_ID,)
    )
    conn.commit()
