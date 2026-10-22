(function () {
  function byId(id) {
    return document.getElementById(id);
  }
  function hazardTokens(value) {
    return (String(value || "").match(/\bH\d{3}[A-Z]?\b/gi) || []).map(function (code) {
      return code.toUpperCase();
    });
  }
  function refreshHazardPicker(widget, loadValue) {
    if (!widget) return;
    var hidden = widget.querySelector(".hazard-codes");
    var extra = widget.querySelector(".hazard-extra");
    var checks = Array.prototype.slice.call(widget.querySelectorAll(".hazard-option input[type=checkbox]"));
    if (!hidden || !extra) return;
    if (loadValue) {
      var wanted = hazardTokens(hidden.value);
      var known = {};
      checks.forEach(function (check) {
        var code = check.value.toUpperCase();
        check.checked = wanted.indexOf(code) >= 0;
        if (check.checked) known[code] = true;
      });
      extra.value = wanted.filter(function (code) { return !known[code]; }).join(", ");
    }
    var selected = checks.filter(function (check) { return check.checked; });
    var extras = hazardTokens(extra.value);
    var allCodes = [];
    selected.forEach(function (check) { allCodes.push(check.value.toUpperCase()); });
    extras.forEach(function (code) { if (allCodes.indexOf(code) < 0) allCodes.push(code); });
    hidden.value = allCodes.join(",");

    var selectedBox = widget.querySelector(".hazard-selected");
    if (selectedBox) {
      selectedBox.replaceChildren();
      if (!allCodes.length) {
        var empty = document.createElement("span");
        empty.className = "muted";
        empty.textContent = "尚未選擇；請依 SDS 確認危害說明";
        selectedBox.appendChild(empty);
      } else {
        allCodes.forEach(function (code) {
          var check = checks.find(function (item) { return item.value.toUpperCase() === code; });
          var text = check ? check.closest("label").querySelector("span").textContent.trim() : code;
          var chip = document.createElement("span");
          chip.className = "hazard-chip";
          var label = document.createElement("span");
          label.textContent = text;
          chip.appendChild(label);
          var remove = document.createElement("button");
          remove.type = "button";
          remove.className = "hazard-remove";
          remove.textContent = "×";
          remove.setAttribute("aria-label", "移除 " + text);
          remove.addEventListener("click", function () {
            if (check) check.checked = false;
            extra.value = hazardTokens(extra.value).filter(function (item) { return item !== code; }).join(", ");
            refreshHazardPicker(widget, false);
          });
          chip.appendChild(remove);
          selectedBox.appendChild(chip);
        });
      }
    }
  }
  function initHazardPicker(widget, loadValue) {
    if (!widget) return;
    var search = widget.querySelector(".hazard-search");
    var extra = widget.querySelector(".hazard-extra");
    var empty = widget.querySelector(".hazard-empty");
    if (!widget.dataset.hazardReady) {
      widget.dataset.hazardReady = "1";
      widget.addEventListener("change", function (event) {
        if (event.target.matches(".hazard-option input[type=checkbox]")) refreshHazardPicker(widget, false);
      });
      if (search) {
        search.addEventListener("input", function () {
          var query = search.value.trim().toLocaleLowerCase();
          var shown = 0;
          widget.querySelectorAll(".hazard-option").forEach(function (label) {
            var match = !query || label.textContent.toLocaleLowerCase().indexOf(query) >= 0;
            label.hidden = !match;
            if (match) shown++;
          });
          widget.querySelectorAll(".hazard-category").forEach(function (group) {
            group.hidden = !group.querySelector(".hazard-option:not([hidden])");
          });
          if (empty) empty.hidden = shown > 0;
        });
      }
      if (extra) extra.addEventListener("input", function () { refreshHazardPicker(widget, false); });
    }
    refreshHazardPicker(widget, !!loadValue);
  }
  function refreshHazardPickers(root, loadValue) {
    (root || document).querySelectorAll("[data-hazard-picker]").forEach(function (widget) {
      initHazardPicker(widget, !!loadValue);
    });
  }
  refreshHazardPickers(document, false);
  function gateValue(ctrl) {
    if (!ctrl) return "";
    if (ctrl.type === "checkbox") return ctrl.checked ? (ctrl.value || "1") : "0";
    return String(ctrl.value || "");
  }
  function panelFields(panel) {
    return Array.prototype.filter.call(
      panel.querySelectorAll("input, select, textarea, button"),
      function (el) {
        return el.closest("[data-panel]") === panel;
      }
    );
  }
  function applyGates() {
    document.querySelectorAll("[data-panel]").forEach(function (panel) {
      var key = panel.getAttribute("data-panel");
      var controls = document.querySelectorAll('[data-gate="' + key + '"]');
      var show = (panel.getAttribute("data-show") || "").split("|");
      var on = Array.prototype.some.call(controls, function (ctrl) {
        var val = gateValue(ctrl);
        return show.indexOf("*") >= 0 ? val.trim() !== "" : show.indexOf(val) >= 0;
      });
      panel.hidden = !on;
      panelFields(panel).forEach(function (el) {
        if (el.type === "hidden") return;
        if (!on) {
          if (el.required) {
            el.setAttribute("data-was-required", "1");
            el.required = false;
          }
          el.disabled = true;
        } else {
          el.disabled = false;
          if (el.getAttribute("data-was-required") === "1") el.required = true;
        }
      });
    });
  }
  document.addEventListener("change", function (ev) {
    if (ev.target && ev.target.hasAttribute && ev.target.hasAttribute("data-gate")) applyGates();
  });
  document.addEventListener("input", function (ev) {
    if (ev.target && ev.target.hasAttribute && ev.target.hasAttribute("data-gate")) applyGates();
  });
  var typeSel = byId("equipment_type");
  var powerWrap = byId("power-wrap");
  function togglePower() {
    if (!typeSel || !powerWrap) return;
    powerWrap.hidden = typeSel.value !== "動力來源";
  }
  if (typeSel) {
    typeSel.addEventListener("change", togglePower);
    togglePower();
  }

  var pidProc = byId("pid-process");
  var covering = byId("pid-covering");
  function filterCovering() {
    if (!pidProc || !covering) return;
    var pid = pidProc.value;
    Array.prototype.forEach.call(covering.options, function (opt) {
      var ok = !pid || opt.getAttribute("data-process") === pid;
      opt.disabled = !ok;
      opt.hidden = !ok;
      if (!ok) opt.selected = false;
    });
    if (covering._refreshPick) covering._refreshPick();
  }
  if (pidProc) {
    pidProc.addEventListener("change", filterCovering);
    filterCovering();
  }

  var sopProc = byId("sop-process");
  var sopEquipment = byId("sop-equipment");
  function filterSopEquipment() {
    if (!sopProc || !sopEquipment) return;
    var pid = sopProc.value;
    Array.prototype.forEach.call(sopEquipment.options, function (opt) {
      var ok = opt.getAttribute("data-process") === pid;
      opt.disabled = !ok;
      opt.hidden = !ok;
      if (!ok) opt.selected = false;
    });
    if (sopEquipment._refreshPick) sopEquipment._refreshPick();
  }
  if (sopProc) {
    sopProc.addEventListener("change", filterSopEquipment);
    filterSopEquipment();
  }

  var esdProc = byId("esd-process") || document.querySelector("form[action='/wizard/6/esd'] [name=process_id]");
  var esdActs = byId("esd-actions");
  function filterEsd() {
    if (!esdProc || !esdActs) return;
    var pid = esdProc.value;
    Array.prototype.forEach.call(esdActs.options, function (opt) {
      var ok = !pid || opt.getAttribute("data-process") === pid;
      opt.disabled = !ok;
      opt.hidden = !ok;
      if (!ok) opt.selected = false;
    });
  }
  if (esdProc) {
    esdProc.addEventListener("change", filterEsd);
    filterEsd();
  }

  function fillFromOption(opt, map) {
    if (!opt) return;
    Object.keys(map).forEach(function (attr) {
      var target = map[attr];
      var val = opt.getAttribute(attr) || "";
      if (typeof target === "function") {
        target(val, opt);
        return;
      }
      var el = typeof target === "string" ? document.querySelector(target) : target;
      if (!el) return;
      if (el.type === "checkbox") {
        el.checked = val === "1" || val === "true";
      } else {
        el.value = val;
      }
    });
  }

  var cas11 = byId("psi-11-cas");
  if (cas11) {
    cas11.addEventListener("change", function () {
      var opt = cas11.options[cas11.selectedIndex];
      fillFromOption(opt, {
        "data-danger": byId("is_danger"),
        "data-harm": byId("is_harmful"),
        "data-flam": byId("is_high_flammable"),
        "data-toxic": byId("is_high_toxic"),
      });
      var form = byId("form-11");
      if (!form || !opt) return;
      if (opt.getAttribute("data-dept")) form.elements.dept_id.value = opt.getAttribute("data-dept");
      if (opt.getAttribute("data-area")) form.elements.area_code.value = opt.getAttribute("data-area");
      if (opt.getAttribute("data-max")) form.elements.max_kg.value = opt.getAttribute("data-max");
      if (form.elements.phase_state) form.elements.phase_state.value = opt.getAttribute("data-phase") || "未填";
      if (form.elements.name_en) {
        form.elements.name_en.value = opt.getAttribute("data-name-en") || "";
      }
    });
  }

  var cas12 = byId("psi-12-cas");
  if (cas12) {
    cas12.addEventListener("change", function () {
      var form = byId("form-12");
      var opt = cas12.options[cas12.selectedIndex];
      if (!form || !opt) return;
      if (opt.getAttribute("data-conc")) form.elements.conc.value = opt.getAttribute("data-conc");
      if (opt.getAttribute("data-physical")) form.elements.physical.value = opt.getAttribute("data-physical");
      if (opt.getAttribute("data-health")) form.elements.health.value = opt.getAttribute("data-health");
      form.elements.incompat.value = opt.getAttribute("data-incompat") === "1" ? "是" : "否";
      if (form.elements.name_en) {
        form.elements.name_en.value = opt.getAttribute("data-name-en") || "";
      }
      if (form.elements.ctrl_qty) {
        form.elements.ctrl_qty.value = opt.getAttribute("data-ctrl-qty") || "";
      }
      if (form.elements.phase_state) form.elements.phase_state.value = opt.getAttribute("data-phase") || "未填";
      if (form.elements.aqueous_label) form.elements.aqueous_label.value = opt.getAttribute("data-aqueous") || "待確認";
      var note = byId("psi-12-annex-note");
      if (note) note.textContent = opt.getAttribute("data-annex-note") || "待確認：請重新選取化學品。";
    });
  }

  var eq16 = byId("psi-16-eq");
  if (eq16) {
    eq16.addEventListener("change", function () {
      var form = byId("form-16");
      var opt = eq16.options[eq16.selectedIndex];
      if (!form || !opt) return;
      if (opt.getAttribute("data-material") && form.elements.material) {
        form.elements.material.value = opt.getAttribute("data-material");
      }
      if (form.elements.material_category) {
        form.elements.material_category.value = opt.getAttribute("data-matcat") || "";
      }
      if (opt.getAttribute("data-spec") && form.elements.spec && !form.elements.spec.value) {
        form.elements.spec.value = opt.getAttribute("data-spec");
      }
    });
  }

  var form19 = byId("form-19");
  if (form19) {
    var eq19 = form19.elements.equipment_id;
    if (eq19) {
      eq19.addEventListener("change", function () {
        var opt = eq19.options[eq19.selectedIndex];
        if (!opt) return;
        if (opt.getAttribute("data-area")) form19.elements.area_code.value = opt.getAttribute("data-area");
        if (opt.getAttribute("data-name") && !form19.elements.device_type.value) {
          form19.elements.device_type.value = opt.getAttribute("data-name");
        }
      });
    }
  }

  var eq111 = byId("psi-111-eq");
  function legalFlag(value) {
    return value === true || value === 1 || ["1", "true", "True", "on", "yes"].indexOf(value) >= 0;
  }
  function legalCategory(row) {
    var labels = [];
    if (legalFlag(row.is_regulated_machinery)) labels.push("危險性機械或設備");
    if (legalFlag(row.is_high_pressure_gas)) labels.push("高壓氣體特定設備或容器");
    return labels.join("／");
  }
  function refreshLegalEquipment() {
    if (!eq111) return;
    var form = byId("form-111");
    var pending = byId("psi-111-pending");
    var saved = byId("psi-111-saved");
    var book = {};
    document.querySelectorAll('tr[data-edit="equipment"][data-json]').forEach(function (tr) {
      try {
        var row = JSON.parse(tr.getAttribute("data-json"));
        book[row.equipment_id] = row;
      } catch (err) { /* Ignore malformed display rows. */ }
    });
    var selected = eq111.value;
    var certIds = {};
    saved.querySelectorAll("tr[data-json]").forEach(function (tr) {
      var row = JSON.parse(tr.getAttribute("data-json"));
      certIds[row.equipment_id] = true;
      var eq = book[row.equipment_id];
      var eligible = eq && !!legalCategory(eq);
      tr.querySelector("[data-legal-name]").textContent = eq ? eq.name : "設備已移除";
      tr.querySelector("[data-fill-row]").disabled = !eligible;
      tr.querySelector("[data-legal-stale]").hidden = eligible;
    });
    eq111.replaceChildren();
    var blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "（選已勾選的設備）";
    eq111.appendChild(blank);
    pending.replaceChildren();
    Object.keys(book).sort().forEach(function (id) {
      var row = book[id];
      var category = legalCategory(row);
      if (!category) return;
      var opt = document.createElement("option");
      opt.value = id;
      opt.textContent = id + " " + row.name;
      opt.setAttribute("data-category", category);
      eq111.appendChild(opt);
      if (certIds[id]) return;
      var tr = document.createElement("tr");
      tr.setAttribute("data-fill-form", "form-111");
      tr.setAttribute("data-json", JSON.stringify({ equipment_id: id, category: category, cert_no: "", expire: "" }));
      fillCells(tr, [row.name, id, category, "待填", "待填", ""]);
      var button = document.createElement("button");
      button.type = "button";
      button.className = "editish";
      button.setAttribute("data-fill-row", "");
      button.textContent = "填寫證明";
      tr.lastElementChild.appendChild(button);
      pending.appendChild(tr);
    });
    eq111.value = selected;
    if (selected && !eq111.value) {
      var cancel = form.querySelector(".cancel-edit");
      if (cancel) cancel.click();
      form.elements.category.value = "";
      form.elements.cert_no.value = "";
      form.elements.expire.value = "";
    }
    var hasEquipment = eq111.options.length > 1;
    eq111.disabled = !hasEquipment;
    form.querySelector('button[type="submit"]').disabled = !hasEquipment;
    byId("psi-111-none").disabled = hasEquipment || Object.keys(certIds).length > 0;
    byId("psi-111-empty").hidden = hasEquipment || Object.keys(certIds).length > 0;
    if (eq111._refreshPick) eq111._refreshPick();
    enhanceFilingRowEdits(pending);
  }
  if (eq111) {
    eq111.addEventListener("change", function () {
      var form = byId("form-111");
      var opt = eq111.options[eq111.selectedIndex];
      if (!form) return;
      form.elements.category.value = opt ? opt.getAttribute("data-category") || "" : "";
      form.elements.cert_no.value = "";
      form.elements.expire.value = "";
    });
    refreshLegalEquipment();
  }

  var miEq = byId("mi-eq");
  if (miEq) {
    miEq.addEventListener("change", function () {
      var form = byId("form-81");
      var opt = miEq.options[miEq.selectedIndex];
      if (!form || !opt) return;
      if (opt.getAttribute("data-process")) form.elements.process_id.value = opt.getAttribute("data-process");
      if (opt.getAttribute("data-area")) form.elements.area_code.value = opt.getAttribute("data-area");
      if (form.elements.material) form.elements.material.value = opt.getAttribute("data-material") || "";
      if (form.elements.material_category) {
        form.elements.material_category.value = opt.getAttribute("data-matcat") || "";
      }
      var note = byId("mi-query-note");
      if (note) {
        if (opt.getAttribute("data-query") === "1") {
          note.textContent = "材質類別、溫度、內容物已齊，可至本署查詢頁勾選介質／保溫等條件。";
        } else {
          note.textContent = "尚未可連線查詢：" + (opt.getAttribute("data-missing") || "請先填表1.6-1 材質類別、表1.5 溫度與內容物");
        }
      }
      if (opt.getAttribute("data-mi")) form.elements.mi_type.value = opt.getAttribute("data-mi");
      if (opt.getAttribute("data-pid") && form.elements.pid_no) form.elements.pid_no.value = opt.getAttribute("data-pid");
      var cas = (opt.getAttribute("data-contents") || "").split(",")[0];
      if (cas && form.elements.cas) {
        Array.prototype.forEach.call(form.elements.cas.options, function (o) {
          if (o.value.indexOf(cas + "|") === 0 && o.getAttribute("data-process") === opt.getAttribute("data-process")) {
            o.selected = true;
          }
        });
      }
    });
    miEq.dispatchEvent(new Event("change"));
  }

  var limitEq = byId("limit-eq");
  var limitCas = byId("limit-cas");
  function filterLimitCas() {
    if (!limitEq || !limitCas) return;
    var pid = "";
    var opt = limitEq.options[limitEq.selectedIndex];
    if (opt) pid = opt.getAttribute("data-process") || "";
    Array.prototype.forEach.call(limitCas.options, function (o) {
      var ok = !pid || o.getAttribute("data-process") === pid;
      o.disabled = !ok;
      o.hidden = !ok;
      if (!ok) o.selected = false;
    });
    if (limitCas._refreshPick) limitCas._refreshPick();
  }
  if (limitEq) {
    limitEq.addEventListener("change", function () {
      filterLimitCas();
      var form = byId("form-limit-review");
      if (!form) return;
      var opt = limitEq.options[limitEq.selectedIndex];
      var data = {};
      try { data = JSON.parse(opt && opt.getAttribute("data-review") || "{}"); } catch (err) { data = {}; }
      Array.prototype.forEach.call(form.querySelectorAll("input[name]:not([type=checkbox])"), function (field) {
        if (field.name !== "equipment_id") field.value = field.name.endsWith("_unit") ? field.defaultValue : "";
      });
      Array.prototype.forEach.call(form.querySelectorAll('input[name="review_parameter"]'), function (field) {
        field.checked = (data.selected || []).indexOf(field.value) >= 0;
      });
      var noChem = form.elements.namedItem("no_process_chemical");
      if (noChem) {
        noChem.checked = !!data.no_process_chemical;
      }
      Object.keys(data).forEach(function (key) {
        if (key !== "selected" && key !== "no_process_chemical") setField(form, key, data[key]);
      });
      if (!data.cas && limitCas) {
        Array.prototype.forEach.call(limitCas.options, function (option) { option.selected = false; });
        if (limitCas._refreshPick) limitCas._refreshPick();
      }
      applyGates();
    });
    limitEq.dispatchEvent(new Event("change"));
  }
  document.addEventListener("click", function (event) {
    var button = event.target.closest(".edit-limit-review");
    if (!button || !limitEq) return;
    limitEq.value = button.getAttribute("data-equipment") || "";
    limitEq.dispatchEvent(new Event("change"));
    var form = byId("form-limit-review");
    if (form) form.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  function fileNameFrom(path) {
    if (!path) return "";
    return String(path).replace(/^placeholder:\/\//, "").split(/[/\\]/).pop();
  }

  function namedControl(form, name) {
    var selector = '[name="' + String(name).replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"]';
    var list = form.querySelectorAll(selector);
    if (list.length === 1) return list[0];
    if (list.length > 1) return list;
    return form.elements.namedItem(name);
  }
  function formAction(form) {
    return form.getAttribute("action") || location.href;
  }
  function setField(form, name, value) {
    var el = namedControl(form, name);
    if (!el || el.type === "file") return;
    var list = Array.isArray(value)
      ? value.map(function (item) { return String(item); })
      : String(value == null ? "" : value).split(",").map(function (item) { return item.trim(); }).filter(Boolean);
    if (typeof el.length === "number" && !el.tagName) {
      var booleanCheckboxGroup = typeof value === "boolean" && Array.prototype.some.call(el, function (item) {
        return item.type === "checkbox";
      });
      Array.prototype.forEach.call(el, function (item) {
        if (item.type === "checkbox") item.checked = booleanCheckboxGroup ? value : list.indexOf(item.value) >= 0;
        else if (item.type === "radio") item.checked = list.indexOf(item.value) >= 0;
        else item.value = value == null ? "" : String(value);
      });
      return;
    }
    if (el.tagName === "SELECT" && el.multiple) {
      var want = {};
      list.forEach(function (v) { want[v] = true; });
      Array.prototype.forEach.call(el.options, function (opt) {
        opt.selected = !!(want[opt.value]);
      });
      if (el._refreshPick) el._refreshPick();
      return;
    }
    if (el.type === "checkbox") {
      el.checked = value === true || !!(value && value !== 0 && value !== "0" && value !== "false");
      return;
    }
    el.value = value == null ? "" : String(value);
  }

  function fillEditForm(form, data, kind) {
    var keys = Object.keys(data);
    var i;
    for (i = 0; i < keys.length; i++) {
      setField(form, keys[i], data[keys[i]]);
    }
    refreshHazardPickers(form, true);
    if (kind === "chemical") setField(form, "file_name", fileNameFrom(data.sds_file) || form.elements.file_name && form.elements.file_name.value);
    if (kind === "area") setField(form, "file_name", fileNameFrom(data.attachment_path) || "plot.pdf");
    var btn = form.querySelector('button[type="submit"]');
    if (btn) btn.textContent = form.getAttribute("data-edit-label") || "更新";
    form.classList.add("editing");
    var cancel = form.querySelector(".cancel-edit");
    if (cancel) cancel.hidden = false;
    if (typeof togglePower === "function") togglePower();
    applyGates();
  }

  function enhanceEditRows(root) {
    (root || document).querySelectorAll("tr[data-edit][data-json]").forEach(function (row) {
      var cell = row.querySelector(":scope > td");
      if (!cell) return;
      if (!cell.querySelector(".edit-row")) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "editish edit-row";
        button.textContent = "編輯";
        button.setAttribute("aria-label", "編輯 " + cell.textContent.trim());
        cell.appendChild(button);
      }
      if (row.closest("table.nest")) return;
      var kind = row.getAttribute("data-edit");
      if (["department", "process", "equipment", "chemical", "area"].indexOf(kind) < 0) return;
      var item;
      try { item = JSON.parse(row.getAttribute("data-json") || "{}"); } catch (err) { return; }
      var keys = { department: ["dept_id"], process: ["process_id"], equipment: ["equipment_id"], chemical: ["process_id", "sds_id", "cas"], area: ["area_code"] }[kind];
      if (!keys.every(function (key) { return item[key] != null && String(item[key]).trim(); })) return;
      var table = row.closest("table");
      var head = table && table.querySelector("tr");
      if (head && head.querySelector("th") && !head.querySelector("th.master-actions")) {
        var th = document.createElement("th");
        th.className = "master-actions";
        th.textContent = "操作";
        if (table.classList.contains("nest") && head.lastElementChild && !head.lastElementChild.textContent.trim()) head.lastElementChild.replaceWith(th);
        else head.appendChild(th);
      }
      var action = row.querySelector(":scope > td.master-actions");
      if (!action) {
        action = document.createElement("td");
        action.className = "master-actions";
        row.appendChild(action);
      }
      if (action.querySelector("form")) return;
      action.textContent = "";
      var remove = document.createElement("form");
      remove.method = "post";
      remove.setAttribute("action", "/wizard/item/delete");
      remove.className = "inline";
      remove.onsubmit = function () { return window.confirm("確定刪除這筆資料？依賴它的其他資料列也可能一起移除，刪除後無法復原。"); };
      var input = document.createElement("input");
      input.type = "hidden"; input.name = "kind"; input.value = kind;
      remove.appendChild(input);
      keys.forEach(function (key) {
        var field = document.createElement("input");
        field.type = "hidden"; field.name = key; field.value = item[key];
        remove.appendChild(field);
      });
      var del = document.createElement("button");
      del.type = "submit"; del.className = "linkish"; del.textContent = "刪除";
      del.setAttribute("aria-label", "刪除 " + cell.textContent.replace("編輯", "").trim());
      remove.appendChild(del);
      action.appendChild(remove);
    });
  }
  enhanceEditRows(document);

  function enhanceFilingRowEdits(root) {
    (root || document).querySelectorAll("tr[data-fill-form][data-json]").forEach(function (row) {
      var button = row.querySelector("[data-fill-row]");
      if (!button) {
        var action = row.lastElementChild;
        if (!action || action.tagName !== "TD") return;
        button = document.createElement("button");
        button.type = "button";
        button.className = "editish";
        button.setAttribute("data-fill-row", "");
        button.textContent = "修改";
        action.insertBefore(button, action.firstChild);
      }
      if (button.dataset.filingEditReady) return;
      button.dataset.filingEditReady = "1";
      button.addEventListener("click", function (event) {
        event.preventDefault();
        beginFilingRowEdit(row, button);
        var form = byId(row.getAttribute("data-fill-form"));
        if (form && form.id === "form-81" && form.elements.equipment_id) {
          var values = {};
          try { values = JSON.parse(row.getAttribute("data-json") || "{}"); } catch (err) { values = {}; }
          form.elements.equipment_id.dispatchEvent(new Event("change"));
          if (values.mi_type && form.elements.mi_type) form.elements.mi_type.value = values.mi_type;
        }
      });
    });
  }
  enhanceFilingRowEdits(document);

  function beginFilingRowEdit(row, button) {
    var form = byId(row.getAttribute("data-fill-form"));
    if (!form) return;
    var values;
    try { values = JSON.parse(row.getAttribute("data-json") || "{}"); } catch (err) { return; }
    if (form.dataset.editingRow) {
      var existingCancel = form.querySelector(".cancel-edit");
      if (existingCancel) existingCancel.click();
    }
    if (form.hasAttribute("data-hide-until-edit")) form.hidden = false;
    if (form.id === "form-24" && values.process_id) form._loadingEdit = true;
    Object.keys(values).forEach(function (key) {
      if (form.id === "form-24" && key === "equipment_id") return;
      setField(form, key, values[key]);
    });
    if (form.id === "form-12" && byId("psi-12-annex-note")) {
      byId("psi-12-annex-note").textContent = values.annex_note || "待確認";
    }
    if (form.id === "form-24" && form.elements.process_id) {
      form._loadingEdit = true;
      form.elements.process_id.dispatchEvent(new Event("change"));
      if (values.equipment_id != null) setField(form, "equipment_id", values.equipment_id);
      form._loadingEdit = false;
    }
    if (form.id === "form-14") {
      var reactionKinds = namedControl(form, "kinds");
      if (reactionKinds && reactionKinds._refreshPick) reactionKinds._refreshPick();
    }
    if ((form.getAttribute("action") || "").indexOf("/wizard/row") >= 0 && values.row_id != null) {
      var rowId = form.querySelector('input[name="row_id"]');
      if (!rowId) {
        rowId = document.createElement("input");
        rowId.type = "hidden";
        rowId.name = "row_id";
        form.insertBefore(rowId, form.firstChild);
      }
      rowId.value = values.row_id;
    }
    form.dataset.editingRow = String(values.row_id || values.detail_id || values.incident_id || "1");
    form.dataset.mode = "edit";
    form.classList.add("editing");
    form.querySelectorAll('input[type="file"]').forEach(function (field) {
      if (field.required) field.dataset.editWasRequired = "1";
      field.required = false;
    });
    form.querySelectorAll("[data-edit-identity]").forEach(function (field) {
      if (field.tagName === "SELECT") {
        field.dataset.editWasDisabled = field.disabled ? "1" : "0";
        var copy = document.createElement("input");
        copy.type = "hidden";
        copy.name = field.name;
        copy.value = field.value;
        copy.setAttribute("data-edit-identity-copy", "");
        field.insertAdjacentElement("afterend", copy);
        field.disabled = true;
      } else {
        field.dataset.editWasReadOnly = field.readOnly ? "1" : "0";
        field.readOnly = true;
      }
    });
    var phaUploadEdit = form.id === "form-pha-record" && values.attachment_id != null && values.record_id == null;
    if (form.id === "form-pha-record") {
      form.querySelectorAll("[data-pha-record-only]").forEach(function (label) {
        label.dataset.editWasHidden = label.hidden ? "1" : "0";
        label.hidden = phaUploadEdit;
        if (phaUploadEdit) {
          label.querySelectorAll("input, select, textarea").forEach(function (field) {
            field.dataset.editWasDisabled = field.disabled ? "1" : "0";
            field.disabled = true;
            if (field.required) {
              field.dataset.editWasRequired = "1";
              field.required = false;
            }
          });
        }
      });
      if (phaUploadEdit) {
        var phaMethod = form.elements.namedItem("method");
        if (phaMethod && phaMethod.required) {
          phaMethod.dataset.editWasRequired = "1";
          phaMethod.required = false;
        }
      }
    }
    var submit = form.querySelector('button[type="submit"]');
    if (submit) submit.textContent = form.getAttribute(form.id === "form-111" && values.row_id == null ? "data-add-label" : "data-edit-label") || "更新資料";
    var cancel = form.querySelector(".cancel-edit");
    if (!cancel) {
      cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "btn secondary cancel-edit";
      cancel.textContent = "取消修改";
      if (submit) submit.insertAdjacentElement("afterend", cancel);
    }
    cancel.hidden = false;
    if (!cancel.dataset.editReady) {
      cancel.dataset.editReady = "1";
      cancel.addEventListener("click", function () {
        HTMLFormElement.prototype.reset.call(form);
        ["row_id", "detail_id", "attachment_id", "incident_id", "code_id", "record_id"].forEach(function (name) {
          form.querySelectorAll('input[type="hidden"][name="' + name + '"]').forEach(function (field) {
            field.value = "";
          });
        });
        if (window.PsmFormUX) window.PsmFormUX.resetIdentity(form);
        form.classList.remove("editing");
        delete form.dataset.editingRow;
        form.dataset.mode = "add";
        form.querySelectorAll('input[type="file"][data-edit-was-required="1"]').forEach(function (field) {
          field.required = true;
          delete field.dataset.editWasRequired;
        });
        form.querySelectorAll("[data-pha-record-only]").forEach(function (label) {
          label.hidden = label.dataset.editWasHidden === "1";
          delete label.dataset.editWasHidden;
          label.querySelectorAll("input, select, textarea").forEach(function (field) {
            if (field.dataset.editWasDisabled != null) {
              field.disabled = field.dataset.editWasDisabled === "1";
              delete field.dataset.editWasDisabled;
            }
            if (field.dataset.editWasRequired === "1") {
              field.required = true;
              delete field.dataset.editWasRequired;
            }
          });
        });
        var phaMethod = form.elements.namedItem("method");
        if (phaMethod && phaMethod.dataset.editWasRequired === "1") {
          phaMethod.required = true;
          delete phaMethod.dataset.editWasRequired;
        }
        form.querySelectorAll("[data-edit-identity]").forEach(function (field) {
          if (field.tagName === "SELECT") {
            field.disabled = field.dataset.editWasDisabled === "1";
            var shadow = field.parentNode.querySelector("[data-edit-identity-copy]");
            if (shadow) shadow.remove();
            delete field.dataset.editWasDisabled;
          } else {
            field.readOnly = field.dataset.editWasReadOnly === "1";
            delete field.dataset.editWasReadOnly;
          }
        });
        if (submit) submit.textContent = form.getAttribute("data-add-label") || "新增資料";
        cancel.hidden = true;
        if (form.hasAttribute("data-hide-until-edit")) form.hidden = true;
        document.querySelectorAll("[data-fill-row][aria-pressed='true']").forEach(function (rowButton) {
          rowButton.removeAttribute("aria-pressed");
        });
        form.querySelectorAll("[data-hazard-picker]").forEach(function (widget) { refreshHazardPicker(widget, true); });
        applyGates();
      });
    }
    refreshHazardPickers(form, true);
    applyGates();
    form.scrollIntoView({ behavior: "smooth", block: "center" });
    if (button) button.setAttribute("aria-pressed", "true");
  }

  document.addEventListener("click", function (ev) {
    var editButton = ev.target.closest(".edit-row");
    if (!editButton && ev.target.closest("button, a, input, select, textarea, label")) return;
    if (editButton) ev.preventDefault();
    var card = ev.target.closest("[data-edit][data-json]");
    if (!card) return;
    var kind = card.getAttribute("data-edit");
    var form = byId("form-" + kind);
    if (!form) return;
    var data;
    try {
      data = JSON.parse(card.getAttribute("data-json"));
    } catch (err) {
      return;
    }
    var groupRoot = card.closest("tbody") || card.parentNode;
    var group = groupRoot.querySelectorAll("[data-edit]");
    Array.prototype.forEach.call(group, function (c) {
      c.classList.toggle("on", c === card);
      var row = c.closest("tr");
      if (row && row !== c) row.classList.toggle("on", c === card);
    });
    fillEditForm(form, data, kind);
    if (kind === "area") {
      placePicks("linked_equipment", data.linked_equipment || []);
      placePicks("linked_cas", data.linked_cas_list || data.linked_cas || []);
    }
    if (kind === "chemical") syncMixtureEditor(data);
    form.scrollIntoView({ block: "center", behavior: "smooth" });
    var firstField = form.querySelector('input:not([type="hidden"]):not([type="file"])');
    if (firstField) firstField.focus({ preventScroll: true });
  });

  var annexPick = byId("annex-pick");
  var chemCas = byId("chem-cas");
  var chemName = byId("chem-name");
  function fillChemFromAnnexOption(opt) {
    if (!opt || !opt.value) return;
    var zh = opt.getAttribute("data-name-zh") || "";
    if (chemKind && chemKind.value === "混合物") {
      var rows = document.querySelectorAll("#mix-body tr");
      var row = rows.length ? rows[rows.length - 1] : addMixRow();
      if (!row) return;
      var casIn = row.querySelector("[name=comp_cas]");
      var nameIn = row.querySelector("[name=comp_name]");
      if (casIn) casIn.value = opt.value;
      if (nameIn && zh) nameIn.value = zh;
      showPhaseHint(opt);
      return;
    }
    if (chemCas) chemCas.value = opt.value;
    if (chemName && zh) chemName.value = zh;
    showPhaseHint(opt);
  }
  function showPhaseHint(opt) {
    var hint = byId("phase-hint");
    if (!hint) return;
    if (!opt || !opt.value) {
      hint.textContent = "";
      return;
    }
    var phase = opt.getAttribute("data-phase") || "";
    var gate = opt.getAttribute("data-gate") === "1";
    if (gate && phase) {
      hint.textContent = "氯化氫、氟化氫須確認操作相態及水溶液別。水溶液不列入；無水液化或資料不足者待確認，不能只依液態排除。";
    } else if (phase) {
      hint.textContent = "常見相態參考為" + phase + "，不因相態不同自動排除。操作量（kg）×wt%÷100 後對照規定數量（kg）。";
    } else {
      hint.textContent = "";
    }
  }
  if (annexPick) {
    annexPick.addEventListener("change", function () {
      fillChemFromAnnexOption(annexPick.options[annexPick.selectedIndex]);
    });
  }
  if (chemCas) {
    chemCas.addEventListener("blur", function () {
      var cas = chemCas.value.trim();
      if (!cas || !annexPick) return;
      var i;
      for (i = 0; i < annexPick.options.length; i++) {
        if (annexPick.options[i].value === cas) {
          annexPick.selectedIndex = i;
          if (chemName && !chemName.value.trim()) {
            chemName.value = annexPick.options[i].getAttribute("data-name-zh") || "";
          }
          showPhaseHint(annexPick.options[i]);
          break;
        }
      }
    });
  }
  var chemKind = byId("chem-kind");
  var mixFlag = byId("chem-mix-flag");
  var mixBody = byId("mix-body");
  var mixTpl = byId("mix-row-tpl");
  function addMixRow(data) {
    if (!mixBody || !mixTpl) return null;
    var row = mixTpl.content.firstElementChild.cloneNode(true);
    mixBody.appendChild(row);
    data = data || {};
    function put(name, value) {
      var el = row.querySelector("[name=" + name + "]");
      if (el && value != null && value !== "") el.value = value;
    }
    put("comp_cas", data.cas);
    put("comp_name", data.name);
    put("comp_role", data.role);
    put("comp_h", data.h_codes);
    initHazardPicker(row.querySelector("[data-hazard-picker]"), true);
    put("comp_pct_lo", data.pct_lo);
    put("comp_pct_hi", data.pct_hi);
    put("comp_formula", data.formula);
    var phase = data.phase_state || "";
    put("comp_phase", phase);
    put("comp_aqueous_status", data.aqueous_status);
    var del = row.querySelector(".mix-del");
    if (del) {
      del.addEventListener("click", function () {
        row.remove();
        if (!mixBody.querySelector("tr")) addMixRow();
      });
    }
    return row;
  }
  function setMixEnabled(on) {
    if (!mixBody) return;
    mixBody.querySelectorAll("input, select").forEach(function (el) {
      el.disabled = !on;
    });
  }
  function toggleMixFields() {
    var mix = chemKind && chemKind.value === "混合物";
    if (mixFlag) mixFlag.checked = !!mix;
    document.querySelectorAll(".mix-only").forEach(function (el) {
      el.hidden = !mix;
    });
    document.querySelectorAll(".pure-only").forEach(function (el) {
      el.hidden = mix;
    });
    var pureForm = byId("form-chemical");
    if (pureForm) {
      ["cas", "phase_state"].forEach(function (name) {
        var el = pureForm.elements.namedItem(name);
        if (el && !el.length) el.required = !mix;
      });
    }
    if (mix && mixBody && !mixBody.querySelector("tr")) addMixRow();
    setMixEnabled(mix);
  }
  function syncMixtureEditor(data) {
    if (chemKind && data && data.kind) chemKind.value = data.kind;
    if (mixBody) mixBody.innerHTML = "";
    if (data && data.kind === "混合物") addMixRow(data);
    toggleMixFields();
  }
  if (mixFlag && chemKind) {
    mixFlag.addEventListener("change", function () {
      chemKind.value = mixFlag.checked ? "混合物" : "純物質";
      if (!mixFlag.checked && mixBody) mixBody.innerHTML = "";
      toggleMixFields();
    });
  }
  if (chemKind) toggleMixFields();
  var mixAdd = byId("mix-add");
  if (mixAdd) {
    mixAdd.addEventListener("click", function () {
      addMixRow();
      setMixEnabled(true);
    });
  }

  var blockProc = byId("block-process");
  function filterBlockEq() {
    if (!blockProc) return;
    var pid = blockProc.value;
    document.querySelectorAll("select.block-eq").forEach(function (sel) {
      Array.prototype.forEach.call(sel.options, function (opt) {
        if (!opt.value) return;
        var ok = opt.getAttribute("data-process") === pid;
        opt.disabled = !ok;
        opt.hidden = !ok;
        if (!ok && opt.selected) {
          opt.selected = false;
          sel.value = "";
        }
      });
    });
  }
  if (blockProc) filterBlockEq();

  function placePicks(field, values) {
    var board = document.querySelector('.pick-board[data-field="' + field + '"]');
    if (!board || typeof board._placeValues !== "function") return;
    board._placeValues(values);
  }
  var pickDrag = null;
  function clearPickOver() {
    document.querySelectorAll(".pick-pool.over, .pick-chosen.over").forEach(function (zone) {
      zone.classList.remove("over");
    });
  }
  function zoneAt(x, y, board) {
    var under = document.elementFromPoint(x, y);
    var zone = under && under.closest(".pick-pool, .pick-chosen");
    if (!zone || zone.closest(".pick-board") !== board) return null;
    return zone;
  }
  function bindPickBoard(board, place) {
    board.querySelectorAll(".drag-box").forEach(function (box) {
      if (box._pickBound) return;
      box._pickBound = true;
      box.addEventListener("pointerdown", function (ev) {
        if (ev.button !== 0 || box.classList.contains("static") || box.hidden) return;
        if (board._locked) return;
        pickDrag = { box: box, board: board, place: place, x: ev.clientX, y: ev.clientY, moved: false, ghost: null };
        if (box.setPointerCapture) box.setPointerCapture(ev.pointerId);
        ev.preventDefault();
      });
    });
  }
  document.addEventListener("pointermove", function (ev) {
    if (!pickDrag) return;
    var dx = ev.clientX - pickDrag.x;
    var dy = ev.clientY - pickDrag.y;
    if (!pickDrag.moved && dx * dx + dy * dy < 16) return;
    pickDrag.moved = true;
    if (!pickDrag.ghost) {
      var ghost = pickDrag.box.cloneNode(true);
      ghost.querySelectorAll("input").forEach(function (node) { node.remove(); });
      ghost.className = "drag-box drag-ghost is-chosen";
      document.body.appendChild(ghost);
      pickDrag.ghost = ghost;
      pickDrag.box.classList.add("is-dragging");
    }
    pickDrag.ghost.style.left = ev.clientX + "px";
    pickDrag.ghost.style.top = ev.clientY + "px";
    clearPickOver();
    var zone = zoneAt(ev.clientX, ev.clientY, pickDrag.board);
    if (zone) zone.classList.add("over");
  });
  document.addEventListener("pointerup", function (ev) {
    if (!pickDrag) return;
    var drag = pickDrag;
    pickDrag = null;
    if (drag.ghost) drag.ghost.remove();
    drag.box.classList.remove("is-dragging");
    clearPickOver();
    if (!drag.moved) {
      drag.place(drag.box, drag.box.classList.contains("is-chosen") ? "pool" : "chosen");
      return;
    }
    var zone = zoneAt(ev.clientX, ev.clientY, drag.board);
    if (!zone) return;
    drag.place(drag.box, zone.classList.contains("pick-chosen") ? "chosen" : "pool");
  });
  function wireValueBoard(board) {
    var pool = board.querySelector(".pick-pool");
    var chosen = board.querySelector(".pick-chosen");
    var field = board.getAttribute("data-field");
    function place(box, side) {
      var input = box.querySelector("input[type=hidden]");
      if (side === "chosen") {
        if (!input) {
          input = document.createElement("input");
          input.type = "hidden";
          input.name = field;
          box.appendChild(input);
        }
        input.value = box.getAttribute("data-value");
        chosen.appendChild(box);
        box.classList.add("is-chosen");
      } else {
        if (input) input.remove();
        pool.appendChild(box);
        box.classList.remove("is-chosen");
      }
    }
    board._syncBoxes = function () { bindPickBoard(board, place); };
    board._placeValues = function (values) {
      var want = {};
      var list = Array.isArray(values) ? values : String(values || "").split(",");
      list.forEach(function (v) {
        var key = String(v || "").trim();
        if (key) want[key] = true;
      });
      board.querySelectorAll(".drag-box").forEach(function (box) {
        place(box, want[box.getAttribute("data-value")] ? "chosen" : "pool");
      });
    };
    bindPickBoard(board, place);
  }
  document.querySelectorAll(".pick-board[data-field]").forEach(wireValueBoard);
  function makeBoard(title) {
    var board = document.createElement("div");
    board.className = "pick-board span-all";
    ["可選", "已選"].forEach(function (side, index) {
      var col = document.createElement("div");
      var label = document.createElement("div");
      label.className = "pick-label";
      label.textContent = title + "・" + side;
      var zone = document.createElement("div");
      zone.className = index === 0 ? "pick-pool" : "pick-chosen";
      zone.setAttribute("data-hint", index === 0 ? "沒有可選項目" : "拖到這裡");
      col.appendChild(label);
      col.appendChild(zone);
      board.appendChild(col);
    });
    return board;
  }
  function labelCaption(label) {
    var text = "";
    label.childNodes.forEach(function (node) {
      if (node.nodeType === 3) text += node.textContent;
    });
    return text.replace(/\s+/g, " ").trim();
  }
  var reactionOtherDialog = null;
  function askReactionKind() {
    return new Promise(function (resolve) {
      if (reactionOtherDialog) {
        reactionOtherDialog.close();
        reactionOtherDialog.remove();
        reactionOtherDialog = null;
      }
      var dialog = document.createElement("dialog");
      reactionOtherDialog = dialog;
      dialog.className = "ux-draft-dialog";
      dialog.setAttribute("aria-labelledby", "rxn-other-title");
      dialog.innerHTML = '<h2 id="rxn-other-title">請寫反應種類</h2><p>已勾選「其他」。請寫明實際的反應種類，例如烷基化、中和。</p><p data-hint role="status"></p><label>反應種類 <input type="text" maxlength="80" autocomplete="off" required></label><div class="ux-dialog-actions"><button type="button" data-choice="ok">確定</button><button type="button" class="secondary" data-choice="cancel">取消</button></div>';
      document.body.appendChild(dialog);
      var input = dialog.querySelector("input");
      var hint = dialog.querySelector("[data-hint]");
      function finish(value) {
        if (dialog.open) dialog.close();
        dialog.remove();
        if (reactionOtherDialog === dialog) reactionOtherDialog = null;
        resolve(value);
      }
      dialog.querySelector('[data-choice="ok"]').addEventListener("click", function () {
        var text = input.value.trim();
        if (!text) {
          hint.textContent = "請寫反應種類。";
          input.setAttribute("aria-invalid", "true");
          input.focus();
          return;
        }
        finish(text);
      });
      dialog.querySelector('[data-choice="cancel"]').addEventListener("click", function () { finish(""); });
      dialog.addEventListener("cancel", function (ev) {
        ev.preventDefault();
        finish("");
      });
      input.addEventListener("keydown", function (ev) {
        if (ev.key !== "Enter") return;
        ev.preventDefault();
        dialog.querySelector('[data-choice="ok"]').click();
      });
      dialog.showModal();
      input.focus();
    });
  }
  function reactionOtherKind(box) {
    if (box._input && box._input.name === "rxn_types" && box._input.value === "其他") return "flag";
    var opt = box._opt;
    var sel = opt && opt.parentNode;
    if (opt && (opt.value === "其他" || opt.textContent.trim() === "其他") && sel && sel.getAttribute("name") === "kinds" && sel.form && sel.form.id === "form-14") return "row";
    return "";
  }
  function reactionOtherInput(box, kind) {
    var form = kind === "flag" ? box._input.form : box._opt.form;
    if (!form) return null;
    return form.querySelector('input[name="' + (kind === "flag" ? "rxn_type_other" : "kind_other") + '"]');
  }
  function paintReactionOther(box, text) {
    box.textContent = text ? "其他：" + text : "其他";
  }
  function withReactionOther(box, side, apply) {
    var wasChosen = box.classList.contains("is-chosen");
    var kind = reactionOtherKind(box);
    if (kind && side === "chosen" && !wasChosen) {
      if (box._asking) return;
      box._asking = true;
      askReactionKind().then(function (text) {
        box._asking = false;
        var field = reactionOtherInput(box, kind);
        if (!text) {
          apply("pool");
          if (field) field.value = "";
          paintReactionOther(box, "");
          return;
        }
        if (field) field.value = text;
        apply("chosen");
        paintReactionOther(box, text);
      });
      return;
    }
    apply(side);
    if (kind && side !== "chosen") {
      var field = reactionOtherInput(box, kind);
      if (field) field.value = "";
      paintReactionOther(box, "");
    }
  }
  document.querySelectorAll("select[multiple]").forEach(function (select) {
    if (select.dataset.pickReady) return;
    select.dataset.pickReady = "1";
    var host = select.parentNode;
    var title = "可複選";
    if (host && host.tagName === "LABEL") {
      title = labelCaption(host) || title;
      host.hidden = true;
    }
    var board = makeBoard(title);
    var pool = board.querySelector(".pick-pool");
    var chosen = board.querySelector(".pick-chosen");
    var anchor = host && host.tagName === "LABEL" ? host : select;
    anchor.parentNode.insertBefore(board, anchor.nextSibling);
    function place(box, side) {
      withReactionOther(box, side, function (next) {
        var opt = box._opt;
        if (!opt) return;
        opt.selected = next === "chosen";
        (next === "chosen" ? chosen : pool).appendChild(box);
        box.classList.toggle("is-chosen", next === "chosen");
      });
    }
    function rebuild() {
      pool.innerHTML = "";
      chosen.innerHTML = "";
      Array.prototype.forEach.call(select.options, function (opt) {
        if (!opt.value && !opt.textContent.trim()) return;
        var box = document.createElement("div");
        box.className = "drag-box";
        box.textContent = opt.textContent.trim();
        box._opt = opt;
        box.hidden = !!(opt.hidden || opt.disabled);
        if (opt.selected && !box.hidden) {
          chosen.appendChild(box);
          box.classList.add("is-chosen");
          if (select.form && select.form.id === "form-14" && (opt.value === "其他" || opt.textContent.trim() === "其他")) {
            var written = select.form.querySelector('input[name="kind_other"]');
            if (written && written.value.trim()) box.textContent = "其他：" + written.value.trim();
          }
        } else {
          pool.appendChild(box);
        }
      });
      bindPickBoard(board, place);
    }
    select._refreshPick = rebuild;
    board._locked = !!select.disabled;
    select.addEventListener("change", rebuild);
    rebuild();
  });
  var checkGroups = {};
  document.querySelectorAll('input[type="checkbox"][name]').forEach(function (input) {
    var form = input.form;
    var key = (form ? form.id || form.getAttribute("action") || "form" : "page") + "::" + input.name;
    if (!checkGroups[key]) checkGroups[key] = [];
    checkGroups[key].push(input);
  });
  Object.keys(checkGroups).forEach(function (key) {
    var inputs = checkGroups[key];
    if (inputs.length < 2) return;
    if (inputs.some(function (input) { return input.hasAttribute("data-native"); })) return;
    // Conditional fields depend on native change events and keyboard access.
    // Keep these groups as checkboxes instead of turning them into drag boxes.
    if (inputs.some(function (input) { return input.hasAttribute("data-gate"); })) return;
    if (inputs[0].closest(".pick-board")) return;
    var firstLabel = inputs[0].closest("label") || inputs[0];
    var fieldset = inputs[0].closest("fieldset");
    var row = inputs[0].closest(".chk-row");
    var holder = fieldset || row;
    var title = "可複選";
    if (fieldset) {
      var legend = fieldset.querySelector("legend");
      if (legend) title = legend.textContent.trim() || title;
    }
    var board = makeBoard(title);
    var pool = board.querySelector(".pick-pool");
    var chosen = board.querySelector(".pick-chosen");
    var insertAt = holder || firstLabel;
    insertAt.parentNode.insertBefore(board, insertAt);
    function place(box, side) {
      withReactionOther(box, side, function (next) {
        if (box._input) box._input.checked = next === "chosen";
        (next === "chosen" ? chosen : pool).appendChild(box);
        box.classList.toggle("is-chosen", next === "chosen");
      });
    }
    inputs.forEach(function (input) {
      var label = input.closest("label");
      var box = document.createElement("div");
      box.className = "drag-box";
      box.textContent = (label ? label.textContent : input.value).replace(/\s+/g, " ").trim();
      box._input = input;
      if (input.checked) {
        chosen.appendChild(box);
        box.classList.add("is-chosen");
      } else {
        pool.appendChild(box);
      }
      if (label) label.hidden = true;
    });
    if (holder) holder.hidden = true;
    bindPickBoard(board, place);
  });

  var designProcess = byId("design-process");
  function filterDesignChoices() {
    if (!designProcess) return;
    document.querySelectorAll("#form-16 [data-design-process]").forEach(function (label) {
      var match = label.getAttribute("data-design-process") === designProcess.value;
      label.hidden = !match;
      var input = label.querySelector("input");
      if (input) {
        input.disabled = !match;
        if (!match) input.checked = false;
      }
    });
  }
  if (designProcess) {
    designProcess.addEventListener("change", filterDesignChoices);
    filterDesignChoices();
  }
  var designForm = byId("form-16");
  var designCancel = byId("design-cancel");
  function setDesignSelections(name, rawValues) {
    var wanted = {};
    String(rawValues || "").split(",").forEach(function (value) {
      value = value.trim();
      if (value) wanted[value] = true;
    });
    if (!designForm) return;
    designForm.querySelectorAll('input[name="' + name + '"]').forEach(function (input) {
      input.checked = !!wanted[input.value];
    });
  }
  if (designForm) {
    var designSubmit = designForm.querySelector('button[type="submit"]');
    function resetDesignEditor() {
      HTMLFormElement.prototype.reset.call(designForm);
      if (window.PsmFormUX) window.PsmFormUX.resetIdentity(designForm);
      designForm.classList.remove("editing");
      document.querySelectorAll("[data-design-code-row].on").forEach(function (row) { row.classList.remove("on"); });
      if (designSubmit) designSubmit.textContent = designForm.getAttribute("data-add-label") || "新增設計規範";
      if (designCancel) designCancel.hidden = true;
      filterDesignChoices();
    }
    if (designCancel) designCancel.addEventListener("click", resetDesignEditor);
    designForm._resetEdit = resetDesignEditor;
    document.addEventListener("click", function (event) {
      var button = event.target.closest(".edit-design-code");
      if (!button || !designForm) return;
      event.preventDefault();
      var data;
      try { data = JSON.parse(button.getAttribute("data-json") || "{}"); } catch (err) { return; }
      resetDesignEditor();
      designForm.elements.code_id.value = data.code_id || "";
      designProcess.value = data.process_id || "";
      designProcess.dispatchEvent(new Event("change"));
      setDesignSelections("equipment_ids", data.equipment_values || "");
      setDesignSelections("cas_list", data.chemical_values || "");
      designForm.elements.material_category.value = data.material_category || "";
      designForm.elements.material.value = data.material || "";
      designForm.elements.spec.value = data.spec || "";
      designForm.elements.scope.value = data.scope || "";
      button.closest("tr").classList.add("on");
      designForm.classList.add("editing");
      if (designSubmit) designSubmit.textContent = designForm.getAttribute("data-edit-label") || "更新設計規範";
      if (designCancel) designCancel.hidden = false;
      designForm.scrollIntoView({ block: "center", behavior: "smooth" });
    });
  }

  var CATALOG_KEY = "psm-fill-catalog";
  function emptyCatalog() {
    return { gen: 0, department: {}, process: {}, equipment: {}, chemical: {}, area: {} };
  }
  function loadCatalog() {
    try {
      var parsed = JSON.parse(localStorage.getItem(CATALOG_KEY) || "");
      if (parsed && parsed.department) return parsed;
    } catch (err) { /* start over */ }
    return emptyCatalog();
  }
  function writeCatalog(cat) {
    localStorage.setItem(CATALOG_KEY, JSON.stringify(cat));
  }
  function pageScroll() {
    return document.scrollingElement || document.documentElement;
  }
  function keepScroll(fn) {
    var top = pageScroll().scrollTop;
    fn();
    pageScroll().scrollTop = top;
  }
  function formNote(form, text, isErr) {
    var note = form.querySelector(".save-inline");
    if (!note) {
      note = document.createElement("p");
      note.className = "save-inline";
      note.setAttribute("role", "status");
      form.appendChild(note);
    }
    note.classList.toggle("err", !!isErr);
    note.textContent = text;
  }
  function refreshCoreStatus(form) {
    var wizard = document.querySelector(".wizard[data-core-ready='0']");
    if (!wizard) return;
    fetch("/wizard/core-status", { credentials: "same-origin" }).then(function (response) {
      return response.json();
    }).then(function (state) {
      if (state.ready) {
        window.location.hash = form.id || "";
        window.location.reload();
        return;
      }
      var list = document.querySelector("#wiz-block ul");
      if (list && Array.isArray(state.missing)) {
        list.textContent = "";
        state.missing.forEach(function (item) {
          var li = document.createElement("li");
          li.textContent = item;
          list.appendChild(li);
        });
      }
    }).catch(function () { /* 儲存已完成，狀態會在下次開頁更新。 */ });
  }
  function headingBefore(form) {
    var node = form.previousElementSibling;
    while (node) {
      if (/^H[2-4]$/.test(node.tagName)) return node;
      node = node.previousElementSibling;
    }
    return null;
  }
  function tableBefore(form) {
    var node = form.previousElementSibling;
    while (node) {
      if (node.matches && node.matches("table.data") && !node.classList.contains("nest")) return node;
      if (node.querySelector) {
        var found = node.querySelector("table.data");
        if (found) return found;
      }
      node = node.previousElementSibling;
    }
    return null;
  }
  function ensureRow(table, kind, match) {
    var row = null;
    table.querySelectorAll("tr[data-edit='" + kind + "']").forEach(function (tr) {
      if (row) return;
      try {
        if (match(JSON.parse(tr.getAttribute("data-json") || "{}"))) row = tr;
      } catch (err) { /* skip */ }
    });
    if (!row) {
      var placeholder = table.querySelector("td[colspan]");
      if (placeholder && placeholder.closest("table") === table) placeholder.parentNode.remove();
      row = document.createElement("tr");
      row.setAttribute("data-edit", kind);
      (table.tBodies[0] || table.createTBody()).appendChild(row);
    }
    return row;
  }
  function fillCells(row, values) {
    var i;
    for (i = 0; i < values.length; i++) {
      if (!row.children[i]) row.appendChild(document.createElement("td"));
      row.children[i].textContent = values[i] == null ? "" : String(values[i]);
    }
  }
  function chipCell(cell, texts) {
    cell.textContent = "";
    if (!texts.length) {
      var empty = document.createElement("span");
      empty.className = "muted";
      empty.textContent = "尚未選";
      cell.appendChild(empty);
      return;
    }
    texts.forEach(function (text) {
      var span = document.createElement("span");
      span.className = "drag-box static";
      span.textContent = text;
      cell.appendChild(span);
    });
  }
  function remember(kind, id, row) {
    var cat = loadCatalog();
    if (!cat[kind]) cat[kind] = {};
    cat[kind][id] = row;
    cat.gen = (cat.gen || 0) + 1;
    writeCatalog(cat);
    return cat;
  }
  function optionText(sel) {
    var opt = sel && sel.options ? sel.options[sel.selectedIndex] : null;
    return opt ? opt.textContent : "";
  }
  function paintMaster(form, kind, row) {
    var table = tableBefore(form);
    if (!table || !row) return;
    if (kind === "department") {
      var drow = ensureRow(table, "department", function (cur) { return cur.dept_id === row.dept_id; });
      fillCells(drow, [row.dept_id, row.name, row.headcount, row.parent_dept_id || ""]);
      drow.setAttribute("data-json", JSON.stringify(row));
    } else if (kind === "process") {
      var prow = ensureRow(table, "process", function (cur) { return cur.process_id === row.process_id; });
      var modeSel = form.elements.namedItem("mode");
      fillCells(prow, [row.process_id, row.name, row.operating_dept_id, optionText(modeSel) || row.mode, row.overview || ""]);
      prow.setAttribute("data-json", JSON.stringify(row));
    } else if (kind === "equipment") {
      var erow = ensureRow(table, "equipment", function (cur) { return cur.equipment_id === row.equipment_id; });
      fillCells(erow, [row.equipment_id, row.name, row.process_id, row.equipment_type, row.maint_dept_id]);
      erow.setAttribute("data-json", JSON.stringify(row));
    } else if (kind === "chemical") {
      var items = row.components && row.components.length ? row.components : [row];
      items.forEach(function (item) {
        if (!item.cas) return;
        var crow = ensureRow(table, "chemical", function (cur) {
          return cur.cas === item.cas && cur.process_id === (item.process_id || row.process_id);
        });
        var stored = Object.assign({}, item, {
          cas: item.cas,
          process_id: item.process_id || row.process_id,
          sds_id: item.sds_id || row.sds_id || "",
          name: item.name || row.name,
          role: item.role || row.role || "",
          h_codes: item.h_codes || row.h_codes || "",
          phase_state: item.phase_state || row.phase_state || "",
          aqueous_status: item.aqueous_status != null ? item.aqueous_status : (row.aqueous_status || ""),
          kind: item.kind || row.kind || "純物質"
        });
        if (crow.closest("table").classList.contains("nest") && crow.children.length >= 5) {
          crow.children[0].textContent = stored.cas;
          crow.children[1].textContent = stored.name;
          crow.children[2].textContent = stored.role;
          crow.children[3].textContent = (stored.phase_state || "未填") + "／" + ({ "1": "水溶液", "0": "非水溶液" }[stored.aqueous_status] || "待確認");
          crow.children[4].textContent = stored.h_codes;
        } else {
          fillCells(crow, [
            stored.kind,
            stored.process_id,
            stored.sds_id,
            stored.name,
            stored.cas + "・" + stored.role + "・" + (stored.phase_state || "未填相態") + "・" + stored.h_codes
          ]);
        }
        crow.setAttribute("data-json", JSON.stringify(stored));
      });
    } else if (kind === "area") {
      var arow = ensureRow(table, "area", function (cur) { return cur.area_code === row.area_code; });
      while (arow.children.length < 10) arow.appendChild(document.createElement("td"));
      var cells = arow.children;
      cells[0].textContent = row.area_code || "";
      cells[1].textContent = row.name || "";
      cells[2].textContent = row.worker_count == null ? "" : String(row.worker_count);
      cells[3].textContent = row.drawing_no || "";
      cells[4].textContent = row.revision || "";
      cells[5].textContent = row.issue_date || "";
      cells[6].textContent = row.process_id || "";
      cells[7].textContent = row.is_assembly_point ? "是" : "否";
      var eqLabels = row.equipment_labels || {};
      var chemLabels = row.chemical_labels || {};
      chipCell(cells[8], (row.linked_equipment || []).map(function (id) { return eqLabels[id] || id; }));
      chipCell(cells[9], (row.linked_cas_list || row.linked_cas || []).map(function (token) {
        return chemLabels[token] || token;
      }));
      arow.setAttribute("data-json", JSON.stringify(row));
    }
    enhanceEditRows(table);
  }
  function storeMaster(kind, row) {
    if (!row) return loadCatalog();
    if (kind === "department") {
      return remember("department", row.dept_id, {
        label: row.dept_id + " " + row.name,
        dept_id: row.dept_id,
        name: row.name,
        headcount: row.headcount,
        parent_dept_id: row.parent_dept_id || ""
      });
    }
    if (kind === "process") {
      return remember("process", row.process_id, {
        label: row.process_id + " " + row.name,
        value: row.process_id,
        process_id: row.process_id,
        name: row.name
      });
    }
    if (kind === "equipment") {
      return remember("equipment", row.equipment_id, {
        label: row.equipment_id + " " + row.name,
        value: row.equipment_id,
        process: row.process_id,
        equipment_id: row.equipment_id,
        name: row.name
      });
    }
    if (kind === "area") {
      return remember("area", row.area_code, {
        label: row.area_code + " " + row.name,
        value: row.area_code,
        area_code: row.area_code,
        name: row.name
      });
    }
    if (kind === "chemical") {
      var cat = loadCatalog();
      if (row.psi_facts) cat.psi_facts = row.psi_facts;
      var items = row.components && row.components.length ? row.components : [row];
      items.forEach(function (item) {
        if (!item.cas) return;
        var pid = item.process_id || row.process_id || "";
        var key = item.cas + "|" + pid;
        cat.chemical[key] = {
          label: item.cas + " " + (item.name || row.name || "") + (pid ? " / " + pid : ""),
          value: key,
          cas: item.cas,
          name: item.name || row.name || "",
          process: pid
        };
      });
      cat.gen = (cat.gen || 0) + 1;
      writeCatalog(cat);
      return cat;
    }
    return loadCatalog();
  }
  function kindOfSelect(sel) {
    if (sel.classList.contains("block-eq") || sel.id === "flow-eq" || sel.id === "limit-eq" || sel.id === "mi-eq") {
      return "equipment";
    }
    var name = sel.getAttribute("name") || "";
    if (name === "parent_dept_id" || name === "operating_dept_id" || name === "maint_dept_id" || name === "dept_id") {
      return "department";
    }
    if (name === "process_id" || name === "ov_process" || name === "block_process" || name === "rxn_process") {
      return "process";
    }
    if (name === "equipment_id") return "equipment";
    if (name === "area_code" || name === "muster") return "area";
    if (name === "cas") return "chemical";
    return "";
  }
  function selectUsesPipe(sel) {
    var i;
    for (i = 0; i < sel.options.length; i++) {
      if ((sel.options[i].value || "").indexOf("|") >= 0) return true;
    }
    return sel.id === "psi-11-cas" || sel.id === "psi-12-cas" || sel.id === "limit-cas";
  }
  function syncSelect(sel, kind, cat) {
    // Table 1.11 has its own eligibility filter; the general catalog contains all equipment.
    if (sel.id === "psi-111-eq") return;
    var book = cat[kind] || {};
    var pipe = kind === "chemical" && selectUsesPipe(sel);
    var seen = {};
    function syncPsiOption(opt) {
      if (sel.id !== "psi-11-cas" && sel.id !== "psi-12-cas") return;
      var fact = (cat.psi_facts || {})[opt.value];
      if (!fact) return;
      opt.setAttribute("data-phase", fact.phase_state || "未填");
      opt.setAttribute("data-aqueous", fact.aqueous_label || "待確認");
      opt.setAttribute("data-ctrl-qty", fact.ctrl_qty || "");
      opt.setAttribute("data-annex-note", fact.annex_note || "待確認");
    }
    Array.prototype.forEach.call(sel.options, function (opt) {
      if (!opt.value) return;
      syncPsiOption(opt);
      var row = book[opt.value];
      if (!row && kind === "chemical") {
        Object.keys(book).forEach(function (key) {
          if (row) return;
          if (key === opt.value || book[key].cas === opt.value) row = book[key];
        });
      }
      if (row && row.label) {
        opt.textContent = pipe || kind !== "chemical" ? row.label : (row.cas + " " + row.name);
        if (row.process) opt.setAttribute("data-process", row.process);
      }
      seen[opt.value] = true;
    });
    Object.keys(book).forEach(function (id) {
      var row = book[id];
      var value = pipe || kind !== "chemical" ? (row.value || id) : row.cas;
      if (!value || seen[value]) return;
      var opt = document.createElement("option");
      opt.value = value;
      opt.textContent = kind === "chemical" && !pipe ? (row.cas + " " + row.name) : row.label;
      if (row.process) opt.setAttribute("data-process", row.process);
      syncPsiOption(opt);
      sel.appendChild(opt);
      seen[value] = true;
    });
    if (sel.disabled && sel.options.length > 1) sel.disabled = false;
    if (sel._refreshPick) sel._refreshPick();
    if ((sel.id === "psi-11-cas" || sel.id === "psi-12-cas") && sel.value) {
      var current = sel.options[sel.selectedIndex];
      var form = sel.form;
      if (form.elements.phase_state) form.elements.phase_state.value = current.getAttribute("data-phase") || "未填";
      if (form.elements.aqueous_label) form.elements.aqueous_label.value = current.getAttribute("data-aqueous") || "待確認";
      if (form.elements.ctrl_qty) form.elements.ctrl_qty.value = current.getAttribute("data-ctrl-qty") || "";
      if (sel.id === "psi-12-cas" && byId("psi-12-annex-note")) byId("psi-12-annex-note").textContent = current.getAttribute("data-annex-note") || "待確認";
    }
  }
  function syncPick(board, kind, cat) {
    var book = cat[kind] || {};
    var pool = board.querySelector(".pick-pool");
    if (!pool) return;
    var have = {};
    board.querySelectorAll(".drag-box").forEach(function (box) {
      var id = box.getAttribute("data-value");
      have[id] = true;
      if (!book[id]) return;
      var input = box.querySelector("input");
      box.textContent = book[id].label;
      if (input) box.appendChild(input);
    });
    Object.keys(book).forEach(function (id) {
      if (have[id]) return;
      var box = document.createElement("div");
      box.className = "drag-box";
      box.setAttribute("data-value", id);
      box.textContent = book[id].label;
      pool.appendChild(box);
    });
    if (board._syncBoxes) board._syncBoxes();
  }
  function applyBlock(heading, cat, skipPicks) {
    var node = heading.nextElementSibling;
    while (node && !/^H[2-4]$/.test(node.tagName)) {
      node.querySelectorAll("select").forEach(function (sel) {
        var kind = kindOfSelect(sel);
        if (kind) syncSelect(sel, kind, cat);
      });
      if (!skipPicks) {
        node.querySelectorAll(".pick-board[data-field]").forEach(function (board) {
          var field = board.getAttribute("data-field");
          if (field === "linked_equipment") syncPick(board, "equipment", cat);
          if (field === "linked_cas") syncPick(board, "chemical", cat);
        });
      }
      node = node.nextElementSibling;
    }
    heading.dataset.catalogGen = String(cat.gen || 0);
  }
  function refreshScrolled() {
    var cat = loadCatalog();
    var gen = String(cat.gen || 0);
    if (gen === "0") return;
    document.querySelectorAll("h3, h4").forEach(function (heading) {
      if (heading.dataset.catalogGen === gen) return;
      var rect = heading.getBoundingClientRect();
      if (rect.bottom < 80 || rect.top > window.innerHeight - 40) return;
      applyBlock(heading, cat, false);
    });
  }
  document.addEventListener("scroll", refreshScrolled, true);
  localStorage.setItem(CATALOG_KEY, JSON.stringify(emptyCatalog()));
  document.querySelectorAll("h3, h4").forEach(function (heading) {
    heading.dataset.catalogGen = "0";
  });

  [
    ["form-department", "department"],
    ["form-process", "process"],
    ["form-equipment", "equipment"],
    ["form-chemical", "chemical"],
    ["form-area", "area"]
  ].forEach(function (pair) {
    var form = byId(pair[0]);
    var kind = pair[1];
    if (!form) return;
    var cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "btn secondary cancel-edit";
    cancel.textContent = "取消編輯";
    cancel.hidden = true;
    form.appendChild(cancel);
    form._resetEdit = function () {
      HTMLFormElement.prototype.reset.call(form);
      form.classList.remove("editing");
      cancel.hidden = true;
      var save = form.querySelector('button[type="submit"]');
      if (save) save.textContent = form.getAttribute("data-add-label") || "新增";
      document.querySelectorAll("tr[data-edit='" + kind + "'].on").forEach(function (row) { row.classList.remove("on"); });
      if (kind === "area") {
        placePicks("linked_equipment", []);
        placePicks("linked_cas", []);
      }
      if (kind === "chemical") syncMixtureEditor({ kind: "純物質" });
      applyGates();
      formNote(form, "已切換為新增模式", false);
    };
    cancel.addEventListener("click", form._resetEdit);
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (form._saving) return;
      form._saving = true;
      var submittedSnapshot = window.PsmFormUX && window.PsmFormUX.snapshot(form);
      var top = pageScroll().scrollTop;
      formNote(form, "儲存中…", false);
      fetch(formAction(form), {
        method: "POST",
        body: new FormData(form),
        headers: { "X-PSM-Partial": "1" },
        credentials: "same-origin"
      }).then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        }, function () {
          return { ok: false, data: { message: "沒有存成" } };
        });
      }).then(function (result) {
        pageScroll().scrollTop = top;
        if (!result.ok || !result.data || !result.data.ok) {
          formNote(form, (result.data && result.data.message) || "沒有存成", true);
          return;
        }
        var row = result.data.area || result.data.row;
        if (kind === "area" && result.data.area) {
          row.is_assembly_point = row.is_assembly_point === 1 || row.is_assembly_point === "1" || row.is_assembly_point === true;
        }
        keepScroll(function () { paintMaster(form, kind, row); });
        storeMaster(kind, row);
        if (kind === "equipment") refreshLegalEquipment();
        var head = headingBefore(form);
        if (head) head.dataset.catalogGen = String(loadCatalog().gen || 0);
        formNote(form, result.data.message || "已存檔", false);
        if (window.PsmFormUX) window.PsmFormUX.markSaved(form, submittedSnapshot);
        refreshCoreStatus(form);
        pageScroll().scrollTop = top;
      }).catch(function () {
        formNote(form, "沒有存成", true);
      }).then(function () {
        form._saving = false;
        pageScroll().scrollTop = top;
      });
    });
  });
  var siteForm = document.querySelector('form[action="/wizard/1"]');
  if (siteForm) {
    var absentOutput = byId("absent-equipment-types");
    var absentInputs = siteForm.querySelectorAll(".absent-equipment-type");
    function syncAbsentTypes() {
      if (!absentOutput) return;
      absentOutput.value = Array.prototype.filter.call(absentInputs, function (input) {
        return input.checked && !input.disabled;
      }).map(function (input) { return input.value; }).join(",");
    }
    absentInputs.forEach(function (input) { input.addEventListener("change", syncAbsentTypes); });
    syncAbsentTypes();
    siteForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (siteForm._saving) return;
      siteForm._saving = true;
      var submittedSnapshot = window.PsmFormUX && window.PsmFormUX.snapshot(siteForm);
      var top = pageScroll().scrollTop;
      formNote(siteForm, "儲存中…", false);
      fetch(formAction(siteForm), {
        method: "POST",
        body: new FormData(siteForm),
        headers: { "X-PSM-Partial": "1" },
        credentials: "same-origin"
      }).then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        }, function () {
          return { ok: false, data: { message: "沒有存成" } };
        });
      }).then(function (result) {
        pageScroll().scrollTop = top;
        formNote(siteForm, (result.data && result.data.message) || (result.ok ? "已存檔" : "沒有存成"), !(result.ok && result.data && result.data.ok));
        if (result.ok && result.data && result.data.ok) {
          refreshCoreStatus(siteForm);
          if (window.PsmFormUX) window.PsmFormUX.markSaved(siteForm, submittedSnapshot);
        }
      }).catch(function () {
        formNote(siteForm, "沒有存成", true);
      }).then(function () {
        siteForm._saving = false;
        pageScroll().scrollTop = top;
      });
    });
  }
  var pha24Process = byId("pha24-process");
  var pha24Equipment = byId("pha24-equipment");
  if (pha24Process && pha24Equipment) {
    function filterPha24Equipment(event) {
      var processId = pha24Process.value;
      var removed = [];
      Array.prototype.forEach.call(pha24Equipment.options, function (option) {
        var applicable = option.getAttribute("data-process") === processId;
        if (!applicable && option.selected) removed.push(option.value);
        option.hidden = !applicable;
        option.disabled = !applicable;
        if (!applicable) option.selected = false;
      });
      if (pha24Equipment._refreshPick) pha24Equipment._refreshPick();
      var note = byId("pha24-equipment-change");
      var ids = removed.filter(function (id, index) { return id && removed.indexOf(id) === index; });
      if (note) {
        note.textContent = event && !pha24Process.form._loadingEdit && ids.length ? "已移除不屬於此製程的設備：" + ids.join("、") : "";
        note.hidden = !note.textContent;
      }
    }
    pha24Process.addEventListener("change", filterPha24Equipment);
    filterPha24Equipment();
  }
  applyGates();
})();
