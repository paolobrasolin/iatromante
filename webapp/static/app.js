const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const api = (p) => fetch(p).then(r => r.json());
const PATHS = [];
const sel = { ask: null, search: null, map: null }; // selected pathology per tab
let MODE = "semantic";

const clusterColor = (c) => `hsl(${(c * 137.508) % 360} 58% 52%)`;
const esc = (s) => (s || "").replace(/[&<>]/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[m]));

// ---- bootstrap ----------------------------------------------------------
api("/api/meta").then(m => {
  $("#count").textContent = m.total.toLocaleString() + " papers";
  PATHS.push(...m.pathologies);
  buildChips("#ask-chips", "ask");
  buildChips("#search-chips", "search");
  buildChips("#map-chips", "map");
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
      if (tab === "map") loadMap();
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
function renderCards(host, results) {
  host.innerHTML = "";
  if (!results.length) { host.innerHTML = '<div class="empty">No results.</div>'; return; }
  results.forEach(r => {
    const div = document.createElement("div");
    div.className = "card";
    const tags = r.pathologies.map(p => `<span class="pill ${p}">${p}</span>`).join("")
      + (r.is_oa ? '<span class="pill oa">free full text</span>' : "")
      + (r.score != null ? `<span class="pill score">${Math.round(r.score * 100)}% match</span>` : "");
    const meta = [r.authors, r.venue, r.year].filter(Boolean).join(" · ");
    div.innerHTML = `<h3>${esc(r.title)}</h3><div class="meta">${esc(meta)}</div>
      <div class="snip">${r.snippet || ""}</div><div class="tags">${tags}</div>`;
    div.onclick = () => openPaper(r.id);
    host.appendChild(div);
  });
}

// ---- ask ----------------------------------------------------------------
$("#ask-go").onclick = doAsk;
$("#ask-q").addEventListener("keydown", e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) doAsk(); });
function doAsk() {
  const q = $("#ask-q").value.trim();
  if (!q) return;
  const host = $("#ask-results");
  host.innerHTML = '<div class="loading">Searching…</div>';
  fetch("/api/ask", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ q, pathology: sel.ask })
  }).then(r => r.json()).then(d => {
    const note = `<div class="note">Showing the most relevant papers for your question.
      A written, cited summary will land here later — for now, open any paper to read it.</div>`;
    host.innerHTML = note;
    const wrap = document.createElement("div");
    host.appendChild(wrap);
    renderCards(wrap, d.results);
  });
}

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
let mapLoaded = false, MAP = { points: [], clusters: [], focus: null, bounds: null };
function loadMap() {
  mapLoaded = true;
  const u = new URL("/api/map", location.origin);
  if (sel.map) u.searchParams.set("pathology", sel.map);
  Promise.all([api(u), api("/api/clusters")]).then(([m, c]) => {
    MAP.points = m.points; MAP.clusters = c.clusters; MAP.focus = null;
    computeBounds(); drawMap(); buildLegend();
  });
}
function computeBounds() {
  let a = Infinity, b = -Infinity, cc = Infinity, d = -Infinity;
  MAP.points.forEach(([x, y]) => { a = Math.min(a, x); b = Math.max(b, x); cc = Math.min(cc, y); d = Math.max(d, y); });
  MAP.bounds = { minx: a, maxx: b, miny: cc, maxy: d };
}
function drawMap() {
  const cv = $("#mapcanvas"), dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth, h = cv.clientHeight;
  cv.width = w * dpr; cv.height = h * dpr;
  const ctx = cv.getContext("2d"); ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  const { minx, maxx, miny, maxy } = MAP.bounds, pad = 16;
  const sx = (x) => pad + (x - minx) / (maxx - minx || 1) * (w - 2 * pad);
  const sy = (y) => h - pad - (y - miny) / (maxy - miny || 1) * (h - 2 * pad);
  for (const [x, y, c] of MAP.points) {
    const focused = MAP.focus == null || MAP.focus === c;
    ctx.globalAlpha = focused ? 0.7 : 0.06;
    ctx.fillStyle = clusterColor(c);
    ctx.beginPath(); ctx.arc(sx(x), sy(y), focused ? 2.2 : 1.6, 0, 6.283); ctx.fill();
  }
  ctx.globalAlpha = 1;
  if (MAP.focus != null) {
    const cl = MAP.clusters.find(c => c.cluster === MAP.focus);
    if (cl) {
      ctx.fillStyle = "#1c1c28"; ctx.font = "600 13px -apple-system, sans-serif";
      ctx.fillText(cl.label, sx(cl.cx) + 6, sy(cl.cy));
    }
  }
}
function buildLegend() {
  const host = $("#legend"); host.innerHTML = "";
  MAP.clusters.forEach(c => {
    const row = document.createElement("div");
    row.className = "legrow";
    row.innerHTML = `<span class="swatch" style="background:${clusterColor(c.cluster)}"></span>
      <span class="lab" title="${esc(c.label)}">${esc(c.label)}</span><span class="sz">${c.size}</span>`;
    row.onclick = () => {
      MAP.focus = MAP.focus === c.cluster ? null : c.cluster;
      $$(".legrow", host).forEach((r, i) =>
        r.classList.toggle("dim", MAP.focus != null && MAP.clusters[i].cluster !== MAP.focus));
      drawMap();
    };
    host.appendChild(row);
  });
}
window.addEventListener("resize", () => { if (mapLoaded && $("#panel-map").classList.contains("active")) drawMap(); });
