(function () {
  "use strict";
  function el(id) { return document.getElementById(id); }
  var form = el("flow-save"), canvas = el("flow-canvas"), seed = el("flow-seed");
  if (!form || !canvas || !seed) return;

  var stage = canvas.parentElement;
  var processId = el("block-process").value;
  var eqSelect = el("flow-eq"), processSelect = el("flow-next-proc");
  var nodes = [];
  try {
    JSON.parse(seed.textContent || "[]").forEach(function (row) {
      if (!row || (!row.name && !row.equipment_id && !row.desc)) return;
      var seq = String(row.seq || nodes.length + 1);
      var x = row.x === "" || row.x == null ? 24 + (Number(seq) - 1) * 220 : Number(row.x);
      var y = row.y === "" || row.y == null ? 36 : Number(row.y);
      nodes.push({
        seq: seq, name: row.name || "", equipment_id: row.equipment_id || "",
        desc: row.desc || "", next: row.next ? String(row.next) : "",
        next_process_id: row.next_process_id || "",
        branch_from: row.branch_from ? String(row.branch_from) : "",
        x: isFinite(x) ? x : 24, y: isFinite(y) ? y : 36
      });
    });
  } catch (error) { nodes = []; }

  var original = JSON.stringify(nodes);
  var selected = nodes.length ? nodes[0].seq : "";
  var modified = false, saving = false, navigating = false, drag = null;
  var isDraft = form.getAttribute("data-draft") === "1";
  var NODE_WIDTH = 184;
  var editor = form.querySelector(".flow-inspector");

  function current() { return nodes.find(function (n) { return n.seq === selected; }); }
  function eqLabel(id) {
    var option = Array.from(eqSelect.options).find(function (item) { return item.value === id; });
    return option ? option.textContent.trim() : id;
  }
  function processLabel(id) {
    var option = Array.from(processSelect.options).find(function (item) { return item.value === id; });
    return option ? option.textContent.trim() : id;
  }
  function updateStatus() {
    var status = el("flow-status");
    status.textContent = modified ? "有未儲存變更" : (isDraft ? "預設方塊尚未儲存" : "目前為已儲存版本");
    status.classList.toggle("flow-status-dirty", modified || isDraft);
    el("flow-reset").hidden = !modified;
    el("flow-count").textContent = " · " + nodes.length + "/15 個步驟";
    el("flow-new").disabled = nodes.length >= 15;
  }
  function changed() { modified = true; updateStatus(); }
  function addOption(select, value, label) {
    var option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }
  function fillChoices(select, emptyLabel, choices, value) {
    select.innerHTML = "";
    addOption(select, "", emptyLabel);
    choices.forEach(function (choice) { addOption(select, choice.value, choice.label); });
    select.value = value || "";
  }
  function renderInspector() {
    var node = current();
    el("flow-create").hidden = !!node;
    el("flow-edit").hidden = !node;
    el("flow-panel-title").textContent = node ? "編輯步驟 " + node.seq : "新增步驟";
    el("flow-panel-help").textContent = node
      ? "修改後請按「儲存流程方塊」。"
      : "加入方塊後，可再設定與其他步驟的連接。";
    if (!node) return;
    el("flow-edit-name").value = node.name;
    el("flow-edit-desc").value = node.desc;
    var editEq = el("flow-edit-eq");
    editEq.innerHTML = "";
    Array.from(eqSelect.options).forEach(function (option) {
      if (!option.value || option.getAttribute("data-process") === processId) {
        editEq.appendChild(option.cloneNode(true));
      }
    });
    if (node.equipment_id && !Array.from(editEq.options).some(function (o) { return o.value === node.equipment_id; })) {
      addOption(editEq, node.equipment_id, node.equipment_id + "（原設備）");
    }
    editEq.value = node.equipment_id;
    var others = nodes.filter(function (n) { return n.seq !== node.seq; })
      .map(function (n) { return { value: n.seq, label: n.seq + " " + (n.name || "未命名") }; });
    fillChoices(el("flow-edit-next"), "無", others, node.next);
    fillChoices(el("flow-edit-branch"), "無", others, node.branch_from);
    var processes = Array.from(processSelect.options).filter(function (o) { return o.value; })
      .map(function (o) { return { value: o.value, label: o.textContent.trim() }; });
    fillChoices(el("flow-edit-process"), "無", processes, node.next_process_id);
  }
  function syncFields() {
    var box = el("flow-fields");
    box.innerHTML = "";
    nodes.forEach(function (n) {
      var fields = {
        seq: n.seq, name: n.name, equipment_id: n.equipment_id, desc: n.desc,
        next: n.next, next_process: n.next_process_id, branch_from: n.branch_from,
        x: String(Math.round(n.x)), y: String(Math.round(n.y))
      };
      Object.keys(fields).forEach(function (key) {
        var input = document.createElement("input");
        input.type = "hidden";
        input.name = key + "_" + n.seq;
        input.value = fields[key] || "";
        box.appendChild(input);
      });
    });
  }
  function point(element, side) {
    var b = element.getBoundingClientRect(), c = canvas.getBoundingClientRect();
    return {
      x: (side === "left" ? b.left : side === "right" ? b.right : b.left + b.width / 2) - c.left,
      y: (side === "top" ? b.top : side === "bottom" ? b.bottom : b.top + b.height / 2) - c.top
    };
  }
  function drawLinks() {
    var svg = canvas.querySelector("svg");
    if (!svg) return;
    svg.innerHTML = '<defs><marker id="flow-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#1f4d3a"/></marker><marker id="flow-arrow-exit" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#235f83"/></marker><marker id="flow-arrow-branch" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#896a2d"/></marker></defs>';
    nodes.forEach(function (n) {
      var from = canvas.querySelector('.flow-node[data-seq="' + n.seq + '"] .flow-port');
      var target = n.next
        ? canvas.querySelector('.flow-node[data-seq="' + n.next + '"]')
        : canvas.querySelector('.flow-exit[data-source="' + n.seq + '"]');
      if (!from || !target || (!n.next && !n.next_process_id)) return;
      var a = point(from, "center"), b = point(target, "left");
      var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      var bend = Math.max(24, Math.abs(b.x - a.x) / 2);
      path.setAttribute("d", "M" + a.x + "," + a.y + " C" + (a.x + bend) + "," + a.y + " " + (b.x - bend) + "," + b.y + " " + b.x + "," + b.y);
      path.setAttribute("class", n.next ? "flow-link-main" : "flow-link-process");
      path.setAttribute("marker-end", n.next ? "url(#flow-arrow)" : "url(#flow-arrow-exit)");
      svg.appendChild(path);
    });
    nodes.forEach(function (n) {
      if (!n.branch_from) return;
      var source = canvas.querySelector('.flow-node[data-seq="' + n.branch_from + '"]');
      var target = canvas.querySelector('.flow-node[data-seq="' + n.seq + '"]');
      if (!source || !target) return;
      var a = point(source, "bottom"), b = point(target, "top");
      var bend = Math.max(20, Math.abs(b.y - a.y) / 2);
      var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", "M" + a.x + "," + a.y + " C" + a.x + "," + (a.y + bend) + " " + b.x + "," + (b.y - bend) + " " + b.x + "," + b.y);
      path.setAttribute("class", "flow-link-branch");
      path.setAttribute("marker-end", "url(#flow-arrow-branch)");
      svg.appendChild(path);
    });
  }
  function renderCanvas() {
    canvas.innerHTML = "";
    var right = nodes.reduce(function (m, n) { return Math.max(m, n.x + NODE_WIDTH); }, 0);
    var bottom = nodes.reduce(function (m, n) { return Math.max(m, n.y + 150); }, 0);
    var hasExits = nodes.some(function (n) { return n.next_process_id && !n.next; });
    var exitX = right + 70;
    canvas.style.width = Math.max(stage.clientWidth - 2, right + 32, hasExits ? exitX + 190 : 0) + "px";
    canvas.style.height = Math.max(340, bottom + 28) + "px";
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("width", canvas.style.width);
    svg.setAttribute("height", canvas.style.height);
    svg.setAttribute("aria-hidden", "true");
    canvas.appendChild(svg);
    if (!nodes.length) {
      var empty = document.createElement("p");
      empty.className = "flow-empty";
      empty.textContent = "尚無步驟。按「新增步驟」開始建立流程圖。";
      canvas.appendChild(empty);
    }
    nodes.forEach(function (n) {
      var box = document.createElement("div");
      box.className = "flow-node" + (selected === n.seq ? " selected" : "");
      box.setAttribute("data-seq", n.seq);
      box.setAttribute("role", "button");
      box.setAttribute("tabindex", "0");
      box.setAttribute("aria-label", "編輯步驟 " + n.seq + " " + (n.name || "未命名"));
      box.setAttribute("aria-pressed", selected === n.seq ? "true" : "false");
      box.style.left = n.x + "px";
      box.style.top = n.y + "px";
      var head = document.createElement("div");
      head.className = "flow-node-h";
      var number = document.createElement("span");
      number.className = "flow-node-number";
      number.textContent = n.seq;
      var name = document.createElement("strong");
      name.textContent = n.name || "未命名步驟";
      head.appendChild(number);
      head.appendChild(name);
      var body = document.createElement("div");
      body.className = "flow-node-b";
      var summary = document.createElement("div");
      summary.className = "flow-node-summary";
      summary.textContent = n.equipment_id ? eqLabel(n.equipment_id) : (n.desc || "未指定設備");
      summary.title = summary.textContent;
      body.appendChild(summary);
      var foot = document.createElement("div");
      foot.className = "flow-node-foot";
      if (n.next) foot.textContent = "→ 步驟 " + n.next;
      else if (n.next_process_id) foot.textContent = "→ " + processLabel(n.next_process_id);
      else foot.textContent = "流程終點";
      body.appendChild(foot);
      if (n.branch_from) {
        var branch = document.createElement("span");
        branch.className = "flow-branch-badge";
        branch.textContent = "從步驟 " + n.branch_from + " 分出";
        body.appendChild(branch);
      }
      var port = document.createElement("div");
      port.className = "flow-port";
      port.title = "拖到下一個步驟以連接";
      port.setAttribute("aria-hidden", "true");
      box.appendChild(head);
      box.appendChild(body);
      box.appendChild(port);
      canvas.appendChild(box);
      box.addEventListener("click", function () { selected = n.seq; render(); if (window.innerWidth < 900) editor.scrollIntoView({ block: "start", behavior: "smooth" }); });
      box.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selected = n.seq; render(); editor.scrollIntoView({ block: "nearest" }); }
      });
      box.addEventListener("mousedown", function (event) {
        if (event.target === port || event.button !== 0) return;
        selected = n.seq;
        drag = { mode: "move", node: n, x: event.clientX, y: event.clientY, fromX: n.x, fromY: n.y };
        event.preventDefault();
      });
      port.addEventListener("mousedown", function (event) {
        if (event.button !== 0) return;
        drag = { mode: "link", node: n };
        event.preventDefault();
        event.stopPropagation();
      });
    });
    nodes.forEach(function (n) {
      if (!n.next_process_id || n.next) return;
      var exit = document.createElement("div");
      exit.className = "flow-exit";
      exit.setAttribute("data-source", n.seq);
      exit.style.left = exitX + "px";
      exit.style.top = Math.max(18, n.y + 38) + "px";
      exit.textContent = "下一製程 · " + processLabel(n.next_process_id);
      canvas.appendChild(exit);
    });
    drawLinks();
    syncFields();
    updateStatus();
  }
  function render() { renderCanvas(); renderInspector(); }

  document.addEventListener("mousemove", function (event) {
    if (!drag || drag.mode !== "move") return;
    drag.node.x = Math.max(8, drag.fromX + event.clientX - drag.x);
    drag.node.y = Math.max(8, drag.fromY + event.clientY - drag.y);
    var box = canvas.querySelector('.flow-node[data-seq="' + drag.node.seq + '"]');
    if (box) { box.style.left = drag.node.x + "px"; box.style.top = drag.node.y + "px"; }
    drawLinks();
  });
  document.addEventListener("mouseup", function (event) {
    if (!drag) return;
    if (drag.mode === "link") {
      var target = event.target.closest ? event.target.closest(".flow-node") : null;
      var seq = target ? target.getAttribute("data-seq") : "";
      if (seq && seq !== drag.node.seq && drag.node.next !== seq) {
        drag.node.next = seq;
        drag.node.next_process_id = "";
        var targetNode = nodes.find(function (n) { return n.seq === seq; });
        if (targetNode) targetNode.branch_from = "";
        changed();
      }
    } else if (drag.node.x !== drag.fromX || drag.node.y !== drag.fromY) changed();
    drag = null;
    render();
  });

  el("flow-new").addEventListener("click", function () {
    if (nodes.length >= 15) return;
    selected = "";
    render();
    editor.scrollIntoView({ block: "nearest", behavior: "smooth" });
    el("flow-name").focus();
  });
  el("flow-add").addEventListener("click", function () {
    var name = el("flow-name").value.trim();
    var equipment = eqSelect.value;
    if (!name && equipment) {
      var option = eqSelect.options[eqSelect.selectedIndex];
      name = option.getAttribute("data-name") || equipment;
    }
    var error = el("flow-create-error");
    if (!name) {
      error.textContent = "請填步驟名稱或選擇設備。";
      error.hidden = false;
      el("flow-name").focus();
      return;
    }
    if (nodes.length >= 15) return;
    error.hidden = true;
    var used = new Set(nodes.map(function (n) { return n.seq; }));
    var seq = "";
    for (var i = 1; i <= 15; i++) if (!used.has(String(i))) { seq = String(i); break; }
    var last = nodes.reduce(function (m, n) { return Math.max(m, n.x); }, -196);
    nodes.push({
      seq: seq, name: name, equipment_id: equipment, desc: el("flow-desc").value.trim(),
      next: "", next_process_id: processSelect.value, branch_from: "",
      x: Math.max(24, last + 220), y: 36
    });
    el("flow-name").value = ""; eqSelect.value = ""; el("flow-desc").value = ""; processSelect.value = "";
    selected = seq;
    changed();
    render();
  });
  eqSelect.addEventListener("change", function () {
    if (!eqSelect.value || el("flow-name").value.trim()) return;
    var option = eqSelect.options[eqSelect.selectedIndex];
    el("flow-name").value = option.getAttribute("data-name") || "";
  });
  el("flow-edit-name").addEventListener("input", function () {
    var n = current(); if (!n) return;
    n.name = this.value; changed(); renderCanvas();
  });
  el("flow-edit-desc").addEventListener("input", function () {
    var n = current(); if (!n) return;
    n.desc = this.value; changed(); renderCanvas();
  });
  el("flow-edit-eq").addEventListener("change", function () {
    var n = current(); if (!n) return;
    n.equipment_id = this.value; changed(); renderCanvas();
  });
  el("flow-edit-next").addEventListener("change", function () {
    var n = current(); if (!n) return;
    n.next = this.value;
    if (n.next) n.next_process_id = "";
    changed(); render();
  });
  el("flow-edit-process").addEventListener("change", function () {
    var n = current(); if (!n) return;
    n.next_process_id = this.value;
    if (n.next_process_id) n.next = "";
    changed(); render();
  });
  el("flow-edit-branch").addEventListener("change", function () {
    var n = current(); if (!n) return;
    n.branch_from = this.value; changed(); render();
  });
  el("flow-clear").addEventListener("click", function () {
    var n = current(); if (!n) return;
    n.next = ""; n.next_process_id = ""; n.branch_from = "";
    changed(); render();
  });
  el("flow-delete").addEventListener("click", function () {
    var n = current(); if (!n || !window.confirm("刪除「" + (n.name || "未命名步驟") + "」？")) return;
    nodes = nodes.filter(function (item) { return item.seq !== n.seq; });
    nodes.forEach(function (item) {
      if (item.next === n.seq) item.next = "";
      if (item.branch_from === n.seq) item.branch_from = "";
    });
    selected = nodes.length ? nodes[0].seq : "";
    changed(); render();
  });
  el("flow-arrange").addEventListener("click", function () {
    var main = nodes.filter(function (n) { return !n.branch_from; })
      .sort(function (a, b) { return Number(a.seq) - Number(b.seq); });
    main.forEach(function (n, i) { n.x = 24 + i * 238; n.y = 34; });
    var branches = nodes.filter(function (n) { return n.branch_from; })
      .sort(function (a, b) { return Number(a.seq) - Number(b.seq); });
    branches.forEach(function (n, i) {
      var source = nodes.find(function (item) { return item.seq === n.branch_from; });
      n.x = source ? source.x : 24 + i * 238;
      n.y = 220 + i * 170;
    });
    changed(); render();
  });
  el("flow-reset").addEventListener("click", function () {
    nodes = JSON.parse(original);
    selected = nodes.length ? nodes[0].seq : "";
    modified = false;
    render();
  });
  form.addEventListener("submit", function () {
    saving = true;
    syncFields();
    el("flow-status").textContent = "儲存中…";
  });
  var loadForm = el("flow-load");
  if (loadForm) loadForm.addEventListener("submit", function (event) {
    if (!modified) return;
    if (!window.confirm("流程方塊尚未儲存。確定切換製程？")) {
      event.preventDefault();
      loadForm.elements.block_process.value = processId;
    } else navigating = true;
  });
  window.addEventListener("beforeunload", function (event) {
    if (!modified || saving || navigating) return;
    event.preventDefault();
    event.returnValue = "";
  });
  window.addEventListener("resize", renderCanvas);
  render();
})();
