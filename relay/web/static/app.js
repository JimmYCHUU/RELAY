/* RELAY dashboard */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  files: {},          // kind -> {path, name, sheets?}
  run: null,          // serialized run payload
  filter: "all",
  reviewMode: "list", // "list" (master-detail) | "table"
  selectedRow: null,  // row.no highlighted in the list
  editing: null,      // {rowNo, slot}
  collecting: { x: false, fb: false },  // both can run at once — independent browsers
  freshCells: new Set(),
};

const SLOT_LABELS = { fb1: "FB 1", fb2: "FB 2", fb3: "FB 3", x: "X", ig: "IG" };
const PLATFORM_LABELS = { fb1: "FB · Main", fb2: "FB · Shongbad", fb3: "FB · Subpage", x: "X / Twitter", ig: "Instagram" };
const icon = (id) => `<svg class="ic-svg" aria-hidden="true"><use href="#${id}"/></svg>`;
const fmt = (n) => n == null ? "—" : n.toLocaleString("en-US");
const fmtShort = (n) => {
  if (n == null) return "—";
  if (n >= 1e6) return (n / 1e6).toFixed(2).replace(/\.?0+$/, "") + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.?0+$/, "") + "K";
  return String(n);
};

/* ═════════ navigation ═════════ */
const VIEW_TITLES = { dashboard: "Dashboard", inputs: "Data Sources", review: "Match Review",
                      report: "Reports", accounts: "Accounts" };
function showView(id) {
  $$(".view").forEach((v) => { v.hidden = v.id !== `view-${id}`; });
  $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === id));
  $("#tbTitle").textContent = VIEW_TITLES[id] || "RELAY";
  $("#crumbView").textContent = VIEW_TITLES[id] || id;
  if (id === "dashboard") renderDashboard();
  if (id === "report") renderReport();
  if (id === "accounts") refreshMetaStatus();
  window.scrollTo({ top: 0 });
}
$$(".nav-item").forEach((b) => b.addEventListener("click", () => {
  if (b.hasAttribute("data-locked")) return;
  showView(b.dataset.view);
}));
// mouse clicks shouldn't leave a keyboard-focus ring on toggles; Tab focus is unaffected
document.addEventListener("pointerdown", (e) => {
  if (e.target.closest(".nav-item, .tab, .chip-filter, .qa")) e.preventDefault();
});
document.addEventListener("click", (e) => {
  const go = e.target.closest("[data-goto-view]");
  if (go) {
    showView(go.dataset.gotoView);
    if (go.hasAttribute("data-open-cc")) $("#ccPanel").open = true;
  }
});
function unlockViews() {
  $$(".nav-item[data-locked]").forEach((b) => b.removeAttribute("data-locked"));
}

/* greeting */
(function greet() {
  const h = new Date().getHours();
  const word = h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  $("#greeting").textContent = `${word}, Asaj 👋`;
})();

/* ═════════ uploads ═════════ */
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
    guessBrand(data.name);
  }
  if (kind === "reference") $("#ccBtn").disabled = false;
  $("#runBtn").disabled = !state.files.campaign;
}

function guessBrand(filename) {
  const stop = /campaign|updated|photocard|fb|social|card|matched|_|\.xlsx/gi;
  const guess = filename.replace(stop, " ").replace(/['\d]/g, " ").trim().split(/\s+/).slice(0, 2).join(" ");
  const dl = $("#brandHints");
  dl.innerHTML = guess ? `<option value="${esc(guess)}">` : "";
  if (!$("#brand").value && guess) $("#brand").value = guess;
}

/* ═════════ run ═════════ */
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
    unlockViews();
    $("#exportBtn").disabled = false;
    $("#rangeText").textContent = `${state.run.brand} · ${state.run.month}`;
    $("#syncTitle").textContent = `${state.run.brand} · ${state.run.month}`;
    $("#syncSub").textContent = `${state.run.rows.length} content rows loaded`;
    renderReview();
    showView("review");
  } catch (e) {
    showError(e.message);
  } finally {
    $("#runBtn").disabled = false;
    $("#runBtn").textContent = "Run matching →";
  }
});
$("#newRunBtn").addEventListener("click", () => showView("inputs"));
$("#exportBtn").addEventListener("click", () => showView("report"));

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

/* ═════════ dashboard ═════════ */
function slotSums() {
  const sums = { fb1: 0, fb2: 0, fb3: 0, x: 0, ig: 0 };
  for (const row of state.run.rows) {
    for (const s of Object.keys(sums)) sums[s] += row.cells[s].value ?? 0;
  }
  return sums;
}

function matchStats() {
  // verified: clean caption match, scraped real value, or a human-entered one
  // estimated: recovered via the reactions × k heuristic — always marked ≈
  // missing: still needs review
  let verified = 0, estimated = 0, missing = 0;
  for (const row of state.run.rows) {
    for (const [slot, c] of Object.entries(row.cells)) {
      if (!row.links[slot]) continue;
      if (c.value == null) missing += 1;
      else if (c.provenance === "estimated") estimated += 1;
      else verified += 1;
    }
  }
  return { verified, estimated, missing, total: verified + estimated + missing };
}

function renderDashboard() {
  const has = !!state.run;
  $("#dashEmpty").hidden = has;
  $("#dashBody").hidden = !has;
  if (!has) return;

  const r = state.run;
  const sums = slotSums();
  const fbTotal = sums.fb1 + sums.fb2 + sums.fb3;
  const total = fbTotal + sums.x + sums.ig;
  const ms = matchStats();
  const matchRate = ms.total ? Math.round((ms.verified / ms.total) * 100) : 0;
  const review = state.run.rows.filter(needsAttention).length;

  $("#greetSub").textContent =
    `Here's the ${r.brand} · ${r.month} sponsored content performance.`;

  $("#kpiRow").innerHTML = [
    kpi(icon("i-package"), "ic-indigo", "Total Contents", String(r.rows.length), "photocards this month"),
    kpi(icon("i-eye"), "ic-blue", "Total Views", fmtShort(total), "all platforms, resolved"),
    kpi(icon("i-x"), "ic-navy", "X Impressions", fmtShort(sums.x),
      sums.x ? "real, scraped from X" : "not collected yet"),
    kpi(icon("i-target"), "ic-green", "Match Rate", `${matchRate}%`, "verified values, no estimates"),
    kpi(icon("i-alert"), "ic-amber", "Needs Review", String(review), review === 1 ? "content row" : "content rows"),
  ].join("");

  renderLineChart();
  renderPlatformSummary(sums);
  renderDonut(ms);
  renderTopContent();
  renderActivity();
}

function kpi(icon, cls, label, value, extra) {
  return `<div class="kpi"><div class="kpi-ic ${cls}">${icon}</div><div>
    <div class="kpi-label">${esc(label)}</div>
    <div class="kpi-value">${esc(value)}</div>
    <div class="kpi-extra">${esc(extra)}</div></div></div>`;
}

/* line chart: daily views per platform (real dates from the campaign sheet) */
const SERIES = [
  { key: "fb", label: "Facebook Views", css: "var(--fb)", slots: ["fb1", "fb2", "fb3"] },
  { key: "ig", label: "Instagram Views", css: "var(--igc)", slots: ["ig"] },
  { key: "x", label: "X Impressions", css: "var(--xc)", slots: ["x"] },
];

function dailySeries() {
  const byDay = new Map();
  for (const row of state.run.rows) {
    const day = row.date ? row.date.slice(0, 10) : null;
    if (!day) continue;
    if (!byDay.has(day)) byDay.set(day, { fb: 0, ig: 0, x: 0 });
    const agg = byDay.get(day);
    for (const s of SERIES) {
      for (const slot of s.slots) agg[s.key] += row.cells[slot].value ?? 0;
    }
  }
  return [...byDay.entries()].sort((a, b) => a[0] < b[0] ? -1 : 1);
}

function renderLineChart() {
  const days = dailySeries();
  const el = $("#lineChart");
  $("#lineLegend").innerHTML = SERIES.map((s) =>
    `<span><i class="sw" style="background:${s.css}"></i>${s.label}</span>`).join("");
  if (days.length < 2) {
    el.innerHTML = `<p class="hint">Not enough dated rows for a daily chart.</p>`;
    return;
  }
  const W = 760, H = 260, PL = 46, PR = 12, PT = 10, PB = 26;
  const iw = W - PL - PR, ih = H - PT - PB;
  const maxY = Math.max(1, ...days.flatMap(([, v]) => [v.fb, v.ig, v.x]));
  const x = (i) => PL + (i / (days.length - 1)) * iw;
  const y = (v) => PT + ih - (v / maxY) * ih;

  const ticks = 4;
  let g = "";
  for (let t = 0; t <= ticks; t++) {
    const yy = PT + (ih / ticks) * t;
    const val = maxY * (1 - t / ticks);
    g += `<line class="lc-grid" x1="${PL}" y1="${yy}" x2="${W - PR}" y2="${yy}"/>`;
    g += `<text class="lc-axis" x="${PL - 8}" y="${yy + 4}" text-anchor="end">${fmtShort(Math.round(val))}</text>`;
  }
  const labEvery = Math.ceil(days.length / 7);
  days.forEach(([d], i) => {
    if (i % labEvery) return;
    const dt = new Date(d + "T00:00:00");
    g += `<text class="lc-axis" x="${x(i)}" y="${H - 8}" text-anchor="middle">` +
         `${dt.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}</text>`;
  });

  let paths = "";
  for (const s of SERIES) {
    const pts = days.map(([, v], i) => `${x(i).toFixed(1)},${y(v[s.key]).toFixed(1)}`);
    if (s.key !== "x") {
      const area = `M${x(0)},${y(0) + 0} L${pts.join(" L")} L${x(days.length - 1)},${PT + ih} L${PL},${PT + ih} Z`;
      paths += `<path d="M${pts.join(" L")} L${x(days.length - 1).toFixed(1)},${(PT + ih).toFixed(1)} L${PL},${(PT + ih).toFixed(1)} Z" fill="${s.css}" opacity="0.07"/>`;
    }
    paths += `<path class="lc-line" stroke="${s.css}" d="M${pts.join(" L")}"/>`;
  }

  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
    ${g}${paths}
    <line id="lcCross" class="crosshair" y1="${PT}" y2="${PT + ih}" x1="-10" x2="-10"/>
    <rect id="lcHit" x="${PL}" y="${PT}" width="${iw}" height="${ih}" fill="transparent"/>
  </svg>`;

  const svg = el.querySelector("svg");
  const hit = el.querySelector("#lcHit");
  const cross = el.querySelector("#lcCross");
  hit.addEventListener("mousemove", (e) => {
    const box = svg.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    const i = Math.max(0, Math.min(days.length - 1, Math.round(((px - PL) / iw) * (days.length - 1))));
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i));
    const [d, v] = days[i];
    const dt = new Date(d + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "long" });
    showTip(e, `<strong>${dt}</strong>` + SERIES.map((s) =>
      `<div class="tt-row"><i class="sw" style="background:${s.css}"></i>${s.label}: ${fmt(v[s.key])}</div>`).join(""));
  });
  hit.addEventListener("mouseleave", () => { hideTip(); cross.setAttribute("x1", -10); cross.setAttribute("x2", -10); });
}

function renderPlatformSummary(sums) {
  const cov = state.run.coverage;
  const xReal = state.run.rows.some((r) => r.cells.x.provenance === "collected");
  const rows = [
    { ic: icon("i-facebook"), bg: "var(--fb)", name: "Facebook", sub: "Views", val: sums.fb1 + sums.fb2 + sums.fb3,
      cov: (cov.fb1 + cov.fb2 + cov.fb3) / 3 },
    { ic: icon("i-camera"), bg: "var(--igc)", name: "Instagram", sub: "Views", val: sums.ig, cov: cov.ig },
    { ic: icon("i-x"), bg: "var(--xc)", name: "X (Twitter)", sub: "Impressions", val: sums.x, cov: cov.x,
      badge: xReal ? { cls: "real", text: "real · scraped" } : { cls: "none", text: "not collected" } },
  ];
  $("#platformSummary").innerHTML = rows.map((r) => `
    <div class="ps-row">
      <div class="ps-ic" style="background:${r.bg}">${r.ic}</div>
      <div class="ps-name"><strong>${r.name}</strong><span class="sub">${r.sub}</span>
        ${r.badge ? `<span class="prov-badge ${r.badge.cls}">${r.badge.text}</span>` : ""}</div>
      <div style="text-align:right">
        <div class="ps-val">${fmtShort(r.val)}</div>
        <div class="ps-cov ${r.cov >= 0.85 ? "ok" : "low"}">${Math.round(r.cov * 100)}% filled</div>
      </div>
    </div>`).join("");
}

function renderDonut(ms) {
  const rate = ms.total ? Math.round((ms.verified / ms.total) * 100) : 0;
  const segs = [
    { label: "Matched — verified value", val: ms.verified, color: "var(--good)" },
    { label: "Estimated — reactions × k", val: ms.estimated, color: "var(--warning)" },
    { label: "Unmatched — needs review", val: ms.missing, color: "var(--critical)" },
  ];
  const C = 2 * Math.PI * 54;
  let off = 0, arcs = "";
  for (const s of segs) {
    const frac = ms.total ? s.val / ms.total : 0;
    const len = frac * C;
    arcs += `<circle r="54" cx="69" cy="69" fill="none" stroke="${s.color}"
      stroke-width="16" stroke-dasharray="${Math.max(len - 2, 0)} ${C - len + 2}"
      stroke-dashoffset="${-off}"/>`;
    off += len;
  }
  $("#donut").innerHTML = `<svg viewBox="0 0 138 138">${arcs}</svg>
    <div class="donut-center"><div><strong>${rate}%</strong><span class="sub">verified</span></div></div>`;
  $("#donutLegend").innerHTML = segs.map((s) => {
    const pct = ms.total ? ((s.val / ms.total) * 100).toFixed(1) : "0";
    return `<li><i class="dot" style="background:${s.color}"></i>${s.label}
      <span class="dl-val">${s.val} (${pct}%)</span></li>`;
  }).join("");
}

function rowStatus(row) {
  const cells = Object.entries(row.cells).filter(([slot]) => row.links[slot]);
  if (cells.some(([, c]) => c.value == null)) return "missing";
  if (cells.some(([, c]) => c.provenance === "estimated")) return "estimated";
  return "matched";
}

function renderTopContent() {
  const rows = state.run.rows.map((row) => ({
    row,
    total: Object.values(row.cells).reduce((a, c) => a + (c.value ?? 0), 0),
  })).sort((a, b) => b.total - a.total).slice(0, 5);
  const tips = { matched: "all values verified", estimated: "contains an estimate",
                 missing: "has unresolved cells" };
  $("#topContent").innerHTML = rows.map((r, i) => {
    const st = rowStatus(r.row);
    return `
    <li><span class="top-rank">${i + 1}</span>
      <i class="dot p-${st}" data-tip="${tips[st]}"></i>
      <span class="top-cap" title="${esc(r.row.caption)}">${esc(r.row.caption)}</span>
      <span class="top-val">${fmtShort(r.total)}</span></li>`;
  }).join("");
}

async function renderActivity() {
  let items = [];
  try {
    const runs = await (await fetch("/api/runs")).json();
    items = runs.slice(0, 5).map((r) => ({
      ic: icon(r.status === "generated" ? "i-doc" : "i-link"),
      title: r.status === "generated"
        ? `${r.brand} · ${r.month} — report generated`
        : `${r.brand} · ${r.month} — supervisor files matched`,
      sub: r.summary || (r.status === "generated"
        ? (r.output_file || "").split("/").pop() : "matching run saved"),
      time: new Date(r.created_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }),
    }));
  } catch { /* activity is optional */ }
  $("#activity").innerHTML = items.length ? items.map((a) => `
    <li><div class="act-ic">${a.ic}</div>
      <div class="act-body"><strong>${esc(a.title)}</strong><span class="sub">${esc(a.sub)}</span></div>
      <span class="act-time">${a.time}</span></li>`).join("")
    : `<li class="hint">No runs recorded yet.</li>`;
}

/* quick actions */
$("#qaCollectX").addEventListener("click", () => { showView("review"); startCollect("x"); });
$("#qaCollectFB").addEventListener("click", () => { showView("review"); startCollect("fb"); });

/* ═════════ review ═════════ */
$$(".chip-filter").forEach((b) => b.addEventListener("click", () => {
  $$(".chip-filter").forEach((x) => x.classList.remove("active"));
  b.classList.add("active");
  state.filter = b.dataset.filter;
  renderReviewBody();
}));

function needsAttention(row) {
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
  renderReviewBody();

  const issues = $("#issues");
  if (r.issues.length) {
    issues.hidden = false;
    issues.innerHTML = `<strong>Input notes</strong><ul>` +
      r.issues.map((i) => `<li>${esc(i.file)} · row ${i.row}: ${esc(i.reason)}</li>`).join("") + `</ul>`;
  } else issues.hidden = true;
}

function tile(label, value, extra, warn = false) {
  return `<div class="tile${warn ? " warn" : ""}"><div class="t-label">${esc(label)}</div>
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
  if (!rows.length) tbody.innerHTML = `<tr><td colspan="8" class="hint" style="padding:18px">Nothing needs attention 🎉</td></tr>`;
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
  // the ≈ mark travels with every heuristic value, here and in the workbook
  const approx = c.provenance === "estimated" ? "≈" : "";
  const val = c.value != null
    ? `<span class="val${fresh}${approx ? " est" : ""}">${approx}${fmt(c.value)}</span>`
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

/* ═════════ cell editor ═════════ */
const dialog = $("#cellDialog");
function openCellEditor(rowNo, slot) {
  state.editing = { rowNo, slot };
  const row = state.run.rows.find((r) => r.no === rowNo);
  const c = row.cells[slot];
  if (state.reviewMode === "list" && state.selectedRow !== rowNo) {
    state.selectedRow = rowNo;
    renderReviewList();
  }
  $("#cellTitle").textContent = `Row ${row.no} · ${SLOT_LABELS[slot]}`;
  $("#cellMeta").textContent = c.note || (c.value != null ? `current: ${fmt(c.value)} (${c.provenance})` : "no value yet");
  const link = $("#cellLink");
  link.hidden = !row.links[slot];
  if (row.links[slot]) link.href = row.links[slot];
  $("#reactions").value = "";
  $("#manualValue").value = c.value ?? "";
  dialog.showModal();
}
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".cell-edit");
  if (!btn) return;
  openCellEditor(+btn.dataset.row, btn.dataset.slot);
});

/* scan forward (wrapping) for the next linked cell that still has no value */
function nextMissingCell(fromRowNo, fromSlot) {
  const slots = ["fb1", "fb2", "fb3", "x", "ig"];
  const rows = state.run.rows;
  const startRow = rows.findIndex((r) => r.no === fromRowNo);
  const startSlot = slots.indexOf(fromSlot);
  for (let step = 1; step <= rows.length * slots.length; step++) {
    const flat = startRow * slots.length + startSlot + step;
    const row = rows[Math.floor(flat / slots.length) % rows.length];
    const slot = slots[flat % slots.length];
    if (row.links[slot] && row.cells[slot].value == null) return { rowNo: row.no, slot };
  }
  return null;
}

$$(".tab", dialog).forEach((t) => t.addEventListener("click", () => {
  $$(".tab", dialog).forEach((x) => x.classList.remove("active"));
  t.classList.add("active");
  $$(".tab-pane", dialog).forEach((p) => { p.hidden = p.dataset.pane !== t.dataset.tab; });
}));
$("#kSlider").addEventListener("input", () => { $("#kOut").textContent = $("#kSlider").value; });

dialog.addEventListener("close", async () => {
  const wantNext = dialog.returnValue === "apply-next";
  if ((dialog.returnValue !== "apply" && !wantNext) || !state.editing) return;
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
  if (wantNext) {
    const next = nextMissingCell(rowNo, slot);
    if (next) setTimeout(() => openCellEditor(next.rowNo, next.slot), 0);
  }
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

/* ═════════ collectors ═════════ */
$("#kCollect").addEventListener("input", () => {
  $("#kCollectOut").textContent = $("#kCollect").value;
  $("#kLabel").textContent = $("#kCollect").value;
});
$("#collectX").addEventListener("click", () => startCollect("x"));
$("#collectFB").addEventListener("click", () => startCollect("fb"));

const COLLECT_BTN = { x: "#collectX", fb: "#collectFB" };
function puEls(target) {
  const u = $(`.progress-unit[data-unit="${target}"]`);
  return { u, fill: $(".pu-fill", u), text: $(".pu-text", u),
           count: $(".pu-count", u), log: $(".pu-log", u), stop: $(".pu-stop", u) };
}

async function startCollect(target) {
  if (!state.run || state.collecting[target]) return;
  const body = { run_id: state.run.run_id, target, k: +$("#kCollect").value };
  const res = await fetch("/api/collect", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const errEl = $("#collectError");
  if (res.status === 412) {
    // No Meta session yet — open the sign-in browser automatically and
    // start collecting the moment the sign-in window is closed.
    await metaSignInThenCollect();
    return;
  }
  if (!res.ok) {
    errEl.textContent = await errText(res);
    errEl.hidden = false;
    return;
  }
  errEl.hidden = true;
  state.collecting[target] = true;
  $(COLLECT_BTN[target]).disabled = true;
  $("#collectProgress").hidden = false;
  const el = puEls(target);
  el.u.hidden = false;
  el.fill.style.width = "0%";
  el.text.textContent = target === "x"
    ? "Scraping public X pages (politely paced)…"
    : "Collecting Facebook via your Meta session…";
  el.count.textContent = "";
  el.log.innerHTML = "";
  el.stop.hidden = false;
  el.stop.disabled = false;
  pollCollect(target);
}

async function pollCollect(target) {
  const el = puEls(target);
  const res = await fetch(`/api/collect/${state.run.run_id}/${target}`);
  if (!res.ok) { finishCollect(target, "status check failed"); return; }
  const s = await res.json();
  if (s.state === "idle") { setTimeout(() => pollCollect(target), 1200); return; }

  if (s.run) {
    for (const row of s.run.rows) {
      const old = state.run.rows.find((r) => r.no === row.no);
      for (const slot of Object.keys(row.cells)) {
        if (row.cells[slot].value != null && old && old.cells[slot].value == null) {
          state.freshCells.add(`${row.no}:${slot}`);
        }
      }
    }
    // both pollers merge into state.run; each only adds cells its collector filled
    state.run = s.run;
  }
  const pct = s.total ? Math.round((s.done / s.total) * 100) : 0;
  el.fill.style.width = pct + "%";
  el.count.textContent = s.total ? `${s.done}/${s.total} visited · ${s.filled} filled` : "";
  if (s.events?.length) {
    el.log.innerHTML = s.events.slice().reverse()
      .map((e) => `<li>${esc(e)}</li>`).join("");
  }
  recomputeCoverage();
  renderReview();

  if (s.state === "running") {
    setTimeout(() => pollCollect(target), 2000);
  } else {
    finishCollect(target, s.message || s.state);
    if (s.state === "error") {
      const errEl = $("#collectError");
      errEl.textContent = s.message;
      errEl.hidden = false;
    }
  }
}

function finishCollect(target, message) {
  state.collecting[target] = false;
  $(COLLECT_BTN[target]).disabled = false;
  const el = puEls(target);
  el.stop.hidden = true;
  el.text.textContent = message;
  setTimeout(() => state.freshCells.clear(), 4000);
}

$$(".pu-stop").forEach((b) => b.addEventListener("click", async () => {
  const target = b.dataset.target;
  if (!state.run || !state.collecting[target]) return;
  b.disabled = true;
  puEls(target).text.textContent = "Stopping after the current post…";
  await fetch(`/api/collect/${state.run.run_id}/${target}/stop`, { method: "POST" });
}));

/* one-time Meta sign-in, launched straight from the Collect button */
async function metaSignInThenCollect() {
  const res = await fetch("/api/login/meta", { method: "POST" });
  const errEl = $("#collectError");
  if (!res.ok) { errEl.textContent = await errText(res); errEl.hidden = false; return; }
  errEl.hidden = true;
  $("#collectProgress").hidden = false;
  const el = puEls("fb");
  el.u.hidden = false;
  el.fill.style.width = "0%";
  el.count.textContent = "";
  el.log.innerHTML = "";
  el.stop.hidden = true;
  el.text.textContent =
    "A browser window opened on this machine — sign in to Facebook / Meta Business Suite " +
    "(2FA is fine), then close that window. Collection starts automatically.";
  $("#collectFB").disabled = true;

  const poll = async () => {
    const s = await (await fetch("/api/login/meta/status")).json();
    if (s.error) {
      $("#collectFB").disabled = false;
      el.text.textContent = "Sign-in did not complete.";
      errEl.textContent = s.error;
      errEl.hidden = false;
      return;
    }
    if (s.ready) {
      $("#collectFB").disabled = false;
      el.text.textContent = "Signed in — starting Facebook collection…";
      startCollect("fb");
      return;
    }
    setTimeout(poll, 2000);
  };
  poll();
}

/* ═════════ report ═════════ */
$("#toReport").addEventListener("click", () => showView("report"));

function renderReport() {
  if (!state.run) return;
  const r = state.run;
  const sums = slotSums();
  const fbTotal = sums.fb1 + sums.fb2 + sums.fb3;
  const grand = fbTotal + sums.x + sums.ig;
  const ms = matchStats();
  const est = r.rows.flatMap((row) => Object.values(row.cells)
    .filter((c) => c.provenance === "estimated")).length;

  $("#reportTiles").innerHTML = [
    tile(`${r.brand} · ${r.month}`, String(r.rows.length), "content rows"),
    tile("Total views", fmt(grand), "all platforms, resolved cells"),
    tile("Facebook", fmt(fbTotal), "links 1–3"),
    tile("Instagram", fmt(sums.ig), "views"),
    tile("Resolved", `${ms.verified + ms.estimated}/${ms.total}`, est ? `cells · ${est} estimated` : "cells",
      ms.missing > 0),
  ].join("");

  const chartRows = [
    ["FB · Main", sums.fb1], ["FB · Shongbad", sums.fb2], ["FB · Subpage", sums.fb3],
    ["Instagram", sums.ig], ["X / Twitter", sums.x],
  ];
  const max = Math.max(...chartRows.map(([, v]) => v), 1);
  $("#platformChart").innerHTML = chartRows.map(([label, v]) => {
    const pct = (v / max) * 100;
    const inside = pct > 82;
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
  $("#dlText").textContent = `Download ${data.name}`;
});

/* ═════════ cross-check ═════════ */
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
    <div class="table-wrap card" style="box-shadow:none"><table>
      <thead><tr><th>Row</th><th>Slot</th><th>RELAY</th><th>Reference</th><th>Status</th></tr></thead>
      <tbody>
        ${diffRows(cc.differs, "differs")}
        ${diffRows(cc.only_generated, "only RELAY")}
        ${diffRows(cc.only_reference, "only reference (manual recovery)")}
      </tbody>
    </table></div>` : `<p>Perfect match.</p>`}`;
});

/* ═════════ tooltip ═════════ */
const tooltip = $("#tooltip");
function showTip(e, html) {
  tooltip.innerHTML = html;
  tooltip.hidden = false;
  positionTip(e);
}
function hideTip() { tooltip.hidden = true; }
function positionTip(e) {
  const pad = 14;
  let x = e.clientX + pad, y = e.clientY + pad;
  const r = tooltip.getBoundingClientRect();
  if (x + r.width > innerWidth - 8) x = e.clientX - r.width - pad;
  if (y + r.height > innerHeight - 8) y = e.clientY - r.height - pad;
  tooltip.style.left = x + "px";
  tooltip.style.top = y + "px";
}
document.addEventListener("mousemove", (e) => {
  const t = e.target.closest("[data-tip]");
  if (t) { showTip(e, esc(t.dataset.tip)); return; }
  if (!e.target.closest("#lcHit")) hideTip();
});

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

/* ═════════ review body: master–detail list or table ═════════ */
const SLOT_META = {
  fb1: { icon: "i-facebook", bg: "var(--fb)" },
  fb2: { icon: "i-facebook", bg: "var(--fb)" },
  fb3: { icon: "i-facebook", bg: "var(--fb)" },
  x:   { icon: "i-x",        bg: "var(--xc)" },
  ig:  { icon: "i-camera",   bg: "var(--igc)" },
};
const STATUS_CHIP = {
  matched:   ["pc-matched", "verified"],
  estimated: ["pc-estimated", "estimated"],
  missing:   ["pc-missing", "needs review"],
};

function filteredRows() {
  return state.run.rows.filter((r) => state.filter === "all" || needsAttention(r));
}

function updateFilterCounts() {
  $("#countAll").textContent = state.run.rows.length;
  $("#countAttn").textContent = state.run.rows.filter(needsAttention).length;
}

function renderReviewBody() {
  updateFilterCounts();
  const table = state.reviewMode === "table";
  $("#reviewSplit").hidden = table;
  $("#tableWrap").hidden = !table;
  if (table) renderReviewRows(); else renderReviewList();
}

function setReviewMode(mode) {
  state.reviewMode = mode;
  $("#modeList").classList.toggle("active", mode === "list");
  $("#modeTable").classList.toggle("active", mode === "table");
  if (state.run) renderReviewBody();
}
$("#modeList").addEventListener("click", () => setReviewMode("list"));
$("#modeTable").addEventListener("click", () => setReviewMode("table"));

function miniRing(filled, linked, status) {
  const R = 12, C = 2 * Math.PI * R;
  const frac = linked ? filled / linked : 0;
  const color = status === "matched" ? "var(--good)"
    : status === "estimated" ? "var(--warning)" : "var(--critical)";
  return `<span class="mini-ring" aria-hidden="true">
    <svg width="30" height="30" viewBox="0 0 30 30">
      <circle r="${R}" cx="15" cy="15" fill="none" stroke="var(--grid)" stroke-width="3"/>
      <circle r="${R}" cx="15" cy="15" fill="none" stroke="${color}" stroke-width="3"
        stroke-linecap="round" stroke-dasharray="${(frac * C).toFixed(1)} ${C.toFixed(1)}"/>
    </svg>
    <span class="mr-n">${filled}/${linked}</span>
  </span>`;
}

function renderReviewList() {
  const rows = filteredRows();
  const list = $("#reviewList");
  if (!rows.length) {
    list.innerHTML = `<div class="rlist-empty">Nothing needs attention 🎉</div>`;
    $("#reviewDetail").innerHTML = "";
    return;
  }
  if (!rows.some((r) => r.no === state.selectedRow)) state.selectedRow = rows[0].no;
  list.innerHTML = rows.map((row) => {
    const linked = Object.keys(row.cells).filter((s) => row.links[s]);
    const filled = linked.filter((s) => row.cells[s].value != null).length;
    const st = rowStatus(row);
    const [chipCls, chipLabel] = STATUS_CHIP[st];
    const date = row.date
      ? new Date(row.date).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "—";
    return `<button class="rcard${row.no === state.selectedRow ? " selected" : ""}" data-no="${row.no}">
      <span class="rcard-top"><span>№ ${row.no}</span><span>${esc(date)}</span></span>
      <span class="rcard-cap" title="${esc(row.caption)}">${esc(row.caption)}</span>
      <span class="rcard-foot">
        <span class="prov-chip ${chipCls}">${chipLabel}</span>
        ${miniRing(filled, linked.length, st)}
      </span>
    </button>`;
  }).join("");
  renderReviewDetail();
}

$("#reviewList").addEventListener("click", (e) => {
  const card = e.target.closest(".rcard");
  if (!card) return;
  state.selectedRow = +card.dataset.no;
  renderReviewList();
});

function renderReviewDetail() {
  const row = state.run.rows.find((r) => r.no === state.selectedRow);
  const el = $("#reviewDetail");
  if (!row) { el.innerHTML = ""; return; }
  const st = rowStatus(row);
  const [chipCls, chipLabel] = STATUS_CHIP[st];
  const date = row.date
    ? new Date(row.date).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }) : "no date";
  el.innerHTML = `
    <h3 class="rd-cap">${esc(row.caption)}</h3>
    <div class="rd-meta">
      <span class="sub">№ ${row.no} · ${esc(date)}</span>
      <span class="prov-chip ${chipCls}">${chipLabel}</span>
    </div>
    ${["fb1", "fb2", "fb3", "x", "ig"].map((slot) => slotRowHtml(row, slot)).join("")}`;
}

function slotRowHtml(row, slot) {
  const meta = SLOT_META[slot];
  const link = row.links[slot];
  const c = row.cells[slot];
  const name = PLATFORM_LABELS[slot];
  if (!link) {
    return `<div class="slot-row" style="opacity:.45">
      <div class="slot-ic" style="background:${meta.bg}"><svg class="ic-svg"><use href="#${meta.icon}"/></svg></div>
      <div class="slot-name"><strong>${esc(name)}</strong><span class="sub">no link in the campaign sheet</span></div>
    </div>`;
  }
  const dot = `<i class="dot p-${c.value == null ? "missing" : c.provenance}" data-tip="${esc(provTip(c))}"></i>`;
  const conf = c.value != null && c.confidence < 0.95
    ? `<span class="conf-badge" data-tip="${esc(c.note || "low confidence")}">check</span>` : "";
  const fresh = state.freshCells.has(`${row.no}:${slot}`) ? " freshly" : "";
  const approx = c.provenance === "estimated" ? "≈" : "";
  const val = c.value != null
    ? `<span class="val${fresh}${approx ? " est" : ""}">${approx}${fmt(c.value)}</span>`
    : `<span class="noval">missing</span>`;
  return `<div class="slot-row">
    <div class="slot-ic" style="background:${meta.bg}"><svg class="ic-svg"><use href="#${meta.icon}"/></svg></div>
    <div class="slot-name"><strong>${esc(name)}</strong>
      <span class="sub">${esc(c.value != null ? c.provenance : "unresolved")}</span></div>
    <div class="slot-val">${dot}${val}${conf}
      <button class="cell-edit" data-row="${row.no}" data-slot="${slot}" title="Estimate or enter manually">✎ edit</button>
    </div>
    <a class="iconlink" href="${esc(link)}" target="_blank" rel="noopener">
      <svg class="ic-svg"><use href="#i-external"/></svg> post</a>
  </div>`;
}

/* ═════════ accounts ═════════ */
async function refreshMetaStatus() {
  const pill = $("#metaStatus"), btn = $("#metaConnect"), hint = $("#metaHint");
  try {
    const s = await (await fetch("/api/login/meta/status")).json();
    if (s.running) {
      pill.textContent = "sign-in window open";
      pill.className = "acct-pill warn";
      btn.disabled = true;
      hint.textContent = "Finish signing in, then close that browser window.";
      setTimeout(() => { if (!$("#view-accounts").hidden) refreshMetaStatus(); }, 2000);
    } else if (s.ready) {
      pill.textContent = "connected";
      pill.className = "acct-pill ok";
      btn.disabled = true;
      btn.textContent = "Session stored";
      hint.textContent = "Collectors will scrape through this session.";
    } else {
      pill.textContent = "not connected";
      pill.className = "acct-pill";
      btn.disabled = false;
      btn.textContent = "Connect Meta account";
      hint.textContent = s.error || "";
    }
  } catch {
    pill.textContent = "status unavailable";
    pill.className = "acct-pill";
  }
}
$("#metaConnect").addEventListener("click", async () => {
  const res = await fetch("/api/login/meta", { method: "POST" });
  if (!res.ok) $("#metaHint").textContent = await errText(res);
  refreshMetaStatus();
});

/* ═════════ theme ═════════ */
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem("relay-theme", t);
  $("use", $("#themeBtn")).setAttribute("href", t === "dark" ? "#i-sun" : "#i-moon");
}
applyTheme(document.documentElement.dataset.theme || "light");
$("#themeBtn").addEventListener("click", () =>
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
