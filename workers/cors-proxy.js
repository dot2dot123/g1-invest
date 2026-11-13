// G1 CORS proxy (Cloudflare Worker, free tier). Origin-locked; forwards only Yahoo chart + SEC companyfacts.
// Usage from the page: https://<worker>.workers.dev/?url=<encoded target URL>
const ORIGINS = ["https://dot2dot123.github.io"];
const ALLOW = [/^https:\/\/query[12]\.finance\.yahoo\.com\/v8\/finance\/chart\//, /^https:\/\/data\.sec\.gov\/api\/xbrl\/companyfacts\/CIK\d{10}\.json$/];
const UA = "G1 personal research proxy (contact: dot2dot123@users.noreply.github.com)"; // SEC requires a descriptive User-Agent

export default {
  async fetch(req) {
    const origin = req.headers.get("Origin") || "";
    const okOrigin = ORIGINS.includes(origin);
    const cors = { "Access-Control-Allow-Origin": okOrigin ? origin : ORIGINS[0], "Access-Control-Allow-Methods": "GET, OPTIONS", "Vary": "Origin" };
    if (req.method === "OPTIONS") return new Response(null, { status: okOrigin ? 204 : 403, headers: cors });
    if (req.method !== "GET" || !okOrigin) return new Response("forbidden", { status: 403, headers: cors });
    const target = new URL(req.url).searchParams.get("url") || "";
    if (!ALLOW.some((re) => re.test(target))) return new Response("target not allowed", { status: 400, headers: cors });
    try {
      const r = await fetch(target, { headers: { "User-Agent": UA, "Accept": "application/json" }, cf: { cacheTtl: 300, cacheEverything: true } });
      const h = new Headers(cors); h.set("Content-Type", r.headers.get("Content-Type") || "application/json"); h.set("Cache-Control", "public, max-age=300");
      return new Response(r.body, { status: r.status, headers: h });
    } catch (e) {
      return new Response("upstream error", { status: 502, headers: cors });
    }
  },
};
