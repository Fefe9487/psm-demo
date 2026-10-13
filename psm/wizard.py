"""首次填報精靈：十四項各一步；未完成不得跳步。"""

from __future__ import annotations

import sqlite3
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from math import isfinite
from pathlib import Path

from psm.db import db_path
from psm.enums import PROCESS_OVERVIEWS, UNIT_TITLES
from psm import filing as fil
from psm import services as svc
from psm.sample_flow import HF_FLOW_ROWS

PREFILL = {
    "company_name": "示範事業股份有限公司",
    "site_name": "HF 密閉供料示範場所",
    "scope": "無水氟化氫密閉卸收、氣態供料及含氟尾氣鹼洗",
    "applicant_name": "王大明",
    "worker_count": "12",
    "assessment_base_date": "2026-08-21",
    "declare_no_equipment_types": "控制系統,其他",
    "dept_id": "D-OPS",
    "dept_name": "操作課",
    "org_file": "org-chart.pdf",
    "doc_date": "2026-01-15",
    "process_id": "P-TANK",
    "process_name": "氣態 HF 供料",
    "area_code": "AREA-A",
    "area_name": "HF 供料區",
    "drawing_no": "PLOT-001",
    "revision": "A",
    "equipment_id": "T-101",
    "equipment_name": "氣態 HF 緩衝槽",
    "cas": "7664-39-3",
    "chem_name": "無水氟化氫",
    "pid_no": "PID-TANK-001",
    "pid_rev": "B",
}

N_STEPS = 14

_WHY = {
    1: "先建立場所、部門、製程、設備、化學品與區域，讓後續章節能直接選用一致的編號。再補上危害資料、操作界限、圖資、安全系統與法令文件。",
    2: "記錄採用哪些危害評估方法、為何採用、各自考量多少問題，並上傳實際評估紀錄。有風險分級時，填寫判定準則與高風險情境。",
    3: "逐項說明勞工如何參與安全管理工作、由誰參與，並上傳程序書或引用既有文件。刪除某項後，完成狀態會提示需要補回。",
    4: "為現有設備類型建立作業程序，也記錄臨時操作、緊急操作及安全操作界限。刪除最後一筆程序後，該類型會顯示待補。",
    5: "列出訓練課程、適用對象、初次與再次訓練安排，逐份核對 SOP 是否已有課程或例外理由。",
    6: "列齊保養、工程及臨時維修承攬商與期間，再關聯其職災或虛驚；近五年沒有事故時據實註明。",
    7: "逐台確認是否適用啟動前安全檢查，再記錄適用設備的檢查日期、改善建議與追蹤。",
    8: "從已建設備選出安全關鍵設備，填維修保養方式、檢查紀錄及各設備的失效率。損壞機制仍需由人員確認。",
    9: "選出需要動火許可的區域，說明防護原因，並填寫動火作業的確認事項。",
    10: "判斷本場所是否有變更案件；有案件時選擇製程與相關設備，記錄變更內容及訓練。",
    11: "上傳事故調查程序書，並列出近五年事故與虛驚；沒有案件時據實註明。",
    12: "列出緊急狀況，複選並確認相關製程、設備、化學品與區域，再登錄搶救設備及器材。",
    13: "已有稽核時記錄計畫；尚未執行首次稽核時可註明免填 13.1。首次申請的 13.2 免填，已有改善事項仍可自願記錄。",
    14: "本章無填報表，以上傳程序書檢核。未揭露成分不虛構 CAS。完成本步後可預覽申報報告。",
}

_TASK = {
    1: "先建立場所、部門、製程、設備、化學品及區域清單，再依下方段落補齊本章資料。",
    2: "選擇評估方法並說明原因，填寫考量問題數，上傳評估紀錄；有風險分級時補齊判定準則。",
    3: "逐項新增勞工參與方式。十三項均填妥後，再上傳程序書並填日期，或引用已上傳文件。",
    4: "為每一種現有設備類型建立至少一筆作業程序，再填臨時操作、緊急操作與安全界限。",
    5: "新增訓練課程，填初訓與複訓安排，並確認每份 SOP 有課程或例外理由。",
    6: "列齊承攬商與期間、上傳管理程序，並關聯事故；零事故也要確認名冊。",
    7: "逐台判定是否適用；適用設備填檢查紀錄，不適用或全場所無案件須說明理由。",
    8: "安全關鍵設備必須是已有編號。八類對六類由人確認。劣化機制資料庫只提供說明，不連庫、不代評分。失效率按設備編號填。",
    9: "列舉動火管制區域及防護原因；可再答四項確認。",
    10: "勾無需變更，或已答定義題且有列／註明尚無案件。",
    11: "有事故列或註明近五年 0 件。",
    12: "逐筆確認緊急狀況的相關製程、設備、化學品、區域及集合點，並列搶救器材。",
    13: "先確認是否已執行首次稽核；已有稽核時填 13.1 計畫。13.2 首次申請免填。",
    14: "上傳商業機密管理程序書，確認檔名顯示後預覽報告。",
}

_NEXT = {
    1: "下一步只填評估方法、數量、準則與上傳，不會出現節點或多選設備評分表。",
    2: "下一步十三列勞工參與，部門下拉用你已建的編號。",
    3: "下一步 SOP 依設備類型預派，製程與代表設備都是下拉。",
    4: "下一步訓練課程掛已有製程，對應作業程序選表4.1-1。",
    5: "下一步填承攬職災／虛驚。保養、工程、臨時維修都要填。",
    6: "下一步啟動前安全檢查，設備編號選表1.0-3。",
    7: "下一步機械完整性與設備同一編號。",
    8: "下一步列舉動火管制區域。工廠維修幾乎都有動火。",
    9: "下一步變更對象只能選已有編號。",
    10: "下一步事故調查：近五年 0 件只要註明。",
    11: "下一步緊急應變：狀況表、確認事項與器材清單。",
    12: "下一步符合性稽核計畫，單元名稱用十四項下拉。",
    13: "最後一章上傳商業機密管理程序書；完成後可預覽報告。",
    14: "可回任一步更正；資料表摺疊區給已會填的人改單筆。示範廠可另開對照。",
}

SOP_TYPE_SLUG = {
    "壓力容器與儲槽": "VESSEL",
    "管線系統": "PIPE",
    "釋放及排放系統": "RELIEF",
    "緊急停車系統": "ESD",
    "控制系統": "CTRL",
    "動力來源": "POWER",
    "裝卸及輸送": "LOAD",
    "其他": "OTHER",
}

STEPS = tuple(
    {
        "n": n,
        "title": UNIT_TITLES[n],
        "why": _WHY[n],
        "task": _TASK[n],
        "next_hint": _NEXT[n],
    }
    for n in range(1, 15)
)


def store_upload(site_id: str, prefix: str, upload, fallback: str) -> str:
    name = getattr(upload, "filename", None) if upload is not None else None
    if upload is not None and name:
        dest = db_path().parent / "uploads" / site_id
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"{prefix}_{Path(name).name}"
        path.write_bytes(upload.file.read())
        return str(path)
    fb = (fallback or "").strip()
    if not fb:
        return ""
    if "://" in fb or "/" in fb or "\\" in fb:
        return fb
    return f"placeholder://{fb}"


def has_uploaded_file(path: str | None) -> bool:
    """Only a file stored on disk counts as an uploaded attachment."""
    value = (path or "").strip()
    if not value or value.startswith("placeholder://"):
        return False
    try:
        file = Path(value)
        return file.is_file() and file.stat().st_size > 0
    except OSError:
        return False


def guess_material_category(material: str | None) -> str:
    return svc.infer_material_category(material)


def declared_no_types(site) -> set[str]:
    if not site:
        return set()
    raw = site["declare_no_equipment_types"] if "declare_no_equipment_types" in site.keys() else ""
    return {x.strip() for x in (raw or "").split(",") if x.strip()}


def existing_equipment_types(conn: sqlite3.Connection, site_id: str) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT equipment_type FROM equipment WHERE site_id=?", (site_id,)
        )
    }


def sop_covered_types(conn: sqlite3.Connection, site_id: str) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            """SELECT e.equipment_type
               FROM sop_equipment se
               JOIN sop s ON s.sop_id=se.sop_id
               JOIN equipment e ON e.equipment_id=se.equipment_id
               JOIN process p ON p.process_id=s.process_id
               WHERE p.site_id=? AND se.confirmed=1 AND e.process_id=s.process_id""",
            (site_id,),
        )
    }


def sop_type_gaps(conn: sqlite3.Connection, site_id: str) -> list[str]:
    need = existing_equipment_types(conn, site_id)
    covered = sop_covered_types(conn, site_id)
    miss = sorted(need - covered)
    if not miss:
        return []
    return [f"表4.1-1 每一已存在設備類型須留一筆程序（缺：{'、'.join(miss)}）"]


def count_sops_for_type(conn: sqlite3.Connection, site_id: str, equipment_type: str) -> int:
    return _count(
        conn,
        """SELECT COUNT(DISTINCT s.sop_id) FROM sop_equipment se
           JOIN sop s ON s.sop_id=se.sop_id
           JOIN equipment e ON e.equipment_id=se.equipment_id
           JOIN process p ON p.process_id=s.process_id
           WHERE p.site_id=? AND se.confirmed=1 AND e.process_id=s.process_id
           AND e.equipment_type=?""",
        (site_id, equipment_type),
    )


def ensure_sops_for_types(conn: sqlite3.Connection, site_id: str) -> None:
    site = _site(conn, site_id)
    if not site:
        return
    covered = sop_covered_types(conn, site_id)
    for etype in sorted(existing_equipment_types(conn, site_id)):
        if etype in covered:
            continue
        eq = conn.execute(
            """SELECT equipment_id, process_id, name FROM equipment
               WHERE site_id=? AND equipment_type=? ORDER BY equipment_id""",
            (site_id, etype),
        ).fetchone()
        if not eq:
            continue
        slug = SOP_TYPE_SLUG.get(etype, "X")
        sop_id = f"SOP-{slug}-01"
        n = 1
        while conn.execute("SELECT 1 FROM sop WHERE sop_id=?", (sop_id,)).fetchone():
            n += 1
            sop_id = f"SOP-{slug}-{n:02d}"
        svc.save_sop(
            conn,
            {
                "sop_id": sop_id,
                "process_id": eq["process_id"],
                "title": f"{etype}操作程序",
                "procedure_no": sop_id,
                "body": "",
                "op_kind": "equipment",
                "equipment_id": eq["equipment_id"],
            },
        )


def default_area_code(conn: sqlite3.Connection, site_id: str, process_id: str = "") -> str:
    if process_id:
        row = conn.execute(
            """SELECT area_code FROM area WHERE site_id=? AND process_id=?
               ORDER BY area_code""",
            (site_id, process_id),
        ).fetchone()
        if row:
            return row["area_code"]
    row = conn.execute(
        "SELECT area_code FROM area WHERE site_id=? ORDER BY area_code", (site_id,)
    ).fetchone()
    return row["area_code"] if row else ""


def _site(conn: sqlite3.Connection, site_id: str):
    return conn.execute("SELECT * FROM site WHERE site_id=?", (site_id,)).fetchone()


def _count(conn: sqlite3.Connection, sql: str, args=()) -> int:
    return conn.execute(sql, args).fetchone()[0]


def _overview_ok(conn: sqlite3.Connection, site_id: str) -> bool:
    flags = fil.all_flags(conn, site_id)
    if (flags.get("overview") or "").strip():
        return True
    for p in conn.execute(
        "SELECT process_id, overview FROM process WHERE site_id=?", (site_id,)
    ):
        if (p["overview"] or "").strip():
            return True
        if (flags.get(f"overview:{p['process_id']}") or "").strip():
            return True
    return bool(fil.list_rows(conn, site_id, "1.3"))


DOCUMENT_REQUIREMENTS: dict[int, tuple[tuple[str, str], ...]] = {
    4: (("sop_procedure", "標準作業程序書"),),
    5: (("training_evidence", "教育訓練教材、簽到與測驗佐證"),),
    6: (("contractor_procedure", "承攬管理與危害告知程序書"),),
    7: (("pssr_checklist", "啟動前安全檢查表"),),
    8: (("mi_procedure", "機械完整性檢查測試程序書"),),
    9: (("hotwork_procedure", "動火許可程序書"),),
    10: (("moc_plan", "變更管理程序書（手冊亦稱變更管理計畫書）"),),
    11: (("incident_procedure", "事故調查程序書"),),
    12: (("emergency_plan", "緊急應變計畫全文"),),
    13: (("audit_procedure", "符合性稽核程序書"),),
}


def document_requirements(conn: sqlite3.Connection, site_id: str, n: int) -> tuple[tuple[str, str], ...]:
    if n == 7 and fil.get_flag(conn, site_id, "pssr_na") == "1":
        return ()
    return DOCUMENT_REQUIREMENTS.get(n, ())


def document_gaps(conn: sqlite3.Connection, site_id: str, n: int) -> list[str]:
    rows = conn.execute(
        """SELECT r.purpose, d.attachment_path FROM filing_document_ref r
           JOIN filing_document d ON d.document_id=r.document_id
           WHERE r.site_id=? AND r.step=? AND d.site_id=?""",
        (site_id, n, site_id),
    ).fetchall()
    ready = {row["purpose"] for row in rows if has_uploaded_file(row["attachment_path"])}
    return [f"第{n}章請上傳或引用已上傳的{label}（文件編號、名稱、修訂日期）"
            for purpose, label in document_requirements(conn, site_id, n) if purpose not in ready]


LIMIT_PARAMETERS = ("壓力", "溫度", "流量", "組成")


def operating_review_gaps(conn: sqlite3.Connection, site_id: str) -> list[str]:
    """1.5 belongs to every equipment, including units with no applicable numeric limit."""
    gaps: list[str] = []
    for equipment in conn.execute(
        "SELECT equipment_id,process_id FROM equipment WHERE site_id=? ORDER BY equipment_id", (site_id,)
    ):
        eid, pid = equipment["equipment_id"], equipment["process_id"]
        review = conn.execute(
            "SELECT * FROM equipment_operating_review WHERE equipment_id=?", (eid,)
        ).fetchone()
        if not review:
            gaps.append(f"1.5 設備 {eid} 尚未確認檢討參數、實際內容物與單次操作量")
            continue
        try:
            selected = json.loads(review["selected_parameters"] or "[]")
        except (TypeError, ValueError):
            selected = None
        if not isinstance(selected, list) or len(selected) != len(set(map(str, selected))) or any(p not in LIMIT_PARAMETERS for p in selected):
            gaps.append(f"1.5 設備 {eid} 的檢討參數資料無效，須重新確認")
            selected = []
        if not selected and not str(review["no_parameter_reason"] or "").strip():
            gaps.append(f"1.5 設備 {eid} 未選安全界限參數，須說明不適用原因")
        if selected and str(review["no_parameter_reason"] or "").strip():
            gaps.append(f"1.5 設備 {eid} 已選參數，不可同時聲明全部不適用")
        limits = list(conn.execute(
            """SELECT * FROM equipment_limit WHERE equipment_id=?
               AND parameter IN ('壓力','溫度','流量','組成')""", (eid,)
        ))
        for param in LIMIT_PARAMETERS:
            rows = [r for r in limits if r["parameter"] == param]
            if param not in selected and rows:
                gaps.append(f"1.5 設備 {eid}／{param} 有界限列，但本次未選此檢討項目")
            if param not in selected:
                continue
            if len(rows) != 1:
                gaps.append(f"1.5 設備 {eid}／{param} 須恰有一筆界限列（目前 {len(rows)} 筆）")
                continue
            row = rows[0]
            if not str(row["unit"] or "").strip():
                gaps.append(f"1.5 設備 {eid}／{param} 須填計算單位")
            numeric_sides = 0
            for side, label in (("high", "上限"), ("low", "下限")):
                design = str(row[f"design_{side}"] or "").strip()
                safety = str(row[f"safety_{side}"] or "").strip()
                reason = str(row[f"{side}_na_reason"] or "").strip()
                def finite(value: str) -> bool:
                    try:
                        return bool(value) and Decimal(value).is_finite()
                    except InvalidOperation:
                        return False
                if design or safety:
                    if not (finite(design) and finite(safety)) or reason:
                        gaps.append(f"1.5 設備 {eid}／{param} {label}須同時有操作值及安全值，且不可填不適用理由")
                    else:
                        numeric_sides += 1
                elif not reason:
                    gaps.append(f"1.5 設備 {eid}／{param} {label}未填數值須說明不適用原因")
            if numeric_sides == 0:
                gaps.append(f"1.5 設備 {eid}／{param} 至少一個方向須有實際數值")
        qty = review["batch_quantity"]
        unit = str(review["batch_unit"] or "").strip()
        batch_na = str(review["batch_na_reason"] or "").strip()
        if qty is None:
            if not batch_na or unit:
                gaps.append(f"1.5 設備 {eid} 須填單次操作量與單位，或說明連續操作不適用")
        else:
            try:
                valid_batch = isfinite(float(qty)) and float(qty) > 0 and bool(unit) and not batch_na
            except (TypeError, ValueError, OverflowError):
                valid_batch = False
            if not valid_batch:
                gaps.append(f"1.5 設備 {eid} 單次操作量須為正數並有單位，且不可同時填不適用理由")
        contents = list(conn.execute(
            "SELECT * FROM equipment_content WHERE equipment_id=?", (eid,)
        ))
        absent = [r for r in contents if r["no_process_chemical"]]
        actual = [r for r in contents if not r["no_process_chemical"]]
        no_content_reason = str(review["no_content_reason"] or "").strip()
        if absent:
            if actual or not no_content_reason:
                gaps.append(f"1.5 設備 {eid} 聲明無操作化學品須填理由，且不得同時選內容物")
        elif not actual:
            gaps.append(f"1.5 設備 {eid} 須確認實際內容物或說明無操作化學品")
        elif no_content_reason:
            gaps.append(f"1.5 設備 {eid} 已選內容物，不可同時填無內容物理由")
        for content in actual:
            if not conn.execute(
                """SELECT 1 FROM chemical WHERE process_id=? AND cas=? AND sds_id=?""",
                (pid, content["cas"], content["sds_id"]),
            ).fetchone():
                gaps.append(f"1.5 設備 {eid} 的內容物 {content['cas']}／{content['sds_id']} 須引用所屬製程與對應 SDS")
    return gaps


def legal_certificate_gaps(conn: sqlite3.Connection, site_id: str) -> list[str]:
    equipment = fil.legal_equipment(conn, site_id)
    rows = fil.list_rows(conn, site_id, "1.11")
    eligible = {e["equipment_id"] for e in equipment}
    gaps = []
    if fil.get_flag(conn, site_id, "no_art16") == "1":
        if equipment or rows:
            gaps.append("1.11 已有危險性機械設備、高壓氣體設備或證明資料，不得同時聲明無適用設備")
    elif not equipment and not rows:
        gaps.append("1.11 請先在表1.0-3 勾選適用設備，或聲明無危險性機械設備及高壓氣體特定設備或容器")
    for e in equipment:
        complete = False
        for row in rows:
            if row.get("equipment_id") != e["equipment_id"]:
                continue
            if not all(str(row.get(k) or "").strip() for k in ("category", "cert_no", "expire")):
                continue
            try:
                date.fromisoformat(str(row["expire"]))
            except ValueError:
                continue
            complete = True
            break
        if not complete:
            gaps.append(f"1.11 設備 {e['equipment_id']}（{e['name']}）須填設備類別、檢查合格證號碼及有效期限")
    for eid in sorted({str(row.get("equipment_id") or "") for row in rows} - eligible):
        gaps.append(f"1.11 設備 {eid or '（未選）'} 未在表1.0-3 勾選危險性機械設備或高壓氣體，請確認關聯")
    return gaps


def _step_missing_core(conn: sqlite3.Connection, site_id: str, n: int) -> list[str]:
    miss: list[str] = []
    site = _site(conn, site_id)
    flags = fil.all_flags(conn, site_id) if site else {}
    if n == 1:
        if not site:
            return ["尚未登錄場所（名稱、範圍、申請義務人、勞工人數）"]
        for col, label in (
            ("company_name", "事業單位名稱"),
            ("site_name", "場所名稱"),
            ("scope", "範圍"),
            ("applicant_name", "申請義務人"),
            ("assessment_base_date", "評估基準日"),
        ):
            if not (site[col] or "").strip():
                miss.append(f"缺{label}")
        if int(site["worker_count"] or 0) < 1:
            miss.append("場所勞工人數須至少 1")
        if _count(conn, "SELECT COUNT(*) FROM department WHERE site_id=?", (site_id,)) < 1:
            miss.append("至少新增一個部門")
        if _count(conn, "SELECT COUNT(*) FROM process WHERE site_id=?", (site_id,)) < 1:
            miss.append("至少新增一個製程（操作權責須選已有部門）")
        if _count(
            conn,
            """SELECT COUNT(*) FROM equipment WHERE site_id=?
               AND process_id IS NOT NULL AND maint_dept_id IS NOT NULL""",
            (site_id,),
        ) < 1:
            miss.append("至少新增一筆設備（須選製程、維護部門）")
        n_chem = _count(
            conn,
            """SELECT COUNT(*) FROM chemical c
               JOIN process p ON p.process_id=c.process_id WHERE p.site_id=?""",
            (site_id,),
        )
        if n_chem < 1:
            miss.append("至少新增一筆化學品（CAS＋製程＋角色＋危害說明＋SDS）")
        nosds = conn.execute(
            """SELECT c.cas, c.process_id FROM chemical c
               JOIN process p ON p.process_id=c.process_id
               WHERE p.site_id=? AND (c.sds_id IS NULL OR c.sds_id='')""",
            (site_id,),
        ).fetchall()
        if nosds:
            miss.append("每筆化學品須掛 SDS 代號")
        noh = conn.execute(
            """SELECT c.cas, c.process_id FROM chemical c
               JOIN process p ON p.process_id=c.process_id
               WHERE p.site_id=? AND (c.h_codes IS NULL OR TRIM(c.h_codes)='')""",
            (site_id,),
        ).fetchall()
        if noh:
            miss.append("每筆化學品須填危害說明（GHS H 代碼）")
        if not fil.list_rows(conn, site_id, "1.1"):
            miss.append("1.1 危害性化學品清單至少一列")
        if not _overview_ok(conn, site_id):
            miss.append("1.3 製程概述須有文字")
        safety_limits = conn.execute("""SELECT l.* FROM equipment_limit l
            JOIN equipment e ON e.equipment_id=l.equipment_id WHERE e.site_id=?
            AND l.parameter IN ('壓力','溫度','流量','組成')""", (site_id,)).fetchall()
        def finite_limit(value: object) -> bool:
            try:
                return Decimal(str(value)).is_finite()
            except InvalidOperation:
                return False
        for limit in safety_limits:
            if (not (limit["unit"] or "").strip() or
                    not any(finite_limit(limit[k]) for k in ("design_high", "design_low")) or
                    not any(finite_limit(limit[k]) for k in ("safety_high", "safety_low"))):
                miss.append(f"1.5 設備 {limit['equipment_id']}／{limit['parameter']} 須填單位、操作範圍及實際安全界限數值")
        miss.extend(operating_review_gaps(conn, site_id))
        pid = conn.execute(
            """SELECT 1 FROM pid_drawing d
               JOIN process p ON p.process_id=d.process_id
               WHERE p.site_id=? AND d.drawing_no<>'' AND d.issue_date<>''""",
            (site_id,),
        ).fetchone()
        if not pid:
            miss.append("1.7 至少一張已填圖號與日期的 PFD／P&ID")
        area_paths = conn.execute("SELECT attachment_path FROM area WHERE site_id=?", (site_id,))
        if any(not has_uploaded_file(r[0]) for r in area_paths):
            miss.append("表1.0-5 區域位置圖：請上傳實際檔案")
        sds_paths = conn.execute(
            """SELECT DISTINCT s.file_path FROM chemical c JOIN process p ON p.process_id=c.process_id
               JOIN sds s ON s.sds_id=c.sds_id WHERE p.site_id=?""",
            (site_id,),
        )
        if any(not has_uploaded_file(r[0]) for r in sds_paths):
            miss.append("表1.0-4 SDS：請上傳實際檔案")
        pid_paths = conn.execute(
            """SELECT d.attachment_path FROM pid_drawing d JOIN process p ON p.process_id=d.process_id
               WHERE p.site_id=?""",
            (site_id,),
        )
        if any(not has_uploaded_file(r[0]) for r in pid_paths):
            miss.append("表1.7-1 圖資：請上傳實際檔案")
        miss.extend(legal_certificate_gaps(conn, site_id))
        return miss
    if not site:
        return ["請先完成第 1 步（製程安全資訊）"]
    if n == 2:
        methods = [x for x in (flags.get("pha_methods") or "").split(",") if x.strip()]
        if not methods:
            miss.append("2.1 至少選一種評估方法")
        labels = {mid: title for mid, title, _ in fil.PHA_METHODS}
        for mid in methods:
            if not (flags.get(f"consider:{mid}") or "").strip():
                miss.append(f"表2.1-1 請寫「{labels.get(mid, mid)}」採用原因")
        if flags.get("risk_na") != "1":
            kinds = {str(r.get("kind") or "") for r in fil.list_rows(conn, site_id, "2.3")}
            for need in ("嚴重度", "可能性", "風險等級"):
                if need not in kinds:
                    miss.append("表2.3-1 至 2.3-3 請各至少一列，或註明僅檢核表、無風險分級")
                    break
        records = conn.execute(
            """SELECT r.method, u.attachment_path FROM pha_record r
               JOIN unstructured_attachment u ON u.attachment_id=r.attachment_id
               WHERE r.site_id=?""", (site_id,)
        ).fetchall()
        for mid in methods:
            if not any(r["method"] == mid and has_uploaded_file(r["attachment_path"]) for r in records):
                miss.append(f"表2.2-1 請上傳「{labels.get(mid, mid)}」含編號、數量及實際檔案的評估紀錄")
        return miss
    if n == 3:
        rows = fil.list_rows(conn, site_id, "3.1")
        by_item = {r.get("item"): r for r in rows}
        for item in fil.LABOR_ITEMS:
            how = (by_item.get(item) or {}).get("how") or ""
            if not str(how).strip():
                miss.append(f"3.1「{item}」須填參與方式")
                break
        if flags.get("labor_see_also") == "1":
            try:
                ref_id = int(flags.get("labor_ref") or 0)
            except ValueError:
                ref_id = 0
            ref = conn.execute(
                """SELECT u.attachment_path FROM unstructured_attachment u
                   LEFT JOIN process p ON p.process_id=u.process_id
                   WHERE u.attachment_id=? AND (u.site_id=? OR p.site_id=?)""",
                (ref_id, site_id, site_id),
            ).fetchone()
            if not ref or not has_uploaded_file(ref[0]):
                miss.append("3.2 請選擇一份已上傳的既有文件")
        else:
            labor_path = (flags.get("labor_file") or "").strip()
            if not has_uploaded_file(labor_path):
                miss.append("3.2 請上傳勞工參與程序，或註明見其他已上傳文件")
            elif not (flags.get("labor_date") or "").strip():
                miss.append("3.2 程序文件須填日期")
        return miss
    if n == 4:
        miss.extend(sop_type_gaps(conn, site_id))
        for sop in conn.execute("""SELECT s.* FROM sop s JOIN process p ON p.process_id=s.process_id
            WHERE p.site_id=? ORDER BY s.sop_id""", (site_id,)):
            try:
                valid_date = bool(sop["updated_on"]) and bool(date.fromisoformat(sop["updated_on"]))
            except (TypeError, ValueError):
                valid_date = False
            if not str(sop["title"] or "").strip() or not str(sop["procedure_no"] or "").strip() or not valid_date:
                miss.append(f"表4.1-1 程序 {sop['sop_id']} 須填文管編號、名稱與有效修訂日期")
            links = conn.execute("""SELECT se.confirmed,e.process_id FROM sop_equipment se
                JOIN equipment e ON e.equipment_id=se.equipment_id
                WHERE se.sop_id=?""", (sop["sop_id"],)).fetchall()
            if sop["op_kind"] == "equipment" and (not links or any(
                not row["confirmed"] or row["process_id"] != sop["process_id"] for row in links
            )):
                miss.append(f"表4.1-1 程序 {sop['sop_id']} 的關聯設備須重新確認且屬所選製程")
        if flags.get("sop_no_temp") != "1" and not fil.list_rows(conn, site_id, "4.2"):
            miss.append("表4.2-1 請列臨時操作項目，或聲明目前無臨時操作")
        if not fil.list_rows(conn, site_id, "4.3"):
            miss.append("表4.3-1 請列緊急停車或處置條件及操作程序")
        limit_rows = conn.execute("""SELECT l.limit_id,l.equipment_id,l.parameter,l.safety_high,l.safety_low FROM equipment_limit l
            JOIN equipment e ON e.equipment_id=l.equipment_id WHERE e.site_id=?
            AND l.parameter IN ('壓力','溫度','流量','組成') ORDER BY l.limit_id""", (site_id,)).fetchall()
        details = fil.list_rows(conn, site_id, "4.4")
        by_limit = {str(r.get("limit_id") or ""): r for r in details if r.get("limit_id")}
        if not limit_rows:
            miss.append("表4.4-1 請先於 1.5 建立壓力、溫度、流量或組成操作界限")
        for limit in limit_rows:
            key = str(limit["limit_id"])
            row = by_limit.get(key)
            label = f"{limit['equipment_id']}／{limit['parameter']}"
            def numeric_bound(value: object) -> bool:
                try:
                    return Decimal(str(value)).is_finite()
                except InvalidOperation:
                    return False
            if not any(numeric_bound(limit[k]) for k in ("safety_high", "safety_low")):
                miss.append(f"表4.4-1 {label} 的 1.5 安全上下限尚無數值")
            if not row:
                miss.append(f"表4.4-1 {label} 須分別填上限、下限偏移後果與矯正程序")
                continue
            for prefix, direction in (("high", "超上限"), ("low", "低於下限")):
                consequence = str(row.get(prefix + "_consequence") or "").strip()
                correction = str(row.get(prefix + "_correct") or "").strip()
                reason = str(row.get(prefix + "_na_reason") or "").strip()
                if not ((consequence and correction and not reason) or (reason and not consequence and not correction)):
                    miss.append(f"表4.4-1 {label} {direction}須填後果與矯正程序，或具體不適用理由")
        if any(not r.get("limit_id") for r in details):
            miss.append("表4.4-1 舊式合併上下限列須刪除，依 1.5 參數重填")
        valid_ids = {str(r["limit_id"]) for r in limit_rows}
        if any(str(r.get("limit_id") or "") not in valid_ids for r in details if r.get("limit_id")):
            miss.append("表4.4-1 有已刪除或不屬本場所的 1.5 操作界限關聯")
        return miss
    if n == 5:
        def positive_hours(value: object) -> bool:
            try:
                amount = float(value)
            except (TypeError, ValueError):
                return False
            return isfinite(amount) and amount > 0

        courses = conn.execute("""SELECT t.* FROM training_course t
            JOIN process p ON p.process_id=t.process_id WHERE p.site_id=?""", (site_id,)).fetchall()
        if not courses:
            miss.append("表5.1-1 至少一列訓練課程")
        elif not any(c["kind"] == "initial" for c in courses):
            miss.append("表5.1-1 須有初次訓練課程")
        linked = {r[0] for r in conn.execute("""SELECT l.sop_id FROM training_course_sop l
            JOIN training_course t ON t.course_id=l.course_id
            JOIN process p ON p.process_id=t.process_id WHERE p.site_id=?""", (site_id,))}
        for course in courses:
            cid = course["course_id"]
            if not positive_hours(course["hours"]):
                miss.append(f"表5.1-1 課程 {cid} 須填正數初訓時數")
            if not positive_hours(course["refresh_hours"]) or not (course["refresh_every"] or "").strip():
                miss.append(f"表5.1-1 課程 {cid} 須填複訓頻率與正數複訓時數")
            if not (course["audience"] or "").strip():
                miss.append(f"表5.1-1 課程 {cid} 須填適用對象")
            if not conn.execute("SELECT 1 FROM training_course_sop WHERE course_id=?", (cid,)).fetchone() and not (course["no_sop_reason"] or "").strip():
                miss.append(f"表5.1-1 課程 {cid} 未關聯 SOP，須說明原因")
        exceptions = {str(r.get("sop_id") or ""): str(r.get("reason") or "").strip()
                      for r in fil.list_rows(conn, site_id, "5.1e")}
        for sop in conn.execute("""SELECT s.sop_id FROM sop s JOIN process p ON p.process_id=s.process_id
            WHERE p.site_id=? ORDER BY s.sop_id""", (site_id,)):
            if sop["sop_id"] not in linked and not exceptions.get(sop["sop_id"]):
                miss.append(f"表5.1-1 SOP {sop['sop_id']} 須關聯訓練課程，或說明例外理由")
        return miss
    if n == 6:
        if _count(conn, "SELECT COUNT(*) FROM contractor WHERE site_id=?", (site_id,)) == 0:
            miss.append("6.1 請登錄承攬商及承攬期間；零事故仍須登錄承攬商")
        if flags.get("c_roster_complete") != "1":
            miss.append("6.1 請確認已列出所有保養、工程及臨時維修承攬商")
        n_inc = _count(
            conn,
            "SELECT COUNT(*) FROM contractor_incident WHERE site_id=?",
            (site_id,),
        )
        if n_inc:
            if flags.get("c_no_accident") == "1":
                miss.append("表6.2-1 已有承攬事故，不得同時聲明近五年零事故")
            unlinked = _count(conn, """SELECT COUNT(*) FROM contractor_incident
                WHERE site_id=? AND (linked_incident_id IS NULL OR linked_incident_id='')""", (site_id,))
            if unlinked:
                miss.append("表6.2-1 有暫存事故未關聯表11.2-1，送出前須補齊")
        elif flags.get("c_no_accident") != "1":
            miss.append("表6.2-1 請登錄承攬事故，或註明近五年零事故")
        return miss
    if n == 7:
        records = fil.list_rows(conn, site_id, "7.1")
        scopes = {str(r.get("equipment_id") or ""): r for r in fil.list_rows(conn, site_id, "7.0")}
        no_case = flags.get("pssr_na") == "1"
        if no_case:
            if not (flags.get("pssr_na_reason") or "").strip():
                miss.append("7.1 聲明本次無適用案件須填理由")
            if records or any(str(r.get("applicable")) == "1" for r in scopes.values()):
                miss.append("7.1 已有適用設備或檢查紀錄，不得同時聲明無適用案件")
        equipment_ids = {r[0] for r in conn.execute("SELECT equipment_id FROM equipment WHERE site_id=?", (site_id,))}
        for eid in sorted(equipment_ids):
            scope = scopes.get(eid)
            if not scope:
                miss.append(f"7.1 設備 {eid} 尚未確認 PSSR 適用性")
            elif str(scope.get("applicable")) == "0" and not str(scope.get("reason") or "").strip():
                miss.append(f"7.1 設備 {eid} 不適用須填理由")
            elif no_case and str(scope.get("applicable")) != "0":
                miss.append(f"7.1 設備 {eid} 已聲明無適用案件，逐台判定須為不適用")
            elif str(scope.get("applicable")) == "1" and not any(r.get("equipment_id") == eid and str(r.get("when") or "").strip() for r in records):
                miss.append(f"表7.1-1 設備 {eid} 須有檢查執行紀錄")
        for record in records:
            eid = str(record.get("equipment_id") or "")
            if eid not in equipment_ids or (eid in scopes and str(scopes[eid].get("applicable")) != "1"):
                miss.append(f"表7.1-1 設備 {eid or '未填'} 的檢查紀錄與適用性不一致")
            if str(record.get("rec") or "").strip() not in ("", "無") and (not str(record.get("due") or "").strip() or not str(record.get("track") or "").strip()):
                miss.append(f"表7.1-1 設備 {eid} 的改善建議須填預定日期與追蹤結果")
        return miss
    if n == 8:
        equipment_ids = {
            r[0] for r in conn.execute(
                "SELECT equipment_id FROM equipment WHERE site_id=?", (site_id,)
            )
        }
        screens = {
            r["equipment_id"]: r for r in conn.execute(
                """SELECT s.* FROM mi_screen s JOIN equipment e ON e.equipment_id=s.equipment_id
                   WHERE e.site_id=?""", (site_id,)
            )
        }
        unscreened = sorted(equipment_ids - screens.keys())
        if unscreened:
            miss.append(f"表8.1-1 請逐台確認安全關鍵性（未篩選：{'、'.join(unscreened)}）")
        critical_ids = {eid for eid, screen in screens.items() if screen["is_critical"]}
        if flags.get("no_critical") == "1":
            if not (flags.get("no_critical_reason") or "").strip():
                miss.append("聲明無安全關鍵設備須填理由")
            if critical_ids or _count(conn, """SELECT COUNT(*) FROM mi_inspection_detail d
                JOIN equipment e ON e.equipment_id=d.equipment_id WHERE e.site_id=?""", (site_id,)):
                miss.append("已聲明無安全關鍵設備，但表8.1-1仍有安全關鍵設備")
            if _count(conn, """SELECT COUNT(*) FROM mi_failure_gap g JOIN equipment e
                ON e.equipment_id=g.equipment_id WHERE e.site_id=?""", (site_id,)):
                miss.append("已聲明無安全關鍵設備，但仍有 8.2 資料不足紀錄")
            return miss
        details: dict[str, list[sqlite3.Row]] = {}
        for detail in conn.execute(
            """SELECT d.* FROM mi_inspection_detail d JOIN equipment e
               ON e.equipment_id=d.equipment_id WHERE e.site_id=?""", (site_id,)
        ):
            details.setdefault(detail["equipment_id"], []).append(detail)
        for eid in sorted(details.keys() - critical_ids):
            miss.append(f"表8.1-1 設備 {eid} 有檢查明細，但未判定為安全關鍵")
        if not critical_ids:
            miss.append("表8.1-1 請篩選安全關鍵設備；若皆否，請聲明並說明原因")
        for eid in sorted(critical_ids):
            if not screens[eid]["mi_type_confirmed"] or screens[eid]["mi_type"] not in fil.MI_SIX:
                miss.append(f"表8.1-1 設備 {eid} 須確認六大類分類")
            if eid not in details:
                miss.append(f"表8.1-1 設備 {eid} 判定為安全關鍵，須補損壞機制與檢查測試資料")
            else:
                for detail in details[eid]:
                    if not detail["confirmed"] or not all(str(detail[k] or "").strip() for k in
                        ("inspect_method", "inspect_frequency", "procedure_ref", "pid_drawing_no")):
                        miss.append(f"表8.1-1 設備 {eid} 檢查項目 {detail['detail_id']} 須逐項確認方式、頻率、程序書與 P&ID")
                    if bool(str(detail["damage_mechanism"] or "").strip()) == bool(str(detail["inspection_item"] or "").strip()):
                        miss.append(f"表8.1-1 設備 {eid} 檢查項目 {detail['detail_id']} 須擇一填損壞機制或功能檢查項目")
                    if "," in (detail["damage_mechanism"] or "") or "，" in (detail["damage_mechanism"] or ""):
                        miss.append(f"表8.1-1 設備 {eid} 檢查項目 {detail['detail_id']} 含多個損壞機制，須分列確認")
                    eq_pid = conn.execute(
                        """SELECT 1 FROM pid_drawing p JOIN equipment e ON e.process_id=p.process_id
                           WHERE e.equipment_id=? AND p.drawing_no=?""",
                        (eid, detail["pid_drawing_no"]),
                    ).fetchone()
                    if not eq_pid:
                        miss.append(f"表8.1-1 設備 {eid} 檢查項目 {detail['detail_id']} 的 P&ID 須屬該製程")
        failures = {r["equipment_id"]: r for r in conn.execute(
            """SELECT f.* FROM mi_failure f JOIN equipment e ON e.equipment_id=f.equipment_id
               WHERE e.site_id=?""", (site_id,)
        )}
        data_gaps = {r["equipment_id"]: r for r in conn.execute(
            """SELECT g.* FROM mi_failure_gap g JOIN equipment e ON e.equipment_id=g.equipment_id
               WHERE e.site_id=?""", (site_id,)
        )}
        for eid in sorted(critical_ids):
            row = failures.get(eid)
            if row and eid in data_gaps:
                miss.append(f"表8.2-1 設備 {eid} 同時有失效率數值與資料不足紀錄，須擇一確認")
            if not row:
                gap = data_gaps.get(eid)
                if gap:
                    try:
                        valid_gap = date.fromisoformat(gap["period_start"]) <= date.fromisoformat(gap["period_end"])
                    except ValueError:
                        valid_gap = False
                    if valid_gap and str(gap["reason"] or "").strip():
                        miss.append(f"表8.2-1 設備 {eid} 資料不足已註明原因，待人工確認；不計算失效率")
                    else:
                        miss.append(f"表8.2-1 設備 {eid} 資料不足須填有效統計期間與原因")
                else:
                    miss.append(f"表8.2-1 設備 {eid} 須填統計期間、運行時間及失效次數，或註明資料不足原因")
                continue
            try:
                hours = float(row["run_hours"])
                count = float(row["failure_count"])
                valid = isfinite(hours) and isfinite(count) and hours >= 0 and count >= 0 and count.is_integer()
            except (TypeError, ValueError):
                valid = False
                hours = -1
            try:
                valid_period = date.fromisoformat(str(row["period_start"] or "")) <= date.fromisoformat(str(row["period_end"] or ""))
            except ValueError:
                valid_period = False
            if not valid or not valid_period:
                miss.append(f"表8.2-1 設備 {eid} 須填有效的統計期間、運行時間與失效事件數")
            elif not row["confirmed"]:
                miss.append(f"表8.2-1 設備 {eid} 的舊統計資料須重新確認")
            elif hours == 0 and not str(row["note"] or "").strip():
                miss.append(f"表8.2-1 設備 {eid} 運行時間為 0 須註明原因")
        return miss
    if n == 9:
        n_zone = _count(
            conn,
            """SELECT COUNT(*) FROM hotwork_zone z
               JOIN area a ON a.area_code=z.area_code WHERE a.site_id=?""",
            (site_id,),
        )
        if n_zone < 1:
            miss.append("表9.1-1 請列舉動火管制區域及防護原因；不得以無動火跳過")
        return miss
    if n == 10:
        cases = fil.list_rows(conn, site_id, "10.1")
        if flags.get("moc_none") not in ("是", "否"):
            miss.append("請確認本次是否為全部新建、尚無變更案件")
        if flags.get("moc_none") == "是":
            if cases:
                miss.append("已聲明全部新建、尚無變更案件，不得同時列變更執行紀錄")
            return miss
        if flags.get("moc_def") not in ("是", "否"):
            miss.append("請回答程序是否已含製程修改定義")
        if cases and flags.get("moc_no_case") == "1":
            miss.append("已有變更執行紀錄，不得同時聲明尚無案件")
        if not cases and flags.get("moc_no_case") != "1":
            miss.append("至少一列變更紀錄，或註明尚無案件")
        ids = [str(case.get("change_id") or "").strip() for case in cases]
        if len(ids) != len(set(ids)) or any(not key for key in ids):
            miss.append("表10.1-2 每件變更須有不重複的管理項次")
        for case in cases:
            label = str(case.get("change_id") or case.get("name") or case["row_id"])
            process_ids = case.get("process_ids")
            equipment_ids = case.get("equipment_ids")
            chemical_refs = case.get("chemical_refs")
            if not isinstance(process_ids, list) or not process_ids or not isinstance(equipment_ids, list) or not isinstance(chemical_refs, list):
                miss.append(f"表10.1-2 {label} 的舊式單一關聯須重新確認實際變更範圍")
                continue
            valid = True
            for pid in process_ids:
                if not conn.execute("SELECT 1 FROM process WHERE process_id=? AND site_id=?", (pid, site_id)).fetchone():
                    valid = False
            for eid in equipment_ids:
                row = conn.execute("SELECT process_id FROM equipment WHERE equipment_id=? AND site_id=?", (eid, site_id)).fetchone()
                if not row or row["process_id"] not in process_ids:
                    valid = False
            for ref in chemical_refs:
                parts = str(ref).split("|", 2)
                if len(parts) != 3 or parts[1] not in process_ids or not conn.execute(
                    "SELECT 1 FROM chemical WHERE cas=? AND process_id=? AND sds_id=?",
                    (parts[0], parts[1], parts[2]),
                ).fetchone():
                    valid = False
            if not valid:
                miss.append(f"表10.1-2 {label} 的製程、設備或化學品關聯須屬本場所及所選製程")
        return miss
    if n == 11:
        has_incidents = bool(conn.execute("SELECT 1 FROM incident WHERE site_id=?", (site_id,)).fetchone())
        if not has_incidents and flags.get("inc_zero") != "1":
            miss.append("表11.2-1 請有列或註明近五年 0 件")
        if has_incidents and flags.get("inc_zero") == "1":
            miss.append("表11.2-1 已有事故，不得同時聲明近五年 0 件")
        return miss
    if n == 12:
        scenarios = fil.list_rows(conn, site_id, "12.1s")
        if not scenarios:
            miss.append("表12.1-1 至少一列緊急狀況")
        for row in scenarios:
            label = str(row.get("situation") or "未命名情境")
            process_ids = row.get("process_ids")
            equipment_ids = row.get("equipment_ids")
            chemical_refs = row.get("chemical_refs")
            area_codes = row.get("area_codes")
            if (not isinstance(process_ids, list) or not process_ids or
                    not isinstance(equipment_ids, list) or
                    not isinstance(chemical_refs, list) or
                    not isinstance(area_codes, list) or not area_codes):
                miss.append(f"表12.1-1「{label}」須重新確認相關製程、設備、化學品與區域範圍")
                continue
            if not str(row.get("description") or "").strip():
                miss.append(f"表12.1-1「{label}」須填狀況原因與說明")
            for pid in process_ids:
                if not conn.execute("SELECT 1 FROM process WHERE process_id=? AND site_id=?", (pid, site_id)).fetchone():
                    miss.append(f"表12.1-1「{label}」含無效製程 {pid}")
            for eid in equipment_ids:
                eq = conn.execute("SELECT process_id FROM equipment WHERE equipment_id=? AND site_id=?", (eid, site_id)).fetchone()
                if not eq or eq["process_id"] not in process_ids:
                    miss.append(f"表12.1-1「{label}」含不屬已選製程的設備 {eid}")
            for ref in chemical_refs:
                parts = str(ref).split("|", 2)
                if len(parts) != 3 or parts[0] not in process_ids or not conn.execute(
                    "SELECT 1 FROM chemical WHERE process_id=? AND COALESCE(sds_id,'')=? AND cas=?", parts
                ).fetchone():
                    miss.append(f"表12.1-1「{label}」含無效化學品關聯 {ref}")
            for area_code in area_codes:
                if not conn.execute("SELECT 1 FROM area WHERE area_code=? AND site_id=?", (area_code, site_id)).fetchone():
                    miss.append(f"表12.1-1「{label}」含無效區域 {area_code}")
            if not equipment_ids and not str(row.get("no_equipment_reason") or "").strip():
                miss.append(f"表12.1-1「{label}」未選設備須說明原因")
            if not chemical_refs and not str(row.get("no_chemical_reason") or "").strip():
                miss.append(f"表12.1-1「{label}」未選化學品須說明原因")
            if not conn.execute("SELECT 1 FROM area WHERE area_code=? AND site_id=? AND is_assembly_point=1",
                                (str(row.get("muster") or ""), site_id)).fetchone():
                miss.append(f"表12.1-1「{label}」集合點須選已確認的緊急集合區")
            if not str(row.get("drill_plan_scope") or "").strip():
                miss.append(f"表12.1-1「{label}」須填演練計畫的涵蓋項目")
            drill_status = str(row.get("drill_status") or "").strip()
            if drill_status == "已執行":
                try:
                    date.fromisoformat(str(row.get("drill_date") or ""))
                except ValueError:
                    miss.append(f"表12.1-1「{label}」已執行演練須填有效日期")
                if not has_uploaded_file(str(row.get("drill_record_path") or "")):
                    miss.append(f"表12.1-1「{label}」已執行演練須上傳對應紀錄")
            elif drill_status == "尚未執行":
                try:
                    date.fromisoformat(str(row.get("drill_due") or ""))
                except ValueError:
                    miss.append(f"表12.1-1「{label}」尚未執行演練須填預定日期")
                if not str(row.get("drill_no_reason") or "").strip():
                    miss.append(f"表12.1-1「{label}」尚未執行演練須填原因")
                miss.append(f"表12.1-1「{label}」演練尚未執行，待人工確認")
            else:
                miss.append(f"表12.1-1「{label}」須確認演練執行狀態")
        gear = fil.list_rows(conn, site_id, "12.2")
        if not gear:
            miss.append("表12.2-1 請列搶救設備與器材、區域、數量、單位及檢點頻率")
        for row in gear:
            try:
                quantity = Decimal(str(row.get("qty") or ""))
            except InvalidOperation:
                quantity = Decimal(0)
            if (not quantity.is_finite() or quantity <= 0 or
                    not str(row.get("unit") or "").strip() or
                    not str(row.get("freq") or "").strip()):
                miss.append(f"表12.2-1「{row.get('name') or '未命名器材'}」須填正數數量、單位與檢點頻率")
        return miss
    if n == 13:
        plans = fil.list_rows(conn, site_id, "13.1")
        followups = fil.list_rows(conn, site_id, "13.2")
        if flags.get("audit_first") == "是":
            if plans or followups:
                miss.append("第13章已聲明尚未執行首次稽核，但仍有稽核計畫或改善紀錄")
            return miss
        if flags.get("audit_first") != "否":
            miss.append("請回答是否尚未執行首次稽核")
        if not plans:
            miss.append("表13.1-1 至少一列稽核計畫")
        for plan in plans:
            if not all(str(plan.get(key) or "").strip() for key in ("when", "dept_id", "unit", "auditor")):
                miss.append("表13.1-1 每列須填稽核時間、受稽核部門、PSM 單元與稽核員")
            elif not conn.execute("SELECT 1 FROM department WHERE dept_id=? AND site_id=?",
                                  (plan["dept_id"], site_id)).fetchone():
                miss.append(f"表13.1-1 受稽核部門 {plan['dept_id']} 不屬本場所")
        if followups and flags.get("audit_zero") == "1":
            miss.append("表13.2-1 已有改善事項，不得同時聲明無不符合")
        plan_times = {str(p.get("when") or "") for p in plans}
        for row in followups:
            finding = str(row.get("finding") or "未命名改善事項")
            if str(row.get("plan_when") or "") not in plan_times:
                miss.append(f"表13.2-1「{finding}」須引用表13.1-1 既有稽核項次")
            if not all(str(row.get(key) or "").strip() for key in ("finding", "action", "dept_id", "due")):
                miss.append(f"表13.2-1「{finding}」須填事項、措施、負責部門及預定完成日期")
        return miss
    if n == 14:
        paths = conn.execute(
            "SELECT attachment_path, note FROM unstructured_attachment WHERE site_id=? AND kind='trade_secret'",
            (site_id,),
        )
        if not any(has_uploaded_file(r["attachment_path"]) and "示範草稿" not in (r["note"] or "") for r in paths):
            miss.append("請上傳核准的商業機密管理程序書；示範草稿不可作正式佐證")
        return miss
    return []


def step_missing(conn: sqlite3.Connection, site_id: str, n: int) -> list[str]:
    missing = _step_missing_core(conn, site_id, n)
    if _site(conn, site_id):
        missing.extend(document_gaps(conn, site_id, n))
    return missing


def step_done(conn: sqlite3.Connection, site_id: str, n: int) -> bool:
    return not step_missing(conn, site_id, n)


def core_missing(conn: sqlite3.Connection, site_id: str) -> list[str]:
    """V8.3 的章節入口只依第一章核心清單，不依其他章完成率。"""
    site = _site(conn, site_id)
    if not site:
        return ["請先建立場所"]
    checks = (
        ("department", "部門"),
        ("process", "製程"),
        ("equipment", "設備"),
        ("area", "區域與位置圖"),
    )
    missing = [
        f"請先建立{label}"
        for table, label in checks
        if _count(conn, f"SELECT COUNT(*) FROM {table} WHERE site_id=?", (site_id,)) == 0
    ]
    chemicals = _count(
        conn,
        """SELECT COUNT(*) FROM chemical c JOIN process p ON p.process_id=c.process_id
           WHERE p.site_id=?""",
        (site_id,),
    )
    if not chemicals:
        missing.append("請先建立化學品清單")
    elif conn.execute(
        """SELECT 1 FROM chemical c JOIN process p ON p.process_id=c.process_id
           WHERE p.site_id=? AND (c.sds_id IS NULL OR c.sds_id='') LIMIT 1""",
        (site_id,),
    ).fetchone():
        missing.append("化學品清單仍有未連結 SDS 的列")
    return missing


def unlocked_step(conn: sqlite3.Connection, site_id: str) -> int:
    if core_missing(conn, site_id):
        return 1
    for n in range(1, N_STEPS + 1):
        if not step_done(conn, site_id, n):
            return n
    return N_STEPS


def step_info(n: int) -> dict:
    return next(s for s in STEPS if s["n"] == n)


def counts(conn: sqlite3.Connection, site_id: str) -> dict:
    return {
        "departments": _count(conn, "SELECT COUNT(*) FROM department WHERE site_id=?", (site_id,)),
        "processes": _count(conn, "SELECT COUNT(*) FROM process WHERE site_id=?", (site_id,)),
        "areas": _count(conn, "SELECT COUNT(*) FROM area WHERE site_id=?", (site_id,)),
        "equipment": _count(conn, "SELECT COUNT(*) FROM equipment WHERE site_id=?", (site_id,)),
        "chemicals": _count(
            conn,
            """SELECT COUNT(*) FROM chemical c JOIN process p ON p.process_id=c.process_id
               WHERE p.site_id=?""",
            (site_id,),
        ),
        "pid": _count(
            conn,
            """SELECT COUNT(*) FROM pid_drawing d JOIN process p ON p.process_id=d.process_id
               WHERE p.site_id=?""",
            (site_id,),
        ),
    }


def page_extra(conn: sqlite3.Connection, site_id: str, step: int) -> dict:
    flags = fil.all_flags(conn, site_id)
    by_sec = fil.rows_by_section(conn, site_id)
    by_sec["11.2"] = [
        {
            **dict(r), "when": r["incident_date"],
            "incident_type": "虛驚" if r["is_near_miss"] else "職業災害",
            "traits": r["characteristics"],
        }
        for r in conn.execute(
            "SELECT * FROM incident WHERE site_id=? ORDER BY incident_date, incident_id", (site_id,)
        )
    ]
    if "mix" in by_sec:
        phase_by = {
            (r["cas"], r["process_id"]): r["phase_state"] or ""
            for r in conn.execute(
                """SELECT c.cas, c.process_id, COALESCE(c.phase_state, '') AS phase_state
                   FROM chemical c JOIN process p ON p.process_id=c.process_id
                   WHERE p.site_id=?""",
                (site_id,),
            )
        }
        refreshed = []
        for raw in by_sec["mix"]:
            row = dict(raw)
            if not str(row.get("phase_state") or "").strip():
                row["phase_state"] = phase_by.get((row.get("cas"), row.get("process_id")), "")
            refreshed.append(fil.attach_annex_check(row))
        by_sec["mix"] = refreshed
    sops = [
        dict(r)
        for r in conn.execute(
            """SELECT s.*, e.equipment_type, e.name AS equipment_name
               FROM sop s
               JOIN process p ON p.process_id=s.process_id
               LEFT JOIN equipment e ON e.equipment_id=s.equipment_id
               WHERE p.site_id=? ORDER BY s.sop_id""",
            (site_id,),
        )
    ]
    courses = [
        dict(r)
        for r in conn.execute(
            """SELECT t.* FROM training_course t JOIN process p ON p.process_id=t.process_id
               WHERE p.site_id=? ORDER BY t.course_id""",
            (site_id,),
        )
    ]
    contents = [
        dict(r)
        for r in conn.execute(
            """SELECT ec.* FROM equipment_content ec
               JOIN equipment e ON e.equipment_id=ec.equipment_id
               WHERE e.site_id=?""",
            (site_id,),
        )
    ]
    pha_uploads = [
        {**dict(r), "is_uploaded": has_uploaded_file(r["attachment_path"])}
        for r in conn.execute(
            """SELECT u.* FROM unstructured_attachment u
               LEFT JOIN process p ON p.process_id=u.process_id
               WHERE u.kind='pha' AND (u.site_id=? OR p.site_id=?)
                 AND NOT EXISTS (SELECT 1 FROM pha_record r WHERE r.attachment_id=u.attachment_id)
               ORDER BY u.attachment_id""",
            (site_id, site_id),
        )
    ]
    for sop in sops:
        linked = conn.execute("""SELECT se.equipment_id,se.confirmed,e.name,e.equipment_type
            FROM sop_equipment se JOIN equipment e ON e.equipment_id=se.equipment_id
            WHERE se.sop_id=? ORDER BY e.equipment_id""", (sop["sop_id"],)).fetchall()
        sop["equipment_ids"] = [r["equipment_id"] for r in linked]
        sop["equipment_refs"] = "、".join(f"{r['equipment_id']} {r['name']}" for r in linked)
        sop["equipment_types"] = "、".join(dict.fromkeys(r["equipment_type"] for r in linked))
        sop["scope_confirmed"] = bool(linked) and all(r["confirmed"] for r in linked)
    pha_records = [
        {**dict(r), "is_uploaded": has_uploaded_file(r["attachment_path"])}
        for r in conn.execute(
            """SELECT r.*, u.original_name, u.attachment_path FROM pha_record r
               JOIN unstructured_attachment u ON u.attachment_id=r.attachment_id
               WHERE r.site_id=? ORDER BY r.record_id""", (site_id,)
        )
    ]
    limit_reviews = []
    limit_form_data = {}
    for e in conn.execute("SELECT equipment_id,process_id,name FROM equipment WHERE site_id=? ORDER BY equipment_id", (site_id,)):
        eid = e["equipment_id"]
        review = conn.execute("SELECT * FROM equipment_operating_review WHERE equipment_id=?", (eid,)).fetchone()
        existing_limits = list(conn.execute("SELECT * FROM equipment_limit WHERE equipment_id=?", (eid,)))
        selected = []
        if review:
            try:
                selected = json.loads(review["selected_parameters"] or "[]")
            except (TypeError, ValueError):
                selected = []
        limit_reviews.append({
            "equipment_id": eid, "name": e["name"],
            "selected": "、".join(selected) if isinstance(selected, list) else "資料待更正",
            "no_parameter_reason": review["no_parameter_reason"] if review else "",
            "batch": (f"{review['batch_quantity']:g} {review['batch_unit']}" if review and review["batch_quantity"] is not None
                      else review["batch_na_reason"] if review else ""),
            "content": "、".join(c["cas"] or c["sds_id"] for c in contents if c["equipment_id"] == eid and not c["no_process_chemical"]),
            "no_content_reason": review["no_content_reason"] if review else "",
            "reviewed": bool(review),
        })
        data = {
            "selected": (selected if isinstance(selected, list) else []) if review else
                        [row["parameter"] for row in existing_limits if row["parameter"] in LIMIT_PARAMETERS],
            "batch_qty": review["batch_quantity"] if review and review["batch_quantity"] is not None else "",
            "batch_unit": review["batch_unit"] if review else "",
            "batch_na_reason": review["batch_na_reason"] if review else "",
            "no_parameter_reason": review["no_parameter_reason"] if review else "",
            "no_content_reason": review["no_content_reason"] if review else "",
            "no_process_chemical": any(c["equipment_id"] == eid and c["no_process_chemical"] for c in contents),
            "cas": [f"{c['cas']}|{e['process_id']}|{c['sds_id']}" for c in contents
                    if c["equipment_id"] == eid and not c["no_process_chemical"]],
        }
        for row in existing_limits:
            prefix = {"壓力": "p_", "溫度": "t_", "流量": "f_", "組成": "c_"}.get(row["parameter"])
            if prefix:
                for key in ("design_high", "design_low", "safety_high", "safety_low",
                            "high_na_reason", "low_na_reason"):
                    data[prefix + key] = row[key] or ""
                data[prefix + "unit"] = row["unit"] or ""
                data["note"] = row["note"] or ""
            elif row["parameter"] == "容積":
                data["volume"] = row["design_high"] or ""
        limit_form_data[eid] = data
    course_sops: dict[str, list[str]] = {}
    for link in conn.execute("""SELECT l.course_id,l.sop_id FROM training_course_sop l
        JOIN training_course t ON t.course_id=l.course_id
        JOIN process p ON p.process_id=t.process_id WHERE p.site_id=? ORDER BY l.sop_id""", (site_id,)):
        course_sops.setdefault(link["course_id"], []).append(link["sop_id"])
    for course in courses:
        course["sop_ids"] = course_sops.get(course["course_id"], [])
    selected_methods = [x for x in (flags.get("pha_methods") or "").split(",") if x.strip()]
    esd_list = [
        dict(r)
        for r in conn.execute(
            """SELECT s.*, GROUP_CONCAT(a.equipment_id) AS action_ids
               FROM esd_scenario s
               JOIN process p ON p.process_id=s.process_id
               LEFT JOIN esd_action a ON a.scenario_id=s.scenario_id
               WHERE p.site_id=?
               GROUP BY s.scenario_id
               ORDER BY s.scenario_id""",
            (site_id,),
        )
    ]
    mi_uploads = [
        dict(r)
        for r in conn.execute(
            """SELECT u.* FROM unstructured_attachment u
               JOIN process p ON p.process_id=u.process_id
               WHERE p.site_id=? AND u.kind='mi'
               ORDER BY u.attachment_id""",
            (site_id,),
        )
    ]
    mi_screen_rows = [
        dict(r) for r in conn.execute(
            """SELECT e.equipment_id, e.name, e.equipment_type, e.process_id,
                      s.is_critical, s.basis, s.mi_type, s.mi_type_confirmed
               FROM equipment e LEFT JOIN mi_screen s ON s.equipment_id=e.equipment_id
               WHERE e.site_id=? ORDER BY e.process_id, e.equipment_id""",
            (site_id,),
        )
    ]
    mi_details = []
    for r in conn.execute(
        """SELECT d.*,e.name AS equipment_name,e.equipment_type,e.process_id,e.area_code,
                  s.mi_type,s.mi_type_confirmed
           FROM mi_inspection_detail d JOIN equipment e ON e.equipment_id=d.equipment_id
           JOIN mi_screen s ON s.equipment_id=d.equipment_id
           WHERE e.site_id=? ORDER BY e.process_id,e.equipment_id,d.detail_id""", (site_id,)
    ):
        detail = dict(r)
        bound = svc.material_for_mi(conn, r["equipment_id"])
        detail["material"] = bound["material"]
        detail["material_category"] = bound["material_category"]
        mi_details.append(detail)
    documents = [
        {**dict(r), "is_uploaded": has_uploaded_file(r["attachment_path"])}
        for r in conn.execute(
            "SELECT * FROM filing_document WHERE site_id=? ORDER BY document_no, revision_date",
            (site_id,),
        )
    ]
    document_refs = [
        dict(r) for r in conn.execute(
            """SELECT r.purpose, r.document_id, d.document_no, d.title, d.revision_date,
                      d.attachment_path FROM filing_document_ref r
               JOIN filing_document d ON d.document_id=r.document_id
               WHERE r.site_id=? AND r.step=? AND d.site_id=?
               ORDER BY r.purpose, d.document_no""",
            (site_id, step, site_id),
        )
    ]
    gear_totals: dict[tuple[str, str], Decimal] = {}
    for row in by_sec.get("12.2") or []:
        name, unit = str(row.get("name") or "").strip(), str(row.get("unit") or "").strip()
        if not name or not unit:
            continue
        try:
            quantity = Decimal(str(row.get("qty") or ""))
        except InvalidOperation:
            continue
        if quantity <= 0:
            continue
        gear_totals[(name, unit)] = gear_totals.get((name, unit), Decimal(0)) + quantity
    return {
        "flags": flags,
        "rows": by_sec,
        "sops": sops,
        "courses": courses,
        "contents": contents,
        "limit_reviews": limit_reviews,
        "limit_form_data": limit_form_data,
        "pha_uploads": pha_uploads,
        "pha_records": pha_records,
        "pha_methods": fil.PHA_METHODS,
        "selected_methods": selected_methods,
        "labor_items": fil.LABOR_ITEMS,
        "labor_grid": fil.labor_grid(conn, site_id),
        "mi_six": fil.MI_SIX,
        "mi_fail_grid": fil.mi_fail_grid(conn, site_id),
        "mi_failure_gaps": [dict(r) for r in conn.execute(
            """SELECT g.*,e.name AS equipment_name FROM mi_failure_gap g
               JOIN equipment e ON e.equipment_id=g.equipment_id
               WHERE e.site_id=? ORDER BY g.equipment_id""", (site_id,)
        )],
        "mi_legacy_fail_rows": fil.list_rows(conn, site_id, "8.2-legacy"),
        "mi_category_rates": [dict(r) for r in conn.execute(
            """SELECT s.mi_type,SUM(f.failure_count) AS failures,SUM(f.run_hours) AS hours,
               SUM(f.failure_count)*1000000.0/SUM(f.run_hours) AS rate
               FROM mi_failure f JOIN mi_screen s ON s.equipment_id=f.equipment_id
               JOIN equipment e ON e.equipment_id=f.equipment_id
               WHERE e.site_id=? AND s.is_critical=1 AND s.mi_type_confirmed=1
               AND f.confirmed=1 AND f.run_hours>0
               GROUP BY s.mi_type ORDER BY s.mi_type""", (site_id,)
        )],
        "mi_uploads": mi_uploads,
        "mi_screen_rows": mi_screen_rows,
        "mi_details": mi_details,
        "mi_detail_equipment": list({d["equipment_id"]: d for d in mi_details
            if d["confirmed"] and any(s["equipment_id"] == d["equipment_id"] and s["is_critical"] == 1
                                     for s in mi_screen_rows)}.values()),
        "documents": documents,
        "document_refs": document_refs,
        "document_requirements": document_requirements(conn, site_id, step),
        "gear_totals": [
            {"name": name, "unit": unit, "quantity": format(total.normalize(), "f")}
            for (name, unit), total in sorted(gear_totals.items())
        ],
        "reaction_types": fil.REACTION_TYPES,
        "damage_mechs": fil.DAMAGE_MECHS,
        "inspect_methods": fil.INSPECT_METHODS,
        "vent_types": fil.VENT_TYPES,
        "vent_levels": fil.VENT_LEVELS,
        "vent_avail": fil.VENT_AVAIL,
        "leak_levels": fil.LEAK_LEVELS,
        "zone_levels": fil.ZONE_LEVELS,
        "ratio_bases": fil.RATIO_BASES,
        "phases": fil.PHASES,
        "special_chem": fil.SPECIAL_CHEM_REF,
        "esd_list": esd_list,
        "block_n": list(range(1, 16)),
        "yn6": fil.YN6,
        "yn9": fil.YN9,
        "yn11": fil.YN11,
        "yn11_help": fil.YN11_HELP,
        "yn12": fil.YN12,
        "yn14": fil.YN14,
        "incident_types": ("職業災害", "虛驚"),
        "site_incidents": [
            dict(r)
            for r in conn.execute(
                """SELECT incident_id, incident_date, summary FROM incident
                   WHERE site_id=? ORDER BY incident_date, incident_id""",
                (site_id,),
            )
        ],
        "contractors": [
            dict(r) for r in conn.execute(
                "SELECT * FROM contractor WHERE site_id=? ORDER BY contractor_id", (site_id,)
            )
        ],
        "contractor_incidents": [
            dict(r)
            for r in conn.execute(
                """SELECT i.* FROM contractor_incident i
                   WHERE i.site_id=? ORDER BY i.occur_date, i.incident_id""",
                (site_id,),
            )
        ],
        "hotwork_zones": [
            dict(r)
            for r in conn.execute(
                """SELECT z.*, a.name AS area_name, a.site_id
                   FROM hotwork_zone z JOIN area a ON a.area_code=z.area_code
                   WHERE a.site_id=? ORDER BY z.area_code""",
                (site_id,),
            )
        ],
        "phys_opts": fil.PHYS_OPTS,
        "health_opts": fil.HEALTH_OPTS,
        "unit_titles": UNIT_TITLES,
        "annex_merge": fil.merge_annex_qty(by_sec.get("mix") or []),
        "annex_catalog": fil.annex_catalog(),
        "chem_104": (
            chem_104 := fil.chem_104_rows(
                [
                    dict(r)
                    for r in conn.execute(
                        """SELECT c.* FROM chemical c
                           JOIN process p ON p.process_id=c.process_id
                           WHERE p.site_id=? ORDER BY c.cas, c.process_id""",
                        (site_id,),
                    )
                ],
                by_sec.get("mix") or [],
            )
        ),
        "chem_groups": fil.group_chem_104(chem_104),
        "assembly_areas": [
            dict(r)
            for r in conn.execute(
                """SELECT area_code, name FROM area
                   WHERE site_id=? AND is_assembly_point=1 ORDER BY area_code""",
                (site_id,),
            )
        ],
    }


def _flag(conn, sid, k, v):
    fil.set_flag(conn, sid, k, v)


_DEMO_PHASE = {
    "7664-39-3": "氣態",
    "1310-73-2": "液態",
}


def _stamp_demo_phase(conn, sid: str) -> None:
    rows = conn.execute(
        """SELECT c.cas, c.process_id, c.sds_id, COALESCE(c.phase_state, '') AS phase_state
           FROM chemical c JOIN process p ON p.process_id=c.process_id
           WHERE p.site_id=?""",
        (sid,),
    ).fetchall()
    for row in rows:
        phase = _DEMO_PHASE.get(row["cas"])
        if phase and not (row["phase_state"] or "").strip():
            conn.execute(
                """UPDATE chemical SET phase_state=?
                   WHERE cas=? AND process_id=? AND sds_id=?""",
                (phase, row["cas"], row["process_id"], row["sds_id"]),
            )
    conn.commit()
    for item in fil.list_rows(conn, sid, "mix"):
        phase = _DEMO_PHASE.get(str(item.get("cas") or ""))
        if phase and not str(item.get("phase_state") or "").strip():
            item["phase_state"] = phase
            if item.get("cas") == "1310-73-2":
                item["is_aqueous"] = "1"
            fil.update_payload(conn, int(item["row_id"]), item)


def _row_once(conn, sid, section, payload, key=None):
    if key:
        if fil.has_row_matching(conn, sid, section, key, payload.get(key)):
            return
    elif fil.list_rows(conn, sid, section):
        return
    fil.add_row(conn, sid, section, payload)


def apply_step_defaults(conn: sqlite3.Connection, site_id: str, n: int) -> str:
    sid = site_id
    date = PREFILL["doc_date"]
    base = PREFILL["assessment_base_date"]
    if n == 1:
        svc.save_site(
            conn,
            {
                "site_id": sid,
                "company_name": PREFILL["company_name"],
                "site_name": PREFILL["site_name"],
                "scope": PREFILL["scope"],
                "applicant_name": PREFILL["applicant_name"],
                "assessment_base_date": base,
                "worker_count": PREFILL["worker_count"],
                "declare_no_equipment_types": PREFILL["declare_no_equipment_types"],
                "declare_no_contractor": False,
                "declare_no_hotwork": False,
                "declare_no_incident_5y": True,
            },
        )
        svc.save_department(conn, {"dept_id": "D-OPS", "site_id": sid, "name": "操作課", "headcount": 8})
        svc.save_department(conn, {"dept_id": "D-MAINT", "site_id": sid, "name": "保養課", "headcount": 4})
        for row in (
            {
                "process_id": "P-TANK",
                "name": "氣態 HF 供料",
                "mode": "continuous",
                "has_overpressure": True,
                "is_loading": False,
                "is_downstream": False,
            },
            {
                "process_id": "P-LOAD",
                "name": "無水 HF 密閉接收",
                "mode": "batch",
                "has_overpressure": False,
                "is_loading": True,
                "is_downstream": False,
            },
            {
                "process_id": "P-SCRUB",
                "name": "含氟尾氣鹼洗",
                "mode": "continuous",
                "has_overpressure": False,
                "is_loading": False,
                "is_downstream": True,
                "has_chemical_reaction": True,
            },
            {
                "process_id": "P-ACID",
                "name": "鹼液輸送",
                "mode": "continuous",
                "has_overpressure": False,
                "is_loading": False,
                "is_downstream": False,
            },
        ):
            row.setdefault("has_chemical_reaction", False)
            row["overview"] = PROCESS_OVERVIEWS.get(row["process_id"], "")
            row.update(
                {
                    "site_id": sid,
                    "operating_dept_id": "D-OPS",
                    "is_special": False,
                }
            )
            svc.save_process(conn, row)
        svc.save_area(
            conn,
            {
                "area_code": "AREA-A",
                "site_id": sid,
                "name": "HF 供料區",
                "drawing_no": "PLOT-001",
                "revision": "A",
                "issue_date": "2025-12-01",
                "process_id": "P-TANK",
                "attachment_path": "placeholder://PLOT-001-A",
                "is_assembly_point": False,
                "is_control_room": True,
                "is_fire_system": True,
                "worker_count": 8,
                "contractor_count": 4,
            },
        )
        svc.save_area(
            conn,
            {
                "area_code": "AREA-B",
                "site_id": sid,
                "name": "無水 HF 接收區",
                "drawing_no": "PLOT-001",
                "revision": "A",
                "issue_date": "2025-12-01",
                "process_id": "P-LOAD",
                "attachment_path": "placeholder://PLOT-001-A",
                "is_assembly_point": False,
                "worker_count": 4,
                "contractor_count": 2,
            },
        )
        svc.save_area(
            conn,
            {
                "area_code": "AREA-M",
                "site_id": sid,
                "name": "廠界上風側集合點（依當日風向調整）",
                "drawing_no": "PLOT-001",
                "revision": "A",
                "issue_date": "2025-12-01",
                "attachment_path": "placeholder://PLOT-001-A",
                "is_assembly_point": True,
            },
        )
        svc.save_area(
            conn,
            {
                "area_code": "AREA-S",
                "site_id": sid,
                "name": "廠界備援集合點（依風向啟用）",
                "drawing_no": "PLOT-001",
                "revision": "A",
                "issue_date": "2025-12-01",
                "attachment_path": "placeholder://PLOT-001-A",
                "is_assembly_point": True,
            },
        )
        for row in (
            {
                "equipment_id": "T-101",
                "name": "氣態 HF 緩衝槽",
                "equipment_type": "壓力容器與儲槽",
                "process_id": "P-TANK",
                "area_code": "AREA-A",
                "material": "材質待依設備資料表與供應商相容性確認",
                "phase_class": "氣體",
                "legal_cert_type": "危險性設備檢查合格證 DEMO-PV-001",
                "is_regulated_machinery": True,
            },
            {
                "equipment_id": "P-101",
                "name": "HF 供氣壓送機",
                "equipment_type": "動力來源",
                "power_kind": "其他",
                "process_id": "P-TANK",
                "area_code": "AREA-A",
                "material": "材質待核對",
                "phase_class": "氣體",
            },
            {
                "equipment_id": "PSV-101",
                "name": "安全閥",
                "equipment_type": "釋放及排放系統",
                "process_id": "P-TANK",
                "area_code": "AREA-A",
                "material": "材質待核對",
                "phase_class": "氣體",
            },
            {
                "equipment_id": "ESD-101",
                "name": "緊急停車系統",
                "equipment_type": "緊急停車系統",
                "process_id": "P-TANK",
                "area_code": "AREA-A",
                "phase_class": "氣體",
            },
            {
                "equipment_id": "LA-101",
                "name": "無水 HF 密閉卸收接頭",
                "equipment_type": "裝卸及輸送",
                "process_id": "P-LOAD",
                "area_code": "AREA-B",
                "material": "材質待核對",
            },
            {
                "equipment_id": "V-101",
                "name": "無水 HF 汽化模組",
                "equipment_type": "壓力容器與儲槽",
                "phase_class": "液體",
                "process_id": "P-LOAD",
                "area_code": "AREA-B",
                "material": "材質待核對",
            },
            {
                "equipment_id": "S-201",
                "name": "洗滌塔",
                "equipment_type": "釋放及排放系統",
                "phase_class": "後段處理",
                "process_id": "P-SCRUB",
                "area_code": "AREA-A",
                "material": "FRP",
            },
            {
                "equipment_id": "PL-201",
                "name": "鹼液輸送管線",
                "equipment_type": "管線系統",
                "process_id": "P-ACID",
                "area_code": "AREA-A",
                "material": "材質待核對",
            },
        ):
            row.setdefault("power_kind", None)
            row.setdefault("phase_class", "液體")
            row.setdefault("legal_cert_type", None)
            row.setdefault("is_regulated_machinery", False)
            row.setdefault("material_category", guess_material_category(row.get("material")))
            row.update(
                {
                    "site_id": sid,
                    "maint_dept_id": "D-MAINT",
                    "is_safety_critical": False,
                    "alias": None,
                }
            )
            svc.save_equipment(conn, row)
        ensure_sops_for_types(conn, sid)
        svc.save_sds(
            conn,
            {
                "sds_id": "SDS-HF-001",
                "site_id": sid,
                "substance_or_mixture_name": "無水氟化氫",
                "file_path": "placeholder://SDS-HF-001.pdf",
                "component_cas_list": "7664-39-3",
            },
        )
        svc.save_sds(
            conn,
            {
                "sds_id": "SDS-NAOH-001",
                "site_id": sid,
                "substance_or_mixture_name": "10% 氫氧化鈉水溶液",
                "file_path": "placeholder://SDS-NAOH-001.pdf",
                "component_cas_list": "1310-73-2",
            },
        )
        for pid, phase in (("P-LOAD", "液態"), ("P-TANK", "氣態")):
            svc.save_chemical(
                conn,
                {
                    "cas": "7664-39-3",
                    "process_id": pid,
                    "name": "無水氟化氫",
                    "role": "原物料",
                    "un_number": "UN 1052",
                    "transport_hazard_class": "8（副危害 6.1）",
                    "concentration_range": "≥99%",
                    "sds_id": "SDS-HF-001",
                    "sds_file": "placeholder://SDS-HF-001.pdf",
                    "h_codes": "H314,H330",
                    "phase_state": phase,
                },
            )
        for pid in ("P-ACID", "P-SCRUB"):
            svc.save_chemical(
                conn,
                {
                    "cas": "1310-73-2",
                    "process_id": pid,
                    "name": "氫氧化鈉水溶液",
                    "role": "原物料",
                    "concentration_range": "10%",
                    "sds_id": "SDS-NAOH-001",
                    "sds_file": "placeholder://SDS-NAOH-001.pdf",
                    "h_codes": "H314",
                    "phase_state": "液態",
                },
            )
        hf_flags = fil.h_code_flags("H314,H330")
        naoh_flags = fil.h_code_flags("H314")
        for item in (
            {
                "cas": "7664-39-3", "process_id": "P-TANK",
                "name": "無水氟化氫", "name_en": "Hydrogen fluoride",
                "dept_id": "D-OPS", "max_kg": "1200", "monthly_kg": "6000",
                "area_code": "AREA-A", "regulation": "氣態 HF；示範操作量，依現場盤點確認",
                **{k: hf_flags[k] for k in ("is_danger", "is_harmful", "is_high_flammable", "is_high_toxic")},
            },
            {
                "cas": "1310-73-2", "process_id": "P-SCRUB",
                "name": "氫氧化鈉水溶液", "name_en": "Sodium hydroxide solution",
                "dept_id": "D-OPS", "max_kg": "5000", "monthly_kg": "1000",
                "area_code": "AREA-A", "regulation": "鹼洗吸收液，非本案例甲類數量來源",
                **{k: naoh_flags[k] for k in ("is_danger", "is_harmful", "is_high_flammable", "is_high_toxic")},
            },
        ):
            _row_once(conn, sid, "1.1", item, "cas")
        for item in (
            {
                "mix_name": "無水氟化氫（氣態供料）", "sds_id": "SDS-HF-001",
                "process_id": "P-TANK", "cas": "7664-39-3",
                "pct_lo": "99", "pct_hi": "100", "basis": "重量比",
                "total_kg": "1200", "is_aqueous": "0", "phase_state": "氣態",
                "formula": "最大在場操作量×重量百分比；氣態列入規定數量，數量須由現場盤點核對",
            },
            {
                "mix_name": "無水氟化氫（液態接收）", "sds_id": "SDS-HF-001",
                "process_id": "P-LOAD", "cas": "7664-39-3",
                "pct_lo": "99", "pct_hi": "100", "basis": "重量比",
                "total_kg": "2000", "is_aqueous": "0", "phase_state": "液態",
                "formula": "液態接收段另列；依手冊相態規則不計入氣態 HF 規定數量",
            },
            {
                "mix_name": "10% 氫氧化鈉水溶液（供液）", "sds_id": "SDS-NAOH-001",
                "process_id": "P-ACID", "cas": "1310-73-2",
                "pct_lo": "10", "pct_hi": "10", "basis": "重量比",
                "total_kg": "5000", "is_aqueous": "1", "phase_state": "液態",
                "formula": "操作量×重量百分比＝純物質公斤",
            },
            {
                "mix_name": "10% 氫氧化鈉水溶液（鹼洗）", "sds_id": "SDS-NAOH-001",
                "process_id": "P-SCRUB", "cas": "1310-73-2",
                "pct_lo": "10", "pct_hi": "10", "basis": "重量比",
                "total_kg": "5000", "is_aqueous": "1", "phase_state": "液態",
                "formula": "同一批吸收液在鹼洗段使用；不得與供液段重複加總",
            },
        ):
            _row_once(conn, sid, "mix", fil.attach_annex_check(item), "process_id")
        for item in (
            {
                "cas": "7664-39-3", "process_id": "P-TANK",
                "name": "無水氟化氫", "name_en": "Hydrogen fluoride",
                "conc": "99", "ctrl_qty": "1000", "state": "氣",
                "odor": "刺激性", "vp": "約 783 mmHg（20°C，NIOSH）",
                "bp": "約 19.4", "fp": "不適用", "expl": "不適用",
                "twa": "NIOSH REL 3 ppm；法定限值須另核對",
                "physical": "不燃、腐蝕性氣體",
                "health": "吸入及皮膚接觸可致嚴重傷害",
                "incompat": "是", "incompat_note": "水、部分金屬、玻璃；依供應商 SDS 與材質資料確認",
                "stable": "是", "stable_note": "本欄僅示範；操作條件與相容性須由設計文件核對",
            },
            {
                "cas": "1310-73-2", "process_id": "P-SCRUB",
                "name": "氫氧化鈉水溶液", "name_en": "Sodium hydroxide solution",
                "conc": "10", "ctrl_qty": "", "state": "液",
                "odor": "無特殊氣味", "vp": "", "bp": "", "fp": "不適用",
                "expl": "不適用", "twa": "依實際 SDS／公告核對",
                "physical": "腐蝕性液體", "health": "皮膚及眼睛腐蝕",
                "incompat": "是", "incompat_note": "與酸接觸可放熱",
                "stable": "是", "stable_note": "吸收 HF 為放熱反應；以現場設計資料確認",
            },
        ):
            _row_once(conn, sid, "1.2", item, "cas")
        _flag(conn, sid, "overview:P-TANK", PROCESS_OVERVIEWS["P-TANK"])
        _flag(conn, sid, "overview", PROCESS_OVERVIEWS["P-TANK"])
        _flag(conn, sid, "no_reaction", "0")
        _flag(conn, sid, "no_explosion", "1")
        _row_once(
            conn,
            sid,
            "1.4",
            {
                "process_id": "P-SCRUB",
                "kinds": "其他",
                "formula": "HF + NaOH → NaF + H₂O",
                "heat": "中和放熱；熱負荷須依製程設計文件確認",
            },
            "process_id",
        )
        if not fil.list_rows(conn, sid, "1.3b"):
            fil.replace_section(
                conn,
                sid,
                "1.3b",
                HF_FLOW_ROWS,
            )
        _row_once(
            conn,
            sid,
            "1.6",
            {
                "equipment_id": "T-101",
                "scope": "",
                "material": "材質待依設備資料表與供應商相容性確認",
                "material_category": "其他",
                "spec": "示範資料；設計壓力與材質須以核准圖資為準",
            },
            "equipment_id",
        )
        svc.save_equipment_material(
            conn,
            {
                "equipment_id": "T-101",
                "material": "材質待依設備資料表與供應商相容性確認",
                "material_category": "其他",
                "spec": "示範資料；設計壓力與材質須以核准圖資為準",
            },
        )
        exists = conn.execute(
            "SELECT 1 FROM equipment_limit WHERE equipment_id='T-101' AND parameter='壓力'"
        ).fetchone()
        if not exists:
            conn.execute(
                """INSERT INTO equipment_limit(equipment_id, parameter, unit, design_high,
                    design_low, safety_high, safety_low, note)
                   VALUES ('T-101','壓力','bar(g)','','','','','待依核准設計資料表填入；不可據此操作')"""
            )
        if not conn.execute(
            "SELECT 1 FROM equipment_limit WHERE equipment_id='T-101' AND parameter='溫度'"
        ).fetchone():
            conn.execute(
                """INSERT INTO equipment_limit(equipment_id, parameter, unit, design_high,
                    design_low, safety_high, safety_low, note)
                   VALUES ('T-101','溫度','℃','','','','','待依核准設計資料表填入；不可據此操作')"""
            )
        if not conn.execute(
            "SELECT 1 FROM equipment_limit WHERE equipment_id='T-101' AND parameter='容積'"
        ).fetchone():
            conn.execute(
                """INSERT INTO equipment_limit(equipment_id, parameter, unit, design_high,
                    design_low, safety_high, safety_low, note)
                   VALUES ('T-101','容積','L','','','','','待依設備圖資核對')"""
            )
        conn.execute(
            """INSERT INTO equipment_content(equipment_id, cas, no_process_chemical, sds_id)
               VALUES ('T-101','7664-39-3',0,'SDS-HF-001')
               ON CONFLICT(equipment_id, cas, sds_id) DO NOTHING"""
        )
        for eid, cas, sds in (
            ("P-101", "7664-39-3", "SDS-HF-001"),
            ("PSV-101", "7664-39-3", "SDS-HF-001"),
            ("LA-101", "7664-39-3", "SDS-HF-001"),
            ("V-101", "7664-39-3", "SDS-HF-001"),
            ("PL-201", "1310-73-2", "SDS-NAOH-001"),
        ):
            conn.execute(
                """INSERT INTO equipment_content(equipment_id, cas, no_process_chemical, sds_id)
                   VALUES (?,?,0,?) ON CONFLICT(equipment_id, cas, sds_id) DO NOTHING""",
                (eid, cas, sds),
            )
        conn.execute(
            """INSERT INTO inventory(cas, process_id, max_kg, area_code, calc_note)
               VALUES ('7664-39-3','P-TANK',1200,'AREA-A','氣態供料段示範最大在場量；須以現場盤點及相態核對')
               ON CONFLICT(cas, process_id) DO UPDATE SET max_kg=excluded.max_kg"""
        )
        conn.execute(
            """INSERT INTO inventory(cas, process_id, max_kg, area_code, calc_note)
               VALUES ('7664-39-3','P-LOAD',2000,'AREA-B','液態無水 HF 接收段示範最大在場量；與氣態供料段分開認定')
               ON CONFLICT(cas, process_id) DO UPDATE SET max_kg=excluded.max_kg"""
        )
        conn.execute(
            """INSERT INTO inventory(cas, process_id, max_kg, area_code, calc_note)
               VALUES ('1310-73-2','P-SCRUB',5000,'AREA-A','10% 氫氧化鈉水溶液總量；與供液段同一批，不重複加總')
               ON CONFLICT(cas, process_id) DO UPDATE SET max_kg=excluded.max_kg"""
        )
        conn.execute(
            """INSERT INTO inventory(cas, process_id, max_kg, area_code, calc_note)
               VALUES ('1310-73-2','P-ACID',5000,'AREA-A','10% 氫氧化鈉水溶液供液段；與鹼洗段同一批')
               ON CONFLICT(cas, process_id) DO UPDATE SET max_kg=excluded.max_kg"""
        )
        conn.execute(
            """INSERT INTO equipment_content(equipment_id, cas, no_process_chemical, sds_id)
               VALUES ('S-201','1310-73-2',0,'SDS-NAOH-001')
               ON CONFLICT(equipment_id, cas, sds_id) DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO reaction_info(process_id, summary, formula, heat, kinds)
               VALUES ('P-SCRUB','HF 尾氣在鹼洗塔與氫氧化鈉中和','HF + NaOH → NaF + H₂O','中和放熱；熱負荷須依設計文件確認','中和')
               ON CONFLICT(process_id) DO UPDATE SET
                 summary=excluded.summary, formula=excluded.formula,
                 heat=excluded.heat, kinds=excluded.kinds"""
        )
        svc.save_pid_drawing(
            conn,
            {
                "drawing_no": "PID-TANK-001",
                "revision": "B",
                "process_id": "P-TANK",
                "name": "HF 氣態供料區管線儀表圖",
                "issue_date": "2026-02-01",
                "is_as_built": True,
                "attachment_path": "placeholder://PID-TANK-001-B",
                "eval_record_no": "",
            },
            covering_ids=["T-101", "P-101", "PSV-101", "ESD-101"],
        )
        _row_once(
            conn,
            sid,
            "1.9",
            {
                "equipment_id": "PSV-101",
                "device_type": "安全閥",
                "calc_no": "REL-T101-01",
                "spec_no": "API 520",
                "pid_no": "PID-TANK-001",
                "area_code": "AREA-A",
                "cas": "7664-39-3",
                "process_id": "P-TANK",
                "phase": "氣",
                "set_p": "待核對",
                "capacity": "待核對",
                "nozzle": "待核對",
                "scenario": "堵塞導致超壓或外部熱暴露；排放導入安全處理系統",
                "basis": "依核准洩壓設計報告確認",
            },
            "equipment_id",
        )
        _row_once(
            conn,
            sid,
            "1.10",
            {
                "equipment_id": "ESD-101",
                "name": "HF-101 高高壓／洩漏警報連鎖",
                "kind": "硬體",
                "function": "高高壓或 HF 偵測異常時隔離供料並導入尾氣處理",
                "normal": "依核准操作界限",
                "warn": "依警報設定表核對",
                "alarm": "依連鎖邏輯圖核對",
                "reset": "手動",
            },
            "name",
        )
        if not conn.execute(
            "SELECT 1 FROM esd_scenario WHERE scenario_id='ESD-SC-TANK-01'"
        ).fetchone():
            svc.save_esd_scenario(
                conn,
                {
                    "scenario_id": "ESD-SC-TANK-01",
                    "process_id": "P-TANK",
                    "esd_equipment_id": "ESD-101",
                    "name": "儲槽緊急停車",
                    "trigger_conditions": "高高壓、HF 洩漏警報或現場緊急按鈕",
                    "maint_dept_id": "D-MAINT",
                },
                ["T-101", "P-101"],
            )
        _row_once(
            conn,
            sid,
            "1.11",
            {
                "equipment_id": "T-101",
                "category": "危險性設備",
                "expire": "2027-12-31",
                "cert_no": "DEMO-PV-001",
            },
            "equipment_id",
        )
        conn.commit()
        _stamp_demo_phase(conn, sid)
        return "已填入場所、三表與 1.1–1.11 預設值（含常用狀況相態、規定數量試算與反應熱）"
    if n == 2:
        _flag(conn, sid, "pha_methods", "hazop")
        _flag(conn, sid, "pha_consider", "HF 接收、汽化、氣態供料及尾氣鹼洗涉及失去密閉、超壓與吸收失效，採 HAZOP 檢討偏離。")
        _flag(conn, sid, "consider:hazop", "HF 接收、汽化、氣態供料及尾氣鹼洗涉及失去密閉、超壓與吸收失效，採 HAZOP 檢討偏離。")
        _flag(conn, sid, "qty:hazop", "2")
        _row_once(
            conn,
            sid,
            "2.3",
            {"kind": "嚴重度", "code": "S3", "desc": "單一部門停工或需送醫", "note": "手冊範例"},
            "code",
        )
        _row_once(
            conn,
            sid,
            "2.3",
            {"kind": "可能性", "code": "L2", "desc": "運轉期間曾發生或類似廠常見", "note": ""},
            "code",
        )
        _row_once(
            conn,
            sid,
            "2.3",
            {"kind": "風險等級", "code": "中", "desc": "須列入改善追蹤", "note": ""},
            "code",
        )
        pid = "P-TANK"
        if not conn.execute("SELECT 1 FROM process WHERE process_id=?", (pid,)).fetchone():
            row = conn.execute(
                "SELECT process_id FROM process WHERE site_id=? ORDER BY process_id", (sid,)
            ).fetchone()
            pid = row["process_id"] if row else ""
        if pid:
            exists = conn.execute(
                """SELECT 1 FROM unstructured_attachment
                   WHERE process_id=? AND kind='pha' AND original_name=?""",
                (pid, "PHA-評估紀錄.pdf"),
            ).fetchone()
            if not exists:
                conn.execute(
                    """INSERT INTO unstructured_attachment(
                        process_id, kind, original_name, attachment_path, note
                    ) VALUES (?,?,?,?,?)""",
                    (pid, "pha", "PHA-評估紀錄.pdf", "placeholder://PHA-評估紀錄.pdf", "HAZOP"),
                )
                conn.commit()
        return "已填評估方法、數量、準則與上傳占位（未建立 HAZOP 節點）"
    if n == 3:
        for item in fil.LABOR_ITEMS:
            how, who, note = fil.LABOR_HINTS[item]
            _row_once(
                conn,
                sid,
                "3.1",
                {"item": item, "how": how, "who": who, "note": note},
                "item",
            )
        _flag(conn, sid, "labor_file", "placeholder://labor-procedure.pdf")
        _flag(conn, sid, "labor_date", date)
        _flag(conn, sid, "labor_see_also", "0")
        return "已填十三列勞工參與與程序檔占位"
    if n == 4:
        ensure_sops_for_types(conn, sid)
        sample_steps = {
            "SOP-VESSEL-01": "操作前核對核准設計界限、HF 偵測與緊急隔離功能；偏離時依核准停車及應變程序處理。",
            "SOP-PIPE-01": "確認管線與接頭密閉、材質相容；檢修前依許可程序隔離、排淨並確認無 HF 殘留。",
            "SOP-RELIEF-01": "核對釋壓裝置整定紀錄與排放至安全處理系統的路徑；異常立即通報。",
            "SOP-ESD-01": "依核准連鎖邏輯定期測試 HF 偵測、警報、切斷及手動復歸。",
            "SOP-POWER-01": "操作前確認壓送機密封及洩漏監測；異常時停止供料並依程序隔離。",
            "SOP-LOAD-01": "接收前核對容器、密閉接頭、隔離狀態及應變待命；卸收中持續監測洩漏。",
        }
        for sop_id, body in sample_steps.items():
            conn.execute(
                "UPDATE sop SET body=? WHERE sop_id=? AND COALESCE(body,'')=''",
                ("示範摘要，實際步驟與界限須以核准程序書為準。" + body, sop_id),
            )
        conn.commit()
        _flag(conn, sid, "sop_no_temp", "1")
        _row_once(
            conn,
            sid,
            "4.3",
            {
                "equipment_id": "ESD-101",
                "equipment_name": "緊急停車系統",
                "equipment_type": "緊急停車系統",
                "process_id": "P-TANK",
                "item": "高高壓、HF 洩漏警報或現場緊急按鈕",
            },
            "equipment_id",
        )
        return "已依設備類型預派 SOP，並帶入緊急停車條件"
    if n == 5:
        if not conn.execute("SELECT 1 FROM training_course WHERE course_id='COURSE-SOP-01'").fetchone():
            svc.save_training_course(
                conn,
                {
                    "course_id": "COURSE-SOP-01",
                    "process_id": "P-TANK",
                    "name": "製程概述及標準作業程序",
                    "hours": 4,
                    "audience": "操作課",
                    "kind": "initial",
                    "op_kind": "process",
                    "sop_id": "SOP-VESSEL-01",
                },
            )
        if not conn.execute("SELECT 1 FROM training_course WHERE course_id='COURSE-JOB-01'").fetchone():
            svc.save_training_course(
                conn,
                {
                    "course_id": "COURSE-JOB-01",
                    "process_id": "P-TANK",
                    "name": "在職複訓",
                    "hours": 2,
                    "audience": "操作課",
                    "kind": "refresher",
                    "op_kind": "process",
                },
            )
        if not conn.execute("SELECT 1 FROM training_course WHERE course_id='COURSE-MOC-01'").fetchone():
            svc.save_training_course(
                conn,
                {
                    "course_id": "COURSE-MOC-01",
                    "process_id": "P-TANK",
                    "name": "HF 供氣壓送機密封更換與隔離確認（變更訓練）",
                    "hours": 1,
                    "audience": "操作課",
                    "kind": "initial",
                    "op_kind": "process",
                    "sop_id": "SOP-POWER-01"
                    if conn.execute("SELECT 1 FROM sop WHERE sop_id='SOP-POWER-01'").fetchone()
                    else "",
                    "is_moc_related": "1",
                },
            )
        return "已新增製程訓練、在職訓練，以及一門變更訓練"
    if n == 6:
        if not conn.execute("""SELECT 1 FROM contractor WHERE site_id=? AND name=?
            AND contract_period=?""", (sid, "大興機械工程有限公司", "2025-03-01～2025-12-31")).fetchone():
            svc.save_contractor(conn, {
                "site_id": sid, "name": "大興機械工程有限公司",
                "contract_period": "2025-03-01～2025-12-31",
                "work_description": "吊裝及設備維修",
            })
        _flag(conn, sid, "c_roster_complete", "1")
        svc.save_incident(
            conn,
            {
                "incident_id": "INC-2025-001",
                "process_id": "P-TANK",
                "equipment_id": "P-101",
                "incident_date": "2025-08-12",
                "summary": "承攬商吊裝 P-101 時吊索偏擺，接近 HF 密閉供料管線；現場立即停止作業，未發生洩漏。",
                "is_near_miss": True,
                "lost_days": 0,
                "cause": "吊點未對中，作業前未完成 HF 管線隔離與吊掛動線確認。",
                "corrective": "修訂吊裝作業許可，增列 HF 管線隔離、動線與監工確認。",
                "characteristics": "其他",
            },
        )
        svc.save_contractor_incident(
            conn,
            {
                "incident_id": "CTR-2025-001",
                "site_id": sid,
                "contractor_name": "大興機械工程有限公司",
                "contract_period": "2025-03-01～2025-12-31",
                "occur_date": "2025-08-12",
                "incident_type": "虛驚",
                "linked_incident_id": "INC-2025-001",
            },
        )
        conn.execute(
            "UPDATE site SET declare_no_incident_5y=0 WHERE site_id=?", (sid,)
        )
        conn.commit()
        _row_once(
            conn,
            sid,
            "6.1",
            {
                "vendor": "大興機械工程有限公司",
                "summary": "吊裝 P-101 接近 HF 密閉供料管線的虛驚；未發生洩漏。",
                "equipment_id": "P-101",
                "incident_type": "虛驚",
            },
            "vendor",
        )
        return "已登錄表6.2-1 承攬虛驚一筆"
    if n == 7:
        eqs = conn.execute(
            "SELECT equipment_id, name, process_id FROM equipment WHERE site_id=? ORDER BY equipment_id",
            (sid,),
        ).fetchall()
        for e in eqs:
            _row_once(conn, sid, "7.0", {
                "equipment_id": e["equipment_id"],
                "applicable": "1",
                "reason": "教學案例：待以現場啟動前檢查範圍核對",
            }, "equipment_id")
            _row_once(
                conn,
                sid,
                "7.1",
                {
                    "equipment_id": e["equipment_id"],
                    "equipment_name": e["name"],
                    "process_id": e["process_id"],
                    "when": "2026-01-20",
                    "rec": "無",
                    "due": "",
                    "track": "完成",
                    "change_id": "MOC-2026-001" if e["equipment_id"] == "P-101" else "",
                },
                "equipment_id",
            )
        for item in fil.list_rows(conn, sid, "7.1"):
            if item.get("equipment_id") == "P-101" and not str(item.get("change_id") or "").strip():
                item["change_id"] = "MOC-2026-001"
                fil.update_payload(conn, int(item["row_id"]), item)
        return "已列出各設備啟動前檢查；P-101 結到變更 MOC-2026-001"
    if n == 8:
        conn.execute(
            """INSERT INTO mi_screen(equipment_id,is_critical,basis)
               VALUES ('T-101',1,'HF 緩衝容器，失去密閉可能造成暴露')
               ON CONFLICT(equipment_id) DO UPDATE SET is_critical=1"""
        )
        if not conn.execute(
            "SELECT 1 FROM mi_inspection_detail WHERE equipment_id='T-101'"
        ).fetchone():
            conn.execute(
                """INSERT INTO mi_inspection_detail
                   (equipment_id,damage_mechanism,inspect_method,inspect_frequency,
                    procedure_ref,pid_drawing_no,confirmed)
                   VALUES ('T-101','HF 接觸介質與含水條件下的材質相容性待評估',
                           '依設備檢查計畫確認密封、厚度與洩漏偵測','每年',
                           'MI-T-101','PID-TANK-001',0)"""
            )
        conn.commit()
        _flag(conn, sid, "mi_fail_note", "開站以文字＋數字說明，不強制公式、不算裂化速度。")
        return "已新增 T-101 檢查項目示例；失效率須依運轉與失效紀錄填入"
    if n == 9:
        svc.save_hotwork_zone(
            conn,
            {
                "area_code": "AREA-A",
                "protection_reason": "HF 供料區維修動火須先隔離、排淨、確認無殘留並監測；隔離與復歸依核准許可程序。",
            },
        )
        svc.save_hotwork_zone(
            conn,
            {
                "area_code": "AREA-B",
                "protection_reason": "無水 HF 接收期間禁止動火；檢修須停止卸收、完成隔離及暴露監測。",
            },
        )
        for k, _ in fil.YN9:
            _flag(conn, sid, k, "是")
        _flag(conn, sid, "hw_eq", "T-101")
        conn.execute(
            """INSERT INTO hotwork_permit(permit_id, equipment_id, area_code, permit_date, measures)
               VALUES ('HW-2026-001','T-101','AREA-A','2026-07-15','停止供料、雙重隔離、排淨確認、HF 監測、應變待命')
               ON CONFLICT(permit_id) DO NOTHING"""
        )
        conn.commit()
        return "已列舉動火管制區域 AREA-A／AREA-B"
    if n == 10:
        _flag(conn, sid, "moc_none", "否")
        _flag(conn, sid, "moc_def", "是")
        _flag(conn, sid, "moc_no_case", "0")
        _row_once(
            conn,
            sid,
            "10.1",
            {
                "change_id": "MOC-2026-001",
                "name": "P-101 HF 供氣壓送機密封型式變更",
                "process_ids": ["P-TANK"],
                "equipment_ids": ["P-101"],
                "chemical_refs": [],
                "start_time": "2026-03-01",
                "due_date": "2026-03-31",
                "description": "更換 HF 供氣壓送機密封；先完成材質相容性、洩漏偵測與隔離程序審查",
                "sop_id": "SOP-POWER-01",
                "course_id": "COURSE-MOC-01",
                "follow_up": "第七章 P-101 啟動前檢查結案",
            },
            "change_id",
        )
        return "已建一筆變更，並連到作業程序、變更訓練與啟動前檢查"
    if n == 11:
        for k, _ in fil.YN11:
            _flag(conn, sid, k, "是")
        _flag(conn, sid, "inc_zero", "0")
        return "已答事故調查制度確認，並登錄一件承攬虛驚"
    if n == 12:
        def hf_ref(process_id: str) -> str:
            chem = conn.execute("""SELECT process_id,COALESCE(sds_id,'') AS sds_id,cas
                FROM chemical WHERE process_id=? AND cas='7664-39-3' ORDER BY sds_id LIMIT 1""",
                (process_id,)).fetchone()
            return "|".join(str(chem[k]) for k in ("process_id", "sds_id", "cas")) if chem else ""
        _row_once(
            conn,
            sid,
            "12.1s",
            {
                "situation": "HF 供料管線破損、氣體外洩",
                "description": "HF 供料管線破損造成有毒氣體外洩，須隔離並依風向疏散",
                "process_ids": ["P-TANK"],
                "equipment_ids": ["T-101"],
                "chemical_refs": [hf_ref("P-TANK")],
                "area_codes": ["AREA-A"],
                "muster": "AREA-M",
                "scope_note": "集合點實際使用依當日風向調整",
            },
            "situation",
        )
        _row_once(
            conn,
            sid,
            "12.1s",
            {
                "situation": "無水 HF 卸收接頭失效、液體外洩",
                "description": "無水 HF 卸收接頭失效造成液體外洩，須停止卸收並隔離",
                "process_ids": ["P-LOAD"],
                "equipment_ids": ["LA-101"],
                "chemical_refs": [hf_ref("P-LOAD")],
                "area_codes": ["AREA-B"],
                "muster": "AREA-M",
                "scope_note": "集合點實際使用依當日風向調整",
            },
            "situation",
        )
        for k, _ in fil.YN12:
            _flag(conn, sid, k, "是")
        _row_once(
            conn,
            sid,
            "12.2",
            {
                "name": "HF 偵測器與遠端隔離裝置",
                "area_code": "AREA-A",
                "qty": "2",
                "unit": "套",
                "total": "2",
                "freq": "每月",
                "cas": "7664-39-3",
            },
            "name",
        )
        _row_once(
            conn,
            sid,
            "12.2",
            {
                "name": "緊急沖淋洗眼器（接收區）",
                "area_code": "AREA-B",
                "qty": "1",
                "unit": "座",
                "total": "1",
                "freq": "每月",
                "cas": "7664-39-3",
            },
            "name",
        )
        return "已填緊急狀況、確認事項與分區器材"
    if n == 13:
        _flag(conn, sid, "audit_first", "否")
        _flag(conn, sid, "audit_zero", "0")
        _row_once(conn, sid, "13.1", {
            "when": "2026-06-15 09:00", "dept_id": "D-OPS",
            "unit": "製程安全資訊", "auditor": "示範稽核員",
            "note": "核對 HF 相態、最大在場量與 SDS 版本",
        }, "when")
        _row_once(conn, sid, "13.2", {
            "plan_when": "2026-06-15 09:00",
            "finding": "T-101 材質相容性與設計界限佐證待補",
            "action": "取得核准設備資料表及供應商相容性證明",
            "dept_id": "D-MAINT", "due": "2026-09-30", "done": "",
            "note": "範例待辦，非已完成改善",
        }, "finding")
        return "已列一筆 HF 案例稽核計畫與待改善事項"
    if n == 14:
        sample = Path(__file__).resolve().parent / "sample_docs" / "hf_trade_secret_demo.txt"
        if not conn.execute(
            "SELECT 1 FROM unstructured_attachment WHERE site_id=? AND kind='trade_secret' AND attachment_path=?",
            (sid, str(sample)),
        ).fetchone():
            conn.execute(
                """INSERT INTO unstructured_attachment(site_id, process_id, kind, original_name, attachment_path, note)
                   VALUES (?,NULL,'trade_secret',?,?,?)""",
                (sid, "HF-商業機密管理程序-示範草稿.txt", str(sample), "示範草稿，不可作正式申報佐證"),
            )
            conn.commit()
        return "已附第十四章示範草稿；正式申報請替換為核准程序書"
    return "本步沒有可套用的預設值"
