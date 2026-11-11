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
  // G1 v2 composite: equal-weight pillars of within-sector percentile ranks (missing -> neutral)
  function compScore(m, f) {
    const qs = D.meta.sq[f._sector] || {};
    const pv = Object.values(m.pillars).map((comps) => comps.reduce((acc, [name, sign]) => {
      const q = qs[name]; const v = q ? qpct(f[name], q) : null; return acc + sign * (v == null ? 0 : v - 0.5);
    }, 0) / comps.length);
    return pv.reduce((a, b) => a + b, 0) / pv.length;
  }
  function scoreOne(key, f) {
    const m = D.models[key]; let p;
    if (m.type === "comp") p = compScore(m, f);
    else {
      let z = m.intercept;
      m.features.forEach((name, i) => { const v = qpct(f[name], m.q[name]); z += m.coef[i] * (v == null ? 0 : v - 0.5); });
      p = 1 / (1 + Math.exp(-z));
    }
    const s = qpct(p, m.pq); const mids = m.cal.map((c) => c.mid);
    const o = { p_raw: p, pct: s };
    ["hit", "p10", "p50", "p90"].forEach((k) => (o[k] = interp(s, mids, m.cal.map((c) => c[k]))));
    return o;
  }
  // ---------- style boxes (display only; rule-based proxies, see methodology) ----------
  const MAGIC_NAME = D.meta.magic.name;  // rename here or in pipeline/build_site.py
  function styleOf(t, f) {
    const T = D.tick[t]; if (!T || !T.sty) return null;
    const st = T.sty.bm_st, tsy = D.meta.tsy, fc = f ? f.fcfy : null;
    const fv = fc == null || !isFinite(fc) ? 1 : fc >= tsy ? 2 : fc >= 0.6 * tsy ? 1 : 0;
    const bm = Object.values(st).reduce((a, b) => a + b, 0) + fv;
    const mp = {};
    Object.entries(D.meta.magic.pillars).forEach(([k, comps]) => {
      mp[k] = comps.reduce((acc, [name, sign]) => { const v = qpct(f ? f[name] : null, D.meta.mq[name]); return acc + (v == null ? 0.5 : sign > 0 ? v : 1 - v); }, 0) / comps.length;
    });
    const m15 = 10 * Object.values(mp).reduce((a, b) => a + b, 0) / Object.keys(mp).length;
    return { bm, bm_st: Object.assign({}, st, { fcf_vs_treasury: fv }), m15, m15p: mp, fcfy: fc };
  }
  function agree(s, ai) {
    if (ai == null || s == null || s.pct == null) return null;
    const g = s.pct >= 0.8 ? 1 : s.pct <= 0.2 ? -1 : 0, d = ai >= 7 ? 1 : ai <= 4 ? -1 : 0;
    if (!g || !d) return "neutral"; return g === d ? "agree" : "disagree";
  }
  function agreePill(a, h) {
    if (!a) return `<span class="ag ag-na" title="No Danelfin AI score for this name">—</span>`;
    const lbl = { agree: "Agree", disagree: "Disagree", neutral: "Neutral" }[a];
    return `<span class="ag ag-${a}" title="${h}m: G1 score in top/bottom 20% vs Danelfin AI ≥7 bullish / ≤4 bearish">${lbl}</span>`;
  }
  const BM_LBL = { durable_roe: "Durable ROE (5y median ≥15% & min ≥10%)", low_leverage: "Low leverage (debt/assets ≤30%)", stable_margins: "Stable operating margins",
    consistent_profits: "Profitable every year (5y min ROA > 0)", gross_margin: "Gross margin moat (≥40% = 2, ≥25% = 1)", share_count: "No net dilution over 3y",
    fcf_vs_treasury: "Owner-earnings (FCF) yield vs 10y Treasury" };
  const BM_MAX = { durable_roe: 2, low_leverage: 1, stable_margins: 1, consistent_profits: 1, gross_margin: 2, share_count: 1, fcf_vs_treasury: 2 };
  function bmBox(y) {
    if (!y) return `<span class="muted" title="Needs SEC fundamentals">—</span>`;
    const tip = Object.entries(y.bm_st).map(([k, v]) => `${BM_LBL[k]}: ${v}/${BM_MAX[k]}`).join("\n") + `\n(10y Treasury ${(D.meta.tsy * 100).toFixed(2)}%; missing data = half points)\nRule-based proxy, not Buffett's or Munger's view.`;
    return `<span class="sty" style="background:${scoreColor(y.bm)}" title="${esc(tip)}">${y.bm.toFixed(1)}</span>`;
  }
  function m15Box(y) {
    if (!y) return `<span class="muted" title="Needs SEC fundamentals">—</span>`;
    const tip = Object.entries(y.m15p).map(([k, v]) => `${D.meta.magic.labels[k]}: ${(v * 10).toFixed(1)}/10`).join("\n") + `\nRule-based proxy of published principles, not these investors' views.`;
    return `<span class="sty" style="background:${scoreColor(y.m15)}" title="${esc(tip)}">${y.m15.toFixed(1)}</span>`;
  }
  function scoreColor(x) { const g = Math.max(-1, Math.min(1, (x - 5) / 3)); return g >= 0 ? `rgba(34,197,94,${0.12 + 0.45 * g})` : `rgba(239,68,68,${0.12 - 0.45 * g})`; }
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
  function chartUrl(sym, host) { return `https://${host}.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=5y&interval=1wk&includeAdjustedClose=true`; }
  async function fetchChart(sym) {
    const s = sym.replace(".", "-");
    const q1 = chartUrl(s, "query1"), q2 = chartUrl(s, "query2");
    // Browsers on GitHub Pages are usually CORS-blocked from Yahoo; fall back to the AllOrigins proxy (raw, then JSON wrapper).
    const AO = "https://api.allorigins.win";
    const candidates = [q1, `${AO}/raw?url=${encodeURIComponent(q2)}`, `${AO}/get?url=${encodeURIComponent(q2)}`,
      `${AO}/raw?url=${encodeURIComponent(q1)}`, `${AO}/get?url=${encodeURIComponent(q1)}`];
    let lastErr;
    for (const url of candidates) {
      try {
        const ctl = new AbortController(); const timer = setTimeout(() => ctl.abort(), url === q1 ? 8000 : 25000);
        const res = await fetch(url, { cache: "no-store", signal: ctl.signal }); clearTimeout(timer);
        if (!res.ok) throw new Error(String(res.status));
        let data = await res.json();
        if (url.includes("/get?url=")) data = JSON.parse(data.contents);  // AllOrigins JSON wrapper
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
    if (!state.spyW) {
      let s = null;
      for (let k = 0; k < 2 && !s; k++) { try { s = await fetchChart("SPY"); } catch (_) {} }
      if (!s) { s = { keys: D.meta.spy_w.keys, a: D.meta.spy_w.a, meta: {}, shipped: true }; }  // fallback: SPY weekly bundled at build
      state.spyW = s; state.spyMap = new Map(s.keys.map((k, i) => [k, s.a[i]]));
    }
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
    return { s: scoreAll(kind, f), kind, px, chart: c, at: new Date(), sty: styleOf(t, f) };
  }

  // ---------- helpers ----------
  const pct = (x, d = 0) => (x == null || !isFinite(x) ? "–" : (x * 100).toFixed(d) + "%");
  const sgn = (x) => (x == null || !isFinite(x) ? "–" : (x >= 0 ? "+" : "") + (x * 100).toFixed(0) + "%");
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const laTime = (d) => d.toLocaleString("en-US", { timeZone: "America/Los_Angeles", month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }) + " PT";
  function verdictClass(v) { return v.startsWith("some") ? "v-some" : v.startsWith("weak") ? "v-weak" : v.startsWith("negative") ? "v-neg" : "v-none"; }
  function probColor(x, base) { const d = x - base; const g = Math.max(-1, Math.min(1, d / 0.06)); return g >= 0 ? `rgba(34,197,94,${0.12 + 0.5 * g})` : `rgba(239,68,68,${0.12 - 0.5 * g})`; }
  function scoresFor(t) { const L = state.live[t]; if (L) return { s: L.s, kind: L.kind, px: L.px, sty: L.sty, live: true }; const T = D.tick[t]; return T ? { s: T.s, kind: T.kind, px: T.px, sty: T.sty, live: false } : null; }
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
  function aiLookup() { const aiOf = {}; Object.values(D.books).forEach((rows) => rows.forEach((r) => { if (r.ai != null && aiOf[r.t] == null) aiOf[r.t] = r.ai; })); return aiOf; }
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
    $("hzNote").innerHTML = `<b>${state.h}-month view.</b> Backtest verdict: v2 composite <span class="${verdictClass(mf.verdict)}">${mf.verdict}</span> (rank IC ${mf.metrics.rank_ic.toFixed(3)}, ~${mf.metrics.independent_periods} independent periods); price-only <span class="${verdictClass(mp.verdict)}">${mp.verdict}</span>. Historical share of top-1000 names beating SPY over ${state.h}m in the test window: ${pct(mf.metrics.base_rate)}. "P(beat SPY)" is the out-of-sample beat rate of stocks that sat in the same score bucket, so with no edge it stays close to that base rate.`;
  }
  function renderTable() {
    const showNew = state.view === "NEW";
    let rows = rowsForView().map((r) => {
      const sc = r.research ? (state.live[r.t] ? scoresFor(r.t) : (r.research.s ? { s: r.research.s, kind: r.research.kind, px: r.research.px, sty: r.research.sty || D.tick[r.t]?.sty || null, live: false } : null)) : scoresFor(r.t);
      return Object.assign(r, { sc });
    });
    const f = state.filter.trim().toUpperCase();
    if (f) rows = rows.filter((r) => r.t.includes(f) || String(r.name || "").toUpperCase().includes(f));
    const val = (r) => {
      const s = r.sc?.s?.[state.h];
      switch (state.sortKey) {
        case "t": return r.t; case "ai": return r.ai ?? -1; case "pct": return s?.pct ?? -1; case "p50": return s?.p50 ?? -9;
        case "bm": return r.sc?.sty?.bm ?? -1; case "m15": return r.sc?.sty?.m15 ?? -1;
        case "ag": return { agree: 2, neutral: 1, disagree: 0 }[agree(s, r.ai)] ?? -1;
        default: return s?.hit ?? -1;
      }
    };
    rows.sort((a, b) => { const x = val(a), y = val(b); return (x < y ? -1 : x > y ? 1 : 0) * state.sortDir; });
    const base = D.models["full_" + state.h].metrics.base_rate;
    const th = (k, l, cls = "") => `<th data-k="${k}" class="${cls}">${l}${state.sortKey === k ? (state.sortDir < 0 ? " ▾" : " ▴") : ""}</th>`;
    let html = `<table><thead><tr>${th("t", "Ticker")}${th("ai", "Danelfin AI")}${th("prob", `G1 P(beat SPY) ${state.h}m`)}${th("ag", `vs Danelfin ${state.h}m`)}${th("p50", "Excess vs SPY p10 / p50 / p90")}${th("pct", "Score pctl", "hide-sm")}<th class="hide-sm">All horizons (6→60m) · Danelfin agreement</th>${th("bm", "B&amp;M")}${th("m15", esc(MAGIC_NAME))}<th>Model</th>${showNew ? "<th>Shares</th><th>Value</th>" : ""}${state.view === "RES" ? "<th></th>" : ""}</tr></thead><tbody>`;
    for (const r of rows) {
      const s = r.sc?.s?.[state.h];
      const strip = r.sc ? HZ.map((h) => { const x = r.sc.s[h].hit, a = agree(r.sc.s[h], r.ai); return `<span class="hzc"><span title="${h}m" style="background:${probColor(x, D.models["full_" + h].metrics.base_rate)}">${(x * 100).toFixed(0)}</span><i class="dot ag-${a || "na"}" title="${h}m vs Danelfin: ${a || "no Danelfin score"}"></i></span>`; }).join("") : "";
      const kind = r.sc ? (r.sc.kind === "price" ? `<span class="pill po" title="No usable SEC fundamentals bundled; scored with the price-only model">price-only</span>` : `<span class="pill">full</span>`) : `<span class="pill">not scored</span>`;
      html += `<tr><td><b>${esc(r.t)}</b>${r.sc?.live ? ' <span class="muted small">live</span>' : ""}<span class="nm">${esc(r.name || "")}</span></td>
        <td>${r.ai != null ? r.ai : '<span class="muted">–</span>'}</td>
        <td class="prob" style="background:${s ? probColor(s.hit, base) : "transparent"}">${s ? pct(s.hit) : "–"}</td>
        <td>${s ? agreePill(agree(s, r.ai), state.h) : "–"}</td>
        <td>${s ? `${sgn(s.p10)} / <b>${sgn(s.p50)}</b> / ${sgn(s.p90)}` : "–"}</td>
        <td class="hide-sm">${s ? Math.round(s.pct * 100) : "–"}</td>
        <td class="hide-sm"><span class="strip">${strip}</span></td><td>${bmBox(r.sc?.sty)}</td><td>${m15Box(r.sc?.sty)}</td><td>${kind}</td>
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
    $("bt").innerHTML = `<h3 class="small">G1 v2 composite (quality, value, low dilution, balance sheet; wide top-1000 universe, out-of-sample walk-forward)</h3><div class="tblwrap"><table>${head}${rowsOf("full")}</table></div>
      <h3 class="small">Composite vs. alternatives on historical S&amp;P 500 members (rank IC, overlap-adjusted t in brackets)</h3><div class="tblwrap"><table><tr><th>Horizon</th><th>G1 v2 composite (live)</th><th>v2 learned ridge (not used)</th><th>G1 v1 logistic (retired)</th></tr>${HZ.map((h) => { const c = D.models["full_" + h].cmp; const f = (x, t) => `${x.toFixed(3)} <span class="muted">(t≈${t.toFixed(1)})</span>`; return `<tr><td>${h}m</td><td>${f(c.sp_A.rank_ic, c.sp_A.ic_t_ovl)}</td><td>${f(c.sp_B.rank_ic, c.sp_B.ic_t_ovl)}</td><td>${f(c.v1.rank_ic, c.v1.t)}</td></tr>`; }).join("")}</table></div>
      <h3 class="small">Style boxes pressure test (fixed rules, month-ends 2014+; rank IC with overlap-adjusted t; partial IC = what is left after removing the G1 composite)</h3><div class="tblwrap"><table><tr><th>Horizon</th><th>B&amp;M wide</th><th>B&amp;M S&amp;P</th><th>B&amp;M partial IC vs G1</th><th>${esc(MAGIC_NAME)} wide</th><th>${esc(MAGIC_NAME)} S&amp;P</th><th>${esc(MAGIC_NAME)} partial IC vs G1</th></tr>${HZ.map((h) => { const b = D.meta.style_bt.BM[h], m = D.meta.style_bt.M15[h]; const f = (x, t) => `${x.toFixed(3)} <span class="muted">(t≈${t.toFixed(1)})</span>`; return `<tr><td>${h}m</td><td>${f(b.wide.ic, b.wide.t)}</td><td>${f(b.sp.ic, b.sp.t)}</td><td>${f(b.partial_ic, b.partial_t)}</td><td>${f(m.wide.ic, m.wide.t)}</td><td>${f(m.sp.ic, m.sp.t)}</td><td>${f(m.partial_ic, m.partial_t)}</td></tr>`; }).join("")}</table></div>
      <p class="small">Pre-registered verdicts: <b>Buffett &amp; Munger: ${D.meta.style_verdict.BM}</b> (significant on the wide universe at every horizon and adds information beyond G1). <b>${esc(MAGIC_NAME)}: ${D.meta.style_verdict.M15}</b>. It is significant at 24–60m on the wide universe but adds little beyond G1, and dropping the deep-value or durable-growth pillar improves it at every horizon. The quality-compounder pillar carries most of the signal. The trend and deep-value pillars pull in opposite directions (correlation −0.23). Both boxes are display-only and never change G1's P(beat SPY).</p>
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
      state.live[t] = { s: r.s, kind: r.kind, px: r.px, at: r.at, sty: r.sty };
      const spy = state.spyW, a = r.chart.a, sa = spy.a;
      const tr = (arr, k) => (arr.length > k ? arr[arr.length - 1] / arr[arr.length - 1 - k] - 1 : null);
      const name = D.tick[t]?.name || r.chart.meta.longName || r.chart.meta.shortName || "";
      const poNote = r.kind === "price" ? `<div class="disc"><b>Price-only score.</b> No SEC fundamentals are bundled for ${esc(t)}, so this uses the price-only model (momentum, volatility, drawdown, beta). Ask in chat for a full fundamentals score.</div>` : "";
      out.innerHTML = `<div class="card"><div class="row" style="justify-content:space-between"><div><b style="font-size:16px">${esc(t)}</b> <span class="muted">${esc(name)}</span> ${r.kind === "price" ? '<span class="pill po">price-only score</span>' : '<span class="pill">full model</span>'}</div>
        <button id="pinBtn">${state.research.some((x) => x.t === t) ? "Pinned ✓" : "Pin to Research"}</button></div>
        <div class="small" style="margin:4px 0">Danelfin AI: <b>${aiLookup()[t] ?? "–"}</b> · Buffett &amp; Munger: ${bmBox(r.sty)} · ${esc(MAGIC_NAME)}: ${m15Box(r.sty)}</div><div class="small muted">Price ${r.px?.toFixed(2)} ${esc(r.chart.meta.currency || "")} · fetched ${laTime(r.at)}</div>${poNote}
        <div class="tblwrap" style="margin-top:8px"><table><tr><th>Trailing return</th><th>6m</th><th>12m</th><th>3y</th></tr>
        <tr><td>${esc(t)}</td><td>${sgn(tr(a, 26))}</td><td>${sgn(tr(a, 52))}</td><td>${sgn(tr(a, 156))}</td></tr>
        <tr><td>SPY</td><td>${sgn(tr(sa, 26))}</td><td>${sgn(tr(sa, 52))}</td><td>${sgn(tr(sa, 156))}</td></tr></table></div>
        <div class="tblwrap" style="margin-top:8px"><table><tr><th>Horizon</th><th>P(beat SPY)</th><th>vs Danelfin</th><th>Excess vs SPY p10 / p50 / p90</th><th>SPY (benchmark)</th><th>Backtest verdict</th></tr>
        ${HZ.map((h) => { const s = r.s[h], m = D.models[r.kind + "_" + h]; return `<tr><td>${h}m</td><td class="prob" style="background:${probColor(s.hit, m.metrics.base_rate)}">${pct(s.hit)}</td><td>${agreePill(agree(s, aiLookup()[t]), h)}</td><td>${sgn(s.p10)} / <b>${sgn(s.p50)}</b> / ${sgn(s.p90)}</td><td class="muted">0% excess · base rate ${pct(m.metrics.base_rate)}</td><td class="${verdictClass(m.verdict)}">${m.verdict}</td></tr>`; }).join("")}
        </table></div></div>`;
      $("pinBtn").onclick = () => {
        if (!state.research.some((x) => x.t === t)) { state.research.push({ t, name, s: r.s, kind: r.kind, px: r.px, sty: r.sty, at: r.at.toISOString() }); saveResearch(); }
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
    $("refStatus").textContent = `Refreshing ${tickers.length} names from Yahoo…` + (tickers.length > 60 ? " (large list through a free proxy: this can take 10+ minutes; keep the tab open)" : "");
    state.spyW = null; await getSpy();
    const queue = tickers.slice();
    async function worker() {
      while (queue.length) {
        const t = queue.shift();
        try { let r = null; try { r = await liveScore(t); } catch (_) { r = await liveScore(t); } state.live[t] = { s: r.s, kind: r.kind, px: r.px, at: r.at, sty: r.sty };
          const rr = state.research.find((x) => x.t === t); if (rr) Object.assign(rr, { s: r.s, kind: r.kind, px: r.px, sty: r.sty, at: r.at.toISOString() });
          ok++; } catch (_) { failed.push(t); }
        done++; if (done % 10 === 0 || done === tickers.length) $("refStatus").textContent = `Refreshed ${done}/${tickers.length}…`;
      }
    }
    await Promise.all(Array.from({ length: 6 }, worker));
    saveResearch();
    state.refreshedAt = new Date(); state.busy = false; $("refresh").disabled = false;
    $("refStatus").textContent = `Live: ${ok}/${tickers.length} updated ${laTime(state.refreshedAt)}` + (state.spyW.shipped ? " (SPY from bundled history; beta slightly stale)" : "") + (failed.length ? ` · failed: ${failed.slice(0, 12).join(", ")}${failed.length > 12 ? "…" : ""} (shipped scores kept)` : "");
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
  window.G1 = { qpct, styleOf, scoreAll, priceFeatures, fundFeatures, D, state }; // for local verification
})();
