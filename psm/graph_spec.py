"""V8.3 手冊實體層的型別圖（規劃圖，不是 demo sqlite）。"""

from __future__ import annotations

# 頂點：手冊實體層。視圖層（chem_usage 等帶出欄）不算第二份頂點。
HANDBOOK_VERTICES = {
    "site": "dimension",
    "department": "access",
    "process": "time",
    "equipment": "space",
    "sds": "matter",
    "chemical_component": "matter",
    "chemical_cite": "matter",
    "area": "space",
    "area_process": "interaction",
    "area_equipment": "interaction",
    "area_chemical": "interaction",
    "attachment": "dimension",
    "equipment_limit": "time",
    "equipment_content": "interaction",
    "pid_drawing": "space",
    "pid_covering": "space",
    "pec_map": "interaction",
    "inventory": "measure",
    "incident": "time",
    "contractor_incident": "time",
    "hotwork_zone": "space",
    "process_route": "time",
    "process_route_block": "interaction",
    "interlock": "interaction",
    "assessment": "time",
    "mi_screen": "measure",
    "mi_failure": "measure",
}

# 有向邊：from 依賴 to（FK 方向）。
# 濃度敏感列連 chemical_component（製程＋SDS＋CAS）。
# 1.1 存量連 chemical_cite（CAS＋製程，歸屬量可加總）。
# 2.2 不掛製程；1.10 選設備；6.2 連 11.2；8.2 只接 8.1。
HANDBOOK_EDGES = [
    ("department", "site"),
    ("process", "site"),
    ("process", "department"),
    ("equipment", "process"),
    ("equipment", "department"),
    ("sds", "site"),
    ("chemical_component", "process"),
    ("chemical_component", "sds"),
    ("chemical_component", "chemical_cite"),
    ("chemical_cite", "process"),
    ("area", "site"),
    ("area_process", "area"),
    ("area_process", "process"),
    ("area_equipment", "area"),
    ("area_equipment", "equipment"),
    ("area_chemical", "area"),
    ("area_chemical", "chemical_component"),
    ("attachment", "site"),
    ("equipment_limit", "equipment"),
    ("equipment_content", "equipment"),
    ("equipment_content", "chemical_component"),
    ("pid_drawing", "process"),
    ("pid_covering", "pid_drawing"),
    ("pid_covering", "equipment"),
    ("pec_map", "process"),
    ("pec_map", "equipment"),
    ("pec_map", "chemical_component"),
    ("inventory", "chemical_cite"),
    ("contractor_incident", "site"),
    ("contractor_incident", "incident"),
    ("hotwork_zone", "area"),
    ("process_route", "site"),
    ("process_route_block", "process_route"),
    ("process_route_block", "process"),
    ("interlock", "equipment"),
    ("mi_screen", "equipment"),
    ("mi_failure", "mi_screen"),
]

# 禁止的邊：會讓「同一事實兩份頂點」或把視圖當主檔。
FORBIDDEN = [
    ("chemical_component", "sds_file_attr"),
    ("equipment", "area_as_required_fk"),
    ("pec_map", "chemical_cite"),
    ("area_chemical", "chemical_cite"),
    ("contractor_incident", "process"),
    ("interlock", "process"),
    ("area", "process"),
    ("assessment", "process"),
]


def handbook_graph_audit() -> dict:
    verts = set(HANDBOOK_VERTICES)
    edges = list(HANDBOOK_EDGES)
    fail: list[str] = []
    warn: list[str] = []

    for a, b in edges:
        if a not in verts:
            fail.append(f"邊 {a}->{b} 的起點不在頂點集")
        if b not in verts:
            fail.append(f"邊 {a}->{b} 的終點不在頂點集")
    for a, b in FORBIDDEN:
        if (a, b) in edges:
            fail.append(f"禁止的邊 {a}->{b}")

    if "sds" not in verts:
        fail.append("缺 SDS 頂點")
    if ("chemical_component", "sds") not in edges:
        fail.append("化學品列必須連 SDS 頂點")

    if "chemical_cite" not in verts:
        fail.append("缺 chemical_cite（CAS＋製程合併頂點）")
    if ("inventory", "chemical_cite") not in edges:
        fail.append("1.1 存量必須連 cite，歸屬量才可加總")
    if ("pec_map", "chemical_component") not in edges:
        fail.append("對應表必須連化學品列，保留 SDS")
    if ("equipment_content", "chemical_component") not in edges:
        fail.append("設備內容物必須連化學品列")
    if ("area_chemical", "chemical_component") not in edges:
        fail.append("區域化學品必須連化學品列")
    if ("contractor_incident", "incident") not in edges:
        fail.append("承攬列必須連 11.2 事故，不得自存另一份")
    if ("interlock", "equipment") not in edges:
        fail.append("連鎖必須連設備；製程由設備帶出")
    if ("mi_screen", "equipment") not in edges:
        fail.append("8.1 必須從設備清單篩選")
    if ("mi_failure", "mi_screen") not in edges:
        fail.append("8.2 只接 8.1 已篩列")
    if ("assessment", "process") in edges:
        fail.append("2.2 不得必掛製程")

    if ("area_equipment", "equipment") not in edges:
        fail.append("缺 area_equipment")
    if ("equipment", "area") in edges:
        warn.append("設備→區域若當成唯一所在，基數變成 N:1；所在應走 area_equipment")

    succ: dict[str, set[str]] = {v: set() for v in verts}
    pred: dict[str, set[str]] = {v: set() for v in verts}
    for a, b in edges:
        if a in verts and b in verts:
            succ[a].add(b)
            pred[b].add(a)
    und: dict[str, set[str]] = {v: set() for v in verts}
    for a, b in edges:
        if a in verts and b in verts:
            und[a].add(b)
            und[b].add(a)
    seen = set()
    stack = ["site"]
    while stack:
        x = stack.pop()
        if x in seen:
            continue
        seen.add(x)
        stack.extend(und[x] - seen)
    core = {"process", "equipment", "chemical_component", "sds", "area"}
    missing_core = core - seen
    if missing_core:
        fail.append(f"從場所走不到：{sorted(missing_core)}")

    loops = [a for a, b in edges if a == b]
    if loops:
        fail.append(f"核心圖不應有自環：{loops}")

    pec_targets = {b for a, b in edges if a == "pec_map"}
    if not {"process", "equipment", "chemical_component"} <= pec_targets:
        fail.append(f"pec_map 須同時接到製程、設備、化學品列，實得 {pec_targets}")

    return {
        "vertices": sorted(verts),
        "edges": edges,
        "fail": fail,
        "warn": warn,
        "reachable_from_site": sorted(seen),
    }
