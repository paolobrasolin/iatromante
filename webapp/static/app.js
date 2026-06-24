const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const api = (p) => fetch(p).then(r => r.json());
const PATHS = [];
const sel = { latest: null, search: null }; // selected pathology per tab
let MODE = "semantic";

function hslRGB(h, s, l) {  // h,s,l in [0,1] -> [r,g,b]
  const k = n => (n + h * 12) % 12;
  const f = n => l - s * Math.min(l, 1 - l) * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1));
  return [Math.round(f(0) * 255), Math.round(f(8) * 255), Math.round(f(4) * 255)];
}
const macroHue = c => (c * 137.508) % 360;     // golden-angle hue per macro
const clusterColor = (c) => c < 0 ? "#c9c9d4" : `hsl(${macroHue(c)} 58% 52%)`;
const clusterRGB = (c) => c < 0 ? [201, 201, 212] : hslRGB(macroHue(c) / 360, 0.58, 0.52);

// per-sub colors: macro's hue, lightness varied across its subs so they're distinguishable
const SUBRGB = {}, MACRORGB = {};
function buildColors() {
  for (const k in SUBRGB) delete SUBRGB[k];
  MAP.macros.forEach(m => {
    const h = macroHue(m.cluster);
    MACRORGB[m.cluster] = hslRGB(h / 360, 0.58, 0.52);
    m._rgb = `hsl(${h} 58% 52%)`;
    const n = m.subs.length;
    m.subs.forEach((s, j) => {
      const l = n > 1 ? 0.40 + 0.26 * (j / (n - 1)) : 0.52;   // 40%..66% within the hue
      SUBRGB[s.cluster] = hslRGB(h / 360, 0.60, l);
      s._rgb = `hsl(${h} 60% ${Math.round(l * 100)}%)`;
    });
  });
}
const esc = (s) => (s || "").replace(/[&<>]/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[m]));

// ---- bootstrap ----------------------------------------------------------
api("/api/meta").then(m => {
  $("#count").textContent = m.total.toLocaleString() + " papers";
  PATHS.push(...m.pathologies);
  buildChips("#search-chips", "search");
  buildChips("#latest-chips", "latest");
  loadLatest(true);
});

function buildChips(sel_, tab) {
  const host = $(sel_);
  host.innerHTML = "";
  PATHS.forEach(p => {
    const c = document.createElement("button");
    c.className = "chip"; c.textContent = p; c.dataset.path = p;
    c.onclick = () => {
      sel[tab] = sel[tab] === p ? null : p;
      $$(".chip", host).forEach(x => x.classList.toggle("on", x.dataset.path === sel[tab]));
      if (tab === "latest") loadLatest(true);
    };
    host.appendChild(c);
  });
}

// ---- tabs ---------------------------------------------------------------
$$(".tab").forEach(t => t.onclick = () => {
  $$(".tab").forEach(x => x.classList.toggle("active", x === t));
  $$(".panel").forEach(p => p.classList.remove("active"));
  $("#panel-" + t.dataset.tab).classList.add("active");
  if (t.dataset.tab === "map" && !mapLoaded) loadMap();
});

// ---- result cards -------------------------------------------------------
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const KIND = { article: "article", preprint: "preprint", clinical_trial: "clinical trial" };  // type label on every card
function fmtDate(s) {  // "YYYY-MM-DD" -> "Mon YYYY"; the day is often synthetic, so show month precision
  if (!s) return "";
  const [y, m] = s.split("-");
  return (m ? MONTHS[+m - 1] + " " : "") + y;
}
function cardEl(r) {
  const div = document.createElement("div");
  div.className = "card";
  const tags = (KIND[r.type] ? `<span class="pill kind">${KIND[r.type]}</span>` : "")
    + r.pathologies.map(p => `<span class="pill ${p}">${p}</span>`).join("")
    + (r.is_oa ? '<span class="pill oa">free full text</span>' : "")
    + (r.score != null ? `<span class="pill score">${Math.round(r.score * 100)}% match</span>` : "");
  const meta = [r.authors, r.venue, r.pub_date ? fmtDate(r.pub_date) : r.year].filter(Boolean).join(" · ");
  div.innerHTML = `<h3>${esc(r.title)}</h3><div class="meta">${esc(meta)}</div>
    <div class="snip">${r.snippet || ""}</div><div class="tags">${tags}</div>`;
  div.onclick = () => openPaper(r.id);
  return div;
}
function renderCards(host, results) {
  host.innerHTML = "";
  if (!results.length) { host.innerHTML = '<div class="empty">No results.</div>'; return; }
  results.forEach(r => host.appendChild(cardEl(r)));
}

// ---- latest feed --------------------------------------------------------
const LATEST_PAGE = 30;
let latestOffset = 0, latestType = "", latestOA = "";
function loadLatest(reset) {
  if (reset) { latestOffset = 0; $("#latest-results").innerHTML = '<div class="loading">Loading…</div>'; }
  const u = new URL("/api/latest", location.origin);
  u.searchParams.set("limit", LATEST_PAGE);
  u.searchParams.set("offset", latestOffset);
  if (sel.latest) u.searchParams.set("pathology", sel.latest);
  if (latestType) u.searchParams.set("type", latestType);
  if (latestOA) u.searchParams.set("oa", "1");
  api(u).then(d => {
    const host = $("#latest-results");
    if (reset) host.innerHTML = "";
    if (reset && !d.results.length) host.innerHTML = '<div class="empty">No papers match these filters.</div>';
    d.results.forEach(r => host.appendChild(cardEl(r)));
    latestOffset += d.results.length;
    $("#latest-more").hidden = d.results.length < LATEST_PAGE;
  });
}
$("#latest-more").onclick = () => loadLatest(false);
$$("#latest-type button").forEach(b => b.onclick = () => {
  latestType = b.dataset.type;
  $$("#latest-type button").forEach(x => x.classList.toggle("on", x === b));
  loadLatest(true);
});
$$("#latest-oa button").forEach(b => b.onclick = () => {
  latestOA = b.dataset.oa;
  $$("#latest-oa button").forEach(x => x.classList.toggle("on", x === b));
  loadLatest(true);
});

// ---- search -------------------------------------------------------------
$("#search-go").onclick = doSearch;
$("#search-q").addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });
$$("#mode-toggle button").forEach(b => b.onclick = () => {
  MODE = b.dataset.mode;
  $$("#mode-toggle button").forEach(x => x.classList.toggle("on", x === b));
  if ($("#search-q").value.trim()) doSearch();
});
function doSearch() {
  const q = $("#search-q").value.trim();
  if (!q) return;
  const host = $("#search-results");
  host.innerHTML = '<div class="loading">Searching…</div>';
  const u = new URL("/api/search", location.origin);
  u.searchParams.set("q", q); u.searchParams.set("mode", MODE);
  if (sel.search) u.searchParams.set("pathology", sel.search);
  api(u).then(d => renderCards(host, d.results || []));
}

// ---- paper modal --------------------------------------------------------
function openPaper(id) {
  const bg = $("#modal-bg");
  bg.classList.add("open");
  $("#modal").innerHTML = '<div class="loading">Loading…</div>';
  api("/api/paper/" + encodeURIComponent(id)).then(p => {
    const authors = p.authors.slice(0, 12).join(", ") + (p.authors.length > 12 ? " et al." : "");
    const meta = [authors, p.venue, p.year].filter(Boolean).join(" · ");
    const tags = p.pathologies.map(x => `<span class="pill ${x}">${x}</span>`).join("");
    const links = [];
    if (p.url) links.push(`<a class="btn primary" href="${p.url}" target="_blank" rel="noopener">Open paper ↗</a>`);
    if (p.full_text_url) links.push(`<a class="btn" href="${p.full_text_url}" target="_blank" rel="noopener">Full text (PDF) ↗</a>`);
    if (p.doi) links.push(`<a class="btn" href="https://doi.org/${p.doi}" target="_blank" rel="noopener">DOI ↗</a>`);
    $("#modal").innerHTML = `<button class="close" onclick="closeModal()">×</button>
      <h2>${esc(p.title)}</h2>
      <div class="meta">${esc(meta)} ${p.cluster_label ? "· topic: " + esc(p.cluster_label) : ""}</div>
      <div class="tags" style="margin-bottom:14px">${tags}${p.is_oa ? '<span class="pill oa">open access</span>' : ""}</div>
      <div class="abstract">${esc(p.abstract) || "<em>No abstract available.</em>"}</div>
      <div class="links">${links.join("")}</div>`;
  });
}
function closeModal() { $("#modal-bg").classList.remove("open"); }
$("#modal-bg").onclick = (e) => { if (e.target.id === "modal-bg") closeModal(); };
document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });

// ---- map ----------------------------------------------------------------
let mapLoaded = false;
let MAP = { points: [], clusters: [], focus: null, condSel: new Set(), bounds: null, tx: null };
let yearMin = 0, yearMax = 9999;
let cmode = "topic";                                   // "topic" | "condition"
const RGB = {};                                        // cluster -> [r,g,b] cache
const COND_RGB = { 1: [194, 84, 122], 2: [201, 138, 43], 4: [106, 90, 205] }; // endo/lip/fibro
const MULTI_RGB = [214, 36, 143];                      // cross-condition standout (magenta)
const COND_INFO = [{ m: 1, name: "endometriosis" }, { m: 2, name: "lipedema" }, { m: 4, name: "fibromyalgia" }];
const popcount = m => (m & 1) + ((m >> 1) & 1) + ((m >> 2) & 1);
let oaOnly = false, mapType = "";           // open-access-only filter; publication-type filter ("" = all)
const TYPE_CODE = { article: 1, preprint: 2, clinical_trial: 3 };  // mirrors app.py; matches point tuple's type code
let view = { z: 1, ox: 0, oy: 0 };          // zoom + pan (pan offsets in device px)
// year-histogram colors: shadow = full corpus distribution, fill = current filter result
const HIST_BG = "#dcdce4";
const HIST_SEL = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#2f7d78";
let histLog = true;                         // histogram vertical scale: log (default, the skew is exponential) vs linear
// point tuple: [x, y, macro, sub, year, pmask, is_oa, type_code]
const visible = p => p[4] >= yearMin && p[4] <= yearMax && (!oaOnly || p[6])
  && (!mapType || p[7] === TYPE_CODE[mapType]);
function makeProj(t) {
  const bx = x => t.pad + (x - t.minx) / (t.maxx - t.minx || 1) * (t.W - 2 * t.pad);
  const by = y => t.H - t.pad - (y - t.miny) / (t.maxy - t.miny || 1) * (t.H - 2 * t.pad);
  return { sx: x => bx(x) * t.z + t.ox, sy: y => by(y) * t.z + t.oy };
}
function clampPan() {
  if (view.z <= 1) { view.z = 1; view.ox = 0; view.oy = 0; return; }
  if (!MAP.tx) return;
  const W = MAP.tx.W, H = MAP.tx.H;
  view.ox = Math.min(0, Math.max(W - W * view.z, view.ox));
  view.oy = Math.min(0, Math.max(H - H * view.z, view.oy));
}

function loadMap() {
  mapLoaded = true;
  $("#map-count").textContent = "loading…";
  const u = new URL("/api/map", location.origin);
  Promise.all([api(u), api("/api/clusters")]).then(([m, c]) => {
    MAP.points = m.points; MAP.macros = c.macros; MAP.focus = null; MAP.condSel = new Set();
    view = { z: 1, ox: 0, oy: 0 };
    buildColors(); computeBounds(); setupYearSlider(); drawMap(); drawHist(); buildLegend();
  });
}
function computeBounds() {
  let a = Infinity, b = -Infinity, cc = Infinity, d = -Infinity;
  for (const [x, y] of MAP.points) {
    if (x < a) a = x; if (x > b) b = x; if (y < cc) cc = y; if (y > d) d = y;
  }
  MAP.bounds = { minx: a, maxx: b, miny: cc, maxy: d };
}
function updateBand() {
  const from = $("#yr-from"), to = $("#yr-to"), band = $("#yr-band");
  const lo = +from.min, span = (+from.max - lo) || 1;
  const a = Math.min(+from.value, +to.value), b = Math.max(+from.value, +to.value);
  // map to thumb-center px: thumbs travel inset by half their 15px width, so the band edges
  // (and its centered handle) line up with the round thumbs rather than the full track width
  const trav = ($("#yr-dual").clientWidth || 0) - 15;
  const x = v => 7.5 + (v - lo) / span * trav;
  band.style.left = x(a) + "px";
  band.style.width = (x(b) - x(a)) + "px";
}
// re-read the slider inputs and refresh everything keyed to the year window
function applyYear() {
  const from = $("#yr-from"), to = $("#yr-to");
  yearMin = Math.min(+from.value, +to.value);
  yearMax = Math.max(+from.value, +to.value);
  $("#yr-from-lab").textContent = yearMin; $("#yr-to-lab").textContent = yearMax;
  updateBand(); drawMap(); drawHist();
  if (cmode === "condition") buildLegend();   // overlap counts track the year window
}
function setupYearSlider() {
  let lo = Infinity, hi = -Infinity;
  for (const p of MAP.points) { const y = p[4]; if (y > 1900) { if (y < lo) lo = y; if (y > hi) hi = y; } }
  if (!isFinite(lo)) { lo = 1950; hi = 2026; }
  const from = $("#yr-from"), to = $("#yr-to");
  from.min = to.min = lo; from.max = to.max = hi; from.value = lo; to.value = hi;
  yearMin = lo; yearMax = hi;
  $("#yr-from-lab").textContent = lo; $("#yr-to-lab").textContent = hi;
  // full per-year distribution — the fixed "shadow" layer behind the histogram
  MAP.histLo = lo; MAP.histN = hi - lo + 1;
  MAP.histFull = new Array(MAP.histN).fill(0);
  for (const p of MAP.points) { const i = p[4] - lo; if (i >= 0 && i < MAP.histN) MAP.histFull[i]++; }
  from.oninput = applyYear; to.oninput = applyYear;
  updateBand();
}
function colorOf(p) {  // -> {rgb, hl, big};  p = [x,y,macro,sub,year,pmask,oa]
  if (cmode === "condition") {
    const mask = p[5], multi = popcount(mask) > 1;
    const rgb = multi ? MULTI_RGB : (COND_RGB[mask] || [200, 200, 208]);
    // no selection -> everything lit; otherwise only the selected exact-set regions
    const hl = MAP.condSel.size === 0 ? true : MAP.condSel.has(mask);
    return { rgb, hl, big: multi };
  }
  const macro = p[2];
  let hl = true;
  if (MAP.focus) hl = MAP.focus.lvl === "macro" ? macro === MAP.focus.id : p[3] === MAP.focus.id;
  return { rgb: SUBRGB[p[3]] || MACRORGB[macro] || clusterRGB(macro), hl, big: false };
}
function drawMap() {
  const cv = $("#mapcanvas"), dpr = window.devicePixelRatio || 1;
  cv.width = cv.clientWidth * dpr; cv.height = cv.clientHeight * dpr;
  const W = cv.width, H = cv.height, ctx = cv.getContext("2d");
  MAP.tx = { minx: MAP.bounds.minx, maxx: MAP.bounds.maxx, miny: MAP.bounds.miny,
             maxy: MAP.bounds.maxy, W, H, pad: 8 * dpr, z: view.z, ox: view.ox, oy: view.oy };
  const { sx, sy } = makeProj(MAP.tx);
  const img = ctx.createImageData(W, H), buf = img.data;
  // point size scales continuously with zoom (sub-linear so it stays sane at high zoom)
  const NS = Math.max(2, Math.min(14, Math.round(1.5 * dpr * Math.sqrt(view.z))));
  const BS = NS + Math.max(1, Math.round(dpr));
  const put = (px, py, r, g, b, s) => {
    px |= 0; py |= 0;
    for (let dx = 0; dx < s; dx++) for (let dy = 0; dy < s; dy++) {
      const X = px + dx, Y = py + dy;
      if (X < 0 || Y < 0 || X >= W || Y >= H) continue;
      const i = (Y * W + X) * 4; buf[i] = r; buf[i + 1] = g; buf[i + 2] = b; buf[i + 3] = 255;
    }
  };
  let shown = 0;
  // 3 layered passes: dimmed background, highlighted points, then emphasized (big) on top
  for (const p of MAP.points) {
    if (!visible(p) || colorOf(p).hl) continue;
    put(sx(p[0]), sy(p[1]), 226, 226, 234, NS);
  }
  for (const p of MAP.points) {
    if (!visible(p)) continue; const k = colorOf(p); if (!k.hl || k.big) continue;
    put(sx(p[0]), sy(p[1]), k.rgb[0], k.rgb[1], k.rgb[2], NS); shown++;
  }
  for (const p of MAP.points) {
    if (!visible(p)) continue; const k = colorOf(p); if (!k.hl || !k.big) continue;
    put(sx(p[0]), sy(p[1]), k.rgb[0], k.rgb[1], k.rgb[2], BS); shown++;
  }
  ctx.putImageData(img, 0, 0);
  if (cmode === "topic" && MAP.focus) {
    let cl = null;
    for (const m of MAP.macros) {
      if (MAP.focus.lvl === "macro" && m.cluster === MAP.focus.id) { cl = m; break; }
      if (MAP.focus.lvl === "sub") { const s = m.subs.find(s => s.cluster === MAP.focus.id); if (s) { cl = s; break; } }
    }
    if (cl) {
      ctx.fillStyle = "#1c1c28"; ctx.font = `600 ${13 * dpr}px -apple-system, sans-serif`;
      ctx.fillText(cl.label, sx(cl.cx) + 6, sy(cl.cy));
    }
  }
  $("#map-count").textContent = shown.toLocaleString() + " papers";
}
// year histogram above the slider: full distribution (shadow) + current filter result (accent),
// both normalized to the full peak so the accent fill reads as the selected share of each year.
function drawHist() {
  const cv = $("#yr-hist"); if (!cv || !MAP.histFull) return;
  const dpr = window.devicePixelRatio || 1;
  cv.width = cv.clientWidth * dpr; cv.height = cv.clientHeight * dpr;
  const W = cv.width, H = cv.height, ctx = cv.getContext("2d");
  ctx.clearRect(0, 0, W, H);
  const lo = MAP.histLo, n = MAP.histN, full = MAP.histFull;
  const sel = new Array(n).fill(0);            // per-year counts passing ALL current filters
  for (const p of MAP.points) {
    if (!visible(p) || !colorOf(p).hl) continue;
    const i = p[4] - lo; if (i >= 0 && i < n) sel[i]++;
  }
  let max = 1; for (let i = 0; i < n; i++) if (full[i] > max) max = full[i];
  const denom = (histLog ? Math.log1p(max) : max) || 1;   // shared scale so both layers stay comparable
  const yh = v => (histLog ? Math.log1p(v) : v) / denom * H;
  const slot = W / n, bw = Math.max(dpr, slot - (slot > 3 * dpr ? dpr : 0));
  for (let i = 0; i < n; i++) {
    const x = i * slot;
    if (full[i]) { const h = yh(full[i]); ctx.fillStyle = HIST_BG;  ctx.fillRect(x, H - h, bw, h); }
    if (sel[i])  { const h = yh(sel[i]);  ctx.fillStyle = HIST_SEL; ctx.fillRect(x, H - h, bw, h); }
  }
}
// toggle a group of exact-set masks in/out of the selection (all-or-nothing for the group)
function toggleCond(masks) {
  if (!masks.length) return;
  const all = masks.every(mk => MAP.condSel.has(mk));
  masks.forEach(mk => all ? MAP.condSel.delete(mk) : MAP.condSel.add(mk));
  drawMap(); drawHist(); buildLegend();
}
// one panel row: dot-matrix (members) + label + proportional bar + count
function condRow(host, masks, members, count, max, condRGBcss) {
  const sel = MAP.condSel, lit = masks.filter(mk => sel.has(mk)).length;
  const row = document.createElement("div");
  row.className = "legrow uprow"
    + (lit && lit === masks.length ? " active" : "")
    + (sel.size && !lit ? " dim" : "");
  const dots = COND_INFO.map(ci => members & ci.m
    ? `<span class="cdot on" style="background:${condRGBcss(ci.m)};border-color:${condRGBcss(ci.m)}"></span>`
    : `<span class="cdot"></span>`).join("");
  const label = COND_INFO.filter(ci => members & ci.m).map(ci => ci.name).join(" + ") || "untagged";
  const pct = max ? Math.max(3, Math.round(count / max * 100)) : 0;
  row.innerHTML = `<span class="barfill" style="width:${pct}%"></span>
    <span class="cdots">${dots}</span>
    <span class="lab" title="${esc(label)}">${esc(label)}</span>
    <span class="sz">${count.toLocaleString()}</span>`;
  if (masks.length) row.onclick = () => toggleCond(masks);
  host.appendChild(row);
}
function buildLegend() {
  const host = $("#legend"); host.innerHTML = "";
  if (cmode === "condition") {
    // counts over the currently-visible points, grouped by EXACT condition set (pmask)
    const exact = new Map();                 // mask -> count (disjoint regions)
    const totals = {};                       // bit  -> count (condition mentioned anywhere)
    COND_INFO.forEach(ci => totals[ci.m] = 0);
    for (const p of MAP.points) {
      if (!visible(p)) continue;
      const m = p[5]; if (!m) continue;      // skip untagged points
      exact.set(m, (exact.get(m) || 0) + 1);
      COND_INFO.forEach(ci => { if (m & ci.m) totals[ci.m]++; });
    }
    const condRGBcss = m => `rgb(${(COND_RGB[m] || [200, 200, 208]).join(",")})`;
    const present = [...exact.keys()];

    // section 1 — each condition (any mention): selects all of its regions as a group
    const h1 = document.createElement("div"); h1.className = "leghdr"; h1.textContent = "by condition";
    host.appendChild(h1);
    const totMax = Math.max(1, ...COND_INFO.map(ci => totals[ci.m]));
    COND_INFO.forEach(ci =>
      condRow(host, present.filter(mk => mk & ci.m), ci.m, totals[ci.m], totMax, condRGBcss));

    // section 2 — exact regions, sorted by size so the heaviest overlaps surface first
    const h2 = document.createElement("div"); h2.className = "leghdr"; h2.textContent = "by overlap";
    host.appendChild(h2);
    const rows = [...exact.entries()].sort((a, b) => b[1] - a[1]);
    const exMax = Math.max(1, ...rows.map(r => r[1]));
    rows.forEach(([mask, count]) => condRow(host, [mask], mask, count, exMax, condRGBcss));
    return;
  }
  // topic mode: expandable macro -> sub tree
  const focusEq = (lvl, id) => MAP.focus && MAP.focus.lvl === lvl && MAP.focus.id === id;
  const setFocus = (lvl, id) => {
    MAP.focus = focusEq(lvl, id) ? null : { lvl, id };
    drawMap(); drawHist(); buildLegend();
  };
  MAP.macros.forEach(macro => {
    const grp = document.createElement("div");
    const head = document.createElement("div");
    head.className = "legrow" + (focusEq("macro", macro.cluster) ? " active" : "");
    head.innerHTML = `<span class="caret">${macro._open ? "▾" : "▸"}</span>
      <span class="swatch" style="background:${macro._rgb}"></span>
      <span class="lab" title="${esc(macro.label)}">${esc(macro.label)}</span>
      <span class="sz">${macro.size.toLocaleString()}</span>`;
    head.querySelector(".caret").onclick = (e) => { e.stopPropagation(); macro._open = !macro._open; buildLegend(); };
    head.onclick = () => setFocus("macro", macro.cluster);
    grp.appendChild(head);
    if (macro._open) {
      macro.subs.forEach(s => {
        const sr = document.createElement("div");
        sr.className = "legrow legsub" + (focusEq("sub", s.cluster) ? " active" : "");
        sr.innerHTML = `<span class="swatch sm" style="background:${s._rgb}"></span>
          <span class="lab" title="${esc(s.label)}">${esc(s.label)}</span>
          <span class="sz">${s.size.toLocaleString()}</span>`;
        sr.onclick = () => setFocus("sub", s.cluster);
        grp.appendChild(sr);
      });
    }
    host.appendChild(grp);
  });
}

// color-mode toggle
$$("#map-mode button").forEach(b => b.onclick = () => {
  cmode = b.dataset.cm;
  $$("#map-mode button").forEach(x => x.classList.toggle("on", x === b));
  MAP.focus = null; MAP.condSel = new Set();
  drawMap(); drawHist(); buildLegend();
});

// ---- map interaction: click-to-open, zoom, pan -------------------------
const mapcv = $("#mapcanvas");
let dragging = false, dragMoved = false, lastX = 0, lastY = 0;

function evToCanvas(e) {  // event -> device-pixel canvas coords
  const rect = mapcv.getBoundingClientRect();
  return [(e.clientX - rect.left) * (mapcv.width / rect.width),
          (e.clientY - rect.top) * (mapcv.height / rect.height)];
}

mapcv.addEventListener("click", e => {
  if (!MAP.tx || dragMoved) { dragMoved = false; return; }  // ignore the click that ends a drag
  const [mx, my] = evToCanvas(e);
  const { sx, sy } = makeProj(MAP.tx);
  let best = null, bd = Infinity;
  for (const p of MAP.points) {
    if (!visible(p)) continue;
    const dx = sx(p[0]) - mx, dy = sy(p[1]) - my, d = dx * dx + dy * dy;
    if (d < bd) { bd = d; best = p; }
  }
  if (best && bd <= (9 * (window.devicePixelRatio || 1)) ** 2)
    api(`/api/map/at?x=${best[0]}&y=${best[1]}`).then(r => { if (r.id) openPaper(r.id); });
});

mapcv.addEventListener("wheel", e => {
  e.preventDefault();
  if (!MAP.tx) return;
  const [mx, my] = evToCanvas(e);
  const nz = Math.min(40, Math.max(1, view.z * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
  view.ox = mx - (mx - view.ox) * (nz / view.z);   // keep the point under the cursor fixed
  view.oy = my - (my - view.oy) * (nz / view.z);
  view.z = nz; clampPan(); drawMap();
}, { passive: false });

mapcv.addEventListener("mousedown", e => { dragging = true; dragMoved = false; lastX = e.clientX; lastY = e.clientY; });
window.addEventListener("mousemove", e => {
  if (!dragging) return;
  const sc = mapcv.width / mapcv.getBoundingClientRect().width;
  view.ox += (e.clientX - lastX) * sc; view.oy += (e.clientY - lastY) * sc;
  lastX = e.clientX; lastY = e.clientY; dragMoved = true;
  clampPan(); drawMap();
});
window.addEventListener("mouseup", () => { dragging = false; });

$("#map-reset").onclick = () => { view = { z: 1, ox: 0, oy: 0 }; drawMap(); };
function mapRefilter() { drawMap(); drawHist(); if (cmode === "condition") buildLegend(); }
$$("#map-oa button").forEach(b => b.onclick = () => {
  oaOnly = !!b.dataset.oa;
  $$("#map-oa button").forEach(x => x.classList.toggle("on", x === b));
  mapRefilter();
});
$$("#map-type button").forEach(b => b.onclick = () => {
  mapType = b.dataset.type;
  $$("#map-type button").forEach(x => x.classList.toggle("on", x === b));
  mapRefilter();
});
$("#hist-scale").onclick = e => { histLog = !histLog; e.currentTarget.textContent = histLog ? "log" : "linear"; e.currentTarget.classList.toggle("on", histLog); drawHist(); };

// drag the band to slide the whole window (both ends together), preserving its width
(() => {
  const band = $("#yr-band"), dual = $("#yr-dual");
  let startX = 0, startLo = 0, width = 0, bandDrag = false;
  band.addEventListener("mousedown", e => {
    const from = $("#yr-from"), to = $("#yr-to");
    bandDrag = true; startX = e.clientX;
    startLo = Math.min(+from.value, +to.value);
    width = Math.abs(+to.value - +from.value);
    document.body.style.userSelect = "none";
    e.preventDefault();
  });
  window.addEventListener("mousemove", e => {
    if (!bandDrag) return;
    const from = $("#yr-from"), to = $("#yr-to");
    const lo = +from.min, hi = +from.max, trav = (dual.clientWidth || 16) - 15;
    const dy = Math.round((e.clientX - startX) / trav * (hi - lo));
    const nlo = Math.max(lo, Math.min(hi - width, startLo + dy));
    from.value = nlo; to.value = nlo + width;
    applyYear();
  });
  window.addEventListener("mouseup", () => {
    if (!bandDrag) return;
    bandDrag = false; document.body.style.userSelect = "";
  });
})();

window.addEventListener("resize", () => { if (mapLoaded && $("#panel-map").classList.contains("active")) { drawMap(); drawHist(); } });
