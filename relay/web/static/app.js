/* RELAY dashboard */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  files: {},          // kind -> {path, name, sheets?}
  run: null,          // serialized run payload
  filter: "all",
  editing: null,      // {rowNo, slot}
  collecting: null,   // "x" | "fb" while a job runs
  freshCells: new Set(),  // "rowNo:slot" recently filled by a collector
};

const SLOT_LABELS = { fb1: "FB 1", fb2: "FB 2", fb3: "FB 3", x: "X", ig: "IG" };
const PLATFORM_LABELS = { fb1: "FB · Main", fb2: "FB · Shongbad", fb3: "FB · Subpage", x: "X / Twitter", ig: "Instagram" };
const fmt = (n) => n == null ? "—" : n.toLocaleString("en-US");

/* ── uploads ─────────────────────────────────────────────── */
const fileInput = $("#fileInput");
let pendingKind = null;

$$(".drop").forEach((zone) => {
  zone.addEventListener("click", () => { pendingKind = zone.dataset.kind; fileInput.click(); });
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("dragover"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault(); zone.classList.remove("dragover");
    if (e.dataTransfer.files[0]) uploadFile(zone.dataset.kind, e.dataTransfer.files[0]);
  });
});
fileInput.addEventListener("change", () => {
  if (fileInput.files[0] && pendingKind) uploadFile(pendingKind, fileInput.files[0]);
  fileInput.value = "";
});

async function uploadFile(kind, file) {
  const fd = new FormData();
  fd.append("kind", kind);
  fd.append("file", file);
  const res = await fetch("/api/upload", { method: "POST", body: fd });
  if (!res.ok) { showError(await errText(res)); return; }
  const data = await res.json();
  state.files[kind] = data;
  const zone = $(`.drop[data-kind="${kind}"]`);
  zone.classList.add("filled");
  $(".file-name", zone).textContent = data.name;

  if (kind === "campaign") {
    const sel = $("#sheet");
    sel.innerHTML = data.sheets.map((s) => `<option>${esc(s)}</option>`).join("");
    sel.disabled = false;
    guessBrand(data.name, data.sheets);
  }
  if (kind === "reference") $("#ccBtn").disabled = false;
  $("#runBtn").disabled = !state.files.campaign;
}

function guessBrand(filename, sheets) {
  const stop = /campaign|updated|photocard|fb|social|card|matched|_|\.xlsx/gi;
  const guess = filename.replace(stop, " ").replace(/['\d]/g, " ").trim().split(/\s+/).slice(0, 2).join(" ");
  const dl = $("#brandHints");
  dl.innerHTML = "";
  if (guess) dl.innerHTML = `<option value="${esc(guess)}">`;
  if (!$("#brand").value && guess) $("#brand").value = guess;
}

/* ── run ─────────────────────────────────────────────────── */
$("#runBtn").addEventListener("click", async () => {
  const body = {
    campaign: state.files.campaign.path,
    sheet: $("#sheet").value,
    brand: $("#brand").value.trim() || "SPONSOR",
    mainpage: state.files.mainpage?.path ?? null,
    subpage: state.files.subpage?.path ?? null,
    insta: state.files.insta?.path ?? null,
  };
  $("#runBtn").disabled = true;
  $("#runBtn").textContent = "Matching…";
  try {
    const res = await fetch("/api/run", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await errText(res));
    state.run = await res.json();
    enterStage("review");
    renderReview();
  } catch (e) {
    showError(e.message);
  } finally {
    $("#runBtn").disabled = false;
    $("#runBtn").textContent = "Run matching";
  }
});

function showError(msg) {
  const el = $("#runError");
  el.textContent = msg;
  el.hidden = false;
  setTimeout(() => { el.hidden = true; }, 8000);
}
async function errText(res) {
  try { const j = await res.json(); return j.detail || res.statusText; }
  catch { return res.statusText; }
}

/* ── stages ──────────────────────────────────────────────── */
function enterStage(id) {
  $$(".stage").forEach((s) => { s.hidden = s.id !== id; });
  $$("#stepNav .step").forEach((b) => {
    b.classList.toggle("active", b.dataset.goto === id);
    if (state.run) b.disabled = false;
  });
  if (id === "report") renderReport();
  window.scrollTo({ top: 0 });
}
$$("#stepNav .step").forEach((b) =>
  b.addEventListener("click", () => !b.disabled && enterStage(b.dataset.goto)));
$("#toReport").addEventListener("click", () => enterStage("report"));

/* ── review stage ────────────────────────────────────────── */
$$(".chip-filter").forEach((b) => b.addEventListener("click", () => {
  $$(".chip-filter").forEach((x) => x.classList.remove("active"));
  b.classList.add("active");
  state.filter = b.dataset.filter;
  renderReviewRows();
}));

function needsAttention(row) {
  // X cells stay empty until collectors run — don't flag every row for them
  return Object.entries(row.cells).some(([slot, c]) =>
    (slot !== "x" && row.links[slot] && c.value == null) ||
    (c.value != null && c.confidence < 0.95));
}

function renderReview() {
  const r = state.run;
  const tiles = [];
  for (const [slot, frac] of Object.entries(r.coverage)) {
    if (slot === "x" && !r.rows.some((row) => row.links.x)) continue;
    tiles.push(tile(PLATFORM_LABELS[slot], `${Math.round(frac * 100)}%`,
      "of linked cells filled", frac < 0.6));
  }
  const attention = r.rows.filter(needsAttention).length;
  tiles.push(tile("Needs attention", String(attention), attention === 1 ? "row" : "rows", attention > 0));
  $("#coverageTiles").innerHTML = tiles.join("");
  renderReviewRows();

  const issues = $("#issues");
  if (r.issues.length) {
    issues.hidden = false;
    issues.innerHTML = `<strong>Input notes</strong><ul>` +
      r.issues.map((i) => `<li>${esc(i.file)} · row ${i.row}: ${esc(i.reason)}</li>`).join("") + `</ul>`;
  } else issues.hidden = true;
}

function tile(label, value, extra, warn = false) {
  return `<div class="tile"><div class="t-label">${esc(label)}</div>
    <div class="t-value${warn ? " warn" : ""}">${esc(value)}</div>
    <div class="t-extra">${esc(extra)}</div></div>`;
}

function renderReviewRows() {
  const tbody = $("#reviewTable tbody");
  const rows = state.run.rows.filter((r) => state.filter === "all" || needsAttention(r));
  tbody.innerHTML = rows.map((row) => {
    const date = row.date ? new Date(row.date).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "—";
    return `<tr>
      <td class="num">${row.no}</td>
      <td class="num">${esc(date)}</td>
      <td class="caption"><span class="cap-text" title="${esc(row.caption)}">${esc(row.caption)}</span></td>
      ${["fb1", "fb2", "fb3", "x", "ig"].map((slot) => cellHtml(row, slot)).join("")}
    </tr>`;
  }).join("");
  if (!rows.length) tbody.innerHTML = `<tr><td colspan="8" class="noval">Nothing needs attention 🎉</td></tr>`;
}

function cellHtml(row, slot) {
  const link = row.links[slot];
  const c = row.cells[slot];
  if (!link) return `<td class="num nolink" aria-label="no link">·</td>`;
  const dot = `<i class="dot p-${c.value == null ? "missing" : c.provenance}"
      data-tip="${esc(provTip(c))}"></i>`;
  const conf = c.value != null && c.confidence < 0.95
    ? `<span class="conf-badge" data-tip="${esc(c.note || "low confidence")}">check</span>` : "";
  const fresh = state.freshCells.has(`${row.no}:${slot}`) ? " freshly" : "";
  const val = c.value != null
    ? `<span class="val${fresh}">${fmt(c.value)}</span>`
    : `<span class="noval">missing</span>`;
  return `<td class="num"><span class="cellv">${dot}${val}${conf}
    <button class="cell-edit" data-row="${row.no}" data-slot="${slot}" title="Estimate or enter manually">✎</button>
  </span></td>`;
}

function provTip(c) {
  const parts = [`${c.provenance}${c.confidence < 1 ? ` · confidence ${c.confidence}` : ""}`];
  if (c.note) parts.push(c.note);
  return parts.join(" — ");
}

/* ── cell editor dialog ──────────────────────────────────── */
const dialog = $("#cellDialog");
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".cell-edit");
  if (!btn) return;
  state.editing = { rowNo: +btn.dataset.row, slot: btn.dataset.slot };
  const row = state.run.rows.find((r) => r.no === state.editing.rowNo);
  const c = row.cells[state.editing.slot];
  $("#cellTitle").textContent = `Row ${row.no} · ${SLOT_LABELS[state.editing.slot]}`;
  $("#cellMeta").textContent = c.note || (c.value != null ? `current: ${fmt(c.value)} (${c.provenance})` : "no value yet");
  $("#reactions").value = "";
  $("#manualValue").value = c.value ?? "";
  dialog.showModal();
});

$$(".tab", dialog).forEach((t) => t.addEventListener("click", () => {
  $$(".tab", dialog).forEach((x) => x.classList.remove("active"));
  t.classList.add("active");
  $$(".tab-pane", dialog).forEach((p) => { p.hidden = p.dataset.pane !== t.dataset.tab; });
}));
$("#kSlider").addEventListener("input", () => { $("#kOut").textContent = $("#kSlider").value; });

dialog.addEventListener("close", async () => {
  if (dialog.returnValue !== "apply" || !state.editing) return;
  const { rowNo, slot } = state.editing;
  const activeTab = $(".tab.active", dialog).dataset.tab;
  let url, body;
  if (activeTab === "estimate") {
    const reactions = parseInt($("#reactions").value, 10);
    if (!Number.isFinite(reactions)) return;
    url = "/api/estimate";
    body = { run_id: state.run.run_id, row_no: rowNo, slot, reactions, k: +$("#kSlider").value };
  } else {
    const value = $("#manualValue").value === "" ? null : parseInt($("#manualValue").value, 10);
    url = "/api/override";
    body = { run_id: state.run.run_id, row_no: rowNo, slot, value };
  }
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) { showError(await errText(res)); return; }
  const cell = await res.json();
  const row = state.run.rows.find((r) => r.no === rowNo);
  row.cells[slot] = cell;
  recomputeCoverage();
  renderReview();
});

function recomputeCoverage() {
  const cov = {};
  for (const slot of ["fb1", "fb2", "fb3", "x", "ig"]) {
    const linked = state.run.rows.filter((r) => r.links[slot]);
    cov[slot] = linked.length
      ? linked.filter((r) => r.cells[slot].value != null).length / linked.length : 1;
  }
  state.run.coverage = cov;
}

/* ── collectors ──────────────────────────────────────────── */
$("#kCollect").addEventListener("input", () => {
  $("#kCollectOut").textContent = $("#kCollect").value;
  $("#kLabel").textContent = $("#kCollect").value;
});
$("#collectX").addEventListener("click", () => startCollect("x"));
$("#collectFB").addEventListener("click", () => startCollect("fb"));

async function startCollect(target) {
  if (state.collecting) return;
  const body = { run_id: state.run.run_id, target, k: +$("#kCollect").value };
  const res = await fetch("/api/collect", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const errEl = $("#collectError");
  if (!res.ok) {
    errEl.textContent = await errText(res);
    errEl.hidden = false;
    return;
  }
  errEl.hidden = true;
  state.collecting = target;
  $("#collectX").disabled = $("#collectFB").disabled = true;
  const box = $("#collectProgress");
  box.hidden = false;
  $("#progressFill").style.width = "0%";
  $("#progressText").textContent = target === "x"
    ? "Scraping public X pages (politely paced)…"
    : "Collecting Facebook via your Meta session…";
  $("#progressCount").textContent = "";
  $("#progressLog").innerHTML = "";
  pollCollect(target);
}

async function pollCollect(target) {
  const res = await fetch(`/api/collect/${state.run.run_id}/${target}`);
  if (!res.ok) { finishCollect("status check failed"); return; }
  const s = await res.json();
  if (s.state === "idle") { setTimeout(() => pollCollect(target), 1200); return; }

  if (s.run) {
    // mark cells that newly gained a value so they pop in the table
    for (const row of s.run.rows) {
      const old = state.run.rows.find((r) => r.no === row.no);
      for (const slot of Object.keys(row.cells)) {
        if (row.cells[slot].value != null && old && old.cells[slot].value == null) {
          state.freshCells.add(`${row.no}:${slot}`);
        }
      }
    }
    state.run = s.run;
  }
  const pct = s.total ? Math.round((s.done / s.total) * 100) : 0;
  $("#progressFill").style.width = pct + "%";
  $("#progressCount").textContent = s.total ? `${s.done}/${s.total} visited · ${s.filled} filled` : "";
  if (s.events?.length) {
    $("#progressLog").innerHTML = s.events.slice().reverse()
      .map((e) => `<li>${esc(e)}</li>`).join("");
  }
  recomputeCoverage();
  renderReview();

  if (s.state === "running") {
    setTimeout(() => pollCollect(target), 2000);
  } else {
    finishCollect(s.message || s.state);
    if (s.state === "error" || s.state === "stopped") {
      const errEl = $("#collectError");
      errEl.textContent = s.message;
      errEl.hidden = false;
    }
  }
}

function finishCollect(message) {
  state.collecting = null;
  $("#collectX").disabled = $("#collectFB").disabled = false;
  $("#progressText").textContent = message;
  setTimeout(() => state.freshCells.clear(), 4000);
}

/* ── report stage ────────────────────────────────────────── */
function renderReport() {
  const r = state.run;
  const sums = {};
  for (const slot of ["fb1", "fb2", "fb3", "x", "ig"]) {
    sums[slot] = r.rows.reduce((a, row) => a + (row.cells[slot].value ?? 0), 0);
  }
  const fbTotal = sums.fb1 + sums.fb2 + sums.fb3;
  const grand = fbTotal + sums.x + sums.ig;
  const filled = r.rows.flatMap((row) => Object.entries(row.cells)
    .filter(([slot, c]) => row.links[slot])).length;
  const resolved = r.rows.flatMap((row) => Object.entries(row.cells)
    .filter(([slot, c]) => row.links[slot] && c.value != null)).length;
  const est = r.rows.flatMap((row) => Object.values(row.cells)
    .filter((c) => c.provenance === "estimated")).length;

  $("#reportTiles").innerHTML = [
    tile(`${r.brand} · ${r.month}`, String(r.rows.length), "content rows"),
    tile("Total views", fmt(grand), "all platforms, resolved cells"),
    tile("Facebook", fmt(fbTotal), "links 1–3"),
    tile("Instagram", fmt(sums.ig), "views"),
    tile("Resolved", `${resolved}/${filled}`, est ? `cells · ${est} estimated` : "cells", resolved < filled),
  ].join("");

  const chartRows = [
    ["FB · Main", sums.fb1], ["FB · Shongbad", sums.fb2], ["FB · Subpage", sums.fb3],
    ["Instagram", sums.ig], ["X / Twitter", sums.x],
  ];
  const max = Math.max(...chartRows.map(([, v]) => v), 1);
  $("#platformChart").innerHTML = chartRows.map(([label, v]) => {
    const pct = (v / max) * 100;
    const inside = pct > 82;   // long bars label inside; short ones at the bar end
    return `
    <div class="hbar-row">
      <div class="hbar-label">${esc(label)}</div>
      <div class="hbar-track">
        <span class="hbar-baseline"></span>
        <div class="hbar-fill" style="width:${pct}%" data-tip="${esc(label)}: ${fmt(v)} views"></div>
        <span class="hbar-val${inside ? " inside" : ""}"
              style="${inside ? `right:${100 - pct}%` : `left:${pct}%`}">${fmt(v)}</span>
      </div>
    </div>`;
  }).join("");
}

$("#genBtn").addEventListener("click", async () => {
  const res = await fetch(`/api/report/${state.run.run_id}?comments=${$("#commentsToggle").checked}`, { method: "POST" });
  if (!res.ok) { showError(await errText(res)); return; }
  const data = await res.json();
  const dl = $("#dlBtn");
  dl.hidden = false;
  dl.href = `/api/report/${state.run.run_id}/download`;
  dl.textContent = `Download ${data.name}`;
});

/* ── cross-check ─────────────────────────────────────────── */
$("#ccBtn").addEventListener("click", async () => {
  const ref = state.files.reference;
  if (!ref) return;
  const res = await fetch("/api/crosscheck", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: state.run.run_id, reference: ref.path }),
  });
  if (!res.ok) { showError(await errText(res)); return; }
  const cc = await res.json();
  const el = $("#ccResult");
  el.hidden = false;
  const diffRows = (list, kind) => list.map((d) =>
    `<tr><td class="num">${d.row_no}</td><td>${SLOT_LABELS[d.slot]}</td>
     <td class="num">${fmt(d.generated)}</td><td class="num">${fmt(d.reference)}</td><td>${kind}</td></tr>`).join("");
  el.innerHTML = `
    <p><span class="cc-acc">${(cc.accuracy * 100).toFixed(1)}%</span>
       &nbsp;${cc.equal} of ${cc.cells} comparable cells identical</p>
    ${cc.differs.length + cc.only_generated.length + cc.only_reference.length ? `
    <div class="table-wrap"><table>
      <thead><tr><th>Row</th><th>Slot</th><th>RELAY</th><th>Reference</th><th>Status</th></tr></thead>
      <tbody>
        ${diffRows(cc.differs, "differs")}
        ${diffRows(cc.only_generated, "only RELAY")}
        ${diffRows(cc.only_reference, "only reference (manual recovery)")}
      </tbody>
    </table></div>` : `<p>Perfect match.</p>`}`;
});

/* ── tooltip ─────────────────────────────────────────────── */
const tooltip = $("#tooltip");
document.addEventListener("mousemove", (e) => {
  const t = e.target.closest("[data-tip]");
  if (!t) { tooltip.hidden = true; return; }
  tooltip.textContent = t.dataset.tip;
  tooltip.hidden = false;
  const pad = 12;
  let x = e.clientX + pad, y = e.clientY + pad;
  const r = tooltip.getBoundingClientRect();
  if (x + r.width > innerWidth - 8) x = e.clientX - r.width - pad;
  if (y + r.height > innerHeight - 8) y = e.clientY - r.height - pad;
  tooltip.style.left = x + "px";
  tooltip.style.top = y + "px";
});

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}
