"use strict";
/* Girls Gone Canon dashboard. Plain DOM + inline SVG, no dependencies.
   Data comes from data.js (written by update.py) as window.GGC_DATA. */

const D = window.GGC_DATA;
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};
const svgEl = (tag, attrs) => {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
};
const fmtInt = (n) => n.toLocaleString("en-US");
const fmtDate = (s) => new Date(s + "T12:00:00Z").toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
const fmtQuarter = (s) => `Q${Math.floor((Number(s.slice(5, 7)) - 1) / 3) + 1} ${s.slice(0, 4)}`;
const fmtMonth = (s) => new Date(s + "-15T12:00:00Z").toLocaleDateString("en-US", { year: "numeric", month: "short" });
const fmtDur = (s) => {
  if (s == null) return "–";
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
};
const median = (a) => {
  if (!a.length) return null;
  const s = [...a].sort((x, y) => x - y), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

// Series buckets shown on charts. Color follows the entity and never changes.
const GROUPS = [
  { key: "ASOIAF", label: "ASOIAF read-through", color: "var(--s1)", match: (s) => s === "ASOIAF" },
  { key: "House of the Dragon", label: "House of the Dragon", color: "var(--s2)", match: (s) => s === "House of the Dragon" },
  { key: "A Knight of the Seven Kingdoms", label: "A Knight of the Seven Kingdoms", color: "var(--s3)", match: (s) => s === "A Knight of the Seven Kingdoms" },
  { key: "His Dark Materials", label: "His Dark Materials", color: "var(--s4)", match: (s) => s === "His Dark Materials" },
  { key: "Fire & Blood", label: "Fire & Blood", color: "var(--s5)", match: (s) => s === "Fire & Blood" },
  { key: "Other", label: "Everything else", color: "var(--s6)", match: () => true },
];
const groupOf = (series) => GROUPS.find((g) => g.match(series));
const BOOKS = D.books;
const BOOK_TITLE = Object.fromEntries(BOOKS.map((b) => [b.key, b.title]));
const TOTAL_CHAPTERS = Object.values(D.chapter_counts).reduce((a, c) => a + Object.values(c).reduce((x, y) => x + y, 0), 0);
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const WEEKDAY_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

// ---------- theme ---------------------------------------------------------------
(function themeInit() {
  let saved = null;
  try { saved = localStorage.getItem("ggc-theme"); } catch (e) { /* private mode */ }
  if (saved === "dark" || saved === "light") document.documentElement.dataset.theme = saved;
  $("theme-btn").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("ggc-theme", next); } catch (e) { /* ignore */ }
  });
})();

// ---------- tooltip -------------------------------------------------------------
const tip = $("tip");
function showTip(evt, title, rows) {
  tip.replaceChildren();
  if (title) tip.appendChild(el("div", "t", title));
  for (const r of rows) {
    const row = el("div", "row");
    if (r.color) { const i = el("i"); i.style.setProperty("--c", r.color); row.appendChild(i); }
    row.appendChild(el("b", null, r.value));
    row.appendChild(el("span", null, r.label));
    tip.appendChild(row);
  }
  tip.hidden = false;
  moveTip(evt);
}
function moveTip(evt) {
  const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = evt.clientX + pad, y = evt.clientY + pad;
  if (x + w > innerWidth - 8) x = evt.clientX - w - pad;
  if (y + h > innerHeight - 8) y = evt.clientY - h - pad;
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
const hideTip = () => { tip.hidden = true; };
function bindTip(node, fn) {
  node.addEventListener("pointerenter", (e) => showTip(e, ...fn()));
  node.addEventListener("pointermove", moveTip);
  node.addEventListener("pointerleave", hideTip);
  node.setAttribute("tabindex", "0");
  node.addEventListener("focus", () => {
    const r = node.getBoundingClientRect();
    showTip({ clientX: r.left + r.width / 2, clientY: r.top }, ...fn());
  });
  node.addEventListener("blur", hideTip);
}

// ---------- header + KPIs -------------------------------------------------------
function paintHeader() {
  const p = D.podcast;
  if (p.title) { $("title").textContent = p.title.replace(/\s*cast$/i, ""); document.title = p.title + ", by the numbers"; }
  if (p.description) $("tagline").textContent = p.description.length > 220 ? p.description.slice(0, 217) + "…" : p.description;
  if (p.image) { const a = $("art"); a.src = p.image; a.hidden = false; a.addEventListener("error", () => { a.hidden = true; }); }
  if (p.feed) $("feed-link").href = p.feed;
  if (p.link) $("site-link").href = p.link;
  const eps = D.episodes;
  const nTr = eps.filter((e) => e.transcripts && e.transcripts.length).length;
  $("updated").textContent = `Updated ${fmtDate(D.generated_at.slice(0, 10))} · ${fmtInt(eps.length)} episodes · ${fmtDate(eps[0].date)} to ${fmtDate(eps[eps.length - 1].date)}` +
    (nTr ? ` · transcripts linked on ${nTr}` : "");
  if (D.source === "sample") $("sample-note").hidden = false;
}

function gapsBetween(eps) {
  const out = [];
  for (let i = 1; i < eps.length; i++) {
    out.push((new Date(eps[i].date) - new Date(eps[i - 1].date)) / 86400000);
  }
  return out;
}

function paintKpis() {
  const eps = D.episodes;
  const secs = eps.reduce((a, e) => a + (e.duration || 0), 0);
  const covered = Object.values(D.coverage).reduce((a, b) => a + Object.values(b).reduce((x, y) => x + y.length, 0), 0);
  const guestEps = eps.filter((e) => e.guests.length).length;
  const guestNames = new Set(eps.flatMap((e) => e.guests));
  const med = median(eps.map((e) => e.duration).filter(Boolean));
  const gap = median(gapsBetween(eps));
  const last12 = eps.filter((e) => new Date(e.date) >= new Date(Date.now() - 365 * 86400000)).length;
  const tiles = [
    ["Episodes", fmtInt(eps.length), `${last12} in the last 12 months`],
    ["Hours recorded", fmtInt(Math.round(secs / 3600)), `about ${Math.round(secs / 86400)} days of audio`],
    ["Chapters covered", `${covered} of ${TOTAL_CHAPTERS}`, "across all five books", "small"],
    ["Guest appearances", fmtInt(guestEps), `${guestNames.size} different guests`],
    ["Typical episode", fmtDur(med), "median runtime"],
    ["Typical gap", gap != null ? `${Math.round(gap)} days` : "–", "median time between releases"],
  ];
  const root = $("kpis");
  root.replaceChildren();
  for (const [lbl, val, sub, cls] of tiles) {
    const t = el("div", "tile");
    t.appendChild(el("div", "lbl", lbl));
    t.appendChild(el("div", "val" + (cls ? " " + cls : ""), val));
    t.appendChild(el("div", "sub", sub));
    root.appendChild(t);
  }
}

// ---------- the read ------------------------------------------------------------
function paintRead() {
  const cov = D.coverage;
  let done = 0;
  const meters = $("book-meters");
  meters.replaceChildren();
  for (const b of BOOKS) {
    const total = Object.values(D.chapter_counts[b.key]).reduce((x, y) => x + y, 0);
    const got = Object.values(cov[b.key] || {}).reduce((x, y) => x + y.length, 0);
    done += got;
    const m = el("div", "meter" + (got >= total ? " done" : ""));
    const name = el("div", "name", b.title);
    name.appendChild(el("small", null, `${b.key} · ${total} chapters`));
    const bar = el("div", "bar");
    const fill = el("div", "fill");
    fill.style.width = (100 * got / total).toFixed(1) + "%";
    bar.appendChild(fill);
    bar.setAttribute("role", "img");
    bar.setAttribute("aria-label", `${b.title}: ${got} of ${total} chapters covered`);
    m.append(name, bar, el("div", "num", `${got} / ${total}`));
    meters.appendChild(m);
  }
  const pct = 100 * done / TOTAL_CHAPTERS;
  $("hero-pct").textContent = (pct >= 99.95 ? "100" : pct.toFixed(1)) + "%";
  $("hero-lbl").textContent = `of A Song of Ice and Fire covered · ${done} of ${TOTAL_CHAPTERS} chapters`;

  // Pace and projection from the last 12 months of chapter episodes.
  const chapterEps = D.episodes.filter((e) => e.chapter_key);
  const cutoff = new Date(Date.now() - 365 * 86400000);
  const recent = new Set(chapterEps.filter((e) => new Date(e.date) >= cutoff).flatMap((e) => e.chapter_keys || [e.chapter_key]));
  const remaining = TOTAL_CHAPTERS - done;
  const last = chapterEps[chapterEps.length - 1];
  let note = "";
  if (last) note += `Latest chapter: ${BOOK_TITLE[last.book] || last.book}, ${last.pov} ${romanList(last)} (${fmtDate(last.date)}). `;
  if (remaining === 0) note += "Every chapter is covered. The Winds of Winter is George's problem now.";
  else if (recent.size === 0) note += `${remaining} chapters to go. No chapter episodes in the last 12 months, so no projection.`;
  else {
    const years = remaining / recent.size;
    const finish = new Date(Date.now() + years * 365 * 86400000);
    note += `${recent.size} new chapters in the last 12 months. At that pace the remaining ${remaining} wrap up around ${finish.toLocaleDateString("en-US", { month: "long", year: "numeric" })}.`;
  }
  $("hero-note").textContent = note;
  paintPovTable();
}

function roman(n) {
  const map = [[10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"]];
  let s = "";
  for (const [v, r] of map) while (n >= v) { s += r; n -= v; }
  return s;
}
function romanList(e) {
  const ords = e.ordinals && e.ordinals.length ? e.ordinals : [e.ordinal];
  return ords.map(roman).join("/");
}

function paintPovTable() {
  const povs = new Set();
  for (const b of BOOKS) for (const p in D.chapter_counts[b.key]) povs.add(p);
  // Order by total chapters, prologue/epilogue at the bottom.
  const rows = [...povs].map((p) => {
    let tot = 0, got = 0;
    const cells = BOOKS.map((b) => {
      const t = D.chapter_counts[b.key][p] || 0;
      const g = ((D.coverage[b.key] || {})[p] || []).length;
      tot += t; got += g;
      return { t, g };
    });
    return { p, cells, tot, got };
  }).sort((a, b) => {
    const ae = /^(Prologue|Epilogue)$/.test(a.p), be = /^(Prologue|Epilogue)$/.test(b.p);
    if (ae !== be) return ae ? 1 : -1;
    return b.tot - a.tot || a.p.localeCompare(b.p);
  });
  const table = $("pov-table");
  table.replaceChildren();
  const thead = el("thead"), tr = el("tr");
  tr.appendChild(el("th", null, "POV"));
  for (const b of BOOKS) tr.appendChild(el("th", "book", b.key));
  tr.appendChild(el("th", "num", "Total"));
  thead.appendChild(tr); table.appendChild(thead);
  const tbody = el("tbody");
  for (const r of rows) {
    const tr = el("tr");
    tr.appendChild(el("td", null, r.p));
    r.cells.forEach((c, i) => {
      const td = el("td", "cell");
      if (!c.t) { td.classList.add("none"); td.textContent = "·"; }
      else {
        const ratio = c.g / c.t;
        const step = ratio === 0 ? 0 : Math.min(6, Math.max(1, Math.ceil(ratio * 6)));
        if (step) td.classList.add("c" + step);
        const s = el("span", null, `${c.g} / ${c.t}`);
        td.appendChild(s);
        td.title = `${r.p} in ${BOOKS[i].title}: ${c.g} of ${c.t} chapters`;
      }
      tr.appendChild(td);
    });
    tr.appendChild(el("td", "num tot", `${r.got} / ${r.tot}`));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
}

// ---------- filters -------------------------------------------------------------
const state = { range: "all", groups: new Set(GROUPS.map((g) => g.key)), sort: { key: "date", dir: -1 }, q: "", shown: 100 };

function initFilters() {
  $("range").addEventListener("change", (e) => { state.range = e.target.value; state.shown = 100; paintFiltered(); });
  const chips = $("series-chips");
  const present = new Set(D.episodes.map((e) => groupOf(e.series).key));
  for (const g of GROUPS) {
    if (!present.has(g.key)) continue;
    const b = el("button", "chip");
    b.type = "button";
    b.setAttribute("aria-pressed", "true");
    b.style.setProperty("--c", g.color);
    b.appendChild(el("i", "sw"));
    b.appendChild(document.createTextNode(g.label));
    b.addEventListener("click", () => {
      if (state.groups.has(g.key)) { if (state.groups.size === 1) return; state.groups.delete(g.key); }
      else state.groups.add(g.key);
      b.setAttribute("aria-pressed", state.groups.has(g.key) ? "true" : "false");
      state.shown = 100;
      paintFiltered();
    });
    chips.appendChild(b);
  }
  $("search").addEventListener("input", (e) => { state.q = e.target.value.trim().toLowerCase(); state.shown = 100; paintEpisodeTable(); });
  $("more").addEventListener("click", () => { state.shown += 200; paintEpisodeTable(); });
}

function filtered() {
  let eps = D.episodes.filter((e) => state.groups.has(groupOf(e.series).key));
  if (state.range !== "all") {
    const cutoff = new Date(); cutoff.setMonth(cutoff.getMonth() - Number(state.range));
    eps = eps.filter((e) => new Date(e.date) >= cutoff);
  }
  return eps;
}

function paintFiltered() {
  const eps = filtered();
  const all = D.episodes.length;
  $("filter-note").textContent = eps.length === all ? `${fmtInt(all)} episodes` : `${fmtInt(eps.length)} of ${fmtInt(all)} episodes`;
  paintOutput(eps);
  paintLength(eps);
  paintWeekday(eps);
  paintGuests(eps);
  paintLongest(eps);
  paintEpisodeTable();
}

// ---------- charts --------------------------------------------------------------
function chartFrame(container, height, pad) {
  const width = Math.max(320, container.clientWidth || 640);
  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, width, height, role: "img" });
  container.replaceChildren(svg);
  return { svg, width, height, pad, iw: width - pad.l - pad.r, ih: height - pad.t - pad.b };
}
function niceMax(v) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const m = v / p;
  const n = m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10;
  return n * p;
}
function yGrid(f, max, ticks, fmt) {
  const g = svgEl("g", { class: "grid" });
  for (let i = 0; i <= ticks; i++) {
    const v = max * i / ticks, y = f.pad.t + f.ih - f.ih * i / ticks;
    g.appendChild(svgEl("line", { x1: f.pad.l, x2: f.pad.l + f.iw, y1: y, y2: y }));
    const t = svgEl("text", { x: f.pad.l - 8, y: y + 4, "text-anchor": "end" });
    t.textContent = fmt ? fmt(v) : fmtInt(v);
    g.appendChild(t);
  }
  f.svg.appendChild(g);
}

// Stacked columns per year, one segment per series group.
function paintOutput(eps) {
  const years = [...new Set(D.episodes.map((e) => e.date.slice(0, 4)))].sort();
  const active = GROUPS.filter((g) => state.groups.has(g.key));
  const counts = {};
  for (const y of years) counts[y] = Object.fromEntries(active.map((g) => [g.key, 0]));
  for (const e of eps) counts[e.date.slice(0, 4)][groupOf(e.series).key]++;
  const totals = years.map((y) => Object.values(counts[y]).reduce((a, b) => a + b, 0));
  const max = niceMax(Math.max(...totals, 1));

  const legend = $("output-legend");
  legend.replaceChildren();
  for (const g of active) {
    const s = el("span"); const i = el("i"); i.style.setProperty("--c", g.color);
    s.append(i, document.createTextNode(g.label)); legend.appendChild(s);
  }

  const f = chartFrame($("output-chart"), 280, { l: 40, r: 12, t: 16, b: 28 });
  yGrid(f, max, 4);
  const slot = f.iw / years.length, bw = Math.min(28, slot * 0.6);
  years.forEach((y, i) => {
    const x = f.pad.l + slot * i + (slot - bw) / 2;
    let acc = 0;
    const segs = active.map((g) => ({ g, v: counts[y][g.key] })).filter((s) => s.v > 0);
    segs.forEach((s, k) => {
      const h = f.ih * s.v / max, top = f.pad.t + f.ih - f.ih * (acc + s.v) / max;
      acc += s.v;
      const isTop = k === segs.length - 1;
      const gap = k === 0 ? 0 : 2;
      const hh = Math.max(0, h - gap);
      let node;
      if (isTop && hh > 4) {
        const r = 4, x2 = x + bw, yb = top + hh;
        node = svgEl("path", { d: `M${x},${yb} V${top + r} a${r},${r} 0 0 1 ${r},-${r} H${x2 - r} a${r},${r} 0 0 1 ${r},${r} V${yb} Z` });
      } else node = svgEl("rect", { x, y: top, width: bw, height: hh });
      node.setAttribute("class", "seg");
      node.setAttribute("fill", s.g.color);
      bindTip(node, () => [y, segs.map((t) => ({ color: t.g.color, value: String(t.v), label: t.g.label })).reverse().concat([{ value: String(totals[i]), label: "total" }])]);
      f.svg.appendChild(node);
    });
    if (totals[i] > 0) {
      const lab = svgEl("text", { x: x + bw / 2, y: f.pad.t + f.ih - f.ih * totals[i] / max - 6, "text-anchor": "middle", class: "dlabel" });
      lab.textContent = totals[i];
      f.svg.appendChild(lab);
    }
    const every = slot >= 40 ? 1 : slot >= 22 ? 2 : 3;
    if (i % every === 0 || i === years.length - 1 && every === 1) {
      const t = svgEl("text", { x: x + bw / 2, y: f.height - 8, "text-anchor": "middle" });
      t.textContent = y;
      f.svg.appendChild(t);
    }
  });
  f.svg.appendChild(svgEl("line", { class: "axis", x1: f.pad.l, x2: f.pad.l + f.iw, y1: f.pad.t + f.ih, y2: f.pad.t + f.ih }));

  const best = totals.indexOf(Math.max(...totals));
  const thisYear = String(new Date().getFullYear());
  $("output-read").textContent = eps.length
    ? `${years[best]} was the busiest year with ${totals[best]} episodes.` + (years.includes(thisYear) ? ` ${thisYear} so far: ${totals[years.indexOf(thisYear)]}.` : "")
    : "No episodes in this range.";
}

// Monthly median runtime as a line with a crosshair.
function paintLength(eps) {
  // Bucket by quarter; each bucket is keyed by its first month so date math stays simple.
  const byQ = {};
  for (const e of eps) if (e.duration) {
    const q = e.date.slice(0, 4) + "-" + String(Math.floor((Number(e.date.slice(5, 7)) - 1) / 3) * 3 + 1).padStart(2, "0");
    (byQ[q] ||= []).push(e.duration);
  }
  const months = Object.keys(byQ).sort();
  const pts = months.map((m) => ({ m, v: median(byQ[m]) / 60, n: byQ[m].length }));
  const container = $("length-chart");
  if (pts.length < 2) { container.replaceChildren(el("p", "empty", "Not enough episodes with a runtime.")); $("length-read").textContent = ""; return; }
  const max = niceMax(Math.max(...pts.map((p) => p.v)));
  const f = chartFrame(container, 240, { l: 44, r: 40, t: 14, b: 26 });
  yGrid(f, max, 4, (v) => `${Math.round(v)}m`);
  const t0 = new Date(months[0] + "-01").getTime(), t1 = new Date(months[months.length - 1] + "-01").getTime();
  const xOf = (m) => t1 === t0 ? f.pad.l : f.pad.l + f.iw * (new Date(m + "-01").getTime() - t0) / (t1 - t0);
  const yOf = (v) => f.pad.t + f.ih - f.ih * v / max;
  const path = pts.map((p, i) => `${i ? "L" : "M"}${xOf(p.m).toFixed(1)},${yOf(p.v).toFixed(1)}`).join(" ");
  f.svg.appendChild(svgEl("path", { class: "area", d: `${path} L${xOf(pts[pts.length - 1].m)},${f.pad.t + f.ih} L${xOf(pts[0].m)},${f.pad.t + f.ih} Z` }));
  f.svg.appendChild(svgEl("path", { class: "line", d: path }));
  // x ticks: one per year boundary
  const seen = new Set();
  let lastX = -Infinity;
  for (const p of pts) {
    const y = p.m.slice(0, 4);
    if (seen.has(y)) continue; seen.add(y);
    if (xOf(p.m) - lastX < 40) continue;
    lastX = xOf(p.m);
    const t = svgEl("text", { x: xOf(p.m), y: f.height - 6, "text-anchor": "start" });
    t.textContent = y; f.svg.appendChild(t);
  }
  f.svg.appendChild(svgEl("line", { class: "axis", x1: f.pad.l, x2: f.pad.l + f.iw, y1: f.pad.t + f.ih, y2: f.pad.t + f.ih }));
  const last = pts[pts.length - 1];
  const endDot = svgEl("circle", { class: "dot", cx: xOf(last.m), cy: yOf(last.v), r: 4 });
  f.svg.appendChild(endDot);
  const endLab = svgEl("text", { class: "end-label", x: xOf(last.m) + 8, y: yOf(last.v) + 4 });
  endLab.textContent = `${Math.round(last.v)}m`;
  f.svg.appendChild(endLab);

  // crosshair + hover
  const cross = svgEl("line", { class: "cross", x1: 0, x2: 0, y1: f.pad.t, y2: f.pad.t + f.ih, visibility: "hidden" });
  const dot = svgEl("circle", { class: "dot", r: 4, visibility: "hidden" });
  const hit = svgEl("rect", { class: "hit", x: f.pad.l, y: f.pad.t, width: f.iw, height: f.ih });
  f.svg.append(cross, dot, hit);
  hit.addEventListener("pointermove", (evt) => {
    const rect = f.svg.getBoundingClientRect();
    const px = (evt.clientX - rect.left) * f.width / rect.width;
    let best = pts[0], bd = Infinity;
    for (const p of pts) { const d = Math.abs(xOf(p.m) - px); if (d < bd) { bd = d; best = p; } }
    cross.setAttribute("x1", xOf(best.m)); cross.setAttribute("x2", xOf(best.m)); cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", xOf(best.m)); dot.setAttribute("cy", yOf(best.v)); dot.setAttribute("visibility", "visible");
    showTip(evt, fmtQuarter(best.m), [{ color: "var(--s1)", value: fmtDur(Math.round(best.v * 60)), label: `median of ${best.n} episode${best.n === 1 ? "" : "s"}` }]);
  });
  hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); hideTip(); });

  const durs = eps.map((e) => e.duration).filter(Boolean);
  const longest = eps.filter((e) => e.duration).sort((a, b) => b.duration - a.duration)[0];
  $("length-read").textContent = `Median runtime per quarter. Overall median ${fmtDur(median(durs))}; the longest is ${fmtDur(longest.duration)}.`;
}

// Single-series columns, Monday to Sunday.
function paintWeekday(eps) {
  const counts = new Array(7).fill(0);
  for (const e of eps) counts[e.weekday]++;
  const max = niceMax(Math.max(...counts, 1));
  const f = chartFrame($("weekday-chart"), 240, { l: 40, r: 12, t: 14, b: 26 });
  yGrid(f, max, 4);
  const slot = f.iw / 7, bw = Math.min(24, slot * 0.6);
  const top = counts.indexOf(Math.max(...counts));
  counts.forEach((c, i) => {
    const x = f.pad.l + slot * i + (slot - bw) / 2, h = f.ih * c / max, y = f.pad.t + f.ih - h;
    let node;
    if (h > 4) { const r = 4; node = svgEl("path", { d: `M${x},${y + h} V${y + r} a${r},${r} 0 0 1 ${r},-${r} H${x + bw - r} a${r},${r} 0 0 1 ${r},${r} V${y + h} Z` }); }
    else node = svgEl("rect", { x, y, width: bw, height: h });
    node.setAttribute("class", "bar"); node.setAttribute("fill", "var(--s1)");
    bindTip(node, () => [WEEKDAYS[i], [{ color: "var(--s1)", value: String(c), label: "episodes" }]]);
    f.svg.appendChild(node);
    if (i === top && c > 0) { const l = svgEl("text", { class: "dlabel", x: x + bw / 2, y: y - 6, "text-anchor": "middle" }); l.textContent = c; f.svg.appendChild(l); }
    const t = svgEl("text", { x: x + bw / 2, y: f.height - 6, "text-anchor": "middle" }); t.textContent = WEEKDAYS[i]; f.svg.appendChild(t);
  });
  f.svg.appendChild(svgEl("line", { class: "axis", x1: f.pad.l, x2: f.pad.l + f.iw, y1: f.pad.t + f.ih, y2: f.pad.t + f.ih }));
  const share = eps.length ? Math.round(100 * counts[top] / eps.length) : 0;
  $("weekday-read").textContent = eps.length ? `${WEEKDAY_FULL[top]} is release day: ${share}% of episodes.` : "No episodes in this range.";
}

// ---------- tables --------------------------------------------------------------
function tableHead(table, cols, sortState, onSort) {
  const thead = el("thead"), tr = el("tr");
  for (const c of cols) {
    const th = el("th", (c.num ? "num " : "") + (onSort ? "sortable" : ""), c.label);
    if (onSort) {
      if (sortState && sortState.key === c.key) th.classList.add("sorted", sortState.dir > 0 ? "asc" : "desc");
      th.addEventListener("click", () => onSort(c.key));
    }
    tr.appendChild(th);
  }
  thead.appendChild(tr); table.replaceChildren(thead);
  const tbody = el("tbody"); table.appendChild(tbody); return tbody;
}
function seriesTag(series) {
  const g = groupOf(series);
  const s = el("span", "tag"); const i = el("i"); i.style.setProperty("--c", g.color);
  s.append(i, document.createTextNode(series)); return s;
}
function chapterLabel(e) {
  return e.chapter_key ? `${e.book} ${e.pov} ${romanList(e)}` : "";
}

function paintGuests(eps) {
  const byGuest = {};
  for (const e of eps) for (const g of (e.guest_details || e.guests.map((n) => ({ name: n })))) {
    const r = (byGuest[g.name] ||= { n: 0, first: e.date, last: e.date, affiliation: null, url: null });
    r.n++; if (e.date < r.first) r.first = e.date; if (e.date > r.last) r.last = e.date;
    if (g.affiliation && !r.affiliation) r.affiliation = g.affiliation;
    if (!r.url && e.episode_links && e.episode_links.length) r.url = e.episode_links[0].url;
  }
  const rows = Object.entries(byGuest).sort((a, b) => b[1].n - a[1].n || a[0].localeCompare(b[0])).slice(0, 15);
  const table = $("guest-table");
  const withGuest = eps.filter((e) => e.guests.length).length;
  const notesOnly = eps.filter((e) => (e.guest_details || []).some((g) => g.sources.includes("notes") && !g.sources.includes("title"))).length;
  $("guest-read").textContent = eps.length
    ? `${withGuest} of ${eps.length} episodes in range have a guest (${Math.round(100 * withGuest / eps.length)}%)` + (notesOnly ? `, ${notesOnly} of them named only in the show notes` : "") + `. Most frequent, top 15.`
    : "No episodes in this range.";
  if (!rows.length) { table.replaceChildren(); table.appendChild(el("caption", "empty", "No guests found in the titles for this range.")); return; }
  const tbody = tableHead(table, [{ label: "Guest" }, { label: "Episodes", num: true }, { label: "First" }, { label: "Latest" }]);
  for (const [g, r] of rows) {
    const tr = el("tr");
    const td = el("td");
    if (r.url) { const a = el("a", null, g); a.href = r.url; a.target = "_blank"; a.rel = "noopener"; td.appendChild(a); }
    else td.textContent = g;
    if (r.affiliation) td.appendChild(el("small", "mut", " · " + r.affiliation));
    tr.append(td, el("td", "num", String(r.n)), el("td", "mut", fmtDate(r.first)), el("td", "mut", fmtDate(r.last)));
    tbody.appendChild(tr);
  }
}

function paintLongest(eps) {
  const rows = eps.filter((e) => e.duration).sort((a, b) => b.duration - a.duration).slice(0, 10);
  const tbody = tableHead($("long-table"), [{ label: "Episode" }, { label: "Runtime", num: true }, { label: "Date" }]);
  for (const e of rows) {
    const tr = el("tr");
    const td = el("td"); const a = el("a", null, e.title); a.href = e.url || "#"; a.target = "_blank"; a.rel = "noopener"; td.appendChild(a);
    tr.append(td, el("td", "num", fmtDur(e.duration)), el("td", "mut", fmtDate(e.date)));
    tbody.appendChild(tr);
  }
  if (!rows.length) $("long-table").appendChild(el("caption", "empty", "No episodes in this range."));
}

const EP_COLS = [
  { key: "date", label: "Date" }, { key: "title", label: "Episode" }, { key: "series", label: "Series" },
  { key: "chapter", label: "Chapter" }, { key: "duration", label: "Runtime", num: true }, { key: "guests", label: "Guests" },
];
function paintEpisodeTable() {
  let eps = filtered();
  if (state.q) eps = eps.filter((e) => (e.title + " " + e.guests.join(" ") + " " + chapterLabel(e) + " " + (e.book ? BOOK_TITLE[e.book] : "") + " " + (e.notes || "")).toLowerCase().includes(state.q));
  const { key, dir } = state.sort;
  const val = (e) => key === "chapter" ? chapterLabel(e) : key === "guests" ? e.guests.join(", ") : key === "duration" ? (e.duration || 0) : e[key];
  eps.sort((a, b) => { const x = val(a), y = val(b); return (x < y ? -1 : x > y ? 1 : 0) * dir || (a.date < b.date ? 1 : -1); });
  const table = $("ep-table");
  const tbody = tableHead(table, EP_COLS, state.sort, (k) => {
    state.sort = state.sort.key === k ? { key: k, dir: -state.sort.dir } : { key: k, dir: k === "title" || k === "series" || k === "guests" ? 1 : -1 };
    paintEpisodeTable();
  });
  const show = eps.slice(0, state.shown);
  for (const e of show) {
    const tr = el("tr");
    const td = el("td"); const a = el("a", null, e.title); a.href = e.url || "#"; a.target = "_blank"; a.rel = "noopener"; td.appendChild(a);
    if (e.notes || (e.transcripts && e.transcripts.length)) {
      const b = el("button", "notes-btn", "notes");
      b.type = "button"; b.setAttribute("aria-expanded", "false"); b.title = "Show notes";
      b.addEventListener("click", () => toggleNotes(tr, e, b));
      td.appendChild(b);
    }
    const ts = el("td"); ts.appendChild(seriesTag(e.series));
    tr.append(el("td", "mut", fmtDate(e.date)), td, ts, el("td", "mut", chapterLabel(e)), el("td", "num", fmtDur(e.duration)), el("td", "mut", e.guests.join(", ")));
    tbody.appendChild(tr);
  }
  if (!eps.length) table.appendChild(el("caption", "empty", "Nothing matches."));
  const more = $("more");
  more.hidden = eps.length <= state.shown;
  more.textContent = `Show more (${fmtInt(eps.length - state.shown)} left)`;
}

function toggleNotes(tr, e, btn) {
  const open = tr.nextElementSibling && tr.nextElementSibling.classList.contains("notes-row");
  if (open) { tr.nextElementSibling.remove(); btn.setAttribute("aria-expanded", "false"); return; }
  const row = el("tr", "notes-row"), td = el("td");
  td.colSpan = EP_COLS.length;
  const box = el("div", "notes-box");
  if (e.notes) {
    for (const para of e.notes.split("\n")) if (para.trim()) box.appendChild(el("p", null, para));
  }
  const links = (e.episode_links || []).slice(0, 8);
  const trs = e.transcripts || [];
  if (links.length || trs.length) {
    const ul = el("div", "notes-links");
    if (trs.length) {
      const a = el("a", "pill", "Transcript"); a.href = trs[0].url; a.target = "_blank"; a.rel = "noopener"; ul.appendChild(a);
    }
    for (const l of links) { const a = el("a", "pill", l.label); a.href = l.url; a.target = "_blank"; a.rel = "noopener"; ul.appendChild(a); }
    box.appendChild(ul);
  }
  td.appendChild(box); row.appendChild(td);
  tr.after(row);
  btn.setAttribute("aria-expanded", "true");
}

// ---------- boot ----------------------------------------------------------------
function boot() {
  if (!D || !D.episodes || !D.episodes.length) {
    $("updated").textContent = "No data yet. Run python3 update.py to build docs/data.js.";
    return;
  }
  paintHeader();
  paintKpis();
  paintRead();
  initFilters();
  paintFiltered();
  let t;
  addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => { const eps = filtered(); paintOutput(eps); paintLength(eps); paintWeekday(eps); }, 150); });
}
boot();
