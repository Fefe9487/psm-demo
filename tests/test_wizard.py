"""首次填報精靈：對齊 docs/2026-08-25-精靈十四項申報SPEC.md 驗收。"""

from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient

from psm.enums import WIZARD_SITE_ID
from psm.web import app


def _client(tmp_path, monkeypatch, name="wiz.sqlite"):
    monkeypatch.setattr("psm.db.db_path", lambda: tmp_path / name)
    monkeypatch.setattr("psm.web.db_path", lambda: tmp_path / name)
    monkeypatch.setattr("psm.wizard.db_path", lambda: tmp_path / name)
    return TestClient(app)


def _walk(client, through: int):
    for n in range(1, through + 1):
        r = client.post("/wizard/defaults", data={"step": str(n)}, follow_redirects=True)
        assert r.status_code == 200, f"step {n} defaults failed: {r.status_code}"
    return r


def test_home_is_first_time_landing_not_plant(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "land.sqlite")
    r = client.get("/")
    assert r.status_code == 200
    assert "開始首次填報" in r.text
    assert "為什麼" not in r.text or "第一次填報" in r.text
    assert 'id="plant-map"' not in r.text
    assert "T-101" not in r.text
    assert "新增／更新" not in r.text
    assert "資料表" in r.text


def test_wizard_step1_title_is_process_safety_info(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/wizard/start", follow_redirects=True)
    assert r.status_code == 200
    assert "第 1／14 章" in r.text
    assert "製程安全資訊" in r.text
    assert "附表一" not in r.text
    assert "附表二" not in r.text
    assert "為什麼" in r.text
    assert "這一頁只要做" in r.text
    nxt = r.text.split('id="wiz-next"', 1)[1].split(">", 1)[0]
    assert "disabled" in nxt
    assert "用預設值存這一頁" in r.text


def test_first_time_site_starts_without_sample_identity_or_accident_declaration(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "blank.sqlite")
    page = client.get("/wizard/1").text
    company = page.split('name="company_name"', 1)[1].split(">", 1)[0]
    incident = page.split('name="declare_no_incident_5y"', 1)[1].split(">", 1)[0]
    assert 'value=""' in company
    assert "checked" not in incident
    assert 'name="declare_no_equipment_types"' in page


def test_cannot_enter_step2_before_step1(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "gate2.sqlite")
    r = client.get("/wizard/2", follow_redirects=False)
    assert r.status_code in (303, 302)
    loc = r.headers.get("location", "")
    assert "/wizard/1" in loc


def test_cannot_skip_to_step8(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "skip8.sqlite")
    r = client.get("/wizard/8", follow_redirects=False)
    assert r.status_code in (303, 302)
    loc = r.headers.get("location", "")
    assert "/wizard/1" in loc
    assert "%E8%AB%8B%E5%85%88%E5%BB%BA%E7%AB%8B" in loc or "請先建立" in loc


def test_defaults_cannot_skip_steps(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "defskip.sqlite")
    r = client.post("/wizard/defaults", data={"step": "8"}, follow_redirects=False)
    assert r.status_code in (303, 302)
    assert "/wizard/1" in r.headers.get("location", "")


def test_step1_defaults_unlock_next_and_check_danger(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/wizard/defaults", data={"step": "1"}, follow_redirects=True)
    r2 = client.get("/wizard/1")
    assert "還不能往下" not in r2.text
    assert 'href="/wizard/2"' in r2.text
    assert "1.1" in r2.text
    assert "氟化氫" in r2.text
    assert "7664-39-3" in r2.text
    assert "應檢討" not in r2.text
    assert "提示事項" not in r2.text
    assert "勞工健康服務與管理措施" not in r2.text
    assert "項次 8　自動檢查計畫" not in r2.text
    assert "自動檢查計畫" not in r2.text


def test_step1_cards_open_edit_form(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "cards.sqlite")
    client.post("/wizard/defaults", data={"step": "1"}, follow_redirects=True)
    page = client.get("/wizard/1").text
    assert 'data-edit="equipment"' in page
    assert 'data-edit="process"' in page
    assert 'data-edit="department"' in page
    assert 'data-edit="area"' in page
    assert 'data-edit="chemical"' in page
    assert "T-101" in page
    assert "data-json=" in page
    assert "點列可改該筆" in page
    assert 'id="form-equipment"' in page
    proc_bit = page.split('data-edit="process"', 1)[1][:500]
    assert "/processes/P-TANK" not in proc_bit


def test_no_annex1_collection_anywhere_in_wizard(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "noannex.sqlite")
    _walk(client, 1)
    for n in range(1, 15):
        page = client.get(f"/wizard/{n}")
        if page.status_code != 200:
            continue
        assert "勞工健康服務與管理措施" not in page.text
        assert "自動檢查計畫" not in page.text
        assert "附表一" not in page.text
        assert "附表二" not in page.text


def test_step2_methods_not_hazop_worksheet(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "pha.sqlite")
    _walk(client, 1)
    page = client.get("/wizard/12", follow_redirects=False)
    assert page.status_code == 200  # V8.3：核心清單建好後各章可並行
    page = client.get("/wizard/2")
    assert page.status_code == 200
    assert "製程危害控制措施" in page.text
    assert "2.1" in page.text
    assert 'id="hazop-equipment"' not in page.text
    assert 'name="severity"' not in page.text
    assert "應檢討" not in page.text
    assert "提示事項" not in page.text
    nxt = page.text.split('id="wiz-next"', 1)[1].split(">", 1)[0]
    assert "disabled" not in nxt
    assert "本章尚待補齊" in page.text
    saved = client.post("/wizard/defaults", data={"step": "2"}, follow_redirects=True)
    assert saved.status_code == 200
    assert "PHA-評估紀錄.pdf" in saved.text
    nxt2 = saved.text.split('id="wiz-next"', 1)[1].split(">", 1)[0]
    assert "disabled" not in nxt2
    assert 'href="/wizard/3"' in saved.text
    db = sqlite3.connect(tmp_path / "pha.sqlite")
    assert db.execute("SELECT COUNT(*) FROM node").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM risk_score").fetchone()[0] == 0


def test_later_chapters_open_with_first_chapter_detail_missing(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "parallel.sqlite")
    _walk(client, 1)
    db = sqlite3.connect(tmp_path / "parallel.sqlite")
    db.execute("DELETE FROM filing_row WHERE site_id=? AND section='1.1'", (WIZARD_SITE_ID,))
    db.commit()
    db.close()
    first = client.get("/wizard/1")
    assert "本章尚待補齊" in first.text
    assert client.get("/wizard/12", follow_redirects=False).status_code == 200


def test_chapter14_requires_procedure_upload(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "secret.sqlite")
    _walk(client, 1)
    before = client.get("/wizard/14")
    assert "請上傳商業機密管理程序書" in before.text
    saved = client.post(
        "/wizard/14/upload",
        files={"file": ("secret-procedure.pdf", b"%PDF-1.4\n", "application/pdf")},
        follow_redirects=True,
    )
    assert saved.status_code == 200
    assert "本章基本檢核通過" in saved.text
    assert "secret-procedure.pdf" in saved.text
    report = client.get("/report")
    assert "secret-procedure.pdf" in report.text


def test_pha_filename_alone_does_not_count_as_upload(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "pha-real-file.sqlite")
    _walk(client, 2)
    page = client.get("/wizard/2")
    assert "僅範例檔名，待上傳" in page.text
    assert "請上傳" in page.text and "評估紀錄" in page.text

    no_file = client.post(
        "/wizard/2/upload", data={"file_name": "named-only.pdf"}, follow_redirects=True,
    )
    assert "只填檔名不算完成" in no_file.text
    db = sqlite3.connect(tmp_path / "pha-real-file.sqlite")
    assert db.execute(
        "SELECT COUNT(*) FROM unstructured_attachment WHERE original_name='named-only.pdf'"
    ).fetchone()[0] == 0
    db.close()

    uploaded = client.post(
        "/wizard/2/upload",
        files={"file": ("actual-pha.pdf", b"%PDF-1.4\n", "application/pdf")},
        follow_redirects=True,
    )
    assert "actual-pha.pdf" in uploaded.text
    assert "至少上傳一份評估紀錄" not in uploaded.text


def test_v83_report_shows_only_current_filing_and_pending_files(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "report-v83.sqlite")
    _walk(client, 2)
    page = client.get("/report")
    assert page.status_code == 200
    assert "V8.3 首次填報預覽" in page.text
    assert "第 14 章" in page.text
    assert "待上傳（僅有檔名）" in page.text
    assert "本示範未納入程序書全文" not in page.text
    assert "PHA-2026-001" not in page.text


def test_pha_method_can_be_cleared_and_first_chapter_marks_sample_files_pending(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "method-clear.sqlite")
    _walk(client, 1)
    first = client.get("/wizard/1").text
    assert "本章尚待補齊" in first
    assert "1.5 設備" in first
    assert "區域位置圖：請上傳實際檔案" in first
    assert "SDS：請上傳實際檔案" in first
    assert "圖資：請上傳實際檔案" in first
    assert "位置圖：待上傳" in first

    client.post(
        "/wizard/flags",
        data={"step": "2", "pha_methods_present": "1", "pha_methods": "hazop", "consider:hazop": "製程需要"},
    )
    assert "hazop" in client.get("/wizard/2").text
    client.post("/wizard/flags", data={"step": "2", "pha_methods_present": "1"})
    db = sqlite3.connect(tmp_path / "method-clear.sqlite")
    value = db.execute(
        "SELECT v FROM filing_flag WHERE site_id=? AND k='pha_methods'", (WIZARD_SITE_ID,)
    ).fetchone()[0]
    db.close()
    assert value == ""


def test_labor_reference_must_point_to_uploaded_file(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "labor-ref.sqlite")
    _walk(client, 2)
    invalid = client.post(
        "/wizard/3/proc",
        data={"labor_see_also": "1", "labor_ref": "999"},
        follow_redirects=True,
    )
    assert "請選擇一份已上傳的既有文件" in invalid.text

    uploaded = client.post(
        "/wizard/2/upload",
        files={"file": ("shared.pdf", b"%PDF-1.4\n", "application/pdf")},
        follow_redirects=True,
    )
    assert uploaded.status_code == 200
    db = sqlite3.connect(tmp_path / "labor-ref.sqlite")
    ref_id = db.execute(
        "SELECT attachment_id FROM unstructured_attachment WHERE original_name='shared.pdf'"
    ).fetchone()[0]
    db.close()
    saved = client.post(
        "/wizard/3/proc",
        data={"labor_see_also": "1", "labor_ref": str(ref_id)},
        follow_redirects=True,
    )
    assert saved.status_code == 200
    assert "shared.pdf" in saved.text
    assert "見既有附件：shared.pdf" in client.get("/report").text


def test_design_code_links_one_rule_to_multiple_equipment_and_chemicals(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "design-code.sqlite")
    _walk(client, 1)
    bad = client.post(
        "/wizard/1/design-code",
        data={"process_id": "P-TANK", "equipment_ids": "LA-101", "material": "CS A283",
              "material_category": "碳鋼(CS)", "spec": "API 650"},
        follow_redirects=True,
    )
    assert "設備必須屬於所選製程" in bad.text
    saved = client.post(
        "/wizard/1/design-code",
        data={"process_id": "P-TANK", "equipment_ids": ["T-101", "P-101"],
              "cas_list": "7664-39-3", "material": "CS A283",
              "material_category": "碳鋼(CS)", "spec": "API 650", "scope": "儲槽與泵浦"},
        follow_redirects=True,
    )
    assert saved.status_code == 200
    assert "儲槽與泵浦" in saved.text
    db = sqlite3.connect(tmp_path / "design-code.sqlite")
    code_id = db.execute("SELECT code_id FROM design_code WHERE code='API 650'").fetchone()[0]
    assert db.execute("SELECT COUNT(*) FROM design_code_equipment WHERE code_id=?", (code_id,)).fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM design_code_chemical WHERE code_id=?", (code_id,)).fetchone()[0] == 1
    db.close()
    report = client.get("/report").text
    assert "API 650" in report and "P-101" in report and "T-101" in report


def test_psi_and_later_use_selects_not_free_names(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "sel.sqlite")
    _walk(client, 1)
    s1 = client.get("/wizard/1").text
    block_11 = s1.split("1.1", 1)[1].split("1.2", 1)[0]
    assert "<select" in block_11
    assert 'name="cas"' in block_11
    block_15 = s1.split("1.5", 1)[1].split("1.6", 1)[0]
    assert 'name="equipment_id"' in block_15
    assert "<select" in block_15
    _walk(client, 12)
    s4 = client.get("/wizard/4").text
    assert "<select" in s4
    assert 'name="process_id"' in s4
    s8 = client.get("/wizard/8").text
    assert 'name="equipment_id"' in s8
    assert "<select" in s8
    s12 = client.get("/wizard/12").text
    assert "<select" in s12


def test_defaults_survive_renamed_parent_tables(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "stale.sqlite")
    first = client.post("/wizard/defaults", data={"step": "1"}, follow_redirects=False)
    assert first.status_code == 303
    conn = sqlite3.connect(tmp_path / "stale.sqlite")
    conn.execute("PRAGMA writable_schema=ON")
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='inventory'").fetchone()[0]
    conn.execute(
        "UPDATE sqlite_master SET sql=? WHERE name='inventory'",
        (
            sql.replace(
                "REFERENCES chemical_cite(cas, process_id)",
                'REFERENCES "chemical__old"(cas, process_id)',
            ),
        ),
    )
    version = int(conn.execute("PRAGMA schema_version").fetchone()[0])
    conn.execute(f"PRAGMA schema_version={version + 1}")
    conn.execute("PRAGMA writable_schema=OFF")
    conn.commit()
    conn.close()
    again = client.post("/wizard/defaults", data={"step": "1"}, follow_redirects=False)
    assert again.status_code == 303
    assert "err=" not in again.headers.get("location", "")
    check = sqlite3.connect(tmp_path / "stale.sqlite")
    fixed = check.execute("SELECT sql FROM sqlite_master WHERE name='inventory'").fetchone()[0]
    assert "chemical__old" not in fixed
    assert "chemical_cite" in fixed
    check.close()


def test_no_contractor_and_no_hotwork_gates(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "decl.sqlite")
    page1 = client.get("/wizard/1").text
    assert 'name="declare_no_contractor"' not in page1
    assert 'name="declare_no_hotwork"' not in page1
    assert "無承攬" not in page1
    assert "無動火" not in page1
    _walk(client, 6)
    s6 = client.get("/wizard/6")
    assert s6.status_code == 200
    assert "還不能往下" not in s6.text
    assert "承攬管理確認事項" not in s6.text
    assert "表6.2-1" in s6.text
    db = sqlite3.connect(tmp_path / "decl.sqlite")
    db.row_factory = sqlite3.Row
    assert db.execute("SELECT declare_no_contractor FROM site").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM contractor_incident").fetchone()[0] >= 1
    _walk(client, 9)
    s9 = client.get("/wizard/9")
    assert s9.status_code == 200
    assert "還不能往下" not in s9.text
    assert "動火許可" in s9.text
    assert "表9.1-1" in s9.text
    assert db.execute("SELECT COUNT(*) FROM hotwork_zone").fetchone()[0] >= 1
    db.close()


def test_walk_all_14_defaults_no_hazop_nodes(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "all14.sqlite")
    for n in range(1, 15):
        r = client.post("/wizard/defaults", data={"step": str(n)}, follow_redirects=True)
        assert r.status_code == 200, n
        page = client.get(f"/wizard/{n}")
        assert page.status_code == 200, n
        if n < 14:
            assert "還不能往下" not in page.text, n
            assert f'href="/wizard/{n + 1}"' in page.text, n
        assert "附表一" not in page.text
        assert "附表二" not in page.text
        assert 'id="hazop-equipment"' not in page.text
        assert 'name="severity"' not in page.text
    last = client.get("/wizard/14")
    assert "商業機密" in last.text
    assert "預覽申報報告" in last.text
    db = sqlite3.connect(tmp_path / "all14.sqlite")
    assert db.execute("SELECT COUNT(*) FROM node").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM risk_score").fetchone()[0] == 0
    assert db.execute("SELECT declare_no_contractor, declare_no_hotwork FROM site").fetchone() == (0, 0)
    assert db.execute("SELECT COUNT(*) FROM contractor_incident").fetchone()[0] >= 1
    assert db.execute("SELECT COUNT(*) FROM hotwork_zone").fetchone()[0] >= 1
    db.close()


def test_wizard_node_score_paths_disabled(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "gone.sqlite")
    r = client.post(
        "/wizard/12/node",
        data={"process_id": "P-TANK", "node_id": "N-01"},
        follow_redirects=False,
    )
    assert r.status_code in (303, 302, 404, 410)
    r2 = client.post(
        "/wizard/12/score",
        data={"consequence_id": "C-01", "severity": "3", "likelihood": "2"},
        follow_redirects=False,
    )
    assert r2.status_code in (303, 302, 404, 410)


def test_psi_handbook_tables_on_step1(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "psi-v6.sqlite")
    page = client.get("/wizard/start", follow_redirects=True).text
    assert "表1.0-4" in page
    assert "混合物成分對應表" not in page
    assert "不是第四張核心表" not in page
    assert "蒸氣壓" in page
    assert "閃火點" in page
    assert "TWA" in page
    assert 'id="flow-canvas"' in page
    assert 'id="flow-add"' in page and "加入流程圖" in page
    assert "已選" in page
    assert "巢狀表" in page
    assert 'id="flow-next-proc"' in page
    assert 'id="flow-edit-process"' in page
    assert "設備編號" in page
    assert "氧化" in page
    assert "硝化" in page
    assert "容積" in page
    assert "通風型式" in page
    assert "本場所未規劃為防爆區域" in page
    assert "設定壓力" in page
    assert "緊急停車方案" not in page
    assert "特化" in page
    assert "附表一" not in page
    assert "操作量" in page or "混合物總量" in page
    assert "規定數量" in page
    saved = client.post("/wizard/defaults", data={"step": "1"}, follow_redirects=True)
    assert saved.status_code == 200
    text = saved.text
    assert "無水氟化氫" in text
    assert "Hydrogen fluoride" in text
    assert "氫氧化鈉" in text
    assert "進料" in text or "方塊" in text
    assert "PSV-101" in text
    assert "ESD-101" in text
    assert "H314,H330" in text
    assert "達規定數量" in text
    assert "7664-39-3" in text
    assert "反應熱" in text
    assert "HF + NaOH" in text
    assert "從危險物／有害物清單帶入" in text
    assert "常用狀況相態" in text
    assert "表1.0-5" in text
    assert text.find("登錄設備及維護部門") < text.find("登錄製程使用的化學品與成分") < text.find("劃分廠區區域並關聯設備與化學品")
    assert "材質類別" in text
    assert "表4.3-1" in text
    db = sqlite3.connect(tmp_path / "psi-v6.sqlite")
    payloads_11 = [
        json.loads(r[0])
        for r in db.execute(
            "SELECT payload FROM filing_row WHERE site_id=? AND section='1.1'",
            (WIZARD_SITE_ID,),
        )
    ]
    cas_11 = {r["cas"] for r in payloads_11}
    assert "7664-39-3" in cas_11
    assert "108-88-3" not in cas_11
    payloads_12 = [
        json.loads(r[0])
        for r in db.execute(
            "SELECT payload FROM filing_row WHERE site_id=? AND section='1.2'",
            (WIZARD_SITE_ID,),
        )
    ]
    cas_12 = {r["cas"] for r in payloads_12}
    assert "7664-39-3" in cas_12
    assert "108-88-3" not in cas_12
    assert db.execute("SELECT 1 FROM chemical WHERE cas='7664-39-3'").fetchone()


def test_mixture_components_save_as_nested_rows(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "mix-nest.sqlite")
    _walk(client, 1)
    page = client.get("/wizard/1")
    assert 'id="chem-mix-flag"' in page.text
    assert 'id="mix-nest"' in page.text
    saved = client.post(
        "/wizard/1/chemical",
        data={
            "kind": "混合物",
            "process_id": "P-TANK",
            "mix_name": "溶劑混和",
            "file_name": "SDS-mix.pdf",
            "basis": "重量比",
            "total_kg": "1000",
            "comp_cas": ["108-88-3", "67-64-1"],
            "comp_name": ["甲苯", "丙酮"],
            "comp_role": ["原物料", "原物料"],
            "comp_h": ["H225", "H225"],
            "comp_pct_lo": ["40", "10"],
            "comp_pct_hi": ["60", "20"],
            "comp_phase": ["液態", "液態"],
            "comp_formula": ["", ""],
        },
        follow_redirects=True,
    )
    assert saved.status_code == 200
    assert "溶劑混和" in saved.text
    assert "67-64-1" in saved.text
    db = sqlite3.connect(tmp_path / "mix-nest.sqlite")
    mixes = [
        json.loads(r[0])
        for r in db.execute(
            "SELECT payload FROM filing_row WHERE site_id=? AND section='mix'",
            (WIZARD_SITE_ID,),
        )
    ]
    db.close()
    named = [m for m in mixes if m.get("mix_name") == "溶劑混和"]
    assert {m["cas"] for m in named} == {"108-88-3", "67-64-1"}


def test_annex_listed_cas_autofills_name(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "annex-name.sqlite")
    _walk(client, 1)
    ok = client.post(
        "/wizard/1/chemical",
        data={
            "cas": "75-21-8",
            "process_id": "P-TANK",
            "name": "",
            "role": "原物料",
            "h_codes": "H220",
            "phase_state": "氣態",
            "file_name": "SDS-EO.pdf",
        },
        follow_redirects=True,
    )
    assert ok.status_code == 200
    assert "環氧乙烷" in ok.text
    miss = client.post(
        "/wizard/1/chemical",
        data={
            "cas": "64-17-5",
            "process_id": "P-TANK",
            "name": "",
            "role": "原物料",
            "h_codes": "H225",
            "phase_state": "液態",
            "file_name": "SDS-etoh.pdf",
        },
        follow_redirects=True,
    )
    assert miss.status_code == 200
    assert "須自行填名稱" in miss.text


def test_other_reaction_kind_requires_written_type(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "rxn-other.sqlite")
    _walk(client, 1)
    missing = client.post(
        "/wizard/row",
        data={
            "step": "1",
            "section": "1.4",
            "process_id": "P-SCRUB",
            "kinds": "其他",
            "kind_other": "",
            "formula": "HF + NaOH → NaF + H2O",
            "heat": "中和放熱",
        },
        follow_redirects=True,
    )
    assert missing.status_code == 200
    assert "請寫反應種類" in missing.text
    saved = client.post(
        "/wizard/row",
        data={
            "step": "1",
            "section": "1.4",
            "process_id": "P-SCRUB",
            "kinds": "其他",
            "kind_other": "中和",
            "formula": "HF + NaOH → NaF + H2O",
            "heat": "中和放熱",
        },
        follow_redirects=True,
    )
    assert saved.status_code == 200
    assert "其他（中和）" in saved.text
    flagged = client.post(
        "/wizard/flags",
        data={"step": "1", "rxn_process": "P-SCRUB", "rxn_types": "其他"},
        follow_redirects=True,
    )
    assert flagged.status_code == 200
    assert "請寫反應種類" in flagged.text
    named = client.post(
        "/wizard/flags",
        data={
            "step": "1",
            "rxn_process": "P-SCRUB",
            "rxn_types": "其他",
            "rxn_type_other": "中和",
        },
        follow_redirects=True,
    )
    assert named.status_code == 200
    assert "請寫反應種類" not in named.text
    conn = sqlite3.connect(tmp_path / "rxn-other.sqlite")
    stored = conn.execute(
        "SELECT v FROM filing_flag WHERE k=?", ("rxn_other:P-SCRUB",)
    ).fetchone()
    conn.close()
    assert stored is not None and stored[0] == "中和"


def test_reaction_formula_requires_heat(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "rxn-heat.sqlite")
    _walk(client, 1)
    r = client.post(
        "/wizard/row",
        data={
            "step": "1",
            "section": "1.4",
            "process_id": "P-SCRUB",
            "kinds": "其他",
            "formula": "2 H2O2 → 2 H2O + O2",
            "heat": "",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "反應熱" in r.text
    assert "須填反應熱" in r.text


def test_psi_save_12_blocks_18_and_esd(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "psi-save.sqlite")
    _walk(client, 1)
    r12 = client.post(
        "/wizard/row",
        data={
            "step": "1",
            "section": "1.2",
            "cas": "7664-39-3|P-TANK",
            "name_en": "Hydrogen fluoride",
            "conc": "99",
            "ctrl_qty": "",
            "state": "氣",
            "odor": "刺激性",
            "vp": "22",
            "bp": "19.4",
            "fp": "不適用",
            "expl": "不適用",
            "twa": "3 ppm（NIOSH REL）",
            "physical": "腐蝕性氣體",
            "health": "吸入及接觸危害",
            "incompat": "是",
            "incompat_note": "",
            "stable": "是",
            "stable_note": "依供應商 SDS 核對",
        },
        follow_redirects=True,
    )
    assert r12.status_code == 200
    assert "22" in r12.text
    assert "19.4" in r12.text
    rblk = client.post(
        "/wizard/1/blocks",
        data={
            "process_id": "P-TANK",
            "seq_1": "1",
            "name_1": "氣態供料",
            "desc_1": "T-101 密閉緩衝供氣",
            "next_1": "2",
            "seq_2": "2",
            "name_2": "緊急隔離",
            "desc_2": "ESD-101 切斷供料",
            "next_2": "",
        },
        follow_redirects=True,
    )
    assert rblk.status_code == 200
    with sqlite3.connect(tmp_path / "psi-save.sqlite") as block_db:
        assert block_db.execute("SELECT 1 FROM filing_row WHERE section='1.3b' AND json_extract(payload, '$.desc')='T-101 密閉緩衝供氣'").fetchone()
    r8 = client.post(
        "/wizard/row",
        data={
            "step": "1",
            "section": "1.8",
            "area_code": "AREA-A",
            "floor": "1F",
            "cas": "7664-39-3|P-TANK",
            "comp": "無水氟化氫",
            "fp": "不適用",
            "bp": "19.4",
            "sg": "0.69",
            "expl": "不適用",
            "ait": "不適用",
            "vent_type": "N",
            "vent_level": "VM",
            "vent_avail": "A",
            "leak": ["P", "S"],
            "zone": ["1", "2"],
            "eq_group": "不適用",
        },
        follow_redirects=True,
    )
    assert r8.status_code == 200
    assert "不適用" in r8.text
    resd = client.post(
        "/wizard/1/esd",
        data={
            "scenario_id": "ESD-SC-01",
            "process_id": "P-TANK",
            "esd_equipment_id": "ESD-101",
            "name": "HF 供料緊急隔離",
            "trigger_conditions": "高高壓或 HF 洩漏警報",
            "maint_dept_id": "D-MAINT",
            "action_ids": ["T-101", "P-101"],
        },
        follow_redirects=True,
    )
    assert resd.status_code == 200
    db = sqlite3.connect(tmp_path / "psi-save.sqlite")
    assert db.execute("SELECT COUNT(*) FROM esd_scenario").fetchone()[0] >= 1
    assert db.execute("SELECT COUNT(*) FROM esd_action").fetchone()[0] >= 1


def test_labor_items_can_be_added_and_deleted_with_file_date(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "labor-v6.sqlite")
    _walk(client, 2)
    page = client.get("/wizard/3").text
    assert "勞工參與" in page
    assert 'name="item"' in page
    assert 'name="how"' in page
    assert 'name="labor_date"' in page
    saved = client.post("/wizard/defaults", data={"step": "3"}, follow_redirects=True)
    assert saved.status_code == 200
    assert "反映與實際運作不一致" in saved.text
    assert "還不能往下" not in saved.text
    item = sqlite3.connect(tmp_path / "labor-v6.sqlite").execute("SELECT json_extract(payload, '$.item') FROM filing_row WHERE section='3.1' LIMIT 1").fetchone()[0]
    updated = client.post("/wizard/3/labor", data={"item": item, "how": "現場參與檢查", "who": "D-OPS"}, follow_redirects=True)
    assert updated.status_code == 200
    assert "現場參與檢查" in updated.text
    assert "/wizard/row/delete" in updated.text


def test_mi_handbook_81_82(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "mi-v6.sqlite")
    _walk(client, 7)
    page = client.get("/wizard/8").text
    assert "挑選安全關鍵設備並安排檢查保養" in page
    assert 'name="damage"' in page
    assert 'name="inspection_item"' in page
    assert "每列只填一個損壞機制" in page
    assert "檢查及測試方式" in page
    assert "失效事件數" in page
    assert "壓力容器與儲槽" in page
    assert "泵浦(轉動設備)" in page
    assert "設備管線劣化機制查詢" in page
    assert "表1.6-1" in page
    assert 'id="mi-matcat"' in page
    assert "readonly" in page
    assert "表8.2-1" in page
    saved = client.post("/wizard/defaults", data={"step": "8"}, follow_redirects=True)
    assert saved.status_code == 200
    with sqlite3.connect(tmp_path / "mi-v6.sqlite") as conn:
        detail_id = conn.execute("SELECT detail_id FROM mi_inspection_detail WHERE equipment_id='T-101'").fetchone()[0]
    confirmed = client.post("/wizard/row", data={
        "step": "8", "section": "8.1", "detail_id": detail_id,
        "equipment_id": "T-101", "mi_type": "壓力容器與儲槽", "damage": "材質相容性",
        "method": "超音波測厚", "freq": "每年", "proc_no": "MI-T-101",
        "pid_no": "PID-TANK-001",
    }, follow_redirects=True)
    assert confirmed.status_code == 200
    fail = client.post(
        "/wizard/8/fail",
        data={
            "equipment_id": "T-101", "period_start": "2025-01-01",
            "period_end": "2025-12-31", "hours": "8000",
            "repair": "1", "note": "不含定期保養",
        },
        follow_redirects=True,
    )
    assert fail.status_code == 200
    assert "8000" in fail.text
    assert "不含定期保養" in fail.text
    assert "T-101" in fail.text


def test_v73_tables_on_later_steps(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "v73.sqlite")
    _walk(client, 12)
    s4 = client.get("/wizard/4").text
    assert "表4.1-1" in s4
    assert "SOP-VESSEL-01" in s4
    assert "設備類型" in s4
    s5 = client.get("/wizard/5").text
    assert "對應作業程序" in s5
    s7 = client.get("/wizard/7").text
    assert "將引入化學品" not in s7
    assert "追蹤檢核結果" in s7
    assert "T-101" in s7
    s6 = client.get("/wizard/6").text
    assert "表6.2-1" in s6
    s9 = client.get("/wizard/9").text
    assert "表9.1-1" in s9
    s12 = client.get("/wizard/12").text
    assert "表12.1-1" in s12
    assert "表12.2-1" in s12
    assert "數量與計數單位分填" in s12
    assert "填否原因" not in s12
    assert "區域名稱" in s12


def test_area_save_can_answer_without_reloading(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, "area-partial.sqlite")
    _walk(client, 1)
    data = {
        "area_code": "AREA-KEEP",
        "name": "留在原處",
        "drawing_no": "PLOT-KEEP",
        "revision": "A",
        "issue_date": "2026-09-22",
        "worker_count": "3",
        "is_assembly_point": "on",
    }
    stayed = client.post(
        "/wizard/1/area",
        data=data,
        headers={"X-PSM-Partial": "1"},
        follow_redirects=False,
    )
    assert stayed.status_code == 200
    body = stayed.json()
    assert body["ok"] is True
    assert body["area"]["name"] == "留在原處"
    assert body["area"]["is_assembly_point"] == 1
    jumped = client.post("/wizard/1/area", data=data, follow_redirects=False)
    assert jumped.status_code == 303
    dept = client.post(
        "/wizard/1/dept",
        data={"dept_id": "D-KEEP", "name": "留在原處部門", "headcount": "4"},
        headers={"X-PSM-Partial": "1"},
        follow_redirects=False,
    )
    assert dept.status_code == 200
    assert dept.json()["row"]["name"] == "留在原處部門"
    page = client.get("/wizard/1").text
    assert "wizard.js?v=" in page
