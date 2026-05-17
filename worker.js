/**
 * Cloudflare Worker that adds HTTP Range support for .pmtiles files.
 *
 * Workers Static Assets currently returns HTTP 200 with the full file when
 * a client sends a Range request, which breaks PMTiles. PMTiles JS issues
 * Range requests for the archive header and individual tile slices; without
 * proper 206 Partial Content responses, it aborts the connection
 * ("Server returned no content-length header or content-length exceeding
 * request. Check that your storage backend supports HTTP Byte Serving.")
 * and the choropleth layers never render.
 *
 * This worker intercepts requests for *.pmtiles, fetches the full asset
 * from the ASSETS binding (so Cloudflare can cache it once), then slices
 * the requested byte range and returns 206. Every other request passes
 * through to the static assets unchanged.
 */

const PMTILES_CACHE_CONTROL = "public, max-age=31536000, immutable";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (!url.pathname.endsWith(".pmtiles")) {
      return env.ASSETS.fetch(request);
    }

    // Strip the client's Range so the asset-storage fetch returns a single
    // canonical full-file response that Cloudflare can edge-cache.
    const assetReq = new Request(url.toString(), { method: "GET" });
    const assetRes = await env.ASSETS.fetch(assetReq);

    if (assetRes.status !== 200 || !assetRes.body) {
      return assetRes;
    }

    const buffer = await assetRes.arrayBuffer();
    const totalSize = buffer.byteLength;

    const headers = new Headers();
    headers.set("Content-Type", "application/octet-stream");
    headers.set("Accept-Ranges", "bytes");
    headers.set("Cache-Control", PMTILES_CACHE_CONTROL);
    // Keep PMTiles archives out of search indexes. They are not standalone
    // documents and should not appear in site: results.
    headers.set("X-Robots-Tag", "noindex, nofollow");
    const etag = assetRes.headers.get("etag");
    if (etag) headers.set("ETag", etag);

    const rangeHeader = request.headers.get("range");
    if (!rangeHeader) {
      headers.set("Content-Length", String(totalSize));
      return new Response(buffer, { status: 200, headers });
    }

    const parsed = parseRange(rangeHeader, totalSize);
    if (!parsed) {
      headers.set("Content-Range", `bytes */${totalSize}`);
      return new Response("Range Not Satisfiable", { status: 416, headers });
    }
    const { start, end } = parsed;
    const slice = buffer.slice(start, end + 1);
    headers.set("Content-Length", String(slice.byteLength));
    headers.set("Content-Range", `bytes ${start}-${end}/${totalSize}`);
    return new Response(slice, { status: 206, headers });
  },
};

/**
 * Parse a single-range `bytes=start-end` header. Returns { start, end } with
 * inclusive end, or null on an unsatisfiable / malformed range.
 */
function parseRange(header, totalSize) {
  const match = /^bytes=(\d*)-(\d*)$/i.exec(header.trim());
  if (!match) return null;
  const [, startStr, endStr] = match;

  let start;
  let end;
  if (startStr === "" && endStr !== "") {
    // Suffix range: last N bytes.
    const length = parseInt(endStr, 10);
    if (length <= 0) return null;
    start = Math.max(0, totalSize - length);
    end = totalSize - 1;
  } else if (startStr !== "") {
    start = parseInt(startStr, 10);
    end = endStr === "" ? totalSize - 1 : parseInt(endStr, 10);
  } else {
    return null;
  }

  if (
    Number.isNaN(start) ||
    Number.isNaN(end) ||
    start < 0 ||
    start >= totalSize ||
    end < start
  ) {
    return null;
  }
  if (end >= totalSize) end = totalSize - 1;
  return { start, end };
}
