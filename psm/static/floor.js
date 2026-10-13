(() => {
  const dataEl = document.getElementById("floor-data");
  const svg = document.getElementById("plant-map");
  const panel = document.getElementById("side-panel");
  const chipBar = document.getElementById("process-chips");
  if (!dataEl || !svg || !panel) return;

  const state = {
    data: JSON.parse(dataEl.textContent),
    processId: new URLSearchParams(location.search).get("process") || "",
    areaCode: "",
    equipmentId: "",
    consequenceId: "",
  };

  const rankOf = (s, l) => {
    const v = s * l;
    if (v <= 4) return "低";
    if (v <= 9) return "中";
    if (v <= 16) return "高";
    return "極高";
  };

  const icon = (kind) => {
    if (kind === "tank") return '<rect x="-18" y="-22" width="36" height="44" rx="8" class="eq-hit"/>';
    if (kind === "pump") return '<circle r="18" class="eq-hit"/>';
    if (kind === "relief") return '<polygon points="0,-20 18,16 -18,16" class="eq-hit"/>';
    if (kind === "esd") return '<polygon points="0,-20 20,0 0,20 -20,0" class="eq-hit"/>';
    if (kind === "scrub") return '<rect x="-12" y="-26" width="24" height="52" rx="4" class="eq-hit"/>';
    if (kind === "loading") return '<rect x="-22" y="-10" width="44" height="20" rx="6" class="eq-hit"/>';
    return '<circle r="16" class="eq-hit"/>';
  };

  const operable = (eq) => {
    if (state.processId && eq.process_id !== state.processId) return false;
    if (state.areaCode && eq.area_code !== state.areaCode) return false;
    return true;
  };

  const byId = () => Object.fromEntries(state.data.equipment.map((e) => [e.equipment_id, e]));

  const setProcess = (id) => {
    state.processId = id;
    if (state.equipmentId) {
      const eq = byId()[state.equipmentId];
      if (eq && !operable(eq)) {
        state.equipmentId = "";
        state.consequenceId = "";
      }
    }
    const u = new URL(location.href);
    if (id) u.searchParams.set("process", id);
    else u.searchParams.delete("process");
    history.replaceState(null, "", u.pathname + u.search);
    draw();
  };

  function renderChips() {
    chipBar.innerHTML = "";
    const mk = (id, label) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip" + (state.processId === id ? " on" : "");
      b.dataset.process = id;
      b.textContent = label;
      b.addEventListener("click", () => setProcess(id));
      chipBar.appendChild(b);
    };
    mk("", "全部製程");
    for (const p of state.data.processes) mk(p.process_id, `${p.process_id} ${p.name}`);
  }

  function draw() {
    renderChips();
    const ns = [];
    for (const a of state.data.areas) {
      const on = state.areaCode === a.area_code ? " on" : "";
      const asm = a.is_assembly_point ? " · 集合點" : "";
      ns.push(`<g class="area-g${on}" data-area="${a.area_code}">
        <rect class="area-box" x="${a.x}" y="${a.y}" width="${a.w}" height="${a.h}" rx="10"/>
        <text class="area-label" x="${a.x + 16}" y="${a.y + 28}">${a.area_code} ${a.name}${asm}</text>
      </g>`);
    }
    for (const e of state.data.equipment) {
      const can = operable(e);
      const dim = can ? "" : " dim";
      const sel = e.equipment_id === state.equipmentId ? " selected" : "";
      ns.push(`<g class="eq-g rank-${e.max_rank_label}${dim}${sel}" data-eq="${e.equipment_id}" data-process="${e.process_id}" data-area="${e.area_code}" transform="translate(${e.x},${e.y})">
        ${icon(e.kind)}
        <text class="eq-id" y="-32">${e.equipment_id}</text>
      </g>`);
    }
    svg.innerHTML = ns.join("");
    svg.querySelectorAll(".area-g").forEach((g) => {
      g.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const code = g.getAttribute("data-area");
        state.areaCode = state.areaCode === code ? "" : code;
        draw();
      });
    });
    svg.querySelectorAll(".eq-g").forEach((g) => {
      g.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const id = g.getAttribute("data-eq");
        const eq = byId()[id];
        if (!eq || !operable(eq)) return;
        state.equipmentId = id;
        state.consequenceId = "";
        draw();
      });
    });
    renderPanel();
  }

  function nodesFor(eqId) {
    return state.data.nodes.filter((n) => n.equipment_ids.includes(eqId));
  }

  function renderMatrix(cons) {
    if (!cons) {
      return `<p class="muted">先在上方選一個後果，再點格子寫入嚴重度×可能性。</p>`;
    }
    const blocked = !state.data.masters_ok;
    const why = blocked ? `<p class="err">核心資料表未完備，矩陣關閉：${(state.data.masters_reasons || []).join("；")}</p>` : "";
    let html = `${why}<p class="muted">${state.data.matrix_version}　${state.data.accept_line}</p>
      <table class="matrix"><thead><tr><th></th>`;
    for (let l = 1; l <= 5; l++) html += `<th>L${l}</th>`;
    html += `</tr></thead><tbody>`;
    for (let s = 5; s >= 1; s--) {
      html += `<tr><th>S${s}</th>`;
      for (let l = 1; l <= 5; l++) {
        const lab = rankOf(s, l);
        const on = cons.severity === s && cons.likelihood === l ? " cell-on" : "";
        html += `<td class="cell-${lab}${on}"><button type="button" data-s="${s}" data-l="${l}" ${blocked ? "disabled" : ""}>${lab}</button></td>`;
      }
      html += `</tr>`;
    }
    html += `</tbody></table>`;
    return html;
  }

  function renderProcessPanel(proc) {
    const eqs = state.data.equipment.filter((e) => e.process_id === proc.process_id);
    const chems = state.data.chemicals.filter((c) => c.process_id === proc.process_id);
    const gaps = state.data.coverage[proc.process_id] || [];
    const esd = (state.data.esd[proc.process_id] || {}).label || "";
    let html = `<h3>${proc.process_id}　${proc.name}</h3>
      <p><a href="/processes/${proc.process_id}">打開完整檢視（SOP／訓練／設備）</a></p>
      <h4>設備</h4>`;
    if (!eqs.length) html += `<p class="muted">此製程尚無設備</p>`;
    for (const e of eqs) {
      html += `<button type="button" class="cons-btn" data-eq="${e.equipment_id}">${e.equipment_id}　${e.name}　${e.area_code}</button>`;
    }
    html += `<h4>化學品（CAS）</h4>
      <p>${chems.map((c) => `<span class="tag">${c.cas}</span>`).join(" ") || "（無）"}</p>
      <h4>涵蓋檢查（尚未進節點）</h4>
      <p>${gaps.length ? gaps.join("、") : "無缺漏"}</p>
      <p class="muted">${esd}</p>`;
    panel.innerHTML = html;
    panel.querySelectorAll("[data-eq]").forEach((b) => {
      b.addEventListener("click", () => {
        state.equipmentId = b.getAttribute("data-eq");
        state.consequenceId = "";
        draw();
      });
    });
  }

  function renderPanel() {
    if (state.processId && !state.equipmentId) {
      const proc = state.data.processes.find((p) => p.process_id === state.processId);
      if (proc) {
        renderProcessPanel(proc);
        return;
      }
    }
    const eq = byId()[state.equipmentId];
    if (!eq) {
      panel.innerHTML = `<p class="muted">點製程卡片篩選並打開該製程摘要；點區域篩該區；點設備編號看部門與評分。選製程 <code>P-TANK</code> 時，裝卸設備 <code>LA-101</code> 會變淡且不可操作。</p>`;
      return;
    }
    const chems = state.data.chemicals.filter((c) => c.process_id === eq.process_id);
    const occ = state.data.occupancy.filter((o) => o.equipment_id === eq.equipment_id);
    const gaps = state.data.coverage[eq.process_id] || [];
    const esd = (state.data.esd[eq.process_id] || {}).label || "";
    const proc = state.data.processes.find((p) => p.process_id === eq.process_id);
    const nodes = nodesFor(eq.equipment_id);
    let html = `<h3>${eq.equipment_id}　${eq.name}</h3>
      <p>製程 <strong>${eq.process_id}</strong> ${eq.process_name}
      · <a href="/processes/${eq.process_id}">製程檢視</a><br>
      操作權責 ${eq.operating_dept_id} ${eq.operating_dept_name}<br>
      維護權責 ${eq.maint_dept_id} ${eq.maint_dept_name}</p>
      <p>類型 ${eq.equipment_type}${eq.power_kind ? "／" + eq.power_kind : ""}　操作分類 ${eq.phase_class}<br>
      區域 ${eq.area_code}　安全關鍵 ${eq.is_safety_critical ? "是" : "否"}　風險圖示 ${eq.max_rank_label}</p>
      <h4>該製程化學品（CAS）</h4>
      <p>${chems.map((c) => `<span class="tag">${c.cas}</span>`).join(" ") || "（無）"}</p>`;
    if (occ.length) {
      html += `<h4>裝卸佔用（車牌不新增設備）</h4>` + occ.map((o) => `<p>${o.plate_or_container}　${o.cas}　${o.start_ts}</p>`).join("");
    }
    html += `<h4>涵蓋檢查（${eq.process_id} 尚未進節點）</h4><p>${gaps.length ? gaps.join("、") : "無缺漏"}</p>`;
    html += `<p class="muted">${esd}</p>`;
    html += `<h4>HAZOP 節點／後果／防護</h4>`;
    if (!nodes.length) html += `<p class="muted">此設備尚未進入任何節點。</p>`;
    for (const n of nodes) {
      html += `<p><strong>${n.node_id}</strong> ${n.deviation}　設備 ${n.equipment_ids.join(", ")}　CAS ${n.cas_list.join(", ")}</p>`;
      for (const c of n.consequences) {
        const on = c.consequence_id === state.consequenceId ? " on" : "";
        const sg = (c.safeguards || []).map((s) => s.equipment_id || s.scenario_id || s.sop_id).join(", ");
        html += `<button type="button" class="cons-btn${on}" data-cons="${c.consequence_id}">${c.consequence_id}　${c.rank_label || "未評"}　S${c.severity || "–"}×L${c.likelihood || "–"}${c.stale ? "　stale" : ""}<br><span>${c.description}</span>${sg ? "<br>防護 " + sg : ""}</button>`;
      }
    }
    const cons = nodes.flatMap((n) => n.consequences).find((c) => c.consequence_id === state.consequenceId);
    html += `<h4>風險矩陣（點格子寫回）</h4>${renderMatrix(cons)}`;
    html += `<h4>在此設備開節點</h4>`;
    if (!proc || !proc.assessment_id) {
      html += `<p class="err">此製程尚無評估</p>`;
    } else {
      html += `<p class="muted">偏離晶片會把設備編號 ${eq.equipment_id} 寫進節點，不手打名稱。</p><div class="chips" id="dev-chips">`;
      for (const d of state.data.deviations) {
        html += `<button type="button" class="chip" data-dev="${d}">${d}</button>`;
      }
      html += `</div>`;
    }
    html += `<p id="panel-msg" class="muted"></p>`;
    panel.innerHTML = html;
    panel.querySelectorAll(".cons-btn").forEach((b) => {
      b.addEventListener("click", () => {
        state.consequenceId = b.getAttribute("data-cons");
        draw();
      });
    });
    panel.querySelectorAll(".matrix button").forEach((b) => {
      b.addEventListener("click", () => postScore(+b.dataset.s, +b.dataset.l));
    });
    panel.querySelectorAll("#dev-chips .chip").forEach((b) => {
      b.addEventListener("click", () => postNode(b.getAttribute("data-dev")));
    });
  }

  async function postScore(severity, likelihood) {
    const msg = document.getElementById("panel-msg");
    if (!state.consequenceId) {
      if (msg) msg.textContent = "請先選後果";
      return;
    }
    const r = await fetch("/api/score", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ consequence_id: state.consequenceId, severity, likelihood }),
    });
    const data = await r.json();
    if (!r.ok) {
      if (msg) msg.textContent = data.error || "評分失敗";
      return;
    }
    state.data = data;
    draw();
  }

  async function postNode(deviation) {
    const msg = document.getElementById("panel-msg");
    const r = await fetch("/api/node", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        equipment_id: state.equipmentId,
        deviation,
        process_id: state.processId || undefined,
      }),
    });
    const data = await r.json();
    if (!r.ok) {
      if (msg) msg.textContent = data.error || "無法開節點";
      return;
    }
    state.data = data;
    state.consequenceId = data.created_consequence_id || "";
    draw();
  }

  draw();
})();
