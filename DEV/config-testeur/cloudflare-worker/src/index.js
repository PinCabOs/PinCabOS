const REPO = "PinCabOs/PinCabOS";
const API_VERSION = "2022-11-28";
const MAX_ENCODED = 900000;
const CHUNK_SIZE = 45000;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function slug(value, fallback) {
  const out = String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^[._-]+|[._-]+$/g, "")
    .slice(0, 64);
  return out || fallback;
}

async function github(env, path, method = "POST", body = undefined) {
  const token = String(env.GITHUB_TOKEN || "").trim();
  if (!token) {
    throw new Error("github_token_missing");
  }

  const response = await fetch(`https://api.github.com/repos/${REPO}${path}`, {
    method,
    headers: {
      accept: "application/vnd.github+json",
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
      "user-agent": "PinCabOS-Tester-Upload-Worker/4",
      "x-github-api-version": API_VERSION,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const text = await response.text();
  let payload = {};
  try { payload = text ? JSON.parse(text) : {}; } catch { payload = { message: text }; }

  if (!response.ok) {
    const accepted = response.headers.get("x-accepted-github-permissions") || "";
    const permissionHint = accepted ? `;accepted=${accepted}` : "";
    throw new Error(
      `github_http_${response.status}:${payload.message || "unknown"};repo=${REPO}${permissionHint}`,
    );
  }
  return payload;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/health") {
      return json({
        ok: true,
        service: "pincabos-tester-upload",
        version: 4,
        repository: REPO,
      });
    }

    if (request.method !== "POST" || url.pathname !== "/v1/tester-report") {
      return json({ ok: false, error: "not_found" }, 404);
    }

    const contentType = request.headers.get("content-type") || "";
    if (!contentType.toLowerCase().includes("application/json")) {
      return json({ ok: false, error: "content_type" }, 415);
    }

    const ip = request.headers.get("cf-connecting-ip") || "unknown";
    if (env.UPLOAD_RATE_LIMITER) {
      const limited = await env.UPLOAD_RATE_LIMITER.limit({ key: `tester-report:${ip}` });
      if (!limited.success) return json({ ok: false, error: "rate_limited" }, 429);
    }

    const declaredLength = Number(request.headers.get("content-length") || 0);
    if (declaredLength > 1200000) {
      return json({ ok: false, error: "request_too_large" }, 413);
    }

    let raw;
    try {
      raw = await request.text();
    } catch {
      return json({ ok: false, error: "body_read" }, 400);
    }
    if (raw.length > 1200000) {
      return json({ ok: false, error: "request_too_large" }, 413);
    }

    let body;
    try {
      body = JSON.parse(raw);
    } catch {
      return json({ ok: false, error: "invalid_json" }, 400);
    }

    const testerName = String(body.tester_name || "").trim();
    const hostName = String(body.host_name || "").trim();
    const reportSha = String(body.report_sha256 || "").toLowerCase();
    const encoded = String(body.payload || "");

    if (body.schema_version !== 4) return json({ ok: false, error: "schema_version" }, 400);
    if (!testerName || testerName.length > 100) return json({ ok: false, error: "tester_name" }, 400);
    if (!hostName || hostName.length > 100) return json({ ok: false, error: "host_name" }, 400);
    if (!/^[a-f0-9]{64}$/.test(reportSha)) return json({ ok: false, error: "sha256" }, 400);
    if (body.compression !== "gzip" || body.encoding !== "base64") return json({ ok: false, error: "encoding" }, 400);
    if (!Number.isInteger(body.encoded_length) || body.encoded_length !== encoded.length) return json({ ok: false, error: "encoded_length" }, 400);
    if (encoded.length < 32 || encoded.length > MAX_ENCODED) return json({ ok: false, error: "payload_size" }, 413);
    if (!/^[A-Za-z0-9+/]+={0,2}$/.test(encoded)) return json({ ok: false, error: "base64" }, 400);

    const chunks = [];
    for (let i = 0; i < encoded.length; i += CHUNK_SIZE) chunks.push(encoded.slice(i, i + CHUNK_SIZE));
    if (!chunks.length || chunks.length > 32) return json({ ok: false, error: "chunk_count" }, 413);

    const metadata = {
      schema_version: 3,
      tester_name: testerName,
      host_name: hostName,
      report_sha256: reportSha,
      compression: "gzip",
      encoding: "base64",
      encoded_length: encoded.length,
      chunks: chunks.length,
      transport: "cloudflare-worker-v4",
    };

    let issueNumber = 0;
    let issueUrl = "";
    try {
      const issue = await github(env, "/issues", "POST", {
        title: `[PINCABOS-TESTER-REPORT-V3] ${slug(testerName, "testeur")} / ${slug(hostName, "pincabos")}`,
        body: `PINCABOS_TESTER_REPORT_V3\n${JSON.stringify(metadata)}`,
      });
      issueNumber = Number(issue.number || 0);
      issueUrl = String(issue.html_url || "");
      if (!issueNumber) throw new Error("github_issue_number_missing");

      for (let i = 0; i < chunks.length; i++) {
        await github(env, `/issues/${issueNumber}/comments`, "POST", {
          body: `PINCABOS_TESTER_REPORT_CHUNK_V3 ${i + 1}/${chunks.length}\n${chunks[i]}`,
        });
      }
      await github(env, `/issues/${issueNumber}/comments`, "POST", {
        body: "PINCABOS_TESTER_REPORT_COMPLETE_V3",
      });
    } catch (error) {
      if (issueNumber) {
        try {
          await github(env, `/issues/${issueNumber}`, "PATCH", {
            state: "closed",
            state_reason: "not_planned",
          });
        } catch {}
      }
      return json({ ok: false, error: String(error && error.message ? error.message : error), issue_url: issueUrl }, 502);
    }

    return json({ ok: true, issue_number: issueNumber, issue_url: issueUrl });
  },
};