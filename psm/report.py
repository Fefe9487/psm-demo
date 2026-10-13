"""由同一套主檔 JOIN 產出甲類送審／報備 HTML（可列印 PDF）。"""

from __future__ import annotations

import html
import sqlite3

from psm.enums import (
    MATRIX_ACCEPT_LINE,
    MATRIX_VERSION,
    PROCEDURE_EMPTY_NOTE,
    PROCESS_MODE_LABEL,
    UNIT_TITLES,
)
from psm import filing as fil


def _e(v) -> str:
    if v is None:
        return ""
    return html.escape(str(v))


def _yn(v) -> str:
    return "是" if v else "否"


def _rows(conn: sqlite3.Connection, sql: str, args=()) -> list[sqlite3.Row]:
    return conn.execute(sql, args).fetchall()


def _table(headers: list[str], rows: list[list[str]]) -> str:
    th = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = []
    for r in rows:
        tds = "".join(f"<td>{cell}</td>" for cell in r)
        body.append(f"<tr>{tds}</tr>")
    if not body:
        body.append(f"<tr><td colspan='{len(headers)}'>（無列）</td></tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _proc_block() -> str:
    return (
        "<h4>程序</h4>"
        f"<p class='empty-proc'>{_e(PROCEDURE_EMPTY_NOTE)}</p>"
        "<p>程序編號／附件：<em>（空）</em></p>"
    )


def _chapter(n: int, exec_html: str, forms: list[str]) -> str:
    title = UNIT_TITLES[n]
    forms_ul = "<ul>" + "".join(f"<li>{_e(x)}</li>" for x in forms) + "</ul>"
    return (
        f"<section id='ch-3-{n}'>"
        f"<h2>3.{n}　第{n}章　{_e(title)}</h2>"
        f"{_proc_block()}"
        f"<h4>執行結果</h4>{exec_html}"
        f"<h4>使用表單／附件清單</h4>{forms_ul}"
        "</section>"
    )


def render_report_html(conn: sqlite3.Connection, site_id: str) -> str:
    site = conn.execute("SELECT * FROM site WHERE site_id=?", (site_id,)).fetchone()
    if not site:
        return "<p>場所不存在</p>"

    processes = _rows(
        conn,
        """SELECT p.*, d.name AS operating_dept_name
           FROM process p JOIN department d ON d.dept_id=p.operating_dept_id
           WHERE p.site_id=? ORDER BY p.process_id""",
        (site_id,),
    )
    depts = _rows(conn, "SELECT * FROM department WHERE site_id=? ORDER BY dept_id", (site_id,))
    equipment = _rows(
        conn,
        """SELECT e.equipment_id, e.name, e.equipment_type, e.power_kind, e.phase_class,
                  e.process_id, p.name AS process_name,
                  p.operating_dept_id, od.name AS operating_dept_name,
                  e.maint_dept_id, md.name AS maint_dept_name,
                  e.area_code, e.is_safety_critical, e.is_regulated_machinery
           FROM equipment e
           JOIN process p ON p.process_id=e.process_id
           JOIN department od ON od.dept_id=p.operating_dept_id
           JOIN department md ON md.dept_id=e.maint_dept_id
           WHERE e.site_id=? ORDER BY e.equipment_id""",
        (site_id,),
    )
    chems = _rows(
        conn,
        """SELECT c.*, p.name AS process_name
           FROM chemical c JOIN process p ON p.process_id=c.process_id
           JOIN process p2 ON p2.process_id=c.process_id AND p2.site_id=?
           ORDER BY c.cas, c.process_id""",
        (site_id,),
    )
    areas = _rows(conn, "SELECT * FROM area WHERE site_id=? ORDER BY area_code", (site_id,))
    pids = _rows(
        conn,
        """SELECT d.*, GROUP_CONCAT(c.equipment_id, ', ') AS covering
           FROM pid_drawing d
           JOIN process p ON p.process_id=d.process_id
           LEFT JOIN pid_covering c ON c.drawing_no=d.drawing_no AND c.revision=d.revision
           WHERE p.site_id=?
           GROUP BY d.drawing_no, d.revision""",
        (site_id,),
    )
    hazop = _rows(
        conn,
        """SELECT n.node_id, n.process_id, n.description, n.deviation, n.cause,
                  GROUP_CONCAT(DISTINCT ne.equipment_id) AS equipment_ids,
                  GROUP_CONCAT(DISTINCT nc.cas) AS cas_list,
                  cons.consequence_id, cons.description AS cons_desc,
                  cons.disaster_type, cons.area_code,
                  rs.severity, rs.likelihood, rs.rank_label, rs.rank_value, rs.stale,
                  (SELECT GROUP_CONCAT(
                      COALESCE(s.equipment_id, s.scenario_id, s.sop_id), ', ')
                   FROM safeguard s WHERE s.consequence_id=cons.consequence_id) AS safeguards
           FROM node n
           LEFT JOIN node_equipment ne ON ne.node_id=n.node_id
           LEFT JOIN node_chemical nc ON nc.node_id=n.node_id
           LEFT JOIN consequence cons ON cons.node_id=n.node_id
           LEFT JOIN risk_score rs ON rs.consequence_id=cons.consequence_id
           JOIN assessment a ON a.assessment_id=n.assessment_id
           JOIN process p ON p.process_id=n.process_id
           WHERE p.site_id=?
           GROUP BY n.node_id, cons.consequence_id
           ORDER BY n.node_id""",
        (site_id,),
    )
    pec = _rows(
        conn,
        """SELECT m.*, p.name AS process_name, e.name AS equipment_name,
                  c.name AS chemical_name
           FROM pec_map m
           JOIN process p ON p.process_id=m.process_id
           JOIN equipment e ON e.equipment_id=m.equipment_id
           LEFT JOIN chemical c ON c.cas=m.cas AND c.process_id=m.process_id
             AND c.sds_id=m.sds_id
           WHERE p.site_id=?
           ORDER BY m.process_id, m.equipment_id, m.cas""",
        (site_id,),
    )
    prompts = _rows(
        conn,
        """SELECT pe.* FROM prompt_event pe
           JOIN process p ON p.process_id=pe.process_id
           WHERE p.site_id=?
           ORDER BY pe.stage, pe.equipment_id""",
        (site_id,),
    )

    cover = f"""
    <section id="cover">
      <p class="doc-kind">甲類工作場所　送審／報備　製程安全管理文件（示範產出）</p>
      <h1>{_e(site['company_name'])}</h1>
      <h2>{_e(site['site_name'])}</h2>
      <table class="meta">
        <tr><th>場所識別</th><td>{_e(site['site_id'])}</td></tr>
        <tr><th>事業單位</th><td>{_e(site['company_name'])}</td></tr>
        <tr><th>場所名稱</th><td>{_e(site['site_name'])}</td></tr>
        <tr><th>範圍</th><td>{_e(site['scope'])}</td></tr>
        <tr><th>申請義務人</th><td>{_e(site['applicant_name'])}</td></tr>
        <tr><th>評估基準日</th><td>{_e(site['assessment_base_date'])}</td></tr>
        <tr><th>矩陣版本</th><td>{_e(MATRIX_VERSION)}</td></tr>
        <tr><th>可接受線</th><td>{_e(MATRIX_ACCEPT_LINE)}</td></tr>
      </table>
    </section>
    """

    toc = "<nav class='toc'><h2>目錄</h2><ol>"
    toc += "<li><a href='#masters'>主檔摘要</a></li>"
    toc += "<li><a href='#drawings'>圖資索引</a></li>"
    for i in range(1, 15):
        toc += f"<li><a href='#ch-3-{i}'>3.{i} {html.escape(UNIT_TITLES[i])}</a></li>"
    toc += "<li><a href='#appendix-a'>附錄 A 自我檢核</a></li></ol></nav>"

    master = f"""
    <section id="masters">
      <h2>主檔摘要</h2>
      <p>名稱由 JOIN 帶出；儲存僅使用編號。部門改名不必改設備列。</p>
      <h3>部門</h3>
      {_table(['部門編號','名稱'], [[_e(d['dept_id']), _e(d['name'])] for d in depts])}
      <h3>製程</h3>
      {_table(
        ['製程編號','名稱','操作權責部門','連續或批次','化學反應','過壓保護','裝卸單元','後段處理'],
        [[
          _e(p['process_id']), _e(p['name']),
          f"{_e(p['operating_dept_id'])} {_e(p['operating_dept_name'])}",
          PROCESS_MODE_LABEL.get(p['mode'], p['mode']),
          _yn(p['has_chemical_reaction']), _yn(p['has_overpressure']),
          _yn(p['is_loading']), _yn(p['is_downstream']),
        ] for p in processes]
      )}
      <h3>設備（JOIN 製程名、部門名；僅甲類範圍內設備／管線）</h3>
      {_table(
        ['設備編號','名稱','類型','動力型式','操作分類','製程編號','製程名稱','操作權責','維護權責','區域','危險性機械或設備'],
        [[
          _e(e['equipment_id']), _e(e['name']), _e(e['equipment_type']),
          _e(e['power_kind']), _e(e['phase_class']), _e(e['process_id']),
          _e(e['process_name']),
          f"{_e(e['operating_dept_id'])} {_e(e['operating_dept_name'])}",
          f"{_e(e['maint_dept_id'])} {_e(e['maint_dept_name'])}",
          _e(e['area_code']), _yn(e['is_regulated_machinery']),
        ] for e in equipment]
      )}
      <h3>化學品（可列製造、處置、使用之危害物；規定數量僅對施行細則所列物質自動帶入）</h3>
      {_table(
        ['CAS','製程編號','製程名稱','品名','角色','UN','運輸分類'],
        [[_e(c['cas']), _e(c['process_id']), _e(c['process_name']), _e(c['name']),
          _e(c['role']), _e(c['un_number']), _e(c['transport_hazard_class'])] for c in chems]
      )}
      <h3>製程－設備－化學品對應表（只列實際關係）</h3>
      {_table(
        ['製程','設備','CAS','危害說明','材質','可能殘留','檢討'],
        [[
          _e(m['process_id']), _e(m['equipment_id']), _e(m['cas']) or '（無）',
          _e(m['h_codes']), _e(m['material']), _yn(m['may_remain']),
          _e(m['review_notes']),
        ] for m in pec]
      )}
    </section>
    """

    drawing = f"""
    <section id="drawings">
      <h2>圖資索引</h2>
      <h3>廠區位置圖區域</h3>
      {_table(
        ['區域代碼','名稱','圖號','版次','製程','集合點'],
        [[_e(a['area_code']), _e(a['name']), _e(a['drawing_no']), _e(a['revision']),
          _e(a['process_id']), _yn(a['is_assembly_point'])] for a in areas]
      )}
      <h3>管線儀表圖（表3.1-4）</h3>
      {_table(
        ['圖號','版次','名稱','製程','現況','涵蓋設備'],
        [[_e(d['drawing_no']), _e(d['revision']), _e(d['name']), _e(d['process_id']),
          _yn(d['is_as_built']), _e(d['covering'])] for d in pids]
      )}
    </section>
    """

    inv = _rows(conn, "SELECT * FROM inventory")
    limits = _rows(conn, "SELECT * FROM equipment_limit")
    mats = _rows(conn, "SELECT * FROM equipment_material")
    relief = _rows(conn, "SELECT * FROM relief_device")
    locks = _rows(conn, "SELECT * FROM interlock")
    hz = _rows(conn, "SELECT * FROM chem_hazard_check")
    cp = _rows(conn, "SELECT * FROM chem_compatibility")
    hd = _rows(conn, "SELECT * FROM chem_handling")
    react = _rows(conn, "SELECT * FROM reaction_info")
    expl = _rows(conn, "SELECT * FROM explosion_area")
    vent = _rows(conn, "SELECT * FROM ventilation")
    codes = _rows(conn, "SELECT * FROM design_code")
    none_types = site["declare_no_equipment_types"] or ""
    mix_rows = [fil.attach_annex_check(r) for r in fil.list_rows(conn, site_id, "mix")]
    mix_tbl = _table(
        ["混合物", "CAS", "製程", "操作量kg", "wt%", "純物質kg", "規定數量kg", "認定"],
        [[
            _e(r.get("mix_name")), _e(r.get("cas")), _e(r.get("process_id")),
            _e(r.get("total_kg")), _e(r.get("pct_hi")), _e(r.get("pure_kg")),
            _e(r.get("limit_kg")), _e(r.get("annex_note")),
        ] for r in mix_rows],
    )
    rxn_tbl = _table(
        ["製程", "反應種類", "化學反應式", "反應熱", "摘要"],
        [[
            _e(r["process_id"]), _e(r["kinds"] if "kinds" in r.keys() else ""),
            _e(r["formula"] if "formula" in r.keys() else ""),
            _e(r["heat"] if "heat" in r.keys() else ""),
            _e(r["summary"]),
        ] for r in react],
    )

    ch1 = _chapter(
        1,
        f"""
        <p>無某設備類型聲明：{_e(none_types) or '（無）'}。禁止虛構主檔列。化學品可自行新增；規定數量自動帶入僅限危險物／有害物清單。管線與設備只填甲類範圍內須申報者。</p>
        <p>甲類數量認定依勞動檢查法施行細則：操作量×重量百分比換算為純物質公斤，再對照危險物／有害物規定數量。化學品須填常用狀況相態（固態、液態、氣態）。氯化氫、氟化氫的附表管制量相態為氣態，液態或固態不列入。同一事業單位間距 500 公尺以內合併計算。</p>
        {mix_tbl}
        {_table(['CAS','製程','最大存量kg','區域','計算說明'],
            [[_e(r['cas']), _e(r['process_id']), _e(r['max_kg']), _e(r['area_code']), _e(r['calc_note'])] for r in inv])}
        <p>表3.1-2 安全上下限（設計範圍，非品質界限）</p>
        {_table(['設備編號','參數','單位','設計高','設計低','安全上','安全下'],
            [[_e(r['equipment_id']), _e(r['parameter']), _e(r['unit']),
              _e(r['design_high']), _e(r['design_low']), _e(r['safety_high']), _e(r['safety_low'])] for r in limits])}
        <p>表3.1-3 建造材料</p>
        {_table(['設備編號','材質類別','建造材料','設計規範','腐蝕裕度'],
            [[_e(r['equipment_id']), _e(r['material_category'] if 'material_category' in r.keys() else ''),
              _e(r['material']), _e(r['spec']), _e(r['corrosion_allowance'])] for r in mats])}
        <p>表3.1-6 釋壓</p>
        {_table(['設備編號','類型','設定壓力','排放量','P&amp;ID','釋放物CAS'],
            [[_e(r['equipment_id']), _e(r['device_type']), _e(r['set_pressure']),
              _e(r['design_capacity']), _e(r['pid_drawing_no'])+' '+_e(r['pid_revision']),
              _e(r['released_cas'])] for r in relief])}
        <p>表3.1-9 安全連鎖</p>
        {_table(['編號','設備編號','名稱','功能','方案','設定'],
            [[_e(r['interlock_id']), _e(r['equipment_id']), _e(r['name']),
              _e(r['function_desc']), _e(r['scenario_id']), _e(r['setpoint'])] for r in locks])}
        <p>化學反應資料（有反應式須記反應熱）</p>
        {rxn_tbl}
        <p>表3.2-1 危害性檢核（引用 Chemical）</p>
        {_table(['CAS','製程','火災','爆炸','毒性','PEL','閃火點'],
            [[_e(r['cas']), _e(r['process_id']), _yn(r['fire']), _yn(r['explosion']),
              _e(r['toxicity']), _e(r['pel_twa']), _e(r['flash_point'])] for r in hz])}
        <p>表3.2-2 相容性</p>
        {_table(['CAS','製程','設備','相容','說明'],
            [[_e(r['cas_a']), _e(r['process_id_a']), _e(r['equipment_id']),
              _yn(r['compatible']), _e(r['hazard_note'])] for r in cp])}
        <p>表3.2-3 處理方法</p>
        {_table(['CAS','製程','儲存','緊急'],
            [[_e(r['cas']), _e(r['process_id']), _e(r['storage_notes']), _e(r['emergency_notes'])] for r in hd])}
        <p>表3.1-5 防爆區域</p>
        {_table(['區域','CAS','製程','分級'],
            [[_e(r['area_code']), _e(r['cas']), _e(r['process_id']), _e(r['zone_class'])] for r in expl])}
        <p>表3.1-7 通風　表3.1-8 設計規範</p>
        {_table(['區域','通風類型','標準'], [[_e(r['area_code']), _e(r['vent_type']), _e(r['standard'])] for r in vent])}
        {_table(['製程','設備','項目','規範'],
            [[_e(r['process_id']), _e(r['equipment_id']), _e(r['item']), _e(r['code'])] for r in codes])}
        <p>3.1.3.9 法令證明：T-101 危險性設備檢查合格證。無控制系統／其他類型：已於場所聲明。管線系統以 PL-201 登錄，未虛構未有類型。</p>
        """,
        ["表3.1-1～3.1-9", "表3.2-1～3.2-3", "表3.1-4 P&ID 清單", "廠區位置圖 PLOT-001"],
    )

    meetings = _rows(conn, "SELECT * FROM meeting")
    signs = _rows(conn, "SELECT * FROM signoff")
    recs = _rows(conn, "SELECT * FROM recommendation")
    incidents = _rows(conn, "SELECT * FROM incident")
    esd_rows = _rows(
        conn,
        """SELECT s.*, GROUP_CONCAT(a.equipment_id) AS actions
           FROM esd_scenario s LEFT JOIN esd_action a ON a.scenario_id=s.scenario_id
           GROUP BY s.scenario_id""",
    )

    hazop_tbl = _table(
        ["節點", "製程", "設備編號", "CAS", "偏離", "後果", "防護", "S", "L", "等級", "stale"],
        [[
            _e(h["node_id"]), _e(h["process_id"]), _e(h["equipment_ids"]),
            _e(h["cas_list"]), _e(h["deviation"]), _e(h["cons_desc"]),
            _e(h["safeguards"]), _e(h["severity"]), _e(h["likelihood"]),
            _e(h["rank_label"]), _yn(h["stale"]),
        ] for h in hazop],
    )

    loc_note = ""
    if hazop:
        loc_note = (
            "<p>設置地點（area_code）、人為因素、控制失效已記於節點旗標；"
            "後果共用，禁止另造災害名。</p>"
        )

    ch2 = _chapter(
        2,
        f"""
        <p>評估 PHA-2026-001，方法 HAZOP，矩陣 {_e(MATRIX_VERSION)}。可接受線：{_e(MATRIX_ACCEPT_LINE)}。</p>
        <h5>HAZOP 工作表</h5>
        {hazop_tbl}
        {loc_note}
        <p>提示事項（不是風險分數；S／L 由小組填寫）</p>
        {_table(['階段','製程','設備','CAS','規則','內容','狀態'],
            [[_e(p['stage']), _e(p['process_id']), _e(p['equipment_id']), _e(p['cas']),
              _e(p['rule_id']), _e(p['message']), _e(p['status'])] for p in prompts])}
        <p>表3.2-4 簽認</p>
        {_table(['姓名','角色','合格人員'],
            [[_e(s['person_name']), _e(s['role']), _yn(s['qualified'])] for s in signs])}
        <p>表3.2-5 會議</p>
        {_table(['會議','評估','製程','日期','摘錄'],
            [[_e(m['meeting_id']), _e(m['assessment_id']), _e(m['process_id']),
              _e(m['meeting_date']), _e(m['notes'])] for m in meetings])}
        <p>改善建議（關閉須指主檔 PK＋主檔已更新＋重評或棄權）</p>
        {_table(['編號','對象表','PK','說明','已改善','主檔更新','重評/棄權','關閉'],
            [[_e(r['rec_id']), _e(r['target_table']), _e(r['target_pk']), _e(r['description']),
              _yn(r['marked_improved']), _yn(r['master_updated']),
              _yn(r['reassessed_or_waiver']), _yn(r['closed'])] for r in recs])}
        <p>表3.2-6 廠內及同業事故納入評估</p>
        {('本場所近五年事故 0 件；附空白格式。' if site['declare_no_incident_5y'] and not incidents
          else _table(['編號','製程','設備','摘要'],
              [[_e(i['incident_id']), _e(i['process_id']), _e(i['equipment_id']), _e(i['summary'])] for i in incidents]))}
        <p>緊急停車方案</p>
        {_table(['方案','製程','系統設備','啟動條件','動作設備'],
            [[_e(s['scenario_id']), _e(s['process_id']), _e(s['esd_equipment_id']),
              _e(s['trigger_conditions']), _e(s['actions'])] for s in esd_rows])}
        """,
        ["表3.2-4 簽認", "表3.2-5 會議", "HAZOP 工作表", "改善建議彙整", "表3.2-6 事故"],
    )

    acts = _rows(conn, "SELECT * FROM worker_activity")
    acc = _rows(conn, "SELECT * FROM info_access")
    ch3_exec = (
        _table(["活動","製程","類型","日期","說明"],
            [[_e(a['activity_id']), _e(a['process_id']), _e(a['activity_type']),
              _e(a['activity_date']), _e(a['description'])] for a in acts])
        + "<p>當年度勞工參與計畫附件：空。</p>"
        + _table(["製程","取得管道","知悉"],
            [[_e(a['process_id']), _e(a['channel']), _yn(a['known'])] for a in acc])
        if acts else "<p>本場所無此情形</p>"
    )
    ch3 = _chapter(3, ch3_exec, ["勞工參與執行紀錄", "資訊取得管道"])

    sops = _rows(
        conn,
        """SELECT s.*, p.name AS process_name
           FROM sop s JOIN process p ON p.process_id=s.process_id
           ORDER BY CASE s.op_kind WHEN 'equipment' THEN 1 ELSE 0 END, s.process_id, s.sop_id""",
    )
    ch4 = _chapter(
        4,
        "<p>製程操作 SOP 掛製程編號；機械設備操作 SOP 掛該製程下設備編號。</p>"
        + _table(["操作別","SOP編號","製程編號","製程名稱","設備編號","標題","程序編號","正文"],
            [[_e("機械設備操作" if s["op_kind"] == "equipment" else "製程操作"),
              _e(s['sop_id']), _e(s['process_id']), _e(s['process_name']),
              _e(s["equipment_id"] or "—"), _e(s['title']), _e(s['procedure_no']),
              "（正文空）"] for s in sops])
        + "<p>七階段操作正文空；工作安全衛生標準清單本示範未列。</p>",
        ["表3.4-1 SOP 清單"],
    )

    courses = _rows(
        conn,
        """SELECT c.*, p.name AS process_name FROM training_course c
           JOIN process p ON p.process_id=c.process_id
           ORDER BY CASE c.op_kind WHEN 'equipment' THEN 1 ELSE 0 END, c.process_id, c.course_id""",
    )
    trains = _rows(
        conn,
        """SELECT r.*, c.process_id, c.name AS course_name
           FROM training_record r JOIN training_course c ON c.course_id=r.course_id""",
    )
    ch5 = _chapter(
        5,
        _table(["操作別","課程","製程","製程名稱","設備編號","名稱","時數","對象"],
            [[_e("機械設備操作" if c["op_kind"] == "equipment" else "製程操作"),
              _e(c['course_id']), _e(c['process_id']), _e(c['process_name']),
              _e(c["equipment_id"] or "—"), _e(c['name']), _e(c['hours']), _e(c['audience'])] for c in courses])
        + _table(["紀錄","課程","學員","日期","測驗"],
            [[_e(t['record_id']), _e(t['course_id']), _e(t['trainee']), _e(t['train_date']), _yn(t['tested'])] for t in trains]),
        ["表3.5-1 初次課程", "訓練紀錄"],
    )

    incidents = _rows(
        conn,
        """SELECT c.incident_id, c.contractor_name, c.contract_period, c.incident_type,
                  c.linked_incident_id,
                  COALESCE(NULLIF(c.summary, ''), a.summary) AS summary,
                  COALESCE(c.occur_date, a.incident_date) AS occur_date,
                  COALESCE(c.process_id, a.process_id) AS process_id,
                  COALESCE(c.equipment_id, a.equipment_id) AS equipment_id,
                  COALESCE(NULLIF(c.corrective, ''), a.corrective) AS corrective
           FROM contractor_incident c
           LEFT JOIN incident a ON a.incident_id=c.linked_incident_id
           LEFT JOIN process p ON p.process_id=COALESCE(c.process_id, a.process_id)
           ORDER BY occur_date, c.incident_id""",
    )
    if incidents:
        ch6_exec = _table(
            ["項次", "承攬人", "期間", "日期", "類型", "摘要", "製程", "設備", "改善"],
            [
                [
                    _e(i["incident_id"]),
                    _e(i["contractor_name"]),
                    _e(i["contract_period"]),
                    _e(i["occur_date"]),
                    _e(i["incident_type"]),
                    _e(i["summary"]),
                    _e(i["process_id"]),
                    _e(i["equipment_id"]),
                    _e(i["corrective"]),
                ]
                for i in incidents
            ],
        )
        ch6_forms = ["表6.2-1 承攬職災／虛驚"]
    else:
        ch6_exec = "<p>有承攬但尚未登錄表6.2-1。</p>"
        ch6_forms = ["表6.2-1"]
    ch6 = _chapter(6, ch6_exec, ch6_forms)

    pssrs = _rows(conn, "SELECT * FROM pssr")
    ch7 = _chapter(
        7,
        _table(["PSSR","設備編號","製程","變更案","日期","發現"],
            [[_e(p['pssr_id']), _e(p['equipment_id']), _e(p['process_id']),
              _e(p['change_id']), _e(p['pssr_date']), _e(p['findings'])] for p in pssrs])
        if pssrs else "<p>本場所無此情形</p>",
        ["啟動前安全檢查紀錄"],
    )

    insp = _rows(conn, "SELECT * FROM inspection")
    screens = _rows(
        conn,
        """SELECT s.*, e.equipment_type, e.process_id,
                  CASE WHEN s.is_critical=1 AND f.run_hours>0
                       THEN ROUND(f.failure_count * 1000000.0 / f.run_hours, 2)
                       WHEN s.is_critical=1 AND f.equipment_id IS NOT NULL THEN NULL
                       ELSE NULL END AS failure_rate,
                  f.period_start, f.period_end, f.run_hours, f.failure_count,
                  f.note AS failure_note,f.confirmed AS failure_confirmed
           FROM mi_screen s
           JOIN equipment e ON e.equipment_id=s.equipment_id
           LEFT JOIN mi_failure f ON f.equipment_id=s.equipment_id
           ORDER BY s.equipment_id""",
    )
    mi_details = _rows(
        conn,
        """SELECT d.* FROM mi_inspection_detail d JOIN equipment e
           ON e.equipment_id=d.equipment_id ORDER BY d.equipment_id,d.detail_id""",
    )
    mi_categories = _rows(
        conn,
        """SELECT s.mi_type,SUM(f.failure_count) AS failures,SUM(f.run_hours) AS hours,
           ROUND(SUM(f.failure_count)*1000000.0/SUM(f.run_hours),4) AS rate
           FROM mi_failure f JOIN mi_screen s ON s.equipment_id=f.equipment_id
           WHERE s.is_critical=1 AND s.mi_type_confirmed=1 AND f.confirmed=1 AND f.run_hours>0
           GROUP BY s.mi_type ORDER BY s.mi_type""",
    )
    ch8 = _chapter(
        8,
        "<p>附表8.1-1 由完整設備清單逐台篩選。結果不回寫設備主檔。</p>"
        + _table(["設備編號","類型","製程","六大類","篩選","依據"],
            [[_e(s['equipment_id']), _e(s['equipment_type']), _e(s['process_id']),
              _e(s['mi_type']) if s['mi_type_confirmed'] else '待確認',
              _yn(s['is_critical']), _e(s['basis'])] for s in screens])
        + _table(["設備編號","損壞機制","功能檢查項目","檢驗","頻率","程序書","P&ID","確認"],
            [[_e(d['equipment_id']), _e(d['damage_mechanism']), _e(d['inspection_item']),
              _e(d['inspect_method']), _e(d['inspect_frequency']), _e(d['procedure_ref']),
              _e(d['pid_drawing_no']), '是' if d['confirmed'] else '待確認'] for d in mi_details])
        + "<p>附表8.2-1 僅列篩選為是者。失效率＝失效次數÷運行小時×1,000,000。</p>"
        + _table(["設備編號","統計期間","運行小時","失效次數","次／百萬小時","說明","確認"],
            [[_e(s['equipment_id']),
              f"{_e(s['period_start'])}～{_e(s['period_end'])}",
              _e(s['run_hours']), _e(s['failure_count']),
              _e(s['failure_rate']) if s['failure_rate'] is not None else "運行時間為 0 或不計算",
              _e(s['failure_note']), '已確認' if s['failure_confirmed'] else '待確認']
             for s in screens if s["is_critical"]])
        + _table(["六大類","總失效事件數","總運行小時","次／百萬小時"],
            [[_e(c['mi_type']),_e(c['failures']),_e(c['hours']),_e(c['rate'])] for c in mi_categories])
        + _table(["檢查","設備編號","日期","人員","方法","結果"],
            [[_e(i['inspection_id']), _e(i['equipment_id']), _e(i['inspect_date']),
              _e(i['inspector']), _e(i['method']), _e(i['result'])] for i in insp]),
        ["附表8.1-1 安全關鍵性篩選", "附表8.2-1 失效率", "檢查紀錄"],
    )

    zones = _rows(
        conn,
        """SELECT z.*, a.name AS area_name
           FROM hotwork_zone z JOIN area a ON a.area_code=z.area_code
           ORDER BY z.area_code""",
    )
    hot = _rows(conn, "SELECT * FROM hotwork_permit")
    ch9_exec = ""
    if zones:
        ch9_exec += _table(
            ["區域", "名稱", "防爆", "防爆說明", "防護原因"],
            [
                [
                    _e(z["area_code"]),
                    _e(z["area_name"]),
                    _yn(z["is_explosion_zone"]),
                    _e(z["explosion_note"]),
                    _e(z["protection_reason"]),
                ]
                for z in zones
            ],
        )
    if hot:
        ch9_exec += _table(
            ["許可", "設備編號", "區域", "日期", "措施"],
            [
                [
                    _e(h["permit_id"]),
                    _e(h["equipment_id"]),
                    _e(h["area_code"]),
                    _e(h["permit_date"]),
                    _e(h["measures"]),
                ]
                for h in hot
            ],
        )
    if not ch9_exec:
        ch9_exec = "<p>尚未列舉動火管制區域。</p>"
    ch9_forms = ["表9.1-1 動火許可區域", "動火許可紀錄"]
    ch9 = _chapter(9, ch9_exec, ch9_forms)

    chgs = _rows(conn, "SELECT * FROM change_request")
    ch10 = _chapter(
        10,
        _table(["變更案","被改表","PK","類型","狀態","已核准","說明"],
            [[_e(c['change_id']), _e(c['target_table']), _e(c['target_pk']),
              _e(c['change_type']), _e(c['status']), _yn(c['approved']), _e(c['description'])] for c in chgs]),
        ["表3.10-1 類型", "已核准變更申請單"],
    )

    ch11 = _chapter(
        11,
        "<p>本場所無此情形：近五年事故 0 件。空白調查報告格式如下（能掛則掛 process_id／equipment_id／cas）。</p>"
        + _table(["報告編號","日期","製程","設備","CAS","經過","基本原因"],
            [["（空白格式）", "", "", "", "", "", ""]])
        + _table(["類型","件數"], [["火災", "0"], ["爆炸", "0"], ["洩漏", "0"], ["虛驚", "0"]]),
        ["表3.11-1 近五年 0 件", "空白調查報告"],
    )

    org = conn.execute("SELECT * FROM emergency_org WHERE site_id=?", (site_id,)).fetchone()
    drills = _rows(conn, "SELECT * FROM drill")
    asm = [a for a in areas if a["is_assembly_point"]]
    ch12 = _chapter(
        12,
        f"<p>組織摘要：{_e(org['org_summary']) if org else ''}。應變中心：{_e(org['command_center']) if org else ''}。</p>"
        f"<p>集合點區域代碼：{', '.join(_e(a['area_code']) for a in asm) or '（未登錄）'}。</p>"
        + _table(["演練","製程","後果編號","日期","說明"],
            [[_e(d['drill_id']), _e(d['process_id']), _e(d['consequence_id']),
              _e(d['drill_date']), _e(d['notes'])] for d in drills])
        + "<p>緊急應變計劃全文空。</p>",
        ["組織摘要", "集合點區域", "表3.12-3 演練"],
    )

    plan = conn.execute("SELECT * FROM audit_plan WHERE site_id=?", (site_id,)).fetchone()
    checks = _rows(conn, "SELECT * FROM audit_checklist ORDER BY item_no")
    if plan and not plan["first_done"]:
        audit_exec = (
            f"<p>尚未第一次符合性稽核。預定實施日期：{_e(plan['planned_date'])}。{_e(plan['notes'])}</p>"
            + _table(["項次", "單元", "查核要點"],
                [[_e(c["item_no"]), _e(UNIT_TITLES.get(int(c["unit_no"] or 0), str(c["unit_no"]))), _e(c["prompt"])] for c in checks])
        )
    else:
        audit_exec = "<p>本場所無此情形</p>"
    ch13 = _chapter(13, audit_exec, ["表3.13-2 預定計畫", "表3.13-1 查核表骨架"])

    secrets = _rows(
        conn,
        """SELECT original_name FROM unstructured_attachment
           WHERE site_id=? AND kind='trade_secret' ORDER BY attachment_id""",
        (site_id,),
    )
    ch14 = _chapter(
        14,
        _table(["已上傳程序書"], [[_e(s['original_name'])] for s in secrets])
        if secrets else "<p>尚未上傳商業機密管理程序書。</p>",
        ["商業機密管理程序書"],
    )

    loads = _rows(conn, "SELECT * FROM loading_occupancy")
    load_html = (
        "<section><h2>裝卸佔用（非運輸主檔）</h2>"
        "<p>車牌只寫在裝卸佔用列，不新增 Equipment。</p>"
        + _table(["佔用","設備","製程","CAS","車牌或容器號","起","迄"],
            [[_e(l['occupancy_id']), _e(l['equipment_id']), _e(l['process_id']),
              _e(l['cas']), _e(l['plate_or_container']), _e(l['start_ts']), _e(l['end_ts'])] for l in loads])
        + "</section>"
    )

    appendix = """
    <section id="appendix-a">
      <h2>附錄 A　事業單位製程安全管理自我檢核</h2>
      <p>有結構化資料的題勾「已建立」；程序題一律「本階段從缺」。</p>
      <table>
        <thead><tr><th>項次</th><th>檢核要旨</th><th>結果</th></tr></thead>
        <tbody>
          <tr><td>1.1</td><td>製程安全資訊管理程序</td><td>本階段從缺</td></tr>
          <tr><td>1.2–1.5</td><td>三塊主檔、存量、上下限、材料、P&amp;ID、釋壓、連鎖、三種檢核</td><td>已建立</td></tr>
          <tr><td>2.1</td><td>製程安全評估管理程序</td><td>本階段從缺</td></tr>
          <tr><td>2.3–2.4</td><td>HAZOP 節點、防護、簽認、會議、改善</td><td>已建立</td></tr>
          <tr><td>3.1</td><td>勞工參與計畫全文</td><td>本階段從缺</td></tr>
          <tr><td>3.x</td><td>勞工參與活動掛製程</td><td>已建立</td></tr>
          <tr><td>4.x</td><td>SOP 清單掛製程；七階段正文</td><td>清單已建立；正文本階段從缺</td></tr>
          <tr><td>5.x</td><td>課程掛製程及已訓紀錄</td><td>已建立</td></tr>
          <tr><td>6.x</td><td>承攬</td><td>表6.2-1 已建立</td></tr>
          <tr><td>7.x</td><td>PSSR 掛設備／變更製程；程序</td><td>紀錄已建立；程序本階段從缺</td></tr>
          <tr><td>8.x</td><td>分類清單與主檔同一編號；檢查；腐蝕表</td><td>清單與檢查已建立；腐蝕本階段從缺</td></tr>
          <tr><td>9.x</td><td>動火</td><td>表9.1-1 已建立</td></tr>
          <tr><td>10.x</td><td>變更指明被改 PK</td><td>已建立</td></tr>
          <tr><td>11.x</td><td>事故調查程序</td><td>本階段從缺；近五年 0 件＋空白格式已建立</td></tr>
          <tr><td>12.x</td><td>應變計劃全文</td><td>本階段從缺；組織／集合點／演練已建立</td></tr>
          <tr><td>13.x</td><td>尚未第一次稽核</td><td>預定計畫已建立</td></tr>
          <tr><td>14.x</td><td>機密清單指回製程／圖號</td><td>已建立；協議本階段從缺</td></tr>
        </tbody>
      </table>
    </section>
    """

    css = """
    body { font-family: "Iwanami Mincho","PMingLiU","Noto Serif TC", serif; margin: 24px; color: #111; }
    h1 { font-size: 1.8rem; margin-bottom: 0.2rem; }
    h2 { border-bottom: 1px solid #333; padding-bottom: 4px; margin-top: 2rem; }
    h4 { margin-bottom: 0.3rem; }
    table { border-collapse: collapse; width: 100%; font-size: 0.85rem; margin: 0.6rem 0 1rem; }
    th, td { border: 1px solid #444; padding: 4px 6px; vertical-align: top; }
    th { background: #eee; }
    .empty-proc { color: #444; font-style: italic; }
    .meta th { width: 10rem; }
    .toc ol { columns: 2; }
    @media print { nav.toc { page-break-after: always; } section { page-break-inside: avoid; } }
    """
    return (
        "<!DOCTYPE html><html lang='zh-Hant'><head><meta charset='utf-8'>"
        f"<title>PSM 十四章申報報告</title><style>{css}</style></head><body>"
        f"{cover}{toc}{master}{drawing}{ch1}{ch2}{ch3}{ch4}{ch5}{ch6}{ch7}{ch8}"
        f"{ch9}{ch10}{ch11}{ch12}{ch13}{ch14}{load_html}{appendix}"
        "</body></html>"
    )
