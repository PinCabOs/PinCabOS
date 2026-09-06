#!/usr/bin/env bash
# ===========================================================================
#  PINCABOS — BUILD-MASTER
#  Reconstruit une machine "master" PinCabOS complete depuis ce depot Git,
#  dans un chroot, sans cab physique ni GPU. Le resultat passe les controles
#  d'entree d'iso.sh (etape 4) : on peut ensuite y produire l'ISO officielle.
#
#  Pourquoi : aujourd'hui l'ISO est la photo d'une machine unique. Ce script
#  est la RECETTE qui permet de reconstruire cette machine depuis le depot :
#  si le master physique disparait, le projet reste reconstructible ; et un
#  contributeur peut produire/tester une ISO avec un simple PC Linux.
#
#  Usage :   sudo ./build-master.sh /chemin/du/master [/chemin/du/depot]
#            (depot par defaut : la racine Git contenant ce script)
#  Ensuite : chroot dans le master puis lancer opt/pincabos/script/iso.sh
#            (penser a monter proc/sys/dev et a bind-monter le master sur
#             lui-meme pour que `findmnt /` reponde : mount --bind M M)
#
#  Valide de bout en bout (aout 2026) : master reconstruit en chroot WSL2,
#  ISO produite par iso.sh sans modification, installee et jouee (VPinFE)
#  en VM QEMU puis sur cab reel.
# ===========================================================================
set -Eeuo pipefail

MASTER="${1:?usage: build-master.sh /chemin/du/master [/chemin/du/depot]}"

# PINCABOS_RECETTE_IDEMPOTENTE_V1 : la recette tourne sans personne devant. Toute
# commande qui poserait une question lit alors une fin de fichier et echoue, au
# lieu d attendre indefiniment une reponse (le blocage est bien plus couteux
# qu une erreur : il est invisible).
exec < /dev/null
REPO="${2:-$(cd "$(dirname "$0")/../../.." && pwd)}"
SUITE="resolute"          # Ubuntu 26.04
MIRROR="http://archive.ubuntu.com/ubuntu"
MANIFEST="$REPO/opt/pincabos/system-manifests/apt-packages.tsv"

[ "$(id -u)" -eq 0 ] || { echo "ERREUR: executer en root"; exit 1; }
[ -f "$MANIFEST" ] || { echo "ERREUR: manifest apt introuvable: $MANIFEST"; exit 1; }
[ -f "$REPO/opt/pincabos/script/iso.sh" ] || { echo "ERREUR: $REPO ne ressemble pas au depot PinCabOS"; exit 1; }

log() { echo; echo "=== $* ==="; }

# --- outils hote -----------------------------------------------------------
log "0) Outils hote"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq debootstrap rsync curl gpg zstd >/dev/null
# les debootstrap plus anciens ne connaissent pas encore la suite cible
if [ ! -e "/usr/share/debootstrap/scripts/$SUITE" ]; then
    ln -s gutsy "/usr/share/debootstrap/scripts/$SUITE"
fi

# --- montage/demontage du chroot ------------------------------------------
mount_chroot() {
    mount --bind /dev      "$MASTER/dev"     2>/dev/null || true
    mount --bind /dev/pts  "$MASTER/dev/pts" 2>/dev/null || true
    mount -t proc  proc    "$MASTER/proc"    2>/dev/null || true
    mount -t sysfs sys     "$MASTER/sys"     2>/dev/null || true
    cp /etc/resolv.conf "$MASTER/etc/resolv.conf" 2>/dev/null || true
}
umount_chroot() {
    umount -R "$MASTER/dev/pts" "$MASTER/dev" "$MASTER/proc" "$MASTER/sys" 2>/dev/null || true
}
trap umount_chroot EXIT

# --- A) base Ubuntu --------------------------------------------------------
log "A) debootstrap $SUITE -> $MASTER"
if [ ! -x "$MASTER/usr/bin/apt-get" ]; then
    debootstrap --arch=amd64 --components=main,restricted,universe,multiverse \
        "$SUITE" "$MASTER" "$MIRROR"
else
    echo "base deja presente, on continue"
fi

# --- B) paquets du manifest -----------------------------------------------
log "B) paquets du manifest ($(wc -l < "$MANIFEST") entrees)"
mount_chroot
# pas de demarrage de services dans le chroot
printf '#!/bin/sh\nexit 101\n' > "$MASTER/usr/sbin/policy-rc.d"
chmod +x "$MASTER/usr/sbin/policy-rc.d"

# sources completes + depot Google Chrome (seul paquet hors depots Ubuntu)
cat > "$MASTER/etc/apt/sources.list.d/ubuntu.sources" <<EOF
Types: deb
URIs: $MIRROR/
Suites: $SUITE $SUITE-updates $SUITE-backports
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: http://security.ubuntu.com/ubuntu/
Suites: $SUITE-security
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
rm -f "$MASTER/etc/apt/sources.list"

chroot "$MASTER" bash -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq curl ca-certificates gpg >/dev/null
    install -d -m 0755 /etc/apt/keyrings
    # PINCABOS_RECETTE_IDEMPOTENTE_V1 : sans --batch --yes, gpg demande
    # « File exists. Overwrite? (y/N) » des que la cle est deja la, c est-a-dire
    # a CHAQUE reconstruction sur un master existant. Il attendait alors une
    # reponse qui ne venait jamais : la recette restait bloquee a l etape B,
    # sans message et sans fin (nuit du 07/09/2026, cinq constructions perdues).
    curl -fsSL --retry 3 --max-time 60 https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --batch --yes --dearmor -o /etc/apt/keyrings/google-chrome.gpg
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list
    apt-get update -qq
'

# liste des paquets : noms sans :amd64.
# Le manifest du master historique contient dracut ET initramfs-tools (heritage
# d upgrades) : sur une base fraiche ils sont en conflit -> choix dracut,
# le standard Ubuntu 26.04 (la config dracut du depot est deja prevue pour).
awk -F'\t' '{print $1}' "$MANIFEST" | sed 's/:amd64$//' | sort -u \
    | grep -vE '^initramfs-tools(-bin|-core)?$' > "$MASTER/tmp/pkglist.txt"

chroot "$MASTER" bash -c '
    set -uo pipefail
    export DEBIAN_FRONTEND=noninteractive
    # pas de prompt grub (aucun disque a amorcer dans un chroot)
    echo "grub-pc grub-pc/install_devices_empty boolean true" | debconf-set-selections
    echo "grub-pc grub-pc/install_devices string"             | debconf-set-selections
    xargs -a /tmp/pkglist.txt apt-get install -y -qq \
        -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"
'

# les postinst NVIDIA font "update-initramfs -k $(uname -r)" : dans un chroot,
# uname -r renvoie le kernel de l HOTE, inconnu du chroot -> shim temporaire
# renvoyant le kernel cible le plus recent. (Le module dkms se compile contre
# les headers : AUCUN GPU n est necessaire.)
chroot "$MASTER" bash -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive
    KV=$(ls /lib/modules | sort -V | tail -1)
    printf "#!/bin/sh\n[ \"\$1\" = \"-r\" ] && { echo %s; exit 0; }\nexec /usr/bin/uname \"\$@\"\n" "$KV" \
        > /usr/local/bin/uname
    chmod +x /usr/local/bin/uname
    dpkg --configure -a
    rm -f /usr/local/bin/uname
'
echo "paquets installes : $(chroot "$MASTER" dpkg -l | grep -c '^ii')"

# --- C) couche PinCabOS (le depot) ----------------------------------------
log "C) overlay du depot"
rsync -a --exclude='.git' --exclude='.gitignore' "$REPO"/ "$MASTER"/

# Git ne versionne PAS les proprietaires : tout l overlay arrive en root.
# On retablit les domaines de l utilisateur pinball (uid/gid 1000, cf
# etc/passwd versionne). Le manifeste tmpfiles du depot prend le relais
# a CHAQUE boot pour les repertoires runtime.
chroot "$MASTER" bash -c '
    id pinball >/dev/null 2>&1 || true   # pinball vient de etc/passwd (overlay)
'
chown -R 1000:1000 "$MASTER/home/pinball"
chown -R 1000:1000 "$MASTER/opt/pincabos/web" "$MASTER/opt/pincabos/media-hunter" 2>/dev/null || true
if [ -f "$MASTER/usr/lib/tmpfiles.d/pincabos.conf" ]; then
    systemd-tmpfiles --root="$MASTER" --create 2>/dev/null || true
fi
# lightdm doit posseder son etat (uid/gid du passwd versionne)
LDM_UG=$(awk -F: '$1=="lightdm"{print $3":"$4}' "$MASTER/etc/passwd")
[ -n "$LDM_UG" ] && chown -R "$LDM_UG" "$MASTER/var/lib/lightdm" 2>/dev/null || true

# --- D) environnements Python de la WebApp --------------------------------
# (non versionnes dans le depot ; versions relevees sur le master de reference)
log "D) venvs WebApp"
cat > "$MASTER/tmp/req-web.txt" <<'EOF'
blinker==1.9.0
certifi==2026.5.20
charset_normalizer==3.4.7
click==8.4.1
flask==3.1.3
idna==3.18
itsdangerous==2.2.0
jinja2==3.1.6
markupsafe==3.0.3
packaging==26.2
psutil==7.2.2
requests==2.34.2
urllib3==2.6.3
waitress==3.0.2
werkzeug==3.1.5
EOF
cat > "$MASTER/tmp/req-media-hunter.txt" <<'EOF'
beautifulsoup4==4.15.0
certifi==2026.6.17
charset_normalizer==3.4.9
idna==3.18
requests==2.34.2
soupsieve==2.8.4
typing_extensions==4.16.0
urllib3==2.6.3
EOF
chroot "$MASTER" bash -c '
    set -e
    export PIP_DISABLE_PIP_VERSION_CHECK=1
    python3 -m venv /opt/pincabos/web/.venv
    /opt/pincabos/web/.venv/bin/pip install -q -r /tmp/req-web.txt
    python3 -m venv /opt/pincabos/media-hunter/venv
    /opt/pincabos/media-hunter/venv/bin/pip install -q -r /tmp/req-media-hunter.txt
'
chown -R 1000:1000 "$MASTER/opt/pincabos/web/.venv" "$MASTER/opt/pincabos/media-hunter/venv"

# --- E) zero identite, zero secret ----------------------------------------
# L image ne doit contenir AUCUNE identite machine : chaque cab genere la
# sienne au premier boot (sinon tous les cabs partagent les memes cles SSH).
log "E) sanitize + identite au premier boot"
rm -f "$MASTER"/etc/ssh/ssh_host_*
: > "$MASTER/etc/machine-id"
rm -f "$MASTER/var/lib/dbus/machine-id"
chroot "$MASTER" passwd -l root >/dev/null
rm -rf "$MASTER"/var/log/* "$MASTER"/var/cache/apt/archives/*.deb "$MASTER"/tmp/* 2>/dev/null || true

cat > "$MASTER/etc/systemd/system/pincabos-firstboot-identity.service" <<'EOF'
[Unit]
Description=PinCabOS first boot unique identity (SSH host keys, machine-id)
ConditionPathExists=!/etc/ssh/ssh_host_ed25519_key
Before=ssh.service sshd.service
After=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/ssh-keygen -A
ExecStart=/usr/bin/systemd-machine-id-setup

[Install]
WantedBy=multi-user.target
EOF
mkdir -p "$MASTER/etc/systemd/system/multi-user.target.wants"
ln -sf ../pincabos-firstboot-identity.service \
    "$MASTER/etc/systemd/system/multi-user.target.wants/pincabos-firstboot-identity.service"

# --- F) theme de demarrage + initrd ---------------------------------------
log "F) theme Plymouth + regeneration des initrd"
if [ -f "$MASTER/usr/share/plymouth/themes/pincabos/pincabos.plymouth" ]; then
    ln -sf /usr/share/plymouth/themes/pincabos/pincabos.plymouth \
        "$MASTER/etc/alternatives/default.plymouth" 2>/dev/null || true
fi
chroot "$MASTER" dracut --regenerate-all --force

# --- controle final : les portes d entree d iso.sh ------------------------
log "Controle final (equivalent iso.sh etape 4)"
ok=0; ko=0
chk() { if eval "$2"; then echo "  [OK] $1"; ok=$((ok+1)); else echo "  [KO] $1"; ko=$((ko+1)); fi; }
chk "/boot avec kernel"        "ls $MASTER/boot/vmlinuz-*    >/dev/null 2>&1"
chk "initrd presents"          "ls $MASTER/boot/initrd.img-* >/dev/null 2>&1"
chk "/lib/modules non vide"    "ls $MASTER/lib/modules/*     >/dev/null 2>&1"
chk "/etc/default/grub"        "test -f $MASTER/etc/default/grub"
chk "theme plymouth pincabos"  "test -f $MASTER/usr/share/plymouth/themes/pincabos/pincabos.plymouth"
chk "aucune cle SSH host"      "! ls $MASTER/etc/ssh/ssh_host_* >/dev/null 2>&1"
chk "machine-id vide"          "test ! -s $MASTER/etc/machine-id"

echo
if [ "$ko" -eq 0 ]; then
    echo "MASTER RECONSTRUIT : $ok/$((ok+ko)) controles OK."
    echo "Etape suivante : chroot \"$MASTER\" puis opt/pincabos/script/iso.sh"
    echo "  (mount --bind \"$MASTER\" \"$MASTER\" d abord, puis proc/sys/dev)"
else
    echo "ECHEC : $ko controle(s) manquant(s)."
    exit 1
fi
