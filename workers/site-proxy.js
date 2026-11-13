// G1 site reverse proxy (Cloudflare Worker, free tier).
// Serves https://dot2dot123.github.io/g1-invest/* from this Worker's root
// (https://<name>.<account>.workers.dev/ and /otw/) so the GitHub Pages
// origin can stay behind the edge. Caching (~10 min) and Cloudflare's
// free DDoS protection come with the Worker. The HTML is passed through
// unchanged except for href/src/action attributes, so StatiCrypt's
// password shell and ciphertext keep working.
//
// Not deployed automatically. See workers/README.md.

const ORIGIN = "https://dot2dot123.github.io";
const PREFIX = "/g1-invest";
const CACHE_TTL = 600; // seconds (~10 minutes)

const HOP = new Set([
  "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
  "te", "trailers", "transfer-encoding", "upgrade",
]);

function originUrl(reqUrl) {
  const u = new URL(reqUrl);
  let path = u.pathname || "/";
  if (path === "/") path = "/";
  // Never escape the PREFIX; only proxy under /g1-invest
  return ORIGIN + PREFIX + path + u.search;
}

function filterReqHeaders(src) {
  const h = new Headers();
  for (const [k, v] of src.entries()) {
    const key = k.toLowerCase();
    if (HOP.has(key) || key === "host" || key === "cf-connecting-ip" || key === "cf-ipcountry") continue;
    h.set(k, v);
  }
  // Ask GitHub Pages for a fresh-enough copy; we apply our own edge TTL.
  h.set("Accept-Encoding", "identity");
  return h;
}

function outHeaders(src) {
  const h = new Headers();
  for (const [k, v] of src.entries()) {
    const key = k.toLowerCase();
    if (HOP.has(key)) continue;
    // Do not leak the GitHub Pages origin via redirects or CORS.
    if (key === "location" || key === "access-control-allow-origin" || key === "link" || key === "server" || key === "x-github-request-id" || key === "x-served-by") continue;
    h.set(k, v);
  }
  h.set("Cache-Control", `public, max-age=${CACHE_TTL}`);
  h.set("X-Content-Type-Options", "nosniff");
  return h;
}

function rewriteLocation(loc, workerOrigin) {
  if (!loc) return loc;
  try {
    const abs = loc.startsWith("http") ? loc : ORIGIN + loc;
    const u = new URL(abs);
    if (u.origin === ORIGIN && (u.pathname === PREFIX || u.pathname.startsWith(PREFIX + "/"))) {
      const rest = u.pathname.slice(PREFIX.length) || "/";
      return workerOrigin + rest + u.search + u.hash;
    }
  } catch (e) { /* leave as-is */ }
  return loc;
}

function rewriteAttr(value, workerOrigin) {
  if (!value) return value;
  if (value.startsWith(ORIGIN + PREFIX)) {
    return workerOrigin + value.slice((ORIGIN + PREFIX).length);
  }
  if (value.startsWith(PREFIX + "/") || value === PREFIX) {
    return value.slice(PREFIX.length) || "/";
  }
  return value;
}

class LinkRewriter {
  constructor(workerOrigin) { this.workerOrigin = workerOrigin; }
  element(el) {
    for (const attr of ["href", "src", "action"]) {
      const v = el.getAttribute(attr);
      if (!v) continue;
      const n = rewriteAttr(v, this.workerOrigin);
      if (n !== v) el.setAttribute(attr, n);
    }
  }
}

export default {
  async fetch(request, env, ctx) {
    const workerOrigin = new URL(request.url).origin;
    const target = originUrl(request.url);

    // Only proxy GET/HEAD; StatiCrypt is a static page.
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("method not allowed", { status: 405, headers: { Allow: "GET, HEAD" } });
    }

    const cache = caches.default;
    const cacheKey = new Request(target, { method: "GET" });
    if (request.method === "GET") {
      const hit = await cache.match(cacheKey);
      if (hit) return hit;
    }

    let upstream;
    try {
      upstream = await fetch(target, {
        method: request.method,
        headers: filterReqHeaders(request.headers),
        redirect: "manual",
        cf: { cacheTtl: CACHE_TTL, cacheEverything: true },
      });
    } catch (e) {
      return new Response("upstream error", { status: 502 });
    }

    const headers = outHeaders(upstream.headers);
    const loc = upstream.headers.get("Location");
    if (loc) headers.set("Location", rewriteLocation(loc, workerOrigin));

    const ctype = (upstream.headers.get("Content-Type") || "").toLowerCase();
    let response;
    if (request.method === "GET" && ctype.includes("text/html") && upstream.status === 200) {
      // Rewrite only element attributes (href/src/action). Do not touch
      // text or script bodies — that would risk corrupting StatiCrypt ciphertext.
      const rewritten = new HTMLRewriter()
        .on("a", new LinkRewriter(workerOrigin))
        .on("link", new LinkRewriter(workerOrigin))
        .on("script", new LinkRewriter(workerOrigin))
        .on("img", new LinkRewriter(workerOrigin))
        .on("form", new LinkRewriter(workerOrigin))
        .transform(upstream);
      response = new Response(rewritten.body, { status: rewritten.status, statusText: rewritten.statusText, headers });
    } else {
      response = new Response(request.method === "HEAD" ? null : upstream.body, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers,
      });
    }

    if (request.method === "GET" && upstream.status === 200) {
      ctx.waitUntil(cache.put(cacheKey, response.clone()));
    }
    return response;
  },
};
