"""現場廠區示意：座標寫死 DEMO-SITE，檢核仍走 services。"""

from __future__ import annotations

import sqlite3

from psm.enums import MATRIX_ACCEPT_LINE, MATRIX_VERSION, SITE_ID
from psm.errors import PsmError
from psm import services as svc

DEVIATIONS = ("液位過高", "無流量", "洩漏", "出口閥誤關")

# 示意座標（SVG viewBox 960×540），不是真 P&ID。
LAYOUT = {
    "T-101": {"x": 168, "y": 236, "kind": "tank"},
    "P-101": {"x": 318, "y": 312, "kind": "pump"},
    "PSV-101": {"x": 248, "y": 148, "kind": "relief"},
    "ESD-101": {"x": 408, "y": 176, "kind": "esd"},
    "S-201": {"x": 468, "y": 372, "kind": "scrub"},
    "LA-101": {"x": 768, "y": 252, "kind": "loading"},
}

AREAS_BOX = {
    "AREA-A": {"x": 28, "y": 52, "w": 540, "h": 448, "label": "儲槽區"},
    "AREA-B": {"x": 588, "y": 52, "w": 344, "h": 448, "label": "裝卸場"},
}


def _next_id(conn: sqlite3.Connection, table: str, col: str, prefix: str) -> str:
    n = 1
    while True:
        cand = f"{prefix}{n:02d}"
        if not conn.execute(f"SELECT 1 FROM {table} WHERE {col}=?", (cand,)).fetchone():
            return cand
        n += 1


def floor_bundle(conn: sqlite3.Connection, site_id: str = SITE_ID) -> dict:
    ok, reasons = svc.masters_complete(conn, site_id)
    site = conn.execute("SELECT * FROM site WHERE site_id=?", (site_id,)).fetchone()
    processes = []
    for p in conn.execute(
        "SELECT process_id, name FROM process WHERE site_id=? ORDER BY process_id",
        (site_id,),
    ):
        processes.append(
            {
                "process_id": p["process_id"],
                "name": p["name"],
                "assessment_id": svc.assessment_id_for_process(conn, p["process_id"]),
            }
        )
    areas = []
    for a in conn.execute(
        "SELECT area_code, name, is_assembly_point FROM area WHERE site_id=? ORDER BY area_code",
        (site_id,),
    ):
        box = AREAS_BOX.get(a["area_code"], {"x": 40, "y": 40, "w": 200, "h": 200, "label": a["name"]})
        areas.append(
            {
                "area_code": a["area_code"],
                "name": a["name"],
                "is_assembly_point": bool(a["is_assembly_point"]),
                **box,
            }
        )

    node_rows = conn.execute(
        """SELECT n.node_id, n.assessment_id, n.process_id, n.description, n.deviation, n.cause
           FROM node n
           JOIN process p ON p.process_id=n.process_id
           WHERE p.site_id=?
           ORDER BY n.node_id""",
        (site_id,),
    ).fetchall()
    nodes = []
    eq_rank: dict[str, tuple[int, str]] = {}
    for n in node_rows:
        eids = [
            r["equipment_id"]
            for r in conn.execute(
                "SELECT equipment_id FROM node_equipment WHERE node_id=? ORDER BY equipment_id",
                (n["node_id"],),
            )
        ]
        cas_list = [
            r["cas"]
            for r in conn.execute(
                "SELECT cas FROM node_chemical WHERE node_id=? ORDER BY cas",
                (n["node_id"],),
            )
        ]
        consequences = []
        for c in conn.execute(
            "SELECT * FROM consequence WHERE node_id=? ORDER BY consequence_id",
            (n["node_id"],),
        ):
            rs = conn.execute(
                "SELECT * FROM risk_score WHERE consequence_id=?",
                (c["consequence_id"],),
            ).fetchone()
            sgs = [
                {
                    "safeguard_id": s["safeguard_id"],
                    "equipment_id": s["equipment_id"],
                    "scenario_id": s["scenario_id"],
                    "sop_id": s["sop_id"],
                }
                for s in conn.execute(
                    "SELECT * FROM safeguard WHERE consequence_id=?",
                    (c["consequence_id"],),
                )
            ]
            cons = {
                "consequence_id": c["consequence_id"],
                "description": c["description"],
                "disaster_type": c["disaster_type"],
                "area_code": c["area_code"],
                "risk_id": rs["risk_id"] if rs else None,
                "severity": rs["severity"] if rs else None,
                "likelihood": rs["likelihood"] if rs else None,
                "rank_label": rs["rank_label"] if rs else None,
                "rank_value": rs["rank_value"] if rs else None,
                "stale": bool(rs["stale"]) if rs else False,
                "safeguards": sgs,
            }
            consequences.append(cons)
            if rs:
                for eid in eids:
                    prev = eq_rank.get(eid)
                    if prev is None or rs["rank_value"] > prev[0]:
                        eq_rank[eid] = (rs["rank_value"], rs["rank_label"])
        nodes.append(
            {
                "node_id": n["node_id"],
                "assessment_id": n["assessment_id"],
                "process_id": n["process_id"],
                "description": n["description"],
                "deviation": n["deviation"],
                "cause": n["cause"],
                "equipment_ids": eids,
                "cas_list": cas_list,
                "consequences": consequences,
            }
        )

    equipment = []
    for e in svc.equipment_list_joined(conn, site_id):
        loc = LAYOUT.get(e["equipment_id"])
        if not loc:
            i = len(equipment)
            loc = {"x": 90 + (i % 6) * 90, "y": 140 + (i // 6) * 80, "kind": "other"}
        rv, rl = eq_rank.get(e["equipment_id"], (None, "無"))
        equipment.append(
            {
                **dict(e),
                "x": loc["x"],
                "y": loc["y"],
                "kind": loc["kind"],
                "max_rank_value": rv,
                "max_rank_label": rl or "無",
            }
        )

    chemicals = [
        dict(r)
        for r in conn.execute(
            """SELECT c.cas, c.process_id, c.name, c.role
               FROM chemical c JOIN process p ON p.process_id=c.process_id
               WHERE p.site_id=? ORDER BY c.process_id, c.cas""",
            (site_id,),
        )
    ]
    occupancy = [
        dict(r)
        for r in conn.execute(
            """SELECT occupancy_id, equipment_id, process_id, cas, plate_or_container, start_ts, end_ts
               FROM loading_occupancy ORDER BY occupancy_id"""
        )
    ]
    coverage = {}
    esd = {}
    for p in processes:
        coverage[p["process_id"]] = [
            g["equipment_id"] for g in svc.coverage_gaps(conn, p["process_id"])
        ]
        esd[p["process_id"]] = svc.esd_status(conn, p["process_id"])

    return {
        "site": dict(site) if site else None,
        "masters_ok": ok,
        "masters_reasons": reasons,
        "matrix_version": MATRIX_VERSION,
        "accept_line": MATRIX_ACCEPT_LINE,
        "deviations": list(DEVIATIONS),
        "processes": processes,
        "areas": areas,
        "equipment": equipment,
        "chemicals": chemicals,
        "nodes": nodes,
        "occupancy": occupancy,
        "coverage": coverage,
        "esd": esd,
    }


def score_consequence(
    conn: sqlite3.Connection, consequence_id: str, severity: int, likelihood: int
) -> dict:
    if not 1 <= int(severity) <= 5 or not 1 <= int(likelihood) <= 5:
        raise PsmError("嚴重度與可能性須為 1–5")
    row = conn.execute(
        """SELECT p.site_id FROM consequence c
           JOIN node n ON n.node_id=c.node_id
           JOIN process p ON p.process_id=n.process_id
           WHERE c.consequence_id=?""",
        (consequence_id,),
    ).fetchone()
    if not row:
        raise PsmError("後果不存在")
    existing = conn.execute(
        "SELECT risk_id FROM risk_score WHERE consequence_id=?", (consequence_id,)
    ).fetchone()
    risk_id = existing["risk_id"] if existing else f"R-{consequence_id}"
    svc.save_risk_score(
        conn,
        {
            "risk_id": risk_id,
            "consequence_id": consequence_id,
            "matrix_version": MATRIX_VERSION,
            "severity": int(severity),
            "likelihood": int(likelihood),
        },
    )
    return floor_bundle(conn, row["site_id"])


def create_node_from_equipment(
    conn: sqlite3.Connection,
    equipment_id: str,
    deviation: str,
    process_filter: str | None = None,
) -> dict:
    if deviation not in DEVIATIONS:
        raise PsmError("偏離只能點晶片，不能手打")
    eq = conn.execute(
        "SELECT * FROM equipment WHERE equipment_id=?", (equipment_id,)
    ).fetchone()
    if not eq:
        raise PsmError("設備不存在")
    process_id = eq["process_id"]
    if process_filter and process_filter != process_id:
        raise PsmError("選製程後只能操作該製程下的設備")
    assessment_id = svc.assessment_id_for_process(conn, process_id)
    if not assessment_id:
        raise PsmError("此製程尚無評估")
    drawings = svc.hazop_usable_drawings(conn, process_id)
    dno = drev = ""
    if drawings:
        dno, drev = drawings[0]["drawing_no"], drawings[0]["revision"]
    chems = svc.chemical_choices(conn, process_id)
    cas_list = list(dict.fromkeys(c["cas"] for c in chems))
    node_id = _next_id(conn, "node", "node_id", "N-")
    svc.save_node(
        conn,
        {
            "node_id": node_id,
            "assessment_id": assessment_id,
            "process_id": process_id,
            "description": f"{equipment_id} {deviation}",
            "deviation": deviation,
            "cause": "現場點選",
            "drawing_no": dno,
            "drawing_revision": drev,
            "considers_location": True,
            "considers_human": True,
            "considers_control_failure": True,
        },
        equipment_ids=[equipment_id],
        cas_list=cas_list,
    )
    cons_id = f"C-{node_id}-1"
    svc.save_consequence(
        conn,
        {
            "consequence_id": cons_id,
            "node_id": node_id,
            "description": f"偏離「{deviation}」於 {equipment_id}，控制失效後可能外洩或火災",
            "disaster_type": "外洩",
            "area_code": eq["area_code"],
        },
    )
    bundle = floor_bundle(conn, eq["site_id"])
    bundle["created_node_id"] = node_id
    bundle["created_consequence_id"] = cons_id
    return bundle
