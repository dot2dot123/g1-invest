(function () {
  "use strict";
  // G1 v4 dashboard. All formulas mirror pipeline/build_site.py live_scores() and docs/PREREGISTRATION_V4.md.
  const D = JSON.parse(document.getElementById("g1data").textContent);
  const M = D.meta, HZ = M.horizons, P = M.page;
  const $ = (id) => document.getElementById(id);
  const LS_KEY = "g1.research.v1"; // watchlist (kept from v1-v3; entries migrate automatically)
  const COLI = Object.fromEntries(M.cols.map((c, i) => [c, i]));
  const state = { view: null, sortKey: "score", sortDir: -1, filter: "", live: {}, spyW: null, refreshedAt: null, busy: false, research: loadResearch(), open: new Set() };

  // ---------- math ----------
  function lowerBound(a, x) { let lo = 0, hi = a.length; while (lo < hi) { const m = (lo + hi) >> 1; if (a[m] < x) lo = m + 1; else hi = m; } return lo; }
  function upperBound(a, x) { let lo = 0, hi = a.length; while (lo < hi) { const m = (lo + hi) >> 1; if (a[m] <= x) lo = m + 1; else hi = m; } return lo; }
  function qpct(x, q) {
    if (x == null || !isFinite(x) || !q) return null;
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
  const mean = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length;

  // ---------- regime / market weather ----------
  function classify(px, sma, hy) {
    const hyOk = hy != null && isFinite(hy);
    if (px < sma || (hyOk && hy > 5.5)) return "off";
    if (px > sma && (!hyOk || hy < 4.5)) return "on";
    return "neutral";
  }
  function weather() {
    const W = M.weather; let spy = W.spy, sma = W.sma40, hi = W.spy_hi52, live = false;
    if (state.spyW && !state.spyW.shipped && state.spyW.a.length >= 40) { const a = state.spyW.a; spy = a[a.length - 1]; sma = mean(a.slice(-40)); hi = Math.max(...a.slice(-52)); live = true; }
    const regime = classify(spy, sma, W.hy);
    const bear = spy < sma && W.breadth < 0.35;
    const capit = spy / hi - 1 <= -0.15 && W.breadth_weekly_now > 0.40 && W.breadth_min13 < 0.35 && W.hy != null && W.hy <= W.hy_peak13 - 0.5;
    let reserve = 0, label = { on: "Sunny", neutral: "Cloudy", off: "Storm Warning" }[regime], icon = { on: "☀️", neutral: "⛅", off: "⛈️" }[regime], mode = regime;
    if (capit) { label = "Clearing after the storm: CAPITULATION BUY"; icon = "🌤️"; mode = "capit"; }
    else if (bear) { reserve = 0.30 + 0.20 * Math.min(1, Math.max(0, (0.35 - W.breadth) / 0.15)); label = "Storm: preserve cash"; icon = "🌪️"; mode = "bear"; }
    return { regime, bear: bear && !capit, capit, reserve, label, icon, mode, spy, sma, hi, live };
  }

  // ---------- features ----------
  function rowOf(t) { const r = D.rows[t]; if (!r) return null; const f = {}; M.cols.forEach((c, i) => (f[c] = r[i])); return f; }
  function tmeta(t) { const m = D.tmeta[t]; return m ? { sector: M.sectors[m[0]], fund: m[1] === 1, fin: m[2] === 1, sp: m[3] === 1, form4: m[4], univ: m[5] === 1, name: m[6] } : null; }
  function reprice(f, px) {   // price-dependent fundamentals at a new price (same formulas as pipeline/features.py)
    const o = Object.assign({}, f);
    if (f.shares_adj == null || !(px > 0)) return o;
    const mcap = px * f.shares_adj, debt = f.debt || 0, cash = f.cash || 0, ev = mcap + debt - cash;
    const fcf = f.cfo != null ? f.cfo - (f.capex || 0) : null;
    o.mcap = mcap; o.px = px;
    o.ey = f.ebit != null && ev > 0 ? f.ebit / ev : null;
    o.fcfy = fcf != null ? fcf / mcap : null;
    o.bm = f.equity != null ? f.equity / mcap : null;
    o.ey_vs_hist = o.ey != null && f.ey_hist_med != null ? o.ey - f.ey_hist_med : null;
    const adj = Math.max(mcap + debt - cash - (f.non_op || 0), 0.25 * mcap);
    o.fcfy_adj_ev = fcf != null ? fcf / adj : null;
    o.ey_adj_ev = f.ebit != null ? f.ebit / adj : null;
    return o;
  }

  // ---------- scores (mirror of build_site.live_scores) ----------
  function rawScores(f, sector, fin, form4, regime) {
    const sq = M.sq[sector] || {}, sqA = M.sqA[sector] || {}, uq = M.uq, fq = M.fq;
    const sg = (v, s) => (v == null ? 0.5 : s > 0 ? v : 1 - v);
    const g = Object.assign({}, f);
    const eyh = g.ey_vs_hist, omt = g.om_trend;
    g.gated_ey_vs_hist = eyh == null ? null : eyh * (omt != null && omt >= 0 ? 1 : 0);
    if (fin) M.fin_mask.forEach((k) => (g[k] = null));
    const rs = (n) => (sq[n] ? qpct(g[n], sq[n]) : null), ru = (n) => (uq[n] ? qpct(g[n], uq[n]) : null), rf = (n) => (fq[n] ? qpct(g[n], fq[n]) : null);
    const o = {};
    o.S1 = fin ? mean(M.sleeves_fin.S1.map(([k, s]) => sg(rf(k), s))) : mean(M.sleeves.S1.map(([k, s]) => sg(rs(k), s)));
    o.S2 = mean(M.sleeves.S2.map(([k, s]) => sg(rs(k), s)));
    o.S3 = mean(M.sleeves.S3.map(([k, s]) => sg(rs(k), s)));
    o.S4 = mean(M.sleeves.S4.map(([k, s]) => 0.5 * sg(ru(k), s) + 0.5 * sg(rs(k), s))) * (M.smult[sector] ?? 1.0);
    const f4 = 0.05 * (form4 || 0);
    o.S5 = (fin ? mean(M.sleeves_fin.S5.map(([k, s]) => sg(rf(k), s))) : mean(M.sleeves.S5.map(([k, s]) => sg(ru(k), s)))) + f4;
    o.U = 100 * (0.35 * o.S3 + 0.35 * o.S4 + 0.30 * (o.S1 + o.S2) / 2);
    o.D = 100 * (0.50 * o.S5 + 0.30 * o.S1 + 0.20 * o.S2);
    const w = M.regime_w[regime];
    o.S_quant = w * o.U + (1 - w) * o.D;
    const sp = mean(M.sprice.map(([k, s]) => sg(ru(k), s))) - 0.15 * (g.sma40_below || 0);
    o.S_price = 100 * Math.min(1, Math.max(0, sp));
    const pv = Object.values(M.pillars).map((comps) => comps.reduce((acc, [n, s]) => acc + s * (sqA[n] && f[n] != null ? qpct(f[n], sqA[n]) - 0.5 : 0), 0) / comps.length);
    o.A = mean(pv);
    return o;
  }
  function calib(score, model, h) {
    const s = qpct(score, M.pq[model]), cal = M.cal[h][model], mids = cal.map((c) => c.mid), o = { pct: s };
    ["hit", "p10", "p50", "p90"].forEach((k) => (o[k] = interp(s, mids, cal.map((c) => c[k]))));
    return o;
  }
  function scoreTicker(t, f, m) {
    // f: features (shipped or live). m: tmeta-like {sector, fund, fin, form4}
    const wx = weather();
    const r = rawScores(f, m.sector, m.fin, m.form4, wx.regime);
    const model = m.fund ? M.live : "S_price";
    const raw = r[model], bands = {};
    HZ.forEach((h) => (bands[h] = calib(raw, model, h)));
    const pct = bands[12].pct;
    const base = model === "A" ? 100 * pct : raw;
    const dz = D.dossiers[t];
    const v4 = dz ? Math.min(100, Math.max(0, base + 1.5 * dz.f_strat)) : null;
    return Object.assign(r, { model, bands, pct, g1: base, v4, kind: m.fund ? "full" : "price" });
  }

  // ---------- execution rules (model estimates, not advice) ----------
  function verdict(sc, f) {
    const wx = weather(), pct = sc.pct;
    const up = M.passed ? sc.U >= 75 && pct >= 0.8 : pct >= 0.8;
    let v, cls, note = "";
    if (pct <= 0.2 || (f.sma40_below === 1 && f.dd_52w != null && f.dd_52w < -0.30)) { v = "SELL / BROKEN"; cls = "v-sell"; }
    else if (f.trend40 != null && f.trend40 >= 0.5 && f.rev_1m != null && f.rev_1m >= 0.15) { v = "CLIMAX TRIM"; cls = "v-trim"; }
    else if (up && f.rev_1m != null && f.rev_1m > 0.15) { v = "ACCUMULATE (Staggered)"; cls = "v-acc"; note = "Buy 50% of target weight now, add the rest on a pullback to the 40-week SMA."; }
    else if (up) { v = "STRONG BUY"; cls = "v-buy"; }
    else { v = "HOLD"; cls = "v-hold"; }
    if (wx.bear && (cls === "v-acc" || cls === "v-buy")) { v += " (buys paused)"; note = "Bear Preservation: new buys paused; keep the T-bill reserve."; }
    return { v, cls, note };
  }
  function kelly(sc, f, t) {
    const b12 = sc.bands[12], p = b12.hit, loss = Math.abs(b12.p10);
    let k;
    if (!(b12.p10 < 0)) k = p; else { const b = b12.p90 / loss; k = b > 0 ? Math.max(0, (p * b - (1 - p)) / b) : 0; }
    k = k / 2;
    const sd = f.sigma_down; if (sd != null && sd > 0) k *= Math.min(1, 0.25 / sd);
    k = Math.min(0.10, k);
    const e = D.earn[t]; let soon = false;
    if (e) { const days = (new Date(e + "T00:00:00") - new Date(new Date().toDateString())) / 86400000; soon = days >= 0 && days <= 7; if (soon) k /= 2; }
    return { k, soon, earn: e };
  }
  function stops(f, entry) {
    const P = f.px; if (!(P > 0)) return null;
    const s1 = Math.max(f.sma40c ?? -Infinity, f.cvar_5 != null ? P * (1 + f.cvar_5) : -Infinity);
    let stage = 1, stop = isFinite(s1) ? s1 : null;
    const gain = entry > 0 ? P / entry - 1 : null;
    if (gain != null && gain >= 0.2) { stage = 2; stop = Math.max(stop ?? -Infinity, entry); }
    if (gain != null && gain >= 0.4 && f.ema10c != null) { stage = 3; stop = Math.max(stop, f.ema10c); }
    return { stage, stop, s1: isFinite(s1) ? s1 : null, gain, entry, broken: stop != null && stop >= P };
  }
  function targets(sc, px) { const b = sc.bands[12]; return px > 0 ? { bear: px * (1 + b.p10), base: px * (1 + b.p50), bull: px * (1 + b.p90) } : null; }

  // ---------- style boxes ----------
  const MAGIC_NAME = M.magic.name;
  function bmStatic(f) {
    const c = {}, med = f.roe_med5, mn = f.roe_min5;
    c.durable_roe = med == null ? 1 : med >= 0.15 && mn >= 0.10 ? 2 : med >= 0.12 ? 1 : 0;
    c.low_leverage = f.lev == null ? 0.5 : f.lev <= 0.30 ? 1 : 0;
    c.stable_margins = f.om_stab == null ? 0.5 : f.om_stab >= -0.03 ? 1 : 0;
    c.consistent_profits = f.roa_min5 == null ? 0.5 : f.roa_min5 > 0 ? 1 : 0;
    c.gross_margin = f.gm == null ? 1 : f.gm >= 0.40 ? 2 : f.gm >= 0.25 ? 1 : 0;
    c.share_count = f.dil_3y == null ? 0.5 : f.dil_3y <= 0 ? 1 : 0;
    const tsy = M.tsy, fc = f.fcfy; c.fcf_vs_treasury = fc == null ? 1 : fc >= tsy ? 2 : fc >= 0.6 * tsy ? 1 : 0;
    return c;
  }
  function styleOf(f, fund) {
    if (!fund) return null;
    const bm_st = bmStatic(f), bm = Object.values(bm_st).reduce((a, b) => a + b, 0);
    const mp = {};
    Object.entries(M.magic.pillars).forEach(([k, comps]) => { mp[k] = mean(comps.map(([n, s]) => { const v = qpct(f[n], M.mq[n]); return v == null ? 0.5 : s > 0 ? v : 1 - v; })); });
    return { bm, bm_st, m15: 10 * mean(Object.values(mp)), m15p: mp };
  }
  const BM_LBL = { durable_roe: "Durable ROE (5y median ≥15% & min ≥10%)", low_leverage: "Low leverage (debt/assets ≤30%)", stable_margins: "Stable operating margins",
    consistent_profits: "Profitable every year (5y min ROA > 0)", gross_margin: "Gross margin moat (≥40% = 2, ≥25% = 1)", share_count: "No net dilution over 3y", fcf_vs_treasury: "Owner-earnings (FCF) yield vs 10y Treasury" };
  const BM_MAX = { durable_roe: 2, low_leverage: 1, stable_margins: 1, consistent_profits: 1, gross_margin: 2, share_count: 1, fcf_vs_treasury: 2 };

  // ---------- price features from weekly bars (mirror of pipeline/features.py) ----------
  function priceFeatures(a, spyMap, keys) {
    const n = a.length, i = n - 1, f = {};
    const at = (k) => (i - k >= 0 ? a[i - k] : null);
    const ratio = (x, y) => (x != null && y != null && y > 0 ? x / y - 1 : null);
    f.mom_12_1 = ratio(at(4), at(52)); f.mom_6_1 = ratio(at(4), at(26)); f.rev_1m = ratio(a[i], at(4));
    const win = (len) => a.slice(Math.max(0, n - len));
    let w = win(52); f.dd_52w = w.length >= 40 ? a[i] / Math.max(...w) - 1 : null;
    w = win(40); const sma = w.length >= 30 ? mean(w) : null; f.trend40 = sma ? a[i] / sma - 1 : null; f.sma40_below = sma ? (a[i] < sma ? 1 : 0) : null;
    const r = []; for (let k = 1; k < n; k++) r.push(Math.log(a[k] / a[k - 1]));
    const sd = (xs) => { const m = mean(xs); return Math.sqrt(xs.reduce((s, x) => s + (x - m) ** 2, 0) / (xs.length - 1)); };
    const r52 = r.slice(-52); f.vol_1y = r52.length >= 40 ? sd(r52) * Math.sqrt(52) : null;
    const pairs = [];
    for (let k = Math.max(1, n - 104); k < n; k++) { const s1 = spyMap.get(keys[k]), s0 = spyMap.get(keys[k - 1]); if (s1 != null && s0 != null) pairs.push([Math.log(a[k] / a[k - 1]), Math.log(s1 / s0)]); }
    if (pairs.length >= 52) {
      const mx = mean(pairs.map((p) => p[0])), my = mean(pairs.map((p) => p[1])); let c = 0, v = 0; pairs.forEach((p) => { c += (p[0] - mx) * (p[1] - my); v += (p[1] - my) ** 2; }); f.beta_2y = v > 0 ? c / v : null;
      const dn = pairs.filter((p) => p[1] < 0);
      if (dn.length >= 20) { const dx = mean(dn.map((p) => p[0])), dy = mean(dn.map((p) => p[1])); let c2 = 0, v2 = 0; dn.forEach((p) => { c2 += (p[0] - dx) * (p[1] - dy); v2 += (p[1] - dy) ** 2; }); f.beta_down = v2 > 0 ? c2 / v2 : null; } else f.beta_down = null;
    } else { f.beta_2y = null; f.beta_down = null; }
    const sr = []; for (let k = Math.max(1, n - 52); k < n; k++) sr.push(a[k] / a[k - 1] - 1);
    if (sr.length >= 40) { const s = sr.slice().sort((x, y) => x - y); f.cvar_5 = mean(s.slice(0, 3)); f.sigma_down = Math.sqrt(52) * Math.sqrt(mean(sr.map((x) => Math.min(x, 0) ** 2))); } else { f.cvar_5 = null; f.sigma_down = null; }
    w = win(156);
    if (w.length >= 100) { let mx = -Infinity, mdd = 0; w.forEach((x) => { mx = Math.max(mx, x); mdd = Math.min(mdd, x / mx - 1); }); f.mdd_3y = mdd; } else f.mdd_3y = null;
    return f;
  }
  function emaOf(xs, n) { const al = 2 / (n + 1); let e = xs[0]; for (let i = 1; i < xs.length; i++) e = al * xs[i] + (1 - al) * e; return e; }

  // ---------- Yahoo fetch (direct, then AllOrigins CORS fallback) ----------
  function chartUrl(sym, host) { return `https://${host}.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=5y&interval=1wk&includeAdjustedClose=true`; }
  async function fetchChart(sym) {
    const s = sym.replace(".", "-"), q1 = chartUrl(s, "query1"), q2 = chartUrl(s, "query2"), AO = "https://api.allorigins.win";
    const candidates = [q1, `${AO}/raw?url=${encodeURIComponent(q2)}`, `${AO}/get?url=${encodeURIComponent(q2)}`, `${AO}/raw?url=${encodeURIComponent(q1)}`, `${AO}/get?url=${encodeURIComponent(q1)}`];
    let lastErr;
    for (const url of candidates) {
      try {
        const ctl = new AbortController(); const timer = setTimeout(() => ctl.abort(), url === q1 ? 8000 : 25000);
        const res = await fetch(url, { cache: "no-store", signal: ctl.signal }); clearTimeout(timer);
        if (!res.ok) throw new Error(String(res.status));
        let data = await res.json(); if (url.includes("/get?url=")) data = JSON.parse(data.contents);
        const r = data?.chart?.result?.[0]; if (!r || !r.timestamp) throw new Error("no data");
        const adj = r.indicators?.adjclose?.[0]?.adjclose || r.indicators?.quote?.[0]?.close, cl = r.indicators?.quote?.[0]?.close || adj;
        const keys = [], a = [], c = [];
        r.timestamp.forEach((ts, k) => { if (adj[k] != null && adj[k] > 0) { keys.push(new Date(ts * 1000).toISOString().slice(0, 10)); a.push(adj[k]); c.push(cl[k] ?? adj[k]); } });
        return { meta: r.meta, keys, a, c };
      } catch (e) { lastErr = e; }
    }
    throw lastErr || new Error("fetch failed");
  }
  async function getSpy() {
    if (!state.spyW) {
      let s = null; for (let k = 0; k < 2 && !s; k++) { try { s = await fetchChart("SPY"); } catch (_) {} }
      if (!s) s = { keys: M.spy_w.keys, a: M.spy_w.a, meta: {}, shipped: true };
      state.spyW = s; state.spyMap = new Map(s.keys.map((k, i) => [k, s.a[i]]));
    }
    return state.spyW;
  }
  function baseOf(t) {   // shipped features + meta, following share-class aliases
    const prim = D.rows[t] ? t : M.alias[t];
    if (!prim) return null;
    return { f: rowOf(prim), m: tmeta(prim), prim };
  }
  async function liveScore(t) {
    await getSpy();
    const c = await fetchChart(t), px = c.meta.regularMarketPrice || c.c[c.c.length - 1];
    const b = baseOf(t), pf = priceFeatures(c.a, state.spyMap, c.keys);
    let f, m;
    if (b) {
      f = Object.assign({}, b.f, pf); m = b.m;
      if (b.prim !== t && b.f.px > 0) f = Object.assign(reprice(f, b.f.px), { px });   // alias: company-level ratios from the primary class
      else f = reprice(f, px);
    } else { f = Object.assign({}, pf, { px }); m = { sector: "Other", fund: false, fin: false, form4: 0, name: c.meta.longName || c.meta.shortName || "" }; }
    f.sma40c = c.c.length >= 30 ? mean(c.c.slice(-40)) : f.sma40c; f.ema10c = c.c.length ? emaOf(c.c.slice(-260), 10) : f.ema10c;
    return { f, m, chart: c, at: new Date() };
  }

  // ---------- helpers ----------
  const pct = (x, d = 0) => (x == null || !isFinite(x) ? "–" : (x * 100).toFixed(d) + "%");
  const sgn = (x) => (x == null || !isFinite(x) ? "–" : (x >= 0 ? "+" : "") + (x * 100).toFixed(0) + "%");
  const usd = (x) => (x == null || !isFinite(x) ? "–" : "$" + (x >= 1000 ? x.toLocaleString("en-US", { maximumFractionDigits: 0 }) : x.toFixed(2)));
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const laTime = (d) => d.toLocaleString("en-US", { timeZone: "America/Los_Angeles", month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }) + " PT";
  function loadResearch() { try { const a = JSON.parse(localStorage.getItem(LS_KEY) || "[]"); return a.filter((x) => x && x.t).map((x) => ({ t: x.t, name: x.name || "", at: x.at || null })); } catch (_) { return []; } }
  function saveResearch() { localStorage.setItem(LS_KEY, JSON.stringify(state.research)); }
  function scoreColor(x) { const g = Math.max(-1, Math.min(1, (x - 5) / 3)); return g >= 0 ? `rgba(34,197,94,${0.12 + 0.45 * g})` : `rgba(239,68,68,${0.12 - 0.45 * g})`; }
  function g1Color(x) { const g = Math.max(-1, Math.min(1, (x - 50) / 35)); return g >= 0 ? `rgba(34,197,94,${0.15 + 0.5 * g})` : `rgba(239,68,68,${0.15 - 0.5 * g})`; }
  function bar(v, cls, tip) { const w = v == null ? 0 : Math.max(0, Math.min(100, v)); return `<div class="bar ${cls}" title="${esc(tip)}"><i style="width:${w}%"></i><span>${v == null ? "–" : Math.round(v)}</span></div>`; }
  function agree(pctv, ai) { if (ai == null || pctv == null) return null; const g = pctv >= 0.8 ? 1 : pctv <= 0.2 ? -1 : 0, d = ai >= 7 ? 1 : ai <= 4 ? -1 : 0; if (!g || !d) return "neutral"; return g === d ? "agree" : "disagree"; }
  function agreePill(a) { if (!a) return ""; return `<span class="ag ag-${a}" title="G1 in its top/bottom 20% vs Danelfin AI ≥7 bullish / ≤4 bearish">${{ agree: "Agree", disagree: "Disagree", neutral: "Neutral" }[a]}</span>`; }

  // full evaluation of a ticker (shipped or live)
  function evalTicker(t, entry) {
    const L = state.live[t]; let f, m, live = false;
    if (L) { f = L.f; m = L.m; live = true; } else { const b = baseOf(t); if (!b) return null; f = b.f; m = b.m; }
    const sc = scoreTicker(t, f, m);
    return { t, f, m, sc, live, vd: verdict(sc, f), kl: kelly(sc, f, t), st: stops(f, entry), tg: targets(sc, f.px), sty: styleOf(f, m.fund) };
  }

  // ---------- views ----------
  function bookRows(k) { return D.books[k] || []; }
  function views() {
    const v = []; if (P.show_sp500) v.push(["SP", "S&P 500"]);
    v.push(["TOP", "G1 Top 30"]);
    Object.keys(D.books).forEach((b) => v.push(["B:" + b, b]));
    v.push(["RES", "Watchlist"]);
    return v;
  }
  function danelfinOf() { const o = {}; Object.values(D.books).forEach((rows) => rows.forEach((r) => { if (r.ai != null && !o[r.t]) o[r.t] = r; })); return o; }
  function rowsForView() {
    if (state.view === "SP") return Object.keys(D.tmeta).filter((t) => D.tmeta[t][3] === 1).map((t) => ({ t }));
    if (state.view === "TOP") return D.finalists.map((t) => ({ t }));
    if (state.view === "RES") return state.research.map((r) => ({ t: r.t, research: true }));
    return bookRows(state.view.slice(2)).map((r) => ({ t: r.t, shares: r.shares, entry: r.entry, name: r.name }));
  }
  function renderTabs() { $("tabs").innerHTML = views().map(([k, l]) => `<button class="tab ${state.view === k ? "on" : ""}" data-v="${esc(k)}">${esc(l)}</button>`).join(""); }
  function renderWeather() {
    const w = weather(), W = M.weather;
    const expl = w.mode === "capit" ? "Deep sell-off with breadth recovering and credit spreads easing: historically a buying window. New buys allowed."
      : w.mode === "bear" ? `S&P 500 below its 40-week average and only ${pct(W.breadth)} of large stocks above theirs. Hold a ${pct(w.reserve)} T-bill reserve (e.g. SGOV) and pause new buys.`
      : w.regime === "on" ? "S&P 500 above its 40-week average and credit spreads calm. Scores lean toward upside (65% Upside / 35% Safety); 100% equities."
      : w.regime === "neutral" ? "Mixed signals. Scores weigh Upside and Safety equally; 100% equities."
      : "S&P 500 below its 40-week average or credit spreads wide. Scores lean toward safety (30% Upside / 70% Safety).";
    $("weather").className = "weather w-" + w.mode;
    $("weather").innerHTML = `<div class="wx-main"><span class="wx-icon">${w.icon}</span><div><b>Market Weather: ${esc(w.label)}</b> <span class="muted small">· cash allocation: ${w.reserve ? pct(w.reserve) + " T-bills (SGOV)" : "100% equities"}</span><div class="small">${esc(expl)}</div></div></div>
      <div class="small muted wx-det">S&amp;P 500 ${usd(w.spy)} vs 40-week avg ${usd(w.sma)}${w.live ? " (live)" : ""} · high-yield spread ${W.hy != null ? W.hy.toFixed(2) + "%" : "–"} (${W.hy_date}) · 10y−2y ${W.curve != null ? W.curve.toFixed(2) + "%" : "–"} · breadth ${pct(W.breadth)} of top 1,000 above 40-week avg · <i>model estimates, not advice</i></div>`;
  }
  function verdictPill(vd) { return `<span class="vd ${vd.cls}" title="${esc(vd.note || "Model estimate, not advice")}">${esc(vd.v)}</span>`; }
  function udBars(sc) { const tag = M.passed ? "" : " (descriptive; not the validated score)"; return bar(sc.U, "up", "Upside 🚀 0–100" + tag) + bar(sc.D, "safe", "Safety 🛡️ 0–100" + tag); }
  function g1Cell(sc) {
    const v4 = sc.v4 != null ? `<div class="small muted" title="S_v4 includes unvalidated analyst-style judgment from the business dossier">v4 ${Math.round(sc.v4)}*</div>` : "";
    return `<span class="g1" style="background:${g1Color(sc.g1)}" title="${sc.kind === "price" ? "Price-only score (no SEC fundamentals)" : M.live === "S_quant" ? "S_quant (validated quant score)" : "G1 composite percentile (validated live score)"}">${Math.round(sc.g1)}</span>${v4}`;
  }
  function oddsCell(e) {
    const b = e.sc.bands[12], br = M.base_rate[12];
    return `<b class="${b.hit - br >= 0.03 ? "pos" : b.hit - br <= -0.03 ? "neg" : ""}">${pct(b.hit)}</b> <span class="muted small">to beat S&amp;P</span><div class="small">${e.tg ? `${usd(e.tg.bear)} · <b>${usd(e.tg.base)}</b> · ${usd(e.tg.bull)}` : "–"}</div>`;
  }
  function stockCell(e, r, dan) {
    const nm = r.name || e.m.name || "";
    const d = dan[e.t]; const ag = d ? agree(e.sc.pct, d.ai) : null;
    const chips = [];
    if (P.danelfin && d && d.ai != null) chips.push(`<span class="chip" title="Danelfin AI Score (uploaded CSV)">Danelfin ${d.ai}</span>${agreePill(ag)}`);
    if (e.sty) chips.push(`<span class="chip" style="background:${scoreColor(e.sty.bm)}" title="Buffett &amp; Munger 0–10 (rule-based proxy)">B&amp;M ${e.sty.bm.toFixed(1)}</span><span class="chip" style="background:${scoreColor(e.sty.m15)}" title="${esc(MAGIC_NAME)} 0–10 (lean; rule-based proxy)">M15 ${e.sty.m15.toFixed(1)}</span>`);
    return `<b>${esc(e.t)}</b>${e.live ? ' <span class="live">live</span>' : ""}<span class="nm">${esc(nm)}</span><div class="chips">${chips.join("")}</div>`;
  }
  function stopText(st) {
    if (!st || st.stop == null) return "–";
    const lbl = { 1: "Stage 1 (40-week avg / tail risk)", 2: "Stage 2 (breakeven, after +20%)", 3: "Stage 3 (10-week EMA trail, after +40%)" }[st.stage];
    return `${usd(st.stop)} <span class="muted small">${lbl}${st.broken ? " · <b class='neg'>price is at or below this level</b>" : ""}${st.entry == null ? " · add a cost column for the ratchet" : ""}</span>`;
  }
  function strengthsFlags(e) {
    const sl = ["S1", "S2", "S3", "S4", "S5"].map((k) => [k, e.sc[k]]);
    const name = { S1: "Quality", S2: "Value vs adjusted EV", S3: "Growth & inflection", S4: "Trend & coil", S5: "Left-tail safety" };
    const good = sl.filter(([, v]) => v >= 0.65).map(([k, v]) => `${name[k]} (${Math.round(v * 100)})`);
    const bad = sl.filter(([, v]) => v <= 0.35).map(([k, v]) => `${name[k]} (${Math.round(v * 100)})`);
    const f = e.f;
    if (f.dd_52w != null && f.dd_52w < -0.3) bad.push(`${pct(-f.dd_52w)} below its 52-week high`);
    if (f.lev != null && f.lev > 0.5) bad.push(`debt ${pct(f.lev)} of assets`);
    if (f.dil_1y != null && f.dil_1y > 0.03) bad.push(`share count ${sgn(f.dil_1y)} in a year`);
    if (f.f_score != null && f.f_score >= 7) good.push(`Piotroski ${f.f_score.toFixed(1)}/9`);
    if (e.m.form4) good.push("insider buying cluster (Form 4)");
    const dz = D.dossiers[e.t]; if (dz && dz.top_threats && !dz.top_threats.startsWith("none")) bad.push(dz.top_threats);
    return { good, bad };
  }
  function dossierBlock(t) {
    const d = D.dossiers[t];
    if (!d) return `<div class="muted small">No business dossier for this name (built for holdings and the G1 Top 30; run <code>pipeline/analyze_ticker.py ${esc(t)}</code> for others).</div>`;
    const lbl = { moat: "Moat vs disruption", stakes: "Hidden stakes / SOTP", talent: "Talent & R&D", pricing: "Pricing power & backlog", variant: "Variant perception gap" };
    const sc = Object.entries(d.scores).map(([k, v]) => `<li>${lbl[k]}: <b>${v > 0 ? "+" : ""}${v}</b>${d.thin.includes(k) ? ' <span class="muted">(thin evidence, scored 0)</span>' : ""}</li>`).join("");
    const ev = d.evidence.slice(0, 8).map((x) => `<li>${esc(x.claim)}${x.src ? ` <a href="${esc(x.src)}" target="_blank" rel="noopener">source</a>` : ""}</li>`).join("");
    const fl = (d.filings || []).slice(0, 4).map((x) => `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.form)} ${esc(x.date)}</a>`).join(" · ");
    return `<div class="doss"><b>Variant Perception &amp; Disruption Dossier</b> <span class="muted small">(f_strat ${d.f_strat > 0 ? "+" : ""}${d.f_strat}; built ${esc(d.built)}; ${esc(d.method)})</span>
      <div class="small"><b>Consensus:</b> ${esc(d.consensus_view)}<br><b>Variant edge:</b> ${esc(d.variant_edge)}<br><b>Top threats:</b> ${esc(d.top_threats)}<br><b>Catalysts:</b> ${esc(d.catalysts)}</div>
      <div class="dgrid small"><div><ul>${sc}</ul></div><div><ul>${ev}</ul></div></div><div class="small muted">Recent SEC filings: ${fl || "–"}</div></div>`;
  }
  function detailHtml(e, r) {
    const sc = e.sc, dan = danelfinOf()[e.t];
    const strip = HZ.map((h) => { const b = sc.bands[h], br = M.base_rate[h]; return `<div class="hzbox"><div class="muted small">${h < 12 ? h + "m" : h / 12 + "y"}</div><div class="ch ${b.hit - br >= 0.03 ? "pos" : b.hit - br <= -0.03 ? "neg" : ""}">${pct(b.hit)}</div></div>`; }).join("");
    const { good, bad } = strengthsFlags(e);
    const dsub = P.danelfin && dan ? `<div class="small">Danelfin (uploaded CSV): AI ${dan.ai ?? "–"} · Fundamental ${dan.fund ?? "–"} · Technical ${dan.tech ?? "–"} · Sentiment ${dan.sent ?? "–"} · Low Risk ${dan.lowrisk ?? "–"} ${agreePill(agree(sc.pct, dan.ai))}</div>` : "";
    const sty = e.sty ? `<div class="dgrid small"><div><b>Buffett &amp; Munger ${e.sty.bm.toFixed(1)}/10</b><ul>${Object.entries(e.sty.bm_st).map(([k, v]) => `<li>${esc(BM_LBL[k])}: <b>${v}</b>/${BM_MAX[k]}</li>`).join("")}</ul></div>
      <div><b>${esc(MAGIC_NAME)} ${e.sty.m15.toFixed(1)}/10</b> <span class="muted">(${esc(M.magic.sub)})</span><ul>${Object.entries(e.sty.m15p).map(([k, v]) => `<li>${esc(M.magic.labels[k])}: <b>${(v * 10).toFixed(1)}</b>/10</li>`).join("")}</ul></div></div>` : "";
    return `<div class="dgrid">
        <div><b>Strengths</b><ul class="small">${good.map((x) => `<li>${esc(x)}</li>`).join("") || "<li class='muted'>none stand out</li>"}</ul><b>Red flags</b><ul class="small">${bad.map((x) => `<li>${esc(x)}</li>`).join("") || "<li class='muted'>none flagged</li>"}</ul></div>
        <div><b>12-month dollar targets</b> <span class="muted small">(vs a flat S&amp;P 500)</span><div>Bear ${usd(e.tg?.bear)} · Base <b>${usd(e.tg?.base)}</b> · Bull ${usd(e.tg?.bull)}</div>
          <div class="small">Stop-loss: ${stopText(e.st)}</div>
          <div class="small">Suggested size (half-Kelly): <b>${pct(e.kl.k, 1)}</b>${e.kl.soon ? " (halved: earnings expected within 7 days)" : ""}${e.kl.earn ? ` · next results ~${esc(e.kl.earn)} (est.)` : ""}</div>
          ${e.vd.note ? `<div class="small"><b>${esc(e.vd.v)}:</b> ${esc(e.vd.note)}</div>` : ""}
          <div class="small muted">Model estimates, not advice. Bands are how similar-scoring stocks did out of sample (10th/50th/90th percentile excess return).</div>
          <div><b>Chance to beat the S&amp;P 500</b><div class="hzrow">${strip}</div></div></div>
      </div>${dsub}${sty}${dossierBlock(e.t)}`;
  }
  function renderHealth() {
    const el = $("health");
    if (!state.view || !state.view.startsWith("B:")) { el.innerHTML = ""; el.hidden = true; return; }
    const rows = bookRows(state.view.slice(2)); const warn = [];
    const val = {}; let tot = 0;
    rows.forEach((r) => { const e = evalTicker(r.t, r.entry); const px = e?.f?.px; const v = r.shares > 0 && px > 0 ? r.shares * px : null; val[r.t] = { v, sector: e?.m?.sector || "Other" }; });
    const useShares = rows.every((r) => val[r.t].v != null);
    const bySec = {}; rows.forEach((r) => { const w = useShares ? val[r.t].v : 1; tot += w; bySec[val[r.t].sector] = (bySec[val[r.t].sector] || 0) + w; });
    Object.entries(bySec).forEach(([s, w]) => { if (tot > 0 && w / tot > 0.35) warn.push(`Warning: ${s} is ${pct(w / tot)} of this book (over 35%). Check diversification.`); });
    const ts = rows.map((r) => r.t).filter((t) => D.w53[t]);
    const ret = {}; ts.forEach((t) => { const a = D.w53[t]; ret[t] = a.slice(1).map((x, i) => (x != null && a[i] != null ? x / a[i] - 1 : null)); });
    const pairs = [];
    for (let i = 0; i < ts.length; i++) for (let j = i + 1; j < ts.length; j++) {
      const x = [], y = []; ret[ts[i]].forEach((v, k) => { const w = ret[ts[j]][k]; if (v != null && w != null) { x.push(v); y.push(w); } });
      if (x.length < 40) continue;
      const mx = mean(x), my = mean(y); let c = 0, vx = 0, vy = 0; x.forEach((v, k) => { c += (v - mx) * (y[k] - my); vx += (v - mx) ** 2; vy += (y[k] - my) ** 2; });
      const rho = c / Math.sqrt(vx * vy); if (rho > 0.8) pairs.push([ts[i], ts[j], rho]);
    }
    pairs.sort((a, b) => b[2] - a[2]).forEach(([a, b, r]) => warn.push(`Warning: ${a} and ${b} are moving identically (correlation ${r.toFixed(2)}). Check diversification.`));
    const sec = Object.entries(bySec).sort((a, b) => b[1] - a[1]).map(([s, w]) => `${s} ${pct(w / tot)}`).join(" · ");
    el.hidden = false;
    el.innerHTML = `<b>Portfolio Health</b> <span class="muted small">(${useShares ? "weights by value" : "equal weights"}; 52-week weekly-return correlations)</span><div class="small">${sec}</div>` +
      (warn.length ? warn.map((w) => `<div class="hwarn">⚠️ ${esc(w)}</div>`).join("") : `<div class="small pos">No sector above 35% and no pair of holdings above 0.80 correlation.</div>`);
  }
  function renderTable() {
    const dan = danelfinOf(), isRes = state.view === "RES";
    let rows = rowsForView().map((r) => Object.assign(r, { e: evalTicker(r.t, r.entry) }));
    const fl = state.filter.trim().toUpperCase();
    if (fl) rows = rows.filter((r) => r.t.includes(fl) || String(r.name || r.e?.m?.name || "").toUpperCase().includes(fl));
    const val = (r) => { const e = r.e; if (!e) return -1; switch (state.sortKey) { case "t": return r.t; case "vd": return ["SELL / BROKEN", "CLIMAX TRIM", "HOLD", "ACCUMULATE (Staggered)", "STRONG BUY"].findIndex((x) => e.vd.v.startsWith(x)); case "ud": return e.sc.U; case "odds": return e.sc.bands[12].hit; case "kelly": return e.kl.k; default: return e.sc.g1; } };
    rows.sort((a, b) => { const x = val(a), y = val(b); return (x < y ? -1 : x > y ? 1 : 0) * state.sortDir; });
    const th = (k, l, tip) => `<th data-k="${k}" title="${esc(tip || "")}">${l}${state.sortKey === k ? (state.sortDir < 0 ? " ▾" : " ▴") : ""}</th>`;
    let html = `<table class="main"><thead><tr>${th("t", "Stock")}${th("vd", "Action verdict", "Model estimate, not advice")}${th("score", "G1 Score", "0–100. v4* = adds the unvalidated business-dossier overlay")}${th("ud", "Upside 🚀 &amp; Safety 🛡️")}${th("odds", "1-yr win odds &amp; $ range", "Chance to beat the S&P 500 over 12 months; Bear · Base · Bull dollar targets")}${th("kelly", "Size", "Half-Kelly, max 10%, halved before earnings")}${isRes ? "<th></th>" : ""}</tr></thead><tbody>`;
    for (const r of rows) {
      const e = r.e, open = state.open.has(r.t);
      if (!e) { html += `<tr data-x="${esc(r.t)}"><td><b>${esc(r.t)}</b></td><td colspan="5" class="muted">Not in the bundled universe. Look it up above for a live price-only read.</td>${isRes ? `<td><button class="ghost" data-unpin="${esc(r.t)}">Remove</button></td>` : ""}</tr>`; continue; }
      html += `<tr class="${open ? "open" : ""}" data-x="${esc(r.t)}"><td>${stockCell(e, r, dan)}</td><td>${verdictPill(e.vd)}</td><td>${g1Cell(e.sc)}</td><td>${udBars(e.sc)}</td><td>${oddsCell(e)}</td><td><b>${pct(e.kl.k, 1)}</b>${e.kl.soon ? ' <span class="small" title="Earnings expected within 7 days: size halved">⏰</span>' : ""}</td>${isRes ? `<td><button class="ghost" data-unpin="${esc(r.t)}">Remove</button></td>` : ""}</tr>`;
      if (open) html += `<tr class="det"><td colspan="${6 + (isRes ? 1 : 0)}">${detailHtml(e, r)}</td></tr>`;
    }
    html += "</tbody></table>";
    if (!rows.length) html = `<div class="card muted">${isRes ? "Nothing pinned yet. Look up a ticker above and press Pin to Watchlist." : "No rows."}</div>`;
    $("tbl").innerHTML = html;
    $("count").textContent = `${rows.length} stocks · click a row for the full report`;
    renderHealth();
  }
  function renderStatus() { $("asof").textContent = `Prices as of ${M.price_asof}` + (state.refreshedAt ? ` · live refresh ${laTime(state.refreshedAt)}` : "") + ` · model built ${M.built}`; }
  function renderBacktest() {
    const v = M.v4, f = (x) => `${x.ic.toFixed(3)} <span class="muted">(t≈${x.t.toFixed(1)})</span>`;
    const rowsOf = (lab) => HZ.map((h) => { const r = v[h][lab]; return `<tr><td>${h}m</td>${["S_quant", "A", "U", "D", "S_price"].map((m) => `<td>${f(r[m])}<br><span class="small muted">p10 ${sgn(r[m].p10)} · top−bottom ${sgn(r[m].tmb)}</span></td>`).join("")}</tr>`; }).join("");
    const head = `<tr><th>Horizon</th><th>S_quant (v4)</th><th>v2 composite A</th><th>Upside U</th><th>Safety D</th><th>Price-only</th></tr>`;
    const ps = M.v4_pass;
    $("bt").innerHTML = `<p class="small">Pre-registered test (docs/PREREGISTRATION_V4.md): top 1,000 US stocks, month-ends from 2014. Labels include a −30% delisting haircut for distressed exits and a 10 bps turnover drag on the top decile. Result: <b>${ps.PASS ? "PASS: S_quant is the live quant score" : "FAIL: v2 composite A stays the live quant score"}</b> (beats A's rank IC at ${ps.a_ic_wins}/6 horizons; t>2.5 at 12m and 24m: ${ps.b_t12_t24 ? "yes" : "no"}; better top-decile p10 at ${ps.c_p10_wins}/6).</p>
      <div class="tblwrap"><table>${head}${rowsOf("haircut_drag")}</table></div>
      <details><summary class="small">Same test without the haircut and drag</summary><div class="tblwrap"><table>${head}${rowsOf("raw")}</table></div></details>
      ${M.style_bt.BM ? `<details><summary class="small">Buffett &amp; Munger and ${esc(MAGIC_NAME)} backtests (rank IC)</summary><div class="tblwrap"><table><tr><th>Horizon</th><th>B&amp;M</th><th>${esc(MAGIC_NAME)} (lean)</th></tr>${HZ.map((h) => `<tr><td>${h}m</td><td>${f(M.style_bt.BM[h])}</td><td>${f(M.style_bt.M15[h])}</td></tr>`).join("")}</table></div></details>` : ""}`;
  }

  // ---------- look-up report card ----------
  async function doSearch() {
    const t = $("q").value.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, "").replace("-", ".");
    if (!t) return;
    const out = $("searchOut");
    const show = (e, note) => {
      const pinned = state.research.some((x) => x.t === t);
      const dan = danelfinOf()[t];
      out.innerHTML = `<div class="card report"><div class="row" style="justify-content:space-between"><div><b style="font-size:18px">${esc(t)}</b> <span class="muted">${esc(e.m.name || "")}</span> · ${usd(e.f.px)} ${note ? `<span class="muted small">${esc(note)}</span>` : ""}</div>
        <div><button id="pinBtn">${pinned ? "Pinned ✓" : "Pin to Watchlist"}</button> <button class="ghost" id="closeRep">✕</button></div></div>
        <div class="rgrid"><div><div class="muted small">G1 Score</div>${g1Cell(e.sc)}</div><div><div class="muted small">Verdict</div>${verdictPill(e.vd)}</div><div style="min-width:220px"><div class="muted small">Upside 🚀 / Safety 🛡️</div>${udBars(e.sc)}</div>
        <div><div class="muted small">1-yr win odds</div>${oddsCell(e)}</div><div><div class="muted small">Size</div><b>${pct(e.kl.k, 1)}</b></div>${P.danelfin && dan ? `<div><div class="muted small">Danelfin</div><b>${dan.ai ?? "–"}</b> ${agreePill(agree(e.sc.pct, dan.ai))}</div>` : ""}</div>
        ${detailHtml(e, { t })}</div>`;
      $("pinBtn").onclick = () => { if (!state.research.some((x) => x.t === t)) { state.research.push({ t, name: e.m.name || "", at: new Date().toISOString() }); saveResearch(); } $("pinBtn").textContent = "Pinned ✓"; if (state.view === "RES") renderTable(); };
      $("closeRep").onclick = () => (out.innerHTML = "");
    };
    const shipped = evalTicker(t, null);
    if (shipped) show(shipped, "bundled data; fetching live price…"); else out.innerHTML = `<div class="card muted">Fetching ${esc(t)} from Yahoo…</div>`;
    try {
      const r = await liveScore(t); state.live[t] = { f: r.f, m: r.m, at: r.at };
      const e = evalTicker(t, null);
      show(e, (D.rows[t] ? "live price" : M.alias[t] ? `live price; fundamentals from share class ${M.alias[t]}` : "live price-only read (no bundled SEC data)"));
    } catch (err) {
      if (!shipped) out.innerHTML = `<div class="card err">Could not fetch ${esc(t)} (${esc(err.message)}). Yahoo or the CORS proxy may be blocking requests; try again shortly.</div>`;
      else show(shipped, "bundled data (live fetch failed)");
    }
  }

  // ---------- refresh ----------
  async function refresh() {
    if (state.busy) return; state.busy = true; $("refresh").disabled = true;
    const tickers = [...new Set(rowsForView().map((r) => r.t))];
    let ok = 0, done = 0; const failed = [];
    $("refStatus").textContent = `Refreshing ${tickers.length} names from Yahoo…` + (tickers.length > 60 ? " (large list through a free proxy: this can take 10+ minutes; keep the tab open)" : "");
    state.spyW = null; await getSpy(); renderWeather();
    const queue = tickers.slice();
    async function worker() {
      while (queue.length) {
        const t = queue.shift();
        try { let r = null; try { r = await liveScore(t); } catch (_) { r = await liveScore(t); } state.live[t] = { f: r.f, m: r.m, at: r.at }; ok++; } catch (_) { failed.push(t); }
        done++; if (done % 10 === 0 || done === tickers.length) $("refStatus").textContent = `Refreshed ${done}/${tickers.length}…`;
      }
    }
    await Promise.all(Array.from({ length: 6 }, worker));
    state.refreshedAt = new Date(); state.busy = false; $("refresh").disabled = false;
    $("refStatus").textContent = `Live: ${ok}/${tickers.length} updated ${laTime(state.refreshedAt)}` + (state.spyW.shipped ? " (SPY from bundled history)" : "") + (failed.length ? ` · failed: ${failed.slice(0, 12).join(", ")}${failed.length > 12 ? "…" : ""} (bundled scores kept)` : "");
    renderStatus(); renderWeather(); renderTable();
  }

  // ---------- wire up ----------
  document.addEventListener("click", (e) => {
    const v = e.target.closest("[data-v]"); if (v) { state.view = v.dataset.v; renderTabs(); renderTable(); return; }
    const k = e.target.closest("th[data-k]"); if (k) { if (state.sortKey === k.dataset.k) state.sortDir *= -1; else { state.sortKey = k.dataset.k; state.sortDir = k.dataset.k === "t" ? 1 : -1; } renderTable(); return; }
    const u = e.target.closest("[data-unpin]"); if (u) { state.research = state.research.filter((x) => x.t !== u.dataset.unpin); saveResearch(); renderTable(); return; }
    if (e.target.closest("a")) return;
    const x = e.target.closest("tr[data-x]"); if (x) { const t = x.dataset.x; state.open.has(t) ? state.open.delete(t) : state.open.add(t); renderTable(); }
  });
  state.view = views()[P.show_sp500 ? 2 : 1]?.[0] || views()[0][0];
  if (!Object.keys(D.books).length) state.view = "TOP";
  $("refresh").onclick = refresh; $("go").onclick = doSearch;
  $("q").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
  $("helpT").onclick = (e) => { e.preventDefault(); $("help").hidden = !$("help").hidden; };
  $("refStatus").textContent = "Scores use prices shipped at build. Refresh pulls live prices and re-scores in your browser.";
  $("flt").addEventListener("input", (e) => { state.filter = e.target.value; renderTable(); });
  renderWeather(); renderTabs(); renderStatus(); renderTable(); renderBacktest();
  // for local verification only
  window.G1 = { qpct, rawScores, scoreTicker, priceFeatures, reprice, classify, weather, evalTicker, rowOf, tmeta, D, state };
})();
