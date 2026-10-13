"""Data-backed preview for the V8.3 first-filing workflow."""

from __future__ import annotations

import html
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from psm import filing as fil
from psm.enums import UNIT_TITLES


SECTIONS = {
    1: (("1.1", "表1.1-1 危害性化學品清單"), ("1.2", "表1.2-1 高度危害化學品"),
        ("1.3", "表1.3-1 製造流程方塊圖"), ("1.3b", "製程流程方塊"),
        ("1.4", "表1.4-1 製程化學反應資料"), ("1.5", "表1.5-1 安全上下限補充"),
        ("1.6", "表1.6-1 建造材料與設計規範補充"), ("1.8", "表1.8-1 防爆區域劃分"),
        ("1.9", "表1.9-1 釋壓系統補充"), ("1.10", "表1.10-1 安全系統補充"),
        ("1.11", "表1.11-1 法令證明文件")),
    2: (("2.3", "表2.3-1 至 2.3-3 風險定義"), ("2.4", "表2.4-1 高風險情境")),
    3: (("3.1", "表3.1-1 勞工參與方式"),),
    4: (("4.2", "表4.2-1 臨時操作程序"), ("4.3", "表4.3-1 緊急停車與緊急操作"),
        ("4.4", "表4.4-1 操作界限")),
    5: (("5.1e", "SOP 訓練課程例外理由"),),
    7: (("7.0", "PSSR 設備適用性判定"), ("7.1", "表7.1-1 啟動前安全檢查")),
    8: (),
    9: (("9.1", "表9.1-1 動火許可補充"),),
    10: (("10.1", "表10.1-2 變更管理紀錄"),),
    11: (("11.2", "表11.2-1 近五年事故概述"),),
    12: (("12.1s", "表12.1-1 計畫所含緊急狀況"), ("12.2", "表12.2-1 搶救設備與器材")),
    13: (("13.1", "表13.1-1 符合性稽核計畫"), ("13.2", "表13.2-1 改善事項與追蹤")),
}

FIELD_NAMES = {
    "process_id": "製程編號", "equipment_id": "設備編號", "sds_id": "SDS 編號",
    "cas": "CAS", "area_code": "區域編號", "dept_id": "部門編號",
    "name": "名稱", "title": "名稱", "item": "項目", "kind": "類型",
    "kinds": "反應種類", "kind_other": "其他反應種類", "formula": "化學反應式", "heat": "反應熱",
    "how": "參與方式", "who": "參與人員／部門", "note": "備註",
    "date": "日期", "updated_on": "更新日期", "description": "說明",
    "file": "檔案", "value": "數值", "unit": "單位",
    "process_ids": "相關製程", "equipment_ids": "相關設備", "chemical_refs": "相關化學品",
    "area_codes": "相關區域", "muster": "集合點", "scope_note": "範圍備註",
    "no_equipment_reason": "未選設備理由", "no_chemical_reason": "未選化學品理由",
    "drill_plan_scope": "演練計畫涵蓋項目", "drill_status": "演練狀態",
    "drill_date": "已執行演練日期", "drill_due": "預定演練日期",
    "drill_record_name": "演練紀錄", "drill_record_path": "演練紀錄檔案路徑",
    "drill_no_reason": "尚未演練原因",
    "applicable": "PSSR 適用性", "reason": "理由",
    "limit_id": "1.5 界限編號", "parameter": "操作參數", "safety_high": "安全上限",
    "safety_low": "安全下限", "high_consequence": "超上限後果", "high_correct": "超上限矯正程序",
    "high_na_reason": "超上限不適用理由", "low_consequence": "低於下限後果",
    "low_correct": "低於下限矯正程序", "low_na_reason": "低於下限不適用理由",
}

ATTACHMENT_CHAPTER = {
    "pha": 2, "labor": 3, "mi": 8, "trade_secret": 14,
}


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _table(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_e(c)}</td>" for c in row) + "</tr>"
        for row in rows
    )
    if not body:
        body = f"<tr><td colspan='{len(headers)}' class='empty'>尚未填報</td></tr>"
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def _query(conn: sqlite3.Connection, sql: str, site_id: str, columns: tuple[str, ...]) -> list[tuple[object, ...]]:
    return [tuple(row[col] for col in columns) for row in conn.execute(sql, (site_id,))]


def _filled_rows(rows: list[dict]) -> str:
    from psm.wizard import has_uploaded_file

    if not rows:
        return "<p class='empty'>尚未填報</p>"
    out = []
    for index, row in enumerate(rows, 1):
        cells = []
        for key, value in row.items():
            if key == "row_id" or value is None or value == "" or value == []:
                continue
            if key == "drill_record_path":
                value = "已上傳" if has_uploaded_file(str(value)) else "檔案遺失"
            if key == "chemical_refs" and isinstance(value, list):
                shown = "、".join(
                    f"{parts[0]}／{parts[2]}（{parts[1]}）" if len(parts := str(ref).split("|", 2)) == 3 else str(ref)
                    for ref in value
                )
            else:
                shown = "、".join(map(str, value)) if isinstance(value, list) else str(value)
            cells.append(f"<dt>{_e(FIELD_NAMES.get(key, key.replace('_', ' ')))}</dt><dd>{_e(shown)}</dd>")
        out.append(f"<div class='record'><strong>第 {index} 筆</strong><dl>{''.join(cells)}</dl></div>")
    return "".join(out)


def _attachment_rows(conn: sqlite3.Connection, site_id: str) -> dict[int, list[tuple[str, str, str]]]:
    grouped: dict[int, list[tuple[str, str, str]]] = defaultdict(list)
    sql = """SELECT u.kind, u.original_name, u.attachment_path, u.note FROM unstructured_attachment u
             LEFT JOIN process p ON p.process_id=u.process_id
             WHERE u.site_id=? OR p.site_id=? ORDER BY u.attachment_id"""
    for row in conn.execute(sql, (site_id, site_id)):
        chapter = ATTACHMENT_CHAPTER.get(row["kind"], 1)
        path = row["attachment_path"] or ""
        if "示範草稿" in (row["note"] or ""):
            status = "示範草稿，正式申報須替換"
        else:
            status = "已上傳" if Path(path).is_file() else "待上傳（僅有檔名或檔案遺失）"
        name = row["original_name"] or Path(path).name
        grouped[chapter].append((row["kind"], name, status))
    return grouped


def render_report_v83(conn: sqlite3.Connection, site_id: str) -> str:
    from psm import wizard as wiz

    site = conn.execute("SELECT * FROM site WHERE site_id=?", (site_id,)).fetchone()
    if site is None:
        return "<p>場所不存在</p>"

    flags = fil.all_flags(conn, site_id)
    by_section = fil.rows_by_section(conn, site_id)
    by_section["11.2"] = [
        {
            **dict(r), "when": r["incident_date"],
            "incident_type": "虛驚" if r["is_near_miss"] else "職業災害",
        }
        for r in conn.execute(
            "SELECT * FROM incident WHERE site_id=? ORDER BY incident_date, incident_id", (site_id,)
        )
    ]
    attachments = _attachment_rows(conn, site_id)
    gaps = {n: wiz.step_missing(conn, site_id, n) for n in range(1, 15)}
    status = "尚有待補資料" if any(gaps.values()) else "十四章基本檢核通過，內容仍須人工核對"
    parts = [
        "<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{_e(site['site_name'])}｜V8.3 填報預覽</title>",
        "<style>body{font:16px/1.65 'Microsoft JhengHei',sans-serif;color:#20323b;max-width:1120px;margin:36px auto;padding:0 28px}h1,h2,h3{line-height:1.35}h2{border-bottom:2px solid #1d786f;padding-bottom:8px;margin-top:44px}h3{margin:26px 0 10px}a{color:#146b64}.meta{color:#53646e}.status{background:#eef7f4;border-left:4px solid #1d786f;padding:10px 14px}.pending{background:#fff5e7;border-left:4px solid #b66d22;padding:10px 14px}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;margin:10px 0 22px}th,td{border:1px solid #c7d4d3;padding:8px 10px;text-align:left;vertical-align:top}th{background:#eff5f3}.empty{color:#777}.record{border:1px solid #c7d4d3;padding:10px 14px;margin:10px 0;break-inside:avoid}dl{display:grid;grid-template-columns:170px 1fr;margin:8px 0;gap:2px 8px}dt{color:#53646e}dd{margin:0}.toc{columns:2}@media print{body{margin:0;max-width:none}.toc{columns:2}section{break-inside:auto}h2,h3{break-after:avoid}}",
        "</style></head><body>",
        f"<header><p class='meta'>製程安全管理｜V8.3 首次填報預覽</p><h1>{_e(site['site_name'])}</h1>",
        f"<p>{_e(site['company_name'])}｜{_e(site['scope'])}</p>",
        f"<p class='meta'>申請義務人：{_e(site['applicant_name'])}　評估基準日：{_e(site['assessment_base_date'])}　勞工人數：{_e(site['worker_count'])}</p>",
        f"<p class='{'pending' if any(gaps.values()) else 'status'}'>{status}。本頁依目前填報資料產生，未填欄位請回到對應章節補齊。</p></header>",
        "<nav aria-label='章節目錄'><h2>目錄</h2><ol class='toc'>",
    ]
    parts.extend(f"<li><a href='#chapter-{n}'>第 {n} 章　{_e(UNIT_TITLES[n])}</a></li>" for n in range(1, 15))
    parts.append("</ol></nav>")

    def add_table(title: str, headers: tuple[str, ...], sql: str, columns: tuple[str, ...]) -> None:
        parts.append(f"<h3>{_e(title)}</h3>")
        parts.append(_table(headers, _query(conn, sql, site_id, columns)))

    for n in range(1, 15):
        parts.append(f"<section id='chapter-{n}'><h2>第 {n} 章　{_e(UNIT_TITLES[n])}</h2>")
        if gaps[n]:
            parts.append("<div class='pending'><strong>待補事項</strong><ul>")
            parts.extend(f"<li>{_e(item)}</li>" for item in gaps[n])
            parts.append("</ul></div>")
        else:
            parts.append("<p class='status'>本章基本檢核通過；資料及程序內容仍須人工核對。</p>")

        if n == 1:
            add_table("表1.0-1 部門", ("編號", "名稱", "人數"),
                      "SELECT dept_id,name,headcount FROM department WHERE site_id=? ORDER BY dept_id",
                      ("dept_id", "name", "headcount"))
            add_table("表1.0-2 製程清單", ("編號", "名稱", "概述", "操作部門"),
                      "SELECT process_id,name,overview,operating_dept_id FROM process WHERE site_id=? ORDER BY process_id",
                      ("process_id", "name", "overview", "operating_dept_id"))
            add_table("表1.0-3 設備清單", ("設備編號", "名稱", "類型", "製程編號"),
                      "SELECT equipment_id,name,equipment_type,process_id FROM equipment WHERE site_id=? ORDER BY equipment_id",
                      ("equipment_id", "name", "equipment_type", "process_id"))
            add_table("表1.0-4 化學品清單", ("製程", "SDS", "CAS", "名稱", "角色", "危害說明"),
                      """SELECT c.process_id,c.sds_id,c.cas,c.name,c.role,c.h_codes FROM chemical c
                         JOIN process p ON p.process_id=c.process_id WHERE p.site_id=? ORDER BY c.process_id,c.cas""",
                      ("process_id", "sds_id", "cas", "name", "role", "h_codes"))
            mix_rows = [fil.attach_annex_check(row) for row in by_section.get("mix", [])]
            parts.append("<h3>表1.0-4 配方成分、相態與列管數量</h3>")
            parts.append(_table(
                ("配方／成分", "製程", "相態", "操作量 kg", "成分 CAS", "重量比 %", "折算純物質 kg", "規定數量 kg", "列管判定"),
                [
                    (
                        row.get("mix_name"), row.get("process_id"), row.get("phase_state"),
                        row.get("total_kg"), row.get("cas"),
                        f"{row.get('pct_lo') or ''}–{row.get('pct_hi') or ''}",
                        row.get("pure_kg"), row.get("limit_kg"), row.get("annex_note"),
                    )
                    for row in mix_rows
                ],
            ))
            add_table("表1.0-5 廠區區域", ("區域編號", "名稱", "圖號", "版次", "日期"),
                      "SELECT area_code,name,drawing_no,revision,issue_date FROM area WHERE site_id=? ORDER BY area_code",
                      ("area_code", "name", "drawing_no", "revision", "issue_date"))
            review_rows = []
            for equipment in conn.execute(
                """SELECT e.equipment_id,e.name,r.* FROM equipment e
                   LEFT JOIN equipment_operating_review r ON r.equipment_id=e.equipment_id
                   WHERE e.site_id=? ORDER BY e.equipment_id""", (site_id,)
            ):
                try:
                    selected = "、".join(json.loads(equipment["selected_parameters"] or "[]"))
                except (TypeError, ValueError):
                    selected = "資料待更正"
                content = "、".join(
                    f"{c['cas'] or '無 CAS'}（{c['sds_id']}）" for c in conn.execute(
                        """SELECT cas,sds_id FROM equipment_content WHERE equipment_id=?
                           AND no_process_chemical=0 ORDER BY cas,sds_id""", (equipment["equipment_id"],)
                    )
                )
                review_rows.append((
                    equipment["equipment_id"], equipment["name"],
                    selected if equipment["selected_parameters"] is not None else "待確認",
                    equipment["no_parameter_reason"], content or equipment["no_content_reason"],
                    equipment["batch_quantity"], equipment["batch_unit"], equipment["batch_na_reason"],
                ))
            parts.append("<h3>表1.5-1 逐台檢討與單次操作量</h3>")
            parts.append(_table(("設備編號", "設備名稱", "檢討參數", "全部不適用理由", "實際內容物與 SDS／無內容物理由",
                                 "單次操作量", "單位", "批次不適用理由"), review_rows))
            add_table("表1.5-1 安全上下限", ("設備編號", "參數", "單位", "操作上限", "操作下限", "安全上限", "安全下限",
                                          "上限不適用理由", "下限不適用理由", "備註"),
                      """SELECT l.equipment_id,l.parameter,l.unit,l.design_high,l.design_low,
                         l.safety_high,l.safety_low,l.high_na_reason,l.low_na_reason,l.note
                         FROM equipment_limit l JOIN equipment e ON e.equipment_id=l.equipment_id
                         WHERE e.site_id=? ORDER BY l.equipment_id,l.parameter,l.limit_id""",
                      ("equipment_id", "parameter", "unit", "design_high", "design_low",
                       "safety_high", "safety_low", "high_na_reason", "low_na_reason", "note"))
            file_rows = []
            for row in conn.execute("SELECT area_code AS ident, attachment_path FROM area WHERE site_id=? ORDER BY area_code", (site_id,)):
                file_rows.append(("區域位置圖", row["ident"], "已上傳" if wiz.has_uploaded_file(row["attachment_path"]) else "待上傳"))
            for row in conn.execute("SELECT sds_id AS ident, file_path AS attachment_path FROM sds WHERE site_id=? ORDER BY sds_id", (site_id,)):
                file_rows.append(("SDS", row["ident"], "已上傳" if wiz.has_uploaded_file(row["attachment_path"]) else "待上傳"))
            parts.append("<h3>第一章圖資及 SDS 附件</h3>")
            parts.append(_table(("種類", "編號", "狀態"), file_rows))
            add_table("表1.7-1 製程圖資", ("製程", "圖號", "版次", "種類", "日期", "附件狀態"),
                      """SELECT d.process_id,d.drawing_no,d.revision,d.diagram_kind,d.issue_date,
                         CASE WHEN d.attachment_path LIKE 'placeholder://%' THEN '待上傳（僅有檔名）' ELSE '已上傳' END AS status
                         FROM pid_drawing d JOIN process p ON p.process_id=d.process_id
                         WHERE p.site_id=? ORDER BY d.drawing_no,d.revision""",
                      ("process_id", "drawing_no", "revision", "diagram_kind", "issue_date", "status"))
        elif n == 2:
            methods = [m for m in (flags.get("pha_methods") or "").split(",") if m]
            method_names = {key: label for key, label, _ in fil.PHA_METHODS}
            parts.append("<h3>表2.1-1 評估方法及考量因素</h3>")
            parts.append(_table(("方法", "採用原因"), [
                (method_names.get(m, m), flags.get(f"consider:{m}", ""))
                for m in methods
            ]))
            add_table("表2.2-1 風險評估紀錄", ("紀錄編號", "方法", "考量問題數", "日期", "文件名稱"),
                      """SELECT r.record_id,r.method,r.question_count,r.record_date,u.original_name
                         FROM pha_record r JOIN unstructured_attachment u ON u.attachment_id=r.attachment_id
                         WHERE r.site_id=? ORDER BY r.record_id""",
                      ("record_id", "method", "question_count", "record_date", "original_name"))
        elif n == 3:
            parts.append("<h3>程序書</h3>")
            labor_path = flags.get("labor_file", "")
            if flags.get("labor_see_also") == "1":
                ref = conn.execute(
                    "SELECT original_name FROM unstructured_attachment WHERE attachment_id=?",
                    (flags.get("labor_ref") or "",),
                ).fetchone()
                parts.append(f"<p>見既有附件：{_e(ref['original_name'] if ref else '未指定')}</p>")
            elif labor_path and not labor_path.startswith("placeholder://"):
                parts.append(f"<p>{_e(flags.get('labor_file_name') or Path(labor_path).name)}｜{_e(flags.get('labor_date'))}｜已上傳</p>")
            else:
                parts.append("<p class='empty'>尚未上傳程序書</p>")
        elif n == 4:
            add_table("表4.1-1 標準作業程序清單", ("程序編號", "名稱", "製程", "關聯設備", "修訂日期", "範圍狀態"),
                      """SELECT s.sop_id,s.title,s.process_id,
                         (SELECT group_concat(se.equipment_id,'、') FROM sop_equipment se
                          WHERE se.sop_id=s.sop_id) AS equipment_ids,s.updated_on,
                         CASE WHEN NOT EXISTS (SELECT 1 FROM sop_equipment se WHERE se.sop_id=s.sop_id)
                                   THEN '未關聯設備'
                              WHEN EXISTS (SELECT 1 FROM sop_equipment se WHERE se.sop_id=s.sop_id AND se.confirmed=0)
                                   THEN '舊資料待確認'
                              ELSE '已確認' END AS scope_status
                         FROM sop s
                         JOIN process p ON p.process_id=s.process_id WHERE p.site_id=? ORDER BY s.sop_id""",
                      ("sop_id", "title", "process_id", "equipment_ids", "updated_on", "scope_status"))
        elif n == 5:
            add_table("表5.1-1 教育訓練課程", ("課程編號", "名稱", "製程", "類型", "初訓時數", "複訓頻率", "複訓時數", "對象", "對應 SOP", "未關聯理由"),
                      """SELECT t.course_id,t.name,t.process_id,t.kind,t.hours,t.refresh_every,t.refresh_hours,t.audience,
                         (SELECT group_concat(sop_id, '、') FROM training_course_sop WHERE course_id=t.course_id) AS sop_ids,
                         t.no_sop_reason FROM training_course t
                         JOIN process p ON p.process_id=t.process_id WHERE p.site_id=? ORDER BY t.course_id""",
                      ("course_id", "name", "process_id", "kind", "hours", "refresh_every", "refresh_hours", "audience", "sop_ids", "no_sop_reason"))
            add_table("訓練執行紀錄", ("紀錄編號", "課程", "受訓者", "日期", "已測驗"),
                      """SELECT r.record_id,r.course_id,r.trainee,r.train_date,
                         CASE WHEN r.tested=1 THEN '是' ELSE '否' END AS tested_label
                         FROM training_record r JOIN training_course t ON t.course_id=r.course_id
                         JOIN process p ON p.process_id=t.process_id WHERE p.site_id=? ORDER BY r.train_date""",
                      ("record_id", "course_id", "trainee", "train_date", "tested_label"))
        elif n == 6:
            add_table("承攬商名冊", ("承攬商", "承攬期間", "工作內容"),
                      "SELECT name,contract_period,work_description FROM contractor WHERE site_id=? ORDER BY contractor_id",
                      ("name", "contract_period", "work_description"))
            add_table("表6.2-1 承攬人職災／虛驚", ("承攬人", "期間", "日期", "類型", "摘要", "關聯事故"),
                      """SELECT ci.contractor_name,ci.contract_period,ci.occur_date,ci.incident_type,
                                COALESCE(NULLIF(ci.summary,''),i.summary,'') AS summary,ci.linked_incident_id
                         FROM contractor_incident ci LEFT JOIN incident i ON i.incident_id=ci.linked_incident_id
                         WHERE ci.site_id=? ORDER BY ci.incident_id""",
                      ("contractor_name", "contract_period", "occur_date", "incident_type", "summary", "linked_incident_id"))
            if flags.get("c_no_accident") == "1":
                parts.append("<p>已註明無承攬職災或虛驚。</p>")
        elif n == 9:
            add_table("表9.1-1 動火管制區域", ("區域編號", "管制原因"),
                      """SELECT z.area_code,z.protection_reason FROM hotwork_zone z JOIN area a ON a.area_code=z.area_code
                         WHERE a.site_id=? ORDER BY z.area_code""", ("area_code", "protection_reason"))
        elif n == 8:
            add_table("表8.1-1 完整設備安全關鍵性篩選", ("製程", "設備編號", "設備名稱", "設備類型", "六大類", "安全關鍵", "判定依據"),
                      """SELECT e.process_id,e.equipment_id,e.name,e.equipment_type,
                         CASE WHEN s.mi_type_confirmed=1 THEN s.mi_type ELSE '待確認' END AS mi_type,
                         CASE WHEN s.is_critical IS NULL THEN '待確認'
                              WHEN s.is_critical=1 THEN '是' ELSE '否' END AS status,
                         s.basis FROM equipment e LEFT JOIN mi_screen s
                         ON s.equipment_id=e.equipment_id
                         WHERE e.site_id=? ORDER BY e.process_id,e.equipment_id""",
                      ("process_id", "equipment_id", "name", "equipment_type", "mi_type", "status", "basis"))
            add_table("表8.1-1 安全關鍵設備逐項檢查明細",
                      ("設備編號", "損壞機制", "功能檢查項目", "方式", "頻率", "程序書", "P&ID", "狀態"),
                      """SELECT d.equipment_id,d.damage_mechanism,d.inspection_item,
                         d.inspect_method,d.inspect_frequency,d.procedure_ref,d.pid_drawing_no,
                         CASE WHEN d.confirmed=1 THEN '已確認' ELSE '舊資料待確認' END AS status
                         FROM mi_inspection_detail d JOIN equipment e ON e.equipment_id=d.equipment_id
                         WHERE e.site_id=? ORDER BY d.equipment_id,d.detail_id""",
                      ("equipment_id", "damage_mechanism", "inspection_item", "inspect_method",
                       "inspect_frequency", "procedure_ref", "pid_drawing_no", "status"))
            add_table("表8.2-1 設備失效率", ("設備編號", "六大類", "統計起", "統計迄", "運行小時", "失效事件數", "次／百萬小時", "說明", "確認"),
                      """SELECT f.equipment_id,s.mi_type,f.period_start,f.period_end,
                         f.run_hours,f.failure_count,
                         CASE WHEN f.run_hours>0 THEN ROUND(f.failure_count*1000000.0/f.run_hours,4)
                              ELSE NULL END AS rate,f.note,
                         CASE WHEN f.confirmed=1 THEN '已確認' ELSE '舊資料待確認' END AS status
                         FROM mi_failure f JOIN mi_screen s ON s.equipment_id=f.equipment_id
                         JOIN equipment e ON e.equipment_id=f.equipment_id
                         WHERE e.site_id=? AND s.is_critical=1 ORDER BY f.equipment_id""",
                      ("equipment_id", "mi_type", "period_start", "period_end", "run_hours",
                       "failure_count", "rate", "note", "status"))
            add_table("表8.2-1 原始資料不足待人工確認", ("設備編號", "統計起", "統計迄", "資料不足原因", "狀態"),
                      """SELECT g.equipment_id,g.period_start,g.period_end,g.reason,
                         '待人工確認' AS status FROM mi_failure_gap g
                         JOIN equipment e ON e.equipment_id=g.equipment_id
                         WHERE e.site_id=? ORDER BY g.equipment_id""",
                      ("equipment_id", "period_start", "period_end", "reason", "status"))
            add_table("表8.2-1 六大類彙總失效率（總失效事件數／總運行時數）",
                      ("六大類", "總失效事件數", "總運行小時", "次／百萬小時"),
                      """SELECT s.mi_type,SUM(f.failure_count) AS failures,
                         SUM(f.run_hours) AS hours,
                         ROUND(SUM(f.failure_count)*1000000.0/SUM(f.run_hours),4) AS rate
                         FROM mi_failure f JOIN mi_screen s ON s.equipment_id=f.equipment_id
                         JOIN equipment e ON e.equipment_id=f.equipment_id
                         WHERE e.site_id=? AND s.is_critical=1 AND s.mi_type_confirmed=1
                         AND f.confirmed=1 AND f.run_hours>0
                         GROUP BY s.mi_type ORDER BY s.mi_type""",
                      ("mi_type", "failures", "hours", "rate"))
        elif n == 11 and flags.get("inc_zero") == "1":
            parts.append("<p>已註明近五年事故 0 件。</p>")
        elif n == 14:
            parts.append("<p>本章無填報表，以程序書附件檢核。</p>")

        for section, title in SECTIONS.get(n, ()):
            parts.append(f"<h3>{_e(title)}</h3>{_filled_rows(by_section.get(section, []))}")
        if n == 12:
            totals = wiz.page_extra(conn, site_id, 12)["gear_totals"]
            if totals:
                parts.append("<h3>同名且同單位器材彙總</h3>")
                parts.append(_table(("器材名稱", "總數量", "單位"), [
                    (r["name"], r["quantity"], r["unit"]) for r in totals
                ]))
        docs = [
            (r["purpose"], r["document_no"], r["title"], r["revision_date"],
             "已上傳" if wiz.has_uploaded_file(r["attachment_path"]) else "檔案遺失")
            for r in conn.execute(
                """SELECT ref.purpose,d.document_no,d.title,d.revision_date,d.attachment_path
                   FROM filing_document_ref ref JOIN filing_document d
                     ON d.document_id=ref.document_id
                   WHERE ref.site_id=? AND ref.step=? AND d.site_id=?
                   ORDER BY ref.purpose,d.document_no""",
                (site_id, n, site_id),
            )
        ]
        if docs:
            parts.append("<h3>本章引用文件與版次</h3>")
            parts.append(_table(("用途", "文件編號", "名稱", "修訂日期", "狀態"), docs))
        if attachments.get(n):
            parts.append("<h3>附件</h3>")
            parts.append(_table(("種類", "文件名稱", "狀態"), attachments[n]))
        parts.append("</section>")

    parts.append("</body></html>")
    return "".join(parts)
