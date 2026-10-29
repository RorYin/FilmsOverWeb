/**
 * FilmsOverWeb - Cloudflare Worker CORS & Stream Proxy for Google Drive
 * 
 * Benefits:
 * - 100% Free & Unlimited Bandwidth on Cloudflare Workers Free Tier.
 * - Streams Google Drive video chunks directly to the client's browser.
 * - Full HTTP 206 Partial Content (Byte-Range) support for instant timeline seeking.
 * - Injects CORS headers (Access-Control-Allow-Origin: *) so WebAssembly players (movi-player) can fetch directly.
 * - Bypasses Google Drive's 100MB+ virus scan warning interstitial page automatically.
 * 
 * Deployment:
 * 1. Log in to https://dash.cloudflare.com/ (Free account).
 * 2. Go to "Workers & Pages" -> Click "Create Worker".
 * 3. Replace the default code with this file and click "Deploy".
 * 4. Copy your worker URL (e.g. https://your-worker-name.your-subdomain.workers.dev).
 * 5. Paste the URL into FilmsOverWeb SuperAdmin Settings (System Configuration).
 */

export default {
  async fetch(request, env) {
    // 1. Handle CORS Preflight (OPTIONS)
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
          "Access-Control-Allow-Headers": "*",
          "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges, Content-Type, Content-Disposition",
          "Cross-Origin-Resource-Policy": "cross-origin",
          "Access-Control-Max-Age": "86400",
        },
      });
    }

    const url = new URL(request.url);

    // Health check endpoint
    if (url.pathname === "/health" || url.pathname === "/ping") {
      return new Response("FilmsOverWeb Cloudflare Stream Worker is Active!", {
        status: 200,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Cross-Origin-Resource-Policy": "cross-origin",
          "Content-Type": "text/plain",
        },
      });
    }

    // 2. Extract Google Drive file_id from query (?file_id=... or ?id=...) or path (/stream/:id)
    let fileId = url.searchParams.get("file_id") || url.searchParams.get("id");
    if (!fileId && url.pathname.startsWith("/stream/")) {
      fileId = url.pathname.replace("/stream/", "").split("?")[0];
    }

    if (!fileId) {
      return new Response(
        JSON.stringify({
          error: "Missing Google Drive file_id",
          usage: "GET /?file_id=1CdUqK06DYnJupR4pPAGnDJb2j7xzE_mX",
        }),
        {
          status: 400,
          headers: {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Cross-Origin-Resource-Policy": "cross-origin",
          },
        }
      );
    }

    // 3. Build Google Drive direct download URL with bypass confirmation or OAuth / API key
    const apiKey = url.searchParams.get("key") || "";
    const token = url.searchParams.get("token") || request.headers.get("Authorization")?.replace(/^Bearer\s+/i, "") || "";
    let gdriveUrl = `https://drive.usercontent.google.com/download?id=${fileId}&export=download&confirm=t`;
    if (token) {
      gdriveUrl = `https://www.googleapis.com/drive/v3/files/${fileId}?alt=media`;
    } else if (apiKey) {
      gdriveUrl = `https://www.googleapis.com/drive/v3/files/${fileId}?alt=media&key=${apiKey}`;
    }

    // Determine target MIME type from filename
    const fileName = (url.searchParams.get("name") || "").toLowerCase();
    let defaultMime = "video/mp4";
    if (fileName.endsWith(".mkv")) {
      defaultMime = "video/x-matroska";
    } else if (fileName.endsWith(".webm")) {
      defaultMime = "video/webm";
    }

    // 4. Handle HEAD probes (used by movi-player WASM player to check size & range support)
    // Google Drive returns Content-Length: 0 on un-ranged HEAD requests.
    // Probing with Range: bytes=0-0 forces Google to return Content-Range: bytes 0-0/{totalSize}.
    if (request.method === "HEAD") {
      try {
        const probeHeaders = new Headers({
          "Range": "bytes=0-0",
          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        });
        if (token) {
          probeHeaders.set("Authorization", `Bearer ${token}`);
        }
        const probeResp = await fetch(gdriveUrl, {
          method: "GET",
          headers: probeHeaders,
          redirect: "follow",
          cf: { cacheEverything: true, cacheTtl: 86400 }
        });

        const probeCt = probeResp.headers.get("Content-Type") || "";
        if (probeCt.includes("text/html")) {
          return new Response(
            JSON.stringify({
              error: "Google Drive Quota Exceeded",
              details: "Google Drive has temporarily rate-limited public downloads for this file (exceeded 24h traffic quota). Configure a Google Service Account in SuperAdmin Settings.",
            }),
            {
              status: 429,
              headers: {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Cross-Origin-Resource-Policy": "cross-origin",
                "Retry-After": "3600"
              }
            }
          );
        }

        const contentRange = probeResp.headers.get("Content-Range") || "";
        let totalSize = "";
        if (contentRange.includes("/")) {
          totalSize = contentRange.split("/")[1].trim();
        }

        const headHeaders = new Headers();
        headHeaders.set("Access-Control-Allow-Origin", "*");
        headHeaders.set("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
        headHeaders.set("Access-Control-Allow-Headers", "*");
        headHeaders.set("Access-Control-Expose-Headers", "Content-Range, Content-Length, Accept-Ranges, Content-Type, Content-Disposition");
        headHeaders.set("Cross-Origin-Resource-Policy", "cross-origin");
        headHeaders.set("Accept-Ranges", "bytes");
        headHeaders.set("Content-Type", defaultMime);
        if (totalSize && totalSize !== "*") {
          headHeaders.set("Content-Length", totalSize);
        }
        headHeaders.set("Cache-Control", "public, max-age=86400");

        return new Response(null, {
          status: 200,
          headers: headHeaders,
        });
      } catch (headErr) {
        return new Response(null, {
          status: 200,
          headers: {
            "Access-Control-Allow-Origin": "*",
            "Cross-Origin-Resource-Policy": "cross-origin",
            "Accept-Ranges": "bytes",
            "Content-Type": defaultMime,
          }
        });
      }
    }

    // 5. Forward client Range header (defaulting to 8MB chunk if un-ranged to prevent Google Quota HTML errors on large files)
    const upstreamHeaders = new Headers();
    const rangeHeader = request.headers.get("Range");
    if (rangeHeader) {
      upstreamHeaders.set("Range", rangeHeader);
    } else {
      upstreamHeaders.set("Range", "bytes=0-8388607");
    }
    upstreamHeaders.set(
      "User-Agent",
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    );
    if (token) {
      upstreamHeaders.set("Authorization", `Bearer ${token}`);
    }

    try {
      const gdriveResponse = await fetch(gdriveUrl, {
        method: "GET",
        headers: upstreamHeaders,
        redirect: "follow",
        cf: {
          cacheEverything: true,
          cacheTtl: 86400,
        }
      });

      const contentType = (gdriveResponse.headers.get("Content-Type") || "").toLowerCase();

      // Check if Google Drive returned an HTML error/quota page instead of binary video
      if (contentType.includes("text/html")) {
        return new Response(
          JSON.stringify({
            error: "Google Drive Quota Exceeded",
            details: "Google Drive has temporarily rate-limited public downloads for this file (exceeded 24h traffic quota). Configure a Google Service Account in SuperAdmin Settings to bypass anonymous limits.",
          }),
          {
            status: 429,
            headers: {
              "Content-Type": "application/json",
              "Access-Control-Allow-Origin": "*",
              "Cross-Origin-Resource-Policy": "cross-origin",
              "Retry-After": "3600"
            },
          }
        );
      }

      // 6. Clone and inject CORS + Range + Cache headers (strip restrictive Google headers)
      const responseHeaders = new Headers(gdriveResponse.headers);
      responseHeaders.set("Access-Control-Allow-Origin", "*");
      responseHeaders.set("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
      responseHeaders.set("Access-Control-Allow-Headers", "*");
      responseHeaders.set(
        "Access-Control-Expose-Headers",
        "Content-Range, Content-Length, Accept-Ranges, Content-Type, Content-Disposition"
      );
      responseHeaders.set("Cross-Origin-Resource-Policy", "cross-origin");
      responseHeaders.delete("Content-Security-Policy");
      responseHeaders.delete("X-Content-Security-Policy");
      responseHeaders.delete("Cross-Origin-Opener-Policy");
      responseHeaders.delete("Cross-Origin-Embedder-Policy");
      responseHeaders.set("Content-Disposition", "inline");
      responseHeaders.set("Accept-Ranges", "bytes");
      responseHeaders.set("Cache-Control", "public, max-age=86400");

      // Infer proper video MIME type if Google returns octet-stream
      if (!contentType || contentType.includes("octet-stream")) {
        responseHeaders.set("Content-Type", defaultMime);
      }

      return new Response(gdriveResponse.body, {
        status: gdriveResponse.status,
        statusText: gdriveResponse.statusText,
        headers: responseHeaders,
      });
    } catch (err) {
      return new Response(
        JSON.stringify({
          error: "Failed to stream from Google Drive upstream",
          details: err.message,
        }),
        {
          status: 502,
          headers: {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Cross-Origin-Resource-Policy": "cross-origin",
          },
        }
      );
    }
  },
};
