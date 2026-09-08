#!/usr/bin/env bash
# PINCABOS_ISO_ETAPES_V1 — etape 80-live-rootfs d iso.sh (texte de l ancienne section, inchange)
set -Eeuo pipefail
. "$(dirname "$(readlink -f "$0")")/00-lib.sh"
trap cleanup_mounts EXIT

echo
echo "=== 9L) Live model: the payload becomes the live root filesystem ==="
echo "PINCABOS_ISO_MODELE_LIVE_V1"
rm -rf "$LIVE_ROOTFS" "$ISO_DIR"
mkdir -p "$LIVE_ROOTFS" "$ISO_DIR/casper"
tar --zstd -xpf "$ARCHIVE" -C "$LIVE_ROOTFS" --numeric-owner
test -d "$LIVE_ROOTFS/opt/pincabos" || die "live rootfs incomplete: $LIVE_ROOTFS/opt/pincabos missing"
test -d "$LIVE_ROOTFS/lib/modules" || die "live rootfs incomplete: no kernel modules"
ROOTFS_DIR="$LIVE_ROOTFS"
echo "GO [OK] live rootfs unpacked in $LIVE_ROOTFS"

echo
echo "=== 12) Ensure required live installer tools inside squashfs ==="
cp -L /etc/resolv.conf "$ROOTFS_DIR/etc/resolv.conf" || true   # -L : sous WSL ou systemd-resolved, un lien

echo
echo "--- PinCabOS hard reset apt sources inside live chroot ---"
mkdir -p "$ROOTFS_DIR/etc/apt/sources.list.d"
mkdir -p "$ROOTFS_DIR/etc/apt/pincabos-disabled-sources"
mkdir -p "$ROOTFS_DIR/etc/apt/pincabos-empty-sourceparts"

# Disable every sourceparts file, including ubuntu.sources.
# This avoids both file:/cdrom and duplicate source warnings.
while IFS= read -r aptsrc; do
  [ -f "$aptsrc" ] || continue
  rel="${aptsrc#$ROOTFS_DIR/}"
  safe="$(echo "$rel" | tr '/' '_')"
  echo "Disabling apt sourceparts file: /$rel"
  cp -a "$aptsrc" "$ROOTFS_DIR/etc/apt/pincabos-disabled-sources/${safe}.bak" || true
  mv "$aptsrc" "$ROOTFS_DIR/etc/apt/pincabos-disabled-sources/${safe}.disabled" || true
done < <(find "$ROOTFS_DIR/etc/apt/sources.list.d" -maxdepth 1 -type f \( -name '*.list' -o -name '*.sources' \) 2>/dev/null | sort)

cat > "$ROOTFS_DIR/etc/apt/sources.list" <<'PINCABOS_APT_SOURCES'
deb http://archive.ubuntu.com/ubuntu resolute main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu resolute-updates main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu resolute-backports main restricted universe multiverse
deb http://security.ubuntu.com/ubuntu resolute-security main restricted universe multiverse
PINCABOS_APT_SOURCES

rm -rf "$ROOTFS_DIR/var/lib/apt/lists"
mkdir -p "$ROOTFS_DIR/var/lib/apt/lists/partial"

echo "--- Final active apt sources.list ---"
cat "$ROOTFS_DIR/etc/apt/sources.list"

echo "--- Final sourceparts directory should be empty ---"
find "$ROOTFS_DIR/etc/apt/sources.list.d" -maxdepth 1 -type f -print || true

if grep -RniE 'cdrom:|file:/cdrom' "$ROOTFS_DIR/etc/apt/sources.list" "$ROOTFS_DIR/etc/apt/sources.list.d" 2>/dev/null; then
  die "Active cdrom apt source still present after hard reset"
fi
echo "OK: active apt sources have no cdrom/file:/cdrom"

mount --bind /dev "$ROOTFS_DIR/dev"
mount --bind /proc "$ROOTFS_DIR/proc"
mount --bind /sys "$ROOTFS_DIR/sys"
mount --bind /run "$ROOTFS_DIR/run"

APT_FORCE_OPTS=(
  -o Dir::Etc::sourcelist=/etc/apt/sources.list
  -o Dir::Etc::sourceparts=/etc/apt/pincabos-empty-sourceparts
  -o APT::Get::List-Cleanup=0
)

# cache apt persistant entre les builds (les .deb survivent au menage)
mkdir -p "$CACHE_DIR/apt-archives"
# PINCABOS_ISO_APT_CACHE_MOUNTPOINT_V1 : le payload exclut ./var/cache/* ; le point de
# montage n existe donc pas dans le rootfs live (« mount point does not exist », vu a
# l execution reelle sur VM). apt le recreerait de toute facon.
mkdir -p "$ROOTFS_DIR/var/cache/apt/archives/partial"
mount --bind "$CACHE_DIR/apt-archives" "$ROOTFS_DIR/var/cache/apt/archives"
chroot "$ROOTFS_DIR" apt-get "${APT_FORCE_OPTS[@]}" update
DEBIAN_FRONTEND=noninteractive chroot "$ROOTFS_DIR" apt-get "${APT_FORCE_OPTS[@]}" install -y \
  zstd \
  parted \
  gdisk \
  dosfstools \
  e2fsprogs \
  util-linux \
  coreutils \
  sudo \
  grub-efi-amd64-bin \
  ca-certificates \
  plymouth \
  plymouth-label \
  fontconfig \
  casper \
  kbd \
  console-setup \
  xserver-xorg-core \
  xserver-xorg-video-all \
  xinit \
  x11-xserver-utils \
  openbox \
  python3-gi \
  gir1.2-webkit-6.0 \
  python3-flask \
  curl \
  fonts-dejavu-core \
  libgl1-mesa-dri

echo
echo "--- PinCabOS: dist-upgrade du live (kernel tenu) + menage apt du live ---"
chroot "$ROOTFS_DIR" bash -c "
  export DEBIAN_FRONTEND=noninteractive
  apt-mark hold linux-generic linux-image-generic linux-headers-generic 2>/dev/null || true
  apt-get -y -qq -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold dist-upgrade 2>&1 | tail -3
  apt-get -y -qq purge mdadm 2>&1 | tail -1
  apt-get -y -qq autoremove --purge 2>&1 | tail -2
"
umount "$ROOTFS_DIR/var/cache/apt/archives"
rm -rf "$ROOTFS_DIR/var/lib/apt/lists"/* "$ROOTFS_DIR/var/cache/apt/archives"/*.deb

echo
echo "--- PinCabOS: theme Plymouth + regeneration initrd live (base server) ---"
mkdir -p "$ROOTFS_DIR/usr/share/plymouth/themes" "$ROOTFS_DIR/etc/plymouth"
cp -a "$SRC/usr/share/plymouth/themes/pincabos" "$ROOTFS_DIR/usr/share/plymouth/themes/"
# Splash du LIVE : la mascotte "Tux au flipper" (theme install de Karots),
# le systeme installe garde le logo classique.
cp "$SRC/usr/share/plymouth/themes/pincabos-install/PCOSLinuxWP.png" \
   "$ROOTFS_DIR/usr/share/plymouth/themes/pincabos/pincabos.png"
printf '[Daemon]\nTheme=pincabos\nShowDelay=0\n' > "$ROOTFS_DIR/etc/plymouth/plymouthd.conf"
# Le plugin "script" n est pas dans le paquet plymouth de base : on le garantit.
DEBIAN_FRONTEND=noninteractive chroot "$ROOTFS_DIR" apt-get install -y -qq plymouth-themes 2>/dev/null || true
PLY_LIB="usr/lib/x86_64-linux-gnu/plymouth"
if [ ! -f "$ROOTFS_DIR/$PLY_LIB/script.so" ]; then
  cp "$SRC/$PLY_LIB/script.so" "$ROOTFS_DIR/$PLY_LIB/script.so"
fi
[ ! -f "$SRC/$PLY_LIB/label.so" ] || cp -n "$SRC/$PLY_LIB/label.so" "$ROOTFS_DIR/$PLY_LIB/" || true
chroot "$ROOTFS_DIR" update-alternatives --install \
  /usr/share/plymouth/themes/default.plymouth default.plymouth \
  /usr/share/plymouth/themes/pincabos/pincabos.plymouth 200
chroot "$ROOTFS_DIR" update-alternatives --set default.plymouth \
  /usr/share/plymouth/themes/pincabos/pincabos.plymouth
[ ! -x "$ROOTFS_DIR/usr/sbin/plymouth-set-default-theme" ] \
  || chroot "$ROOTFS_DIR" /usr/sbin/plymouth-set-default-theme pincabos
echo "--- PinCabOS: reseau DHCP du live ---"
mkdir -p "$ROOTFS_DIR/etc/netplan"
cat > "$ROOTFS_DIR/etc/netplan/01-pincabos-live-dhcp.yaml" <<'PCO_NET'
# pincabos-live-dhcp : DHCP simple sur toute interface ethernet du live
network:
  version: 2
  ethernets:
    all-en:
      match: {name: "en*"}
      dhcp4: true
      optional: true
PCO_NET
chmod 600 "$ROOTFS_DIR/etc/netplan/01-pincabos-live-dhcp.yaml"

echo "--- PinCabOS: hostname du live ---"
echo pincabos-installer > "$ROOTFS_DIR/etc/hostname"
printf '127.0.0.1 localhost\n127.0.1.1 pincabos-installer\n' > "$ROOTFS_DIR/etc/hosts"

echo "--- PinCabOS: installeur GUI (wizard + kiosk + dispatch) ---"
mkdir -p "$ROOTFS_DIR/opt/pincabos/installer-gui"
cp -a "$SRC/opt/pincabos/installer-gui/." "$ROOTFS_DIR/opt/pincabos/installer-gui/"
install -m 755 "$SRC"/usr/local/sbin/pincabos-installer-dispatch \
  "$ROOTFS_DIR/usr/local/sbin/pincabos-installer-dispatch"
install -m 755 "$SRC"/usr/local/bin/pincabos-kiosk.py \
  "$ROOTFS_DIR/usr/local/bin/pincabos-kiosk.py"
install -m 755 "$SRC"/usr/local/bin/pincabos-kiosk-session \
  "$ROOTFS_DIR/usr/local/bin/pincabos-kiosk-session"
# PINCABOS_INSTALLEUR_UN_SEUL_CHEMIN_V1 : plus d'installeur texte de secours ;
# si le kiosque ne tient pas, la panne est annoncee en clair sur tty1.
install -m 755 "$SRC"/usr/local/sbin/pincabos-installer-failure \
  "$ROOTFS_DIR/usr/local/sbin/pincabos-installer-failure"
cp "$SRC"/etc/systemd/system/pincabos-gui-wizard.service \
   "$SRC"/etc/systemd/system/pincabos-gui-kiosk.service \
   "$SRC"/etc/systemd/system/pincabos-installer-failure.service \
   "$ROOTFS_DIR/etc/systemd/system/"
rm -f "$ROOTFS_DIR/usr/local/sbin/pincabos-gui-fallback" \
      "$ROOTFS_DIR/usr/local/sbin/pincabos-live-installer-console" \
      "$ROOTFS_DIR/etc/systemd/system/pincabos-tui-fallback.service"
mkdir -p "$ROOTFS_DIR/etc/X11/xorg.conf.d"
# PINCABOS_LIVE_XORG_AUTO_V1
# Le live imposait « Driver "modesetting" » pour le kiosque. Sur une carte
# NVIDIA propriétaire c'est fatal : modesetting ne sait pas créer de ressources
# d'écran sur un nœud DRM nvidia, et une section Device explicite ÉCRASE
# l'OutputClass que le pilote installe (/usr/share/X11/xorg.conf.d/10-nvidia.conf,
# « MatchDriver nvidia-drm / Driver nvidia »). L'assistant graphique ne démarrait
# donc jamais sur un cab NVIDIA — constaté sur celui de Yann (RTX 3070 Ti,
# 08/09/2026) : « (EE) failed to create screen resources », kiosque relancé trois
# fois puis abandon, alors que le système installé démarre parfaitement.
# Sans section Device, Xorg choisit seul : l'OutputClass NVIDIA s'applique sur
# NVIDIA, et modesetting reste le choix automatique partout ailleurs (Intel, AMD,
# VM). On ne pose donc plus rien ici — la disposition clavier reste, elle.
rm -f "$ROOTFS_DIR/etc/X11/xorg.conf.d/10-pincabos-kiosk.conf"
echo "OK: installeur GUI embarque dans le live (Xorg choisit son pilote seul)"

# PINCABOS_ISO_LIVE_KVER_V1
# Le live embarque le noyau le plus recent du rootfs. Des qu une reconstruction
# en installe un second (07/09/2026 : 7.0.0-31 pose par-dessus le 29), l ISO
# demarre sur un noyau que personne n a essaye en live. Le 31 s est revele bon
# sur le cab de Yann (RTX 3070 Ti, installe et redemarre) : ce n est donc pas une
# regression du noyau, mais le choix reste implicite. PCO_LIVE_KVER permet de
# figer celui du live pour reproduire une construction ou revenir en arriere.
LIVE_KVER="${PCO_LIVE_KVER:-$(ls "$ROOTFS_DIR/lib/modules" | sort -V | tail -1)}"
[ -d "$ROOTFS_DIR/lib/modules/$LIVE_KVER" ] || die "noyau demande absent du live : $LIVE_KVER"
echo "--- PinCabOS: noyau du live = $LIVE_KVER ---"
DEBIAN_FRONTEND=noninteractive chroot "$ROOTFS_DIR" update-initramfs -c -k "$LIVE_KVER" \
  || DEBIAN_FRONTEND=noninteractive chroot "$ROOTFS_DIR" update-initramfs -u -k "$LIVE_KVER"
cp "$ROOTFS_DIR/boot/initrd.img-$LIVE_KVER" "$ISO_DIR/casper/initrd"
if [ -f "$ROOTFS_DIR/boot/vmlinuz-$LIVE_KVER" ]; then
  cp "$ROOTFS_DIR/boot/vmlinuz-$LIVE_KVER" "$ISO_DIR/casper/vmlinuz"
fi
# PINCABOS_ISO_GREP_SANS_SIGPIPE_V1 : sous `set -o pipefail`, `lsinitramfs | grep -q` rend
# 141 (grep quitte a la premiere ligne, lsinitramfs recoit SIGPIPE) alors que le plugin est
# bien la : « Plugin script.so absent » sur le banc, trois fois, avec un initrd correct. La
# liste est prise une fois, les tests se font dessus.
INITRD_LISTE="$(lsinitramfs "$ISO_DIR/casper/initrd")"
grep -q "themes/pincabos/pincabos.script" <<<"$INITRD_LISTE" \
  || die "Theme pincabos absent de l initrd live"
grep -q "plymouth/script.so" <<<"$INITRD_LISTE" \
  || die "Plugin script.so absent de l initrd live"
echo "OK: initrd live regenere avec plymouth+casper ($LIVE_KVER), theme pincabos verifie"

cleanup_mounts

echo
echo "=== 13) Disable Ubuntu Welcome/GDM and force PinCabOS tty installer ==="
mkdir -p "$ROOTFS_DIR/etc/systemd/system"
mkdir -p "$ROOTFS_DIR/etc/systemd/system/multi-user.target.wants"

ln -sfn /lib/systemd/system/multi-user.target "$ROOTFS_DIR/etc/systemd/system/default.target"
ln -sfn /dev/null "$ROOTFS_DIR/etc/systemd/system/display-manager.service"
ln -sfn /dev/null "$ROOTFS_DIR/etc/systemd/system/gdm.service"
ln -sfn /dev/null "$ROOTFS_DIR/etc/systemd/system/gdm3.service"

echo
echo "--- Disable unused CUPS services in live ISO to avoid reboot/shutdown delay ---"
echo "PINCABOS_LIVE_DISABLE_CUPS_SHUTDOWN_DELAY_V1"
for unit in cups.service cups.socket cups.path cups-browsed.service; do
  echo "Masking live unit: $unit"
  ln -sfn /dev/null "$ROOTFS_DIR/etc/systemd/system/$unit" || true
done

DISABLED_DIR="$ROOTFS_DIR/var/lib/pincabos-disabled-ubuntu-welcome"
mkdir -p "$DISABLED_DIR"

while IFS= read -r f; do
  [ -f "$f" ] || continue
  rel="${f#$ROOTFS_DIR/}"
  safe="$(echo "$rel" | tr '/' '_')"
  echo "Disabling: /$rel"
  cp -a "$f" "$DISABLED_DIR/$safe" || true
  mv "$f" "$f.disabled-by-pincabos" || true
done < <(find "$ROOTFS_DIR" -xdev -type f \( \
  -path '*/etc/xdg/autostart/*' -o \
  -path '*/usr/share/applications/*' -o \
  -path '*/etc/systemd/system/*' -o \
  -path '*/lib/systemd/system/*' -o \
  -path '*/usr/lib/systemd/system/*' \
\) \( \
  -iname '*ubuntu*welcome*' -o \
  -iname '*ubuntu*bootstrap*' -o \
  -iname '*ubuntu*desktop*installer*' -o \
  -iname '*subiquity*' -o \
  -iname '*casper*installer*' \
\) | sort)

mkdir -p "$ROOTFS_DIR/usr/local/sbin"

install -m 755 "$INSTALLER_SRC/pincabos-live-installer" "$ROOTFS_DIR/usr/local/sbin/pincabos-live-installer" \
  || die "live installer missing: $INSTALLER_SRC/pincabos-live-installer"

bash -n "$ROOTFS_DIR/usr/local/sbin/pincabos-live-installer" \
  || die "Live installer has a Bash syntax error"
echo "GO [OK] live installer syntax valid"

echo
echo "=== PinCabOS lean live TTY boot ==="
echo "PINCABOS_LIVE_TTY_BOOT_NO_CYCLE_V1"

mkdir -p \
  "$ROOTFS_DIR/etc/systemd/system" \
  "$ROOTFS_DIR/etc/systemd/system/multi-user.target.wants" \
  "$ROOTFS_DIR/usr/local/sbin"

echo
echo "--- Set stable live hostname ---"

printf 'pincabos-live\n' > "$ROOTFS_DIR/etc/hostname"

if [ -f "$ROOTFS_DIR/etc/hosts" ]; then
  sed -i \
    '/^[[:space:]]*127\.0\.1\.1[[:space:]]/d' \
    "$ROOTFS_DIR/etc/hosts"
else
  printf '127.0.0.1 localhost\n' > "$ROOTFS_DIR/etc/hosts"
fi

printf '127.0.1.1 pincabos-live\n' \
  >> "$ROOTFS_DIR/etc/hosts"

echo
echo "--- Mask unnecessary desktop/live background services ---"

LIVE_MASK_UNITS=(
  casper-md5check.service
  cloud-init-local.service
  cloud-init.service
  cloud-config.service
  cloud-final.service
  cloud-init.target
  snapd.service
  snapd.socket
  snapd.seeded.service
  snapd.autoimport.service
  apt-daily.service
  apt-daily.timer
  apt-daily-upgrade.service
  apt-daily-upgrade.timer
  unattended-upgrades.service
  packagekit.service
  NetworkManager-wait-online.service
  systemd-networkd-wait-online.service
  fwupd.service
  fwupd-refresh.service
  fwupd-refresh.timer
  whoopsie.service
  apport.service
)
# plymouth n est plus masque : le live affiche le splash PinCabOS (theme via 17b)

for unit in "${LIVE_MASK_UNITS[@]}"; do
  echo "Masking live-only unit: $unit"
  ln -sfn /dev/null \
    "$ROOTFS_DIR/etc/systemd/system/$unit"
done

# tty1 belongs exclusively to the PinCabOS installer.
ln -sfn /dev/null \
  "$ROOTFS_DIR/etc/systemd/system/getty@tty1.service"

ln -sfn /dev/null \
  "$ROOTFS_DIR/etc/systemd/system/autovt@tty1.service"

install -m 755 "$INSTALLER_SRC/pincabos-live-installer-wait" "$ROOTFS_DIR/usr/local/sbin/pincabos-live-installer-wait" \
  || die "live installer wait missing: $INSTALLER_SRC/pincabos-live-installer-wait"


# PINCABOS_INSTALLEUR_UN_SEUL_CHEMIN_V1 : l'installeur texte (console tty1)
# n'existe plus ; tty1 lance l'assistant graphique via le dispatch.
install -m 644 "$INSTALLER_SRC/pincabos-live-installer-tty.service" "$ROOTFS_DIR/etc/systemd/system/pincabos-live-installer-tty.service" \
  || die "live installer tty unit missing: $INSTALLER_SRC/pincabos-live-installer-tty.service"

ln -sfn ../pincabos-live-installer-tty.service \
  "$ROOTFS_DIR/etc/systemd/system/multi-user.target.wants/pincabos-live-installer-tty.service"
