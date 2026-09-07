#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
clear 2>/dev/null || true

EXPECTED_USER="pinball"
LAUNCHER_URL="https://raw.githubusercontent.com/PinCabOs/PinCabOS/653f23a8701b7ef7b292e7a69fd2069ee4fb8fb0/DEV/config-testeur/pincabos-system-audit-launcher.sh"
SITE_AUDIT_URL="${PINCABOS_SITE_AUDIT_URL:-https://pincabos.cc/api/device/audits}"
WORK_DIR="$HOME/.cache/pincabos-tester-report"
STAMP="$(date +%Y%m%d-%H%M%S)"
TMP_LAUNCHER="$WORK_DIR/.auto-launcher-$STAMP.sh"
START_EPOCH="$(date +%s)"

say(){ printf '%s\n' "$*"; }

if [[ "$(id -un)" != "$EXPECTED_USER" ]]; then
  say "NOGO [PROTECTION] Ce lanceur doit etre execute comme utilisateur pinball."
  exit 1
fi

command -v curl >/dev/null 2>&1 || { say "NOGO [PROTECTION] curl absent."; exit 1; }
command -v python3 >/dev/null 2>&1 || { say "NOGO [PROTECTION] python3 absent."; exit 1; }

SESSION_NAME="${PINCABOS_SESSION_NAME:-}"
SESSION_NAME="${SESSION_NAME#${SESSION_NAME%%[![:space:]]*}}"
SESSION_NAME="${SESSION_NAME%${SESSION_NAME##*[![:space:]]}}"

if [[ -z "$SESSION_NAME" ]]; then
  say "NOGO [SESSION] PINCABOS_SESSION_NAME absent."
  exit 2
fi

DEVICE_TOKEN="${PINCABOS_DEVICE_TOKEN:-}"
if [[ -z "$DEVICE_TOKEN" && -n "${PINCABOS_DEVICE_TOKEN_FILE:-}" ]]; then
  TOKEN_FILE="$PINCABOS_DEVICE_TOKEN_FILE"
  if [[ ! -f "$TOKEN_FILE" ]]; then
    say "NOGO [TOKEN] Fichier token absent."
    exit 3
  fi
  DEVICE_TOKEN="$(cat "$TOKEN_FILE")"
fi

if [[ -z "$DEVICE_TOKEN" ]]; then
  say "NOGO [TOKEN] Token appareil absent."
  exit 3
fi

mkdir -p "$WORK_DIR"
chmod 700 "$WORK_DIR"

say "================================================================"
say " PINFORGE-SAFE — AUDIT AUTOMATIQUE POST-JUMELAGE"
say " SESSION : $SESSION_NAME"
say " RAPPORT -> PINCABOS.CC"
say " TOKEN JAMAIS AFFICHE"
say "================================================================"

curl -fsSL "$LAUNCHER_URL" -o "$TMP_LAUNCHER"
bash -n "$TMP_LAUNCHER"
chmod 700 "$TMP_LAUNCHER"

set +e
PINCABOS_SESSION_NAME="$SESSION_NAME" bash "$TMP_LAUNCHER"
AUDIT_RC=$?
set -e
rm -f "$TMP_LAUNCHER"

REPORT="$(
  find "$HOME" -maxdepth 1 -type f -name '*-system-audit.txt' -printf '%T@ %p\n' 2>/dev/null \
    | awk -v start="$START_EPOCH" '$1 >= start {sub(/^[^ ]+ /,""); print}' \
    | tail -n 1
)"

if [[ -z "$REPORT" || ! -f "$REPORT" ]]; then
  say "NOGO [AUDIT] Aucun rapport local cree."
  exit "${AUDIT_RC:-4}"
fi

say "GO [AUDIT LOCAL] $(basename "$REPORT")"

PINCABOS_DEVICE_TOKEN="$DEVICE_TOKEN" \
PINCABOS_SITE_AUDIT_URL="$SITE_AUDIT_URL" \
PINCABOS_REPORT="$REPORT" \
PINCABOS_SESSION_NAME="$SESSION_NAME" \
python3 <<'PY'
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

url = os.environ['PINCABOS_SITE_AUDIT_URL']
token = os.environ['PINCABOS_DEVICE_TOKEN'].strip()
report = Path(os.environ['PINCABOS_REPORT']).resolve()
session_name = os.environ['PINCABOS_SESSION_NAME'].strip()

if not report.is_file():
    raise SystemExit('NOGO [UPLOAD] Rapport absent.')
raw = report.read_bytes()
if not raw or len(raw) > 8 * 1024 * 1024:
    raise SystemExit('NOGO [UPLOAD] Taille rapport invalide.')

req = urllib.request.Request(
    url,
    data=raw,
    method='POST',
    headers={
        'Authorization': 'PinCabOS-Device ' + token,
        'Content-Type': 'text/plain; charset=utf-8',
        'X-PinCabOS-Session-Name': session_name,
        'X-PinCabOS-Report-Name': report.name,
        'User-Agent': 'PinCabOS-Auto-Audit/1',
        'Accept': 'application/json',
    },
)
try:
    with urllib.request.urlopen(req, timeout=90) as response:
        body = response.read().decode('utf-8', errors='replace')
        data = json.loads(body) if body else {}
except urllib.error.HTTPError as exc:
    detail = exc.read().decode('utf-8', errors='replace')[:500]
    raise SystemExit(f'NOGO [UPLOAD] HTTP {exc.code}: {detail}')
except urllib.error.URLError as exc:
    raise SystemExit(f'NOGO [UPLOAD] {exc.reason}')

if not data.get('ok'):
    raise SystemExit('NOGO [UPLOAD] Serveur a refuse le rapport.')

print('GO [UPLOAD PINCABOS.CC] audit_id=' + str(data.get('audit_id') or ''))
PY

unset DEVICE_TOKEN
say "GO [POST-JUMELAGE] Audit automatique termine."
exit 0
