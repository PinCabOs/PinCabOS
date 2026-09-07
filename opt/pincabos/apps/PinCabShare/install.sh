#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/opt/pincabos/apps/PinCabShare
UNIT_SOURCE="$ROOT/systemd/pincabshare-v2.service"
UNIT_TARGET=/etc/systemd/system/pincabshare-v2.service
DATA=/srv/pincabshare/data
VIEW=/home/pinball/PinCabShare
RUNTIME=/run/pincabshare-v2
EXPORT=/etc/exports.d/pincabshare-v2.exports
AVAHI=/etc/avahi/services/pincabshare-v2.service
DEVICE_STATE=/var/lib/pincabos-link/device.json
COMMANDER=/opt/pincabos/web/pincabos_webapp_commander.py

fail() {
    printf 'NOGO [PINCABSHARE] %s\n' "$*" >&2
    exit 1
}

[[ "$EUID" -eq 0 ]] || fail "Lance ce script avec sudo."
id pinball >/dev/null 2>&1 || fail "Utilisateur pinball absent."
[[ -f "$ROOT/pincabshare.py" ]] || fail "Moteur PinCabShare absent."
[[ -f "$ROOT/gate_client.py" ]] || fail "Client gate absent."
[[ -f "$UNIT_SOURCE" ]] || fail "Unité systemd V2 absente."
[[ -f "$DEVICE_STATE" ]] || fail "Identité PinCabOS Link absente."

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/opt/pincabos/backups/pincabshare-v2-install/$STAMP"
install -d -o root -g root -m 0755 "$BACKUP"

for candidate in \
    /etc/systemd/system/pincabshare-mesh.service \
    /etc/systemd/system/pincabshare.service \
    /etc/systemd/system/pincabshare-v2.service \
    /etc/avahi/services/pincabshare.service \
    /etc/avahi/services/pincabshare-v2.service \
    /etc/exports.d/pincabshare.exports \
    /etc/exports.d/pincabshare-v2.exports \
    "$COMMANDER"
 do
    if [[ -e "$candidate" ]]; then
        cp -a "$candidate" "$BACKUP/$(basename "$candidate")"
    fi
done

printf 'GO [BACKUP] %s\n' "$BACKUP"

# Neutralise uniquement les anciens composants PinCabShare. Les données ne sont
# jamais supprimées.
systemctl disable --now pincabshare-mesh.service >/dev/null 2>&1 || true
systemctl disable --now pincabshare.service >/dev/null 2>&1 || true
rm -f \
    /etc/systemd/system/pincabshare-mesh.service \
    /etc/systemd/system/pincabshare.service \
    /etc/avahi/services/pincabshare.service \
    /etc/exports.d/pincabshare.exports

if command -v exportfs >/dev/null 2>&1; then
    exportfs -ra || true
fi

# Évite les redémarrages automatiques de services tiers par needrestart.
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=l
apt-get update
apt-get \
    -o Dpkg::Options::=--force-confold \
    -o Dpkg::Options::=--force-confdef \
    install -y --no-install-recommends \
    avahi-daemon avahi-utils nfs-common nfs-kernel-server

install -d -o pinball -g pinball -m 2775 "$DATA"
install -d -o pinball -g pinball -m 0755 "$VIEW"
install -d -o root -g root -m 0755 "$RUNTIME" "$RUNTIME/mounts"
install -d -o root -g root -m 0755 /etc/exports.d /etc/avahi/services

chmod 0755 \
    "$ROOT/pincabshare.py" \
    "$ROOT/gate_client.py" \
    "$ROOT/install.sh" \
    "$ROOT/uninstall.sh" \
    2>/dev/null || true
python3 -m py_compile "$ROOT/pincabshare.py" "$ROOT/gate_client.py"

# Commander doit afficher la vue dynamique V2. L'ancien « Partage PinCabOS »
# reste volontairement sur /home/pinball/Share pour les autres outils.
WEBAPP_PATCHED=0
if [[ -f "$COMMANDER" ]]; then
    python3 - "$COMMANDER" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = '"PinCabShare": Path("/home/pinball/Share")'
new = '"PinCabShare": Path("/home/pinball/PinCabShare")'

if new in text:
    print("GO [WEBAPP] PinCabShare déjà mappé vers la vue V2.")
elif text.count(old) == 1:
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("GO [WEBAPP] PinCabShare -> /home/pinball/PinCabShare")
else:
    raise SystemExit("NOGO [WEBAPP] ancre PinCabShare inattendue")
PY
    python3 -m py_compile "$COMMANDER" || fail "Commander invalide après patch."
    WEBAPP_PATCHED=1
fi

install -o root -g root -m 0644 "$UNIT_SOURCE" "$UNIT_TARGET"

# Toujours repartir fail-closed avant l'activation du daemon.
rm -f "$AVAHI" "$EXPORT"
exportfs -ra || fail "Impossible de recharger les exports NFS."
python3 "$ROOT/pincabshare.py" --close || fail "Nettoyage fail-closed impossible."

systemctl daemon-reload
systemctl enable avahi-daemon.service nfs-server.service >/dev/null
systemctl start avahi-daemon.service nfs-server.service
systemctl is-active --quiet avahi-daemon.service || fail "Avahi inactif."
systemctl is-active --quiet nfs-server.service || fail "NFS serveur inactif."

systemctl enable --now pincabshare-v2.service
sleep 3
systemctl is-active --quiet pincabshare-v2.service || fail "PinCabShare V2 inactif."

# Seule la WebApp est rechargée si sa source est présente. Aucun restart du
# Multiplayer, VPX ou VPinFE.
if [[ "$WEBAPP_PATCHED" -eq 1 ]] && systemctl list-unit-files pincabos-webapp.service >/dev/null 2>&1; then
    systemctl restart pincabos-webapp.service
    systemctl is-active --quiet pincabos-webapp.service || fail "WebApp inactive après reload."
fi

printf 'GO [SERVICE] pincabshare-v2.service actif.\n'
printf 'GO [DATA] %s conservé.\n' "$DATA"
printf 'GO [VIEW] %s géré automatiquement.\n' "$VIEW"
printf 'GO [TRANSPORT] NFS dynamique + Avahi découverte uniquement.\n'
printf 'GO [FAIL-CLOSED] aucun export permanent /24 et aucun SMB PinCabShare ajouté.\n'
printf 'GO [SAFETY] Multiplayer non modifié; VPX privé, BGFX privé et VPinFE non touchés.\n'

if [[ -f "$RUNTIME/status.json" ]]; then
    cat "$RUNTIME/status.json"
fi
