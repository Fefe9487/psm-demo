/* Shared table editing, draft protection and recoverable form submission. */
(function () {
  "use strict";
  var baselines = new WeakMap();
  var identityDefaults = new WeakMap();
  var bypass = false;
  var leaving = false;
  var saving = false;
  var refreshNeeded = false;
  var pendingKey = "psm-table-pending-action";
  var main = document.querySelector("main");
  if (!main) return;

  function forms() {
    return Array.from(main.querySelectorAll('form[method="post"]')).filter(function (f) {
      return !f.classList.contains("inline") && f.id !== "flow-save" && !f.closest(".sidebar");
    });
  }
  var identityNames = ["row_id", "detail_id", "attachment_id", "incident_id", "code_id", "record_id"];
  function controls(form) {
    return Array.from(form.querySelectorAll("input, select, textarea")).filter(function (el) {
      return el.name && el.form === form && !/^(submit|button|reset|image)$/.test(el.type || "");
    });
  }
  function fieldValue(el) {
    if (el.type === "file") {
      return Array.from(el.files || []).map(function (file) { return [file.name, file.size, file.lastModified]; });
    }
    if (el.multiple && el.selectedOptions) {
      return Array.from(el.selectedOptions).map(function (option) { return option.value; });
    }
    return el.value;
  }
  function snapshot(form) {
    return JSON.stringify(controls(form).map(function (el) {
      return [el.name, fieldValue(el), /^(checkbox|radio)$/.test(el.type || "") ? el.checked : null];
    }));
  }
  function isEditing(form) {
    return form.dataset.mode === "edit" || form.classList.contains("editing");
  }
  function markSaved(form, submitted) { baselines.set(form, typeof submitted === "string" ? submitted : snapshot(form)); }
  function dirty() { return forms().filter(function (f) { return baselines.has(f) && baselines.get(f) !== snapshot(f); }); }
  function resetIdentity(form) {
    var defaults = identityDefaults.get(form) || {};
    form.querySelectorAll('input[type="hidden"]').forEach(function (field) {
      if (/^(row_id|detail_id|attachment_id|incident_id|code_id|record_id)$/.test(field.name)) field.value = defaults[field.name] || "";
    });
  }
  window.PsmFormUX = { markSaved: markSaved, snapshot: snapshot, resetIdentity: resetIdentity };
  forms().forEach(function (form) {
    var submitButton = form.querySelector('button[type="submit"]');
    if (submitButton && !form.dataset.addLabel) form.dataset.addLabel = submitButton.textContent.trim();
    var defaults = {};
    form.querySelectorAll('input[type="hidden"]').forEach(function (field) { defaults[field.name] = field.value; });
    identityDefaults.set(form, defaults);
    markSaved(form);
  });

  function notice(form, message, error) {
    var box = form.querySelector(":scope > .ux-form-message");
    if (!box) {
      box = document.createElement("div");
      box.className = "ux-form-message span-all";
      box.tabIndex = -1;
      form.prepend(box);
    }
    box.classList.toggle("is-error", !!error);
    box.setAttribute("role", error ? "alert" : "status");
    box.textContent = message;
    if (error) {
      box.scrollIntoView({ block: "center", behavior: "smooth" });
      box.focus({ preventScroll: true });
    }
  }
  function explainFailure(message) {
    var text = (message || "未能完成儲存").trim();
    if (text.indexOf("請") < 0) text += "。請依這項說明修正標示欄位後再儲存";
    if (text.indexOf("保留") < 0) text += "。目前填寫的內容會保留";
    return text;
  }
  function showError(form, message, fields) {
    notice(form, explainFailure(message), true);
    var matched = [];
    Array.from(form.elements).forEach(function (field) {
      if (!field.name || field.type === "hidden" || field.disabled) return;
      var label = field.closest("label");
      var caption = label ? label.textContent.trim().split(/[（：(\n]/)[0].replace(/^\*\s*/, "").trim() : "";
      var terms = (field.dataset.errorTerms || "").split("|").filter(Boolean);
      if ((fields || []).indexOf(field.name) >= 0 || (caption.length >= 2 && message.indexOf(caption) >= 0) || terms.some(function (term) { return message.indexOf(term) >= 0; })) {
        field.setAttribute("aria-invalid", "true");
        var hint = document.createElement("span");
        hint.className = "ux-field-error";
        hint.id = "ux-error-" + Array.from(document.forms).indexOf(form) + "-" + matched.length;
        hint.textContent = message;
        field.dataset.uxOriginalDescription = field.getAttribute("aria-describedby") || "";
        field.setAttribute("aria-describedby", (field.dataset.uxOriginalDescription + " " + hint.id).trim());
        field.insertAdjacentElement("afterend", hint);
        matched.push(field);
      }
    });
    if (matched.length) { matched[0].focus(); matched[0].scrollIntoView({ block: "center" }); }
  }
  function clearErrors(form) {
    form.querySelectorAll(".ux-field-error").forEach(function (e) { e.remove(); });
    form.querySelectorAll("[data-ux-original-description]").forEach(function (el) {
      el.removeAttribute("aria-invalid");
      if (el.dataset.uxOriginalDescription) el.setAttribute("aria-describedby", el.dataset.uxOriginalDescription);
      else el.removeAttribute("aria-describedby");
      delete el.dataset.uxOriginalDescription;
    });
  }
  async function save(form, submitter) {
    if (!form.reportValidity()) return null;
    clearErrors(form);
    if (!isEditing(form)) resetIdentity(form);
    var body = new FormData(form);
    if (!isEditing(form)) {
      identityNames.forEach(function (name) {
        form.querySelectorAll('input[type="hidden"][name="' + name + '"]').forEach(function () {
          body.set(name, "");
        });
      });
    }
    if (submitter && submitter.name) body.append(submitter.name, submitter.value);
    var submitted = snapshot(form);
    var buttons = Array.from(form.querySelectorAll('button[type="submit"], input[type="submit"]'));
    var wasDisabled = buttons.map(function (b) { return b.disabled; });
    buttons.forEach(function (b) { b.disabled = true; });
    form.setAttribute("aria-busy", "true");
    notice(form, "儲存中…", false);
    try {
      var res = await fetch(form.getAttribute("action") || location.href, { method: "POST", body: body, credentials: "same-origin", headers: { "X-PSM-Partial": "1" } });
      var url = new URL(res.url);
      var message = url.searchParams.get("err");
      var fields = [];
      var json = null;
      if ((res.headers.get("content-type") || "").indexOf("application/json") >= 0) {
        json = await res.json();
        if (!res.ok || json.ok === false) {
          message = json.message;
          if (Array.isArray(json.fields)) fields = json.fields;
          if (!message && Array.isArray(json.detail)) {
            fields = json.detail.map(function (item) { return item.loc[item.loc.length - 1]; });
            message = "請檢查必填欄位及資料格式";
          }
        }
      } else {
        var doc = new DOMParser().parseFromString(await res.text(), "text/html");
        var banner = doc.querySelector("main > .banner.err");
        if (banner) message = banner.textContent.trim();
      }
      if (message || !res.ok) {
        showError(form, message || "未能完成儲存。請檢查標示欄位後再按一次儲存", fields);
        return null;
      }
      markSaved(form, submitted);
      refreshNeeded = true;
      notice(form, "已儲存。重新整理後顯示最新列表。", false);
      return json ? location.pathname + location.search : res.url;
    } catch (error) {
      showError(form, "連線中斷，尚無法確認是否已儲存。請先核對資料，確認後再按一次儲存");
      return null;
    } finally {
      buttons.forEach(function (b, i) { b.disabled = wasDisabled[i]; });
      form.removeAttribute("aria-busy");
    }
  }

  var dialog = document.createElement("dialog");
  dialog.className = "ux-draft-dialog";
  dialog.setAttribute("aria-labelledby", "ux-draft-title");
  dialog.innerHTML = '<h2 id="ux-draft-title">尚有未儲存的修改</h2><p id="ux-draft-description"></p><div class="ux-dialog-actions"><button type="button" data-choice="save">儲存後繼續</button><button type="button" class="secondary" data-choice="discard">放棄修改</button><button type="button" class="secondary" data-choice="stay">繼續編輯</button></div>';
  document.body.appendChild(dialog);
  function ask(count) {
    return new Promise(function (resolve) {
      dialog.querySelector("p").textContent = "目前有 " + count + " 個區段尚未儲存。儲存後繼續會依序儲存這些區段；若驗證失敗，會保留內容並停在錯誤處。";
      function done(value) { dialog.close(); dialog.onclick = null; dialog.oncancel = null; resolve(value); }
      dialog.onclick = function (ev) { var b = ev.target.closest("[data-choice]"); if (b) done(b.dataset.choice); };
      dialog.oncancel = function (ev) { ev.preventDefault(); done("stay"); };
      dialog.showModal();
      dialog.querySelector('[data-choice="stay"]').focus();
    });
  }
  function navigate(url, action) {
    if (action) {
      try { sessionStorage.setItem(pendingKey, JSON.stringify({ path: location.pathname, action: action })); } catch (e) { /* navigation still works */ }
    }
    leaving = true;
    location.assign(url);
  }
  async function guard(proceed, action, affected) {
    if (saving || dialog.open || forms().some(function (f) { return f._saving; })) return;
    var changed = dirty();
    if (affected && changed.indexOf(affected) < 0) { proceed(); return; }
    if (!changed.length) { proceed(); return; }
    var choice = await ask(changed.length);
    if (choice === "stay") return;
    if (choice === "discard") {
      proceed();
      return;
    }
    saving = true;
    try {
      for (var form of changed) { if (!await save(form)) return; }
      if (dirty().length) {
        notice(dirty()[0], "儲存期間仍有新的修改，請確認後再次儲存。", false);
        return;
      }
      if (action && action.kind === "navigate") navigate(action.href);
      else navigate(location.pathname + location.search, action);
    } finally { saving = false; }
  }

  function mode(form, label) {
    var note = form.querySelector(":scope > .ux-mode");
    if (!note) { note = document.createElement("div"); note.className = "ux-mode span-all"; note.setAttribute("role", "status"); form.prepend(note); }
    note.textContent = label;
  }
  function reset(form) {
    if (form._resetEdit) form._resetEdit();
    else {
      var cancel = form.querySelector(".cancel-edit");
      if (cancel && !cancel.hidden) { bypass = true; cancel.click(); bypass = false; }
      else HTMLFormElement.prototype.reset.call(form);
    }
    form.querySelectorAll("select").forEach(function (select) {
      select.dispatchEvent(new Event("change", { bubbles: true }));
      if (select._refreshPick) select._refreshPick();
    });
    if (!form.hasAttribute("data-hide-until-edit")) form.hidden = false;
    form.classList.remove("editing");
    delete form.dataset.editingRow;
    form.dataset.mode = "add";
    resetIdentity(form);
    var submit = form.querySelector('button[type="submit"]');
    if (submit) submit.textContent = form.dataset.addLabel || "新增資料";
    var cancelBtn = form.querySelector(".cancel-edit");
    if (cancelBtn) cancelBtn.hidden = true;
    clearErrors(form);
    var message = form.querySelector(":scope > .ux-form-message");
    if (message) message.remove();
    mode(form, "新增資料");
    markSaved(form);
  }
  function addModeLabel(form, element) {
    var label = ((element && element.textContent) || form.dataset.addLabel || "新增資料").replace(/\s+/g, " ").trim();
    if (!label || label.indexOf("正在修改") === 0) return form.dataset.addLabel || "新增資料";
    return label;
  }
  function rowCaption(source) {
    var cell = source && source.querySelector("td");
    var text = (cell || source || {}).textContent || "";
    return text.replace(/編輯／確認|編輯|修改/g, "").replace(/\s+/g, " ").trim() || "已選資料";
  }
  function perform(action, element) {
    if (action.kind === "add") {
      var form = document.getElementById(action.formId);
      if (!form) return;
      reset(form);
      mode(form, addModeLabel(form, element));
      form.scrollIntoView({ block: "center", behavior: "smooth" });
      var field = form.querySelector('input:not([type="hidden"]):not([readonly]), select:not([disabled]), textarea');
      if (field) field.focus({ preventScroll: true });
    } else if (element) {
      bypass = true;
      element.click();
      bypass = false;
    }
  }
  document.addEventListener("click", function (ev) {
    if (bypass || ev.defaultPrevented || ev.button !== 0 || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) return;
    var add = ev.target.closest("[data-new-form]");
    var edit = ev.target.closest("[data-fill-row], .edit-row, .edit-design-code, .edit-limit-review, .cancel-edit, #design-cancel");
    var row = ev.target.closest("[data-edit][data-json]");
    if (!edit && row && !ev.target.closest("a, button, input, select, textarea, label")) edit = row;
    if (add || edit) {
      var formId = add ? add.dataset.newForm : null;
      var source = edit && (edit.closest("[data-fill-form]") || edit.closest("[data-edit]"));
      if (source) formId = source.dataset.fillForm || "form-" + source.dataset.edit;
      if (edit && edit.matches(".edit-design-code")) formId = "form-16";
      if (edit && edit.matches(".edit-limit-review")) formId = "form-limit-review";
      var form = formId ? document.getElementById(formId) : edit.closest("form");
      if (!form) return;
      var action = { kind: add ? "add" : "edit", formId: form.id, data: source && source.dataset.json, design: edit && edit.dataset.json, equipment: edit && edit.dataset.equipment, cancel: !!(edit && edit.matches(".cancel-edit, #design-cancel")) };
      var element = add || edit;
      function proceed() {
        clearErrors(form);
        var message = form.querySelector(":scope > .ux-form-message");
        if (message) message.remove();
        perform(action, element);
        if (!add) {
          form.dataset.mode = action.cancel ? "add" : "edit";
          mode(form, action.cancel ? "新增資料" : "正在修改：" + rowCaption(source));
          markSaved(form);
        }
      }
      ev.preventDefault(); ev.stopImmediatePropagation();
      guard(proceed, action, form);
      return;
    }
    var link = ev.target.closest("a[href]");
    if (!link || link.target === "_blank" || link.hasAttribute("download")) return;
    var url = new URL(link.href, location.href);
    if (url.pathname === location.pathname && url.search === location.search && url.hash) return;
    if (!dirty().length) return;
    ev.preventDefault(); ev.stopImmediatePropagation();
    guard(function () { navigate(url.href); }, { kind: "navigate", href: url.href });
  }, true);

  document.addEventListener("submit", function (ev) {
    if (ev.defaultPrevented) return; // Existing master/flow handlers retain their own behavior.
    var form = ev.target;
    if ((form.getAttribute("method") || "get").toLowerCase() !== "post" || !main.contains(form)) return;
    if (form.id === "flow-save") return;
    ev.preventDefault();
    if (saving) return;
    saving = true;
    save(form, ev.submitter).then(function (url) {
      saving = false;
      if (!url) return;
      var destination = new URL(url, location.href);
      if (form.id) destination.hash = form.id;
      guard(function () { navigate(destination.href); }, { kind: "navigate", href: destination.href });
    }).finally(function () { saving = false; });
  });
  window.addEventListener("beforeunload", function (ev) {
    if (!leaving && (saving || dirty().length)) { ev.preventDefault(); ev.returnValue = ""; }
  });
  // A successful save can remain on screen when the user keeps another draft.
  var refresh = document.createElement("button");
  refresh.type = "button"; refresh.className = "secondary ux-refresh";
  refresh.textContent = "更新列表"; refresh.hidden = true;
  refresh.onclick = function () { guard(function () { navigate(location.pathname + location.search); }, { kind: "navigate", href: location.pathname + location.search }); };
  main.appendChild(refresh);
  new MutationObserver(function () { refresh.hidden = !refreshNeeded; }).observe(main, { childList: true, subtree: true });

  function enhanceTables() {
    main.querySelectorAll("table.data").forEach(function (table) {
      if (table.closest("form")) return;
      if (table.dataset.uxTable) {
        var existingHead = table.rows[0];
        if (existingHead) Array.from(table.rows).slice(1).forEach(function (row) {
          if (row.cells.length !== existingHead.cells.length) return;
          Array.from(row.cells).forEach(function (cell, i) {
            ["ux-first-column", "ux-identifier", "ux-actions"].forEach(function (name) {
              cell.classList.toggle(name, existingHead.cells[i].classList.contains(name));
            });
          });
        });
        return;
      }
      table.dataset.uxTable = "1";
      var wrap = table.parentElement;
      if (!wrap.classList.contains("table-wrap")) {
        wrap = document.createElement("div"); wrap.className = "table-wrap";
        table.before(wrap); wrap.appendChild(table);
      }
      wrap.classList.add("ux-table-wrap");
      wrap.tabIndex = 0;
      wrap.setAttribute("role", "region");
      var section = table.closest(".sec");
      var heading = section && section.querySelector("h3, h4");
      wrap.setAttribute("aria-label", (heading ? heading.textContent.trim() : "資料表") + "，可左右捲動");
      var header = table.rows[0];
      if (!header) return;
      if (header.querySelector("th") && header.parentElement.tagName !== "THEAD") {
        var head = table.createTHead(); head.appendChild(header);
      }
      Array.from(header.cells).forEach(function (cell, index) {
        var caption = cell.textContent.trim();
        cell.setAttribute("scope", "col");
        if (!caption && index === header.cells.length - 1) cell.textContent = "操作";
        if (/操作/.test(cell.textContent)) {
          Array.from(table.rows).forEach(function (row) {
            if (row.cells.length === header.cells.length) row.cells[index].classList.add("ux-actions");
          });
        }
        if (/編號|代號|CAS/.test(caption)) {
          Array.from(table.rows).forEach(function (row) {
            if (row.cells.length === header.cells.length) row.cells[index].classList.add("ux-identifier");
          });
        }
      });
      if (header.cells.length >= 8) table.classList.add("ux-wide-table");
      Array.from(table.rows).forEach(function (row) {
        if (row.cells.length === header.cells.length && row.cells[0].colSpan === 1) row.cells[0].classList.add("ux-first-column");
      });
      var hint = document.createElement("p"); hint.className = "ux-scroll-hint";
      hint.textContent = "左右捲動查看完整欄位；識別欄與操作欄保持顯示。";
      wrap.before(hint);
      var wide = header.cells.length >= 8;
      function overflow() { hint.hidden = !wide && table.scrollWidth <= wrap.clientWidth + 1; }
      new ResizeObserver(overflow).observe(wrap); overflow();
    });
  }
  enhanceTables();
  new MutationObserver(enhanceTables).observe(main, { childList: true, subtree: true });
  try {
    var pending = JSON.parse(sessionStorage.getItem(pendingKey) || "null");
    sessionStorage.removeItem(pendingKey);
    if (pending && pending.path === location.pathname) {
      var action = pending.action;
      if (action.kind === "add") perform(action);
      else if (!action.cancel) {
        var candidates = Array.from(document.querySelectorAll("[data-fill-form], [data-edit][data-json], .edit-design-code, .edit-limit-review"));
        var target = candidates.find(function (el) {
          return (action.data && el.dataset.json === action.data && (el.dataset.fillForm || "form-" + el.dataset.edit) === action.formId) ||
            (action.design && el.matches(".edit-design-code") && el.dataset.json === action.design) ||
            (action.equipment && el.matches(".edit-limit-review") && el.dataset.equipment === action.equipment);
        });
        if (target) {
          perform(action, target.querySelector("[data-fill-row], .edit-row") || target);
          var restoredForm = document.getElementById(action.formId);
          if (restoredForm) {
            restoredForm.dataset.mode = "edit";
            mode(restoredForm, "正在修改：" + rowCaption(target));
            markSaved(restoredForm);
          }
        }
      }
    }
  } catch (e) { console.warn("無法還原編輯位置：", e.message); }
})();
