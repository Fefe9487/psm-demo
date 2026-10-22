"""精靈 HTTP：十四項步驟與存檔。示範廠 /hazop 編輯器不走這裡。"""

from __future__ import annotations

import sqlite3
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from urllib.parse import parse_qs, quote, urlparse
from uuid import uuid4

from fastapi import File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse

from psm.enums import WIZARD_SITE_ID
from psm.db import wizard_case
from psm.errors import PsmError
from psm import filing as fil
from psm import services as svc
from psm import wizard as wiz
from psm import delete_item


def _partial(request: Request) -> bool:
    return request.headers.get("x-psm-partial") == "1"


def _json_ok(payload: dict | None = None, message: str = "已存檔"):
    body = {"ok": True, "message": message}
    if payload:
        body.update(payload)
    return JSONResponse(body)


def _json_err(message: str):
    return JSONResponse({"ok": False, "message": message}, status_code=400)


def _area_client_payload(conn, area_code: str) -> dict:
    row = conn.execute(
        "SELECT * FROM area WHERE area_code=? AND site_id=?",
        (area_code, WIZARD_SITE_ID),
    ).fetchone()
    area = {k: row[k] for k in row.keys()}
    for key, value in list(area.items()):
        if value is None:
            area[key] = ""
    eqs = [
        {"equipment_id": r["equipment_id"], "name": r["name"]}
        for r in conn.execute(
            """SELECT equipment_id, name FROM equipment
               WHERE site_id=? AND area_code=? ORDER BY equipment_id""",
            (WIZARD_SITE_ID, area_code),
        )
    ]
    area["linked_equipment"] = [e["equipment_id"] for e in eqs]
    area["equipment_labels"] = {
        e["equipment_id"]: f"{e['equipment_id']} {e['name']}" for e in eqs
    }
    tokens = [x for x in str(area.get("linked_cas") or "").split(",") if x]
    area["linked_cas_list"] = tokens
    labels = {}
    for token in tokens:
        bits = token.split("|")
        cas = bits[0]
        pid = bits[1] if len(bits) > 1 else ""
        chem = conn.execute(
            "SELECT name FROM chemical WHERE cas=? AND (?='' OR process_id=?) ORDER BY process_id",
            (cas, pid, pid),
        ).fetchone()
        labels[token] = f"{cas} {chem['name']}" if chem else token
    area["chemical_labels"] = labels
    return area


def _save_wizard_chemical(
    conn,
    *,
    cas: str,
    process_id: str,
    name: str,
    role: str,
    h_codes: str,
    sds: str,
    sds_id: str,
    kind: str,
    mix_name: str,
    pct_lo: str,
    pct_hi: str,
    basis: str,
    total_kg: str,
    is_aqueous: str,
    formula: str,
    un_number: str = "",
    concentration_range: str = "",
    phase_state: str = "",
    name_en: str = "",
    attributed_qty: str = "",
    aqueous_status: str = "",
) -> str:
    filled = fil.annex_fill_blanks(cas, {"cas": cas, "name": name}, keys=("cas", "name"))
    if not str(filled.get("name") or "").strip():
        raise PsmError("未列於危險物／有害物清單者須自行填名稱")
    if not fil.parse_h_codes(h_codes):
        raise PsmError("化學品必填 GHS H 代碼")
    sid = (sds_id or "").strip() or None
    svc.save_chemical(
        conn,
        {
            "cas": filled["cas"],
            "process_id": process_id,
            "name": filled["name"],
            "role": role or "原物料",
            "h_codes": h_codes,
            "sds_id": sid,
            "sds_file": sds,
            "un_number": un_number,
            "concentration_range": concentration_range or pct_hi,
            "purity_or_mixture": kind or "純物質",
            "mixture_name": mix_name,
            "pct_lo": pct_lo,
            "pct_hi": pct_hi or concentration_range,
            "basis": basis,
            "total_kg": total_kg,
            "phase_state": phase_state,
            "name_en": name_en,
            "attributed_qty": attributed_qty,
            "aqueous_status": aqueous_status,
        },
    )
    stored = conn.execute(
        """SELECT c.sds_id FROM chemical c JOIN sds s ON s.sds_id=c.sds_id
           WHERE c.cas=? AND c.process_id=? AND s.file_path=? ORDER BY c.sds_id""",
        (filled["cas"], process_id, sds),
    ).fetchone()
    stored_sds_id = sid or (stored["sds_id"] if stored else "")
    if kind == "混合物":
        mix = {
            "mix_name": mix_name or filled["name"],
            "sds_id": stored_sds_id,
            "process_id": process_id,
            "cas": filled["cas"],
            "pct_lo": pct_lo,
            "pct_hi": pct_hi or concentration_range,
            "basis": basis or "重量比",
            "total_kg": total_kg,
            "phase_state": phase_state,
            "aqueous_status": aqueous_status,
            "is_aqueous": "1" if is_aqueous in ("1", "on", "true") else "0",
            "formula": formula or "操作量（kg）×重量百分比÷100＝純物質量（kg）",
            "h_codes": h_codes,
            "name": filled["name"],
        }
        checked = fil.attach_annex_check(mix)
        legacy_sds_id = sds_id or str(sds).replace("\\", "/").rsplit("/", 1)[-1]
        existing = next((r for r in fil.list_rows(conn, WIZARD_SITE_ID, "mix")
                         if (r.get("cas"), r.get("process_id")) == (mix["cas"], mix["process_id"])
                         and r.get("sds_id") in (stored_sds_id, legacy_sds_id)), None)
        if existing:
            fil.update_payload(conn, existing["row_id"], checked)
        else:
            fil.add_row(conn, WIZARD_SITE_ID, "mix", checked)
    return stored_sds_id


def _delete_mix_entries(conn, anchor_row_id: int, *, whole_group: bool) -> bool:
    """Remove one mixture component or its entire visible table row."""
    sid = WIZARD_SITE_ID
    rows = fil.list_rows(conn, sid, "mix")
    anchor = next((r for r in rows if r["row_id"] == anchor_row_id), None)
    if not anchor or not conn.execute(
        "SELECT 1 FROM process WHERE process_id=? AND site_id=?",
        (anchor.get("process_id"), sid),
    ).fetchone():
        return False
    group_key = tuple(anchor.get(k) or "" for k in ("process_id", "mix_name", "sds_id"))
    selected = (
        [r for r in rows if tuple(r.get(k) or "" for k in ("process_id", "mix_name", "sds_id")) == group_key]
        if whole_group else [anchor]
    )
    removed_ids = {r["row_id"] for r in selected}
    remaining = [r for r in rows if r["row_id"] not in removed_ids]

    def chemical_key(row: dict) -> tuple[str, str, str] | None:
        cas, process_id = row.get("cas") or "", row.get("process_id") or ""
        if not cas or not process_id:
            return None
        chemicals = conn.execute(
            """SELECT c.process_id, c.sds_id, c.cas, c.mixture_name
               FROM chemical c JOIN process p ON p.process_id=c.process_id
               WHERE c.cas=? AND c.process_id=? AND p.site_id=?""",
            (cas, process_id, sid),
        ).fetchall()
        if not chemicals:
            return None
        exact = [c for c in chemicals if c["sds_id"] == (row.get("sds_id") or "")]
        named = [c for c in chemicals if c["mixture_name"] == (row.get("mix_name") or "")]
        matches = exact or named or chemicals
        if len(matches) != 1:
            raise PsmError("同一成分對應多份 SDS，無法確定要刪除哪筆；請先確認化學品資料")
        chemical = matches[0]
        return chemical["process_id"], chemical["sds_id"], chemical["cas"]

    try:
        for row in selected:
            conn.execute(
                "DELETE FROM filing_row WHERE site_id=? AND section='mix' AND row_id=?",
                (sid, row["row_id"]),
            )
        deleted_chemicals: set[tuple[str, str, str]] = set()
        for row in selected:
            key = chemical_key(row)
            if key is None or key in deleted_chemicals:
                continue
            if any(
                chemical_key(other) == key for other in remaining
                if other.get("cas") == key[2] and other.get("process_id") == key[0]
            ):
                continue
            delete_item.delete_record(
                conn, sid, "chemical",
                {"process_id": key[0], "sds_id": key[1], "cas": key[2]},
                commit=False,
            )
            deleted_chemicals.add(key)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


def _next_step(message: str) -> str:
    text = (message or "未能完成儲存").strip()
    if "請" not in text:
        text += "。請依這項說明修正標示欄位後再儲存"
    if "保留" not in text:
        text += "。目前填寫的內容會保留"
    return text


def register_wizard(app, *, get_conn, render, redirect_ok, redirect_err):
    @app.middleware("http")
    async def partial_validation_stays(request: Request, call_next):
        response = await call_next(request)
        if request.headers.get("x-psm-partial") != "1" or response.status_code not in (301, 302, 303, 307, 308):
            return response
        query = parse_qs(urlparse(response.headers.get("location", "")).query)
        if "err" not in query:
            return response
        return _json_err(_next_step(query["err"][0]))

    def _fail(request: Request, url: str, message: str, fields: list[str] | None = None):
        if _partial(request):
            body = {"ok": False, "message": _next_step(message)}
            if fields:
                body["fields"] = fields
            return JSONResponse(body, status_code=400)
        return redirect_err(url, message)

    def _guard(conn, step: int):
        if step < 1 or step > wiz.N_STEPS:
            return redirect_err("/wizard/1", "步驟不存在")
        if step > 1 and wiz.core_missing(conn, WIZARD_SITE_ID):
            return redirect_err("/wizard/1", "請先建立場所、部門、製程、設備、化學品與區域清單")
        return None

    @app.post("/wizard/document/create")
    def wizard_document_create(
        step: int = Form(...), purpose: str = Form(...), document_no: str = Form(...),
        title: str = Form(...), revision_date: str = Form(...), document_id: str = Form(""),
        file: UploadFile | None = File(None),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, step)
            if blocked:
                return blocked
            if purpose not in dict(wiz.document_requirements(conn, WIZARD_SITE_ID, step)):
                return redirect_err(f"/wizard/{step}", "文件用途不屬於本章")
            number, name, revised = document_no.strip(), title.strip(), revision_date.strip()
            try:
                date.fromisoformat(revised)
            except ValueError:
                return redirect_err(f"/wizard/{step}", "請填有效的文件修訂日期")
            existing_doc = None
            if document_id.strip():
                existing_doc = conn.execute(
                    "SELECT * FROM filing_document WHERE document_id=? AND site_id=?",
                    (document_id.strip(), WIZARD_SITE_ID),
                ).fetchone()
                if not existing_doc:
                    return redirect_err(f"/wizard/{step}", "找不到本場所的文件資料")
            if not number or not name or (not existing_doc and not getattr(file, "filename", "")):
                return redirect_err(f"/wizard/{step}", "請填文件編號、名稱並選擇實際檔案")
            duplicate = conn.execute(
                """SELECT document_id FROM filing_document
                   WHERE site_id=? AND document_no=? AND revision_date=?
                     AND document_id<>COALESCE(?, -1)""",
                (WIZARD_SITE_ID, number, revised, existing_doc["document_id"] if existing_doc else None),
            ).fetchone()
            if duplicate:
                return redirect_err(f"/wizard/{step}", "同一編號及修訂日期已上傳，請從既有文件選取")
            path = wiz.store_upload(WIZARD_SITE_ID, f"doc-{uuid4().hex}", file, "") if file and file.filename else None
            if existing_doc:
                conn.execute(
                    """UPDATE filing_document SET title=?,attachment_path=?
                       WHERE document_id=? AND site_id=?""",
                    (name, path or existing_doc["attachment_path"], existing_doc["document_id"], WIZARD_SITE_ID),
                )
                doc_id = existing_doc["document_id"]
            else:
                doc_id = conn.execute(
                    """INSERT INTO filing_document(site_id,document_no,title,revision_date,attachment_path)
                       VALUES (?,?,?,?,?)""",
                    (WIZARD_SITE_ID, number, name, revised, path),
                ).lastrowid
            conn.execute(
                """INSERT INTO filing_document_ref(site_id,step,purpose,document_id)
                   VALUES (?,?,?,?)""",
                (WIZARD_SITE_ID, step, purpose, doc_id),
            )
            conn.commit()
        finally:
            conn.close()
        return redirect_ok(f"/wizard/{step}", "文件資料已更新" if existing_doc else "文件已上傳並關聯本章")

    @app.post("/wizard/document/link")
    def wizard_document_link(
        step: int = Form(...), purpose: str = Form(...), document_id: int = Form(...),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, step)
            if blocked:
                return blocked
            if purpose not in dict(wiz.document_requirements(conn, WIZARD_SITE_ID, step)):
                return redirect_err(f"/wizard/{step}", "文件用途不屬於本章")
            doc = conn.execute(
                "SELECT attachment_path FROM filing_document WHERE document_id=? AND site_id=?",
                (document_id, WIZARD_SITE_ID),
            ).fetchone()
            if not doc or not wiz.has_uploaded_file(doc["attachment_path"]):
                return redirect_err(f"/wizard/{step}", "請選擇本場所已上傳的文件")
            conn.execute(
                """INSERT OR IGNORE INTO filing_document_ref(site_id,step,purpose,document_id)
                   VALUES (?,?,?,?)""",
                (WIZARD_SITE_ID, step, purpose, document_id),
            )
            conn.commit()
        finally:
            conn.close()
        return redirect_ok(f"/wizard/{step}", "已引用既有文件")

    @app.post("/wizard/document/unlink")
    def wizard_document_unlink(
        step: int = Form(...), purpose: str = Form(...), document_id: int = Form(...),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, step)
            if blocked:
                return blocked
            conn.execute(
                """DELETE FROM filing_document_ref
                   WHERE site_id=? AND step=? AND purpose=? AND document_id=?""",
                (WIZARD_SITE_ID, step, purpose, document_id),
            )
            conn.commit()
        finally:
            conn.close()
        return redirect_ok(f"/wizard/{step}", "已解除本章文件關聯；原檔仍供其他章節引用")

    def _wizard_extra(conn, step: int, request: Request | None = None) -> dict:
        sid = WIZARD_SITE_ID
        wsite = conn.execute("SELECT * FROM site WHERE site_id=?", (sid,)).fetchone()
        unlocked = wiz.unlocked_step(conn, sid)
        core_missing = wiz.core_missing(conn, sid)
        missing = wiz.step_missing(conn, sid, step)
        attachment_only = bool(missing) and all(
            item.startswith(("表1.0-5 區域位置圖", "表1.0-4 SDS", "表1.7-1 圖資"))
            for item in missing
        )
        steps_out = [{**s, "done": wiz.step_done(conn, sid, s["n"])} for s in wiz.STEPS]
        extra = {
            "step": step,
            "n_steps": wiz.N_STEPS,
            "info": wiz.step_info(step),
            "steps": steps_out,
            "unlocked": unlocked,
            "core_ready": not core_missing,
            "core_missing": core_missing,
            "missing": missing,
            "attachment_only": attachment_only,
            "can_next": not core_missing,
            "wsite": dict(wsite) if wsite else None,
            "tally": wiz.counts(conn, sid),
            "secret_uploads": [
                dict(r) for r in conn.execute(
                    """SELECT attachment_id, original_name, note FROM unstructured_attachment
                       WHERE site_id=? AND kind='trade_secret' ORDER BY attachment_id""",
                    (sid,),
                )
            ],
            "shared_uploads": [
                dict(r) for r in conn.execute(
                    """SELECT u.attachment_id, u.kind, u.original_name, u.attachment_path
                       FROM unstructured_attachment u
                       LEFT JOIN process p ON p.process_id=u.process_id
                       WHERE u.site_id=? OR p.site_id=? ORDER BY u.attachment_id""",
                    (sid, sid),
                ) if wiz.has_uploaded_file(r["attachment_path"])
            ],
            "departments": [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM department WHERE site_id=? ORDER BY dept_id", (sid,)
                )
            ],
            "processes": [
                dict(r)
                for r in conn.execute(
                    """SELECT p.*, d.name AS operating_dept_name
                       FROM process p JOIN department d ON d.dept_id=p.operating_dept_id
                       WHERE p.site_id=? ORDER BY p.process_id""",
                    (sid,),
                )
            ],
            "areas": [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM area WHERE site_id=? ORDER BY area_code", (sid,)
                )
            ],
            "equipment": svc.equipment_list_joined(conn, sid),
            "design_codes": [
                dict(r) for r in conn.execute(
                    """SELECT dc.code_id, dc.process_id, dc.item AS material, dc.code AS spec,
                              dc.material_category, dc.scope,
                              (SELECT GROUP_CONCAT(p.process_id, '、') FROM design_code_process p WHERE p.code_id=dc.code_id) AS processes,
                              (SELECT GROUP_CONCAT(e.equipment_id, '、') FROM design_code_equipment e WHERE e.code_id=dc.code_id) AS equipment_ids,
                              (SELECT GROUP_CONCAT(e.equipment_id, ',') FROM design_code_equipment e WHERE e.code_id=dc.code_id) AS equipment_values,
                              (SELECT GROUP_CONCAT(c.cas, '、') FROM design_code_chemical c WHERE c.code_id=dc.code_id) AS cas_list,
                              (SELECT GROUP_CONCAT(c.cas, ',') FROM design_code_chemical c WHERE c.code_id=dc.code_id) AS chemical_values
                       FROM design_code dc JOIN design_code_process link ON link.code_id=dc.code_id
                       JOIN process p ON p.process_id=link.process_id WHERE p.site_id=?
                       GROUP BY dc.code_id ORDER BY dc.code_id""",
                    (sid,),
                )
            ],
            "chemicals": [
                dict(r)
                for r in conn.execute(
                    """SELECT c.*, p.name AS process_name, p.operating_dept_id,
                              i.max_kg AS inv_max_kg, i.area_code AS inv_area_code,
                              s.file_path AS sds_file
                       FROM chemical c
                       JOIN process p ON p.process_id=c.process_id
                       LEFT JOIN sds s ON s.sds_id=c.sds_id
                       LEFT JOIN inventory i ON i.cas=c.cas AND i.process_id=c.process_id
                       WHERE p.site_id=? ORDER BY c.cas, c.process_id""",
                    (sid,),
                )
            ],
            "eq_all": [
                dict(r)
                for r in conn.execute(
                    """SELECT e.equipment_id, e.process_id, e.name, e.equipment_type,
                              e.power_kind,
                              COALESCE(m.material, e.material) AS material,
                              COALESCE(NULLIF(m.material_category, ''), e.material_category) AS material_category,
                              m.spec AS design_spec,
                              e.area_code,
                              e.is_regulated_machinery, e.is_high_pressure_gas, e.legal_cert_type
                       FROM equipment e
                       LEFT JOIN equipment_material m ON m.equipment_id=e.equipment_id
                       WHERE e.site_id=? ORDER BY e.equipment_id""",
                    (sid,),
                )
            ],
            "drawings": [
                dict(r)
                for r in conn.execute(
                    """SELECT d.*, GROUP_CONCAT(c.equipment_id) AS covering
                       FROM pid_drawing d
                       JOIN process p ON p.process_id=d.process_id
                       LEFT JOIN pid_covering c
                         ON c.drawing_no=d.drawing_no AND c.revision=d.revision
                       WHERE p.site_id=?
                       GROUP BY d.drawing_no, d.revision""",
                    (sid,),
                )
            ],
            "limits": [
                dict(r)
                for r in conn.execute(
                    """SELECT l.* FROM equipment_limit l
                       JOIN equipment e ON e.equipment_id=l.equipment_id
                       WHERE e.site_id=?""",
                    (sid,),
                )
            ],
            "prefill": wiz.PREFILL,
        }
        extra.update(wiz.page_extra(conn, sid, step))
        extra["legal_equipment"] = fil.legal_equipment(conn, sid)
        contents_by_eq: dict[str, list[str]] = {}
        for c in extra.get("contents") or []:
            contents_by_eq.setdefault(c["equipment_id"], []).append(c.get("cas") or "")
        pid_by_eq: dict[str, str] = {}
        for d in extra["drawings"]:
            d["is_uploaded"] = wiz.has_uploaded_file(d.get("attachment_path"))
            for eid in str(d.get("covering") or "").split(","):
                eid = eid.strip()
                if eid and eid not in pid_by_eq:
                    pid_by_eq[eid] = d["drawing_no"]
        for c in extra["chemicals"]:
            c["h_flags"] = fil.h_code_flags(c.get("h_codes") or "")
            c["special_ref"] = fil.SPECIAL_CHEM_REF.get(c["cas"])
            c["annex"] = fil.lookup_annex(c.get("cas"))
        for e in extra["eq_all"]:
            e["mi_type"] = fil.mi_type_suggest(e.get("equipment_type") or "", e.get("power_kind"))
            e["contents"] = ",".join(x for x in contents_by_eq.get(e["equipment_id"], []) if x)
            e["pid_no"] = pid_by_eq.get(e["equipment_id"], "")
            e["query"] = svc.mi_query_ready(conn, e["equipment_id"])
        extra["contents_by_eq"] = contents_by_eq
        proc_ids = [p["process_id"] for p in extra["processes"]]
        default_pid = proc_ids[0] if proc_ids else ""
        want_pid = ""
        if request is not None:
            want_pid = str(request.query_params.get("block_process") or "").strip()
        if not want_pid:
            want_pid = str((extra.get("flags") or {}).get("ov_process") or "").strip()
        if want_pid not in proc_ids:
            want_pid = default_pid
        extra["block_process"] = want_pid
        extra["block_process_row"] = next(
            (p for p in extra["processes"] if p["process_id"] == want_pid), None
        )
        all_blocks = extra.get("rows", {}).get("1.3b") or []
        named = {p["process_id"]: p.get("name") or "" for p in extra["processes"]}
        extra["flow_blocks"] = []
        for r in all_blocks:
            pid = str(r.get("process_id") or "") or default_pid
            nxt = str(r.get("next_process_id") or "")
            extra["flow_blocks"].append(
                {
                    **r,
                    "process_id": pid,
                    "process_name": named.get(pid, ""),
                    "next_process_name": named.get(nxt, ""),
                }
            )
        scoped = [
            r
            for r in extra["flow_blocks"]
            if str(r.get("process_id") or "") == want_pid
            or (not str(r.get("process_id") or "") and want_pid == default_pid)
        ]
        named = [
            r
            for r in scoped
            if str(r.get("name") or "").strip()
            or str(r.get("equipment_id") or "").strip()
            or str(r.get("desc") or "").strip()
        ]
        drafts: list[dict] = []
        if not named and want_pid:
            seq = 1
            for e in extra["eq_all"]:
                if e.get("process_id") != want_pid or seq > 15:
                    continue
                drafts.append(
                    {
                        "seq": str(seq),
                        "name": e.get("name") or e["equipment_id"],
                        "desc": "表1.0-3 已列設備",
                        "next": "",
                        "equipment_id": e["equipment_id"],
                        "next_process_id": "",
                        "process_id": want_pid,
                        "x": 24 + ((seq - 1) % 5) * 200,
                        "y": 36 + ((seq - 1) // 5) * 130,
                    }
                )
                seq += 1
            seen_cas: set[str] = set()
            for c in extra["chemicals"]:
                if c.get("process_id") != want_pid or seq > 15:
                    continue
                cas = str(c.get("cas") or "")
                if cas in seen_cas:
                    continue
                seen_cas.add(cas)
                drafts.append(
                    {
                        "seq": str(seq),
                        "name": c.get("name") or cas,
                        "desc": f"表1.0-4 {cas}".strip(),
                        "next": "",
                        "equipment_id": "",
                        "next_process_id": "",
                        "process_id": want_pid,
                        "x": 24 + ((seq - 1) % 5) * 200,
                        "y": 36 + ((seq - 1) // 5) * 130,
                    }
                )
                seq += 1
        extra["block_from_lists"] = not named
        extra["block_draft_count"] = len(drafts)
        by_n = {str(r.get("seq")): r for r in (named or drafts)}
        extra["blocks_15"] = [
            by_n.get(
                str(i),
                {
                    "seq": str(i),
                    "name": "",
                    "desc": "",
                    "next": "",
                    "equipment_id": "",
                    "next_process_id": "",
                    "process_id": want_pid,
                },
            )
            for i in range(1, 16)
        ]
        for a in extra["areas"]:
            a["is_uploaded"] = wiz.has_uploaded_file(a.get("attachment_path"))
            a["linked_equipment"] = [
                e["equipment_id"] for e in extra["eq_all"] if e.get("area_code") == a.get("area_code")
            ]
            a["linked_cas_list"] = [x for x in str(a.get("linked_cas") or "").split(",") if x]
        return extra

    def _render_wizard(request: Request, step: int):
        conn = get_conn()
        try:
            unlocked = wiz.unlocked_step(conn, WIZARD_SITE_ID)
            if step < 1 or step > wiz.N_STEPS:
                return RedirectResponse("/wizard/1", status_code=303)
            if step > 1 and wiz.core_missing(conn, WIZARD_SITE_ID):
                return redirect_err("/wizard/1", "請先建立核心清單")
            extra = _wizard_extra(conn, step, request)
        finally:
            conn.close()
        # 首次填報從空白欄位開始；範例資料只由明確的按鈕載入。
        extra["prefill"] = {}
        extra["sample_case"] = wizard_case.get()
        return render(request, "wizard.html", title=f"第 {step} 步", **extra)

    def _apply_defaults(step: int):
        conn = get_conn()
        try:
            blocked = _guard(conn, step)
            if blocked:
                return blocked
            msg = wiz.apply_step_defaults(conn, WIZARD_SITE_ID, step)
        except PsmError as e:
            return redirect_err(f"/wizard/{step}", e.message)
        finally:
            conn.close()
        return redirect_ok(f"/wizard/{step}", msg)

    def _hazop_gone():
        return RedirectResponse(
            f"/wizard/2?err={quote('精靈不提供線上 HAZOP 節點或評分工作表')}",
            status_code=303,
        )

    @app.get("/wizard/start")
    def wizard_start():
        return RedirectResponse("/wizard/1", status_code=303)

    @app.get("/wizard")
    def wizard_resume():
        conn = get_conn()
        try:
            n = wiz.unlocked_step(conn, WIZARD_SITE_ID)
        finally:
            conn.close()
        return RedirectResponse(f"/wizard/{n}", status_code=303)

    @app.post("/wizard/defaults")
    def wizard_defaults_post(step: int = Form(...)):
        return _apply_defaults(step)

    @app.get("/wizard/defaults")
    def wizard_defaults_get():
        return RedirectResponse("/wizard/1", status_code=303)

    @app.get("/wizard/core-status")
    def wizard_core_status():
        conn = get_conn()
        try:
            missing = wiz.core_missing(conn, WIZARD_SITE_ID)
            return JSONResponse({"ready": not missing, "missing": missing})
        finally:
            conn.close()

    @app.post("/wizard/{step}/defaults")
    def wizard_apply_defaults(step: int):
        return _apply_defaults(step)

    @app.get("/wizard/{step}")
    def wizard_step(request: Request, step: int):
        return _render_wizard(request, step)

    @app.post("/wizard/14/upload")
    def wizard_secret_upload(
        attachment_id: str = Form(""),
        file: UploadFile | None = File(None),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, 14)
            if blocked:
                return blocked
            existing = None
            if attachment_id.strip():
                existing = conn.execute(
                    """SELECT attachment_id,original_name,attachment_path,note
                       FROM unstructured_attachment
                       WHERE attachment_id=? AND site_id=? AND kind='trade_secret'""",
                    (attachment_id.strip(), WIZARD_SITE_ID),
                ).fetchone()
                if not existing:
                    return redirect_err("/wizard/14", "找不到本場所的程序書附件")
            has_new_file = bool(file and file.filename)
            if not has_new_file and not existing:
                return redirect_err("/wizard/14", "請選擇程序書檔案")
            path = wiz.store_upload(WIZARD_SITE_ID, "trade-secret", file, "") if has_new_file else None
            if existing:
                conn.execute(
                    """UPDATE unstructured_attachment SET original_name=?,attachment_path=?,note=?
                       WHERE attachment_id=? AND site_id=?""",
                    (file.filename if has_new_file else existing["original_name"],
                     path or existing["attachment_path"],
                     "第十四章程序書" if has_new_file else existing["note"],
                     existing["attachment_id"], WIZARD_SITE_ID),
                )
            else:
                conn.execute(
                    """INSERT INTO unstructured_attachment(
                        site_id, process_id, kind, original_name, attachment_path, note
                    ) VALUES (?,?,?,?,?,?)""",
                    (WIZARD_SITE_ID, None, "trade_secret", file.filename, path, "第十四章程序書"),
                )
            conn.commit()
        finally:
            conn.close()
        return redirect_ok("/wizard/14", "程序書已更新" if existing else "程序書已上傳")

    @app.post("/wizard/6/contractor")
    def wizard_contractor(
        contractor_id: str = Form(""),
        name: str = Form(...),
        contract_period: str = Form(...),
        work_description: str = Form(""),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, 6)
            if blocked:
                return blocked
            svc.save_contractor(conn, {
                "site_id": WIZARD_SITE_ID,
                "contractor_id": int(contractor_id) if contractor_id.strip() else None,
                "name": name,
                "contract_period": contract_period, "work_description": work_description,
            })
        except PsmError as e:
            return redirect_err("/wizard/6", e.message)
        finally:
            conn.close()
        return redirect_ok("/wizard/6", "承攬商已登錄")

    @app.post("/wizard/6/contractor/delete")
    def wizard_contractor_delete(contractor_id: int = Form(...)):
        conn = get_conn()
        try:
            owned = conn.execute(
                "SELECT 1 FROM contractor WHERE contractor_id=? AND site_id=?",
                (contractor_id, WIZARD_SITE_ID),
            ).fetchone()
            if not owned:
                return redirect_err("/wizard/6", "找不到本場所的承攬商")
            linked = conn.execute(
                "SELECT 1 FROM contractor_incident WHERE contractor_id=?", (contractor_id,)
            ).fetchone()
            if linked:
                return redirect_err("/wizard/6", "請先處理這家承攬商的事故關聯")
            conn.execute("DELETE FROM contractor WHERE contractor_id=?", (contractor_id,))
            conn.commit()
        finally:
            conn.close()
        return redirect_ok("/wizard/6", "承攬商已刪除")

    @app.post("/wizard/6/incident")
    def wizard_contractor_link(
        incident_id: str = Form(""),
        contractor_id: int = Form(...),
        linked_incident_id: str = Form(""),
        summary: str = Form(""),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, 6)
            if blocked:
                return blocked
            svc.save_contractor_incident(conn, {
                "site_id": WIZARD_SITE_ID, "incident_id": incident_id,
                "contractor_id": contractor_id,
                "linked_incident_id": linked_incident_id, "summary": summary,
            })
        except PsmError as e:
            return redirect_err("/wizard/6", e.message)
        finally:
            conn.close()
        return redirect_ok("/wizard/6", "承攬事故關聯已存檔")

    @app.post("/wizard/11/incident/delete")
    def wizard_incident_delete(incident_id: str = Form(...)):
        conn = get_conn()
        try:
            owned = conn.execute(
                "SELECT 1 FROM incident WHERE incident_id=? AND site_id=?",
                (incident_id, WIZARD_SITE_ID),
            ).fetchone()
            if not owned:
                return redirect_err("/wizard/11", "找不到本場所的事故")
            if conn.execute(
                "SELECT 1 FROM contractor_incident WHERE linked_incident_id=?", (incident_id,)
            ).fetchone():
                return redirect_err("/wizard/11", "請先移除第六章的承攬事故關聯")
            conn.execute("DELETE FROM incident WHERE incident_id=?", (incident_id,))
            conn.commit()
        finally:
            conn.close()
        return redirect_ok("/wizard/11", "事故已刪除")

    @app.post("/wizard/1")
    def wizard_save_site(
        request: Request,
        company_name: str = Form(...),
        site_name: str = Form(...),
        scope: str = Form(...),
        applicant_name: str = Form(...),
        assessment_base_date: str = Form(...),
        worker_count: str = Form("0"),
        declare_no_equipment_types: str = Form(""),
        declare_no_contractor: str = Form(""),
        declare_no_hotwork: str = Form(""),
        declare_no_incident_5y: str = Form(""),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, 1)
            if blocked:
                return blocked
            svc.save_site(
                conn,
                {
                    "site_id": WIZARD_SITE_ID,
                    "company_name": company_name,
                    "site_name": site_name,
                    "scope": scope,
                    "applicant_name": applicant_name,
                    "assessment_base_date": assessment_base_date,
                    "worker_count": worker_count,
                    "declare_no_equipment_types": declare_no_equipment_types,
                    "declare_no_contractor": declare_no_contractor,
                    "declare_no_hotwork": declare_no_hotwork,
                    "declare_no_incident_5y": declare_no_incident_5y,
                },
            )
        except PsmError as e:
            if _partial(request):
                return _json_err(e.message)
            return redirect_err("/wizard/1", e.message)
        finally:
            conn.close()
        if _partial(request):
            return _json_ok()
        return redirect_ok("/wizard/1")

    @app.post("/wizard/1/dept")
    def wizard_dept(
        request: Request,
        dept_id: str = Form(...),
        name: str = Form(...),
        parent_dept_id: str = Form(""),
        headcount: str = Form("0"),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, 1)
            if blocked:
                return blocked
            svc.save_department(
                conn,
                {
                    "dept_id": dept_id,
                    "site_id": WIZARD_SITE_ID,
                    "name": name,
                    "parent_dept_id": parent_dept_id,
                    "headcount": headcount,
                },
            )
            row = {
                "dept_id": dept_id,
                "name": name,
                "parent_dept_id": parent_dept_id,
                "headcount": headcount,
            }
        except PsmError as e:
            if _partial(request):
                return _json_err(e.message)
            return redirect_err("/wizard/1", e.message)
        finally:
            conn.close()
        if _partial(request):
            return _json_ok({"kind": "department", "row": row})
        return redirect_ok("/wizard/1")

    @app.post("/wizard/1/process")
    def wizard_process(
        request: Request,
        process_id: str = Form(...),
        name: str = Form(...),
        operating_dept_id: str = Form(...),
        mode: str = Form(...),
        has_chemical_reaction: str = Form(""),
        has_overpressure: str = Form(""),
        is_special: str = Form(""),
        is_loading: str = Form(""),
        is_downstream: str = Form(""),
        overview: str = Form(""),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, 1)
            if blocked:
                return blocked
            svc.save_process(
                conn,
                {
                    "process_id": process_id,
                    "site_id": WIZARD_SITE_ID,
                    "name": name,
                    "operating_dept_id": operating_dept_id,
                    "mode": mode,
                    "has_chemical_reaction": has_chemical_reaction,
                    "has_overpressure": has_overpressure,
                    "is_special": is_special,
                    "is_loading": is_loading,
                    "is_downstream": is_downstream,
                    "overview": overview,
                },
            )
            row = {
                "process_id": process_id,
                "name": name,
                "operating_dept_id": operating_dept_id,
                "mode": mode,
                "has_chemical_reaction": has_chemical_reaction,
                "has_overpressure": has_overpressure,
                "is_special": is_special,
                "is_loading": is_loading,
                "is_downstream": is_downstream,
                "overview": overview,
            }
        except PsmError as e:
            if _partial(request):
                return _json_err(e.message)
            return redirect_err("/wizard/1", e.message)
        finally:
            conn.close()
        if _partial(request):
            return _json_ok({"kind": "process", "row": row})
        return redirect_ok("/wizard/1")

    @app.post("/wizard/1/area")
    def wizard_area(
        request: Request,
        area_code: str = Form(...),
        name: str = Form(...),
        drawing_no: str = Form(...),
        revision: str = Form(...),
        issue_date: str = Form(...),
        process_id: str = Form(""),
        file_name: str = Form(""),
        file: UploadFile | None = File(None),
        is_assembly_point: str = Form(""),
        is_control_room: str = Form(""),
        is_fire_system: str = Form(""),
        worker_count: str = Form("0"),
        contractor_count: str = Form("0"),
        visitor_count: str = Form("0"),
        linked_equipment: list[str] = Form(default=[]),
        linked_cas: list[str] = Form(default=[]),
    ):
        conn = get_conn()
        partial = _partial(request)
        try:
            blocked = _guard(conn, 1)
            if blocked:
                if partial:
                    return JSONResponse(
                        {"ok": False, "message": "請先完成目前步驟"},
                        status_code=400,
                    )
                return blocked
            path = wiz.store_upload(WIZARD_SITE_ID, "area", file, file_name)
            svc.save_area(
                conn,
                {
                    "area_code": area_code,
                    "site_id": WIZARD_SITE_ID,
                    "name": name,
                    "drawing_no": drawing_no,
                    "revision": revision,
                    "issue_date": issue_date,
                    "process_id": process_id,
                    "attachment_path": path or "placeholder://area",
                    "is_assembly_point": is_assembly_point,
                    "is_control_room": is_control_room,
                    "is_fire_system": is_fire_system,
                    "worker_count": worker_count,
                    "contractor_count": contractor_count,
                    "visitor_count": visitor_count,
                    "linked_cas": ",".join(linked_cas),
                },
            )
            if linked_equipment:
                svc.assign_area_equipment(conn, area_code, list(linked_equipment))
            if partial:
                return JSONResponse(
                    {"ok": True, "message": "已存檔", "area": _area_client_payload(conn, area_code)}
                )
        except PsmError as e:
            if partial:
                return JSONResponse({"ok": False, "message": e.message}, status_code=400)
            return redirect_err("/wizard/1", e.message)
        finally:
            conn.close()
        return redirect_ok("/wizard/1")

    @app.post("/wizard/1/equipment")
    def wizard_equipment(
        request: Request,
        equipment_id: str = Form(...),
        name: str = Form(...),
        process_id: str = Form(...),
        maint_dept_id: str = Form(...),
        equipment_type: str = Form(...),
        phase_class: str = Form("液體"),
        area_code: str = Form(""),
        material: str = Form(""),
        material_category: str = Form(""),
        power_kind: str = Form(""),
        is_safety_critical: str = Form(""),
        is_regulated_machinery: str = Form(""),
        is_high_pressure_gas: str = Form(""),
        legal_cert_type: str = Form(""),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, 1)
            if blocked:
                return blocked
            area = area_code or wiz.default_area_code(conn, WIZARD_SITE_ID, process_id)
            if not area:
                msg = "請先於表1.0-5 建立廠區區域，再於該表勾選關聯設備"
                if _partial(request):
                    return _json_err(msg)
                return redirect_err("/wizard/1", msg)
            svc.save_equipment(
                conn,
                {
                    "equipment_id": equipment_id,
                    "site_id": WIZARD_SITE_ID,
                    "name": name,
                    "process_id": process_id,
                    "maint_dept_id": maint_dept_id,
                    "equipment_type": equipment_type,
                    "phase_class": phase_class,
                    "area_code": area,
                    "material": material,
                    "material_category": material_category or wiz.guess_material_category(material),
                    "power_kind": power_kind or None,
                    "is_safety_critical": is_safety_critical or True,
                    "is_regulated_machinery": is_regulated_machinery,
                    "is_high_pressure_gas": is_high_pressure_gas,
                    "legal_cert_type": legal_cert_type,
                },
            )
            wiz.ensure_sops_for_types(conn, WIZARD_SITE_ID)
            row = {
                "equipment_id": equipment_id,
                "name": name,
                "process_id": process_id,
                "maint_dept_id": maint_dept_id,
                "equipment_type": equipment_type,
                "phase_class": phase_class,
                "material": material,
                "material_category": material_category,
                "power_kind": power_kind,
                "is_regulated_machinery": is_regulated_machinery,
                "is_high_pressure_gas": is_high_pressure_gas,
                "legal_cert_type": legal_cert_type,
            }
        except PsmError as e:
            if _partial(request):
                return _json_err(e.message)
            return redirect_err("/wizard/1", e.message)
        finally:
            conn.close()
        if _partial(request):
            return _json_ok({"kind": "equipment", "row": row})
        return redirect_ok("/wizard/1")

    @app.post("/wizard/1/chemical")
    async def wizard_chemical(request: Request):
        form = await request.form()
        conn = get_conn()
        partial = _partial(request)

        def bail(message: str):
            if partial:
                return _json_err(message)
            return redirect_err("/wizard/1", message)

        try:
            blocked = _guard(conn, 1)
            if blocked:
                return blocked
            kind = str(form.get("kind") or "純物質").strip() or "純物質"
            process_id = str(form.get("process_id") or "").strip()
            if not process_id:
                return bail("化學品須選製程")
            upload = form.get("file")
            sds = wiz.store_upload(
                WIZARD_SITE_ID, "sds", upload, str(form.get("file_name") or "")
            )
            if not sds:
                return bail("請上傳 SDS 或填檔名")
            sds_id = str(form.get("sds_id") or "").strip()
            basis = str(form.get("basis") or "重量比").strip() or "重量比"
            total_kg = str(form.get("total_kg") or "").strip()
            mix_name = str(form.get("mix_name") or "").strip()

            def _at(values, index: int) -> str:
                if index >= len(values):
                    return ""
                return str(values[index] or "").strip()

            if kind == "混合物":
                cases = form.getlist("comp_cas")
                names = form.getlist("comp_name")
                roles = form.getlist("comp_role")
                codes = form.getlist("comp_h")
                los = form.getlist("comp_pct_lo")
                his = form.getlist("comp_pct_hi")
                phases = form.getlist("comp_phase")
                aqueous_statuses = form.getlist("comp_aqueous_status")
                formulas = form.getlist("comp_formula")
                rows = []
                for i, raw in enumerate(cases):
                    cas = str(raw or "").strip()
                    if not cas:
                        continue
                    rows.append(
                        {
                            "cas": cas,
                            "name": _at(names, i),
                            "role": _at(roles, i) or "原物料",
                            "h_codes": _at(codes, i),
                            "pct_lo": _at(los, i),
                            "pct_hi": _at(his, i),
                            "phase_state": _at(phases, i),
                            "aqueous_status": _at(aqueous_statuses, i),
                            "formula": _at(formulas, i),
                        }
                    )
                if not rows:
                    return bail("混合物請在巢狀表至少填一列成分")
                if not mix_name:
                    return bail("混合物須填名稱")
                for row in rows:
                    if row["phase_state"] not in fil.PHASES:
                        return bail("每一成分須填常用狀況相態（固態、液態或氣態）")
                    if row["aqueous_status"] not in ("", "0", "1"):
                        return bail("請選擇有效的水溶液別")
                    row["is_aqueous"] = row["aqueous_status"]
                for row in rows:
                    row["sds_id"] = _save_wizard_chemical(
                        conn,
                        cas=row["cas"],
                        process_id=process_id,
                        name=row["name"],
                        role=row["role"],
                        h_codes=row["h_codes"],
                        sds=sds,
                        sds_id=sds_id,
                        kind="混合物",
                        mix_name=mix_name,
                        pct_lo=row["pct_lo"],
                        pct_hi=row["pct_hi"],
                        basis=basis,
                        total_kg=total_kg,
                        is_aqueous=row["is_aqueous"],
                        formula=row["formula"],
                        phase_state=row["phase_state"],
                        aqueous_status=row["aqueous_status"],
                    )
            else:
                phase_state = str(form.get("phase_state") or "").strip()
                if phase_state not in fil.PHASES:
                    return bail("請填常用狀況相態（固態、液態或氣態）")
                sds_id = _save_wizard_chemical(
                    conn,
                    cas=str(form.get("cas") or ""),
                    process_id=process_id,
                    name=str(form.get("name") or ""),
                    role=str(form.get("role") or "原物料"),
                    h_codes=str(form.get("h_codes") or ""),
                    sds=sds,
                    sds_id=sds_id,
                    kind="純物質",
                    mix_name="",
                    pct_lo="",
                    pct_hi=str(form.get("concentration_range") or ""),
                    basis=basis,
                    total_kg="",
                    is_aqueous=str(form.get("aqueous_status") or ""),
                    formula="",
                    phase_state=phase_state,
                    un_number=str(form.get("un_number") or ""),
                    concentration_range=str(form.get("concentration_range") or ""),
                    name_en=str(form.get("name_en") or ""),
                    attributed_qty=str(form.get("attributed_qty") or ""),
                    aqueous_status=str(form.get("aqueous_status") or ""),
                )
            saved = {
                "kind": kind,
                "process_id": process_id,
                "sds_id": sds_id,
                "name": mix_name or str(form.get("name") or ""),
                "name_en": str(form.get("name_en") or ""),
                "cas": str(form.get("cas") or ""),
                "role": str(form.get("role") or ""),
                "h_codes": str(form.get("h_codes") or ""),
                "phase_state": str(form.get("phase_state") or ""),
                "aqueous_status": str(form.get("aqueous_status") or ""),
                "attributed_qty": str(form.get("attributed_qty") or ""),
                "concentration_range": str(form.get("concentration_range") or ""),
            }
            if kind == "混合物":
                saved["components"] = [
                    {
                        "cas": r["cas"],
                        "name": r["name"],
                        "role": r["role"],
                        "h_codes": r["h_codes"],
                        "phase_state": r["phase_state"],
                        "aqueous_status": r["aqueous_status"],
                        "mix_name": mix_name,
                        "total_kg": total_kg,
                        "pct_lo": r["pct_lo"],
                        "pct_hi": r["pct_hi"],
                        "basis": basis,
                        "formula": r["formula"],
                        "process_id": process_id,
                        "sds_id": r["sds_id"],
                        "kind": "混合物",
                    }
                    for r in rows
                ]
            saved["psi_facts"] = fil.psi_chemical_facts(conn, WIZARD_SITE_ID)
        except PsmError as e:
            return bail(e.message)
        finally:
            conn.close()
        if partial:
            return _json_ok({"kind": "chemical", "row": saved})
        return redirect_ok("/wizard/1")

    @app.post("/wizard/1/pid")
    def wizard_pid(
        drawing_no: str = Form(...),
        revision: str = Form("A"),
        process_id: str = Form(...),
        name: str = Form(""),
        issue_date: str = Form(...),
        file_name: str = Form(""),
        file: UploadFile | None = File(None),
        covering: list[str] = Form(default=[]),
        eval_record_no: str = Form(""),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, 1)
            if blocked:
                return blocked
            if not drawing_no.strip() or not issue_date.strip():
                return redirect_err("/wizard/1", "1.7 須填圖號與日期")
            path = wiz.store_upload(WIZARD_SITE_ID, "pid", file, file_name)
            if not path:
                current = conn.execute(
                    "SELECT attachment_path FROM pid_drawing WHERE drawing_no=? AND revision=?",
                    (drawing_no, revision),
                ).fetchone()
                path = (current["attachment_path"] if current else None) or "placeholder://pid"
            conn.execute(
                """INSERT INTO pid_drawing(drawing_no, revision, process_id, name,
                    issue_date, is_as_built, attachment_path, eval_record_no)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(drawing_no, revision) DO UPDATE SET
                     process_id=excluded.process_id, name=excluded.name,
                     issue_date=excluded.issue_date, attachment_path=excluded.attachment_path,
                     eval_record_no=excluded.eval_record_no""",
                (drawing_no, revision, process_id, name or drawing_no, issue_date, 1, path, eval_record_no),
            )
            conn.execute(
                "DELETE FROM pid_covering WHERE drawing_no=? AND revision=?",
                (drawing_no, revision),
            )
            for eid in covering:
                if eid:
                    conn.execute(
                        "INSERT INTO pid_covering(drawing_no, revision, equipment_id) VALUES (?,?,?)",
                        (drawing_no, revision, eid),
                    )
            conn.commit()
        except PsmError as e:
            return redirect_err("/wizard/1", e.message)
        finally:
            conn.close()
        return redirect_ok("/wizard/1")

    @app.post("/wizard/1/limit")
    async def wizard_limit(request: Request):
        form = await request.form()
        conn = get_conn()
        try:
            blocked = _guard(conn, 1)
            if blocked:
                return blocked
            equipment_id = str(form.get("equipment_id") or "").strip()
            equipment = conn.execute(
                "SELECT process_id FROM equipment WHERE equipment_id=? AND site_id=?",
                (equipment_id, WIZARD_SITE_ID),
            ).fetchone()
            if not equipment:
                return redirect_err("/wizard/1", "1.5 須選本場所已建立的設備")
            selected = [str(p).strip() for p in form.getlist("review_parameter") if str(p).strip()]
            if not selected and form.get("parameter"):
                selected = [str(form.get("parameter")).strip()]
            if len(selected) != len(set(selected)) or any(p not in wiz.LIMIT_PARAMETERS for p in selected):
                return redirect_err("/wizard/1", "1.5 檢討參數只能各選一次壓力、溫度、流量或組成")
            no_parameter_reason = str(form.get("no_parameter_reason") or "").strip()
            if not selected and not no_parameter_reason:
                return redirect_err("/wizard/1", "未選界限參數須說明不適用原因")
            if selected and no_parameter_reason:
                return redirect_err("/wizard/1", "已選界限參數時不可填全部不適用原因")
            note = str(form.get("note") or "").strip()
            spec_map = {"壓力": ("kg/cm²G", "p_"), "溫度": ("℃", "t_"),
                        "流量": ("m³/hr", "f_"), "組成": ("%", "c_")}
            specs = []
            for param in selected:
                default_unit, prefix = spec_map[param]
                if form.get("parameter") and not form.getlist("review_parameter"):
                    prefix = ""
                unit = str(form.get(prefix + "unit") or default_unit).strip()
                values = {key: str(form.get(prefix + key) or "").strip()
                          for key in ("design_high", "design_low", "safety_high", "safety_low",
                                      "high_na_reason", "low_na_reason")}
                numeric_sides = 0
                for side, label in (("high", "上限"), ("low", "下限")):
                    design, safety = values[f"design_{side}"], values[f"safety_{side}"]
                    reason = values[f"{side}_na_reason"]
                    if design or safety:
                        try:
                            valid = Decimal(design).is_finite() and Decimal(safety).is_finite()
                        except InvalidOperation:
                            valid = False
                        if not valid or reason:
                            return redirect_err("/wizard/1", f"{param}{label}須同時填操作值及安全值，且不可填不適用理由")
                        numeric_sides += 1
                    elif not reason:
                        return redirect_err("/wizard/1", f"{param}{label}未填數值須說明不適用原因")
                if not unit or numeric_sides == 0:
                    return redirect_err("/wizard/1", f"{param}須有計算單位及至少一個方向的實際數值")
                old = conn.execute("SELECT limit_id FROM equipment_limit WHERE equipment_id=? AND parameter=?",
                                   (equipment_id, param)).fetchall()
                if len(old) > 1:
                    return redirect_err("/wizard/1", f"{param}已有重複界限列，請先核對並刪除多餘列")
                specs.append((param, unit, values, old[0]["limit_id"] if old else None))
            batch_raw = str(form.get("batch_qty") or "").strip()
            batch_unit = str(form.get("batch_unit") or "").strip()
            batch_na = str(form.get("batch_na_reason") or "").strip()
            quantity = None
            quantity_float = None
            if batch_raw:
                try:
                    quantity = Decimal(batch_raw)
                    quantity_float = float(quantity)
                except (InvalidOperation, ValueError):
                    quantity = None
                except OverflowError:
                    quantity = None
                if (quantity is None or not quantity.is_finite() or quantity <= 0 or
                        not isfinite(quantity_float or float("nan")) or not batch_unit or batch_na):
                    return redirect_err("/wizard/1", "單次操作量須為正數並填單位，且不可同時填不適用理由")
            elif not batch_na or batch_unit:
                return redirect_err("/wizard/1", "請填單次操作量與單位，或說明連續操作不適用")
            no_content = bool(form.get("no_process_chemical"))
            no_content_reason = str(form.get("no_content_reason") or "").strip()
            refs = [str(c).strip() for c in form.getlist("cas") if str(c).strip()]
            if no_content:
                if refs or not no_content_reason:
                    return redirect_err("/wizard/1", "聲明設備無操作化學品須填理由，且不可同時選內容物")
            elif not refs or no_content_reason:
                return redirect_err("/wizard/1", "請選實際內容物及 SDS；若無則勾選並說明理由")
            content_refs = []
            for ref in refs:
                bits = ref.split("|", 2)
                if len(bits) != 3 or bits[1] != equipment["process_id"] or not conn.execute(
                    "SELECT 1 FROM chemical WHERE cas=? AND process_id=? AND sds_id=?",
                    (bits[0], bits[1], bits[2]),
                ).fetchone():
                    return redirect_err("/wizard/1", "內容物須選本設備製程已建立的化學品及對應 SDS")
                content_refs.append((bits[0], bits[2]))
            vol = str(form.get("volume") or "").strip()
            if vol:
                try:
                    if not Decimal(vol).is_finite() or Decimal(vol) <= 0:
                        raise InvalidOperation
                except InvalidOperation:
                    return redirect_err("/wizard/1", "容積須為正數")
            conn.execute(
                """INSERT INTO equipment_operating_review
                   (equipment_id,selected_parameters,no_parameter_reason,batch_quantity,
                    batch_unit,batch_na_reason,no_content_reason) VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(equipment_id) DO UPDATE SET
                   selected_parameters=excluded.selected_parameters,
                   no_parameter_reason=excluded.no_parameter_reason,
                   batch_quantity=excluded.batch_quantity,batch_unit=excluded.batch_unit,
                   batch_na_reason=excluded.batch_na_reason,no_content_reason=excluded.no_content_reason""",
                (equipment_id, json.dumps(selected, ensure_ascii=False), no_parameter_reason,
                 quantity_float, batch_unit, batch_na, no_content_reason),
            )
            for param, unit, values, limit_id in specs:
                fields = (unit, values["design_high"], values["design_low"],
                          values["safety_high"], values["safety_low"],
                          values["high_na_reason"], values["low_na_reason"], note)
                if limit_id:
                    conn.execute(
                        """UPDATE equipment_limit SET unit=?,design_high=?,design_low=?,
                           safety_high=?,safety_low=?,high_na_reason=?,low_na_reason=?,note=?
                           WHERE limit_id=?""", (*fields, limit_id),
                    )
                else:
                    conn.execute(
                        """INSERT INTO equipment_limit(equipment_id,parameter,unit,design_high,
                           design_low,safety_high,safety_low,high_na_reason,low_na_reason,note)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""", (equipment_id, param, *fields),
                    )
            if vol:
                old_vol = conn.execute(
                    "SELECT limit_id FROM equipment_limit WHERE equipment_id=? AND parameter='容積' ORDER BY limit_id LIMIT 1",
                    (equipment_id,),
                ).fetchone()
                if old_vol:
                    conn.execute("UPDATE equipment_limit SET unit='L',design_high=?,note=? WHERE limit_id=?",
                                 (vol, note, old_vol["limit_id"]))
                else:
                    conn.execute(
                        """INSERT INTO equipment_limit(equipment_id,parameter,unit,design_high,note)
                           VALUES (?,'容積','L',?,?)""", (equipment_id, vol, note),
                    )
            conn.execute("DELETE FROM equipment_content WHERE equipment_id=?", (equipment_id,))
            if no_content:
                conn.execute(
                    """INSERT INTO equipment_content(equipment_id,cas,no_process_chemical,sds_id)
                       VALUES (?,'',1,'')""", (equipment_id,),
                )
            else:
                for cas, sds_id in sorted(set(content_refs)):
                    conn.execute(
                        """INSERT INTO equipment_content(equipment_id,cas,no_process_chemical,sds_id)
                           VALUES (?,?,0,?)""", (equipment_id, cas, sds_id),
                    )
            conn.commit()
        except sqlite3.IntegrityError:
            return redirect_err("/wizard/1", "1.5 資料關聯錯誤，請確認設備、化學品與 SDS")
        finally:
            conn.close()
        return redirect_ok("/wizard/1")

    @app.post("/wizard/2/upload")
    def wizard_pha_upload(
        process_id: str = Form(""),
        method: str = Form(""),
        record_id: str = Form(""),
        attachment_id: str = Form(""),
        question_count: str = Form(""),
        record_date: str = Form(""),
        file_name: str = Form(""),
        file: UploadFile | None = File(None),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, 2)
            if blocked:
                return blocked
            pid = (process_id or "").strip()
            if pid and not conn.execute("SELECT 1 FROM process WHERE process_id=?", (pid,)).fetchone():
                return redirect_err("/wizard/2", "所屬製程須選已建立的製程編號")
            rid = record_id.strip()
            existing_record = None
            existing_upload = None
            if rid:
                if method not in {key for key, _, _ in fil.PHA_METHODS}:
                    return redirect_err("/wizard/2", "請選有效的評估方法")
                try:
                    qty = int(question_count)
                except (TypeError, ValueError):
                    return redirect_err("/wizard/2", "考量問題數須為非負整數")
                if qty < 0 or not record_date.strip():
                    return redirect_err("/wizard/2", "請填非負整數的考量問題數及紀錄日期")
                existing_record = conn.execute(
                    """SELECT r.attachment_id,u.attachment_path,u.original_name
                       FROM pha_record r JOIN unstructured_attachment u
                         ON u.attachment_id=r.attachment_id
                       WHERE r.record_id=? AND r.site_id=?""",
                    (rid, WIZARD_SITE_ID),
                ).fetchone()
                if not existing_record and conn.execute(
                    "SELECT 1 FROM pha_record WHERE record_id=?", (rid,)
                ).fetchone():
                    return redirect_err("/wizard/2", "評估紀錄編號已由其他場所使用")
            elif attachment_id.strip():
                existing_upload = conn.execute(
                    """SELECT u.* FROM unstructured_attachment u
                       LEFT JOIN process p ON p.process_id=u.process_id
                       WHERE u.attachment_id=? AND (u.site_id=? OR p.site_id=?) AND u.kind='pha'
                         AND NOT EXISTS (SELECT 1 FROM pha_record r WHERE r.attachment_id=u.attachment_id)""",
                    (attachment_id.strip(), WIZARD_SITE_ID, WIZARD_SITE_ID),
                ).fetchone()
                if not existing_upload:
                    return redirect_err("/wizard/2", "找不到可修改的評估附件")
            has_new_file = bool(file and file.filename)
            if not existing_record and not existing_upload and not has_new_file:
                return redirect_err("/wizard/2", "請選擇實際檔案上傳；只填檔名不算完成")
            if has_new_file:
                path = wiz.store_upload(WIZARD_SITE_ID, "pha", file, "")
            if existing_record:
                conn.execute(
                    """UPDATE unstructured_attachment SET original_name=?,attachment_path=?,note=?
                       WHERE attachment_id=?""",
                    (file_name.strip() or (file.filename if has_new_file else existing_record["original_name"]),
                     path if has_new_file else existing_record["attachment_path"],
                     method, existing_record["attachment_id"]),
                )
                conn.execute(
                    """UPDATE pha_record SET method=?,question_count=?,record_date=?
                       WHERE record_id=? AND site_id=?""",
                    (method, qty, record_date.strip(), rid, WIZARD_SITE_ID),
                )
            elif existing_upload:
                conn.execute(
                    """UPDATE unstructured_attachment SET process_id=?,original_name=?,attachment_path=?,note=?
                       WHERE attachment_id=?""",
                    (pid or None, file_name.strip() or (file.filename if has_new_file else existing_upload["original_name"]),
                     path if has_new_file else existing_upload["attachment_path"], method,
                     existing_upload["attachment_id"]),
                )
            else:
                cursor = conn.execute(
                    """INSERT INTO unstructured_attachment(
                        process_id, kind, original_name, attachment_path, note, site_id
                    ) VALUES (?,?,?,?,?,?)""",
                    (None if rid else (pid or None), "pha", file_name.strip() or file.filename, path, method, WIZARD_SITE_ID),
                )
            if rid and not existing_record:
                conn.execute(
                    """INSERT INTO pha_record(record_id,site_id,method,question_count,record_date,attachment_id)
                       VALUES (?,?,?,?,?,?)""",
                    (rid, WIZARD_SITE_ID, method, qty, record_date.strip(), cursor.lastrowid),
                )
            conn.commit()
        except PsmError as e:
            return redirect_err("/wizard/2", e.message)
        finally:
            conn.close()
        return redirect_ok("/wizard/2", "評估紀錄已更新" if existing_record else "評估紀錄已上傳")

    @app.post("/wizard/2/record/delete")
    def wizard_pha_record_delete(record_id: str = Form(...)):
        conn = get_conn()
        try:
            record = conn.execute(
                "SELECT attachment_id FROM pha_record WHERE record_id=? AND site_id=?",
                (record_id, WIZARD_SITE_ID),
            ).fetchone()
            if not record:
                return redirect_err("/wizard/2", "找不到本場所的評估紀錄")
            if any(r.get("assessment_id") == record_id for r in fil.list_rows(conn, WIZARD_SITE_ID, "2.4")):
                return redirect_err("/wizard/2", "請先移除引用這份評估紀錄的高風險情境")
            conn.execute("DELETE FROM pha_record WHERE record_id=?", (record_id,))
            conn.execute("DELETE FROM unstructured_attachment WHERE attachment_id=?", (record["attachment_id"],))
            conn.commit()
        finally:
            conn.close()
        return redirect_ok("/wizard/2", "評估紀錄已刪除")

    @app.post("/wizard/4/sop")
    def wizard_sop(
        sop_id: str = Form(...),
        title: str = Form(...),
        process_id: str = Form(...),
        procedure_no: str = Form(""),
        equipment_id: str = Form(""),
        equipment_ids: list[str] = Form(default=[]),
        updated_on: str = Form(""),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, 4)
            if blocked:
                return blocked
            sop_id = sop_id.strip()
            title = title.strip()
            procedure_no = procedure_no.strip()
            process_id = process_id.strip()
            linked_ids = list(dict.fromkeys(str(v).strip() for v in equipment_ids if str(v).strip()))
            if not linked_ids and equipment_id.strip():
                linked_ids = [equipment_id.strip()]
            if not sop_id or not title or not procedure_no or not linked_ids:
                return redirect_err("/wizard/4", "4.1 須填程序編號、名稱及至少一台關聯設備")
            try:
                date.fromisoformat(updated_on.strip())
            except ValueError:
                return redirect_err("/wizard/4", "4.1 須填有效的最後修訂日期")
            if not conn.execute("SELECT 1 FROM process WHERE process_id=? AND site_id=?",
                                (process_id, WIZARD_SITE_ID)).fetchone():
                return redirect_err("/wizard/4", "4.1 須選本場所製程")
            data = {
                "sop_id": sop_id,
                "title": title,
                "process_id": process_id,
                "procedure_no": procedure_no,
                "body": "",
                "op_kind": "equipment",
                "equipment_id": linked_ids[0],
                "equipment_ids": linked_ids,
                "updated_on": updated_on.strip(),
            }
            svc.save_sop(conn, data)
        except PsmError as e:
            return redirect_err("/wizard/4", e.message)
        finally:
            conn.close()
        return redirect_ok("/wizard/4")

    @app.post("/wizard/4/sop/delete")
    def wizard_sop_delete(sop_id: str = Form(...)):
        conn = get_conn()
        try:
            blocked = _guard(conn, 4)
            if blocked:
                return blocked
            owned = conn.execute("SELECT 1 FROM sop s JOIN process p ON p.process_id=s.process_id WHERE s.sop_id=? AND p.site_id=?", (sop_id, WIZARD_SITE_ID)).fetchone()
            if not owned:
                return redirect_err("/wizard/4", "程序不存在")
            delete_item.delete_record(conn, WIZARD_SITE_ID, "sop", {"sop_id": sop_id})
        except PsmError as e:
            return redirect_err("/wizard/4", e.message)
        finally:
            conn.close()
        return redirect_ok("/wizard/4")

    @app.post("/wizard/5/course")
    def wizard_course(
        course_id: str = Form(...),
        name: str = Form(...),
        kind: str = Form(...),
        audience: str = Form(...),
        process_id: str = Form(...),
        hours: str = Form(""),
        sop_id: str = Form(""),
        sop_ids: list[str] = Form([]),
        no_sop_reason: str = Form(""),
        is_moc_related: str = Form(""),
        refresh_every: str = Form(""),
        refresh_hours: str = Form(""),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, 5)
            if blocked:
                return blocked
            existing = conn.execute("""SELECT p.site_id FROM training_course t
                JOIN process p ON p.process_id=t.process_id WHERE t.course_id=?""", (course_id,)).fetchone()
            if existing and existing["site_id"] != WIZARD_SITE_ID:
                return redirect_err("/wizard/5", "課程編號已由其他場所使用")
            try:
                init_hours = float(hours)
                retrain_hours = float(refresh_hours)
            except ValueError:
                return redirect_err("/wizard/5", "初訓與複訓時數須為正數")
            if not isfinite(init_hours) or not isfinite(retrain_hours) or init_hours <= 0 or retrain_hours <= 0 or not refresh_every.strip():
                return redirect_err("/wizard/5", "初訓與複訓時數須為正數，且須填複訓頻率")
            selected_sops = sop_ids or ([sop_id] if sop_id else [])
            if not selected_sops and not no_sop_reason.strip():
                return redirect_err("/wizard/5", "未關聯 SOP 的課程須說明原因")
            svc.save_training_course(
                conn,
                {
                    "course_id": course_id,
                    "name": name,
                    "kind": kind,
                    "audience": audience,
                    "process_id": process_id,
                    "hours": init_hours,
                    "op_kind": "process",
                    "sop_ids": selected_sops,
                    "no_sop_reason": no_sop_reason,
                    "is_moc_related": is_moc_related,
                    "refresh_every": refresh_every,
                    "refresh_hours": refresh_hours,
                },
            )
        except PsmError as e:
            return redirect_err("/wizard/5", e.message)
        finally:
            conn.close()
        return redirect_ok("/wizard/5")

    @app.post("/wizard/flags")
    async def wizard_flags(request: Request):
        form = await request.form()
        step = int(form.get("step") or 1)
        conn = get_conn()
        try:
            blocked = _guard(conn, step)
            if blocked:
                return blocked
            methods = form.getlist("pha_methods") if hasattr(form, "getlist") else []
            if str(form.getlist("no_art16")[-1] if form.getlist("no_art16") else "") == "1":
                if fil.legal_equipment(conn, WIZARD_SITE_ID) or fil.list_rows(conn, WIZARD_SITE_ID, "1.11"):
                    return redirect_err(f"/wizard/{step}", "表1.0-3 已有適用設備或表1.11 已有證明，不可聲明無適用設備")
            if "pha_methods_present" in form:
                fil.set_flag(conn, WIZARD_SITE_ID, "pha_methods", ",".join(str(m) for m in methods))
            skip = {"step", "pha_methods", "pha_methods_present", "ov_process", "rxn_process", "rxn_types", "rxn_type_other", "no_reaction_proc"}
            for k in form.keys():
                if k in skip:
                    continue
                vals = form.getlist(k) if hasattr(form, "getlist") else [form.get(k)]
                fil.set_flag(conn, WIZARD_SITE_ID, k, str(vals[-1] if vals else "") or "")
            ov = str(form.get("ov_process") or "").strip()
            if ov and "overview" in form:
                text = str(form.get("overview") or "")
                fil.set_flag(conn, WIZARD_SITE_ID, f"overview:{ov}", text)
                conn.execute(
                    "UPDATE process SET overview=? WHERE process_id=?", (text, ov)
                )
                conn.commit()
            rxn_proc = str(form.get("rxn_process") or "").strip()
            if rxn_proc:
                types = [str(t) for t in (form.getlist("rxn_types") if hasattr(form, "getlist") else []) if t]
                other = str(form.get("rxn_type_other") or "").strip()
                if "其他" in types and not other:
                    return redirect_err(
                        f"/wizard/{step}",
                        "勾選其他時請寫反應種類。請在彈出的視窗寫明實際反應種類後再儲存",
                    )
                if "其他" not in types:
                    other = ""
                fil.set_flag(
                    conn,
                    WIZARD_SITE_ID,
                    f"rxn_types:{rxn_proc}",
                    ",".join(types),
                )
                fil.set_flag(conn, WIZARD_SITE_ID, f"rxn_other:{rxn_proc}", other)
                fil.set_flag(
                    conn,
                    WIZARD_SITE_ID,
                    f"no_reaction:{rxn_proc}",
                    "1" if str(form.get("no_reaction_proc") or "") in ("1", "on") else "0",
                )
        finally:
            conn.close()
        return redirect_ok(f"/wizard/{step}")

    @app.post("/wizard/row")
    async def wizard_row(request: Request):
        form = await request.form()
        step = int(form.get("step") or 1)
        section = str(form.get("section") or "")
        conn = get_conn()
        try:
            blocked = _guard(conn, step)
            if blocked:
                return blocked
            raw_row_id = str(form.get("row_id") or "").strip()
            editing_row = None
            if raw_row_id:
                try:
                    row_id = int(raw_row_id)
                except ValueError:
                    return redirect_err(f"/wizard/{step}", "修改資料識別碼無效")
                editing_row = conn.execute(
                    "SELECT section,payload FROM filing_row WHERE site_id=? AND row_id=?",
                    (WIZARD_SITE_ID, row_id),
                ).fetchone()
                if not editing_row or editing_row["section"] != section:
                    return redirect_err(f"/wizard/{step}", "找不到本章可修改的資料列")
                editing_payload = json.loads(editing_row["payload"] or "{}")
            else:
                editing_payload = {}
            payload = {}
            for k in form.keys():
                if k in ("step", "section", "row_id", "drill_file"):
                    continue
                vals = form.getlist(k) if hasattr(form, "getlist") else [form.get(k)]
                vals = [str(v) for v in vals if v not in (None, "")]
                if k in ("is_danger", "is_harmful", "is_high_flammable", "is_high_toxic"):
                    payload[k] = "1" if any(v in ("on", "1", "true", "True", "是") for v in vals) else "0"
                else:
                    payload[k] = vals[0] if len(vals) == 1 else ",".join(vals)
            if section == "1.11":
                eid = str(payload.get("equipment_id") or "").strip()
                if not any(e["equipment_id"] == eid for e in fil.legal_equipment(conn, WIZARD_SITE_ID)):
                    return redirect_err("/wizard/1", "表1.11 須選表1.0-3 已勾選危險性機械設備或高壓氣體的設備")
                for key in ("category", "cert_no", "expire"):
                    payload[key] = str(payload.get(key) or "").strip()
                if not all(payload[k] for k in ("category", "cert_no", "expire")):
                    return redirect_err("/wizard/1", "表1.11 須填設備類別、檢查合格證號碼及有效期限")
                try:
                    date.fromisoformat(payload["expire"])
                except ValueError:
                    return redirect_err("/wizard/1", "表1.11 請填有效的合格證有效期限")
                payload["equipment_id"] = eid
            cas_key = payload.get("cas") or ""
            if "|" in cas_key:
                payload["cas"], proc = cas_key.split("|", 1)
                payload.setdefault("process_id", proc)
            if section == "10.1":
                process_ids = list(dict.fromkeys(str(v).strip() for v in form.getlist("process_ids") if str(v).strip()))
                equipment_ids = list(dict.fromkeys(str(v).strip() for v in form.getlist("equipment_ids") if str(v).strip()))
                chemical_refs = list(dict.fromkeys(str(v).strip() for v in form.getlist("chemical_refs") if str(v).strip()))
                if not process_ids or not all(str(payload.get(k) or "").strip() for k in ("change_id", "name", "description")):
                    return redirect_err("/wizard/10", "變更案件須填項次、名稱、說明及至少一個製程")
                if any(str(r.get("change_id") or "").strip() == str(payload["change_id"]).strip()
                       and (not editing_row or int(r.get("row_id") or 0) != row_id)
                       for r in fil.list_rows(conn, WIZARD_SITE_ID, "10.1")):
                    return redirect_err("/wizard/10", "變更管理項次已存在，請使用不同編號")
                for pid in process_ids:
                    if not conn.execute("SELECT 1 FROM process WHERE process_id=? AND site_id=?", (pid, WIZARD_SITE_ID)).fetchone():
                        return redirect_err("/wizard/10", "變更案件製程須屬本場所")
                for eid in equipment_ids:
                    row = conn.execute("SELECT process_id FROM equipment WHERE equipment_id=? AND site_id=?", (eid, WIZARD_SITE_ID)).fetchone()
                    if not row or row["process_id"] not in process_ids:
                        return redirect_err("/wizard/10", "變更案件設備須屬所選製程")
                for ref in chemical_refs:
                    parts = ref.split("|", 2)
                    if len(parts) != 3 or parts[1] not in process_ids or not conn.execute(
                        "SELECT 1 FROM chemical WHERE cas=? AND process_id=? AND sds_id=?",
                        (parts[0], parts[1], parts[2]),
                    ).fetchone():
                        return redirect_err("/wizard/10", "變更案件化學品須屬所選製程並有對應 SDS")
                payload.pop("process_id", None)
                payload.pop("equipment_id", None)
                payload.pop("cas", None)
                payload["process_ids"] = process_ids
                payload["equipment_ids"] = equipment_ids
                payload["chemical_refs"] = chemical_refs
            if section == "1.1":
                chem = conn.execute(
                    "SELECT name, h_codes FROM chemical WHERE cas=? AND process_id=?",
                    (payload.get("cas"), payload.get("process_id")),
                ).fetchone()
                if not chem:
                    return redirect_err("/wizard/1", "1.1 須選已有化學品（CAS＋製程）")
                payload["name"] = payload.get("name") or chem["name"]
                payload = fil.annex_fill_blanks(
                    payload.get("cas"), payload, keys=("name_en",)
                )
                hf = fil.h_code_flags(chem["h_codes"] or "")
                for bk in ("is_danger", "is_harmful", "is_high_flammable", "is_high_toxic"):
                    raw = payload.get(bk)
                    if raw in ("", None):
                        payload[bk] = hf[bk]
                    else:
                        payload[bk] = raw in ("on", "1", "true", "True", "是")
                if not payload.get("dept_id") or not payload.get("area_code") or not payload.get("max_kg"):
                    return redirect_err("/wizard/1", "1.1 使用單位、地點、最大存量必填")
                payload.update(fil.psi_chemical_facts(conn, WIZARD_SITE_ID).get(
                    f"{payload.get('cas')}|{payload.get('process_id')}", {}
                ))
            if section == "1.2":
                chem = conn.execute(
                    "SELECT name, h_codes, concentration_range FROM chemical WHERE cas=? AND process_id=?",
                    (payload.get("cas"), payload.get("process_id")),
                ).fetchone()
                if not chem:
                    return redirect_err("/wizard/1", "1.2 須選已有化學品（CAS＋製程）")
                payload["name"] = payload.get("name") or chem["name"]
                payload = fil.annex_fill_blanks(
                    payload.get("cas"), payload, keys=("name_en", "ctrl_qty")
                )
                payload.update(fil.psi_chemical_facts(conn, WIZARD_SITE_ID).get(
                    f"{payload.get('cas')}|{payload.get('process_id')}", {}
                ))
                payload.pop("state", None)
                hf = fil.h_code_flags(chem["h_codes"] or "")
                if not payload.get("physical"):
                    payload["physical"] = hf["physical_label"]
                if not payload.get("health"):
                    payload["health"] = hf["health_label"]
                if not payload.get("incompat"):
                    payload["incompat"] = "是" if hf["incompat_air_water"] else "否"
                if not payload.get("conc"):
                    payload["conc"] = chem["concentration_range"] or ""
                mix_rows = fil.list_rows(conn, WIZARD_SITE_ID, "mix")
                if not payload.get("conc"):
                    for m in mix_rows:
                        if m.get("cas") == payload.get("cas") and m.get("process_id") == payload.get("process_id"):
                            payload["conc"] = m.get("pct_hi") or m.get("pct_lo") or ""
                            break
            if section == "2.4":
                record_id = str(payload.get("assessment_id") or "").strip()
                process_id = str(payload.get("process_id") or "").strip()
                if not conn.execute(
                    "SELECT 1 FROM pha_record WHERE record_id=? AND site_id=?",
                    (record_id, WIZARD_SITE_ID),
                ).fetchone():
                    return redirect_err("/wizard/2", "請選表2.2-1 已上傳的評估紀錄編號")
                if not conn.execute(
                    "SELECT 1 FROM process WHERE process_id=? AND site_id=?",
                    (process_id, WIZARD_SITE_ID),
                ).fetchone():
                    return redirect_err("/wizard/2", "高風險情境須選本場所的製程")
                equipment_ids = [x.strip() for x in str(payload.get("equipment_id") or "").split(",") if x.strip()]
                for eid in equipment_ids:
                    if not conn.execute(
                        "SELECT 1 FROM equipment WHERE equipment_id=? AND process_id=? AND site_id=?",
                        (eid, process_id, WIZARD_SITE_ID),
                    ).fetchone():
                        return redirect_err("/wizard/2", "高風險情境的設備須屬於所選製程")
                payload["equipment_ids"] = equipment_ids
            if section == "12.1s":
                def selected(key: str) -> list[str]:
                    return list(dict.fromkeys(x.strip() for x in str(payload.get(key) or "").split(",") if x.strip()))

                process_ids = selected("process_ids")
                equipment_ids = selected("equipment_ids")
                chemical_refs = selected("chemical_refs")
                area_codes = selected("area_codes")
                if not str(payload.get("situation") or "").strip() or not str(payload.get("description") or "").strip():
                    return redirect_err("/wizard/12", "緊急狀況類別與原因說明必填")
                if not process_ids or not area_codes:
                    return redirect_err("/wizard/12", "緊急狀況須確認至少一個製程與區域")
                for pid in process_ids:
                    if not conn.execute("SELECT 1 FROM process WHERE process_id=? AND site_id=?",
                                        (pid, WIZARD_SITE_ID)).fetchone():
                        return redirect_err("/wizard/12", "製程須選本場所既有編號")
                for eid in equipment_ids:
                    eq = conn.execute("SELECT process_id FROM equipment WHERE equipment_id=? AND site_id=?",
                                      (eid, WIZARD_SITE_ID)).fetchone()
                    if not eq or eq["process_id"] not in process_ids:
                        return redirect_err("/wizard/12", "相關設備須屬於已選製程")
                for ref in chemical_refs:
                    parts = ref.split("|", 2)
                    if len(parts) != 3 or parts[0] not in process_ids or not conn.execute(
                        "SELECT 1 FROM chemical WHERE process_id=? AND COALESCE(sds_id,'')=? AND cas=?",
                        parts,
                    ).fetchone():
                        return redirect_err("/wizard/12", "相關化學品須屬於已選製程與 SDS")
                for area_code in area_codes:
                    if not conn.execute("SELECT 1 FROM area WHERE area_code=? AND site_id=?",
                                        (area_code, WIZARD_SITE_ID)).fetchone():
                        return redirect_err("/wizard/12", "區域須選本場所既有編號")
                muster = str(payload.get("muster") or "").strip()
                if not conn.execute("SELECT 1 FROM area WHERE area_code=? AND site_id=? AND is_assembly_point=1",
                                    (muster, WIZARD_SITE_ID)).fetchone():
                    return redirect_err("/wizard/12", "集合點須選表1.0-5 已確認的緊急集合區")
                if not equipment_ids and not str(payload.get("no_equipment_reason") or "").strip():
                    return redirect_err("/wizard/12", "未選相關設備須說明原因")
                if not chemical_refs and not str(payload.get("no_chemical_reason") or "").strip():
                    return redirect_err("/wizard/12", "未選相關化學品須說明原因")
                if not str(payload.get("drill_plan_scope") or "").strip():
                    return redirect_err("/wizard/12", "每個緊急狀況都須填演練計畫的涵蓋項目")
                drill_status = str(payload.get("drill_status") or "").strip()
                if drill_status == "已執行":
                    try:
                        date.fromisoformat(str(payload.get("drill_date") or ""))
                    except ValueError:
                        return redirect_err("/wizard/12", "已執行演練須填有效日期")
                    drill_file = form.get("drill_file")
                    if getattr(drill_file, "filename", "") and hasattr(drill_file, "file"):
                        payload["drill_record_name"] = drill_file.filename
                        payload["drill_record_path"] = wiz.store_upload(
                            WIZARD_SITE_ID, f"drill_{uuid4().hex}", drill_file, ""
                        )
                    elif wiz.has_uploaded_file(str(editing_payload.get("drill_record_path") or "")):
                        payload["drill_record_name"] = editing_payload.get("drill_record_name") or ""
                        payload["drill_record_path"] = editing_payload["drill_record_path"]
                    else:
                        return redirect_err("/wizard/12", "已執行演練須上傳對應紀錄")
                    payload.pop("drill_due", None)
                    payload.pop("drill_no_reason", None)
                elif drill_status == "尚未執行":
                    try:
                        date.fromisoformat(str(payload.get("drill_due") or ""))
                    except ValueError:
                        return redirect_err("/wizard/12", "尚未執行演練須填有效的預定日期")
                    if not str(payload.get("drill_no_reason") or "").strip():
                        return redirect_err("/wizard/12", "尚未執行演練須填原因")
                    payload.pop("drill_date", None)
                else:
                    return redirect_err("/wizard/12", "請確認此緊急狀況的演練執行狀態")
                payload.update(process_ids=process_ids, equipment_ids=equipment_ids,
                               chemical_refs=chemical_refs, area_codes=area_codes)
                for old_key in ("process_id", "equipment_id", "cas", "area_code"):
                    payload.pop(old_key, None)
            if section == "13.1":
                if fil.get_flag(conn, WIZARD_SITE_ID, "audit_first") != "否":
                    return redirect_err("/wizard/13", "請先確認已執行首次稽核")
                if not all(str(payload.get(key) or "").strip() for key in ("when", "dept_id", "unit", "auditor")):
                    return redirect_err("/wizard/13", "稽核時間、受稽核部門、PSM 單元與稽核員必填")
                try:
                    datetime.fromisoformat(str(payload["when"]))
                except ValueError:
                    return redirect_err("/wizard/13", "請填有效的稽核日期與時間")
                if not conn.execute("SELECT 1 FROM department WHERE dept_id=? AND site_id=?",
                                    (payload["dept_id"], WIZARD_SITE_ID)).fetchone():
                    return redirect_err("/wizard/13", "受稽核部門須選本場所部門")
            if section == "13.2":
                if fil.get_flag(conn, WIZARD_SITE_ID, "audit_first") != "否":
                    return redirect_err("/wizard/13", "請先確認已執行首次稽核")
                if fil.get_flag(conn, WIZARD_SITE_ID, "audit_zero") == "1":
                    return redirect_err("/wizard/13", "已聲明無不符合，請先取消聲明再新增改善事項")
                if not any(r.get("when") == payload.get("plan_when")
                           for r in fil.list_rows(conn, WIZARD_SITE_ID, "13.1")):
                    return redirect_err("/wizard/13", "改善事項須引用表13.1-1 既有稽核項次")
                if not all(str(payload.get(key) or "").strip() for key in ("finding", "action", "dept_id", "due")):
                    return redirect_err("/wizard/13", "改善事項、措施、負責部門與預定完成日期必填")
                if not conn.execute("SELECT 1 FROM department WHERE dept_id=? AND site_id=?",
                                    (payload["dept_id"], WIZARD_SITE_ID)).fetchone():
                    return redirect_err("/wizard/13", "負責部門須選本場所部門")
                try:
                    date.fromisoformat(str(payload["due"]))
                    if payload.get("done"):
                        date.fromisoformat(str(payload["done"]))
                except ValueError:
                    return redirect_err("/wizard/13", "改善日期須為有效日期")
            if section == "12.2":
                area_code = str(payload.get("area_code") or "").strip()
                area = conn.execute(
                    "SELECT 1 FROM area WHERE area_code=? AND site_id=?",
                    (area_code, WIZARD_SITE_ID),
                ).fetchone()
                if not area:
                    return redirect_err("/wizard/12", "搶救器材須選本場所已建立的區域")
                try:
                    quantity = Decimal(str(payload.get("qty") or ""))
                except InvalidOperation:
                    quantity = Decimal(0)
                if (not quantity.is_finite() or quantity <= 0 or
                        not str(payload.get("name") or "").strip() or
                        not str(payload.get("unit") or "").strip() or
                        not str(payload.get("freq") or "").strip()):
                    return redirect_err("/wizard/12", "器材須填名稱、正數數量、單位及檢點頻率")
                payload["qty"] = format(quantity.normalize(), "f")
                payload["cas"] = "、".join(
                    r[0] for r in conn.execute(
                        "SELECT DISTINCT cas FROM area_chemical WHERE area_code=? ORDER BY cas",
                        (area_code,),
                    )
                )
            if section == "mix":
                payload = fil.attach_annex_check(payload)
            if section == "11.2":
                svc.save_incident(conn, {
                    "site_id": WIZARD_SITE_ID,
                    "incident_id": payload.get("incident_id"),
                    "incident_date": payload.get("when"),
                    "is_near_miss": payload.get("incident_type") == "虛驚",
                    "characteristics": payload.get("traits"),
                    "summary": payload.get("summary"),
                    "casualty": payload.get("casualty"),
                    "lost_days": payload.get("lost_days"),
                    "cause": payload.get("cause"),
                    "process_id": payload.get("process_id"),
                    "equipment_id": payload.get("equipment_id"),
                    "cas": payload.get("cas"),
                    "corrective": payload.get("corrective"),
                })
                return redirect_ok("/wizard/11", "事故已登錄，可在第六章引用")
            if section == "1.4":
                if (payload.get("formula") or "").strip() and not (payload.get("heat") or "").strip():
                    return redirect_err("/wizard/1", "有化學反應式須填反應熱")
                kind_list = [part.strip() for part in str(payload.get("kinds") or "").split(",") if part.strip()]
                kind_other = str(payload.get("kind_other") or "").strip()
                if "其他" in kind_list and not kind_other:
                    return redirect_err(
                        "/wizard/1",
                        "勾選其他時請寫反應種類。請在彈出的視窗寫明實際反應種類後再儲存",
                    )
                payload["kind_other"] = kind_other if "其他" in kind_list else ""
            if section == "1.6" and payload.get("equipment_id"):
                if not payload.get("material"):
                    eq = conn.execute(
                        """SELECT COALESCE(m.material, e.material) AS material,
                                  COALESCE(NULLIF(m.material_category, ''), e.material_category) AS material_category
                           FROM equipment e
                           LEFT JOIN equipment_material m ON m.equipment_id=e.equipment_id
                           WHERE e.equipment_id=?""",
                        (payload["equipment_id"],),
                    ).fetchone()
                    if eq:
                        payload["material"] = eq["material"] or ""
                        if not payload.get("material_category"):
                            payload["material_category"] = eq["material_category"] or ""
                if not payload.get("material_category") and payload.get("material"):
                    payload["material_category"] = wiz.guess_material_category(
                        payload.get("material")
                    )
                if payload.get("material"):
                    svc.save_equipment_material(
                        conn,
                        {
                            "equipment_id": payload["equipment_id"],
                            "material": payload.get("material") or "",
                            "material_category": payload.get("material_category") or "",
                            "spec": payload.get("spec") or "",
                        },
                    )
            if section == "1.9" and payload.get("equipment_id"):
                eq = conn.execute(
                    "SELECT name, equipment_type, area_code, process_id FROM equipment WHERE equipment_id=?",
                    (payload["equipment_id"],),
                ).fetchone()
                if eq:
                    payload.setdefault("device_type", payload.get("device_type") or eq["name"] or "")
                    if not payload.get("area_code"):
                        payload["area_code"] = eq["area_code"]
                    if not payload.get("process_id"):
                        payload["process_id"] = eq["process_id"]
            if section == "4.4":
                limit_id = str(payload.get("limit_id") or "").strip()
                limit = conn.execute("""SELECT l.*,e.name AS equipment_name,e.equipment_type,e.process_id
                    FROM equipment_limit l JOIN equipment e ON e.equipment_id=l.equipment_id
                    WHERE l.limit_id=? AND e.site_id=? AND l.parameter IN ('壓力','溫度','流量','組成')""",
                    (limit_id, WIZARD_SITE_ID)).fetchone()
                if not limit:
                    return redirect_err("/wizard/4", "請選 1.5 已建立的壓力、溫度、流量或組成操作界限")
                valid_bounds = []
                for key in ("safety_high", "safety_low"):
                    try:
                        valid_bounds.append(Decimal(str(limit[key])).is_finite())
                    except InvalidOperation:
                        valid_bounds.append(False)
                if not any(valid_bounds):
                    return redirect_err("/wizard/4", "請先在 1.5 填入實際安全上限或下限數值")
                if any(r.get("limit_id") == limit_id and
                       (not editing_row or int(r.get("row_id") or 0) != row_id)
                       for r in fil.list_rows(conn, WIZARD_SITE_ID, "4.4")):
                    return redirect_err("/wizard/4", "該操作界限已有 4.4 列；請先刪除舊列再重填")
                for prefix, label in (("high", "超上限"), ("low", "低於下限")):
                    consequence = str(payload.get(prefix + "_consequence") or "").strip()
                    correction = str(payload.get(prefix + "_correct") or "").strip()
                    reason = str(payload.get(prefix + "_na_reason") or "").strip()
                    if not ((consequence and correction and not reason) or (reason and not consequence and not correction)):
                        return redirect_err("/wizard/4", f"{label}須填後果與矯正程序，或具體不適用理由")
                payload.update(equipment_id=limit["equipment_id"], equipment_name=limit["equipment_name"],
                               equipment_type=limit["equipment_type"], process_id=limit["process_id"],
                               parameter=limit["parameter"], unit=limit["unit"],
                               safety_high=limit["safety_high"], safety_low=limit["safety_low"])
            if section == "5.1e":
                sop_id = str(payload.get("sop_id") or "").strip()
                reason = str(payload.get("reason") or "").strip()
                if not reason or not conn.execute("""SELECT 1 FROM sop s JOIN process p ON p.process_id=s.process_id
                    WHERE s.sop_id=? AND p.site_id=?""", (sop_id, WIZARD_SITE_ID)).fetchone():
                    return redirect_err("/wizard/5", "請選本場所 SOP 並說明免設專屬課程的理由")
                old = next((r for r in fil.list_rows(conn, WIZARD_SITE_ID, "5.1e")
                            if r.get("sop_id") == sop_id), None)
                if editing_row and old and int(old.get("row_id") or 0) != row_id:
                    return redirect_err("/wizard/5", "該 SOP 已有例外紀錄，請修改原列")
                if old:
                    fil.update_payload(conn, old["row_id"], payload)
                    return redirect_ok("/wizard/5")
            if section == "7.0":
                eid = str(payload.get("equipment_id") or "").strip()
                applicable = str(payload.get("applicable") or "")
                if not conn.execute("SELECT 1 FROM equipment WHERE equipment_id=? AND site_id=?",
                                    (eid, WIZARD_SITE_ID)).fetchone():
                    return redirect_err("/wizard/7", "須選本場所設備")
                if applicable not in ("0", "1") or (applicable == "0" and not str(payload.get("reason") or "").strip()):
                    return redirect_err("/wizard/7", "請判定是否適用；不適用須填理由")
                if applicable == "0" and any(r.get("equipment_id") == eid for r in fil.list_rows(conn, WIZARD_SITE_ID, "7.1")):
                    return redirect_err("/wizard/7", "該設備已有檢查紀錄；請先刪除紀錄再標為不適用")
                old = next((r for r in fil.list_rows(conn, WIZARD_SITE_ID, "7.0")
                            if r.get("equipment_id") == eid), None)
                if editing_row and old and int(old.get("row_id") or 0) != row_id:
                    return redirect_err("/wizard/7", "該設備已有適用性判定，請修改原列")
                if old:
                    fil.update_payload(conn, old["row_id"], payload)
                    return redirect_ok("/wizard/7")
            if section == "7.1":
                eid = str(payload.get("equipment_id") or "").strip()
                if not any(r.get("equipment_id") == eid and str(r.get("applicable")) == "1"
                           for r in fil.list_rows(conn, WIZARD_SITE_ID, "7.0")):
                    return redirect_err("/wizard/7", "請先將設備判定為適用 PSSR")
                try:
                    date.fromisoformat(str(payload.get("when") or ""))
                except ValueError:
                    return redirect_err("/wizard/7", "請填有效的檢查日期")
                if not str(payload.get("rec") or "").strip():
                    payload["rec"] = "無"
                if payload["rec"] != "無" and (not str(payload.get("due") or "").strip() or not str(payload.get("track") or "").strip()):
                    return redirect_err("/wizard/7", "改善建議須填預定完成日期與追蹤結果")
                if payload["rec"] != "無":
                    try:
                        date.fromisoformat(str(payload["due"]))
                    except ValueError:
                        return redirect_err("/wizard/7", "改善建議須填有效的預定完成日期")
            if section == "8.1" and payload.get("equipment_id"):
                eq = conn.execute(
                    """SELECT name, process_id, area_code, equipment_type, power_kind
                       FROM equipment WHERE equipment_id=? AND site_id=?""",
                    (payload["equipment_id"], WIZARD_SITE_ID),
                ).fetchone()
                if not eq:
                    return redirect_err("/wizard/8", "設備須選已有編號")
                screen = conn.execute(
                    "SELECT is_critical FROM mi_screen WHERE equipment_id=?", (payload["equipment_id"],)
                ).fetchone()
                if not screen or not screen["is_critical"]:
                    return redirect_err("/wizard/8", "請先將設備判定為安全關鍵")
                bound = svc.material_for_mi(conn, payload["equipment_id"])
                payload["equipment_name"] = eq["name"]
                payload["process_id"] = eq["process_id"]
                payload["area_code"] = eq["area_code"]
                payload["material"] = bound["material"]
                payload["material_category"] = bound["material_category"]
                if payload.get("mi_type") not in fil.MI_SIX:
                    return redirect_err("/wizard/8", "請確認設備所屬的六大類")
                if not payload.get("cas"):
                    row = conn.execute(
                        "SELECT cas FROM equipment_content WHERE equipment_id=? AND cas<>'' LIMIT 1",
                        (payload["equipment_id"],),
                    ).fetchone()
                    if row:
                        payload["cas"] = row["cas"]
                damage = str(payload.get("damage") or "").strip()
                item = str(payload.get("inspection_item") or "").strip()
                if bool(damage) == bool(item):
                    return redirect_err("/wizard/8", "每筆明細須選一項損壞機制或填一項功能檢查項目")
                if "," in damage or "，" in damage:
                    return redirect_err("/wizard/8", "每筆明細只對應一項損壞機制，請分列填寫")
                if not all(str(payload.get(k) or "").strip() for k in ("method", "freq", "proc_no", "pid_no")):
                    return redirect_err("/wizard/8", "安全關鍵設備須填檢查方式、頻率、程序書編號及 P&ID 圖號")
                if not conn.execute(
                    "SELECT 1 FROM pid_drawing WHERE drawing_no=? AND process_id=?",
                    (payload["pid_no"], eq["process_id"]),
                ).fetchone():
                    return redirect_err("/wizard/8", "P&ID 圖號須屬於該設備的製程")
                detail_id = str(payload.get("detail_id") or "").strip()
                if detail_id:
                    old = conn.execute(
                        """SELECT d.detail_id,d.equipment_id FROM mi_inspection_detail d JOIN equipment e
                           ON e.equipment_id=d.equipment_id WHERE d.detail_id=? AND e.site_id=?""",
                        (detail_id, WIZARD_SITE_ID),
                    ).fetchone()
                    if not old:
                        return redirect_err("/wizard/8", "找不到本場所的檢查明細")
                    if old["equipment_id"] != payload["equipment_id"]:
                        return redirect_err("/wizard/8", "既有檢查項目不可改掛設備；請刪除後重新建立")
                    conn.execute(
                        """UPDATE mi_inspection_detail SET equipment_id=?,damage_mechanism=?,
                           inspection_item=?,inspect_method=?,inspect_frequency=?,procedure_ref=?,
                           pid_drawing_no=?,confirmed=1 WHERE detail_id=?""",
                        (payload["equipment_id"], damage, item, payload["method"],
                         payload["freq"], payload["proc_no"], payload["pid_no"], detail_id),
                    )
                else:
                    conn.execute(
                        """INSERT INTO mi_inspection_detail
                           (equipment_id,damage_mechanism,inspection_item,inspect_method,
                            inspect_frequency,procedure_ref,pid_drawing_no,confirmed)
                           VALUES (?,?,?,?,?,?,?,1)""",
                        (payload["equipment_id"], damage, item, payload["method"],
                         payload["freq"], payload["proc_no"], payload["pid_no"]),
                    )
                conn.execute(
                    """UPDATE mi_screen SET mi_type=?,mi_type_confirmed=1
                       WHERE equipment_id=?""",
                    (payload["mi_type"], payload["equipment_id"]),
                )
                conn.commit()
                return redirect_ok("/wizard/8", "設備檢查項目已儲存")
            if section in ("4.2", "4.3", "4.4", "7.1") and payload.get("equipment_id"):
                eq = conn.execute(
                    """SELECT name, equipment_type, process_id FROM equipment
                       WHERE equipment_id=?""",
                    (payload["equipment_id"],),
                ).fetchone()
                if eq:
                    payload["equipment_name"] = eq["name"]
                    payload["equipment_type"] = eq["equipment_type"]
                    payload.setdefault("process_id", eq["process_id"])
            eid = payload.get("equipment_id")
            if eid and section in ("4.2", "4.3", "4.4", "7.1", "8.1", "10.1"):
                if not conn.execute("SELECT 1 FROM equipment WHERE equipment_id=?", (eid,)).fetchone():
                    return redirect_err(f"/wizard/{step}", "設備須選已有編號")
            if section == "6.1":
                payload["incident_id"] = svc.save_contractor_incident(
                    conn,
                    {
                        "site_id": WIZARD_SITE_ID,
                        "contractor_name": payload.get("vendor") or payload.get("contractor_name"),
                        "contract_period": payload.get("period") or payload.get("contract_period"),
                        "occur_date": payload.get("occur_date"),
                        "incident_type": payload.get("incident_type") or "虛驚",
                        "summary": payload.get("summary") or payload.get("note"),
                        "linked_incident_id": payload.get("linked_incident_id"),
                        "casualty": payload.get("casualty"),
                        "lost_days": payload.get("lost_days"),
                        "cause": payload.get("cause"),
                        "process_id": payload.get("process_id"),
                        "equipment_id": payload.get("equipment_id"),
                        "corrective": payload.get("corrective"),
                    },
                )
            if section == "9.1z":
                svc.save_hotwork_zone(
                    conn,
                    {
                        "area_code": payload.get("area_code"),
                        "protection_reason": payload.get("protection_reason"),
                    },
                )
                return redirect_ok(f"/wizard/{step}")
            if editing_row:
                fil.update_payload(conn, row_id, payload)
            else:
                fil.add_row(conn, WIZARD_SITE_ID, section, payload)
        except PsmError as e:
            return redirect_err(f"/wizard/{step}", e.message)
        finally:
            conn.close()
        return redirect_ok(f"/wizard/{step}")

    @app.post("/wizard/1/design-code")
    async def wizard_design_code(request: Request):
        form = await request.form()
        conn = get_conn()
        try:
            blocked = _guard(conn, 1)
            if blocked:
                return blocked
            pid = str(form.get("process_id") or "").strip()
            equipment_ids = list(dict.fromkeys(str(v).strip() for v in form.getlist("equipment_ids") if v))
            cas_list = list(dict.fromkeys(str(v).strip() for v in form.getlist("cas_list") if v))
            material = str(form.get("material") or "").strip()
            category = str(form.get("material_category") or "").strip()
            spec = str(form.get("spec") or "").strip()
            scope = str(form.get("scope") or "").strip()
            if not pid or not conn.execute("SELECT 1 FROM process WHERE process_id=? AND site_id=?", (pid, WIZARD_SITE_ID)).fetchone():
                return redirect_err("/wizard/1", "1.6 須選已有製程")
            if not equipment_ids or not material or not category or not spec:
                return redirect_err("/wizard/1", "1.6 須選至少一台設備，並填建造材料、材質類別與設計規範")
            for eid in equipment_ids:
                if not conn.execute("SELECT 1 FROM equipment WHERE equipment_id=? AND process_id=? AND site_id=?", (eid, pid, WIZARD_SITE_ID)).fetchone():
                    return redirect_err("/wizard/1", "1.6 設備必須屬於所選製程")
            for cas in cas_list:
                if not conn.execute("SELECT 1 FROM chemical_cite WHERE cas=? AND process_id=?", (cas, pid)).fetchone():
                    return redirect_err("/wizard/1", "1.6 化學品必須屬於所選製程")
            raw_code_id = str(form.get("code_id") or "").strip()
            try:
                code_id = int(raw_code_id) if raw_code_id else None
            except ValueError:
                return redirect_err("/wizard/1", "設計規範編號無效，請重新選取資料列")
            if code_id is not None:
                owned = conn.execute(
                    """SELECT 1 FROM design_code_process d JOIN process p ON p.process_id=d.process_id
                       WHERE d.code_id=? AND p.site_id=?""",
                    (code_id, WIZARD_SITE_ID),
                ).fetchone()
                if not owned:
                    return redirect_err("/wizard/1", "找不到這筆設計規範，請重新整理後再編輯")
                conn.execute(
                    """UPDATE design_code SET process_id=?, equipment_id=?, item=?, code=?,
                       material_category=?, scope=? WHERE code_id=?""",
                    (pid, equipment_ids[0], material, spec, category, scope, code_id),
                )
                for table in ("design_code_chemical", "design_code_equipment", "design_code_process"):
                    conn.execute(f"DELETE FROM {table} WHERE code_id=?", (code_id,))
            else:
                cursor = conn.execute(
                    """INSERT INTO design_code(process_id,equipment_id,item,code,material_category,scope)
                       VALUES (?,?,?,?,?,?)""",
                    (pid, equipment_ids[0], material, spec, category, scope),
                )
                code_id = cursor.lastrowid
            conn.execute("INSERT INTO design_code_process(code_id,process_id) VALUES (?,?)", (code_id, pid))
            for eid in equipment_ids:
                conn.execute("INSERT INTO design_code_equipment(code_id,equipment_id) VALUES (?,?)", (code_id, eid))
                svc.save_equipment_material(conn, {
                    "equipment_id": eid, "material": material, "material_category": category, "spec": spec,
                })
            for cas in cas_list:
                conn.execute(
                    "INSERT INTO design_code_chemical(code_id,process_id,cas) VALUES (?,?,?)",
                    (code_id, pid, cas),
                )
            payload = {
                "code_id": code_id, "process_id": pid, "equipment_ids": equipment_ids,
                "cas_list": cas_list, "material": material,
                "material_category": category, "spec": spec, "scope": scope,
            }
            prior_row = next(
                (row for row in fil.list_rows(conn, WIZARD_SITE_ID, "1.6") if row.get("code_id") == code_id),
                None,
            )
            if prior_row:
                fil.update_payload(conn, prior_row["row_id"], payload)
            else:
                fil.add_row(conn, WIZARD_SITE_ID, "1.6", payload)
        except PsmError as e:
            return redirect_err("/wizard/1", e.message)
        finally:
            conn.close()
        return redirect_ok("/wizard/1", "已儲存設計規範及適用設備")

    @app.post("/wizard/1/design-code/delete")
    def wizard_design_code_delete(code_id: int = Form(...)):
        conn = get_conn()
        try:
            owned = conn.execute(
                """SELECT 1 FROM design_code_process d JOIN process p ON p.process_id=d.process_id
                   WHERE d.code_id=? AND p.site_id=?""",
                (code_id, WIZARD_SITE_ID),
            ).fetchone()
            if not owned:
                return redirect_err("/wizard/1", "找不到這筆設計規範")
            for row in fil.list_rows(conn, WIZARD_SITE_ID, "1.6"):
                if row.get("code_id") == code_id:
                    fil.delete_row(conn, WIZARD_SITE_ID, row["row_id"])
            for table in ("design_code_chemical", "design_code_equipment", "design_code_process"):
                conn.execute(f"DELETE FROM {table} WHERE code_id=?", (code_id,))
            conn.execute("DELETE FROM design_code WHERE code_id=?", (code_id,))
            conn.commit()
        finally:
            conn.close()
        return redirect_ok("/wizard/1", "已刪除設計規範")

    @app.post("/wizard/1/blocks")
    async def wizard_blocks(request: Request):
        form = await request.form()
        conn = get_conn()
        try:
            blocked = _guard(conn, 1)
            if blocked:
                return blocked
            payloads = []
            process_id = str(form.get("process_id") or "").strip()
            if not process_id:
                return redirect_err("/wizard/1", "流程方塊須選表1.0-2 製程編號")
            proc = conn.execute(
                "SELECT process_id FROM process WHERE process_id=? AND site_id=?",
                (process_id, WIZARD_SITE_ID),
            ).fetchone()
            if not proc:
                return redirect_err("/wizard/1", "製程須選表1.0-2 已有編號")
            for i in range(1, 16):
                name = str(form.get(f"name_{i}") or "").strip()
                desc = str(form.get(f"desc_{i}") or "").strip()
                equipment_id = str(form.get(f"equipment_id_{i}") or "").strip()
                next_process_id = str(form.get(f"next_process_{i}") or "").strip()
                if not name and not desc and not equipment_id:
                    continue
                if equipment_id:
                    eq = conn.execute(
                        """SELECT equipment_id, name FROM equipment
                           WHERE equipment_id=? AND process_id=? AND site_id=?""",
                        (equipment_id, process_id, WIZARD_SITE_ID),
                    ).fetchone()
                    if not eq:
                        return redirect_err("/wizard/1", "方塊設備須為該製程已列編號")
                    if not name:
                        name = eq["name"]
                if next_process_id:
                    if next_process_id == process_id:
                        return redirect_err("/wizard/1", "下一製程不得等於本列所屬製程")
                    nxt = conn.execute(
                        "SELECT 1 FROM process WHERE process_id=? AND site_id=?",
                        (next_process_id, WIZARD_SITE_ID),
                    ).fetchone()
                    if not nxt:
                        return redirect_err("/wizard/1", "下一製程須選表1.0-2 已有編號")
                payloads.append(
                    {
                        "process_id": process_id,
                        "seq": str(form.get(f"seq_{i}") or i),
                        "name": name,
                        "equipment_id": equipment_id,
                        "desc": desc,
                        "next": str(form.get(f"next_{i}") or ""),
                        "next_process_id": next_process_id,
                        "branch_from": str(form.get(f"branch_from_{i}") or "").strip(),
                        "x": str(form.get(f"x_{i}") or ""),
                        "y": str(form.get(f"y_{i}") or ""),
                    }
                )
            active_seqs = {row["seq"] for row in payloads}
            for row in payloads:
                next_seq = row["next"].strip()
                if next_seq and next_seq not in active_seqs:
                    return redirect_err("/wizard/1", "下一方塊須為此製程已建立的方塊")
                if next_seq and next_seq == row["seq"]:
                    return redirect_err("/wizard/1", "方塊不得連到自己")
                if next_seq and row["next_process_id"]:
                    return redirect_err("/wizard/1", "同一方塊請擇一設定下一方塊或下一製程")
                branch_from = row["branch_from"]
                if branch_from and (branch_from not in active_seqs or branch_from == row["seq"]):
                    return redirect_err("/wizard/1", "支線來源須為此製程的另一個方塊")
            fil.replace_section_for_key(
                conn, WIZARD_SITE_ID, "1.3b", payloads, "process_id", process_id
            )
        finally:
            conn.close()
        return redirect_ok(f"/wizard/1?block_process={quote(process_id)}", "已存線上流程方塊")

    @app.post("/wizard/1/esd")
    async def wizard_esd(request: Request):
        form = await request.form()
        conn = get_conn()
        try:
            blocked = _guard(conn, 1)
            if blocked:
                return blocked
            actions = form.getlist("action_ids") if hasattr(form, "getlist") else []
            svc.save_esd_scenario(
                conn,
                {
                    "scenario_id": str(form.get("scenario_id") or "").strip(),
                    "process_id": str(form.get("process_id") or "").strip(),
                    "esd_equipment_id": str(form.get("esd_equipment_id") or "").strip(),
                    "name": str(form.get("name") or "").strip(),
                    "trigger_conditions": str(form.get("trigger_conditions") or "").strip(),
                    "maint_dept_id": str(form.get("maint_dept_id") or "").strip(),
                },
                [str(a) for a in actions if a],
            )
        except PsmError as e:
            return redirect_err("/wizard/1", e.message)
        finally:
            conn.close()
        return redirect_ok("/wizard/1", "已存緊急停車方案")

    @app.post("/wizard/3/labor")
    async def wizard_labor(request: Request):
        form = await request.form()
        conn = get_conn()
        try:
            blocked = _guard(conn, 3)
            if blocked:
                return blocked
            item = str(form.get("item") or "")
            if item not in fil.LABOR_ITEMS:
                return redirect_err("/wizard/3", "請選擇參與項目")
            payload = {
                "item": item,
                "how": str(form.get("how") or "").strip(),
                "who": str(form.get("who") or "").strip(),
                "note": str(form.get("note") or "").strip(),
            }
            if not payload["how"]:
                return redirect_err("/wizard/3", "請填參與方式")
            existing = next((r for r in fil.list_rows(conn, WIZARD_SITE_ID, "3.1") if r.get("item") == item), None)
            if existing:
                fil.update_payload(conn, existing["row_id"], payload)
            else:
                fil.add_row(conn, WIZARD_SITE_ID, "3.1", payload)
        finally:
            conn.close()
        return redirect_ok("/wizard/3", "已儲存勞工參與方式")

    @app.post("/wizard/3/proc")
    async def wizard_labor_proc(
        labor_file: str = Form(""),
        labor_date: str = Form(""),
        labor_see_also: str = Form(""),
        labor_ref: str = Form(""),
        file: UploadFile | None = File(None),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, 3)
            if blocked:
                return blocked
            old_flags = fil.all_flags(conn, WIZARD_SITE_ID)
            if labor_see_also:
                try:
                    ref_id = int(labor_ref)
                except ValueError:
                    ref_id = 0
                ref = conn.execute(
                    """SELECT u.attachment_path FROM unstructured_attachment u
                       LEFT JOIN process p ON p.process_id=u.process_id
                       WHERE u.attachment_id=? AND (u.site_id=? OR p.site_id=?)""",
                    (ref_id, WIZARD_SITE_ID, WIZARD_SITE_ID),
                ).fetchone()
                if not ref or not wiz.has_uploaded_file(ref[0]):
                    return redirect_err("/wizard/3", "請選擇一份已上傳的既有文件")
                fil.set_flag(conn, WIZARD_SITE_ID, "labor_ref", str(ref_id))
            elif (not file or not file.filename) and not wiz.has_uploaded_file(old_flags.get("labor_file")):
                return redirect_err("/wizard/3", "請選擇程序書檔案，或勾選見其他已上傳文件")
            if file and file.filename:
                path = wiz.store_upload(WIZARD_SITE_ID, "labor", file, "")
                fil.set_flag(conn, WIZARD_SITE_ID, "labor_file", path)
                fil.set_flag(conn, WIZARD_SITE_ID, "labor_file_name", labor_file.strip() or file.filename)
            fil.set_flag(conn, WIZARD_SITE_ID, "labor_date", labor_date)
            fil.set_flag(conn, WIZARD_SITE_ID, "labor_see_also", "1" if labor_see_also else "0")
        finally:
            conn.close()
        return redirect_ok("/wizard/3")

    @app.post("/wizard/8/screen")
    def wizard_mi_screen(
        request: Request,
        equipment_id: str = Form(...), is_critical: str = Form(...), basis: str = Form(""),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, 8)
            if blocked:
                return blocked
            if is_critical not in ("0", "1"):
                return _fail(request, "/wizard/8", "安全關鍵性須選是或否", ["is_critical"])
            if not conn.execute(
                "SELECT 1 FROM equipment WHERE equipment_id=? AND site_id=?",
                (equipment_id, WIZARD_SITE_ID),
            ).fetchone():
                return _fail(request, "/wizard/8", "須選本場所已建設備", ["equipment_id"])
            if is_critical == "0" and not basis.strip():
                return _fail(
                    request, "/wizard/8",
                    "判定為否時必須填寫判定依據。請補上判定依據後再按儲存",
                    ["basis"],
                )
            if is_critical == "0":
                if conn.execute("SELECT 1 FROM mi_inspection_detail WHERE equipment_id=?", (equipment_id,)).fetchone():
                    return _fail(request, "/wizard/8", "請先刪除這台設備的安全關鍵性明細，再改判為否")
                if conn.execute("SELECT 1 FROM mi_failure WHERE equipment_id=?", (equipment_id,)).fetchone():
                    return _fail(request, "/wizard/8", "請先刪除這台設備的失效率紀錄，再改判為否")
                if conn.execute("SELECT 1 FROM mi_failure_gap WHERE equipment_id=?", (equipment_id,)).fetchone():
                    return _fail(request, "/wizard/8", "請先刪除這台設備的資料不足紀錄，再改判為否")
            conn.execute(
                """INSERT INTO mi_screen(equipment_id,is_critical,basis)
                   VALUES (?,?,?) ON CONFLICT(equipment_id) DO UPDATE SET
                   is_critical=excluded.is_critical,basis=excluded.basis""",
                (equipment_id, int(is_critical), basis.strip()),
            )
            conn.commit()
        finally:
            conn.close()
        return redirect_ok("/wizard/8", "設備安全關鍵性已確認")

    @app.post("/wizard/8/fail")
    async def wizard_mi_fail(request: Request):
        form = await request.form()
        conn = get_conn()
        try:
            blocked = _guard(conn, 8)
            if blocked:
                return blocked
            selected_eid = str(form.get("equipment_id") or "").strip()
            if selected_eid:
                source = conn.execute(
                    """SELECT 1 FROM mi_inspection_detail d JOIN mi_screen s
                       ON s.equipment_id=d.equipment_id WHERE d.equipment_id=?
                       AND d.confirmed=1 AND s.is_critical=1 AND s.mi_type_confirmed=1""", (selected_eid,)
                ).fetchone()
                equipment = conn.execute("SELECT name, equipment_type FROM equipment WHERE site_id=? AND equipment_id=?", (WIZARD_SITE_ID, selected_eid)).fetchone()
                if not source or not equipment:
                    return redirect_err("/wizard/8", "請先將設備加入關鍵設備清單")
                hours = str(form.get("hours") or "").strip()
                repair = str(form.get("repair") or "").strip()
                try:
                    h, count = float(hours), float(repair)
                    if not isfinite(h) or not isfinite(count) or h < 0 or count < 0 or not count.is_integer():
                        raise ValueError
                except ValueError:
                    return redirect_err("/wizard/8", "使用時間不可小於零，失效事件數須為非負整數")
                if h == 0 and not str(form.get("note") or "").strip():
                    return redirect_err("/wizard/8", "運行時間為零時，須註明資料不足或未運行的原因")
                period_start = str(form.get("period_start") or "").strip()
                period_end = str(form.get("period_end") or "").strip()
                try:
                    valid_period = date.fromisoformat(period_start) <= date.fromisoformat(period_end)
                except ValueError:
                    valid_period = False
                if not valid_period:
                    return redirect_err("/wizard/8", "請填有效的統計期間起迄")
                conn.execute(
                    """INSERT INTO mi_failure(equipment_id,period_start,period_end,run_hours,
                       failure_count,note,confirmed) VALUES (?,?,?,?,?,?,1)
                       ON CONFLICT(equipment_id) DO UPDATE SET period_start=excluded.period_start,
                       period_end=excluded.period_end,run_hours=excluded.run_hours,
                       failure_count=excluded.failure_count,note=excluded.note,confirmed=1""",
                    (selected_eid, period_start, period_end, h, int(count),
                     str(form.get("note") or "").strip()),
                )
                conn.execute("DELETE FROM mi_failure_gap WHERE equipment_id=?", (selected_eid,))
                conn.commit()
                return redirect_ok("/wizard/8", "已儲存設備失效率")
            return redirect_err("/wizard/8", "請選一台已確認檢查項目的安全關鍵設備")
        finally:
            conn.close()
        return redirect_ok("/wizard/8", "已存設備失效率")

    @app.post("/wizard/8/fail/gap")
    def wizard_mi_failure_gap(
        equipment_id: str = Form(...), period_start: str = Form(...),
        period_end: str = Form(...), reason: str = Form(...),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, 8)
            if blocked:
                return blocked
            source = conn.execute(
                """SELECT 1 FROM mi_inspection_detail d JOIN mi_screen s
                   ON s.equipment_id=d.equipment_id JOIN equipment e
                   ON e.equipment_id=d.equipment_id WHERE d.equipment_id=?
                   AND e.site_id=? AND d.confirmed=1 AND s.is_critical=1
                   AND s.mi_type_confirmed=1""", (equipment_id, WIZARD_SITE_ID),
            ).fetchone()
            if not source:
                return redirect_err("/wizard/8", "請先確認該安全關鍵設備的檢查項目")
            try:
                valid_period = date.fromisoformat(period_start) <= date.fromisoformat(period_end)
            except ValueError:
                valid_period = False
            if not valid_period or not reason.strip():
                return redirect_err("/wizard/8", "資料不足須填有效統計期間與具體原因")
            conn.execute(
                """INSERT INTO mi_failure_gap(equipment_id,period_start,period_end,reason)
                   VALUES (?,?,?,?) ON CONFLICT(equipment_id) DO UPDATE SET
                   period_start=excluded.period_start,period_end=excluded.period_end,
                   reason=excluded.reason""",
                (equipment_id, period_start, period_end, reason.strip()),
            )
            conn.execute("DELETE FROM mi_failure WHERE equipment_id=?", (equipment_id,))
            conn.commit()
        finally:
            conn.close()
        return redirect_ok("/wizard/8", "資料不足已保存；本章仍待人工確認")

    @app.post("/wizard/8/upload")
    def wizard_mi_upload(
        process_id: str = Form(...),
        equipment_id: str = Form(""),
        attachment_id: str = Form(""),
        file_name: str = Form(""),
        file: UploadFile | None = File(None),
    ):
        conn = get_conn()
        try:
            blocked = _guard(conn, 8)
            if blocked:
                return blocked
            path = wiz.store_upload(WIZARD_SITE_ID, "mi", file, file_name)
            existing = None
            if attachment_id.strip():
                existing = conn.execute(
                    """SELECT u.attachment_id,u.attachment_path,u.original_name
                       FROM unstructured_attachment u JOIN process p ON p.process_id=u.process_id
                       WHERE u.attachment_id=? AND u.kind='mi' AND p.site_id=?""",
                    (attachment_id.strip(), WIZARD_SITE_ID),
                ).fetchone()
                if not existing:
                    return redirect_err("/wizard/8", "找不到本場所的檢查附件")
            if not path and not existing:
                return redirect_err("/wizard/8", "請選檔或填文件名")
            if existing:
                conn.execute(
                    """UPDATE unstructured_attachment SET process_id=?,original_name=?,
                       attachment_path=?,note=? WHERE attachment_id=?""",
                    (process_id, file_name or (file.filename if file and file.filename else existing["original_name"]),
                     path or existing["attachment_path"], equipment_id, existing["attachment_id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO unstructured_attachment(
                        process_id, kind, original_name, attachment_path, note
                    ) VALUES (?,?,?,?,?)""",
                    (process_id, "mi", file_name or path, path, equipment_id),
                )
            conn.commit()
        except PsmError as e:
            return redirect_err("/wizard/8", e.message)
        finally:
            conn.close()
        return redirect_ok("/wizard/8", "檢查測試紀錄已登錄")

    @app.post("/wizard/row/delete")
    def wizard_row_delete(step: int = Form(...), row_id: int = Form(...)):
        conn = get_conn()
        try:
            blocked = _guard(conn, step)
            if blocked:
                return blocked
            row = conn.execute("SELECT section, payload FROM filing_row WHERE site_id=? AND row_id=?", (WIZARD_SITE_ID, row_id)).fetchone()
            if not row or not (row["section"].startswith(f"{step}.") or (step == 1 and row["section"] == "mix")):
                return redirect_err(f"/wizard/{step}", "找不到本章這筆資料")
            if row["section"] == "mix":
                if not _delete_mix_entries(conn, row_id, whole_group=False):
                    return redirect_err("/wizard/1", "找不到這筆混合物成分")
                return redirect_ok("/wizard/1", "已刪除混合物成分")
            fil.delete_row(conn, WIZARD_SITE_ID, row_id)
        except (PsmError, sqlite3.IntegrityError) as e:
            return redirect_err(f"/wizard/{step}", e.message if isinstance(e, PsmError) else "仍有關聯資料，請先檢查引用後再刪除")
        finally:
            conn.close()
        return redirect_ok(f"/wizard/{step}", "已刪除")

    @app.post("/wizard/8/detail/delete")
    def wizard_mi_detail_delete(detail_id: int = Form(...)):
        conn = get_conn()
        try:
            blocked = _guard(conn, 8)
            if blocked:
                return blocked
            row = conn.execute(
                """SELECT d.equipment_id FROM mi_inspection_detail d JOIN equipment e
                   ON e.equipment_id=d.equipment_id WHERE d.detail_id=? AND e.site_id=?""",
                (detail_id, WIZARD_SITE_ID),
            ).fetchone()
            if not row:
                return redirect_err("/wizard/8", "找不到本場所的檢查明細")
            conn.execute("DELETE FROM mi_inspection_detail WHERE detail_id=?", (detail_id,))
            if not conn.execute(
                "SELECT 1 FROM mi_inspection_detail WHERE equipment_id=?", (row["equipment_id"],)
            ).fetchone():
                conn.execute("DELETE FROM mi_failure WHERE equipment_id=?", (row["equipment_id"],))
                conn.execute("DELETE FROM mi_failure_gap WHERE equipment_id=?", (row["equipment_id"],))
            conn.commit()
        finally:
            conn.close()
        return redirect_ok("/wizard/8", "已刪除檢查項目")

    @app.post("/wizard/8/fail/delete")
    def wizard_mi_fail_delete(equipment_id: str = Form(...)):
        conn = get_conn()
        try:
            blocked = _guard(conn, 8)
            if blocked:
                return blocked
            conn.execute(
                """DELETE FROM mi_failure WHERE equipment_id=? AND equipment_id IN
                   (SELECT equipment_id FROM equipment WHERE site_id=?)""",
                (equipment_id, WIZARD_SITE_ID),
            )
            conn.execute(
                """DELETE FROM mi_failure_gap WHERE equipment_id=? AND equipment_id IN
                   (SELECT equipment_id FROM equipment WHERE site_id=?)""",
                (equipment_id, WIZARD_SITE_ID),
            )
            conn.commit()
        finally:
            conn.close()
        return redirect_ok("/wizard/8", "已刪除設備失效率")

    @app.post("/wizard/1/mix/delete")
    def wizard_mix_delete(row_id: int = Form(...)):
        conn = get_conn()
        try:
            if not _delete_mix_entries(conn, row_id, whole_group=True):
                return redirect_err("/wizard/1", "找不到這筆混合物")
        except (PsmError, sqlite3.IntegrityError) as e:
            return redirect_err("/wizard/1", e.message if isinstance(e, PsmError) else "仍有關聯資料，請先檢查引用後再刪除")
        finally:
            conn.close()
        return redirect_ok("/wizard/1", "已刪除整筆混合物及成分")

    @app.post("/wizard/item/delete")
    async def wizard_item_delete(request: Request):
        form = await request.form()
        kind = str(form.get("kind") or "")
        definitions = {
            "department": (1, "department", ("dept_id",)),
            "process": (1, "process", ("process_id",)),
            "equipment": (1, "equipment", ("equipment_id",)),
            "chemical": (1, "chemical", ("process_id", "sds_id", "cas")),
            "area": (1, "area", ("area_code",)),
            "drawing": (1, "pid_drawing", ("drawing_no", "revision")),
            "limit": (1, "equipment_limit", ("limit_id",)),
            "pha_upload": (2, "unstructured_attachment", ("attachment_id",)),
            "course": (5, "training_course", ("course_id",)),
            "contractor": (6, "contractor_incident", ("incident_id",)),
            "mi_upload": (8, "unstructured_attachment", ("attachment_id",)),
            "hotwork_zone": (9, "hotwork_zone", ("area_code",)),
            "secret_upload": (14, "unstructured_attachment", ("attachment_id",)),
        }
        if kind not in definitions:
            return redirect_err("/wizard/1", "無法辨識要刪除的資料")
        step, table, keys = definitions[kind]
        values = {key: str(form.get(key) or "").strip() for key in keys}
        if not all(values.values()):
            return redirect_err(f"/wizard/{step}", "請指定要刪除的資料")
        conn = get_conn()
        try:
            blocked = _guard(conn, step)
            if blocked:
                return blocked
            if table in ("department", "process", "equipment", "area", "contractor_incident"):
                owned = conn.execute(f"SELECT 1 FROM {table} WHERE {keys[0]}=? AND site_id=?", (values[keys[0]], WIZARD_SITE_ID)).fetchone()
            elif table == "chemical":
                owned = conn.execute("SELECT 1 FROM chemical c JOIN process p ON p.process_id=c.process_id WHERE c.process_id=? AND c.sds_id=? AND c.cas=? AND p.site_id=?", (*values.values(), WIZARD_SITE_ID)).fetchone()
            elif table == "pid_drawing":
                owned = conn.execute("""SELECT 1 FROM pid_drawing d JOIN process p ON p.process_id=d.process_id
                    WHERE d.drawing_no=? AND d.revision=? AND p.site_id=?""",
                    (values["drawing_no"], values["revision"], WIZARD_SITE_ID)).fetchone()
            elif table == "training_course":
                owned = conn.execute("""SELECT 1 FROM training_course t JOIN process p ON p.process_id=t.process_id
                    WHERE t.course_id=? AND p.site_id=?""", (values["course_id"], WIZARD_SITE_ID)).fetchone()
            elif table == "equipment_limit":
                owned = conn.execute("SELECT 1 FROM equipment_limit l JOIN equipment e ON e.equipment_id=l.equipment_id WHERE l.limit_id=? AND e.site_id=?", (values["limit_id"], WIZARD_SITE_ID)).fetchone()
            elif table == "hotwork_zone":
                owned = conn.execute("SELECT 1 FROM hotwork_zone z JOIN area a ON a.area_code=z.area_code WHERE z.area_code=? AND a.site_id=?", (values["area_code"], WIZARD_SITE_ID)).fetchone()
            else:
                owned = conn.execute("""SELECT 1 FROM unstructured_attachment u LEFT JOIN process p ON p.process_id=u.process_id
                    WHERE u.attachment_id=? AND u.kind=? AND (u.site_id=? OR p.site_id=?)""",
                    (values["attachment_id"], {"pha_upload": "pha", "mi_upload": "mi", "secret_upload": "trade_secret"}[kind], WIZARD_SITE_ID, WIZARD_SITE_ID)).fetchone()
            if not owned:
                return redirect_err(f"/wizard/{step}", "找不到本場所這筆資料")
            contractor = conn.execute("SELECT * FROM contractor_incident WHERE incident_id=?", (values["incident_id"],)).fetchone() if kind == "contractor" else None
            if not delete_item.delete_record(conn, WIZARD_SITE_ID, table, values):
                return redirect_err(f"/wizard/{step}", "這筆資料已刪除")
            if contractor:
                entries = fil.list_rows(conn, WIZARD_SITE_ID, "6.1")
                linked = next((r for r in entries if r.get("incident_id") == values["incident_id"]), None)
                if not linked:
                    linked = next((r for r in entries if
                        r.get("vendor") == contractor["contractor_name"]
                        and str(r.get("period") or "") == str(contractor["contract_period"] or "")
                        and (r.get("summary") or r.get("note") or "") == (contractor["summary"] or "")
                    ), None)
                if linked:
                    fil.delete_row(conn, WIZARD_SITE_ID, linked["row_id"])
        except (sqlite3.IntegrityError, ValueError):
            return redirect_err(f"/wizard/{step}", "仍有關聯資料，請先檢查引用後再刪除")
        finally:
            conn.close()
        return redirect_ok(f"/wizard/{step}", "已刪除；章節狀態已更新")

    @app.post("/wizard/12/node")
    def wizard_node_disabled():
        return _hazop_gone()

    @app.post("/wizard/12/score")
    def wizard_score_disabled():
        return _hazop_gone()

    @app.post("/wizard/12/consequence")
    def wizard_cons_disabled():
        return _hazop_gone()

    @app.post("/wizard/12/assessment")
    def wizard_assess_disabled():
        return _hazop_gone()

    @app.post("/wizard/8/map")
    def wizard_map_disabled():
        return RedirectResponse(
            f"/wizard/1?err={quote('預設路徑不填製程－設備－化學品對應表')}",
            status_code=303,
        )
