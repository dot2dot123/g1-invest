(function () {
  "use strict";
  // G1 v4 dashboard. All formulas mirror pipeline/build_site.py live_scores() and docs/PREREGISTRATION_V4.md.
  const D = JSON.parse(document.getElementById("g1data").textContent);
  const M = D.meta, HZ = M.horizons, P = M.page;
  const HZ_STRIP = M.hz_strip || [3, ...HZ];
  const HZ_LBL = (h) => (h < 12 ? h + "m" : (h / 12) + "y");
  const HZ_HEAD = (h) => (h === 3 ? "3 mo" : (h < 12 ? h + " mo" : (h / 12) + " yr"));
  const HZ_W = { 3: 0.05, 6: 0.10, 12: 0.20, 24: 0.20, 36: 0.15, 48: 0.15, 60: 0.15 };
  const HZ_W_TIP = "G1 Overall is a weighted blend of the 1–10 horizon scores: 3 mo 5%, 6 mo 10%, 1 yr 20%, 2 yr 20%, 3 yr 15%, 4 yr 15%, 5 yr 15%. Missing horizons are dropped and the rest re-weighted. Model estimate, not advice.";
  const NCOL = 14; // Stock, Verdict, G1 Score, G1 Overall, 7 horizons, Upside, 1-yr odds, Size
  let edgeCuts = null; // per-horizon edge decile cuts (universe), rebuilt after a live refresh
  const $ = (id) => document.getElementById(id);
  const LS_KEY = "g1.research.v1"; // watchlist (kept from v1-v3; entries migrate automatically)
  const POS_KEY = "g1.positions.v1"; // browser-only Entry $ per ticker; never leaves this browser
  const COLI = Object.fromEntries(M.cols.map((c, i) => [c, i]));
  const state = { view: null, sortKey: "score", sortDir: -1, filter: "", live: {}, spyW: null, refreshedAt: null, busy: false, research: loadResearch(), open: new Set(), pos: loadPos(), proxyIdx: 0 };

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
    const eqVM = W.eq_vm ?? 1, equity = Math.min(eqVM, 1 - reserve);
    return { regime, bear: bear && !capit, capit, reserve, label, icon, mode, spy, sma, hi, live, eqVM, equity };
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
    o.fcfy_ev = fcf != null && ev > 0 ? fcf / ev : null;
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
    const cal = M.cal && M.cal[h] && M.cal[h][model];
    if (score == null || !cal || !M.pq[model]) return null;
    const s = qpct(score, M.pq[model]), mids = cal.map((c) => c.mid), o = { pct: s };
    ["hit", "p10", "p50", "p90"].forEach((k) => (o[k] = interp(s, mids, cal.map((c) => c[k]))));
    return o;
  }
  // ---------- v4.2 live score (mirror of build_site.v42_parts / v42_score) ----------
  function v42Of(f, sector) {
    const q = M.v42q, sqs = q.sec[sector] || {}, nz5 = (v) => (v == null ? 0.5 : v);
    const bm = Object.values(bmStatic(f)).reduce((a, b) => a + b, 0);
    const sg = (v, s) => (v == null ? 0.5 : s > 0 ? v : 1 - v);
    const pills = Object.values(M.magic.pillars).map((comps) => comps.reduce((a, [n, s]) => a + sg(qpct(f[n], M.mq[n]), s), 0) / comps.length);
    const l15 = 10 * pills.reduce((a, b) => a + b, 0) / pills.length;
    const p1 = nz5(qpct(bm, q.bm)), p2 = nz5(qpct(l15, q.l15));
    const p3 = (nz5(qpct(f.ey_hist_med, sqs.ey_hist_med)) + nz5(qpct(f.fcfy_ev, sqs.fcfy_ev))) / 2;
    const bd = qpct(f.beta_down, q.beta_down);
    const p4 = (nz5(qpct(f.mom_12_1, sqs.mom_12_1)) + (bd == null ? 0.5 : 1 - bd)) / 2;
    const blend = (p1 + p2 + p3 + p4) / 4;
    let v = qpct(blend, q.blend); const gated = bm < 4.0; if (gated) v = Math.min(v, 0.65);
    return { V42: 100 * v, bm, l15, P1: p1, P2: p2, P3: p3, P4: p4, gated };
  }
  function scoreTicker(t, f, m) {
    // f: features (shipped or live). m: tmeta-like {sector, fund, fin, form4}
    const wx = weather();
    const r = rawScores(f, m.sector, m.fin, m.form4, wx.regime);
    if (m.fund) { const v = v42Of(f, m.sector); r.V42 = v.V42; r.v42 = v; } else r.V42 = null;
    const model = m.fund ? M.live : "S_price";
    const raw = r[model], bands = {};
    HZ_STRIP.forEach((h) => {
      const mdl = (h === 3 && M.v42_3m && m.fund) ? M.v42_3m.winner : model;
      bands[h] = calib(r[mdl], mdl, h);
    });
    const pct = bands[12] ? bands[12].pct : null;
    const quant = model === "A" ? 100 * pct : raw;   // validated headline score, 0-100
    const dz = D.dossiers[t];
    // Upside / Safety as percentiles among the top-1,000 universe (same scale as the G1 Score; raw sleeve averages are compressed ~10-80)
    r.Up = r.U == null ? null : 100 * qpct(r.U, M.pq.U); r.Sp = r.D == null ? null : 100 * qpct(r.D, M.pq.D);
    return Object.assign(r, { model, bands, pct, g1: quant, quant, fstrat: dz ? dz.f_strat : null, kind: m.fund ? "full" : "price" });
  }
  // ---------- execution rules (docs/PREREGISTRATION_V4_2.md §4; UI rules, not backtested; model estimates, not advice) ----------
  const VCLS = { "STRONG BUY": "v-buy", "ACCUMULATE (Staggered)": "v-acc", "WAIT FOR TREND (Pullback)": "v-wait", "CLIMAX TRIM": "v-trim", "SELL / BROKEN": "v-sell", "HOLD": "v-hold" };
  const VNOTE = {
    "STRONG BUY": "Strong business and the price trend agrees (above its 40-week average, not overheated).",
    "ACCUMULATE (Staggered)": "Strong business, but up more than 15% in a month: buy 50% now, add 50% on a pullback to the 10- or 40-week average.",
    "WAIT FOR TREND (Pullback)": "Strong fundamentals; wait for price to reclaim the 10-week EMA or hit the Deep-Value zone.",
    "CLIMAX TRIM": "Up 40%+ from your entry, stretched 35%+ above its 40-week average on a huge-volume week that closed weak: consider trimming.",
    "SELL / BROKEN": "Below its 40-week average and the business is weak (G1 Score under 45, or falling operating margins with a score under 70).",
    "HOLD": "Nothing urgent either way." };
  function verdict(sc, f, entry) {
    const wx = weather(), Q = sc.quant, Up = sc.Up, Sf = sc.Sp, P = f.px, sma = f.sma40c, r1 = f.rev_1m;
    const below = sma != null ? P < sma : f.sma40_below === 1, above = sma != null ? P > sma : f.sma40_below === 0;
    const gain = entry > 0 && P > 0 ? P / entry - 1 : null;
    const hasFund = sc.kind !== "price";   // QA fix: no SEC fundamentals (ETFs, some foreign listings) -> no 'strong business' verdicts
    const fundOK = hasFund && Q >= 75 && Up >= 70 && Sf >= 60;
    let v;
    if (gain != null && gain >= 0.4 && sma != null && P > 1.35 * sma && f.wk_vol_x != null && f.wk_vol_x > 3 && f.wk_close_pos != null && f.wk_close_pos < 0.5) v = "CLIMAX TRIM";
    else if (fundOK && above && !(r1 > 0.15)) v = "STRONG BUY";
    else if (fundOK && above && r1 > 0.15) v = "ACCUMULATE (Staggered)";
    else if (hasFund && Q >= 70 && Up >= 65 && (below || (f.dd_52w != null && f.dd_52w < -0.2))) v = "WAIT FOR TREND (Pullback)";
    else if (below && (Q < 45 || (f.om_trend != null && f.om_trend < 0 && Q < 70))) v = "SELL / BROKEN";   // QA fix: a strong G1 Score (70+) is never "broken" on a margin dip alone
    else v = "HOLD";
    const out = { v, base: v, cls: VCLS[v], note: VNOTE[v] };
    if (!hasFund && v === "HOLD") out.note = "Price-only score (no SEC fundamentals, e.g. an ETF or foreign listing): buy verdicts need fundamentals.";
    if (wx.bear && (v === "STRONG BUY" || v === "ACCUMULATE (Staggered)")) { out.v += " (buys paused)"; out.note = "Bear Preservation: new buys paused; keep the T-bill reserve."; }
    return out;
  }
  function kelly(sc, f, t, vd) {   // conviction sizing (name kept for compatibility)
    const p = sc.bands[12].hit, base = M.base_rate[12], edge = Math.max(0, p - base);
    const sd = f.sigma_down != null && isFinite(f.sigma_down) ? f.sigma_down : 0.25, r = edge / Math.max(sd, 0.12);
    let tier, k;
    if (r >= 0.40) { tier = "High conviction"; k = 0.06 + 0.02 * Math.min(1, (r - 0.40) / 0.40); }
    else if (r >= 0.20) { tier = "Core"; k = 0.03 + 0.02 * (r - 0.20) / 0.20; }
    else if (r > 0) { tier = "Starter"; k = 0.01 + 0.01 * r / 0.20; }
    else { tier = "No edge"; k = 0; }
    const why = [];
    if (vd && (vd.base === "SELL / BROKEN" || vd.base === "CLIMAX TRIM")) { k = 0; tier = vd.base === "SELL / BROKEN" ? "Exit / avoid" : "Trim"; }
    if (vd && vd.base === "WAIT FOR TREND (Pullback)" && k > 0) { k /= 2; why.push("halved: waiting for trend"); }
    const e = D.earn[t]; let soon = false;
    if (e) { const days = (new Date(e + "T00:00:00") - new Date(new Date().toDateString())) / 86400000; soon = days >= 0 && days <= 7; if (soon && k > 0) { k /= 2; why.push("halved: earnings within 7 days"); } }
    return { k, tier, edge, p, base, r, soon, earn: e, why };
  }
  function deepValue(f) {   // price at which EBIT/EV equals its 5-year median
    if (!(f.ebit > 0) || !(f.ey_hist_med > 0) || !(f.shares_adj > 0)) return null;
    const p = (f.ebit / f.ey_hist_med - (f.debt || 0) + (f.cash || 0)) / f.shares_adj;
    return p > 0 && isFinite(p) ? p : null;
  }
  function stops(f, entry, vd) {
    const P = f.px; if (!(P > 0)) return null;
    const risk = f.cvar_5 != null && f.cvar_5 < 0 ? P * (1 + f.cvar_5) : null, sma = f.sma40c;   // cvar_5 >= 0 = untraded/flat price data: no risk stop
    const smaOk = sma != null && sma < P;
    let s1 = smaOk ? Math.max(sma, risk ?? -Infinity) : risk;
    if (!(s1 > 0 && s1 < P)) s1 = null;   // a stop is always below the current price
    const o = { entry: entry > 0 ? entry : null, s1, trendBroken: sma != null && sma >= P, sma, ema: f.ema10c, dv: deepValue(f) };
    if (o.entry) {
      const gain = P / entry - 1; let stage = 1, stop = s1;
      if (gain >= 0.2) { stage = 2; stop = Math.max(stop ?? -Infinity, entry); }
      if (gain >= 0.4 && f.ema10c != null && f.ema10c < P) { stage = 3; stop = Math.max(stop, f.ema10c); }
      Object.assign(o, { mode: "held", stage, stop, gain });
    } else {
      Object.assign(o, { mode: "new", stop: s1, trigger: f.ema10c != null && P < f.ema10c ? f.ema10c : null });
    }
    o.wait = vd && vd.base === "WAIT FOR TREND (Pullback)";
    return o;
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

  // ---------- Yahoo fetch: own proxy (meta.proxy_url) -> direct -> free CORS proxies, each with a timeout ----------
  function chartUrl(sym, host) { return `https://${host}.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=5y&interval=1wk&includeAdjustedClose=true`; }
  function routes(q1, q2) {
    const r = [];
    if (M.proxy_url) r.push({ n: "g1-proxy", u: `${M.proxy_url.replace(/\/$/, "")}/?url=${encodeURIComponent(q1)}`, to: 10000 });
    r.push({ n: "direct", u: q1, to: 6000 });
    r.push({ n: "corsproxy.io", u: `https://corsproxy.io/?url=${encodeURIComponent(q1)}`, to: 12000 });
    r.push({ n: "codetabs", u: `https://api.codetabs.com/v1/proxy/?quest=${encodeURIComponent(q2)}`, to: 12000 });
    r.push({ n: "allorigins", u: `https://api.allorigins.win/raw?url=${encodeURIComponent(q2)}`, to: 15000 });
    r.push({ n: "allorigins-get", u: `https://api.allorigins.win/get?url=${encodeURIComponent(q1)}`, to: 15000, wrap: true });
    return r;
  }
  async function fetchChart(sym) {
    const s = sym.replace(".", "-"), rs = routes(chartUrl(s, "query1"), chartUrl(s, "query2"));
    const order = rs.map((_, i) => i); const k0 = Math.min(state.proxyIdx, rs.length - 1); order.splice(order.indexOf(k0), 1); order.unshift(k0);  // last route that worked goes first
    let lastErr;
    for (const i of order) {
      const rt = rs[i];
      try {
        const ctl = new AbortController(); const timer = setTimeout(() => ctl.abort(), rt.to);
        const res = await fetch(rt.u, { cache: "no-store", signal: ctl.signal }); clearTimeout(timer);
        if (!res.ok) throw new Error(String(res.status));
        let data = await res.json(); if (rt.wrap) data = JSON.parse(data.contents);
        const r = data?.chart?.result?.[0]; if (!r || !r.timestamp) throw new Error("no data");
        const q = r.indicators?.quote?.[0] || {};
        const adj = r.indicators?.adjclose?.[0]?.adjclose || q.close, cl = q.close || adj;
        const keys = [], a = [], c = [], hi = [], lo = [], vo = [];
        r.timestamp.forEach((ts, k) => { if (adj[k] != null && adj[k] > 0) { keys.push(new Date(ts * 1000).toISOString().slice(0, 10)); a.push(adj[k]); c.push(cl[k] ?? adj[k]); hi.push(q.high?.[k] ?? null); lo.push(q.low?.[k] ?? null); vo.push(q.volume?.[k] ?? null); } });
        state.proxyIdx = i; state.route = rt.n;
        return { meta: r.meta, keys, a, c, hi, lo, vo, route: rt.n };
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
    const n = c.vo.length;   // weekly climax inputs from Yahoo's real weekly high/low/volume
    if (n >= 53 && c.vo[n - 1] != null) { const pv = c.vo.slice(n - 53, n - 1).filter((x) => x != null).sort((x, y) => x - y); const med = pv.length ? pv[Math.floor(pv.length / 2)] : null; if (med > 0) f.wk_vol_x = c.vo[n - 1] / med; }
    if (n && c.hi[n - 1] != null && c.lo[n - 1] != null) f.wk_close_pos = c.hi[n - 1] > c.lo[n - 1] ? (c.c[n - 1] - c.lo[n - 1]) / (c.hi[n - 1] - c.lo[n - 1]) : 0.5;
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
  function loadPos() { try { const o = JSON.parse(localStorage.getItem(POS_KEY) || "{}"); return o && typeof o === "object" ? o : {}; } catch (_) { return {}; } }
  function savePos() { localStorage.setItem(POS_KEY, JSON.stringify(state.pos)); }
  function entryOf(t, csv) { if (csv > 0) return { v: csv, src: "csv" }; const p = state.pos[t]; return p && p.entry > 0 ? { v: p.entry, src: "browser" } : { v: null, src: null }; }
  function scoreColor(x) { const g = Math.max(-1, Math.min(1, (x - 5) / 3)); return g >= 0 ? `rgba(34,197,94,${0.12 + 0.45 * g})` : `rgba(239,68,68,${0.12 - 0.45 * g})`; }
  function g1Color(x) { const g = Math.max(-1, Math.min(1, (x - 50) / 35)); return g >= 0 ? `rgba(34,197,94,${0.15 + 0.5 * g})` : `rgba(239,68,68,${0.15 - 0.5 * g})`; }
  function bar(v, cls, tip) { const w = v == null ? 0 : Math.max(0, Math.min(100, v)); return `<div class="bar ${cls}" title="${esc(tip)}"><i style="width:${w}%"></i><span>${v == null ? "–" : Math.round(v)}</span></div>`; }
  function agree(pctv, ai) { if (ai == null || pctv == null) return null; const g = pctv >= 0.8 ? 1 : pctv <= 0.2 ? -1 : 0, d = ai >= 7 ? 1 : ai <= 4 ? -1 : 0; if (!g || !d) return "neutral"; return g === d ? "agree" : "disagree"; }
  function agreePill(a) { if (!a) return ""; return `<span class="ag ag-${a}" title="G1 in its top/bottom 20% vs Danelfin AI ≥7 bullish / ≤4 bearish">${{ agree: "Agree", disagree: "Disagree", neutral: "Neutral" }[a]}</span>`; }

  // full evaluation of a ticker (shipped or live)
  function evalTicker(t, csvEntry) {
    const L = state.live[t]; let f, m, live = false;
    if (L) { f = L.f; m = L.m; live = true; } else { const b = baseOf(t); if (!b) return null; f = b.f; m = b.m; }
    const sc = scoreTicker(t, f, m), en = entryOf(t, csvEntry);
    const vd = verdict(sc, f, en.v);
    const st = stops(f, en.v, vd); if (st) { st.px = f.px; st.cyc = !!(D.dossiers[t] && D.dossiers[t].flags && D.dossiers[t].flags.cyclical_peak); }
    return { t, f, m, sc, live, en, vd, kl: kelly(sc, f, t, vd), st, tg: targets(sc, f.px), sty: styleOf(f, m.fund) };
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
  function dfn3Of(t) { const b = danelfinOf()[t]; return (b && b.ai != null) ? b.ai : ((D.dfn3 && D.dfn3[t] != null) ? D.dfn3[t] : null); }
  function agree3mPair(gPct, ai) {
    if (gPct == null || ai == null) return null;
    return (gPct >= 0.5) === (ai >= 6);
  }
  function rowsForView() {
    if (state.view === "SP") return Object.keys(D.tmeta).filter((t) => D.tmeta[t][3] === 1).map((t) => ({ t }));
    if (state.view === "TOP") return D.finalists.map((t) => ({ t }));
    if (state.view === "RES") return state.research.map((r) => ({ t: r.t, research: true }));
    return bookRows(state.view.slice(2)).map((r) => ({ t: r.t, shares: r.shares, entry: r.entry, name: r.name }));
  }
  function renderTabs() { $("tabs").innerHTML = views().map(([k, l]) => `<button class="tab ${state.view === k ? "on" : ""}" data-v="${esc(k)}">${esc(l)}</button>`).join(""); }
  function renderWeather() {
    const w = weather(), W = M.weather;
    const expl = w.mode === "capit" ? "Deep sell-off with breadth recovering and credit spreads easing: historically a buying window."
      : w.mode === "bear" ? `S&P 500 below its 40-week average and only ${pct(W.breadth)} of large stocks above theirs. Bear Preservation: keep a ${pct(w.reserve)} T-bill reserve and pause new buys.`
      : w.regime === "on" ? "S&P 500 above its 40-week average and credit spreads calm."
      : w.regime === "neutral" ? "Mixed signals: trend and credit disagree."
      : "S&P 500 below its 40-week average or credit spreads wide.";
    $("weather").className = "banners";
    $("weather").innerHTML = `<div class="banner w-${w.mode}" title="Market Weather: S&amp;P 500 vs its 40-week average, plus the high-yield credit spread">
        <div class="bn-icon">${w.icon}</div><div><div class="bn-k">Market Weather</div><div class="bn-v">${esc(w.label)}</div><div class="small">${esc(expl)}</div>
        <div class="tiny muted">S&amp;P 500 ${usd(w.spy)} vs 40-week avg ${usd(w.sma)}${w.live ? " (live)" : ""} · high-yield spread ${W.hy != null ? W.hy.toFixed(2) + "%" : "–"} · breadth ${pct(W.breadth)} above 40-week avg</div></div></div>
      <div class="banner cash" title="Volatility-managed allocation: equity share = 0.14 ÷ the S&amp;P 500's downside volatility over the last year, kept between 50% and 100%">
        <div class="bn-icon">🛟</div><div><div class="bn-k">Cash plan</div><div class="bn-v">${pct(w.equity)} stocks · ${pct(1 - w.equity)} T-bills (SGOV)</div>
        <div class="alloc"><i style="width:${(100 * w.equity).toFixed(1)}%"></i></div>
        <div class="tiny muted">S&amp;P 500 downside volatility ${pct(W.spy_dvol, 1)} (1 year, daily) → volatility-managed equity ${pct(w.eqVM)}${w.reserve ? ` · Bear reserve ${pct(w.reserve)}` : ""} · model estimate, not advice</div></div></div>`;
  }
  function verdictPill(vd) { return `<span class="vd ${vd.cls}" title="${esc(vd.note + " Model estimate, not advice.")}">${esc(vd.v)}</span>`; }
  function udBars(sc) { return bar(sc.Up, "up", "Upside percentile (0–100) among the top 1,000 US stocks: growth, trend and value. Verdicts need 70+ for STRONG BUY, 65+ for WAIT.") + bar(sc.Sp, "safe", "Safety percentile (0–100) among the top 1,000 US stocks: low tail risk, strong balance sheet, quality. STRONG BUY needs 60+."); }
  function dossPill(sc) {
    if (sc.fstrat == null) return "";
    const v = sc.fstrat, c = v >= 3 ? "dp-pos" : v <= -3 ? "dp-neg" : "dp-mid";
    return `<span class="dpill ${c}" title="Business dossier overlay f_strat (−10…+10). Includes unvalidated analyst-style judgment from a web search; never added into the G1 Score.">Dossier ${v > 0 ? "+" : ""}${v}</span>`;
  }
  function hzHit(sc, h) {
    const b = sc && sc.bands && sc.bands[h];
    return b && b.hit != null && isFinite(b.hit) ? b.hit : null;
  }
  function hzEdge(sc, h) {
    const hit = hzHit(sc, h), br = M.base_rate && M.base_rate[h];
    return hit == null || br == null ? null : hit - br;
  }
  function invalidateEdgeCuts() { edgeCuts = null; }
  function getEdgeCuts() {
    if (edgeCuts) return edgeCuts;
    const cuts = {};
    const univ = Object.keys(D.tmeta).filter((t) => D.tmeta[t][1] === 1 && D.tmeta[t][5] === 1 && D.rows[t]);
    for (const h of HZ_STRIP) {
      const edges = [];
      for (const t of univ) {
        const m = tmeta(t), f = rowOf(t);
        if (!m || !f) continue;
        const sc = scoreTicker(t, f, m);
        const e = hzEdge(sc, h);
        if (e != null && isFinite(e)) edges.push(e);
      }
      edges.sort((a, b) => a - b);
      cuts[h] = edges;
    }
    edgeCuts = cuts;
    return cuts;
  }
  // 1–10 from the universe edge distribution. 10 = top 10% edge, 1 = bottom 10%.
  function hzAi(sc, h) {
    const e = hzEdge(sc, h);
    if (e == null) return null;
    const xs = getEdgeCuts()[h];
    if (!xs || !xs.length) return null;
    let below = 0, equal = 0;
    for (let i = 0; i < xs.length; i++) { if (xs[i] < e) below++; else if (xs[i] === e) equal++; else break; }
    const pct = (below + 0.5 * equal) / xs.length;
    return Math.min(10, Math.max(1, Math.floor(pct * 10) + 1));
  }
  function overallAi(sc) {
    let num = 0, den = 0;
    for (const h of HZ_STRIP) {
      const s = hzAi(sc, h);
      if (s == null) continue;
      const w = HZ_W[h] || 0;
      num += w * s; den += w;
    }
    if (!den) return null;
    return Math.min(10, Math.max(1, Math.round(num / den)));
  }
  function aiClass(s) { return s == null ? "" : s <= 3 ? "ai-lo" : s <= 6 ? "ai-mid" : "ai-hi"; }
  function pp(edge) {
    if (edge == null || !isFinite(edge)) return "";
    const n = Math.round(edge * 100);
    return `${n >= 0 ? "+" : ""}${n}`;
  }
  function hzSub(sc, h) {
    const hit = hzHit(sc, h), edge = hzEdge(sc, h);
    if (hit == null) return "–";
    const unval = h === 3 && M.v42_3m && M.v42_3m.unvalidated;
    const star = unval ? '<sup class="uv" title="Unvalidated: 3-month rank IC t is below 2.">*</sup>' : "";
    return `${pct(hit)}${star} <span class="hze">(${pp(edge)})</span>`;
  }
  function hzTips(h) {
    const unval = !!(M.v42_3m && M.v42_3m.unvalidated);
    const winner = (M.v42_3m && M.v42_3m.winner) || "V42";
    const tWin = M.v42_3m ? M.v42_3m.t_winner : null;
    const br = M.base_rate && M.base_rate[h];
    const usual = br != null ? ` Usual rate ${pct(br)}.` : "";
    if (h === 3) {
      return {
        g: "G1 3 mo: 1–10 rating of the edge over the usual chance of beating SPY (10 = top 10% edge in the universe), from a 3-month test of " + winner + usual + (unval ? ` Unvalidated: rank IC t ≈ ${tWin != null ? tWin.toFixed(2) : "?"} < 2.` : ""),
        d: "Danelfin AI Score (their 3-month 1–10 rating of a stock’s probability advantage over the average stock), from the uploaded portfolio CSV.",
        dmiss: "No Danelfin data"
      };
    }
    return { g: `G1 ${HZ_HEAD(h)}: 1–10 rating of the edge over the usual chance of beating SPY (10 = top 10% edge).${usual}` };
  }
  function aiBox(s, extraCls, tip) {
    if (s == null) return `<span class="aiscore muted">–</span>`;
    return `<span class="aiscore ${aiClass(s)} ${extraCls || ""}" title="${esc(tip || "")}">${s}</span>`;
  }
  function hz3Inner(sc, t) {
    const s = hzAi(sc, 3), df = P.danelfin ? dfn3Of(t) : null, tips = hzTips(3);
    const dfBox = !P.danelfin ? "" : (df == null
      ? `<span class="hzdfcol" title="${esc(tips.dmiss)}"><span class="aiscore muted">n/a</span><span class="dflbl">DF</span></span>`
      : `<span class="hzdfcol" title="${esc(tips.d)}">${aiBox(df)}<span class="dflbl">DF</span></span>`);
    return `<div class="hz3cmp">${aiBox(s, "g1ai", tips.g)}${dfBox}</div><div class="hzpct">${hzSub(sc, 3)}</div>`;
  }
  function hzInner(sc, t, h) {
    if (h === 3) return hz3Inner(sc, t);
    const s = hzAi(sc, h), tips = hzTips(h);
    return `${aiBox(s, "", tips.g)}<div class="hzpct">${hzSub(sc, h)}</div>`;
  }
  function overallInner(sc) {
    const s = overallAi(sc);
    return `${aiBox(s, "", HZ_W_TIP)}<div class="hzpct muted" title="${esc(HZ_W_TIP)}">Overall</div>`;
  }
  function hzTds(sc, t) {
    const ov = `<td class="hzcell hzov" data-l="G1 Overall" data-hz="ov">${overallInner(sc)}</td>`;
    return ov + HZ_STRIP.map((h) => `<td class="hzcell${h === 3 ? " hz3" : ""}" data-l="${esc(HZ_HEAD(h))}" data-hz="${h}">${hzInner(sc, t, h)}</td>`).join("");
  }
  function hzBoard(sc, t) {
    const ov = `<div class="hzcol hzov"><div class="hzh">G1 Overall</div><div class="hzv">${overallInner(sc)}</div></div>`;
    const cols = HZ_STRIP.map((h) => `<div class="hzcol${h === 3 ? " hz3" : ""}"><div class="hzh">${esc(HZ_HEAD(h))}${usualLine(h)}</div><div class="hzv">${hzInner(sc, t, h)}</div></div>`).join("");
    return `<div class="hzboard" role="group" aria-label="Chance of beating S&amp;P 500">${ov}${cols}</div>`;
  }
  function usualLine(h) {
    const br = M.base_rate && M.base_rate[h];
    return br != null ? `<span class="usual">usual ${pct(br)}</span>` : "";
  }
  function usualTip(h) {
    const br = M.base_rate && M.base_rate[h];
    return br != null ? ` Usual chance of beating the S&amp;P 500: ${pct(br)}.` : "";
  }
  function g1Cell(sc) {
    const tip = sc.kind === "price" ? "Price-only score (no SEC fundamentals): momentum, drawdown and tail risk" : M.live === "V42" ? "G1 Quant Score (v4.2, passed its pre-registered test): percentile among the top 1,000 US stocks" : "G1 composite percentile (validated live score)";
    return `<div class="scorecell"><span class="g1" style="background:${g1Color(sc.g1)}" title="${esc(tip)}">${Math.round(sc.g1)}</span>${sc.kind === "price" ? '<span class="tiny muted">price-only</span>' : ""}</div>`;
  }
  function oddsCell(e) {
    const k = e.kl, ed = k.p - k.base;
    return `<div title="Chance to beat the S&amp;P 500 over 12 months, from how similar-scoring stocks did out of sample, vs the usual (base) rate"><b class="${ed >= 0.03 ? "pos" : ed <= -0.03 ? "neg" : ""}">${pct(k.p)}</b> <span class="muted small">vs ${pct(k.base)} usual (${ed >= 0 ? "+" : "−"}${Math.abs(ed * 100).toFixed(0)}% edge)</span></div>
      <div class="small muted" title="12-month Bear · Base · Bull price (10th / 50th / 90th percentile of similar stocks, flat S&amp;P 500)">${e.tg ? `${usd(e.tg.bear)} · <b class="txt">${usd(e.tg.base)}</b> · ${usd(e.tg.bull)}` : "–"}</div>`;
  }
  function sizeCell(e) {
    const k = e.kl;
    return `<div title="Conviction size from the edge over the usual odds divided by downside volatility. ${esc(k.why.join("; ") || "")} Model estimate, not advice."><b>${k.k > 0 ? pct(k.k, 1) : "0%"}</b><div class="tiny muted">${esc(k.tier)}${k.why.length ? " · ½" : ""}${k.soon ? " ⏰" : ""}</div></div>`;
  }
  function stockCell(e, r, dan) {
    const nm = r.name || e.m.name || "";
    const d = dan[e.t]; const ag = d ? agree(e.sc.pct, d.ai) : null;
    const chips = [];
    if (P.danelfin && d && d.ai != null) chips.push(`<span class="chip" title="Danelfin AI Score (uploaded CSV)">Danelfin ${d.ai}</span>${agreePill(ag)}`);
    if (e.sty) chips.push(`<span class="chip" style="background:${scoreColor(e.sty.bm)}" title="Buffett &amp; Munger 0–10 (rule-based proxy)">B&amp;M ${e.sty.bm.toFixed(1)}</span><span class="chip" style="background:${scoreColor(e.sty.m15)}" title="${esc(MAGIC_NAME)} 0–10 (lean; rule-based proxy)">M15 ${e.sty.m15.toFixed(1)}</span>`);
    const doss = dossPill(e.sc);
    if (doss) chips.push(doss);
    return `<b>${esc(e.t)}</b>${e.live ? ' <span class="live">live</span>' : ""}<span class="nm">${esc(nm)}</span><div class="chips">${chips.join("")}</div>`;
  }
  function stopText(st) {
    if (!st) return "–";
    const L = [];
    if (st.mode === "held") {
      const lbl = { 1: "Stage 1: 40-week avg / bad-week risk", 2: "Stage 2: breakeven (after +20%)", 3: "Stage 3: 10-week EMA trail (after +40%)" }[st.stage];
      L.push(st.stop == null ? `<span class="muted">Trailing stop: n/a until +20% (not enough clean price history for a risk stop)</span>` : `<b>Trailing stop ${usd(st.stop)}</b> <span class="muted">${lbl} · entry ${usd(st.entry)} (${sgn(st.gain)})</span>`);
      if (st.trendBroken) L.push(`<span class="neg">Price is below its 40-week average (${usd(st.sma)}): the trend stop has been crossed.</span>`);
    } else {
      if (st.stop == null) L.push(`<span class="muted">Initial risk stop: n/a (not enough clean price history)</span>`); else L.push(`<b>Initial risk stop ${usd(st.stop)}</b> <span class="muted">${st.trendBroken ? "a typical bad week below today (the 40-week avg is above the price)" : "40-week avg or a typical bad week, whichever is higher"}</span>`);
      if (st.trigger) L.push(`Momentum reclaim trigger: <b>buy on a reclaim of ${usd(st.trigger)}</b> (10-week EMA)`);
      const cyc = st.cyc ? ` <span class="neg">· based on possibly peak-cycle earnings: unreliable</span>` : "";
      if (st.dv && st.dv < st.px) L.push(`Deep-Value zone: <b>${usd(st.dv)}</b> <span class="muted">(price where EV/EBIT equals its 5-year median)</span>${cyc}`);
      else if (st.dv) L.push(`<span class="muted">Deep-Value zone: already below it (EV/EBIT under its 5-year median; that price is ${usd(st.dv)})</span>${cyc}`);
      else if (st.wait) L.push(`<span class="muted">Deep-Value zone: n/a (needs positive EBIT and 5 years of history)</span>`);
      L.push(`<span class="muted">Add your Entry $ to switch on the breakeven (+20%) and 10-week EMA (+40%) stages.</span>`);
    }
    return L.map((x) => `<div>${x}</div>`).join("");
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
    const dz = D.dossiers[e.t]; if (dz?.flags?.cyclical_peak) bad.push("dossier: earnings look like a cyclical peak"); if (dz?.flags?.ai_threat) bad.push("dossier: " + dz.flags.ai_threat);
    return { good, bad };
  }
  function dossierBlock(t) {
    const d = D.dossiers[t];
    if (!d) return `<div class="muted small">No business dossier for this name (built for holdings and the G1 Top 30 on request).</div>`;
    const lbl = { moat: "Moat vs disruption", hidden_stakes: "Hidden stakes / SOTP", ai_threat: "AI / agentic moat threat", cyclical: "Cyclical-peak penalty", pricing: "Pricing power & backlog", variant: "Variant perception gap" };
    const sc = Object.entries(d.scores || {}).map(([k, v]) => `<li>${esc(lbl[k] || k)}: <b>${v > 0 ? "+" : ""}${v}</b>${(d.thin || []).includes(k) ? ' <span class="muted">(thin evidence, 0)</span>' : ""}</li>`).join("");
    const flags = [d.flags?.cyclical_peak ? "⚠️ cyclical peak" : "", d.flags?.hidden_sotp ? `💎 ${esc(d.flags.hidden_sotp)}` : "", d.flags?.ai_threat ? `🤖 ${esc(d.flags.ai_threat)}` : ""].filter(Boolean).map((x) => `<span class="chip">${x}</span>`).join(" ");
    const src = (d.sources || []).slice(0, 6).map((x, i) => `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title || "source " + (i + 1))}</a>`).join(" · ");
    return `<div class="doss"><div><b>Business dossier</b> ${dossPill({ fstrat: d.f_strat })} <span class="tiny muted">built ${esc(d.built)} · ${esc(d.method || "")} · includes unvalidated analyst-style judgment</span></div>
      ${flags ? `<div class="chips">${flags}</div>` : ""}
      <div class="dgrid small"><div><b class="pos">Bull case</b><div>${esc(d.bull_case)}</div></div><div><b class="neg">Bear case</b><div>${esc(d.bear_case)}</div></div></div>
      <div class="dgrid small"><div><ul>${sc}</ul></div><div>${d.note ? `<div><b>Gary's note:</b> ${esc(d.note)}</div>` : ""}${d.thin_all ? '<div class="muted">Evidence thin: scored 0.</div>' : ""}</div></div>
      <div class="tiny muted">Sources: ${src || "–"}</div></div>`;
  }
  function detailHtml(e, r) {
    const sc = e.sc, dan = danelfinOf()[e.t];
    const strip = hzBoard(sc, e.t);
    const { good, bad } = strengthsFlags(e);
    const dsub = P.danelfin && dan ? `<div class="small">Danelfin (uploaded CSV): AI ${dan.ai ?? "–"} · Fundamental ${dan.fund ?? "–"} · Technical ${dan.tech ?? "–"} · Sentiment ${dan.sent ?? "–"} · Low Risk ${dan.lowrisk ?? "–"} ${agreePill(agree(sc.pct, dan.ai))}</div>` : "";
    const sty = e.sty ? `<div class="dgrid small"><div><b>Buffett &amp; Munger ${e.sty.bm.toFixed(1)}/10</b>${sc.v42?.gated ? ' <span class="muted">(below 4: G1 Score capped at 65)</span>' : ""}<ul>${Object.entries(e.sty.bm_st).map(([k, v]) => `<li>${esc(BM_LBL[k])}: <b>${v}</b>/${BM_MAX[k]}</li>`).join("")}</ul></div>
      <div><b>${esc(MAGIC_NAME)} ${e.sty.m15.toFixed(1)}/10</b> <span class="muted">(${esc(M.magic.sub)})</span><ul>${Object.entries(e.sty.m15p).map(([k, v]) => `<li>${esc(M.magic.labels[k])}: <b>${(v * 10).toFixed(1)}</b>/10</li>`).join("")}</ul></div></div>` : "";
    const pil = sc.v42 ? `<div class="small"><b>G1 Score pillars</b> (percentiles): Buffett &amp; Munger ${Math.round(100 * sc.v42.P1)} · Magic 15 ${Math.round(100 * sc.v42.P2)} · Cyclically-adjusted value ${Math.round(100 * sc.v42.P3)} · Trend &amp; defense ${Math.round(100 * sc.v42.P4)}</div>` : "";
    const held = r && (r.shares !== undefined || r.research !== undefined || r.entryUI);
    const entryUI = held ? `<div class="entry"><label>Entry $ <input type="number" step="0.01" min="0" inputmode="decimal" data-entry="${esc(e.t)}" value="${e.en.src === "browser" ? e.en.v : ""}" placeholder="${e.en.src === "csv" ? "from CSV" : "your buy price"}" ${e.en.src === "csv" ? "disabled" : ""}></label> <span class="tiny muted">${e.en.src === "csv" ? "from the portfolio CSV" : "saved only in this browser (g1.positions.v1)"}</span></div>` : "";
    return `<div class="dgrid">
        <div><b>Strengths</b><ul class="small">${good.map((x) => `<li>${esc(x)}</li>`).join("") || "<li class='muted'>none stand out</li>"}</ul><b>Red flags</b><ul class="small">${bad.map((x) => `<li>${esc(x)}</li>`).join("") || "<li class='muted'>none flagged</li>"}</ul>${pil}</div>
        <div><div class="small"><b>${esc(e.vd.v)}</b>: ${esc(e.vd.note)}</div>
          ${entryUI}
          <div class="small stops">${stopText(e.st)}</div>
          <div class="small">Size: <b>${e.kl.k > 0 ? pct(e.kl.k, 1) : "0%"}</b> (${esc(e.kl.tier)}; edge ${sgn(e.kl.edge)} ÷ downside vol ${pct(e.f.sigma_down)})${e.kl.why.length ? " · " + esc(e.kl.why.join("; ")) : ""}${e.kl.earn ? ` · next results ~${esc(e.kl.earn)} (est.)` : ""}</div>
          <div class="small">12-month targets: Bear ${usd(e.tg?.bear)} · Base <b>${usd(e.tg?.base)}</b> · Bull ${usd(e.tg?.bull)}</div>
          <div><b class="small">Chance to beat the S&amp;P 500</b><div class="hzrow">${strip}</div></div>
          <div class="tiny muted">Model estimates, not advice. Verdict, stop and size rules are simple UI rules, not backtested.</div></div>
      </div>${dsub}${sty}${dossierBlock(e.t)}`;
  }
  function bookWeights(rows) {   // current weights by value (needs share counts) vs equal-weight targets
    const val = {}; rows.forEach((r) => { const e = r.e || evalTicker(r.t, r.entry); const px = e?.f?.px; val[r.t] = { v: r.shares > 0 && px > 0 ? r.shares * px : null, sector: e?.m?.sector || "Other" }; });
    const priced = rows.filter((r) => val[r.t].v != null), tot = priced.reduce((a, r) => a + val[r.t].v, 0);
    const out = { val, useShares: priced.length === rows.length && tot > 0, drift: {} };
    if (out.useShares) { const tgt = 1 / priced.length; priced.forEach((r) => { const w = val[r.t].v / tot; out.drift[r.t] = { w, tgt, d: w / tgt - 1 }; }); }
    return out;
  }
  function renderHealth() {
    const el = $("health");
    if (!state.view || !state.view.startsWith("B:")) { el.innerHTML = ""; el.hidden = true; return; }
    const rows = bookRows(state.view.slice(2)); const warn = [];
    const bw = bookWeights(rows), val = bw.val; let tot = 0;
    const bySec = {}; rows.forEach((r) => { const w = bw.useShares ? val[r.t].v : 1; tot += w; bySec[val[r.t].sector] = (bySec[val[r.t].sector] || 0) + w; });
    Object.entries(bySec).forEach(([s, w]) => { if (tot > 0 && w / tot > 0.35) warn.push(`${s} is ${pct(w / tot)} of this book (over 35%). Check diversification.`); });
    const ts = rows.map((r) => r.t).filter((t) => D.w53[t]);
    const ret = {}; ts.forEach((t) => { const a = D.w53[t]; ret[t] = a.slice(1).map((x, i) => (x != null && a[i] != null ? x / a[i] - 1 : null)); });
    const pairs = [];
    for (let i = 0; i < ts.length; i++) for (let j = i + 1; j < ts.length; j++) {
      const x = [], y = []; ret[ts[i]].forEach((v, k) => { const w = ret[ts[j]][k]; if (v != null && w != null) { x.push(v); y.push(w); } });
      if (x.length < 40) continue;
      const mx = mean(x), my = mean(y); let c = 0, vx = 0, vy = 0; x.forEach((v, k) => { c += (v - mx) * (y[k] - my); vx += (v - mx) ** 2; vy += (y[k] - my) ** 2; });
      const rho = c / Math.sqrt(vx * vy); if (rho > 0.8) pairs.push([ts[i], ts[j], rho]);
    }
    pairs.sort((a, b) => b[2] - a[2]).forEach(([a, b, r]) => warn.push(`${a} and ${b} move almost identically (correlation ${r.toFixed(2)}). Check diversification.`));
    Object.entries(bw.drift).forEach(([t, d]) => { if (Math.abs(d.d) > 0.25) warn.push(`Rebalance: ${t} is ${pct(d.w, 1)} of the book vs a ${pct(d.tgt, 1)} equal-weight target (${sgn(d.d)} drift).`); });
    const sec = Object.entries(bySec).sort((a, b) => b[1] - a[1]).map(([s, w]) => `<span class="chip">${esc(s)} ${pct(w / tot)}</span>`).join(" ");
    el.hidden = false;
    el.innerHTML = `<div class="hh"><b>Portfolio health</b> <span class="tiny muted">${bw.useShares ? "weights by value; rebalance alert when a holding drifts more than 25% from equal weight" : "equal weights (the CSV has no share counts, so rebalance alerts are off)"} · 52-week correlations</span></div><div class="chips">${sec}</div>` +
      (warn.length ? warn.map((w) => `<div class="hwarn">⚠️ ${esc(w)}</div>`).join("") : `<div class="small pos">No sector above 35%, no pair above 0.80 correlation${bw.useShares ? ", no weight drift above 25%" : ""}.</div>`);
  }
  const VORDER = ["SELL / BROKEN", "CLIMAX TRIM", "HOLD", "WAIT FOR TREND (Pullback)", "ACCUMULATE (Staggered)", "STRONG BUY"];
  function renderTable() {
    const dan = danelfinOf(), isRes = state.view === "RES";
    let rows = rowsForView().map((r) => Object.assign(r, { e: evalTicker(r.t, r.entry) }));
    const fl = state.filter.trim().toUpperCase();
    if (fl) rows = rows.filter((r) => r.t.includes(fl) || String(r.name || r.e?.m?.name || "").toUpperCase().includes(fl));
    const val = (r) => {
      const e = r.e; if (!e) return -1;
      if (state.sortKey === "ov") { const n = overallAi(e.sc); return n == null ? -1 : n; }
      if (String(state.sortKey).startsWith("hz")) { const n = hzAi(e.sc, +state.sortKey.slice(2)); return n == null ? -1 : n; }
      switch (state.sortKey) { case "t": return r.t; case "vd": return VORDER.findIndex((x) => e.vd.base === x) * 1000 + e.sc.g1; case "ud": return e.sc.Up; case "odds": return e.kl.p; case "kelly": return e.kl.k; default: return e.sc.g1; }
    };
    rows.sort((a, b) => { const x = val(a), y = val(b); return (x < y ? -1 : x > y ? 1 : 0) * state.sortDir; });
    const mark = (k) => (state.sortKey === k ? (state.sortDir < 0 ? " ▾" : " ▴") : "");
    const th = (k, l, tip, rs) => `<th data-k="${k}"${rs ? ' rowspan="2"' : ""} title="${esc(tip || "")}">${l}${mark(k)}</th>`;
    const hzTip = (h) => (h === 3
      ? "3 mo: G1 1–10 edge score (10 = top 10% edge) and Danelfin’s 1–10 AI Score. Underneath: G1 chance of beating the S&P 500 and the edge in points. * = unvalidated."
      : `G1 ${HZ_HEAD(h)}: 1–10 edge score (10 = top 10% edge) and the chance of beating the S&P 500, with the edge in points.`) + usualTip(h);
    const ncols = NCOL + (isRes ? 1 : 0);
    const hzSubHeads = [th("ov", "G1 Overall", HZ_W_TIP)].concat(HZ_STRIP.map((h) => `<th data-k="hz${h}" title="${esc(hzTip(h))}">${esc(HZ_HEAD(h))}${mark("hz" + h)}${usualLine(h)}</th>`)).join("");
    let html = `<table class="main"><thead><tr>${th("t", "Stock", "", true)}${th("vd", "Verdict", "Action verdict: a simple rule combining the business score with the price trend. Model estimate, not advice.", true)}${th("score", "G1 Score", "0–100 validated quant score (percentile among the top 1,000 US stocks).", true)}<th class="hzgroup" colspan="${HZ_STRIP.length + 1}">Chance of beating S&amp;P 500</th>${th("ud", "Upside · Safety", "Descriptive 0–100 axes used by the verdict rules", true)}${th("odds", "1-yr odds · $ range", "Chance to beat the S&P 500 over 12 months vs the usual rate, and Bear · Base · Bull price", true)}${th("kelly", "Size", "Conviction size: edge over the usual odds ÷ downside volatility. Halved while waiting for trend or before earnings.", true)}${isRes ? '<th rowspan="2"></th>' : ""}</tr><tr class="hzsub">${hzSubHeads}</tr></thead><tbody>`;
    for (const r of rows) {
      const e = r.e, open = state.open.has(r.t);
      if (!e) { html += `<tr data-x="${esc(r.t)}"><td data-l="Stock"><b>${esc(r.t)}</b></td><td colspan="${ncols - 1 - (isRes ? 1 : 0)}" class="muted">Not in the bundled universe. Look it up above for a live price-only read.</td>${isRes ? `<td><button class="ghost" data-unpin="${esc(r.t)}">Remove</button></td>` : ""}</tr>`; continue; }
      html += `<tr class="${open ? "open" : ""}" data-x="${esc(r.t)}"><td data-l="Stock">${stockCell(e, r, dan)}</td><td data-l="Verdict">${verdictPill(e.vd)}</td><td data-l="G1 Score">${g1Cell(e.sc)}</td>${hzTds(e.sc, e.t)}<td data-l="Upside · Safety">${udBars(e.sc)}</td><td data-l="1-yr odds">${oddsCell(e)}</td><td data-l="Size">${sizeCell(e)}</td>${isRes ? `<td><button class="ghost" data-unpin="${esc(r.t)}">Remove</button></td>` : ""}</tr>`;
      if (open) html += `<tr class="det"><td colspan="${ncols}">${detailHtml(e, r)}</td></tr>`;
    }
    html += "</tbody></table>";
    if (!rows.length) html = `<div class="card muted">${isRes ? "Nothing pinned yet. Look up a ticker above and press Pin to Watchlist." : "No rows."}</div>`;
    const uv = M.v42_3m && M.v42_3m.unvalidated;
    const legend = `<p class="hzleg small">1–10 is G1’s edge vs the usual chance of beating the S&amp;P 500 (10 = top 10% edge). The % is that chance, with the edge in points.${P.danelfin ? " 3 mo also shows Danelfin’s 1–10 AI Score." : ""} G1 Overall blends the horizons (see its tooltip).${uv ? " * = 3 mo G1 is unvalidated (t &lt; 2)." : ""} Model estimates, not advice.</p>`;
    let agreeLine = "";
    if (P.danelfin) {
      let n = 0, ag = 0;
      for (const r of rows) {
        const e = r.e; if (!e) continue;
        const g = hzAi(e.sc, 3), df = dfn3Of(r.t);
        if (g == null || df == null) continue;
        n++; if ((g >= 6) === (df >= 6)) ag++;
      }
      if (n) agreeLine = `<p class="hzagr small">G1 3 mo and Danelfin 3 mo agreed on ${ag}/${n} names (${Math.round(100 * ag / n)}%) in this list (same half: both ≥ 6 or both ≤ 5).</p>`;
    }
    $("tbl").innerHTML = legend + agreeLine + html;
    const cnt = {}; rows.forEach((r) => { if (r.e) cnt[r.e.vd.base] = (cnt[r.e.vd.base] || 0) + 1; });
    $("count").innerHTML = `${rows.length} stocks · ` + VORDER.slice().reverse().filter((v) => cnt[v]).map((v) => `<span class="vd ${VCLS[v]} mini">${esc(v.replace(/ \(.*/, ""))} ${cnt[v]}</span>`).join(" ") + ` <span class="tiny muted">· tap a row for details</span>`;
    renderHealth();
  }
  function renderStatus() { $("asof").textContent = `Prices as of ${M.price_asof}` + (state.refreshedAt ? ` · live refresh ${laTime(state.refreshedAt)}` : "") + ` · model built ${M.built}`; }
  function renderBacktest() {
    const v = M.v42, ps = M.v42_pass, f = (x) => `${x.ic.toFixed(3)} <span class="muted">(t≈${x.t.toFixed(1)})</span>`;
    const rowsOf = (lab) => HZ.map((h) => { const r = v[h][lab]; return `<tr><td>${h}m</td>${["V42", "A"].map((m) => `<td>${f(r[m])}<br><span class="tiny muted">top-decile p10 ${sgn(r[m].p10)} · top−bottom ${sgn(r[m].tmb)}</span></td>`).join("")}</tr>`; }).join("");
    const head = `<tr><th>Horizon</th><th>G1 v4.2</th><th>v2 composite A</th></tr>`;
    const m3 = M.v42_3m;
    const line3 = m3 ? `<p class="small">3-month add-on (docs/PREREGISTRATION_V4_2_3M.md, committed before any 3m result): V42 rank IC ${m3.ic_V42.toFixed(3)} (t≈${m3.t_winner.toFixed(2)}) vs A ${m3.ic_A.toFixed(3)} (t≈${m3.primary.A.t.toFixed(2)}). Winner for the 3m G1 cell: <b>${m3.winner}</b>${m3.unvalidated ? " (unvalidated: t &lt; 2; the cell is marked and does not change the live headline score)" : ""}.</p>` : "";
    $("bt").innerHTML = `<p class="small">Pre-registered test (docs/PREREGISTRATION_V4_2.md, committed before any result): top 1,000 US stocks, month-ends from 2014, no fitted parameters. v4.2 = equal blend of Buffett &amp; Munger, lean Magic 15, cyclically-adjusted value (5-year median EBIT/EV and FCF/EV, within sector) and trend &amp; defense (12-1 month momentum within sector, low downside beta), capped at the 65th percentile when Buffett &amp; Munger is below 4. Result: <b>${ps.PASS ? "PASS: v4.2 is the live G1 Score" : "FAIL: composite A stays live"}</b> (rank IC beats A at ${ps.ic_wins}/6 horizons; turnover with a 15%/35% hold buffer ${M.v42_turnover.hyst.V42.toFixed(3)} vs ${M.v42_turnover.hyst.A.toFixed(3)} a month, ratio ${ps.turnover_ratio.toFixed(2)} ≤ 1.2).</p>${line3}
      <p class="small"><b>Caveat:</b> v4.2 ranks the whole list better and its top decile has milder bad outcomes, but its top-minus-bottom decile spread is much smaller than the composite's. Read the score as a broad ranking plus downside filter rather than a "buy only the top 10%" signal.</p>
      <div class="tblwrap"><table>${head}${rowsOf("primary")}</table></div>
      <details><summary class="small">Same test without the haircut and turnover drag</summary><div class="tblwrap"><table>${head}${rowsOf("raw")}</table></div></details>
      <details><summary class="small">Earlier v4 test (failed)</summary><p class="small">The v4 five-sleeve engine (S_quant) beat A's rank IC at ${M.v4_pass.a_ic_wins}/6 horizons and churned about 3× as much; it was not deployed. Its Upside and Safety axes are still shown as descriptive inputs to the verdict rules.</p></details>`;
  }
  // ---------- look-up report card ----------
  async function doSearch() {
    const t = $("q").value.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, "").replace("-", ".");
    if (!t) return;
    const out = $("searchOut");
    const show = (e, note) => {
      const pinned = state.research.some((x) => x.t === t);
      const dan = danelfinOf()[t];
      out.innerHTML = `<div class="card report"><div class="rhead"><div><span class="rt">${esc(t)}</span> <span class="muted">${esc(e.m.name || "")}</span><div class="small"><b class="txt">${usd(e.f.px)}</b> <span class="muted">${esc(note || "")}</span></div></div>
        <div class="row"><button id="pinBtn">${pinned ? "Pinned ✓" : "☆ Pin to Watchlist"}</button><button class="ghost" id="closeRep" title="Close">✕</button></div></div>
        <div class="rgrid"><div class="kv"><div class="tiny muted">G1 Score</div>${g1Cell(e.sc)}${dossPill(e.sc)}</div><div class="kv"><div class="tiny muted">Verdict</div>${verdictPill(e.vd)}</div><div class="kv"><div class="tiny muted">Upside · Safety</div>${udBars(e.sc)}</div>
        <div class="kv"><div class="tiny muted">1-yr odds · $ range</div>${oddsCell(e)}</div><div class="kv"><div class="tiny muted">Size</div>${sizeCell(e)}</div>${P.danelfin && dan ? `<div class="kv"><div class="tiny muted">Danelfin</div><b>${dan.ai ?? "–"}</b> ${agreePill(agree(e.sc.pct, dan.ai))}</div>` : ""}</div>
        ${hzBoard(e.sc, t)}
        ${detailHtml(e, { t, entryUI: true })}</div>`;
      $("pinBtn").onclick = () => { if (!state.research.some((x) => x.t === t)) { state.research.push({ t, name: e.m.name || "", at: new Date().toISOString() }); saveResearch(); } $("pinBtn").textContent = "Pinned ✓"; if (state.view === "RES") renderTable(); };
      $("closeRep").onclick = () => (out.innerHTML = "");
    };
    state.lastLookup = { t, show };
    const shipped = D.rows[t] ? evalTicker(t, null) : null;   // aliases wait for their own live price
    if (shipped) show(shipped, `price as of ${M.price_asof}; fetching live price…`); else out.innerHTML = `<div class="card muted">Fetching ${esc(t)} from Yahoo…</div>`;
    try {
      const r = await liveScore(t); state.live[t] = { f: r.f, m: r.m, at: r.at };
      const e = evalTicker(t, null);
      show(e, (D.rows[t] ? "live price" : M.alias[t] ? `live price; fundamentals from share class ${M.alias[t]}` : "live price-only read (no bundled SEC data)") + ` · via ${r.chart.route}`);
    } catch (err) {
      if (!shipped) out.innerHTML = `<div class="card err">Could not fetch ${esc(t)} (${esc(err.message)}). Yahoo and the free proxies may be blocking requests; try again shortly.</div>`;
      else show(shipped, `price as of ${M.price_asof} (live fetch failed)`);
    }
  }
  // ---------- refresh ----------
  async function refresh() {
    if (state.busy) return; state.busy = true; $("refresh").disabled = true;
    const tickers = [...new Set(rowsForView().map((r) => r.t))];
    let ok = 0, done = 0; const failed = [];
    $("refStatus").textContent = `Refreshing ${tickers.length} names from Yahoo${M.proxy_url ? " (own proxy first)" : ""}…` + (tickers.length > 60 ? " (large list through a free proxy: this can take 10+ minutes; keep the tab open)" : "");
    state.spyW = null; await getSpy(); renderWeather();
    const queue = tickers.slice();
    async function worker() {
      while (queue.length) {
        const t = queue.shift();
        try { let r = null; try { r = await liveScore(t); } catch (_) { r = await liveScore(t); } state.live[t] = { f: r.f, m: r.m, at: r.at }; ok++; } catch (_) { failed.push(t); }
        done++; if (done % 10 === 0 || done === tickers.length) $("refStatus").textContent = `Refreshed ${done}/${tickers.length}…`;
      }
    }
    await Promise.all(Array.from({ length: M.proxy_url ? 6 : 3 }, worker));   // free proxies rate-limit: fewer parallel requests
    if (failed.length) {   // one slower retry pass for names the free proxies dropped
      $("refStatus").textContent = `Retrying ${failed.length} names…`; await new Promise((r) => setTimeout(r, 2000));
      queue.push(...failed.splice(0)); done -= queue.length;
      await Promise.all(Array.from({ length: 2 }, worker));
    }
    state.refreshedAt = new Date(); state.busy = false; $("refresh").disabled = false;
    $("refStatus").textContent = `Live: ${ok}/${tickers.length} updated ${laTime(state.refreshedAt)}` + (state.spyW.shipped ? " (SPY from bundled history)" : "") + (state.route ? ` · via ${state.route}` : "") + (failed.length ? ` · failed: ${failed.slice(0, 12).join(", ")}${failed.length > 12 ? "…" : ""} (bundled scores kept)` : "");
    invalidateEdgeCuts(); renderStatus(); renderWeather(); renderTable();
  }

  // ---------- wire up ----------
  document.addEventListener("click", (e) => {
    const v = e.target.closest("[data-v]"); if (v) { state.view = v.dataset.v; renderTabs(); renderTable(); return; }
    const k = e.target.closest("th[data-k]"); if (k) { if (state.sortKey === k.dataset.k) state.sortDir *= -1; else { state.sortKey = k.dataset.k; state.sortDir = k.dataset.k === "t" ? 1 : -1; } renderTable(); return; }
    const u = e.target.closest("[data-unpin]"); if (u) { state.research = state.research.filter((x) => x.t !== u.dataset.unpin); saveResearch(); renderTable(); return; }
    if (e.target.closest("a, input, label, button")) return;
    const x = e.target.closest("tr[data-x]"); if (x) { const t = x.dataset.x; state.open.has(t) ? state.open.delete(t) : state.open.add(t); renderTable(); }
  });
  state.view = views()[P.show_sp500 ? 2 : 1]?.[0] || views()[0][0];
  if (!Object.keys(D.books).length) state.view = "TOP";
  document.addEventListener("change", (e) => {
    const inp = e.target.closest("input[data-entry]"); if (!inp) return;
    const t = inp.dataset.entry, v = parseFloat(inp.value);
    if (v > 0) state.pos[t] = { entry: v, at: new Date().toISOString() }; else delete state.pos[t];
    savePos(); renderTable();
    if (state.lastLookup && state.lastLookup.t === t) { const ev = evalTicker(t, null); if (ev) state.lastLookup.show(ev, "entry saved in this browser"); }
  });
  $("refresh").onclick = refresh; $("go").onclick = doSearch;
  $("q").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
  $("helpT").onclick = (e) => { e.preventDefault(); $("help").hidden = !$("help").hidden; };
  $("refStatus").textContent = "Scores use prices shipped at build. Refresh pulls live prices and re-scores in your browser.";
  $("flt").addEventListener("input", (e) => { state.filter = e.target.value; renderTable(); });
  renderWeather(); renderTabs(); renderStatus(); renderTable(); renderBacktest();
  // for local verification only
  window.G1 = { qpct, rawScores, scoreTicker, v42Of, verdict, kelly, stops, deepValue, priceFeatures, reprice, classify, weather, evalTicker, rowOf, tmeta, D, state, hzAi, overallAi, hzHit, hzEdge };
})();
