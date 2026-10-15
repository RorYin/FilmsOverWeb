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
          "Access-Control-Allow-Headers": "Range, Content-Type, Authorization, Accept-Encoding",
          "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges, Content-Type",
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
          },
        }
      );
    }

    // 3. Build Google Drive direct download URL with bypass confirmation
    const apiKey = url.searchParams.get("key") || "";
    let gdriveUrl = `https://drive.usercontent.google.com/download?id=${fileId}&export=download&confirm=t`;
    if (apiKey) {
      gdriveUrl = `https://www.googleapis.com/drive/v3/files/${fileId}?alt=media&key=${apiKey}`;
    }

    // 4. Forward client Range header for chunked seeking
    const upstreamHeaders = new Headers();
    const rangeHeader = request.headers.get("Range");
    if (rangeHeader) {
      upstreamHeaders.set("Range", rangeHeader);
    }
    upstreamHeaders.set(
      "User-Agent",
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    );

    try {
      const gdriveResponse = await fetch(gdriveUrl, {
        method: request.method,
        headers: upstreamHeaders,
        redirect: "follow",
      });

      // 5. Clone and inject CORS + Range headers
      const responseHeaders = new Headers(gdriveResponse.headers);
      responseHeaders.set("Access-Control-Allow-Origin", "*");
      responseHeaders.set("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
      responseHeaders.set("Access-Control-Allow-Headers", "Range, Content-Type, Authorization");
      responseHeaders.set(
        "Access-Control-Expose-Headers",
        "Content-Range, Content-Length, Accept-Ranges, Content-Type"
      );
      responseHeaders.set("Accept-Ranges", "bytes");

      // Infer proper video MIME type if Google returns octet-stream
      const contentType = responseHeaders.get("Content-Type") || "";
      const fileName = (url.searchParams.get("name") || "").toLowerCase();
      if (!contentType || contentType.includes("octet-stream") || contentType.includes("text/html")) {
        if (fileName.endsWith(".mkv")) {
          responseHeaders.set("Content-Type", "video/x-matroska");
        } else if (fileName.endsWith(".webm")) {
          responseHeaders.set("Content-Type", "video/webm");
        } else {
          responseHeaders.set("Content-Type", "video/mp4");
        }
      }

      return new Response(gdriveResponse.body, {
        status: gdriveResponse.status,
        statusText: gdriveResponse.statusText,
        headers: responseHeaders,
      });
    } catch (err) {
      return new Response(
        JSON.stringify({
          error: "Failed to stream from Google Drive",
          details: err.message,
        }),
        {
          status: 502,
          headers: {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
          },
        }
      );
    }
  },
};
