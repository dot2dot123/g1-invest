(function () {
  "use strict";
  const D = JSON.parse(document.getElementById("g1data").textContent);
  const PAGE = document.body.dataset.page; // "main" | "otw"
  const HZ = D.meta.horizons;
  const $ = (id) => document.getElementById(id);
  const LS_KEY = "g1.research.v1";
  const state = {
    view: PAGE === "otw" ? "OTW" : "SP",
    h: 12, sortKey: "prob", sortDir: -1, filter: "",
    live: {},           // ticker -> {s, px, at}
    spyW: null, refreshedAt: null, busy: false,
    research: loadResearch(),
  };

  // ---------- math (mirrors pipeline/build_site.py) ----------
  function lowerBound(a, x) { let lo = 0, hi = a.length; while (lo < hi) { const m = (lo + hi) >> 1; if (a[m] < x) lo = m + 1; else hi = m; } return lo; }
  function upperBound(a, x) { let lo = 0, hi = a.length; while (lo < hi) { const m = (lo + hi) >> 1; if (a[m] <= x) lo = m + 1; else hi = m; } return lo; }
  function qpct(x, q) {
    if (x == null || !isFinite(x)) return null;
    const n = q.length;
    if (x < q[0]) return 0; if (x > q[n - 1]) return 1;
    const lo = lowerBound(q, x), hi = upperBound(q, x) - 1;
    if (lo <= hi) return (lo + hi) / 2 / (n - 1);
    const a = hi, b = lo; return (a + (x - q[a]) / (q[b] - q[a])) / (n - 1);
  }
  function interp(x, xs, ys) {
    if (x <= xs[0]) return ys[0]; if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
    for (let i = 1; i < xs.length; i++) if (x <= xs[i]) { const t = (x - xs[i - 1]) / (xs[i] - xs[i - 1]); return ys[i - 1] + t * (ys[i] - ys[i - 1]); }
    return ys[ys.length - 1];
  }
  function scoreOne(key, f) {
    const m = D.models[key]; let z = m.intercept;
    m.features.forEach((name, i) => { const v = qpct(f[name], m.q[name]); z += m.coef[i] * (v == null ? 0 : v - 0.5); });
    const p = 1 / (1 + Math.exp(-z));
    const s = qpct(p, m.pq); const mids = m.cal.map((c) => c.mid);
    const o = { p_raw: p, pct: s };
    ["hit", "p10", "p50", "p90"].forEach((k) => (o[k] = interp(s, mids, m.cal.map((c) => c[k]))));
    return o;
  }
  function scoreAll(kind, f) { const s = {}; HZ.forEach((h) => (s[h] = scoreOne(kind + "_" + h, f))); return s; }

  // weekly-bar price features (same definitions as pipeline/features.py)
  function priceFeatures(a, spyMap, keys) {
    const n = a.length, i = n - 1, f = {};
    const at = (k) => (i - k >= 0 ? a[i - k] : null);
    const ratio = (x, y) => (x != null && y != null && y > 0 ? x / y - 1 : null);
    f.mom_12_1 = ratio(at(4), at(52)); f.mom_6_1 = ratio(at(4), at(26)); f.mom_3 = ratio(a[i], at(13));
    f.rev_1m = ratio(a[i], at(4)); f.mom_36_12 = ratio(at(52), at(156));
    const win = (len) => a.slice(Math.max(0, n - len));
    let w = win(52); f.dd_52w = w.length >= 40 ? a[i] / Math.max(...w) - 1 : null;
    w = win(40); f.trend40 = w.length >= 30 ? a[i] / (w.reduce((s, x) => s + x, 0) / w.length) - 1 : null;
    const r = []; for (let k = 1; k < n; k++) r.push(Math.log(a[k] / a[k - 1]));
    const sd = (xs) => { const m = xs.reduce((s, x) => s + x, 0) / xs.length; return Math.sqrt(xs.reduce((s, x) => s + (x - m) ** 2, 0) / (xs.length - 1)); };
    const r52 = r.slice(-52); f.vol_1y = r52.length >= 40 ? sd(r52) * Math.sqrt(52) : null;
    // beta vs SPY over 104 weekly returns aligned by bar date
    const pairs = [];
    for (let k = Math.max(1, n - 104); k < n; k++) {
      const s1 = spyMap.get(keys[k]), s0 = spyMap.get(keys[k - 1]);
      if (s1 != null && s0 != null) pairs.push([Math.log(a[k] / a[k - 1]), Math.log(s1 / s0)]);
    }
    if (pairs.length >= 52) {
      const mx = pairs.reduce((s, p) => s + p[0], 0) / pairs.length, my = pairs.reduce((s, p) => s + p[1], 0) / pairs.length;
      let c = 0, v = 0; pairs.forEach((p) => { c += (p[0] - mx) * (p[1] - my); v += (p[1] - my) ** 2; });
      f.beta_2y = v > 0 ? c / v : null;
    } else f.beta_2y = null;
    w = win(156);
    if (w.length >= 100) { let mx = -Infinity, mdd = 0; w.forEach((x) => { mx = Math.max(mx, x); mdd = Math.min(mdd, x / mx - 1); }); f.mdd_3y = mdd; } else f.mdd_3y = null;
    return f;
  }
  function fundFeatures(t, px, base) {
    const T = D.tick[t]; if (!T || T.kind !== "full") return base;
    const f = Object.assign({}, base), R = T.raw;
    if (R.shares_adj == null || !(px > 0)) return f;
    const mcap = px * R.shares_adj, debt = R.debt || 0, cash = R.cash || 0, ev = mcap + debt - cash;
    f.ey = R.ebit != null && ev > 0 ? R.ebit / ev : null;
    f.fcfy = R.cfo != null ? (R.cfo - (R.capex || 0)) / mcap : null;
    f.sy = R.rev != null && ev > 0 ? R.rev / ev : null;
    f.bm = R.equity != null ? R.equity / mcap : null;
    f.ey_vs_hist = f.ey != null && T.hist.ey != null ? f.ey - T.hist.ey : null;
    f.fcfy_vs_hist = f.fcfy != null && T.hist.fcfy != null ? f.fcfy - T.hist.fcfy : null;
    const sm = D.meta.secmed;
    f.ey_vs_sector = f.ey != null && sm.ey[T.sector] != null ? f.ey - sm.ey[T.sector] : null;
    f.fcfy_vs_sector = f.fcfy != null && sm.fcfy[T.sector] != null ? f.fcfy - sm.fcfy[T.sector] : null;
    return f;
  }

  // ---------- Yahoo fetch (direct, then AllOrigins CORS fallback) ----------
  function chartUrl(sym) { return `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=5y&interval=1wk&includeAdjustedClose=true`; }
  async function fetchChart(sym) {
    const direct = chartUrl(sym.replace(".", "-"));
    const candidates = [direct, `https://api.allorigins.win/raw?url=${encodeURIComponent(direct)}`, `https://api.codetabs.com/v1/proxy?quest=${encodeURIComponent(direct)}`];
    let lastErr;
    for (const url of candidates) {
      try {
        const res = await fetch(url, { cache: "no-store" });
        if (!res.ok) throw new Error(String(res.status));
        const data = await res.json();
        const r = data?.chart?.result?.[0];
        if (!r || !r.timestamp) throw new Error("no data");
        const adj = r.indicators?.adjclose?.[0]?.adjclose || r.indicators?.quote?.[0]?.close;
        const keys = [], a = [];
        r.timestamp.forEach((ts, k) => { if (adj[k] != null && adj[k] > 0) { keys.push(new Date(ts * 1000).toISOString().slice(0, 10)); a.push(adj[k]); } });
        return { meta: r.meta, keys, a };
      } catch (e) { lastErr = e; }
    }
    throw lastErr || new Error("fetch failed");
  }
  async function getSpy() {
    if (!state.spyW) { const s = await fetchChart("SPY"); state.spyW = s; state.spyMap = new Map(s.keys.map((k, i) => [k, s.a[i]])); }
    return state.spyW;
  }
  async function liveScore(t) {
    await getSpy();
    const c = await fetchChart(t);
    const pf = priceFeatures(c.a, state.spyMap, c.keys);
    const T = D.tick[t];
    const px = c.meta.regularMarketPrice;
    let kind = "price", f = pf;
    if (T && T.kind === "full") { kind = "full"; f = fundFeatures(t, px, Object.assign({}, T.f, pf)); }
    return { s: scoreAll(kind, f), kind, px, chart: c, at: new Date() };
  }

  // ---------- helpers ----------
  const pct = (x, d = 0) => (x == null || !isFinite(x) ? "–" : (x * 100).toFixed(d) + "%");
  const sgn = (x) => (x == null || !isFinite(x) ? "–" : (x >= 0 ? "+" : "") + (x * 100).toFixed(0) + "%");
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const laTime = (d) => d.toLocaleString("en-US", { timeZone: "America/Los_Angeles", month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }) + " PT";
  function verdictClass(v) { return v.startsWith("some") ? "v-some" : v.startsWith("weak") ? "v-weak" : v.startsWith("negative") ? "v-neg" : "v-none"; }
  function probColor(x, base) { const d = x - base; const g = Math.max(-1, Math.min(1, d / 0.06)); return g >= 0 ? `rgba(34,197,94,${0.12 + 0.5 * g})` : `rgba(239,68,68,${0.12 - 0.5 * g})`; }
  function scoresFor(t) { const L = state.live[t]; if (L) return { s: L.s, kind: L.kind, px: L.px, live: true }; const T = D.tick[t]; return T ? { s: T.s, kind: T.kind, px: T.px, live: false } : null; }
  function loadResearch() { try { return JSON.parse(localStorage.getItem(LS_KEY) || "[]"); } catch (_) { return []; } }
  function saveResearch() { localStorage.setItem(LS_KEY, JSON.stringify(state.research)); }

  // ---------- views ----------
  function views() {
    const v = [];
    if (PAGE === "main") v.push(["SP", "S&P 500"]);
    Object.keys(D.books).forEach((b) => v.push([b, D.book_label[b]]));
    v.push(["RES", "Research"]);
    return v;
  }
  function rowsForView() {
    const aiOf = {}; Object.values(D.books).forEach((rows) => rows.forEach((r) => { if (r.ai != null && aiOf[r.t] == null) aiOf[r.t] = r.ai; }));
    if (state.view === "SP") return Object.keys(D.tick).filter((t) => D.tick[t].sp).map((t) => ({ t, name: D.tick[t].name, ai: aiOf[t] }));
    if (state.view === "RES") return state.research.map((r) => ({ t: r.t, name: r.name, ai: aiOf[r.t], research: r }));
    return D.books[state.view].map((r) => ({ t: r.t, name: r.name || D.tick[r.t]?.name, ai: r.ai, shares: r.shares }));
  }
  function renderTabs() {
    $("tabs").innerHTML = views().map(([k, l]) => `<button class="tab ${state.view === k ? "on" : ""}" data-v="${k}">${esc(l)}</button>`).join("");
    $("hz").innerHTML = HZ.map((h) => { const m = D.models["full_" + h]; return `<button class="tab ${state.h === h ? "on" : ""}" data-h="${h}">${h}m <span class="${verdictClass(m.verdict)}">●</span></button>`; }).join("");
  }
  function renderBanner() {
    const mf = D.models["full_" + state.h], mp = D.models["price_" + state.h];
    $("hzNote").innerHTML = `<b>${state.h}-month view.</b> Backtest verdict: full model <span class="${verdictClass(mf.verdict)}">${mf.verdict}</span> (rank IC ${mf.metrics.rank_ic.toFixed(3)}, ~${mf.metrics.independent_periods} independent periods); price-only <span class="${verdictClass(mp.verdict)}">${mp.verdict}</span>. Historical share of S&amp;P names beating SPY over ${state.h}m in the test window: ${pct(mf.metrics.base_rate)}. "P(beat SPY)" is the out-of-sample beat rate of stocks that sat in the same score bucket, so with no edge it stays close to that base rate.`;
  }
  function renderTable() {
    const showNew = state.view === "NEW";
    let rows = rowsForView().map((r) => {
      const sc = r.research ? (state.live[r.t] ? scoresFor(r.t) : (r.research.s ? { s: r.research.s, kind: r.research.kind, px: r.research.px, live: false } : null)) : scoresFor(r.t);
      return Object.assign(r, { sc });
    });
    const f = state.filter.trim().toUpperCase();
    if (f) rows = rows.filter((r) => r.t.includes(f) || String(r.name || "").toUpperCase().includes(f));
    const val = (r) => {
      const s = r.sc?.s?.[state.h];
      switch (state.sortKey) {
        case "t": return r.t; case "ai": return r.ai ?? -1; case "pct": return s?.pct ?? -1; case "p50": return s?.p50 ?? -9;
        default: return s?.hit ?? -1;
      }
    };
    rows.sort((a, b) => { const x = val(a), y = val(b); return (x < y ? -1 : x > y ? 1 : 0) * state.sortDir; });
    const base = D.models["full_" + state.h].metrics.base_rate;
    const th = (k, l, cls = "") => `<th data-k="${k}" class="${cls}">${l}${state.sortKey === k ? (state.sortDir < 0 ? " ▾" : " ▴") : ""}</th>`;
    let html = `<table><thead><tr>${th("t", "Ticker")}${th("ai", "Danelfin AI")}${th("prob", `G1 P(beat SPY) ${state.h}m`)}${th("p50", "Excess vs SPY p10 / p50 / p90")}${th("pct", "Score pctl", "hide-sm")}<th class="hide-sm">All horizons (6→60m)</th><th>Model</th>${showNew ? "<th>Shares</th><th>Value</th>" : ""}${state.view === "RES" ? "<th></th>" : ""}</tr></thead><tbody>`;
    for (const r of rows) {
      const s = r.sc?.s?.[state.h];
      const strip = r.sc ? HZ.map((h) => { const x = r.sc.s[h].hit; return `<span title="${h}m" style="background:${probColor(x, D.models["full_" + h].metrics.base_rate)}">${(x * 100).toFixed(0)}</span>`; }).join("") : "";
      const kind = r.sc ? (r.sc.kind === "price" ? `<span class="pill po" title="No usable SEC fundamentals bundled; scored with the price-only model">price-only</span>` : `<span class="pill">full</span>`) : `<span class="pill">not scored</span>`;
      html += `<tr><td><b>${esc(r.t)}</b>${r.sc?.live ? ' <span class="muted small">live</span>' : ""}<span class="nm">${esc(r.name || "")}</span></td>
        <td>${r.ai != null ? r.ai : '<span class="muted">–</span>'}</td>
        <td class="prob" style="background:${s ? probColor(s.hit, base) : "transparent"}">${s ? pct(s.hit) : "–"}</td>
        <td>${s ? `${sgn(s.p10)} / <b>${sgn(s.p50)}</b> / ${sgn(s.p90)}` : "–"}</td>
        <td class="hide-sm">${s ? Math.round(s.pct * 100) : "–"}</td>
        <td class="hide-sm"><span class="strip">${strip}</span></td><td>${kind}</td>
        ${showNew ? `<td>${r.shares ?? "–"}</td><td>${r.sc?.px && r.shares ? "$" + (r.sc.px * r.shares).toLocaleString("en-US", { maximumFractionDigits: 0 }) : "–"}</td>` : ""}
        ${state.view === "RES" ? `<td><button class="ghost" data-unpin="${esc(r.t)}">Remove</button></td>` : ""}</tr>`;
    }
    html += "</tbody></table>";
    if (!rows.length) html = `<div class="card muted">${state.view === "RES" ? "No pinned tickers yet. Search a ticker above and press Pin." : "No rows."}</div>`;
    $("tbl").innerHTML = html;
    $("count").textContent = `${rows.length} names`;
  }
  function renderStatus() {
    $("asof").textContent = `Model + fundamentals built ${D.meta.built}; shipped prices as of ${D.meta.price_asof}.` + (state.refreshedAt ? ` Live prices refreshed ${laTime(state.refreshedAt)}.` : "");
  }
  function renderBacktest() {
    const rowsOf = (kind) => HZ.map((h) => {
      const m = D.models[kind + "_" + h], x = m.metrics;
      return `<tr><td>${h}m</td><td>${x.test_start.slice(0, 7)} → ${x.test_end.slice(0, 7)}</td><td>${x.independent_periods}</td><td>${pct(x.base_rate)}</td><td>${x.auc.toFixed(3)}</td><td>${x.mean_date_auc != null ? x.mean_date_auc.toFixed(3) : "–"}</td><td>${x.rank_ic.toFixed(3)} <span class="muted">(t≈${x.rank_ic_t_overlap_adj.toFixed(1)})</span></td><td>${sgn(x.top_minus_bottom_decile)}</td><td>${pct(x.tmb_share_positive)}</td><td>${x.ece.toFixed(3)}</td><td class="${verdictClass(m.verdict)}">${m.verdict}</td></tr>`;
    }).join("");
    const head = `<tr><th>Horizon</th><th>Test window (rebalance dates)</th><th>~Indep. periods</th><th>Base rate</th><th>AUC (pooled)</th><th>AUC (avg per date)</th><th>Rank IC</th><th>Top−bottom decile excess</th><th>Months top &gt; bottom</th><th>Calib. error (ECE)</th><th>Verdict</th></tr>`;
    $("bt").innerHTML = `<h3 class="small">Full model (price + SEC fundamentals)</h3><div class="tblwrap"><table>${head}${rowsOf("full")}</table></div>
      <h3 class="small">Price-only model (used for ETFs, foreign/multi-class filers without usable XBRL, and searched tickers)</h3><div class="tblwrap"><table>${head}${rowsOf("price")}</table></div>`;
  }

  // ---------- search ----------
  async function doSearch() {
    const t = $("q").value.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, "");
    if (!t) return;
    const out = $("searchOut");
    out.innerHTML = `<div class="card muted">Fetching ${esc(t)} and SPY from Yahoo…</div>`;
    try {
      const r = await liveScore(t);
      state.live[t] = { s: r.s, kind: r.kind, px: r.px, at: r.at };
      const spy = state.spyW, a = r.chart.a, sa = spy.a;
      const tr = (arr, k) => (arr.length > k ? arr[arr.length - 1] / arr[arr.length - 1 - k] - 1 : null);
      const name = D.tick[t]?.name || r.chart.meta.longName || r.chart.meta.shortName || "";
      const poNote = r.kind === "price" ? `<div class="disc"><b>Price-only score.</b> No SEC fundamentals are bundled for ${esc(t)}, so this uses the price-only model (momentum, volatility, drawdown, beta). Ask in chat for a full fundamentals score.</div>` : "";
      out.innerHTML = `<div class="card"><div class="row" style="justify-content:space-between"><div><b style="font-size:16px">${esc(t)}</b> <span class="muted">${esc(name)}</span> ${r.kind === "price" ? '<span class="pill po">price-only score</span>' : '<span class="pill">full model</span>'}</div>
        <button id="pinBtn">${state.research.some((x) => x.t === t) ? "Pinned ✓" : "Pin to Research"}</button></div>
        <div class="small muted">Price ${r.px?.toFixed(2)} ${esc(r.chart.meta.currency || "")} · fetched ${laTime(r.at)}</div>${poNote}
        <div class="tblwrap" style="margin-top:8px"><table><tr><th>Trailing return</th><th>6m</th><th>12m</th><th>3y</th></tr>
        <tr><td>${esc(t)}</td><td>${sgn(tr(a, 26))}</td><td>${sgn(tr(a, 52))}</td><td>${sgn(tr(a, 156))}</td></tr>
        <tr><td>SPY</td><td>${sgn(tr(sa, 26))}</td><td>${sgn(tr(sa, 52))}</td><td>${sgn(tr(sa, 156))}</td></tr></table></div>
        <div class="tblwrap" style="margin-top:8px"><table><tr><th>Horizon</th><th>P(beat SPY)</th><th>Excess vs SPY p10 / p50 / p90</th><th>SPY (benchmark)</th><th>Backtest verdict</th></tr>
        ${HZ.map((h) => { const s = r.s[h], m = D.models[r.kind + "_" + h]; return `<tr><td>${h}m</td><td class="prob" style="background:${probColor(s.hit, m.metrics.base_rate)}">${pct(s.hit)}</td><td>${sgn(s.p10)} / <b>${sgn(s.p50)}</b> / ${sgn(s.p90)}</td><td class="muted">0% excess · base rate ${pct(m.metrics.base_rate)}</td><td class="${verdictClass(m.verdict)}">${m.verdict}</td></tr>`; }).join("")}
        </table></div></div>`;
      $("pinBtn").onclick = () => {
        if (!state.research.some((x) => x.t === t)) { state.research.push({ t, name, s: r.s, kind: r.kind, px: r.px, at: r.at.toISOString() }); saveResearch(); }
        $("pinBtn").textContent = "Pinned ✓"; if (state.view === "RES") renderTable();
      };
    } catch (e) {
      out.innerHTML = `<div class="card err">Could not fetch ${esc(t)} (${esc(e.message)}). Yahoo or the CORS proxy may be blocking requests; try again shortly.</div>`;
    }
  }

  // ---------- refresh ----------
  async function refresh() {
    if (state.busy) return; state.busy = true; $("refresh").disabled = true;
    const tickers = [...new Set(rowsForView().map((r) => r.t))];
    let ok = 0, done = 0; const failed = [];
    $("refStatus").textContent = `Refreshing ${tickers.length} names from Yahoo…`;
    try { state.spyW = null; await getSpy(); } catch (e) { $("refStatus").textContent = "Could not reach Yahoo (direct or AllOrigins) for SPY. Showing shipped scores."; state.busy = false; $("refresh").disabled = false; return; }
    const queue = tickers.slice();
    async function worker() {
      while (queue.length) {
        const t = queue.shift();
        try { const r = await liveScore(t); state.live[t] = { s: r.s, kind: r.kind, px: r.px, at: r.at };
          const rr = state.research.find((x) => x.t === t); if (rr) Object.assign(rr, { s: r.s, kind: r.kind, px: r.px, at: r.at.toISOString() });
          ok++; } catch (_) { failed.push(t); }
        done++; if (done % 10 === 0 || done === tickers.length) $("refStatus").textContent = `Refreshed ${done}/${tickers.length}…`;
      }
    }
    await Promise.all(Array.from({ length: 6 }, worker));
    saveResearch();
    state.refreshedAt = new Date(); state.busy = false; $("refresh").disabled = false;
    $("refStatus").textContent = `Live: ${ok}/${tickers.length} updated ${laTime(state.refreshedAt)}` + (failed.length ? ` · failed: ${failed.slice(0, 12).join(", ")}${failed.length > 12 ? "…" : ""} (shipped scores kept)` : "");
    renderStatus(); renderTable();
  }

  // ---------- wire up ----------
  document.addEventListener("click", (e) => {
    const v = e.target.closest("[data-v]"); if (v) { state.view = v.dataset.v; renderTabs(); renderTable(); return; }
    const h = e.target.closest("[data-h]"); if (h) { state.h = +h.dataset.h; renderTabs(); renderBanner(); renderTable(); return; }
    const k = e.target.closest("th[data-k]"); if (k) { if (state.sortKey === k.dataset.k) state.sortDir *= -1; else { state.sortKey = k.dataset.k; state.sortDir = k.dataset.k === "t" ? 1 : -1; } renderTable(); return; }
    const u = e.target.closest("[data-unpin]"); if (u) { state.research = state.research.filter((x) => x.t !== u.dataset.unpin); saveResearch(); renderTable(); }
  });
  $("refresh").onclick = refresh;
  $("go").onclick = doSearch;
  $("q").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
  $("flt").addEventListener("input", (e) => { state.filter = e.target.value; renderTable(); });
  renderTabs(); renderBanner(); renderStatus(); renderTable(); renderBacktest();
  $("gaps").textContent = Object.keys(D.tick).filter((t) => D.tick[t].kind === "price").sort().join(", ") || "none";
  window.G1 = { qpct, scoreAll, priceFeatures, fundFeatures, D, state }; // for local verification
})();
