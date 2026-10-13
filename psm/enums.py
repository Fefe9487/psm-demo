"""開站 SPEC §3 枚舉。值必須用完整中文名稱，不得縮寫。"""

EQUIPMENT_TYPES = (
    "壓力容器與儲槽",
    "管線系統",
    "釋放及排放系統",
    "緊急停車系統",
    "控制系統",
    "動力來源",
    "裝卸及輸送",
    "其他",
)

POWER_KINDS = ("泵浦", "氣動", "其他")

PHASE_CLASSES = ("粉狀固體", "粒狀固體", "液體", "氣體", "後段處理")

INCIDENT_TYPES = ("職業災害", "虛驚")

PROCESS_OVERVIEWS = {
    "P-TANK": "無水氟化氫經汽化後進入密閉緩衝與氣態供料系統；異常時切斷供料並導入尾氣處理。",
    "P-LOAD": "無水氟化氫以密閉接頭卸收，在接收區與供料區之間經汽化模組轉為氣態。",
    "P-SCRUB": "含氟尾氣進入鹼洗塔，以氫氧化鈉水溶液吸收並監測排放。",
    "P-ACID": "氫氧化鈉水溶液由配液區輸送至尾氣鹼洗塔。",
}

CHEMICAL_ROLES = ("原物料", "原料", "中間產物", "產物", "副產物", "觸媒", "清洗劑")

# 手冊表1.0-3 材質類別；對本署劣化機制查詢選項。建造材料另填規格名稱。
MATERIAL_CATEGORIES = (
    "碳鋼(CS)",
    "低合金",
    "高強度低合金(HSLA)",
    "300系不銹鋼",
    "400系不銹鋼",
    "銅",
    "鎳",
    "鑄鐵",
    "雙相不銹鋼",
    "鈦合金",
    "鋁合金",
    "耐火材料",
    "高分子材料",
    "其他",
)

PROCESS_MODES = ("continuous", "batch")

PROCESS_MODE_LABEL = {"continuous": "連續", "batch": "批次"}

SAFEGUARD_KINDS = ("equipment", "scenario", "sop")

# SOP／訓練清單的操作別：掛製程，或再掛該製程下的設備編號（不是第四份主檔）
OP_KINDS = ("process", "equipment")
OP_KIND_LABEL = {"process": "製程操作", "equipment": "機械設備操作"}

MASTER_TABLES = ("Process", "Equipment", "Chemical")

# 開站只做這一條寫死提示。完整專家規則屬後續投資，不算裂化速度、不代評分。
RULE_H314_CS_REMAIN = "R-H314-CS-REMAIN"
RULE_PHA_TEXT = "材質條件不相容；停車未排淨。請小組討論腐蝕穿孔、殘留接觸。嚴重度與可能性由小組填寫。"
RULE_MI_TEXT = "碳鋼與腐蝕性內容物且可能殘留：請檢討材質、排淨與檢測。可對照劣化機制查詢資料庫，查詢結果不代替風險評分。"

MATRIX_VERSION = "DEMO-5x5-2026"
MATRIX_ACCEPT_LINE = "S×L ≤ 9（低或中）為可接受；S×L ≥ 10（高或極高）須提出改善"

SITE_ID = "DEMO-SITE"
WIZARD_SITE_ID = "FILL-SITE"

UNIT_TITLES = {
    1: "製程安全資訊",
    2: "製程危害控制措施",
    3: "勞工參與",
    4: "標準作業程序",
    5: "教育訓練",
    6: "承攬管理",
    7: "啟動前安全檢查",
    8: "機械完整性",
    9: "動火許可",
    10: "變更管理",
    11: "事故調查",
    12: "緊急應變",
    13: "符合性稽核",
    14: "商業機密",
}

PROCEDURE_EMPTY_NOTE = "本示範未納入程序書全文。"
