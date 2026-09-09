#!/usr/bin/env python3
"""Reconstruct a PinCabOS tester report from a GitHub transport issue."""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = "PinCabOs/PinCabOS"
EXPECTED_AUTHOR = "KarotsSugarpie"
ISSUE_MARKER = "PINCABOS_TESTER_REPORT_V3"
CHUNK_MARKER = "PINCABOS_TESTER_REPORT_CHUNK_V3"
FINAL_MARKER = "PINCABOS_TESTER_REPORT_COMPLETE_V3"
DEST = Path("DEV/config-testeur")
MAX_REPORT_BYTES = 512 * 1024
MAX_COMPRESSED_BYTES = 600 * 1024
MAX_CHUNKS = 32


def fail(message: str):
    raise SystemExit("NOGO: " + message)


def api_get(url: str, token: str):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "PinCabOS-Tester-Report-Ingest/3",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        fail(f"GitHub HTTP {exc.code}")
    except urllib.error.URLError:
        fail("GitHub inaccessible")


def slugify(value: str, fallback: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.lower())
    value = re.sub(r"-{2,}", "-", value).strip("._-")
    return (value or fallback)[:64]


def parse_issue_metadata(body: str) -> dict:
    lines = str(body or "").splitlines()
    if len(lines) < 2 or lines[0].strip() != ISSUE_MARKER:
        fail("marqueur issue invalide")
    try:
        metadata = json.loads("\n".join(lines[1:]))
    except json.JSONDecodeError:
        fail("metadata JSON invalide")
    if not isinstance(metadata, dict) or metadata.get("schema_version") != 3:
        fail("schema invalide")
    return metadata


def fetch_all_comments(issue_number: int, token: str) -> list[dict]:
    comments: list[dict] = []
    for page in range(1, 11):
        url = (
            f"https://api.github.com/repos/{REPO}/issues/{issue_number}/comments"
            f"?per_page=100&page={page}"
        )
        batch = api_get(url, token)
        if not isinstance(batch, list):
            fail("reponse commentaires invalide")
        comments.extend(batch)
        if len(batch) < 100:
            return comments
    fail("trop de commentaires")


def parse_chunks(comments: list[dict], expected_total: int) -> str:
    chunk_re = re.compile(
        rf"^{re.escape(CHUNK_MARKER)}\s+(\d{{1,3}})/(\d{{1,3}})\n([A-Za-z0-9+/=\n\r]+)$"
    )
    chunks: dict[int, str] = {}
    saw_final = False

    for comment in comments:
        author = str(((comment.get("user") or {}).get("login") or ""))
        if author != EXPECTED_AUTHOR:
            continue
        body = str(comment.get("body") or "").strip()
        if body == FINAL_MARKER:
            saw_final = True
            continue
        match = chunk_re.fullmatch(body)
        if not match:
            continue
        index = int(match.group(1))
        total = int(match.group(2))
        if total != expected_total or not (1 <= index <= expected_total):
            fail("index de chunk invalide")
        if index in chunks:
            fail("chunk duplique")
        chunks[index] = re.sub(r"\s+", "", match.group(3))

    if not saw_final:
        fail("marqueur final absent")
    if len(chunks) != expected_total:
        fail(f"chunks incomplets: {len(chunks)}/{expected_total}")
    return "".join(chunks[index] for index in range(1, expected_total + 1))


def decompress_report(encoded: str, expected_sha256: str) -> str:
    try:
        compressed = base64.b64decode(encoded, validate=True)
    except Exception:
        fail("base64 invalide")
    if not compressed or len(compressed) > MAX_COMPRESSED_BYTES:
        fail("archive compressee trop volumineuse")

    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as gz:
            raw = gz.read(MAX_REPORT_BYTES + 1)
    except OSError:
        fail("gzip invalide")

    if not 256 <= len(raw) <= MAX_REPORT_BYTES:
        fail("taille rapport invalide")
    digest = hashlib.sha256(raw).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or ""):
        fail("SHA256 metadata invalide")
    if digest != expected_sha256:
        fail("SHA256 rapport invalide")

    try:
        report = raw.decode("utf-8")
    except UnicodeDecodeError:
        fail("rapport non UTF-8")
    if "PINFORGE-SAFE - PINCABOS TESTER SYSTEM AUDIT" not in report:
        fail("marqueur rapport invalide")
    return report


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        fail("usage: ingest ISSUE_NUMBER")

    issue_number = int(sys.argv[1])
    token = str(os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        fail("GITHUB_TOKEN absent")

    runtime_repo = str(os.environ.get("GITHUB_REPOSITORY") or REPO)
    if runtime_repo != REPO:
        fail(f"depot inattendu: {runtime_repo}")

    issue = api_get(f"https://api.github.com/repos/{REPO}/issues/{issue_number}", token)
    if not isinstance(issue, dict):
        fail("issue introuvable")
    if issue.get("pull_request"):
        fail("pull request refusee")

    author = str(((issue.get("user") or {}).get("login") or ""))
    if author != EXPECTED_AUTHOR:
        fail("auteur issue refuse")

    title = str(issue.get("title") or "")
    if not title.startswith("[PINCABOS-TESTER-REPORT-V3]"):
        fail("titre issue invalide")

    metadata = parse_issue_metadata(str(issue.get("body") or ""))
    tester = str(metadata.get("tester_name") or "").strip()
    hostname = str(metadata.get("host_name") or "").strip()
    expected_sha = str(metadata.get("report_sha256") or "").lower().strip()
    chunks_total = metadata.get("chunks")
    encoded_length = metadata.get("encoded_length")

    if not (1 <= len(tester) <= 120 and 1 <= len(hostname) <= 120):
        fail("identite invalide")
    if not isinstance(chunks_total, int) or not 1 <= chunks_total <= MAX_CHUNKS:
        fail("nombre de chunks invalide")
    if not isinstance(encoded_length, int) or not 1 <= encoded_length <= 900_000:
        fail("longueur encodee invalide")

    comments = fetch_all_comments(issue_number, token)
    encoded = parse_chunks(comments, chunks_total)
    if len(encoded) != encoded_length:
        fail("longueur encodee non conforme")
    report = decompress_report(encoded, expected_sha)

    created = str(issue.get("created_at") or "")
    try:
        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        created_dt = datetime.now(timezone.utc)

    stamp = created_dt.strftime("%Y%m%d-%H%M%S")
    filename = (
        f"{slugify(tester, 'testeur')}-{slugify(hostname, 'pincabos')}-"
        f"{stamp}-issue{issue_number}-system-audit.txt"
    )

    DEST.mkdir(parents=True, exist_ok=True)
    destination = DEST / filename
    if destination.exists():
        fail("rapport deja ingere")
    destination.write_text(report, encoding="utf-8")

    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"report_path={destination.as_posix()}\n")
            handle.write(f"report_sha256={expected_sha}\n")

    print(destination.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
