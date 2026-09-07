#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/opt/pincabos/apps/PinCabShare
UNIT_SOURCE="$ROOT/systemd/pincabshare.service"
UNIT_TARGET=/etc/systemd/system/pincabshare.service
SMB_SOURCE="$ROOT/samba/pincabshare.conf"
SMB_INCLUDE=/etc/samba/pincabshare.conf
SMB_MAIN=/etc/samba/smb.conf
DATA=/srv/pincabshare/data
VIEW=/home/pinball/PinCabShare
AVAHI_SMB=/etc/avahi/services/pincabshare-smb.service
AVAHI_INTERCAB=/etc/avahi/services/pincabshare-intercab.service
LEGACY_UNIT=/etc/systemd/system/pincabshare-mesh.service
LEGACY_AVAHI=/etc/avahi/services/pincabshare.service
LEGACY_EXPORT=/etc/exports.d/pincabshare.exports

fail() {
    printf 'NOGO [PINCABSHARE] %s\n' "$*" >&2
    exit 1
}

[[ "$EUID" -eq 0 ]] || fail "Lance ce script avec sudo."
id pinball >/dev/null 2>&1 || fail "Utilisateur pinball absent."
[[ -f "$ROOT/pincabshare.py" ]] || fail "Moteur PinCabShare absent."
[[ -f "$UNIT_SOURCE" ]] || fail "Unité systemd absente."
[[ -f "$SMB_SOURCE" ]] || fail "Configuration SMB PinCabShare absente."
[[ -f /opt/pincabos/apps/VPX_MultiPlayers/sessions/current.json || -d /opt/pincabos/apps/VPX_MultiPlayers/sessions ]] \
    || fail "VPX_MultiPlayers sessions absent."

# Retire uniquement les artefacts du POC/V1 PinCabShare. Les données restent
# intactes et aucun service NFS générique du cabinet n'est arrêté/désinstallé.
STAMP="$(date +%Y%m%d-%H%M%S)"
LEGACY_BACKUP="/opt/pincabos/backups/pincabshare-v1-retired/$STAMP"
LEGACY_FOUND=0
for candidate in \
    "$LEGACY_UNIT" \
    "$LEGACY_AVAHI" \
    "$LEGACY_AVAHI.disabled" \
    "$LEGACY_EXPORT" \
    "$LEGACY_EXPORT.disabled"
do
    if [[ -e "$candidate" ]]; then
        if [[ "$LEGACY_FOUND" -eq 0 ]]; then
            install -d -o root -g root -m 0755 "$LEGACY_BACKUP"
            LEGACY_FOUND=1
        fi
        cp -a "$candidate" "$LEGACY_BACKUP/$(basename "$candidate")"
    fi
done

systemctl disable --now pincabshare-mesh.service >/dev/null 2>&1 || true
rm -f \
    "$LEGACY_UNIT" \
    "$LEGACY_AVAHI" \
    "$LEGACY_AVAHI.disabled" \
    "$LEGACY_EXPORT" \
    "$LEGACY_EXPORT.disabled"
if command -v exportfs >/dev/null 2>&1; then
    exportfs -ra || true
fi

# Préserve automatiquement les fichiers dpkg personnalisés PinCabOS.
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get \
    -o Dpkg::Options::=--force-confold \
    -o Dpkg::Options::=--force-confdef \
    install -y --no-install-recommends \
    avahi-daemon avahi-utils samba cifs-utils

install -d -o pinball -g pinball -m 2775 "$DATA"
install -d -o pinball -g pinball -m 0755 "$VIEW"
install -d -o root -g root -m 0755 /etc/avahi/services /etc/samba
chmod 0755 \
    "$ROOT/pincabshare.py" \
    "$ROOT/gate_client.py" \
    "$ROOT/close_intercab.py" \
    "$ROOT/install.sh" \
    2>/dev/null || true
install -o root -g root -m 0644 "$UNIT_SOURCE" "$UNIT_TARGET"
install -o root -g root -m 0644 "$SMB_SOURCE" "$SMB_INCLUDE"

# Sauvegarde avant la seule modification de smb.conf: un include idempotent.
[[ -f "$SMB_MAIN" ]] || cat > "$SMB_MAIN" <<'EOF'
[global]
    server role = standalone server
    server min protocol = SMB2
EOF

if ! grep -Fqx '    include = /etc/samba/pincabshare.conf' "$SMB_MAIN"; then
    BACKUP="$SMB_MAIN.pincabshare.bak.$(date +%Y%m%d-%H%M%S)"
    cp -a "$SMB_MAIN" "$BACKUP"
    python3 - "$SMB_MAIN" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
include = "    include = /etc/samba/pincabshare.conf"
lines = [line for line in lines if line.strip() != "include = /etc/samba/pincabshare.conf"]
try:
    start = next(i for i, line in enumerate(lines) if line.strip().lower() == "[global]")
except StopIteration:
    lines = ["[global]", include, ""] + lines
else:
    end = len(lines)
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            end = i
            break
    lines.insert(end, include)
path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
PY
fi

testparm -s >/dev/null || fail "Configuration Samba invalide."

# SMB LAN visible EN PERMANENCE, indépendamment du Lobby.
cat > "$AVAHI_SMB" <<'EOF'
<?xml version="1.0" standalone="no"?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">PinCabShare on %h</name>
  <service>
    <type>_smb._tcp</type>
    <port>445</port>
  </service>
</service-group>
EOF
chmod 0644 "$AVAHI_SMB"

# Les auto-liens CAB↔CAB partent toujours OFF.
rm -f "$AVAHI_INTERCAB"

systemctl daemon-reload
systemctl enable --now smbd.service avahi-daemon.service
systemctl restart smbd.service avahi-daemon.service
systemctl enable --now pincabshare.service
sleep 2

systemctl is-active --quiet smbd.service || fail "SMB PinCabShare inactif."
systemctl is-active --quiet pincabshare.service || fail "Service PinCabShare inactif."
ss -ltn | grep -Eq '[:.]445[[:space:]]' || fail "Port SMB 445 non écouté."

if [[ "$LEGACY_FOUND" -eq 1 ]]; then
    printf 'GO [MIGRATION] PinCabShare V1 neutralisé; backup: %s\n' "$LEGACY_BACKUP"
else
    printf 'GO [MIGRATION] Aucun artefact PinCabShare V1 détecté.\n'
fi
printf 'GO [SMB] \\\\IP-DU-CAB\\PinCabShare actif en permanence sur le LAN.\n'
printf 'GO [INTERCAB] auto-montage CAB↔CAB OFF hors Lobby/gate valide.\n'
printf 'GO [TRANSPORT] SMB/CIFS uniquement; aucun NFS PinCabShare actif.\n'
printf 'GO [SAFETY] VPX privé, BGFX privé et VPinFE non modifiés.\n'
