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
    research: loadResearch(), open: new Set(),
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
  function bmParts(y) { return y.bm_st.fcf_vs_treasury != null ? y.bm_st : Object.assign({}, y.bm_st, { fcf_vs_treasury: y.bm_fcf }); }
  function bmBox(y) {
    if (!y) return `<span class="muted" title="Needs SEC fundamentals">—</span>`;
    const tip = Object.entries(bmParts(y)).map(([k, v]) => `${BM_LBL[k]}: ${v}/${BM_MAX[k]}`).join("\n") + `\n(10y Treasury ${(D.meta.tsy * 100).toFixed(2)}%; missing data = half points)\nRule-based proxy, not Buffett's or Munger's view.`;
    return `<span class="sty" style="background:${scoreColor(y.bm)}" title="${esc(tip)}">${y.bm.toFixed(1)}</span>`;
  }
  function m15Box(y) {
    if (!y) return `<span class="muted" title="Needs SEC fundamentals">—</span>`;
    const tip = Object.entries(y.m15p).map(([k, v]) => `${D.meta.magic.labels[k]}: ${(v * 10).toFixed(1)}/10`).join("\n") + `\n${D.meta.magic.sub}. Left out on purpose: ${D.meta.magic.left_out.join("; ")}.\nRule-based proxy of published principles, not these investors' views.`;
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
  const HZL = { 6: "6 months", 12: "1 year", 24: "2 years", 36: "3 years", 48: "4 years", 60: "5 years" };
  const HZS = { 6: "6m", 12: "1y", 24: "2y", 36: "3y", 48: "4y", 60: "5y" };
  function views() {
    const v = [];
    if (PAGE === "main") v.push(["SP", "S&P 500"]);
    Object.keys(D.books).forEach((b) => v.push([b, D.book_label[b]]));
    v.push(["RES", "Research"]);
    return v;
  }
  function aiLookup() { const aiOf = {}; Object.values(D.books).forEach((rows) => rows.forEach((r) => { if (r.ai != null && aiOf[r.t] == null) aiOf[r.t] = r.ai; })); return aiOf; }
  function rowsForView() {
    const aiOf = aiLookup();
    if (state.view === "SP") return Object.keys(D.tick).filter((t) => D.tick[t].sp).map((t) => ({ t, name: D.tick[t].name, ai: aiOf[t] }));
    if (state.view === "RES") return state.research.map((r) => ({ t: r.t, name: r.name, ai: aiOf[r.t], research: r }));
    return D.books[state.view].map((r) => ({ t: r.t, name: r.name || D.tick[r.t]?.name, ai: r.ai, shares: r.shares }));
  }
  function renderTabs() {
    $("tabs").innerHTML = views().map(([k, l]) => `<button class="tab ${state.view === k ? "on" : ""}" data-v="${k}">${esc(l)}</button>`).join("");
    $("hz").innerHTML = `<span class="small muted" style="margin-right:4px">Holding period:</span>` + HZ.map((h) => `<button class="tab ${state.h === h ? "on" : ""}" data-h="${h}">${HZL[h]}</button>`).join("");
  }
  function renderBanner() {
    const mf = D.models["full_" + state.h], mp = D.models["price_" + state.h];
    $("hzNote").innerHTML = `<b>${HZL[state.h]}:</b> G1 composite backtest <span class="${verdictClass(mf.verdict)}">${mf.verdict}</span> (rank IC ${mf.metrics.rank_ic.toFixed(3)}, about ${mf.metrics.independent_periods} independent periods); price-only model <span class="${verdictClass(mp.verdict)}">${mp.verdict}</span>. Historically ${pct(mf.metrics.base_rate)} of large US stocks beat the S&amp;P 500 over ${HZL[state.h]}. That is the "usual" level the chance column compares against.`;
  }
  function chanceWord(hit, base) { const d = hit - base; return d >= 0.03 ? ["above usual", "up"] : d <= -0.03 ? ["below usual", "down"] : ["about usual", "flat"]; }
  function chanceCell(s, h) {
    if (!s) return "–";
    const base = D.models["full_" + h].metrics.base_rate, [w, cls] = chanceWord(s.hit, base);
    return `<span class="ch" style="background:${probColor(s.hit, base)}" title="Usual for any large stock: ${pct(base)}">${pct(s.hit)}</span> <span class="cw cw-${cls}">${w}</span>`;
  }
  function styleList(y) {
    if (!y) return `<div class="muted small">Needs SEC fundamentals (not available for this name).</div>`;
    const bm = Object.entries(bmParts(y)).map(([k, v]) => `<li>${esc(BM_LBL[k])}: <b>${v}</b>/${BM_MAX[k]}</li>`).join("");
    const mg = Object.entries(y.m15p).map(([k, v]) => `<li>${esc(D.meta.magic.labels[k])}: <b>${(v * 10).toFixed(1)}</b>/10</li>`).join("");
    return `<div class="dgrid"><div><b>Buffett &amp; Munger ${y.bm.toFixed(1)}/10</b><ul>${bm}</ul><div class="muted small">10-year Treasury ${(D.meta.tsy * 100).toFixed(2)}%; missing data scores half points.</div></div>
      <div><b>${esc(MAGIC_NAME)} ${y.m15.toFixed(1)}/10</b> <span class="muted small">(${esc(D.meta.magic.sub)})</span><ul>${mg}</ul><div class="muted small">Left out on purpose (they cancelled out or added little in testing): ${D.meta.magic.left_out.map(esc).join("; ")}.</div></div></div>`;
  }
  function detailRow(r, ncol) {
    const sc = r.sc, s = sc?.s?.[state.h];
    if (!sc) return `<tr class="det"><td colspan="${ncol}" class="muted">Not scored yet. Use Refresh or search this ticker.</td></tr>`;
    const strip = HZ.map((h) => { const x = sc.s[h], a = agree(x, r.ai); return `<div class="hzbox"><div class="muted small">${HZS[h]}</div><div class="ch" style="background:${probColor(x.hit, D.models["full_" + h].metrics.base_rate)}">${pct(x.hit)}</div>${agreeMini(a)}</div>`; }).join("");
    return `<tr class="det"><td colspan="${ncol}">
      <div class="dgrid">
        <div><b>Likely result vs the S&amp;P 500 over ${HZL[state.h]}</b><div>Bad case ${sgn(s.p10)} · typical <b>${sgn(s.p50)}</b> · good case ${sgn(s.p90)}</div>
          <div class="muted small">From how similar-scoring stocks did in the backtest (10th / 50th / 90th percentile). G1 score rank: ${Math.round(s.pct * 100)} of 100. ${sc.kind === "price" ? "Price-only model: no usable SEC fundamentals for this name." : "Full model (price + SEC fundamentals)."}${sc.live ? " Live prices." : ""}</div></div>
        <div><b>Every holding period</b> <span class="muted small">(dot = Danelfin agreement)</span><div class="hzrow">${strip}</div></div>
      </div>${styleList(sc.sty)}</td></tr>`;
  }
  function agreeMini(a) { return `<i class="dot ag-${a || "na"}" title="${a ? "Danelfin: " + a : "No Danelfin score"}"></i>`; }
  function renderTable() {
    const showNew = state.view === "NEW", isRes = state.view === "RES";
    let rows = rowsForView().map((r) => {
      const sc = r.research ? (state.live[r.t] ? scoresFor(r.t) : (r.research.s ? { s: r.research.s, kind: r.research.kind, px: r.research.px, sty: D.tick[r.t]?.sty || r.research.sty || null, live: false } : null)) : scoresFor(r.t);
      return Object.assign(r, { sc });
    });
    const f = state.filter.trim().toUpperCase();
    if (f) rows = rows.filter((r) => r.t.includes(f) || String(r.name || "").toUpperCase().includes(f));
    const val = (r) => {
      const s = r.sc?.s?.[state.h];
      switch (state.sortKey) {
        case "t": return r.t; case "ai": return r.ai ?? -1;
        case "bm": return r.sc?.sty?.bm ?? -1; case "m15": return r.sc?.sty?.m15 ?? -1;
        default: return s?.hit ?? -1;
      }
    };
    rows.sort((a, b) => { const x = val(a), y = val(b); return (x < y ? -1 : x > y ? 1 : 0) * state.sortDir; });
    const th = (k, l, tip) => `<th data-k="${k}" title="${esc(tip || "")}">${l}${state.sortKey === k ? (state.sortDir < 0 ? " ▾" : " ▴") : ""}</th>`;
    const ncol = 6 + (showNew ? 2 : 0) + (isRes ? 1 : 0);
    let html = `<table class="main"><thead><tr>${th("t", "Stock")}${th("prob", `Chance to beat S&amp;P 500<br><span class="muted small">over ${HZL[state.h]}</span>`, "Share of similar-scoring stocks that beat the S&P 500 (total return) in the backtest")}${th("ai", "Danelfin", "Danelfin AI Score (1–10, Nov 8) and whether it agrees with G1 for this period")}${th("bm", "Buffett &amp; Munger<br><span class=\"muted small\">0–10</span>", "Rule-based proxy of their published principles. Hover a score for the breakdown")}${th("m15", `${esc(MAGIC_NAME)}<br><span class="muted small">0–10</span>`, "Lean: quality compounders + downside protection. Rule-based proxy, not those investors' views")}${showNew ? "<th>Shares</th><th>Value</th>" : ""}<th></th>${isRes ? "<th></th>" : ""}</tr></thead><tbody>`;
    for (const r of rows) {
      const s = r.sc?.s?.[state.h], open = state.open.has(r.t);
      const a = s ? agree(s, r.ai) : null;
      html += `<tr class="${open ? "open" : ""}" data-x="${esc(r.t)}"><td><b>${esc(r.t)}</b>${r.sc?.live ? ' <span class="live">live</span>' : ""}<span class="nm">${esc(r.name || "")}</span></td>
        <td>${chanceCell(s, state.h)}</td>
        <td>${r.ai != null ? `<b>${r.ai}</b> ` : ""}${s ? agreePill(a, state.h) : ""}</td>
        <td>${bmBox(r.sc?.sty)}</td><td>${m15Box(r.sc?.sty)}</td>
        ${showNew ? `<td>${r.shares ?? "–"}</td><td>${r.sc?.px && r.shares ? "$" + (r.sc.px * r.shares).toLocaleString("en-US", { maximumFractionDigits: 0 }) : "–"}</td>` : ""}
        <td><button class="ghost xbtn" data-x="${esc(r.t)}" title="Show details">${open ? "▾" : "▸"}</button></td>
        ${isRes ? `<td><button class="ghost" data-unpin="${esc(r.t)}">Remove</button></td>` : ""}</tr>`;
      if (open) html += detailRow(r, ncol);
    }
    html += "</tbody></table>";
    if (!rows.length) html = `<div class="card muted">${isRes ? "Nothing pinned yet. Search a ticker above and press Pin." : "No rows."}</div>`;
    $("tbl").innerHTML = html;
    $("count").textContent = `${rows.length} stocks · click a row for details`;
  }
  function renderStatus() {
    $("asof").textContent = `Prices as of ${D.meta.price_asof}` + (state.refreshedAt ? ` · live refresh ${laTime(state.refreshedAt)}` : "") + ` · model built ${D.meta.built}`;
  }
  function renderBacktest() {
    const sb = D.meta.style_bt, f = (x) => x ? `${x.ic.toFixed(3)} <span class="muted">(t≈${x.t.toFixed(1)})</span>` : "–";
    const sum = `<table><tr><th>Holding period</th><th>G1 composite</th><th>Buffett &amp; Munger</th><th>${esc(MAGIC_NAME)} (lean, live)</th><th>Old 6-pillar ${esc(MAGIC_NAME)} (retired)</th></tr>${HZ.map((h) => `<tr><td>${HZL[h]}</td><td>${f(sb.A[h].wide)}</td><td>${f(sb.BM[h].wide)}</td><td>${f(sb.M15[h].wide)}</td><td>${f(sb.M15_old[h].wide)}</td></tr>`).join("")}</table>`;
    const part = `<table><tr><th>Holding period</th><th>B&amp;M on S&amp;P names</th><th>B&amp;M beyond G1 (partial IC)</th><th>${esc(MAGIC_NAME)} on S&amp;P names</th><th>${esc(MAGIC_NAME)} beyond G1 (partial IC)</th></tr>${HZ.map((h) => { const b = sb.BM[h], m = sb.M15[h]; return `<tr><td>${HZL[h]}</td><td>${f(b.sp)}</td><td>${b.partial_ic.toFixed(3)} <span class="muted">(t≈${b.partial_t.toFixed(1)})</span></td><td>${f(m.sp)}</td><td>${m.partial_ic.toFixed(3)} <span class="muted">(t≈${m.partial_t.toFixed(1)})</span></td></tr>`; }).join("")}</table>`;
    const rowsOf = (kind) => HZ.map((h) => {
      const m = D.models[kind + "_" + h], x = m.metrics;
      return `<tr><td>${HZL[h]}</td><td>${x.test_start.slice(0, 7)} → ${x.test_end.slice(0, 7)}</td><td>${x.independent_periods}</td><td>${pct(x.base_rate)}</td><td>${x.auc.toFixed(3)}</td><td>${x.rank_ic.toFixed(3)} <span class="muted">(t≈${x.rank_ic_t_overlap_adj.toFixed(1)})</span></td><td>${sgn(x.top_minus_bottom_decile)}</td><td>${x.ece.toFixed(3)}</td><td class="${verdictClass(m.verdict)}">${m.verdict}</td></tr>`;
    }).join("");
    const head = `<tr><th>Period</th><th>Test window</th><th>~Indep. periods</th><th>Base rate</th><th>AUC</th><th>Rank IC</th><th>Top−bottom decile</th><th>Calib. error</th><th>Verdict</th></tr>`;
    const cmp = `<table><tr><th>Period</th><th>G1 v2 composite</th><th>v2 learned ridge (not used)</th><th>G1 v1 (retired)</th></tr>${HZ.map((h) => { const c = D.models["full_" + h].cmp; const g = (x, t) => `${x.toFixed(3)} <span class="muted">(t≈${t.toFixed(1)})</span>`; return `<tr><td>${HZL[h]}</td><td>${g(c.sp_A.rank_ic, c.sp_A.ic_t_ovl)}</td><td>${g(c.sp_B.rank_ic, c.sp_B.ic_t_ovl)}</td><td>${g(c.v1.rank_ic, c.v1.t)}</td></tr>`; }).join("")}</table>`;
    $("bt").innerHTML = `<p class="small">Rank IC measures how well each score ranks future returns: 0 means no skill, and a t-statistic above about 2 is meaningful. These are walk-forward tests on the top 1,000 US stocks, month-ends from 2014, rules fixed before testing. Verdicts: <b>Buffett &amp; Munger: ${esc(D.meta.style_verdict.BM)}</b>; <b>${esc(MAGIC_NAME)}: ${esc(D.meta.style_verdict.M15)}</b>.</p>
      <div class="tblwrap">${sum}</div>
      <details><summary class="small">More: S&amp;P-only results and value beyond G1</summary><div class="tblwrap">${part}</div></details>
      <details><summary class="small">More: G1 model backtests (composite, price-only, retired models)</summary>
        <h3 class="small">G1 v2 composite (out-of-sample, top 1,000)</h3><div class="tblwrap"><table>${head}${rowsOf("full")}</table></div>
        <h3 class="small">Price-only model (ETFs, names without SEC data, searched tickers)</h3><div class="tblwrap"><table>${head}${rowsOf("price")}</table></div>
        <h3 class="small">G1 versions on historical S&amp;P 500 members (rank IC)</h3><div class="tblwrap">${cmp}</div></details>`;
  }

  // ---------- search ----------
  async function doSearch() {
    const t = $("q").value.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, "");
    if (!t) return;
    const out = $("searchOut");
    out.innerHTML = `<div class="card muted">Fetching ${esc(t)} from Yahoo…</div>`;
    try {
      const r = await liveScore(t);
      state.live[t] = { s: r.s, kind: r.kind, px: r.px, at: r.at, sty: r.sty };
      const spy = state.spyW, a = r.chart.a, sa = spy.a;
      const tr = (arr, k) => (arr.length > k ? arr[arr.length - 1] / arr[arr.length - 1 - k] - 1 : null);
      const name = D.tick[t]?.name || r.chart.meta.longName || r.chart.meta.shortName || "";
      const ai = aiLookup()[t];
      out.innerHTML = `<div class="card"><div class="row" style="justify-content:space-between"><div><b style="font-size:16px">${esc(t)}</b> <span class="muted">${esc(name)}</span> · $${r.px?.toFixed(2)}</div>
        <button id="pinBtn">${state.research.some((x) => x.t === t) ? "Pinned ✓" : "Pin to Research"}</button></div>
        <div class="row" style="gap:14px;margin:8px 0"><div>Chance to beat S&amp;P 500 over ${HZL[state.h]}: ${chanceCell(r.s[state.h], state.h)}</div><div>Danelfin: ${ai ?? "–"} ${agreePill(agree(r.s[state.h], ai), state.h)}</div><div>Buffett &amp; Munger ${bmBox(r.sty)}</div><div>${esc(MAGIC_NAME)} ${m15Box(r.sty)}</div></div>
        <div class="hzrow">${HZ.map((h) => { const x = r.s[h]; return `<div class="hzbox"><div class="muted small">${HZS[h]}</div><div class="ch" style="background:${probColor(x.hit, D.models["full_" + h].metrics.base_rate)}">${pct(x.hit)}</div>${agreeMini(agree(x, ai))}</div>`; }).join("")}</div>
        <div class="small muted" style="margin-top:6px">Past returns: 6 months ${sgn(tr(a, 26))} (S&amp;P ${sgn(tr(sa, 26))}) · 1 year ${sgn(tr(a, 52))} (S&amp;P ${sgn(tr(sa, 52))}) · 3 years ${sgn(tr(a, 156))} (S&amp;P ${sgn(tr(sa, 156))}).${r.kind === "price" ? " <b>Price-only score:</b> no SEC fundamentals are bundled for this ticker, so the style scores are blank." : ""}</div></div>`;
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
    const x = e.target.closest("[data-x]");
    if (x && !e.target.closest("[data-unpin]") && !e.target.closest(".sty")) { const t = x.dataset.x; state.open.has(t) ? state.open.delete(t) : state.open.add(t); renderTable(); return; }
    const u = e.target.closest("[data-unpin]"); if (u) { state.research = state.research.filter((x) => x.t !== u.dataset.unpin); saveResearch(); renderTable(); }
  });
  $("refresh").onclick = refresh;
  $("go").onclick = doSearch;
  $("q").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
  $("helpT").onclick = (e) => { e.preventDefault(); $("help").hidden = !$("help").hidden; };
  $("refStatus").textContent = "Scores use the prices shipped at build. Refresh pulls live prices and re-scores in your browser.";
  $("flt").addEventListener("input", (e) => { state.filter = e.target.value; renderTable(); });
  renderTabs(); renderBanner(); renderStatus(); renderTable(); renderBacktest();
  if ($("gaps")) $("gaps").textContent = Object.keys(D.tick).filter((t) => D.tick[t].kind === "price").sort().join(", ") || "none";
  window.G1 = { qpct, styleOf, scoreAll, priceFeatures, fundFeatures, D, state }; // for local verification
})();
