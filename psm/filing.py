"""十四項申報列與是／否欄。不是第四張核心資料表。"""

from __future__ import annotations

import json
import re
import sqlite3

H_RE = re.compile(r"H\d{3}[A-Z]?", re.I)
HIGH_FLAMMABLE = {"H220", "H221", "H222", "H223"}
HIGH_TOXIC = {"H300", "H301", "H310", "H311", "H330", "H331"}
INCOMPAT = {"H260", "H261"}

PHA_METHODS = (
    ("checklist", "檢核表分析", "問題項目數量"),
    ("whatif", "如果－結果分析", "問題項目數量"),
    ("whatif_check", "如果－結果／檢核表分析", "問題項目數量"),
    ("hazop", "危害及可操作性分析（HAZOP）", "節點數量"),
    ("fmea", "失誤模式與影響分析（FMEA）", "設備元件數量"),
    ("fta", "故障樹分析（FTA）", "頂端事件數量"),
    ("other", "其他經中央主管機關認可之方法", "說明及數量"),
)

LABOR_ITEMS = (
    "製程安全資訊",
    "製程危害控制措施",
    "標準作業程序",
    "教育訓練",
    "事故調查",
    "承攬管理",
    "動火許可",
    "變更管理",
    "啟動前安全檢查",
    "機械完整性",
    "緊急應變",
    "符合性稽核",
    "商業機密",
)

# 手冊表3.1-1 範例；人員可改。who 可為部門編號或文字（如「所有勞工」）。
LABOR_HINTS = {
    "製程安全資訊": ("反映與實際運作不一致之書面資訊", "所有勞工", ""),
    "製程危害控制措施": ("參與製程安全評估研討分析", "製造、維護、研發等部門勞工", "研討分析會議紀錄"),
    "標準作業程序": ("參與標準作業程序之檢討修正", "製造部門勞工", ""),
    "教育訓練": ("提供在職訓練頻率及課程規劃等建議", "製造部門人員", ""),
    "事故調查": ("參與事故調查", "事故部門勞工及其代表", "事故調查報告"),
    "承攬管理": ("提報不安全行為及狀況", "所有勞工", "虛驚事故／事件提報單、承攬人違規單"),
    "動火許可": ("提報不安全行為及狀況", "所有勞工", "虛驚事故／事件提報單、承攬人違規單"),
    "變更管理": ("反應未符合規定之變更", "所有勞工", "改善提案表"),
    "啟動前安全檢查": ("新建／變更活動參與", "變更與新建相關部門", ""),
    "機械完整性": ("參與設備檢查與測試、設備失效檢討及改進建議", "維護部門", "改善提案表"),
    "緊急應變": ("就演習及實際事故之應變計畫進行意見回饋", "所有勞工", "緊急應變演練檢討紀錄"),
    "符合性稽核": ("提供規劃稽核計畫及矯正措施等意見", "所有勞工", ""),
    "商業機密": ("取得製程危害分析相關資料，了解製程潛在危害", "所有勞工", "勞工保密協議"),
}

MI_SIX = (
    "壓力容器與儲槽",
    "管線(包括管線組件如閥)",
    "釋放及排放系統和設備",
    "緊急停車系統",
    "控制系統（包括監測設備、感應器，警報及連鎖系統）",
    "泵浦(轉動設備)",
)

REACTION_TYPES = (
    "氧化",
    "硝化",
    "鹵化",
    "有機金屬化",
    "偶氮化",
    "氫化",
    "裂解／熱分解",
    "聚合",
    "磺化",
    "縮合",
    "其他",
)

DAMAGE_MECHS = (
    "腐蝕",
    "沖蝕",
    "疲勞",
    "裂化",
    "過熱",
    "機械損傷",
    "應力腐蝕",
    "其他",
)

INSPECT_METHODS = (
    "目視檢查",
    "超音波測厚",
    "非破壞檢測",
    "功能測試",
    "洩漏測試",
    "試壓",
    "其他",
)

VENT_TYPES = (("N", "N 自然"), ("A", "A 人工"))
VENT_LEVELS = (("VH", "VH 高度"), ("VM", "VM 中度"), ("VL", "VL 低度"))
VENT_AVAIL = (("A", "A 良好"), ("B", "B 中等"), ("C", "C 差"))
LEAK_LEVELS = (("C", "C 連續"), ("P", "P 主要"), ("S", "S 次要"))
ZONE_LEVELS = (("0", "0 區"), ("1", "1 區"), ("2", "2 區"))
RATIO_BASES = ("重量比", "體積比", "重量／體積比")
PHASES = ("固態", "液態", "氣態")

# 勞動檢查法施行細則（FL015074）第 29 條：危險物／有害物規定數量（公斤）。
# 列：annex, 中文, 英文, 化學式, CAS, 規定數量kg
_ANNEX_ROWS = (
    ("危險物", "過氧化丁酮", "Methyl ethyl ketone peroxide", "C8H16O4", "1338-23-4", 2000),
    ("危險物", "過氧化二苯甲醯", "Dibenzoyl peroxide", "C14H10O4", "94-36-0", 3000),
    ("危險物", "環氧丙烷", "Propylene oxide", "C3H6O", "75-56-9", 10000),
    ("危險物", "環氧乙烷", "Ethylene oxide", "C2H4O", "75-21-8", 5000),
    ("危險物", "二硫化碳", "Carbon disulphide", "CS2", "75-15-0", 5000),
    ("危險物", "乙炔", "Acetylene", "C2H2", "74-86-2", 5000),
    ("危險物", "氫氣", "Hydrogen", "H2", "1333-74-0", 5000),
    ("危險物", "過氧化氫", "Hydrogen peroxide", "H2O2", "7722-84-1", 5000),
    ("危險物", "矽甲烷", "Silane", "SiH4", "7803-62-5", 50),
    ("危險物", "硝化乙二醇", "Nitroglycol", "C2H4(NO3)2", "628-96-6", 1000),
    ("危險物", "硝化甘油", "Nitroglycerin", "C3H5(NO3)3", "55-63-0", 1000),
    ("危險物", "硝化纖維", "Nitrocellulose", "C6H7O2(NO3)3", "9004-70-0", 10000),
    ("危險物", "三硝基苯", "Trinitrobenzene", "C6H3(NO2)3", "99-35-4", 5000),
    ("危險物", "三硝基甲苯", "Trinitrotoluene", "C6H2CH3(NO2)3", "118-96-7", 5000),
    ("危險物", "三硝基酚", "Trinitrophenol", "C6H2OH(NO2)3", "88-89-1", 5000),
    ("危險物", "過醋酸", "Peracetic acid", "CH3COOOH", "79-21-0", 5000),
    ("危險物", "氯酸鈉", "Sodium chlorate", "NaClO3", "7775-09-9", 25000),
    ("危險物", "雷汞", "Mercury fulminate", "Hg(CNO)2", "628-86-4", 1000),
    ("危險物", "疊氮化鉛", "Lead azide", "Pb(N3)2", "13424-46-9", 5000),
    ("危險物", "史蒂芬酸鉛", "Lead styphnate", "", "15245-44-0", 5000),
    ("危險物", "丙烯腈", "Acrylonitrile", "C3H3N", "107-13-1", 20000),
    ("危險物", "重氮硝基酚", "Diazodinitrophenol", "", "4682-03-5", 1000),
    ("有害物", "黃磷火柴", "Yellow phosphorus match", "", "", 1),
    ("有害物", "含苯膠糊", "Glue that contains benzene", "", "", 1),
    ("有害物", "二氯聯苯胺及其鹽類", "Dichlorobenzidine and its salts", "C12H10Cl2N2", "91-94-1", 10),
    ("有害物", "α–萘胺及其鹽類", "α-Naphthylamine and its salts", "C10H9N", "134-32-7", 10),
    ("有害物", "鄰–二甲基聯苯胺及其鹽類", "O-Tolidine and its salts", "C14H16N2", "119-93-7", 10),
    ("有害物", "二甲氧基聯苯胺及其鹽類", "Dianisidine and its salts", "C14H16N2O2", "119-90-4", 10),
    ("有害物", "鈹及其化合物", "Beryllium and its compounds", "Be", "7440-41-7", 10),
    ("有害物", "四羰化鎳", "Nickel carbonyl", "C4O4Ni", "13463-39-3", 100),
    ("有害物", "β-丙內酯", "β-Propiolactone", "C3H4O2", "57-57-8", 100),
    ("有害物", "氯", "Chlorine", "Cl2", "7782-50-5", 5000),
    ("有害物", "氰化氫", "Hydrogen cyanide", "HCN", "74-90-8", 1000),
    ("有害物", "次乙亞胺", "Ethyleneimine", "C2H5N", "151-56-4", 500),
    ("有害物", "磷化氫", "Phosphine", "PH3", "7803-51-2", 50),
    ("有害物", "異氰酸甲酯", "Methyl isocyanate", "C2H3NO", "624-83-9", 300),
    ("有害物", "氟化氫", "Hydrogen fluoride", "HF", "7664-39-3", 1000),
    ("有害物", "四甲基鉛", "Tetramethyl lead", "Pb(CH3)4", "75-74-1", 1000),
    ("有害物", "四乙基鉛", "Tetraethyl lead", "Pb(C2H5)4", "78-00-2", 5000),
    ("有害物", "氨", "Ammonia", "NH3", "7664-41-7", 50000),
    ("有害物", "氯化氫", "Hydrogen chloride", "HCl", "7647-01-0", 5000),
    ("有害物", "二氧化硫", "Sulfur dioxide", "SO2", "7446-09-5", 1000),
    ("有害物", "光氣", "Phosgene", "COCl2", "75-44-5", 100),
    ("有害物", "甲醛", "Formaldehyde", "CH2O", "50-00-0", 5000),
    ("有害物", "丙烯醛", "Acrolein", "C3H4O", "107-02-8", 150),
    ("有害物", "臭氧", "Ozone", "O3", "10028-15-6", 100),
    ("有害物", "砷化氫", "Arsine", "AsH3", "7784-42-1", 50),
    ("有害物", "溴", "Bromine", "Br2", "7726-95-6", 1000),
    ("有害物", "溴甲烷", "Methyl bromide", "CH3Br", "74-83-9", 2000),
)
_ANNEX_BY_CAS = {
    r[4]: {
        "annex": r[0],
        "name_zh": r[1],
        "name_en": r[2],
        "formula": r[3],
        "cas": r[4],
        "limit_kg": r[5],
    }
    for r in _ANNEX_ROWS
    if r[4]
}
# 表列中文「丙烯」實為丙烯腈（Acrylonitrile）
_ANNEX_BY_CAS["107-13-1"]["aliases"] = ("丙烯",)
# 附表管制量相態（固態／液態／氣態）。phase_gate 為真時，常用狀況相態不符者不列入管制量。
# 氯化氫、氟化氫依勞動部解釋以氣態為規範對象；其餘為對照用，不另排除。
_LIMIT_PHASE = {
    "1338-23-4": "液態",
    "94-36-0": "固態",
    "75-56-9": "液態",
    "75-21-8": "氣態",
    "75-15-0": "液態",
    "74-86-2": "氣態",
    "1333-74-0": "氣態",
    "7722-84-1": "液態",
    "7803-62-5": "氣態",
    "628-96-6": "液態",
    "55-63-0": "液態",
    "9004-70-0": "固態",
    "99-35-4": "固態",
    "118-96-7": "固態",
    "88-89-1": "固態",
    "79-21-0": "液態",
    "7775-09-9": "固態",
    "628-86-4": "固態",
    "13424-46-9": "固態",
    "15245-44-0": "固態",
    "107-13-1": "液態",
    "4682-03-5": "固態",
    "91-94-1": "固態",
    "134-32-7": "固態",
    "119-93-7": "固態",
    "119-90-4": "固態",
    "7440-41-7": "固態",
    "13463-39-3": "液態",
    "57-57-8": "液態",
    "7782-50-5": "氣態",
    "74-90-8": "氣態",
    "151-56-4": "液態",
    "7803-51-2": "氣態",
    "624-83-9": "液態",
    "7664-39-3": "氣態",
    "75-74-1": "液態",
    "78-00-2": "液態",
    "7664-41-7": "氣態",
    "7647-01-0": "氣態",
    "7446-09-5": "氣態",
    "75-44-5": "氣態",
    "50-00-0": "氣態",
    "107-02-8": "液態",
    "10028-15-6": "氣態",
    "7784-42-1": "氣態",
    "7726-95-6": "液態",
    "74-83-9": "氣態",
}
_PHASE_GATE = frozenset({"7647-01-0", "7664-39-3"})
for _cas, _rec in _ANNEX_BY_CAS.items():
    _rec["limit_phase"] = _LIMIT_PHASE.get(_cas, "")
    _rec["phase_gate"] = _cas in _PHASE_GATE
# 氯化氫、氟化氫：氣態才列入；水溶液之鹽酸、氫氟酸不列入
AQUEOUS_EXCLUDED_CAS = frozenset({"7647-01-0", "7664-39-3"})
NITROCELLULOSE_CAS = "9004-70-0"

# 特化／優先管理參考，不是第四張核心表，不據以判斷 MI 或缺漏。
SPECIAL_CHEM_REF = {
    "7647-01-0": {
        "name": "氯化氫（水溶液）",
        "special": "視濃度",
        "priority": "視公告",
        "h_codes": "H314、H335",
        "pel": "依公告",
        "phys": "不燃",
        "incompat": "鹼、氧化劑、多數金屬",
        "unsuitable": "碳鋼、鍍鋅",
        "ppe": "C／B 級（依濃度）",
        "cartridge": "酸性氣體",
    },
    "108-88-3": {
        "name": "甲苯",
        "special": "否（依公告確認）",
        "priority": "視公告",
        "h_codes": "H225、H304、H315、H336、H361、H373",
        "pel": "TWA 100 ppm（參考；以場所 SDS／公告為準）",
        "phys": "閃火點約 4 ℃、沸點約 110.6 ℃、爆炸界限約 1.1–7.1%",
        "incompat": "強氧化劑",
        "unsuitable": "依 SDS 確認",
        "ppe": "依 SDS",
        "cartridge": "有機蒸氣",
    },
    "7722-84-1": {
        "name": "過氧化氫",
        "special": "視濃度",
        "priority": "視公告",
        "h_codes": "H272、H314",
        "pel": "TWA 1 ppm（參考）",
        "phys": "強氧化性液體",
        "incompat": "有機物、金屬、還原劑",
        "unsuitable": "碳鋼、銅及其合金",
        "ppe": "依 SDS",
        "cartridge": "依 SDS",
    },
}

YN6 = (
    ("c_perf", "考慮安全衛生管理績效"),
    ("c_env", "告知工作環境與應採取措施"),
    ("c_er", "告知緊急應變規定"),
    ("c_std", "已訂工作安全衛生標準"),
    ("c_train", "定期評核教育訓練"),
    ("c_rec", "保存承攬職災紀錄"),
)

YN9 = (
    ("h_fire", "火災預防及保護措施"),
    ("h_date", "核可動火作業日期"),
    ("h_target", "動火作業對象"),
    ("h_period", "動火作業期間"),
)

YN11 = (
    ("i_near", "制度是否包含虛驚事故"),
    ("i_proc", "制度是否包含製程事件"),
    ("i_sop", "已訂意外事故調查標準作業程序"),
    ("i_keep", "調查報告應包含法定項目並保存五年以上"),
    ("i_corr", "已建立迅速處理報告結果與建議之系統"),
    ("i_review", "調查報告應與相關作業人員檢討"),
)

YN11_HELP = {
    "i_near": "是／否",
    "i_proc": "是／否",
    "i_sop": "實施意外事故及虛驚事故調查，並成立調查小組；至少一位成員熟知發生事故之製程。涉及承攬作業者，小組成員應包括一位承攬人勞工",
    "i_keep": "至少包含：事故發生日期、調查開始日期、事故發生經過、事故發生原因、依調查結果研擬之改善建議",
    "i_corr": "解決及矯正措施須予以記錄",
    "i_review": "包含承攬人勞工",
}

YN12 = (
    ("e_org_struct", "1.1 緊急應變組織架構及權責"),
    ("e_ctrl_center", "1.2 緊急應變控制中心位置及設施"),
    ("e_flow", "1.3 緊急應變運作流程及說明"),
    ("e_cmd", "2 應變協調指揮者及其責任"),
    ("e_evac", "3 緊急疏散程序及疏散路徑"),
    ("e_pre", "4 疏散前必須遵守之程序"),
    ("e_muster", "5 完全疏散後再集合清點"),
    ("e_med", "6 搶救與醫療責任"),
    ("e_notify", "7 火災及其他緊急事件之通報"),
    ("e_ctrl", "8 各項危害物質之控制程序"),
    ("e_aid", "9 急救處理及搜救計畫"),
    ("e_gear", "10 緊急應變設備置備與外援聯繫"),
    ("e_recov", "11 災後復原（清空及再進入）"),
    ("e_drill", "12 演練計畫與演練紀錄"),
    ("e_rev", "13 緊急應變計畫之修正"),
)

YN14 = (
    ("t_info", "提供必要資訊供相關人員作業"),
    ("t_nda", "得要求遵守保密協議"),
    ("t_rep", "勞工代表可獲知但得要求保密"),
)

PHYS_OPTS = ("易燃氣體或氣溶膠", "易燃液體", "腐蝕金屬", "與空氣或水不相容", "其他物理性危害")
HEALTH_OPTS = ("急性毒性", "腐蝕／嚴重損傷", "特定標的器官毒性", "其他健康危害")


def parse_h_codes(text: str) -> set[str]:
    return {m.group(0).upper() for m in H_RE.finditer(text or "")}


def h_code_flags(text: str) -> dict:
    codes = parse_h_codes(text)
    phys = {c for c in codes if c.startswith("H2")}
    health = {c for c in codes if c.startswith("H3")}
    env = {c for c in codes if c.startswith("H4")}
    physical_label = ""
    if codes & {"H220", "H221", "H222", "H223"}:
        physical_label = "易燃氣體或氣溶膠"
    elif codes & {"H224", "H225", "H226"}:
        physical_label = "易燃液體"
    elif codes & {"H290"}:
        physical_label = "腐蝕金屬"
    elif codes & INCOMPAT:
        physical_label = "與空氣或水不相容"
    elif phys:
        physical_label = "其他物理性危害"
    health_label = ""
    if codes & HIGH_TOXIC:
        health_label = "急性毒性"
    elif codes & {"H314", "H318"}:
        health_label = "腐蝕／嚴重損傷"
    elif health:
        health_label = "其他健康危害"
    return {
        "is_danger": bool(phys),
        "is_harmful": bool(health or env),
        "is_high_flammable": bool(codes & HIGH_FLAMMABLE),
        "is_high_toxic": bool(codes & HIGH_TOXIC),
        "incompat_air_water": bool(codes & INCOMPAT),
        "physical_label": physical_label,
        "health_label": health_label,
    }


def mi_type_suggest(equipment_type: str, power_kind: str | None = None) -> str:
    if equipment_type == "動力來源" and (power_kind or "") == "泵浦":
        return "泵浦(轉動設備)"
    if equipment_type == "管線系統":
        return "管線(包括管線組件如閥)"
    if equipment_type == "釋放及排放系統":
        return "釋放及排放系統和設備"
    if equipment_type == "控制系統":
        return "控制系統（包括監測設備、感應器，警報及連鎖系統）"
    if equipment_type in ("壓力容器與儲槽", "緊急停車系統"):
        return equipment_type
    return ""


def get_flag(conn: sqlite3.Connection, site_id: str, k: str) -> str:
    row = conn.execute(
        "SELECT v FROM filing_flag WHERE site_id=? AND k=?", (site_id, k)
    ).fetchone()
    return (row["v"] if row else "") or ""


def set_flag(conn: sqlite3.Connection, site_id: str, k: str, v: str) -> None:
    conn.execute(
        """INSERT INTO filing_flag(site_id, k, v) VALUES (?,?,?)
           ON CONFLICT(site_id, k) DO UPDATE SET v=excluded.v""",
        (site_id, k, v or ""),
    )
    conn.commit()


def all_flags(conn: sqlite3.Connection, site_id: str) -> dict[str, str]:
    return {
        r["k"]: r["v"]
        for r in conn.execute("SELECT k, v FROM filing_flag WHERE site_id=?", (site_id,))
    }


def list_rows(conn: sqlite3.Connection, site_id: str, section: str) -> list[dict]:
    out = []
    for r in conn.execute(
        "SELECT row_id, payload FROM filing_row WHERE site_id=? AND section=? ORDER BY row_id",
        (site_id, section),
    ):
        try:
            payload = json.loads(r["payload"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        item = dict(payload)
        item["row_id"] = r["row_id"]
        out.append(item)
    return out


def legal_equipment(conn: sqlite3.Connection, site_id: str) -> list[dict]:
    """Table 1.11 cites the equipment flagged in table 1.0-3."""
    out = []
    for row in conn.execute(
        """SELECT * FROM equipment WHERE site_id=?
           AND (is_regulated_machinery=1 OR is_high_pressure_gas=1)
           ORDER BY equipment_id""", (site_id,),
    ):
        item = dict(row)
        categories = []
        if item["is_regulated_machinery"]:
            categories.append("危險性機械或設備")
        if item["is_high_pressure_gas"]:
            categories.append("高壓氣體特定設備或容器")
        item["legal_category"] = "／".join(categories)
        out.append(item)
    return out


def rows_by_section(conn: sqlite3.Connection, site_id: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in conn.execute(
        "SELECT row_id, section, payload FROM filing_row WHERE site_id=? ORDER BY row_id",
        (site_id,),
    ):
        try:
            payload = json.loads(r["payload"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        item = dict(payload)
        item["row_id"] = r["row_id"]
        out.setdefault(r["section"], []).append(item)
    return out


def update_payload(conn: sqlite3.Connection, row_id: int, payload: dict) -> None:
    body = {k: v for k, v in payload.items() if k != "row_id"}
    conn.execute(
        "UPDATE filing_row SET payload=? WHERE row_id=?",
        (json.dumps(body, ensure_ascii=False), row_id),
    )
    conn.commit()


def add_row(conn: sqlite3.Connection, site_id: str, section: str, payload: dict) -> int:
    cur = conn.execute(
        "INSERT INTO filing_row(site_id, section, payload) VALUES (?,?,?)",
        (site_id, section, json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()
    return int(cur.lastrowid)


def has_row_matching(conn: sqlite3.Connection, site_id: str, section: str, key: str, value) -> bool:
    for row in list_rows(conn, site_id, section):
        if str(row.get(key) or "") == str(value or ""):
            return True
    return False


def delete_row(conn: sqlite3.Connection, site_id: str, row_id: int) -> None:
    conn.execute(
        "DELETE FROM filing_row WHERE site_id=? AND row_id=?", (site_id, row_id)
    )
    conn.commit()


def replace_section(conn: sqlite3.Connection, site_id: str, section: str, payloads: list[dict]) -> None:
    conn.execute(
        "DELETE FROM filing_row WHERE site_id=? AND section=?", (site_id, section)
    )
    for payload in payloads:
        conn.execute(
            "INSERT INTO filing_row(site_id, section, payload) VALUES (?,?,?)",
            (site_id, section, json.dumps(payload, ensure_ascii=False)),
        )
    conn.commit()


def replace_section_for_key(
    conn: sqlite3.Connection,
    site_id: str,
    section: str,
    payloads: list[dict],
    key: str,
    value: str,
) -> None:
    """Overwrite rows whose payload[key]==value; keep the rest of the section."""
    kept = []
    for row in list_rows(conn, site_id, section):
        if str(row.get(key) or "") in ("", str(value)):
            continue
        item = dict(row)
        item.pop("row_id", None)
        kept.append(item)
    replace_section(conn, site_id, section, kept + payloads)


def labor_grid(conn: sqlite3.Connection, site_id: str) -> list[dict]:
    saved = {r.get("item"): r for r in list_rows(conn, site_id, "3.1")}
    out = []
    for i, item in enumerate(LABOR_ITEMS):
        if item not in saved:
            continue
        hint = LABOR_HINTS.get(item, ("", "", ""))
        row = saved[item]
        out.append(
            {
                "i": i,
                "row_id": row.get("row_id"),
                "item": item,
                "how": row.get("how") or "",
                "who": row.get("who") or "",
                "note": row.get("note") or "",
                "how_hint": hint[0],
                "who_hint": hint[1],
                "note_hint": hint[2],
            }
        )
    return out


def mi_fail_grid(conn: sqlite3.Connection, site_id: str) -> list[dict]:
    return [
        {
            "equipment_id": r["equipment_id"],
            "equipment_name": r["name"],
            "equipment_type": r["equipment_type"],
            "mi_type": r["mi_type"],
            "period_start": r["period_start"],
            "period_end": r["period_end"],
            "hours": r["run_hours"],
            "repair": r["failure_count"],
            "rate": f"{r['failure_count'] / r['run_hours'] * 1000000:.4g} 次/百萬小時" if r["run_hours"] > 0 else "",
            "note": r["note"],
            "confirmed": r["confirmed"],
        }
        for r in conn.execute(
            """SELECT f.*,e.name,e.equipment_type,s.mi_type FROM mi_failure f
               JOIN equipment e ON e.equipment_id=f.equipment_id
               JOIN mi_screen s ON s.equipment_id=f.equipment_id
               WHERE e.site_id=? AND s.is_critical=1 ORDER BY f.equipment_id""", (site_id,)
        )
    ]


def chem_104_rows(chemicals: list[dict], mix_rows: list[dict]) -> list[dict]:
    """表1.0-4：混合物列優先；無混合物列之化學品以純物質列出。"""
    covered: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    by_key = {(c.get("cas"), c.get("process_id")): c for c in chemicals}
    by_exact = {
        (c.get("cas"), c.get("process_id"), c.get("sds_id")): c
        for c in chemicals
    }
    for m in mix_rows:
        cas, pid = m.get("cas"), m.get("process_id")
        chem = by_exact.get((cas, pid, m.get("sds_id"))) or by_key.get((cas, pid)) or {}
        out.append(
            {
                **m,
                "kind": "混合物",
                "mix_sds_id": m.get("sds_id") or "",
                "name": chem.get("name") or m.get("name") or "",
                "role": chem.get("role") or "",
                "h_codes": chem.get("h_codes") or m.get("h_codes") or "",
                "sds_file": chem.get("sds_file") or chem.get("sds_path") or "",
                "sds_id": chem.get("sds_id") or m.get("sds_id") or "",
                "phase_state": m.get("phase_state") or chem.get("phase_state") or "",
            }
        )
        if cas and pid:
            covered.add((cas, pid, chem.get("sds_id") or m.get("sds_id") or ""))
    for c in chemicals:
        key = (c.get("cas"), c.get("process_id"), c.get("sds_id"))
        if key in covered:
            continue
        out.append(
            {
                "kind": "純物質",
                "cas": c.get("cas"),
                "process_id": c.get("process_id"),
                "name": c.get("name"),
                "role": c.get("role"),
                "h_codes": c.get("h_codes"),
                "sds_id": c.get("sds_id") or "",
                "mix_name": "",
                "pct_lo": "",
                "pct_hi": "",
                "basis": "",
                "total_kg": "",
                "qty": c.get("concentration_range") or "",
                "pure_kg": "",
                "sds_file": c.get("sds_file"),
                "phase_state": c.get("phase_state") or "",
                "row_id": None,
            }
        )
    return out


def group_chem_104(rows: list[dict]) -> list[dict]:
    """表1.0-4：混合物收成一組，成分放在巢狀列。"""
    groups: list[dict] = []
    index: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        if row.get("kind") != "混合物":
            groups.append({"kind": "純物質", "head": row, "components": [row]})
            continue
        key = (
            str(row.get("process_id") or ""),
            str(row.get("mix_name") or ""),
            str(row.get("mix_sds_id") or row.get("sds_id") or ""),
        )
        group = index.get(key)
        if group is None:
            group = {
                "kind": "混合物",
                "process_id": key[0],
                "mix_name": key[1],
                "sds_id": row.get("sds_id") or key[2],
                "total_kg": row.get("total_kg") or "",
                "basis": row.get("basis") or "",
                "components": [],
            }
            index[key] = group
            groups.append(group)
        group["components"].append(row)
    return groups


def yn12_ok(flags: dict) -> bool:
    for k, _ in YN12:
        v = flags.get(k) or ""
        if v not in ("是", "否"):
            return False
        if v == "否" and not (flags.get(f"{k}_reason") or "").strip():
            return False
    return True


def _num(v) -> float | None:
    try:
        s = str(v or "").replace(",", "").replace("%", "").strip()
        if s == "":
            return None
        return float(s)
    except ValueError:
        return None


def mix_allocated(total: str, pct_hi: str, pct_lo: str = "") -> dict:
    """混合物數量歸屬：比例為範圍時採上限；不寫入化學品核心列。"""
    tot = _num(total)
    hi = _num(pct_hi)
    if tot is None or hi is None:
        return {"qty": "", "estimate": False, "pure_kg": None}
    qty = tot * hi / 100.0
    lo = str(pct_lo or "").strip()
    estimate = bool(lo) and lo != str(pct_hi).strip()
    return {"qty": f"{qty:g}", "estimate": estimate, "pure_kg": qty}


def lookup_annex(cas: str | None, name: str | None = None) -> dict | None:
    key = str(cas or "").strip()
    if key and key in _ANNEX_BY_CAS:
        return dict(_ANNEX_BY_CAS[key])
    n = str(name or "").strip()
    if n:
        for row in _ANNEX_BY_CAS.values():
            if n in (row["name_zh"], row["name_en"]) or n in (row.get("aliases") or ()):
                return dict(row)
    return None


def annex_catalog() -> list[dict]:
    """施行細則危險物／有害物清單（有 CAS 者），供表單帶入名稱與規定數量。"""
    rows = [dict(v) for v in _ANNEX_BY_CAS.values() if v.get("cas")]
    rows.sort(key=lambda r: (0 if r["annex"] == "危險物" else 1, r["name_zh"]))
    return rows


def annex_fill_blanks(
    cas: str | None,
    fields: dict,
    *,
    keys: tuple[str, ...] = ("cas", "name", "name_en", "ctrl_qty"),
) -> dict:
    """僅在清單有列時補空白欄；已填的名稱、CAS 不覆寫。"""
    out = dict(fields)
    rec = lookup_annex(cas or out.get("cas"), out.get("name") if "name" in keys else None)
    if not rec:
        return out
    mapping = {
        "cas": rec["cas"],
        "name": rec["name_zh"],
        "name_en": rec["name_en"],
        "ctrl_qty": str(rec["limit_kg"]),
    }
    for k in keys:
        if k in mapping and not str(out.get(k) or "").strip():
            out[k] = mapping[k]
    return out


def annex_qty_check(
    *,
    cas: str | None = None,
    name: str | None = None,
    op_kg: str = "",
    wt_pct: str = "",
    wt_lo: str = "",
    is_aqueous: bool = False,
    n_pct: str | None = None,
    phase: str = "",
) -> dict:
    """操作量×重量百分比＝純物質公斤，再對施行細則規定數量。相態不符管制量相態者不列入。"""
    alloc = mix_allocated(op_kg, wt_pct or "100", wt_lo)
    pure = alloc["pure_kg"]
    rec = lookup_annex(cas, name)
    out = {
        "listed": bool(rec),
        "annex": rec["annex"] if rec else "",
        "limit_kg": rec["limit_kg"] if rec else None,
        "pure_kg": pure,
        "counted": False,
        "exceeds": False,
        "estimate": alloc["estimate"],
        "note": "",
        "name_zh": rec["name_zh"] if rec else "",
        "limit_phase": (rec.get("limit_phase") or "") if rec else "",
        "phase": str(phase or "").strip(),
    }
    if pure is None:
        out["note"] = "操作量或濃度無法計算"
        return out
    if not rec:
        out["note"] = "未列於勞動檢查法施行細則危險物／有害物規定數量，不納入甲類數量認定"
        return out
    cas_k = str(cas or rec.get("cas") or "").strip()
    phase_s = str(phase or "").strip()
    limit_phase = str(rec.get("limit_phase") or "")
    if rec.get("phase_gate") and phase_s and limit_phase and phase_s != limit_phase:
        out["note"] = (
            f"常用狀況相態為{phase_s}，附表管制量相態為{limit_phase}，相態不符不列入管制量"
        )
        return out
    if cas_k in AQUEOUS_EXCLUDED_CAS and is_aqueous and phase_s != "氣態":
        out["note"] = "氯化氫、氟化氫以氣態為規範對象；水溶液（鹽酸／氫氟酸）不列入"
        return out
    if cas_k == NITROCELLULOSE_CAS:
        np = _num(n_pct)
        if np is None or np <= 12.6:
            out["note"] = "硝化纖維僅含氮量大於 12.6% 者納入累計"
            return out
    out["counted"] = True
    out["exceeds"] = pure >= rec["limit_kg"]
    out["note"] = "達規定數量" if out["exceeds"] else "未達規定數量"
    return out


def _as_bool(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "on", "yes", "是")


def attach_annex_check(payload: dict) -> dict:
    row = dict(payload)
    op = row.get("total_kg") or row.get("op_kg") or ""
    wt = row.get("pct_hi") or row.get("wt") or ""
    chk = annex_qty_check(
        cas=row.get("cas"),
        name=row.get("mix_name") or row.get("name"),
        op_kg=str(op),
        wt_pct=str(wt),
        wt_lo=str(row.get("pct_lo") or ""),
        is_aqueous=_as_bool(row.get("is_aqueous")),
        n_pct=row.get("n_pct"),
        phase=str(row.get("phase_state") or row.get("phase") or ""),
    )
    alloc = mix_allocated(op, wt, row.get("pct_lo") or "")
    if not row.get("qty") and alloc["qty"]:
        row["qty"] = alloc["qty"]
    row["estimate"] = alloc["estimate"] or chk["estimate"]
    row["pure_kg"] = "" if chk["pure_kg"] is None else f"{chk['pure_kg']:g}"
    row["limit_kg"] = "" if chk["limit_kg"] is None else str(chk["limit_kg"])
    row["annex"] = chk["annex"]
    row["counted"] = chk["counted"]
    row["exceeds"] = chk["exceeds"]
    row["annex_note"] = chk["note"]
    if not row.get("formula"):
        row["formula"] = "操作量×重量百分比（上限）＝純物質公斤"
    return row


def merge_annex_qty(rows: list[dict]) -> dict[str, dict]:
    """同一 CAS 合併（示範場所視為間距 500 公尺以內）。"""
    out: dict[str, dict] = {}
    for raw in rows:
        row = attach_annex_check(raw)
        cas = str(row.get("cas") or "").strip()
        if not cas or not row.get("counted"):
            continue
        pure = _num(row.get("pure_kg")) or 0.0
        bucket = out.setdefault(
            cas,
            {
                "cas": cas,
                "pure_kg": 0.0,
                "limit_kg": _num(row.get("limit_kg")),
                "annex": row.get("annex") or "",
                "exceeds": False,
            },
        )
        bucket["pure_kg"] += pure
        lim = bucket.get("limit_kg")
        bucket["exceeds"] = lim is not None and bucket["pure_kg"] >= lim
    return out


def yn_all(flags: dict, keys: tuple[tuple[str, str], ...]) -> bool:
    return all((flags.get(k) or "") in ("是", "否") for k, _ in keys)
