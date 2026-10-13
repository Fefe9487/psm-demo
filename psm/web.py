"""單機單使用者 Demo。引導順序不可顛倒；細表只選 ID。"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from psm.db import connect, db_mode, db_path, init_schema, wizard_case
from psm import filing as fil
from psm.hazards import HAZARD_STATEMENT_GROUPS, hazard_display_labels
from psm.enums import (
    CHEMICAL_ROLES,
    EQUIPMENT_TYPES,
    MATERIAL_CATEGORIES,
    MATRIX_VERSION,
    OP_KIND_LABEL,
    PHASE_CLASSES,
    POWER_KINDS,
    PROCEDURE_EMPTY_NOTE,
    PROCESS_MODE_LABEL,
    PROCESS_MODES,
    SITE_ID,
    UNIT_TITLES,
    INCIDENT_TYPES,
    WIZARD_SITE_ID,
)
from psm.errors import PsmError
from psm.floor import create_node_from_equipment, floor_bundle, score_consequence
from psm.seed import seed_hf_demo
from psm import services as svc
from psm import wizard as wiz
from psm.wizard_http import register_wizard
from psm.sample_petrochemical import seed_petrochemical_sample

ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.cache = None
templates.env.globals.update(
    UNIT_TITLES=UNIT_TITLES,
    PROCEDURE_EMPTY_NOTE=PROCEDURE_EMPTY_NOTE,
    EQUIPMENT_TYPES=EQUIPMENT_TYPES,
    POWER_KINDS=POWER_KINDS,
    PHASE_CLASSES=PHASE_CLASSES,
    INCIDENT_TYPES=INCIDENT_TYPES,
    CHEMICAL_ROLES=CHEMICAL_ROLES,
    MATERIAL_CATEGORIES=MATERIAL_CATEGORIES,
    PROCESS_MODES=PROCESS_MODES,
    PROCESS_MODE_LABEL=PROCESS_MODE_LABEL,
    MATRIX_VERSION=MATRIX_VERSION,
    SITE_ID=SITE_ID,
    WIZARD_SITE_ID=WIZARD_SITE_ID,
    OP_KIND_LABEL=OP_KIND_LABEL,
    HAZARD_STATEMENT_GROUPS=HAZARD_STATEMENT_GROUPS,
    hazard_display_labels=hazard_display_labels,
    prefill=wiz.PREFILL,
)

app = FastAPI(title="PSM 線上風險評估 Demo")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


class DbModeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/wizard"):
            mode = "wizard"
        elif path == "/demo" or path.startswith("/demo"):
            mode = "demo"
        else:
            mode = request.cookies.get("psm_mode") or "demo"
        token = db_mode.set(mode)
        case_token = wizard_case.set(
            request.cookies.get("psm_wizard_case")
            if request.cookies.get("psm_wizard_case") in {"hf", "petrochemical"} else "hf"
        )
        try:
            response = await call_next(request)
            if path.startswith("/wizard"):
                response.set_cookie("psm_mode", "wizard", path="/")
            elif path == "/demo" or path.startswith("/demo"):
                response.set_cookie("psm_mode", "demo", path="/")
            return response
        finally:
            wizard_case.reset(case_token)
            db_mode.reset(token)


app.add_middleware(DbModeMiddleware)


def active_site() -> str:
    return WIZARD_SITE_ID if db_mode.get() == "wizard" else SITE_ID

NAV_PRIMARY = [
    ("/", "首次填報"),
    ("/wizard", "繼續精靈"),
    ("/report", "十四章報告"),
]
NAV_DATA = [
    ("/site", "場所"),
    ("/departments", "部門"),
    ("/processes", "製程"),
    ("/areas", "廠區位置圖"),
    ("/equipment", "設備／ESD"),
    ("/chemicals", "化學品"),
    ("/map", "對應表"),
    ("/pid", "P&ID"),
    ("/psi", "存量與上下限"),
    ("/checks", "三種檢核"),
    ("/hazop", "評估紀錄（資料表）"),
    ("/labor", "3.3 勞工參與"),
    ("/sop", "3.4 SOP"),
    ("/training", "3.5 訓練"),
    ("/contractor", "3.6 承攬"),
    ("/pssr", "3.7 PSSR"),
    ("/mi", "3.8 機械完整性"),
    ("/hotwork", "3.9 動火"),
    ("/moc", "3.10 變更"),
    ("/incident", "3.11 事故"),
    ("/emergency", "3.12 應變"),
    ("/audit", "3.13 稽核"),
    ("/secret", "3.14 機密"),
]
NAV = NAV_PRIMARY + NAV_DATA


def get_conn():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    init_schema(conn)
    if db_mode.get() == "wizard" and wizard_case.get() == "petrochemical":
        if not conn.execute("SELECT 1 FROM site WHERE site_id=?", (WIZARD_SITE_ID,)).fetchone():
            seed_petrochemical_sample(conn, WIZARD_SITE_ID)
    if db_mode.get() != "wizard":
        n = conn.execute("SELECT COUNT(*) FROM site").fetchone()[0]
        if n == 0:
            seed_hf_demo(conn)
    return conn


@app.get("/wizard/sample/{sample_name}")
def wizard_select_sample(sample_name: str):
    if sample_name not in {"hf", "petrochemical"}:
        return RedirectResponse("/wizard/1", status_code=303)
    response = RedirectResponse("/wizard/1", status_code=303)
    response.set_cookie("psm_wizard_case", sample_name, path="/", samesite="lax")
    return response


def render(request: Request, name: str, **extra):
    return templates.TemplateResponse(request, name, ctx(request, **extra))


def ctx(request: Request, **extra):
    conn = get_conn()
    try:
        sid = active_site()
        site = conn.execute("SELECT * FROM site WHERE site_id=?", (sid,)).fetchone()
        if site:
            ok, reasons = svc.masters_complete(conn, sid)
        else:
            ok, reasons = False, ["場所未建立"]
        path = request.url.path
        wizardish = path.startswith("/wizard")
        landing = path == "/"
        base = {
            "request": request,
            "nav": NAV,
            "nav_primary": NAV_PRIMARY,
            "nav_data": NAV_DATA,
            "data_open": path not in ("/", "/report") and not wizardish,
            "floor_mode": False,
            "body_class": "wizard-mode" if wizardish else "",
            "show_masters_banner": (not landing) and (not wizardish),
            "masters_ok": ok,
            "masters_reasons": reasons,
            "site": dict(site) if site else None,
            "prefill": wiz.PREFILL,
            "err": request.query_params.get("err"),
            "okmsg": request.query_params.get("ok"),
            "annex_catalog": fil.annex_catalog(),
        }
        base.update(extra)
        return base
    finally:
        conn.close()


def _flash_url(url: str, key: str, message: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{key}={quote(message)}"


def redirect_err(url: str, message: str) -> RedirectResponse:
    return RedirectResponse(_flash_url(url, "err", message), status_code=303)


def redirect_ok(url: str, message: str = "已存檔") -> RedirectResponse:
    return RedirectResponse(_flash_url(url, "ok", message), status_code=303)


def rows(sql: str, args=()):
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


class ScoreIn(BaseModel):
    consequence_id: str
    severity: int = Field(ge=1, le=5)
    likelihood: int = Field(ge=1, le=5)


class NodeIn(BaseModel):
    equipment_id: str
    deviation: str
    process_id: str | None = None


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return render(request, "home.html", title="首次填報")


@app.get("/floor")
@app.get("/demo")
def demo_enter():
    return RedirectResponse("/processes", status_code=303)


@app.get("/api/floor")
def api_floor():
    conn = get_conn()
    try:
        return floor_bundle(conn, active_site())
    finally:
        conn.close()


@app.post("/api/score")
def api_score(body: ScoreIn):
    conn = get_conn()
    try:
        return score_consequence(conn, body.consequence_id, body.severity, body.likelihood)
    except PsmError as e:
        return JSONResponse({"error": e.message}, status_code=400)
    finally:
        conn.close()


@app.post("/api/node")
def api_node(body: NodeIn):
    conn = get_conn()
    try:
        return create_node_from_equipment(
            conn, body.equipment_id, body.deviation, body.process_id
        )
    except PsmError as e:
        return JSONResponse({"error": e.message}, status_code=400)
    finally:
        conn.close()


@app.post("/reset")
@app.post("/demo/reset")
def reset():
    token = db_mode.set("demo")
    try:
        path = db_path()
        if path.exists():
            path.unlink()
        conn = connect(path)
        init_schema(conn)
        seed_hf_demo(conn)
        conn.close()
    finally:
        db_mode.reset(token)
    resp = redirect_ok("/processes", "已重載 DEMO-SITE")
    resp.set_cookie("psm_mode", "demo", path="/")
    return resp


@app.post("/wizard/reset")
def wizard_reset():
    token = db_mode.set("wizard")
    try:
        path = db_path()
        if path.exists():
            path.unlink()
    finally:
        db_mode.reset(token)
    return redirect_ok("/wizard/1", "已清空首次填報，從步驟 1 開始")


register_wizard(app, get_conn=get_conn, render=render, redirect_ok=redirect_ok, redirect_err=redirect_err)


def _site_exists(conn) -> bool:
    return bool(conn.execute("SELECT 1 FROM site WHERE site_id=?", (WIZARD_SITE_ID,)).fetchone())


@app.get("/site", response_class=HTMLResponse)
def site_page(request: Request):
    return render(request, "site.html")


@app.post("/site")
def site_save(
    site_id: str = Form(...),
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
        svc.save_site(
            conn,
            {
                "site_id": site_id,
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
        return redirect_err("/site", e.message)
    finally:
        conn.close()
    return redirect_ok("/site")


@app.get("/departments", response_class=HTMLResponse)
def departments(request: Request):
    return render(request, "departments.html", departments=rows("SELECT * FROM department ORDER BY dept_id"))


@app.post("/departments")
def departments_save(
    dept_id: str = Form(...),
    name: str = Form(...),
    parent_dept_id: str = Form(""),
):
    conn = get_conn()
    try:
        svc.save_department(
            conn,
            {
                "dept_id": dept_id,
                "site_id": active_site(),
                "name": name,
                "parent_dept_id": parent_dept_id or None,
            },
        )
    except PsmError as e:
        return redirect_err("/departments", e.message)
    finally:
        conn.close()
    return redirect_ok("/departments")


@app.post("/departments/rename")
def departments_rename(dept_id: str = Form(...), name: str = Form(...)):
    conn = get_conn()
    try:
        svc.rename_department(conn, dept_id, name)
    except PsmError as e:
        return redirect_err("/departments", e.message)
    finally:
        conn.close()
    return redirect_ok("/departments", "部門已更名；設備列不必改")


@app.get("/processes", response_class=HTMLResponse)
def processes(request: Request):
    return render(
        request,
        "processes.html",
        processes=rows(
            """SELECT p.*, d.name AS operating_dept_name
               FROM process p JOIN department d ON d.dept_id=p.operating_dept_id
               ORDER BY p.process_id"""
        ),
        departments=rows("SELECT * FROM department ORDER BY dept_id"),
    )


@app.get("/processes/{process_id}", response_class=HTMLResponse)
def process_detail(request: Request, process_id: str):
    conn = get_conn()
    try:
        data = svc.process_inspect(conn, process_id, active_site())
    finally:
        conn.close()
    if not data:
        return redirect_err("/processes", "製程編號不存在")
    return render(request, "process_detail.html", title=f"製程 {process_id}", **data)


@app.post("/processes")
def processes_save(
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
        svc.save_process(
            conn,
            {
                "process_id": process_id,
                "site_id": active_site(),
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
    except PsmError as e:
        return redirect_err("/processes", e.message)
    finally:
        conn.close()
    return redirect_ok("/processes")


@app.get("/areas", response_class=HTMLResponse)
def areas(request: Request):
    return render(
        request,
        "areas.html",
        areas=rows("SELECT * FROM area ORDER BY area_code"),
        processes=rows("SELECT process_id, name FROM process ORDER BY process_id"),
    )


@app.post("/areas")
def areas_save(
    area_code: str = Form(...),
    name: str = Form(...),
    drawing_no: str = Form(...),
    revision: str = Form(...),
    issue_date: str = Form(...),
    process_id: str = Form(""),
    attachment_path: str = Form(...),
    is_assembly_point: str = Form(""),
):
    conn = get_conn()
    try:
        svc.save_area(
            conn,
            {
                "area_code": area_code,
                "site_id": active_site(),
                "name": name,
                "drawing_no": drawing_no,
                "revision": revision,
                "issue_date": issue_date,
                "process_id": process_id or None,
                "attachment_path": attachment_path,
                "is_assembly_point": is_assembly_point,
            },
        )
    except PsmError as e:
        return redirect_err("/areas", e.message)
    finally:
        conn.close()
    return redirect_ok("/areas")


@app.get("/equipment", response_class=HTMLResponse)
def equipment(request: Request):
    conn = get_conn()
    try:
        joined = svc.equipment_list_joined(conn, active_site())
        esd = {p["process_id"]: svc.esd_status(conn, p["process_id"]) for p in conn.execute("SELECT process_id FROM process")}
        scenarios = [dict(r) for r in conn.execute(
            """SELECT s.*, GROUP_CONCAT(a.equipment_id) AS actions
               FROM esd_scenario s LEFT JOIN esd_action a ON a.scenario_id=s.scenario_id
               GROUP BY s.scenario_id"""
        )]
        extra = {
            "equipment": joined,
            "processes": [dict(r) for r in conn.execute("SELECT process_id, name FROM process")],
            "departments": [dict(r) for r in conn.execute("SELECT dept_id, name FROM department")],
            "areas": [dict(r) for r in conn.execute("SELECT area_code, name FROM area")],
            "esd": esd,
            "scenarios": scenarios,
            "eq_all": [dict(r) for r in conn.execute("SELECT equipment_id, process_id, name, equipment_type FROM equipment")],
        }
    finally:
        conn.close()
    return render(request, "equipment.html", **extra)


@app.post("/equipment")
def equipment_save(
    equipment_id: str = Form(...),
    name: str = Form(...),
    process_id: str = Form(""),
    maint_dept_id: str = Form(""),
    equipment_type: str = Form(...),
    power_kind: str = Form(""),
    phase_class: str = Form(...),
    area_code: str = Form(...),
    material: str = Form(""),
    legal_cert_type: str = Form(""),
    alias: str = Form(""),
    is_safety_critical: str = Form(""),
    is_regulated_machinery: str = Form(""),
    is_high_pressure_gas: str = Form(""),
):
    conn = get_conn()
    try:
        svc.save_equipment(
            conn,
            {
                "equipment_id": equipment_id,
                "site_id": active_site(),
                "name": name,
                "process_id": process_id,
                "maint_dept_id": maint_dept_id,
                "equipment_type": equipment_type,
                "power_kind": power_kind or None,
                "phase_class": phase_class,
                "area_code": area_code,
                "material": material or None,
                "legal_cert_type": legal_cert_type or None,
                "alias": alias or None,
                "is_safety_critical": is_safety_critical,
                "is_regulated_machinery": is_regulated_machinery,
                "is_high_pressure_gas": is_high_pressure_gas,
            },
        )
    except PsmError as e:
        return redirect_err("/equipment", e.message)
    finally:
        conn.close()
    return redirect_ok("/equipment")


@app.post("/esd")
def esd_save(
    scenario_id: str = Form(...),
    process_id: str = Form(...),
    esd_equipment_id: str = Form(...),
    name: str = Form(...),
    trigger_conditions: str = Form(...),
    maint_dept_id: str = Form(""),
    action_ids: list[str] = Form(default=[]),
):
    conn = get_conn()
    try:
        svc.save_esd_scenario(
            conn,
            {
                "scenario_id": scenario_id,
                "process_id": process_id,
                "esd_equipment_id": esd_equipment_id,
                "name": name,
                "trigger_conditions": trigger_conditions,
                "maint_dept_id": maint_dept_id or None,
            },
            action_ids=action_ids,
        )
    except PsmError as e:
        return redirect_err("/equipment", e.message)
    finally:
        conn.close()
    return redirect_ok("/equipment", "ESD 方案已存")


@app.get("/chemicals", response_class=HTMLResponse)
def chemicals(request: Request):
    return render(
        request,
        "chemicals.html",
        chemicals=rows(
            """SELECT c.*, p.name AS process_name FROM chemical c
               JOIN process p ON p.process_id=c.process_id ORDER BY c.cas, c.process_id"""
        ),
        processes=rows("SELECT process_id, name FROM process"),
    )


@app.post("/chemicals")
def chemicals_save(
    cas: str = Form(...),
    process_id: str = Form(...),
    name: str = Form(""),
    role: str = Form(...),
    un_number: str = Form(""),
    transport_hazard_class: str = Form(""),
    concentration_range: str = Form(""),
    h_codes: str = Form(""),
    phase_state: str = Form(""),
):
    conn = get_conn()
    try:
        filled = fil.annex_fill_blanks(cas, {"cas": cas, "name": name}, keys=("cas", "name"))
        if not str(filled.get("name") or "").strip():
            return redirect_err(
                "/chemicals",
                "未列於危險物／有害物清單者須自行填名稱",
            )
        svc.save_chemical(
            conn,
            {
                "cas": filled["cas"],
                "process_id": process_id,
                "name": filled["name"],
                "role": role,
                "un_number": un_number or None,
                "transport_hazard_class": transport_hazard_class or None,
                "concentration_range": concentration_range or None,
                "h_codes": h_codes,
                "sds_file": f"placeholder://SDS-{filled['cas']}.pdf",
                **({"phase_state": phase_state.strip()} if phase_state.strip() else {}),
            },
        )
    except PsmError as e:
        return redirect_err("/chemicals", e.message)
    finally:
        conn.close()
    return redirect_ok("/chemicals")


@app.get("/map", response_class=HTMLResponse)
def pec_map_page(request: Request):
    conn = get_conn()
    try:
        extra = {
            "pec_maps": svc.pec_map_rows(conn, site_id=active_site()),
            "processes": [dict(r) for r in conn.execute("SELECT process_id, name FROM process ORDER BY process_id")],
            "equipment": [dict(r) for r in conn.execute(
                "SELECT equipment_id, process_id, name, material FROM equipment ORDER BY equipment_id"
            )],
            "chemicals": [dict(r) for r in conn.execute(
                "SELECT cas, process_id, sds_id, name, h_codes FROM chemical ORDER BY cas, process_id, sds_id"
            )],
            "map_ok": svc.site_map_complete(conn, active_site())[0],
            "map_reasons": svc.site_map_complete(conn, active_site())[1],
        }
    finally:
        conn.close()
    return render(request, "pec.html", **extra)


@app.post("/map")
def pec_map_save(
    process_id: str = Form(...),
    equipment_id: str = Form(...),
    cas: str = Form(""),
    sds_id: str = Form(""),
    no_process_chemical: str = Form(""),
    may_remain: str = Form(""),
    material: str = Form(""),
    review_notes: str = Form(""),
    confirmed: str = Form(""),
    na_reason: str = Form(""),
):
    conn = get_conn()
    try:
        svc.save_pec_map(
            conn,
            {
                "process_id": process_id,
                "equipment_id": equipment_id,
                "cas": cas.split("||", 1)[0] if "||" in cas else cas,
                "sds_id": sds_id or (cas.split("||", 1)[1] if "||" in cas else ""),
                "no_process_chemical": no_process_chemical,
                "may_remain": may_remain,
                "material": material,
                "review_notes": review_notes,
                "confirmed": confirmed,
                "na_reason": na_reason,
            },
        )
    except PsmError as e:
        return redirect_err("/map", e.message)
    finally:
        conn.close()
    return redirect_ok("/map", "對應列已存（僅實際關係）")


@app.post("/prompt/status")
def prompt_status_save(
    prompt_id: str = Form(...),
    status: str = Form(...),
    na_reason: str = Form(""),
    next: str = Form("/map"),
):
    conn = get_conn()
    try:
        svc.set_prompt_status(conn, prompt_id, status, na_reason)
    except PsmError as e:
        return redirect_err(next or "/map", e.message)
    finally:
        conn.close()
    return redirect_ok(next or "/map")


@app.get("/pid", response_class=HTMLResponse)
def pid_page(request: Request):
    return render(
        request,
        "pid.html",
        drawings=rows(
            """SELECT d.*, GROUP_CONCAT(c.equipment_id) AS covering
               FROM pid_drawing d
               LEFT JOIN pid_covering c ON c.drawing_no=d.drawing_no AND c.revision=d.revision
               GROUP BY d.drawing_no, d.revision"""
        ),
        orphans=rows("SELECT * FROM unstructured_attachment"),
        processes=rows("SELECT process_id, name FROM process"),
        equipment=rows("SELECT equipment_id, process_id, name FROM equipment ORDER BY equipment_id"),
    )


@app.post("/pid")
def pid_save(
    drawing_no: str = Form(""),
    revision: str = Form(""),
    process_id: str = Form(""),
    name: str = Form(""),
    issue_date: str = Form(""),
    is_as_built: str = Form(""),
    attachment_path: str = Form(""),
    covering_ids: list[str] = Form(default=[]),
):
    conn = get_conn()
    try:
        svc.save_pid_drawing(
            conn,
            {
                "drawing_no": drawing_no,
                "revision": revision,
                "process_id": process_id,
                "name": name,
                "issue_date": issue_date,
                "is_as_built": is_as_built,
                "attachment_path": attachment_path,
            },
            covering_ids=covering_ids,
        )
    except PsmError as e:
        return redirect_err("/pid", e.message)
    finally:
        conn.close()
    return redirect_ok("/pid")


@app.get("/psi", response_class=HTMLResponse)
def psi_page(request: Request):
    return render(
        request,
        "psi.html",
        inventory=rows("SELECT * FROM inventory"),
        limits=rows("SELECT * FROM equipment_limit"),
        materials=rows("SELECT * FROM equipment_material"),
        relief=rows("SELECT * FROM relief_device"),
        interlocks=rows("SELECT * FROM interlock"),
        occupancy=rows("SELECT * FROM loading_occupancy"),
        chemicals=rows("SELECT cas, process_id, name FROM chemical"),
        equipment=rows("SELECT equipment_id, name, equipment_type, process_id FROM equipment"),
        areas=rows("SELECT area_code, name FROM area"),
        processes=rows("SELECT process_id, name FROM process"),
        scenarios=rows("SELECT scenario_id, name FROM esd_scenario"),
        drawings=rows("SELECT drawing_no, revision FROM pid_drawing"),
    )


@app.post("/psi/inventory")
def psi_inventory(
    cas: str = Form(...),
    process_id: str = Form(...),
    max_kg: str = Form(...),
    area_code: str = Form(...),
    calc_note: str = Form(""),
):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO inventory(cas, process_id, max_kg, area_code, calc_note)
               VALUES (?,?,?,?,?)
               ON CONFLICT(cas, process_id) DO UPDATE SET max_kg=excluded.max_kg,
                 area_code=excluded.area_code, calc_note=excluded.calc_note""",
            (cas, process_id, float(max_kg), area_code, calc_note),
        )
        conn.commit()
    except Exception as e:
        return redirect_err("/psi", str(e))
    finally:
        conn.close()
    return redirect_ok("/psi")


@app.post("/psi/limit")
def psi_limit(
    equipment_id: str = Form(...),
    parameter: str = Form(...),
    unit: str = Form(""),
    design_high: str = Form(""),
    design_low: str = Form(""),
    safety_high: str = Form(""),
    safety_low: str = Form(""),
):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO equipment_limit(equipment_id, parameter, unit, design_high,
                design_low, safety_high, safety_low) VALUES (?,?,?,?,?,?,?)""",
            (equipment_id, parameter, unit, design_high, design_low, safety_high, safety_low),
        )
        conn.commit()
    except Exception as e:
        return redirect_err("/psi", str(e))
    finally:
        conn.close()
    return redirect_ok("/psi")


@app.post("/psi/occupancy")
def psi_occupancy(
    occupancy_id: str = Form(...),
    equipment_id: str = Form(...),
    process_id: str = Form(...),
    cas: str = Form(...),
    plate_or_container: str = Form(...),
    start_ts: str = Form(...),
    end_ts: str = Form(""),
):
    conn = get_conn()
    try:
        svc.save_loading_occupancy(
            conn,
            {
                "occupancy_id": occupancy_id,
                "equipment_id": equipment_id,
                "process_id": process_id,
                "cas": cas,
                "plate_or_container": plate_or_container,
                "start_ts": start_ts,
                "end_ts": end_ts or None,
            },
        )
    except PsmError as e:
        return redirect_err("/psi", e.message)
    finally:
        conn.close()
    return redirect_ok("/psi", "裝卸佔用已寫車牌，未新增設備列")


def _cas_process(token: str) -> tuple[str, str]:
    cas, _, process_id = (token or "").partition("|")
    return cas, process_id


@app.post("/psi/material")
def psi_material(
    equipment_id: str = Form(...),
    material: str = Form(...),
    material_category: str = Form(""),
    spec: str = Form(""),
):
    conn = get_conn()
    try:
        svc.save_equipment_material(
            conn,
            {
                "equipment_id": equipment_id,
                "material": material,
                "material_category": material_category,
                "spec": spec,
            },
        )
    except PsmError as e:
        return redirect_err("/psi", e.message)
    finally:
        conn.close()
    return redirect_ok("/psi")


@app.post("/psi/relief")
def psi_relief(
    equipment_id: str = Form(...),
    device_type: str = Form(...),
    set_pressure: str = Form(""),
    released_cas: str = Form(""),
    pid_drawing_no: str = Form(""),
):
    conn = get_conn()
    try:
        cas, process_id = _cas_process(released_cas)
        drawing, _, revision = (pid_drawing_no or "").partition("|")
        conn.execute(
            """INSERT INTO relief_device(
                equipment_id, device_type, set_pressure, pid_drawing_no, pid_revision,
                released_cas, released_process_id
            ) VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(equipment_id) DO UPDATE SET
                device_type=excluded.device_type, set_pressure=excluded.set_pressure,
                pid_drawing_no=excluded.pid_drawing_no, pid_revision=excluded.pid_revision,
                released_cas=excluded.released_cas, released_process_id=excluded.released_process_id""",
            (equipment_id, device_type, set_pressure, drawing, revision, cas, process_id),
        )
        conn.commit()
    except Exception as e:
        return redirect_err("/psi", str(e))
    finally:
        conn.close()
    return redirect_ok("/psi")


@app.post("/psi/interlock")
def psi_interlock(
    interlock_id: str = Form(...),
    equipment_id: str = Form(...),
    name: str = Form(...),
    function_desc: str = Form(...),
    scenario_id: str = Form(""),
):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT process_id FROM equipment WHERE equipment_id=?", (equipment_id,)
        ).fetchone()
        if not row:
            return redirect_err("/psi", "設備須選已有編號")
        conn.execute(
            """INSERT INTO interlock(
                interlock_id, process_id, equipment_id, name, function_desc, scenario_id
            ) VALUES (?,?,?,?,?,?)
            ON CONFLICT(interlock_id) DO UPDATE SET
                process_id=excluded.process_id, equipment_id=excluded.equipment_id,
                name=excluded.name, function_desc=excluded.function_desc,
                scenario_id=excluded.scenario_id""",
            (
                interlock_id,
                row["process_id"],
                equipment_id,
                name,
                function_desc,
                scenario_id or None,
            ),
        )
        conn.commit()
    except Exception as e:
        return redirect_err("/psi", str(e))
    finally:
        conn.close()
    return redirect_ok("/psi")


@app.get("/checks", response_class=HTMLResponse)
def checks(request: Request):
    return render(
        request,
        "checks.html",
        hazards=rows("SELECT * FROM chem_hazard_check"),
        compat=rows("SELECT * FROM chem_compatibility"),
        handling=rows("SELECT * FROM chem_handling"),
        chemicals=rows("SELECT cas, process_id, name FROM chemical"),
        equipment=rows("SELECT equipment_id, name FROM equipment"),
    )


@app.post("/checks/hazard")
def checks_hazard(
    cas: str = Form(...),
    process_id: str = Form(...),
    toxicity: str = Form(""),
    pel_twa: str = Form(""),
    flash_point: str = Form(""),
    fire: str = Form(""),
    explosion: str = Form(""),
):
    conn = get_conn()
    try:
        sds_id = svc.resolve_component_sds(conn, process_id, cas, None)
        conn.execute(
            """INSERT INTO chem_hazard_check(cas, process_id, sds_id, toxicity, pel_twa, flash_point, fire, explosion)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(process_id, sds_id, cas) DO UPDATE SET toxicity=excluded.toxicity,
                 pel_twa=excluded.pel_twa, flash_point=excluded.flash_point,
                 fire=excluded.fire, explosion=excluded.explosion""",
            (cas, process_id, sds_id, toxicity, pel_twa, flash_point, 1 if fire else 0, 1 if explosion else 0),
        )
        conn.commit()
    except Exception as e:
        return redirect_err("/checks", str(e))
    finally:
        conn.close()
    return redirect_ok("/checks")


@app.post("/checks/compat")
def checks_compat(
    cas: str = Form(...),
    equipment_id: str = Form(""),
    compatible: str = Form(""),
    hazard_note: str = Form(""),
):
    conn = get_conn()
    try:
        cas_a, process_id = _cas_process(cas)
        conn.execute(
            """INSERT INTO chem_compatibility(
                cas_a, process_id_a, equipment_id, compatible, hazard_note
            ) VALUES (?,?,?,?,?)""",
            (cas_a, process_id, equipment_id or None, 1 if compatible else 0, hazard_note),
        )
        conn.commit()
    except Exception as e:
        return redirect_err("/checks", str(e))
    finally:
        conn.close()
    return redirect_ok("/checks")


@app.post("/checks/handling")
def checks_handling(
    cas: str = Form(...),
    storage_notes: str = Form(""),
    process_conditions: str = Form(""),
    emergency_notes: str = Form(""),
):
    conn = get_conn()
    try:
        cas_no, process_id = _cas_process(cas)
        conn.execute(
            """INSERT INTO chem_handling(cas, process_id, storage_notes, process_conditions, emergency_notes)
               VALUES (?,?,?,?,?)
               ON CONFLICT(cas, process_id) DO UPDATE SET
                 storage_notes=excluded.storage_notes,
                 process_conditions=excluded.process_conditions,
                 emergency_notes=excluded.emergency_notes""",
            (cas_no, process_id, storage_notes, process_conditions, emergency_notes),
        )
        conn.commit()
    except Exception as e:
        return redirect_err("/checks", str(e))
    finally:
        conn.close()
    return redirect_ok("/checks")


@app.get("/hazop", response_class=HTMLResponse)
def hazop(request: Request, process_id: str = ""):
    conn = get_conn()
    try:
        ok, reasons = svc.masters_complete(conn, active_site())
        choices = svc.equipment_choices(conn, process_id or None)
        chems = svc.chemical_choices(conn, process_id or None)
        drawings = svc.hazop_usable_drawings(conn, process_id or None)
        gaps = svc.coverage_gaps(conn, process_id) if process_id else []
        nodes = []
        if process_id:
            nodes = [dict(r) for r in conn.execute(
                """SELECT n.*, GROUP_CONCAT(DISTINCT ne.equipment_id) AS equipment_ids,
                          GROUP_CONCAT(DISTINCT nc.cas) AS cas_list
                   FROM node n
                   LEFT JOIN node_equipment ne ON ne.node_id=n.node_id
                   LEFT JOIN node_chemical nc ON nc.node_id=n.node_id
                   WHERE n.process_id=?
                   GROUP BY n.node_id""",
                (process_id,),
            )]
        extra = {
            "process_id": process_id,
            "processes": [dict(r) for r in conn.execute("SELECT process_id, name FROM process")],
            "eq_choices": choices,
            "chem_choices": chems,
            "drawings": drawings,
            "gaps": gaps,
            "nodes": nodes,
            "assessments": (
                svc.assessments_touching_process(conn, process_id)
                if process_id
                else [dict(r) for r in conn.execute("SELECT * FROM assessment ORDER BY assessment_id")]
            ),
            "consequences": [dict(r) for r in conn.execute(
                """SELECT c.*, n.process_id FROM consequence c JOIN node n ON n.node_id=c.node_id"""
            )],
            "safeguards": [dict(r) for r in conn.execute("SELECT * FROM safeguard")],
            "scores": [dict(r) for r in conn.execute("SELECT * FROM risk_score")],
            "recs": [dict(r) for r in conn.execute("SELECT * FROM recommendation")],
            "sops": [dict(r) for r in conn.execute("SELECT sop_id, process_id, title, op_kind, equipment_id FROM sop")],
            "scenarios": [dict(r) for r in conn.execute("SELECT scenario_id, process_id, name FROM esd_scenario")],
            "areas": [dict(r) for r in conn.execute("SELECT area_code, name FROM area")],
            "scoring_blocked": not ok,
            "scoring_reasons": list(reasons),
            "pha_prompts": svc.prompt_events(conn, process_id=process_id or None, stage="pha") if process_id else [],
        }
        if process_id:
            mok, mreasons = svc.map_complete(conn, process_id)
            if not mok:
                extra["scoring_blocked"] = True
                extra["scoring_reasons"].extend(mreasons)
    finally:
        conn.close()
    return render(request, "hazop.html", **extra)


@app.post("/hazop/assessment")
def hazop_assessment(
    assessment_id: str = Form(...),
    process_id: str = Form(""),
    method: str = Form("HAZOP"),
    assessment_date: str = Form(""),
):
    conn = get_conn()
    try:
        svc.save_assessment(
            conn,
            {
                "assessment_id": assessment_id,
                "process_id": process_id,
                "method": method,
                "matrix_version": MATRIX_VERSION,
                "assessment_date": assessment_date,
            },
        )
    except PsmError as e:
        return redirect_err("/hazop", e.message)
    finally:
        conn.close()
    return redirect_ok(f"/hazop?process_id={quote(process_id)}")


@app.post("/hazop/node")
def hazop_node(
    node_id: str = Form(...),
    assessment_id: str = Form(...),
    process_id: str = Form(...),
    description: str = Form(...),
    deviation: str = Form(...),
    cause: str = Form(...),
    drawing_no: str = Form(""),
    drawing_revision: str = Form(""),
    equipment_ids: list[str] = Form(default=[]),
    cas_list: list[str] = Form(default=[]),
    considers_location: str = Form(""),
    considers_human: str = Form(""),
    considers_control_failure: str = Form(""),
):
    conn = get_conn()
    try:
        dno, drev = drawing_no, drawing_revision
        if drawing_no and "||" in drawing_no:
            dno, drev = drawing_no.split("||", 1)
        svc.save_node(
            conn,
            {
                "node_id": node_id,
                "assessment_id": assessment_id,
                "process_id": process_id,
                "description": description,
                "deviation": deviation,
                "cause": cause,
                "drawing_no": dno,
                "drawing_revision": drev,
                "considers_location": considers_location,
                "considers_human": considers_human,
                "considers_control_failure": considers_control_failure,
            },
            equipment_ids=equipment_ids,
            cas_list=cas_list,
        )
    except PsmError as e:
        return redirect_err(f"/hazop?process_id={quote(process_id)}", e.message)
    finally:
        conn.close()
    return redirect_ok(f"/hazop?process_id={quote(process_id)}")


@app.post("/hazop/consequence")
def hazop_cons(
    consequence_id: str = Form(...),
    node_id: str = Form(...),
    description: str = Form(...),
    disaster_type: str = Form("外洩"),
    area_code: str = Form(""),
    process_id: str = Form(""),
):
    conn = get_conn()
    try:
        svc.save_consequence(
            conn,
            {
                "consequence_id": consequence_id,
                "node_id": node_id,
                "description": description,
                "disaster_type": disaster_type,
                "area_code": area_code or None,
            },
        )
    except PsmError as e:
        return redirect_err(f"/hazop?process_id={quote(process_id)}", e.message)
    finally:
        conn.close()
    return redirect_ok(f"/hazop?process_id={quote(process_id)}")


@app.post("/hazop/safeguard")
def hazop_sg(
    safeguard_id: str = Form(...),
    consequence_id: str = Form(...),
    kind: str = Form(...),
    equipment_id: str = Form(""),
    scenario_id: str = Form(""),
    sop_id: str = Form(""),
    process_id: str = Form(""),
):
    conn = get_conn()
    try:
        svc.save_safeguard(
            conn,
            {
                "safeguard_id": safeguard_id,
                "consequence_id": consequence_id,
                "kind": kind,
                "equipment_id": equipment_id or None,
                "scenario_id": scenario_id or None,
                "sop_id": sop_id or None,
            },
        )
    except PsmError as e:
        return redirect_err(f"/hazop?process_id={quote(process_id)}", e.message)
    finally:
        conn.close()
    return redirect_ok(f"/hazop?process_id={quote(process_id)}")


@app.post("/hazop/score")
def hazop_score(
    risk_id: str = Form(...),
    consequence_id: str = Form(...),
    severity: int = Form(...),
    likelihood: int = Form(...),
    process_id: str = Form(""),
):
    conn = get_conn()
    try:
        svc.save_risk_score(
            conn,
            {
                "risk_id": risk_id,
                "consequence_id": consequence_id,
                "matrix_version": MATRIX_VERSION,
                "severity": severity,
                "likelihood": likelihood,
            },
        )
    except PsmError as e:
        return redirect_err(f"/hazop?process_id={quote(process_id)}", e.message)
    finally:
        conn.close()
    return redirect_ok(f"/hazop?process_id={quote(process_id)}")


@app.post("/hazop/complete")
def hazop_complete(assessment_id: str = Form(...), process_id: str = Form("")):
    conn = get_conn()
    try:
        svc.mark_assessment_complete(conn, assessment_id)
    except PsmError as e:
        return redirect_err(f"/hazop?process_id={quote(process_id)}", e.message)
    finally:
        conn.close()
    return redirect_ok(f"/hazop?process_id={quote(process_id)}", "評估已標示完成")


@app.post("/hazop/rec")
def hazop_rec(
    rec_id: str = Form(...),
    assessment_id: str = Form(...),
    consequence_id: str = Form(""),
    target_table: str = Form(""),
    target_pk: str = Form(""),
    description: str = Form(...),
    process_id: str = Form(""),
):
    conn = get_conn()
    try:
        svc.save_recommendation(
            conn,
            {
                "rec_id": rec_id,
                "assessment_id": assessment_id,
                "consequence_id": consequence_id or None,
                "target_table": target_table or None,
                "target_pk": target_pk or None,
                "description": description,
            },
        )
    except PsmError as e:
        return redirect_err(f"/hazop?process_id={quote(process_id)}", e.message)
    finally:
        conn.close()
    return redirect_ok(f"/hazop?process_id={quote(process_id)}")


@app.post("/hazop/rec/close")
def hazop_rec_close(
    rec_id: str = Form(...),
    master_updated: str = Form(""),
    reassessed_or_waiver: str = Form(""),
    marked_improved: str = Form(""),
    process_id: str = Form(""),
):
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE recommendation SET marked_improved=?, master_updated=?, reassessed_or_waiver=?
               WHERE rec_id=?""",
            (
                1 if marked_improved else 0,
                1 if master_updated else 0,
                1 if reassessed_or_waiver else 0,
                rec_id,
            ),
        )
        conn.commit()
        svc.close_recommendation(conn, rec_id)
    except PsmError as e:
        return redirect_err(f"/hazop?process_id={quote(process_id)}", e.message)
    finally:
        conn.close()
    return redirect_ok(f"/hazop?process_id={quote(process_id)}", "改善已關閉")


def _unit_page(request: Request, template: str, **extra):
    return render(request, template, **extra)


@app.get("/labor", response_class=HTMLResponse)
def labor(request: Request):
    return _unit_page(
        request,
        "labor.html",
        unit_no=3,
        activities=rows("SELECT * FROM worker_activity"),
        processes=rows("SELECT process_id, name FROM process"),
    )


@app.post("/labor")
def labor_save(
    activity_id: str = Form(...),
    process_id: str = Form(...),
    activity_type: str = Form(...),
    activity_date: str = Form(...),
    description: str = Form(...),
):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO worker_activity(activity_id, process_id, activity_type, activity_date, description)
               VALUES (?,?,?,?,?)""",
            (activity_id, process_id, activity_type, activity_date, description),
        )
        conn.commit()
    except Exception as e:
        return redirect_err("/labor", str(e))
    finally:
        conn.close()
    return redirect_ok("/labor")


@app.get("/sop", response_class=HTMLResponse)
def sop_page(request: Request):
    conn = get_conn()
    try:
        board = svc.sop_board(conn, active_site())
        equipment = svc.equipment_list_joined(conn, active_site())
        processes = [dict(r) for r in conn.execute("SELECT process_id, name FROM process ORDER BY process_id")]
    finally:
        conn.close()
    return _unit_page(
        request,
        "sop.html",
        unit_no=4,
        board=board,
        equipment=equipment,
        processes=processes,
    )


@app.post("/sop")
def sop_save(
    sop_id: str = Form(...),
    title: str = Form(...),
    procedure_no: str = Form(""),
    op_kind: str = Form("process"),
    process_id: str = Form(""),
    equipment_id: str = Form(""),
):
    conn = get_conn()
    try:
        svc.save_sop(
            conn,
            {
                "sop_id": sop_id,
                "title": title,
                "procedure_no": procedure_no or None,
                "body": "",
                "op_kind": op_kind,
                "process_id": process_id,
                "equipment_id": equipment_id,
            },
        )
    except PsmError as e:
        return redirect_err("/sop", e.message)
    finally:
        conn.close()
    return redirect_ok("/sop")


@app.get("/training", response_class=HTMLResponse)
def training(request: Request):
    conn = get_conn()
    try:
        board = svc.training_board(conn, active_site())
        equipment = svc.equipment_list_joined(conn, active_site())
        processes = [dict(r) for r in conn.execute("SELECT process_id, name FROM process ORDER BY process_id")]
        courses = [dict(r) for r in conn.execute("SELECT course_id, name FROM training_course ORDER BY course_id")]
    finally:
        conn.close()
    return _unit_page(
        request,
        "training.html",
        unit_no=5,
        board=board,
        equipment=equipment,
        processes=processes,
        courses=courses,
        records=board["records"],
    )


@app.post("/training/course")
def training_course(
    course_id: str = Form(...),
    name: str = Form(...),
    hours: str = Form("0"),
    audience: str = Form(""),
    kind: str = Form("initial"),
    op_kind: str = Form("process"),
    process_id: str = Form(""),
    equipment_id: str = Form(""),
):
    conn = get_conn()
    try:
        svc.save_training_course(
            conn,
            {
                "course_id": course_id,
                "name": name,
                "hours": hours,
                "audience": audience,
                "kind": kind,
                "op_kind": op_kind,
                "process_id": process_id,
                "equipment_id": equipment_id,
            },
        )
    except PsmError as e:
        return redirect_err("/training", e.message)
    finally:
        conn.close()
    return redirect_ok("/training")


@app.post("/training/record")
def training_record(
    record_id: str = Form(...),
    course_id: str = Form(...),
    trainee: str = Form(...),
    train_date: str = Form(...),
    tested: str = Form(""),
):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO training_record(record_id, course_id, trainee, train_date, tested)
               VALUES (?,?,?,?,?)""",
            (record_id, course_id, trainee, train_date, 1 if tested else 0),
        )
        conn.commit()
    except Exception as e:
        return redirect_err("/training", str(e))
    finally:
        conn.close()
    return redirect_ok("/training")


@app.get("/contractor", response_class=HTMLResponse)
def contractor(request: Request):
    return _unit_page(
        request,
        "contractor.html",
        unit_no=6,
        incidents=rows(
            """SELECT c.incident_id, c.contractor_name, c.contract_period, c.incident_type,
                      c.linked_incident_id,
                      COALESCE(NULLIF(c.summary, ''), a.summary) AS summary,
                      COALESCE(c.occur_date, a.incident_date) AS occur_date,
                      COALESCE(c.process_id, a.process_id) AS process_id,
                      COALESCE(c.equipment_id, a.equipment_id) AS equipment_id
               FROM contractor_incident c
               LEFT JOIN incident a ON a.incident_id=c.linked_incident_id
               ORDER BY occur_date, c.incident_id"""
        ),
        accidents=rows("SELECT incident_id, summary FROM incident ORDER BY incident_date, incident_id"),
        processes=rows("SELECT process_id, name FROM process"),
        equipment=rows("SELECT equipment_id, name FROM equipment"),
    )


@app.post("/contractor")
def contractor_save(
    incident_id: str = Form(""),
    contractor_name: str = Form(...),
    contract_period: str = Form(""),
    incident_type: str = Form("虛驚"),
    linked_incident_id: str = Form(""),
):
    conn = get_conn()
    try:
        svc.save_contractor_incident(
            conn,
            {
                "incident_id": incident_id,
                "site_id": active_site(),
                "contractor_name": contractor_name,
                "contract_period": contract_period,
                "incident_type": incident_type,
                "linked_incident_id": linked_incident_id,
            },
        )
    except PsmError as e:
        return redirect_err("/contractor", e.message)
    finally:
        conn.close()
    return redirect_ok("/contractor")


@app.get("/pssr", response_class=HTMLResponse)
def pssr_page(request: Request):
    return _unit_page(
        request,
        "pssr.html",
        unit_no=7,
        pssrs=rows("SELECT * FROM pssr"),
        equipment=rows("SELECT equipment_id, name FROM equipment"),
        processes=rows("SELECT process_id, name FROM process"),
        changes=rows("SELECT change_id, target_table, target_pk FROM change_request"),
    )


@app.post("/pssr")
def pssr_save(
    pssr_id: str = Form(...),
    pssr_date: str = Form(...),
    findings: str = Form(""),
    equipment_id: str = Form(""),
    process_id: str = Form(""),
    change_id: str = Form(""),
):
    if not equipment_id and not process_id:
        return redirect_err("/pssr", "PSSR 須掛設備編號或變更所涉製程")
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO pssr(pssr_id, equipment_id, process_id, change_id, pssr_date, findings)
               VALUES (?,?,?,?,?,?)""",
            (pssr_id, equipment_id or None, process_id or None, change_id or None, pssr_date, findings),
        )
        conn.commit()
    except Exception as e:
        return redirect_err("/pssr", str(e))
    finally:
        conn.close()
    return redirect_ok("/pssr")


@app.get("/mi", response_class=HTMLResponse)
def mi_page(request: Request):
    conn = get_conn()
    try:
        extra = {
            "unit_no": 8,
            "equipment": svc.equipment_list_joined(conn, active_site()),
            "inspections": [dict(r) for r in conn.execute("SELECT * FROM inspection")],
            "esd": {p["process_id"]: svc.esd_status(conn, p["process_id"]) for p in conn.execute("SELECT process_id FROM process")},
            "mi_prompts": svc.prompt_events(conn, stage="mi"),
            "screens": [
                dict(r)
                for r in conn.execute(
                    """SELECT s.*, e.equipment_type, e.name,
                              f.period_start, f.period_end, f.run_hours, f.failure_count,
                              CASE WHEN f.run_hours>0
                                   THEN ROUND(f.failure_count * 1000000.0 / f.run_hours, 2)
                                   ELSE NULL END AS failure_rate
                       FROM mi_screen s
                       JOIN equipment e ON e.equipment_id=s.equipment_id
                       LEFT JOIN mi_failure f ON f.equipment_id=s.equipment_id
                       ORDER BY s.equipment_id"""
                )
            ],
            "mi_details": [dict(r) for r in conn.execute(
                """SELECT d.*,e.process_id FROM mi_inspection_detail d
                   JOIN equipment e ON e.equipment_id=d.equipment_id
                   WHERE e.site_id=? ORDER BY d.equipment_id,d.detail_id""",
                (active_site(),),
            )],
            "mi_six": fil.MI_SIX,
        }
    finally:
        conn.close()
    return render(request, "mi.html", **extra)


@app.post("/mi/inspection")
def mi_insp(
    inspection_id: str = Form(...),
    equipment_id: str = Form(...),
    inspect_date: str = Form(...),
    inspector: str = Form(...),
    method: str = Form(...),
    result: str = Form(...),
):
    conn = get_conn()
    try:
        svc.save_inspection(
            conn,
            {
                "inspection_id": inspection_id,
                "equipment_id": equipment_id,
                "inspect_date": inspect_date,
                "inspector": inspector,
                "method": method,
                "result": result,
            },
        )
    except PsmError as e:
        return redirect_err("/mi", e.message)
    finally:
        conn.close()
    return redirect_ok("/mi")


@app.post("/mi/screen")
def mi_screen_save(
    equipment_id: str = Form(...),
    basis: str = Form(...),
    is_critical: str = Form(""),
    mi_type: str = Form(""),
    damage_mechanism: str = Form(""),
    inspection_item: str = Form(""),
    inspect_method: str = Form(""),
    inspect_frequency: str = Form(""),
    procedure_ref: str = Form(""),
    pid_drawing_no: str = Form(""),
):
    conn = get_conn()
    try:
        svc.save_mi_screen(
            conn,
            {
                "equipment_id": equipment_id,
                "basis": basis,
                "is_critical": bool(is_critical),
                "mi_type": mi_type,
                "damage_mechanism": damage_mechanism,
                "inspection_item": inspection_item,
                "inspect_method": inspect_method,
                "inspect_frequency": inspect_frequency,
                "procedure_ref": procedure_ref,
                "pid_drawing_no": pid_drawing_no,
            },
        )
    except PsmError as e:
        return redirect_err("/mi", e.message)
    finally:
        conn.close()
    return redirect_ok("/mi")


@app.get("/hotwork", response_class=HTMLResponse)
def hotwork(request: Request):
    return _unit_page(
        request,
        "hotwork.html",
        unit_no=9,
        permits=rows("SELECT * FROM hotwork_permit"),
        zones=rows(
            """SELECT z.*, a.name AS area_name
               FROM hotwork_zone z JOIN area a ON a.area_code=z.area_code
               ORDER BY z.area_code"""
        ),
        equipment=rows("SELECT equipment_id, name FROM equipment"),
        areas=rows("SELECT area_code, name FROM area"),
    )


@app.post("/hotwork")
def hotwork_save(
    permit_id: str = Form(...),
    equipment_id: str = Form(...),
    area_code: str = Form(""),
    permit_date: str = Form(...),
    measures: str = Form(""),
):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO hotwork_permit(permit_id, equipment_id, area_code, permit_date, measures)
               VALUES (?,?,?,?,?)""",
            (permit_id, equipment_id, area_code or None, permit_date, measures),
        )
        conn.commit()
    except Exception as e:
        return redirect_err("/hotwork", str(e))
    finally:
        conn.close()
    return redirect_ok("/hotwork")


@app.post("/hotwork/zone")
def hotwork_zone_save(
    area_code: str = Form(...),
    protection_reason: str = Form(...),
):
    conn = get_conn()
    try:
        svc.save_hotwork_zone(
            conn,
            {"area_code": area_code, "protection_reason": protection_reason},
        )
    except PsmError as e:
        return redirect_err("/hotwork", e.message)
    finally:
        conn.close()
    return redirect_ok("/hotwork")


@app.get("/moc", response_class=HTMLResponse)
def moc(request: Request):
    return _unit_page(
        request,
        "moc.html",
        unit_no=10,
        changes=rows("SELECT * FROM change_request"),
        processes=rows("SELECT process_id FROM process"),
        equipment=rows("SELECT equipment_id FROM equipment"),
        chemicals=rows("SELECT cas, process_id FROM chemical"),
    )


@app.post("/moc")
def moc_save(
    change_id: str = Form(...),
    target_table: str = Form(...),
    target_pk: str = Form(...),
    description: str = Form(...),
    change_type: str = Form(""),
    approved: str = Form(""),
):
    conn = get_conn()
    try:
        svc.save_change(
            conn,
            {
                "change_id": change_id,
                "target_table": target_table,
                "target_pk": target_pk,
                "description": description,
                "change_type": change_type,
                "status": "approved" if approved else "draft",
                "approved": approved,
            },
        )
    except PsmError as e:
        return redirect_err("/moc", e.message)
    finally:
        conn.close()
    return redirect_ok("/moc")


@app.get("/incident", response_class=HTMLResponse)
def incident(request: Request):
    return _unit_page(
        request,
        "incident.html",
        unit_no=11,
        incidents=rows("SELECT * FROM incident WHERE site_id=?", (active_site(),)),
        processes=rows("SELECT process_id, name FROM process"),
        equipment=rows("SELECT equipment_id, name FROM equipment"),
        chemicals=rows("SELECT cas, process_id FROM chemical"),
    )


@app.post("/incident")
def incident_save(
    incident_id: str = Form(...),
    summary: str = Form(...),
    process_id: str = Form(""),
    equipment_id: str = Form(""),
    cas: str = Form(""),
    incident_date: str = Form(""),
    is_near_miss: str = Form(""),
):
    conn = get_conn()
    try:
        svc.save_incident(
            conn,
            {
                "incident_id": incident_id,
                "site_id": active_site(),
                "summary": summary,
                "process_id": process_id,
                "equipment_id": equipment_id,
                "cas": cas,
                "incident_date": incident_date,
                "is_near_miss": bool(is_near_miss),
                "characteristics": "其他" if is_near_miss else "",
            },
        )
    except Exception as e:
        return redirect_err("/incident", str(e))
    finally:
        conn.close()
    return redirect_ok("/incident")


@app.get("/emergency", response_class=HTMLResponse)
def emergency(request: Request):
    org = rows("SELECT * FROM emergency_org")
    return _unit_page(
        request,
        "emergency.html",
        unit_no=12,
        org=org[0] if org else None,
        drills=rows("SELECT * FROM drill"),
        areas=rows("SELECT * FROM area"),
        processes=rows("SELECT process_id, name FROM process"),
        consequences=rows("SELECT consequence_id, description FROM consequence"),
    )


@app.post("/emergency/drill")
def emergency_drill(
    drill_id: str = Form(...),
    process_id: str = Form(...),
    consequence_id: str = Form(""),
    drill_date: str = Form(...),
    notes: str = Form(""),
):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO drill(drill_id, process_id, consequence_id, drill_date, notes)
               VALUES (?,?,?,?,?)""",
            (drill_id, process_id, consequence_id or None, drill_date, notes),
        )
        conn.commit()
    except Exception as e:
        return redirect_err("/emergency", str(e))
    finally:
        conn.close()
    return redirect_ok("/emergency")


@app.get("/audit", response_class=HTMLResponse)
def audit(request: Request):
    plans = rows("SELECT * FROM audit_plan")
    return _unit_page(
        request,
        "audit.html",
        unit_no=13,
        plan=plans[0] if plans else None,
        checklist=rows("SELECT * FROM audit_checklist ORDER BY item_no"),
    )


@app.get("/secret", response_class=HTMLResponse)
def secret(request: Request):
    return _unit_page(
        request,
        "secret.html",
        unit_no=14,
        secrets=rows("SELECT * FROM trade_secret"),
        processes=rows("SELECT process_id, name FROM process"),
        drawings=rows("SELECT drawing_no, revision FROM pid_drawing"),
    )


@app.post("/secret")
def secret_save(
    doc_id: str = Form(...),
    title: str = Form(...),
    process_id: str = Form(""),
    drawing_no: str = Form(""),
):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO trade_secret(doc_id, process_id, drawing_no, title, ids_selectable)
               VALUES (?,?,?,?,1)""",
            (doc_id, process_id or None, drawing_no or None, title),
        )
        conn.commit()
    except Exception as e:
        return redirect_err("/secret", str(e))
    finally:
        conn.close()
    return redirect_ok("/secret")


@app.get("/report")
def report_page():
    conn = get_conn()
    try:
        html = svc.generate_report_html(conn, active_site())
        out = db_path().parent / "report.html"
        out.write_text(html, encoding="utf-8")
    finally:
        conn.close()
    return HTMLResponse(html)


@app.get("/report/file")
def report_file():
    conn = get_conn()
    try:
        html = svc.generate_report_html(conn, active_site())
        out = db_path().parent / "report.html"
        out.write_text(html, encoding="utf-8")
        return Response(
            html,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=psm-14-report.html"},
        )
    finally:
        conn.close()
