#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
clear 2>/dev/null || true

EXPECTED_USER="pinball"
RAW_AUDIT="https://raw.githubusercontent.com/KarotsSugarpie/PinCabOS/main/DEV/config-testeur/pincabos-system-audit-v4.sh"
WORK_DIR="$HOME/.cache/pincabos-tester-report"
AUDIT_SCRIPT="$WORK_DIR/pincabos-system-audit-v4.sh"
RUNNER="$WORK_DIR/pincabos-system-audit-runner-v4.sh"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$WORK_DIR/audit-$STAMP.log"
STATUS_FILE="$WORK_DIR/audit-$STAMP.status"

say(){ printf '%s\n' "$*"; }

if [[ "$(id -un)" != "$EXPECTED_USER" ]]; then
  say "NOGO [PROTECTION] Ce lanceur doit etre execute comme utilisateur pinball."
  say "Utilisateur actuel : $(id -un)"
  exit 1
fi
command -v curl >/dev/null 2>&1 || { say "NOGO [PROTECTION] curl absent."; exit 1; }
command -v bash >/dev/null 2>&1 || { say "NOGO [PROTECTION] bash absent."; exit 1; }
command -v nohup >/dev/null 2>&1 || { say "NOGO [PROTECTION] nohup absent."; exit 1; }
command -v python3 >/dev/null 2>&1 || { say "NOGO [PROTECTION] python3 absent."; exit 1; }

say "================================================================"
say " PINFORGE-SAFE - PINCABOS TESTER SYSTEM AUDIT V4"
say " MODE RESILIENT SSH"
say " CLOUDFLARE GATEWAY -> GITHUB"
say " AUCUN TOKEN SUR LE CABINET"
say "================================================================"
say

# Le nom vient automatiquement de la session PinCabOS qui a jumele le cabinet.
# PINCABOS_SESSION_NAME = display_name du compte, sinon username.
# Aucun prompt interactif: un lancement automatique sans identite de session
# doit echouer proprement plutot que rester bloque en attente de saisie.
TESTER_NAME="${PINCABOS_SESSION_NAME:-${PINCABOS_TESTER_NAME:-}}"
TESTER_NAME="${TESTER_NAME#${TESTER_NAME%%[![:space:]]*}}"
TESTER_NAME="${TESTER_NAME%${TESTER_NAME##*[![:space:]]}}"

if [[ -z "$TESTER_NAME" ]]; then
  say "NOGO [SESSION] Nom de session PinCabOS absent."
  say "Le jumelage doit fournir PINCABOS_SESSION_NAME."
  exit 1
fi

say "GO [SESSION] Testeur : $TESTER_NAME"
say

mkdir -p "$WORK_DIR"
chmod 700 "$WORK_DIR"
TMP_SCRIPT="$WORK_DIR/.audit-v4-$STAMP.tmp"
curl -fsSL "$RAW_AUDIT" -o "$TMP_SCRIPT"
bash -n "$TMP_SCRIPT"
mv -f "$TMP_SCRIPT" "$AUDIT_SCRIPT"
chmod 700 "$AUDIT_SCRIPT"

cat > "$RUNNER" <<'RUNNER_EOF'
#!/usr/bin/env bash
set +e
umask 077
PINCABOS_TESTER_NAME="$PINCABOS_TESTER_NAME" bash "$PINCABOS_AUDIT_SCRIPT"
RC=$?
printf '%s\n' "$RC" > "$PINCABOS_STATUS_FILE"
exit "$RC"
RUNNER_EOF
chmod 700 "$RUNNER"
rm -f "$STATUS_FILE"

PINCABOS_TESTER_NAME="$TESTER_NAME" \
PINCABOS_AUDIT_SCRIPT="$AUDIT_SCRIPT" \
PINCABOS_STATUS_FILE="$STATUS_FILE" \
nohup "$RUNNER" >"$LOG_FILE" 2>&1 </dev/null &
PID=$!

say
say "GO [OK] Audit V4 lance en tache detachee."
say "PID     : $PID"
say "Journal : $LOG_FILE"
say "Token GitHub local : AUCUN"
say "SSH peut maintenant se couper sans interrompre l'audit."
say
say "Suivi en direct :"
say "----------------------------------------------------------------"

tail --pid="$PID" -n +1 -f "$LOG_FILE" 2>/dev/null || true

say "----------------------------------------------------------------"
if [[ -f "$STATUS_FILE" ]]; then
  RC="$(cat "$STATUS_FILE" 2>/dev/null || echo 1)"
  if [[ "$RC" == "0" ]]; then
    say "GO [OK] Audit termine et transmis."
  else
    say "NOGO [AUDIT] Le job a termine avec le code $RC."
  fi
else
  say "INFO Le suivi SSH s'est termine avant le job. Le job detache continue."
fi
say "Journal conserve : $LOG_FILE"
