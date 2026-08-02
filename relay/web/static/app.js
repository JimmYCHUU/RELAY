/* RELAY dashboard */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  files: {},          // kind -> {path, name, sheets?}
  pending: [],        // brands staged for this cycle: {campaign, brand, sheets, merge}
  runs: [],           // every tab's run in the cycle — matching is always per tab
  /* One delivered workbook each: {brand, label, run_ids}. A brand whose tabs
     were ticked together is one group of several runs; everything else is a
     group of one. Reporting works off these, matching and review off `runs`. */
  groups: [],
  run: null,          // the ACTIVE run — all per-brand renderers read this
  dashSel: "all",     // dashboard scope: "all" | run index
  filter: "all",
  reviewMode: "table", // "table" (flat row list, default) | "list" (master-detail)
  selectedRow: null,  // row.no highlighted in the list
  editing: null,      // {rowNo, slot}
  collecting: { fb: false, ig: false, x: false },  // can run at once — independent browsers
  autopilot: false,   // hands-free cycle running — excludes the manual collect buttons
  freshCells: new Set(),
};

const SLOT_LABELS = { fb1: "FB 1", fb2: "FB 2", fb3: "FB 3", x: "X", ig: "IG" };
const PLATFORM_LABELS = { fb1: "FB · Main", fb2: "FB · Shongbad", fb3: "FB · Subpage", x: "X / Twitter", ig: "Instagram" };
const icon = (id) => `<svg class="ic-svg" aria-hidden="true"><use href="#${id}"/></svg>`;
const capText = (row) => row.caption || "(no caption — see the post)";
/* The sheet's caption is kept whenever RELAY replaced it with the post's own,
   so the person reconciling the two can always see what the sheet still says. */
const capBadge = (row) => row.original_caption
  ? ` <span class="conf-badge" data-tip="${esc("RELAY read this caption from the live post. The campaign sheet still says: " + row.original_caption)}">updated</span>`
  : "";
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

// Insights takes one export per page, so its zone accepts several files at
// once and accumulates them; every other zone holds exactly one.
const isMulti = (kind) => !!$(`.drop[data-kind="${kind}"]`)?.dataset.multi;

async function uploadMany(kind, files) {
  for (const f of files) await uploadFile(kind, f);
}

$$(".drop").forEach((zone) => {
  zone.addEventListener("click", () => {
    pendingKind = zone.dataset.kind;
    fileInput.multiple = !!zone.dataset.multi;
    fileInput.click();
  });
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("dragover"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault(); zone.classList.remove("dragover");
    const files = [...e.dataTransfer.files];
    if (!files.length) return;
    uploadMany(zone.dataset.kind, zone.dataset.multi ? files : files.slice(0, 1));
  });
});
fileInput.addEventListener("change", () => {
  const files = [...fileInput.files];
  if (files.length && pendingKind) {
    uploadMany(pendingKind, isMulti(pendingKind) ? files : files.slice(0, 1));
  }
  fileInput.value = "";
});

async function uploadFile(kind, file) {
  const fd = new FormData();
  fd.append("kind", kind);
  fd.append("file", file);
  const res = await fetch("/api/upload", { method: "POST", body: fd });
  if (!res.ok) { showError(await errText(res)); return; }
  const data = await res.json();
  const zone = $(`.drop[data-kind="${kind}"]`);
  if (isMulti(kind)) {
    const list = (state.files[kind] ??= []);
    if (!list.some((f) => f.name === data.name)) list.push(data);
    $(".file-name", zone).textContent =
      list.length === 1 ? list[0].name : `${list.length} exports`;
  } else {
    state.files[kind] = data;
    $(".file-name", zone).textContent = data.name;
  }
  zone.classList.add("filled");

  if (kind === "campaign") {
    renderSheetList(data.sheets);
    guessBrand(data.name);
  }
  if (kind === "reference") $("#ccBtn").disabled = false;
  updateRunButtons();
}

/* A sponsor's workbook is usually one campaign split across tabs, so every tab
   starts ticked and merged; unticking is how you say otherwise. */
function renderSheetList(sheets) {
  const list = sheets ?? [];
  $("#sheetList").innerHTML = list.map((s) => `
    <label><input type="checkbox" value="${esc(s)}" checked>${esc(s)}</label>`).join("");
  $("#mergeRow").hidden = list.length < 2;
}

function pickedSheets() {
  return $$("#sheetList input:checked").map((i) => i.value);
}
$("#sheetList").addEventListener("change", updateRunButtons);

function updateRunButtons() {
  const ready = !!state.files.campaign && pickedSheets().length > 0;
  $("#addBrandBtn").disabled = !ready;
  $("#runBtn").disabled = !(ready || state.pending.length);
}

function guessBrand(filename) {
  const stop = /campaign|updated|photocard|fb|social|card|matched|_|\.xlsx/gi;
  const guess = filename.replace(stop, " ").replace(/['\d]/g, " ").trim().split(/\s+/).slice(0, 2).join(" ");
  const dl = $("#brandHints");
  dl.innerHTML = guess ? `<option value="${esc(guess)}">` : "";
  if (!$("#brand").value && guess) $("#brand").value = guess;
}

/* ═════════ cycle staging & run ═════════ */
function stageBrand() {
  const sheets = pickedSheets();
  if (!state.files.campaign || !sheets.length) return;
  state.pending.push({
    campaign: state.files.campaign,
    brand: $("#brand").value.trim() || "SPONSOR",
    sheets,
    merge: sheets.length > 1 && $("#mergeToggle").checked,
  });
  state.files.campaign = null;
  const zone = $('.drop[data-kind="campaign"]');
  zone.classList.remove("filled");
  $(".file-name", zone).textContent = "";
  renderSheetList([]);
  $("#brand").value = "";
  renderCycleList();
  updateRunButtons();
}
$("#addBrandBtn").addEventListener("click", stageBrand);

function stagedTabs(p) {
  if (p.sheets.length === 1) return p.sheets[0];
  return `${p.sheets.length} tabs${p.merge ? " merged" : " separate"}`;
}

function renderCycleList() {
  const el = $("#cycleList");
  el.hidden = !state.pending.length;
  el.innerHTML = state.pending.map((p, i) => `
    <span class="cycle-chip">${esc(p.brand)}<span class="sub">· ${esc(stagedTabs(p))}</span>
      <button data-i="${i}" title="Remove ${esc(p.brand)}">✕</button></span>`).join("");
}
$("#cycleList").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-i]");
  if (!b) return;
  state.pending.splice(+b.dataset.i, 1);
  renderCycleList();
  updateRunButtons();
});

function cycleLabel() {
  if (!state.runs.length) return "No month loaded";
  const month = state.runs[0].month;
  // Counted by brand, not by run: three tabs of one sponsor are one brand.
  const brands = new Set(state.runs.map((r) => r.brand));
  if (brands.size > 1) return `${brands.size} brands · ${month}`;
  const tabs = state.runs.length;
  return `${state.runs[0].brand} · ${month}` + (tabs > 1 ? ` +${tabs - 1} tabs` : "");
}

$("#runBtn").addEventListener("click", async () => {
  if (state.files.campaign) stageBrand();  // single-brand flow needs no Add click
  if (!state.pending.length) return;
  const shared = {
    insights: (state.files.insights ?? []).map((f) => f.path),
    ig_insights: (state.files.ig_insights ?? []).map((f) => f.path),
  };
  const batch = state.pending;
  $("#runBtn").disabled = true;
  try {
    // Matching is always per tab — each has its own header row, its own blank-
    // date repair and its own brand colour. Merging happens at report time.
    const runs = [];
    const groups = [];
    const total = batch.reduce((a, p) => a + p.sheets.length, 0);
    let done = 0;
    for (const p of batch) {
      const ids = [];
      for (const sheet of p.sheets) {
        done += 1;
        $("#runBtn").textContent = total > 1
          ? `Matching ${p.brand} · ${sheet} (${done}/${total})…` : "Matching…";
        const res = await fetch("/api/run", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ campaign: p.campaign.path, sheet, brand: p.brand, ...shared }),
        });
        if (!res.ok) throw new Error(`${p.brand} · ${sheet}: ${await errText(res)}`);
        const run = await res.json();
        runs.push(run);
        ids.push(run.run_id);
      }
      if (p.merge && ids.length > 1) {
        groups.push({ brand: p.brand, label: p.sheets[0], run_ids: ids });
      } else {
        ids.forEach((id, k) => groups.push(
          { brand: p.brand, label: p.sheets[k], run_ids: [id] }));
      }
    }
    state.runs = runs;
    state.groups = groups;
    state.run = runs[0];
    state.pending = [];
    state.selectedRow = null;
    state.dashSel = "all";
    renderCycleList();
    unlockViews();
    $("#exportBtn").disabled = false;
    $("#rangeText").textContent = cycleLabel();
    $("#syncTitle").textContent = cycleLabel();
    $("#syncSub").textContent =
      `${runs.reduce((a, r) => a + r.rows.length, 0)} content rows loaded`;
    renderReview();
    showView("review");
  } catch (e) {
    showError(e.message);
  } finally {
    $("#runBtn").disabled = false;
    $("#runBtn").textContent = "Run matching →";
    updateRunButtons();
  }
});
$("#newRunBtn").addEventListener("click", () => showView("inputs"));
$("#exportBtn").addEventListener("click", () => showView("report"));

/* [hidden] removes the element from layout, so a transition has nothing to run
   from: un-hide first, force a style flush so that state is the transition's
   start, then add the visible class; on the way out drop the class and re-hide
   once the transition has had time to finish. */
const CONCEAL_MS = 320;
function reveal(el) {
  clearTimeout(el._concealTimer);
  el.hidden = false;
  void el.offsetHeight;  // flush the un-hidden state; rAF would stall in a
                         // background tab, and scrapes run for minutes
  el.classList.add("in");
}
function conceal(el) {
  if (el.hidden) return;
  el.classList.remove("in");
  clearTimeout(el._concealTimer);
  el._concealTimer = setTimeout(() => { el.hidden = true; }, CONCEAL_MS);
}

function showError(msg) {
  const el = $("#runError");
  el.textContent = msg;
  reveal(el);
  clearTimeout(el._dismissTimer);
  el._dismissTimer = setTimeout(() => conceal(el), 8000);
}
async function errText(res) {
  // A dashboard reloaded against a RELAY that has not been restarted yet finds
  // the newer endpoints missing, and "Not Found" tells nobody anything.
  if (res.status === 404 || res.status === 405) return RESTART_HINT;
  try { const j = await res.json(); return j.detail || res.statusText; }
  catch { return res.statusText; }
}
const RESTART_HINT =
  "This RELAY server is still running the previous version — close it and start it "
  + "again (Start RELAY.bat) to enable this. Nothing already collected is lost.";

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
  // missing: still needs review
  let verified = 0, missing = 0;
  for (const row of state.run.rows) {
    for (const [slot, c] of Object.entries(row.cells)) {
      if (!row.links[slot]) continue;
      if (c.value == null) missing += 1;
      else verified += 1;
    }
  }
  return { verified, missing, total: verified + missing };
}

function mergedRun() {
  const rows = state.runs.flatMap((r) => r.rows);
  const cov = {};
  for (const slot of ["fb1", "fb2", "fb3", "x", "ig"]) {
    const linked = rows.filter((r) => r.links[slot]);
    cov[slot] = linked.length
      ? linked.filter((r) => r.cells[slot].value != null).length / linked.length : 1;
  }
  return { run_id: "__all__", brand: "All brands", month: state.runs[0].month,
           rows, coverage: cov, issues: state.runs.flatMap((r) => r.issues) };
}

function renderDashSeg() {
  const el = $("#dashBrandSeg");
  el.hidden = state.runs.length < 2;
  if (el.hidden) return;
  const opts = [["all", "All brands"],
                ...state.runs.map((r, i) => [String(i), runTabLabel(r)])];
  el.innerHTML = opts.map(([v, label]) =>
    `<button class="tab${String(state.dashSel) === v ? " active" : ""}" data-sel="${v}">${esc(label)}</button>`).join("");
}
$("#dashBrandSeg").addEventListener("click", (e) => {
  const b = e.target.closest(".tab");
  if (!b) return;
  state.dashSel = b.dataset.sel === "all" ? "all" : +b.dataset.sel;
  renderDashboard();
});

function renderDashboard() {
  const has = !!state.run;
  $("#dashEmpty").hidden = has;
  $("#dashBody").hidden = !has;
  if (!has) return;
  renderDashSeg();

  // every dashboard renderer reads state.run — swap in the dashboard's scope
  // (one brand or the "All brands" merge), render, restore
  const prev = state.run;
  if (state.runs.length > 1) {
    state.run = state.dashSel === "all" ? mergedRun() : (state.runs[state.dashSel] || prev);
  }
  try {
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
      kpi(icon("i-target"), "ic-green", "Match Rate", `${matchRate}%`, "exact values from Meta"),
      kpi(icon("i-alert"), "ic-amber", "Needs Review", String(review), review === 1 ? "content row" : "content rows"),
    ].join("");

    renderLineChart();
    renderPlatformSummary(sums);
    renderDonut(ms);
    renderTopContent();
    renderActivity();
  } finally {
    state.run = prev;
  }
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
  return "matched";
}

function renderTopContent() {
  const rows = state.run.rows.map((row) => ({
    row,
    total: Object.values(row.cells).reduce((a, c) => a + (c.value ?? 0), 0),
  })).sort((a, b) => b.total - a.total).slice(0, 5);
  const tips = { matched: "all values verified",
                 missing: "has unresolved cells" };
  $("#topContent").innerHTML = rows.map((r, i) => {
    const st = rowStatus(r.row);
    return `
    <li><span class="top-rank">${i + 1}</span>
      <i class="dot p-${st}" data-tip="${tips[st]}"></i>
      <span class="top-cap" title="${esc(capText(r.row))}">${esc(capText(r.row))}</span>
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

/* one tab per brand — the workspace switcher (Phase 8); count = needs attention */
/* One brand across several tabs would otherwise render as identical tabs, so
   the tab name is shown whenever a brand appears more than once. */
function runTabLabel(run) {
  const repeated = state.runs.filter((r) => r.brand === run.brand).length > 1;
  return repeated ? `${run.brand} · ${run.month}` : run.brand;
}

/* The ✕ lives beside the tab, not inside it: a button inside a button is
   invalid, and the browser stops delivering clicks to the inner one. */
function renderBrandTabs(sel, onSwitch) {
  const el = $(sel);
  el.innerHTML = state.runs.map((r, i) => `
    <span class="ctab-wrap${r === state.run ? " active" : ""}">
      <button class="ctab${r === state.run ? " active" : ""}" role="tab"
        aria-selected="${r === state.run}" data-run="${i}">
        ${esc(runTabLabel(r))} <span class="count">${r.rows.filter(needsAttention).length || ""}</span>
      </button>
      <button class="ctab-x" data-drop="${i}" title="Remove ${esc(runTabLabel(r))} from this cycle"
        aria-label="Remove ${esc(runTabLabel(r))} from this cycle">
        <svg class="ic-svg"><use href="#i-close"/></svg></button>
    </span>`).join("");
  el.onclick = (e) => {
    const x = e.target.closest(".ctab-x");
    if (x) { discardRun(state.runs[+x.dataset.drop]); return; }
    const b = e.target.closest(".ctab");
    if (!b || state.runs[+b.dataset.run] === state.run) return;
    state.run = state.runs[+b.dataset.run];
    state.selectedRow = null;
    onSwitch();
  };
}

/* ═════════ discarding a campaign mid-review ═════════ */
/* The wrong campaign sheet is usually only recognisable once its rows are on
   screen, which used to mean re-running the whole cycle to be rid of it. */
async function discardRun(run) {
  if (!run) return;
  const label = runTabLabel(run);
  const ok = await askConfirm({
    title: `Remove ${label}?`,
    body: `${run.rows.length} matched rows leave this cycle and ${label} drops out of `
        + `the reports. The campaign sheet itself is untouched — load it again any time, `
        + `and everything already collected for it comes back.`,
    ok: "Remove campaign",
  });
  if (!ok) return;

  const res = await fetch(`/api/run/${encodeURIComponent(run.run_id)}`, { method: "DELETE" });
  if (!res.ok) { showError(await errText(res)); return; }

  state.runs = state.runs.filter((r) => r !== run);
  // A group is one delivered workbook; it survives losing one of its tabs and
  // disappears only when it has no tabs left.
  state.groups = state.groups
    .map((g) => ({ ...g, run_ids: g.run_ids.filter((id) => id !== run.run_id) }))
    .filter((g) => g.run_ids.length);
  if (state.run === run) state.run = state.runs[0] || null;
  state.selectedRow = null;
  state.dashSel = "all";

  if (!state.runs.length) {
    $("#exportBtn").disabled = true;
    $("#rangeText").textContent = "No month loaded";
    $("#syncTitle").textContent = "No run yet";
    $("#syncSub").textContent = "Upload this month's files";
    $$(".nav-item[data-view='review'], .nav-item[data-view='report']")
      .forEach((b) => b.setAttribute("data-locked", ""));
    showView("inputs");
    return;
  }
  $("#rangeText").textContent = cycleLabel();
  $("#syncTitle").textContent = cycleLabel();
  $("#syncSub").textContent =
    `${state.runs.reduce((a, r) => a + r.rows.length, 0)} content rows loaded`;
  renderReview();
  if (!$("#view-report").hidden) renderReport();
}

/* ═════════ confirm ═════════ */
const confirmDialog = $("#confirmDialog");
function askConfirm({ title, body, ok = "Confirm" }) {
  $("#confirmTitle").textContent = title;
  $("#confirmBody").textContent = body;
  $("#confirmOk").textContent = ok;
  confirmDialog.showModal();
  return new Promise((resolve) => {
    confirmDialog.addEventListener(
      "close", () => resolve(confirmDialog.returnValue === "ok"), { once: true });
  });
}

function renderReview() {
  renderBrandTabs("#brandTabs", renderReview);
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

  renderIssues(r.issues);
}

/* Input notes. The list is scrolled rather than allowed to run the page off the
   bottom — a two-hundred-row sheet with blank dates puts a hundred lines here,
   and the Continue button ended up below all of them.
   `where` comes from the backend because "row 5" means two different things:
   a line of the workbook for an ingest note, the No the table shows for a
   per-cell one. */
function renderIssues(issues) {
  const el = $("#issues");
  if (!issues.length) { el.hidden = true; return; }
  el.hidden = false;
  el.innerHTML =
    `<div class="issues-head"><strong>Input notes</strong>
       <span class="issues-count">${issues.length}</span></div>
     <ul class="issues-list">` +
    issues.map((i) => `<li>${esc(i.file)}${i.where ? ` · ${esc(i.where)}` : ""}: `
      + `${esc(i.reason)}</li>`).join("") + `</ul>`;
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
      <td class="caption"><span class="cap-text" title="${esc(capText(row))}">${esc(capText(row))}</span>${capBadge(row)}</td>
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
  const fresh = state.freshCells.has(`${state.run.run_id}:${row.no}:${slot}`) ? " freshly" : "";
  // the ≈ mark travels with every heuristic value, here and in the workbook
  const val = c.value != null
    ? `<span class="val${fresh}">${fmt(c.value)}</span>`
    : `<span class="noval">missing</span>`;
  return `<td class="num"><span class="cellv">${dot}${val}${conf}
    <button class="cell-edit" data-row="${row.no}" data-slot="${slot}" title="Enter a value manually">✎</button>
  </span></td>`;
}

function provTip(c) {
  const parts = [`${c.provenance}${c.confidence < 1 ? ` · confidence ${c.confidence}` : ""}`];
  if (c.note) parts.push(c.note);
  return parts.join(" — ");
}

/* ═════════ cell editor ═════════ */
const dialog = $("#cellDialog");
/* Only Facebook: Meta publishes reach and engagement per post and the report
   has a column for each. X's public page and the Instagram export offer
   neither, so those slots would be collecting numbers nothing can print. */
const HAS_COMPANIONS = (slot) => slot.startsWith("fb");

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
  $("#manualValue").value = c.value ?? "";
  const pair = $("#fbMetrics");
  pair.hidden = !HAS_COMPANIONS(slot);
  $("#manualReach").value = pair.hidden ? "" : (c.reach ?? "");
  $("#manualEngagement").value = pair.hidden ? "" : (c.engagement ?? "");
  // Nothing to strike off a slot the sheet never linked.
  $("#deadLinkRow").hidden = !row.links[slot];
  dialog.showModal();
}

/* A post the team took down, whose link nobody removed from the sheet. */
$("#removeLinkBtn").addEventListener("click", async () => {
  if (!state.editing) return;
  const { rowNo, slot } = state.editing;
  const ok = await askConfirm({
    title: `Remove the ${SLOT_LABELS[slot]} link on row ${rowNo}?`,
    body: "Use this when the post itself is gone from the platform. The slot stops "
        + "counting as a missing value, and the delivered workbook leaves its link and "
        + "figures blank instead of pointing the sponsor at a dead page.",
    ok: "Remove link",
  });
  if (!ok) return;
  const res = await fetch("/api/link/remove", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: state.run.run_id, row_no: rowNo, slot }),
  });
  if (!res.ok) { showError(await errText(res)); return; }
  const data = await res.json();
  const row = state.run.rows.find((r) => r.no === rowNo);
  row.links[slot] = null;
  row.cells[slot] = data.cell;
  state.editing = null;          // the close handler must not then write a value
  dialog.close("cancel");
  recomputeCoverage();
  renderReview();
});
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

dialog.addEventListener("close", async () => {
  const wantNext = dialog.returnValue === "apply-next";
  if ((dialog.returnValue !== "apply" && !wantNext) || !state.editing) return;
  const { rowNo, slot } = state.editing;
  const num = (sel) => $(sel).value === "" ? null : parseInt($(sel).value, 10);
  const body = { run_id: state.run.run_id, row_no: rowNo, slot,
                 value: num("#manualValue") };
  if (HAS_COMPANIONS(slot)) {
    body.reach = num("#manualReach");
    body.engagement = num("#manualEngagement");
  }
  const res = await fetch("/api/override", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) { showError(await errText(res)); return; }
  const cell = await res.json();
  // An older server accepts the request and drops the two extra figures without
  // saying so, which is the one way this can fail silently.
  if (body.reach != null && cell.reach == null) showError(RESTART_HINT);
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
$("#collectX").addEventListener("click", () => startCollect("x"));
$("#collectFB").addEventListener("click", () => startCollect("fb"));
$("#collectIG").addEventListener("click", () => startCollect("ig"));

const COLLECT_BTN = { fb: "#collectFB", ig: "#collectIG", x: "#collectX" };
const COLLECT_LABEL = {
  x: "Scraping public X pages (politely paced)…",
  fb: "Identifying each post by its post ID via your Meta session…",
  ig: "Collecting Instagram via your Meta session…",
};
function puEls(target) {
  const u = $(`.progress-unit[data-unit="${target}"]`);
  return { u, fill: $(".pu-fill", u), text: $(".pu-text", u),
           count: $(".pu-count", u), log: $(".pu-log", u), stop: $(".pu-stop", u) };
}

/* merge freshly-scraped runs from a status poll into state, marking new cells */
function applyRunUpdates(freshRuns) {
  // each poll owns its own fresh set: a cell pops on the poll it arrives and
  // never again, even though every poll rebuilds the table's DOM
  state.freshCells.clear();
  const activeId = state.run.run_id;
  state.runs = state.runs.map((old) => {
    const fresh = freshRuns[old.run_id];
    if (!fresh) return old;
    for (const row of fresh.rows) {
      const oldRow = old.rows.find((r) => r.no === row.no);
      for (const slot of Object.keys(row.cells)) {
        if (row.cells[slot].value != null && oldRow && oldRow.cells[slot].value == null) {
          state.freshCells.add(`${fresh.run_id}:${row.no}:${slot}`);
        }
      }
    }
    return fresh;
  });
  state.run = state.runs.find((r) => r.run_id === activeId) || state.runs[0];
}

function anyCollecting() {
  return Object.values(state.collecting).some(Boolean);
}

async function startCollect(target) {
  if (!state.runs.length || state.collecting[target] || state.autopilot) return;
  // always the batch endpoint: one browser session and one shared Pacer
  // budget across every brand in the cycle
  const body = { run_ids: state.runs.map((r) => r.run_id), target };
  const res = await fetch("/api/collect/batch", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const errEl = $("#collectError");
  if (res.status === 412) {
    // No Meta session yet — open the sign-in browser automatically and
    // start collecting the moment the sign-in window is closed.
    await metaSignInThenCollect(target);
    return;
  }
  if (!res.ok) {
    errEl.textContent = await errText(res);
    reveal(errEl);
    return;
  }
  conceal(errEl);
  state.collecting[target] = true;
  $(COLLECT_BTN[target]).disabled = true;
  $("#autopilotBtn").disabled = true;
  $("#collectProgress").hidden = false;
  const el = puEls(target);
  reveal(el.u);
  el.fill.style.width = "0%";
  el.text.textContent = COLLECT_LABEL[target];
  el.count.textContent = "";
  el.log.innerHTML = "";
  reveal(el.stop);
  el.stop.disabled = false;
  pollCollect(target);
}

async function pollCollect(target) {
  const el = puEls(target);
  const ids = state.runs.map((r) => r.run_id).join(",");
  const res = await fetch(`/api/collect/batch/${target}?ids=${ids}`);
  if (!res.ok) { finishCollect(target, "status check failed"); return; }
  const s = await res.json();
  if (s.state === "idle") { setTimeout(() => pollCollect(target), 1200); return; }

  if (s.runs) applyRunUpdates(s.runs);
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
      reveal(errEl);
    }
  }
}

function finishCollect(target, message) {
  state.collecting[target] = false;
  $(COLLECT_BTN[target]).disabled = false;
  if (!anyCollecting() && !state.autopilot) $("#autopilotBtn").disabled = false;
  const el = puEls(target);
  conceal(el.stop);
  el.text.textContent = message;
  setTimeout(() => state.freshCells.clear(), 4000);
}

$$(".pu-stop").forEach((b) => b.addEventListener("click", async () => {
  const target = b.dataset.target;
  if (!state.collecting[target]) return;
  b.disabled = true;
  puEls(target).text.textContent = "Stopping after the current post…";
  await fetch(`/api/collect/batch/${target}/stop`, { method: "POST" });
}));

/* one-time Meta sign-in, launched straight from the Collect button */
async function metaSignInThenCollect(target = "fb") {
  const res = await fetch("/api/login/meta", { method: "POST" });
  const errEl = $("#collectError");
  if (!res.ok) { errEl.textContent = await errText(res); reveal(errEl); return; }
  conceal(errEl);
  $("#collectProgress").hidden = false;
  const el = puEls(target);
  reveal(el.u);
  el.fill.style.width = "0%";
  el.count.textContent = "";
  el.log.innerHTML = "";
  conceal(el.stop);
  el.text.textContent =
    "A browser window opened on this machine — sign in to Facebook / Meta Business Suite " +
    (target === "ig" ? "and instagram.com " : "") +
    "(2FA is fine), then close that window. Collection starts automatically.";
  $(COLLECT_BTN[target]).disabled = true;

  const poll = async () => {
    const s = await (await fetch("/api/login/meta/status")).json();
    if (s.error) {
      $(COLLECT_BTN[target]).disabled = false;
      el.text.textContent = "Sign-in did not complete.";
      errEl.textContent = s.error;
      reveal(errEl);
      return;
    }
    if (s.ready) {
      $(COLLECT_BTN[target]).disabled = false;
      el.text.textContent = "Signed in — starting collection…";
      startCollect(target);
      return;
    }
    setTimeout(poll, 2000);
  };
  poll();
}

/* ═════════ autopilot ═════════ */
const AP_LABELS = { fb: "Facebook", ig: "Instagram", x: "X / Twitter" };

$("#autopilotBtn").addEventListener("click", startAutopilot);
$("#apStop").addEventListener("click", async () => {
  if (!state.autopilot) return;
  $("#apStop").disabled = true;
  puEls("ap").text.textContent = "Stopping after the current post…";
  await fetch("/api/autopilot/stop", { method: "POST" });
});

function resetApUnit() {
  const el = puEls("ap");
  reveal(el.u);
  el.fill.style.width = "0%";
  el.count.textContent = "";
  el.log.innerHTML = "";
  $("#apStage").hidden = true;
  $("#collectProgress").hidden = false;
  return el;
}

async function startAutopilot() {
  if (!state.runs.length || state.autopilot || anyCollecting()) return;
  const res = await fetch("/api/autopilot", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_ids: state.runs.map((r) => r.run_id) }),
  });
  const errEl = $("#collectError");
  if (res.status === 412) {
    // check upfront: the Meta session must exist before anything runs
    await metaSignInThenAutopilot();
    return;
  }
  if (!res.ok) {
    errEl.textContent = await errText(res);
    reveal(errEl);
    return;
  }
  conceal(errEl);
  state.autopilot = true;
  $("#autopilotBtn").disabled = true;
  Object.values(COLLECT_BTN).forEach((sel) => { $(sel).disabled = true; });
  const el = resetApUnit();
  el.text.textContent = "Autopilot started…";
  reveal($("#apStop"));
  $("#apStop").disabled = false;
  pollAutopilot();
}

async function pollAutopilot() {
  const el = puEls("ap");
  const ids = state.runs.map((r) => r.run_id).join(",");
  const res = await fetch(`/api/autopilot/status?ids=${ids}`);
  if (!res.ok) { finishAutopilot("status check failed"); return; }
  const s = await res.json();
  if (s.state === "idle") { setTimeout(pollAutopilot, 1200); return; }

  if (s.runs) applyRunUpdates(s.runs);
  const stage = $("#apStage");
  if (s.brand && s.target) {
    stage.hidden = false;
    stage.textContent = state.runs.length > 1
      ? `${s.brand} · ${s.campaign}/${s.campaigns} · ${AP_LABELS[s.target]}`
      : AP_LABELS[s.target];
  }
  const pct = s.total ? Math.round((s.done / s.total) * 100) : 0;
  el.fill.style.width = pct + "%";
  el.count.textContent = s.total ? `${s.done}/${s.total} visited · ${s.filled} filled` : "";
  if (s.state === "running") {
    // A pacing pause is a quarter of an hour of deliberate silence. Say so and
    // count it down, or the run reads as wedged and gets stopped by hand.
    el.text.textContent = s.cooling
      ? `Pacing pause — ${AP_LABELS[s.target]} resumes in ${fmtWait(s.cooling)}. `
        + "Autopilot carries on by itself."
      : s.target ? `Collecting ${AP_LABELS[s.target]} for ${s.brand}…` : "Starting…";
  }
  if (s.events?.length) {
    el.log.innerHTML = s.events.slice().reverse()
      .map((e) => `<li>${esc(e)}</li>`).join("");
  }
  recomputeCoverage();
  renderReview();

  if (s.state === "running") {
    setTimeout(pollAutopilot, 2000);
  } else {
    finishAutopilot(s.message || s.state);
    if (s.state === "error") {
      const errEl = $("#collectError");
      errEl.textContent = s.message;
      reveal(errEl);
    }
  }
}

function finishAutopilot(message) {
  state.autopilot = false;
  $("#autopilotBtn").disabled = false;
  Object.values(COLLECT_BTN).forEach((sel) => { $(sel).disabled = false; });
  const el = puEls("ap");
  conceal($("#apStop"));
  el.text.textContent = message;
  setTimeout(() => state.freshCells.clear(), 4000);
}

/* upfront Meta sign-in, then the cycle starts by itself */
async function metaSignInThenAutopilot() {
  const res = await fetch("/api/login/meta", { method: "POST" });
  const errEl = $("#collectError");
  if (!res.ok) { errEl.textContent = await errText(res); reveal(errEl); return; }
  conceal(errEl);
  const el = resetApUnit();
  conceal($("#apStop"));
  el.text.textContent =
    "Autopilot needs the Meta session first. A browser window opened on this machine — " +
    "sign in to Facebook / Meta Business Suite and instagram.com (2FA is fine), " +
    "then close that window. Autopilot starts automatically.";
  $("#autopilotBtn").disabled = true;

  const poll = async () => {
    const s = await (await fetch("/api/login/meta/status")).json();
    if (s.error) {
      $("#autopilotBtn").disabled = false;
      el.text.textContent = "Sign-in did not complete.";
      errEl.textContent = s.error;
      reveal(errEl);
      return;
    }
    if (s.ready) {
      $("#autopilotBtn").disabled = false;
      el.text.textContent = "Signed in — starting autopilot…";
      startAutopilot();
      return;
    }
    setTimeout(poll, 2000);
  };
  poll();
}

/* ═════════ report ═════════ */
$("#toReport").addEventListener("click", () => showView("report"));

/* The group whose workbook the active run will land in. */
function activeGroup() {
  const id = state.run?.run_id;
  return state.groups.find((g) => g.run_ids.includes(id))
    ?? { brand: state.run?.brand, label: state.run?.month, run_ids: [id] };
}

function renderGenHint() {
  const g = activeGroup();
  const el = $("#genHint");
  el.hidden = g.run_ids.length < 2;
  if (el.hidden) return;
  const tabs = g.run_ids
    .map((id) => state.runs.find((r) => r.run_id === id)?.month)
    .filter(Boolean);
  const rows = g.run_ids.reduce((a, id) =>
    a + (state.runs.find((r) => r.run_id === id)?.rows.length ?? 0), 0);
  el.textContent = `One workbook for ${g.brand}: ${tabs.join(" + ")} — `
    + `${rows} rows in one table, each tagged with the tab it came from.`;
}

function renderReport() {
  if (!state.run) return;
  renderBrandTabs("#brandTabsReport", renderReport);
  renderGenHint();
  $("#genAllBtn").hidden = state.groups.length < 2;
  if (state.groups.length < 2) $("#dlAllBtn").hidden = true;
  const r = state.run;
  const sums = slotSums();
  const fbTotal = sums.fb1 + sums.fb2 + sums.fb3;
  const grand = fbTotal + sums.x + sums.ig;
  const ms = matchStats();
  $("#reportTiles").innerHTML = [
    tile(`${r.brand} · ${r.month}`, String(r.rows.length), "content rows"),
    tile("Total views", fmt(grand), "all platforms, resolved cells"),
    tile("Facebook", fmt(fbTotal), "links 1–3"),
    tile("Instagram", fmt(sums.ig), "views"),
    tile("Resolved", `${ms.verified}/${ms.total}`, "cells", ms.missing > 0),
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
  const g = activeGroup();
  const res = await fetch("/api/report/group", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_ids: g.run_ids, label: g.label }),
  });
  if (!res.ok) { showError(await errText(res)); return; }
  const data = await res.json();
  const dl = $("#dlBtn");
  reveal(dl);
  // By name, not by run id: a merged workbook belongs to several runs at once.
  dl.href = `/api/report/download/${encodeURIComponent(data.name)}`;
  $("#dlText").textContent = `Download ${data.name}`;
});

$("#genAllBtn").addEventListener("click", async () => {
  const res = await fetch("/api/report/batch", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      groups: state.groups.map((g) => ({ run_ids: g.run_ids, label: g.label })),
      comments: $("#commentsToggle").checked,
    }),
  });
  if (!res.ok) { showError(await errText(res)); return; }
  const data = await res.json();
  const dl = $("#dlAllBtn");
  reveal(dl);
  dl.href = `/api/report/batch/download/${encodeURIComponent(data.name)}`;
  $("#dlAllText").textContent = `Download ${data.name}`;
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

/* A countdown reads as stalled in bare seconds once it passes a minute. */
function fmtWait(secs) {
  if (secs < 60) return `${secs}s`;
  const m = Math.floor(secs / 60);
  return `${m}m ${String(secs % 60).padStart(2, "0")}s`;
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
  matched: ["pc-matched", "verified"],
  missing: ["pc-missing", "needs review"],
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
  const color = status === "matched" ? "var(--good)" : "var(--critical)";
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
      <span class="rcard-cap" title="${esc(capText(row))}">${esc(capText(row))}</span>
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
    <h3 class="rd-cap">${esc(capText(row))}</h3>
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
  const fresh = state.freshCells.has(`${state.run.run_id}:${row.no}:${slot}`) ? " freshly" : "";
  const val = c.value != null
    ? `<span class="val${fresh}">${fmt(c.value)}</span>`
    : `<span class="noval">missing</span>`;
  return `<div class="slot-row">
    <div class="slot-ic" style="background:${meta.bg}"><svg class="ic-svg"><use href="#${meta.icon}"/></svg></div>
    <div class="slot-name"><strong>${esc(name)}</strong>
      <span class="sub">${esc(c.value != null ? c.provenance : "unresolved")}</span></div>
    <div class="slot-val">${dot}${val}${conf}
      <button class="cell-edit" data-row="${row.no}" data-slot="${slot}" title="Enter a value manually">✎ edit</button>
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
/* a full-page colour inversion is jarring with no bridge; the View Transitions
   API cross-fades it without transitioning colours on every element */
function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    document.startViewTransition(() => applyTheme(next));
  } else {
    applyTheme(next);
  }
}
$("#themeBtn").addEventListener("click", toggleTheme);
