"use strict";

const state = { meta: null, report: "by_category", expanded: new Set() };

// ------------------------------------------------------------ helpers

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k in el && k !== "list") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null) el.append(c instanceof Node ? c : String(c));
  return el;
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: opts.body ? { "Content-Type": "application/json" } : {},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Request failed (${res.status})`);
  }
  return res.status === 204 ? null : res.json();
}

const fmt = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" });
const money = (cents) => fmt.format(cents / 100);

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 3000);
}

function guard(fn) {
  return async (...args) => {
    try { await fn(...args); } catch (e) { toast(e.message); }
  };
}

const today = () => new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD in local time

// ------------------------------------------------------------ pickers

function entityOptions(current, { blank = "— Entity —" } = {}) {
  const opts = [h("option", { value: "" }, blank)];
  for (const t of state.meta.entity_types) {
    const ents = state.meta.entities.filter((e) => e.type === t.code && (!e.archived || e.id === current));
    if (ents.length) opts.push(h("optgroup", { label: t.label },
      ents.map((e) => h("option", { value: e.id, selected: e.id === current }, e.name))));
  }
  return opts;
}

function categoryOptions(current) {
  const opts = [h("option", { value: "" }, "— Category —")];
  for (const g of state.meta.category_groups) {
    const cats = g.categories.filter((c) => (!c.archived && !g.archived) || c.id === current);
    if (cats.length) opts.push(h("optgroup", { label: g.name },
      cats.map((c) => h("option", { value: c.id, selected: c.id === current, title: c.description }, c.name))));
  }
  return opts;
}

function fillPickers() {
  for (const sel of document.querySelectorAll("[data-picker]")) {
    const keep = sel.value;
    const kind = sel.dataset.picker;
    if (kind === "entity") sel.replaceChildren(...entityOptions(null));
    if (kind === "entity-filter") sel.replaceChildren(...entityOptions(null, { blank: "All entities" }));
    if (kind === "category") sel.replaceChildren(...categoryOptions(null));
    if (kind === "entity-type") sel.replaceChildren(...state.meta.entity_types.map((t) => h("option", { value: t.code }, t.label)));
    if (keep) sel.value = keep;
  }
  const scope = document.getElementById("r-scope");
  const keep = scope.value;
  scope.replaceChildren(
    h("option", { value: "" }, "Combined (everything)"),
    h("optgroup", { label: "By type" }, state.meta.entity_types.map((t) => h("option", { value: `type:${t.code}` }, `All ${t.label}`))),
    h("optgroup", { label: "Single entity" }, state.meta.entities.filter((e) => !e.archived).map((e) => h("option", { value: `entity:${e.id}` }, e.name))),
  );
  scope.value = keep;
}

async function loadMeta() {
  state.meta = await api("/api/meta");
  fillPickers();
}

// ------------------------------------------------------------ transactions

const addForm = document.getElementById("add-form");

function resetAddForm() {
  addForm.reset();
  addForm.date.value = today();
  addForm.querySelector(".reimb-from").hidden = true;
}

addForm.reimbursable.addEventListener("change", (e) => {
  addForm.querySelector(".reimb-from").hidden = !e.target.checked;
});

addForm.addEventListener("submit", guard(async (e) => {
  e.preventDefault();
  const f = addForm;
  const raw = f.amount.value.replace(/[$,\s-]/g, "");
  if (!raw || isNaN(Number(raw))) throw new Error("Enter an amount, e.g. 42.50");
  const sign = f.kind.value === "expense" ? "-" : "";
  const txn = await api("/api/transactions", { method: "POST", body: {
    date: f.date.value, amount: sign + raw, description: f.description.value,
    entity_id: f.entity_id.value, category_id: f.category_id.value,
    reimbursable: f.reimbursable.checked, reimburse_from: f.reimburse_from.value, notes: f.notes.value,
  }});
  const keepEntity = f.entity_id.value, keepDate = f.date.value;
  resetAddForm();
  f.entity_id.value = keepEntity; // entering a batch for one entity is common
  f.date.value = keepDate;
  f.querySelector(".form-msg").textContent = `Added ${txn.description || "transaction"} (${money(txn.amount_cents)})`;
  f.amount.focus();
  await loadTransactions();
}));

function txnRow(t) {
  const patch = guard(async (body) => {
    const updated = await api(`/api/transactions/${t.id}`, { method: "PATCH", body });
    Object.assign(t, updated);
    li.replaceWith(txnRow(t));
    updateSummary();
  });
  const untagged = !t.entity_id || !t.category_id;
  const li = h("li", { className: "txn" + (untagged ? " untagged" : "") },
    h("div", { className: "meta date" }, t.date, " ", t.source !== "manual" ? h("span", { className: "badge" }, t.source) : null),
    h("div", { className: "body" },
      h("div", { className: "desc" }, t.description || "(no description)"),
      t.notes ? h("div", { className: "meta" }, t.notes) : null),
    h("div", { className: "tags" },
      h("select", { "aria-label": "Entity", onchange: (e) => patch({ entity_id: e.target.value }) }, entityOptions(t.entity_id)),
      h("select", { "aria-label": "Category", onchange: (e) => patch({ category_id: e.target.value }) }, categoryOptions(t.category_id))),
    h("div", { className: "amt " + (t.amount_cents < 0 ? "neg" : "pos") }, money(t.amount_cents)),
    h("div", { className: "row-actions" },
      h("label", { className: "check" },
        h("input", { type: "checkbox", checked: !!t.reimbursable, onchange: (e) => patch({ reimbursable: e.target.checked }) }),
        "Reimbursable"),
      t.reimbursable ? [
        h("input", { type: "text", value: t.reimburse_from, placeholder: "Owed by", "aria-label": "Owed by",
          onchange: (e) => patch({ reimburse_from: e.target.value }) }),
        h("label", { className: "check" },
          h("input", { type: "checkbox", checked: !!t.reimbursed_on,
            onchange: (e) => patch({ reimbursed_on: e.target.checked ? today() : null }) }),
          t.reimbursed_on ? `Paid back ${t.reimbursed_on}` : "Paid back"),
      ] : null,
      h("button", { type: "button", className: "link", onclick: guard(async () => {
        if (!confirm(`Delete "${t.description || "this transaction"}"?`)) return;
        await api(`/api/transactions/${t.id}`, { method: "DELETE" });
        li.remove();
        state.txns = state.txns.filter((x) => x !== t);
        updateSummary();
      }) }, "Delete")),
  );
  return li;
}

function updateSummary() {
  const txns = state.txns || [];
  const income = txns.filter((t) => t.amount_cents > 0).reduce((s, t) => s + t.amount_cents, 0);
  const spent = txns.filter((t) => t.amount_cents < 0).reduce((s, t) => s - t.amount_cents, 0);
  const untagged = txns.filter((t) => !t.entity_id || !t.category_id).length;
  document.getElementById("list-summary").textContent =
    `${txns.length} shown · income ${money(income)} · spent ${money(spent)} · net ${money(income - spent)}` +
    (untagged ? ` · ${untagged} need tagging` : "");
}

async function loadTransactions() {
  const p = new URLSearchParams();
  const q = document.getElementById("f-q").value.trim();
  const ent = document.getElementById("f-entity").value;
  if (q) p.set("q", q);
  if (ent) p.set("entity_id", ent);
  if (document.getElementById("f-untagged").checked) p.set("uncategorized", "1");
  const { transactions } = await api(`/api/transactions?${p}`);
  state.txns = transactions;
  const list = document.getElementById("txn-list");
  list.replaceChildren(...transactions.map(txnRow));
  if (!transactions.length) list.append(h("li", { className: "muted" }, "No transactions yet."));
  updateSummary();
}

let searchTimer;
document.getElementById("f-q").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(guard(loadTransactions), 250);
});
document.getElementById("f-entity").addEventListener("change", guard(loadTransactions));
document.getElementById("f-untagged").addEventListener("change", guard(loadTransactions));

// ------------------------------------------------------------ reports

function rangeDates(kind) {
  const now = new Date();
  const iso = (d) => d.toLocaleDateString("en-CA");
  const monthsBack = (n) => iso(new Date(now.getFullYear(), now.getMonth() - n, 1));
  switch (kind) {
    case "month": return [monthsBack(0), ""];
    case "3m": return [monthsBack(2), ""];
    case "12m": return [monthsBack(11), ""];
    case "ytd": return [`${now.getFullYear()}-01-01`, ""];
    case "custom": return [document.getElementById("r-start").value, document.getElementById("r-end").value];
    default: return ["", ""];
  }
}

function renderPicker() {
  document.getElementById("report-picker").replaceChildren(...state.meta.reports.map((r) =>
    h("button", { type: "button", "aria-pressed": String(r.key === state.report),
      onclick: () => { state.report = r.key; state.expanded.clear(); renderPicker(); loadReport(); } }, r.title)));
}

function cell(col, value) {
  if (value == null || value === "") return h("td", {}, col.type === "text" ? "" : "—");
  if (col.type === "money") return h("td", { className: value < 0 ? "neg" : "" }, money(value));
  if (col.type === "percent") return h("td", {}, `${value > 0 && col.key === "change" ? "+" : ""}${value}%`);
  return h("td", {}, value);
}

async function loadReport() {
  const p = new URLSearchParams();
  const scope = document.getElementById("r-scope").value;
  if (scope.startsWith("type:")) p.set("entity_type", scope.slice(5));
  if (scope.startsWith("entity:")) p.set("entity_id", scope.slice(7));
  const [start, end] = rangeDates(document.getElementById("r-range").value);
  if (start) p.set("start", start);
  if (end) p.set("end", end);
  const r = await api(`/api/reports/${state.report}?${p}`);
  document.getElementById("report-title").textContent = r.title;
  document.getElementById("report-desc").textContent = r.description;

  const table = document.getElementById("report-table");
  const head = h("thead", {}, h("tr", {}, r.columns.map((c) => h("th", {}, c.label))));
  const body = h("tbody");
  if (!r.rows.length) body.append(h("tr", {}, h("td", { colSpan: r.columns.length, className: "muted" }, "Nothing to show for this selection.")));
  r.rows.forEach((row, i) => {
    const id = `${i}:${row[r.columns[0].key]}`;
    const open = state.expanded.has(id);
    const kids = row.children || [];
    const tr = h("tr", { className: kids.length ? "parent" : "" },
      r.columns.map((c, ci) => {
        const td = cell(c, row[c.key]);
        if (ci === 0 && kids.length) td.prepend(h("span", { className: "caret" }, open ? "▾" : "▸"));
        return td;
      }));
    if (kids.length) tr.addEventListener("click", () => {
      open ? state.expanded.delete(id) : state.expanded.add(id);
      loadReport();
    });
    body.append(tr);
    if (open) for (const k of kids) body.append(h("tr", { className: "child" }, r.columns.map((c) => cell(c, k[c.key]))));
  });
  if (r.totals && r.rows.length) body.append(h("tr", { className: "total" }, r.columns.map((c) => cell(c, r.totals[c.key]))));
  table.replaceChildren(head, body);
}

document.getElementById("r-scope").addEventListener("change", guard(loadReport));
document.getElementById("r-range").addEventListener("change", guard(async (e) => {
  document.getElementById("r-custom").hidden = e.target.value !== "custom";
  await loadReport();
}));
for (const id of ["r-start", "r-end"]) document.getElementById(id).addEventListener("change", guard(loadReport));

// ------------------------------------------------------------ settings

function archiveButton(item, path) {
  return h("button", { type: "button", onclick: guard(async () => {
    await api(path, { method: "PATCH", body: { archived: !item.archived } });
    await refreshSettings();
  }) }, item.archived ? "Restore" : "Archive");
}

function renameInput(item, path, label) {
  return h("input", { value: item.name, "aria-label": label, onchange: guard(async (e) => {
    await api(path, { method: "PATCH", body: { name: e.target.value } });
    await refreshSettings();
    toast("Renamed");
  }) });
}

function renderSettings() {
  document.getElementById("entity-list").replaceChildren(...state.meta.entities.map((e) =>
    h("li", { className: e.archived ? "archived" : "" },
      renameInput(e, `/api/entities/${e.id}`, "Entity name"),
      h("select", { "aria-label": "Entity type", onchange: guard(async (ev) => {
        await api(`/api/entities/${e.id}`, { method: "PATCH", body: { type: ev.target.value } });
        await refreshSettings();
      }) }, state.meta.entity_types.map((t) => h("option", { value: t.code, selected: t.code === e.type }, t.label))),
      archiveButton(e, `/api/entities/${e.id}`))));

  document.getElementById("category-tree").replaceChildren(...state.meta.category_groups.map((g) =>
    h("div", { className: "group" },
      h("div", { className: "group-head" + (g.archived ? " archived" : "") },
        renameInput(g, `/api/category-groups/${g.id}`, "Group name"),
        archiveButton(g, `/api/category-groups/${g.id}`)),
      h("ul", { className: "settings-list" }, g.categories.map((c) =>
        h("li", { className: c.archived ? "archived" : "" },
          renameInput(c, `/api/categories/${c.id}`, "Category name"),
          h("select", { "aria-label": "Move to group", onchange: guard(async (ev) => {
            await api(`/api/categories/${c.id}`, { method: "PATCH", body: { group_id: Number(ev.target.value) } });
            await refreshSettings();
          }) }, state.meta.category_groups.map((og) => h("option", { value: og.id, selected: og.id === g.id }, og.name))),
          archiveButton(c, `/api/categories/${c.id}`)))),
      h("form", { className: "inline-form", onsubmit: guard(async (ev) => {
        ev.preventDefault();
        await api("/api/categories", { method: "POST", body: { group_id: g.id, name: ev.target.name.value } });
        await refreshSettings();
      }) }, h("input", { name: "name", placeholder: `New category in ${g.name}`, required: true }), h("button", { type: "submit" }, "Add")))));
}

async function refreshSettings() {
  await loadMeta();
  renderSettings();
}

document.getElementById("add-entity").addEventListener("submit", guard(async (e) => {
  e.preventDefault();
  await api("/api/entities", { method: "POST", body: { name: e.target.name.value, type: e.target.type.value } });
  e.target.reset();
  await refreshSettings();
}));
document.getElementById("add-group").addEventListener("submit", guard(async (e) => {
  e.preventDefault();
  await api("/api/category-groups", { method: "POST", body: { name: e.target.name.value } });
  e.target.reset();
  await refreshSettings();
}));

// ------------------------------------------------------------ tabs

function showTab(name) {
  for (const b of document.querySelectorAll(".tabs button")) b.setAttribute("aria-selected", String(b.dataset.tab === name));
  for (const s of document.querySelectorAll(".tab")) s.hidden = s.id !== `tab-${name}`;
  try { localStorage.setItem("tab", name); } catch {}
  if (name === "transactions") return loadTransactions();
  if (name === "reports") { renderPicker(); return loadReport(); }
  if (name === "settings") return renderSettings();
}

for (const b of document.querySelectorAll(".tabs button")) b.addEventListener("click", guard(() => showTab(b.dataset.tab)));

guard(async () => {
  await loadMeta();
  resetAddForm();
  let tab = "transactions";
  try { tab = localStorage.getItem("tab") || tab; } catch {}
  await showTab(tab);
})();
