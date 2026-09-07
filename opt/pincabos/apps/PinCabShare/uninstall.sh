#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/opt/pincabos/apps/PinCabShare
UNIT=/etc/systemd/system/pincabshare-v2.service
AVAHI=/etc/avahi/services/pincabshare-v2.service
EXPORT=/etc/exports.d/pincabshare-v2.exports
RUNTIME=/run/pincabshare-v2
DATA=/srv/pincabshare/data

fail() {
    printf 'NOGO [PINCABSHARE] %s\n' "$*" >&2
    exit 1
}

[[ "$EUID" -eq 0 ]] || fail "Lance ce script avec sudo."

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/opt/pincabos/backups/pincabshare-v2-uninstall/$STAMP"
install -d -o root -g root -m 0755 "$BACKUP"

for candidate in "$UNIT" "$AVAHI" "$EXPORT"; do
    if [[ -e "$candidate" ]]; then
        cp -a "$candidate" "$BACKUP/$(basename "$candidate")"
    fi
done

# Le moteur sait distinguer les liens PinCabShare qu'il gère; on ne fait
# volontairement aucun find -delete générique dans la vue utilisateur.
if [[ -f "$ROOT/pincabshare.py" ]]; then
    python3 "$ROOT/pincabshare.py" --close || true
fi

systemctl disable --now pincabshare-v2.service >/dev/null 2>&1 || true
rm -f "$UNIT" "$AVAHI" "$EXPORT"
exportfs -ra >/dev/null 2>&1 || true
systemctl daemon-reload
rm -rf "$RUNTIME"

printf 'GO [UNINSTALL] service PinCabShare V2 retiré.\n'
printf 'GO [DATA] %s CONSERVÉ.\n' "$DATA"
printf 'GO [BACKUP] %s\n' "$BACKUP"
printf 'GO [SAFETY] Avahi/NFS système laissés installés; Multiplayer/VPX/VPinFE non modifiés.\n'
