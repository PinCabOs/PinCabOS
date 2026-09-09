#!/usr/bin/env bash
# PinCabOS — live ISO builder ("the ISO *is* PinCabOS").
#
# Instead of grafting the system onto an Ubuntu Server ISO and shipping it as a
# split tarball, we photograph the prepared rootfs as a bootable squashfs. The
# very same image then serves three purposes:
#
#   * Try PinCabOS without installing (casper boots the system read-only)
#   * install it (the payload helper deploys with unsquashfs — see iso.sh)
#   * rescue / text install fallback
#
# Measured against the current model: 2.7 GB instead of 4.6, ~3 min of zstd
# instead of ~10 min of xz, and no Ubuntu ISO to download.
#
# Usage:
#   iso-live.sh [--rootfs DIR] [--payload DIR] [--out FILE] [--level N]
#
#   --rootfs   prepared PinCabOS root filesystem (default: $ROOTFS_DIR or
#              /root/pco-master)
#   --installer overlay holding the live installer components (engine,
#              dispatcher, tty unit) to drop into the rootfs before it is
#              compressed. Without them the ISO boots but cannot install.
#   --payload  payload directory produced by iso.sh (helper script + Plymouth
#              overlay). Optional: without it the ISO still boots and installs,
#              it just carries no post-install helper.
#   --out      output ISO (default: /root/pincabos-live.iso)
#   --level    zstd compression level (default 19; use 10 for quick test runs)
set -euo pipefail

ROOTFS="${ROOTFS_DIR:-/root/pco-master}"
PAYLOAD_SRC=""
INSTALLER_SRC=""
OUT_ISO="/root/pincabos-live.iso"
ZSTD_LEVEL=19
KERNEL_VERSION=""

while [ $# -gt 0 ]; do
  case "$1" in
    --rootfs)  ROOTFS="$2"; shift 2 ;;
    --payload) PAYLOAD_SRC="$2"; shift 2 ;;
    --installer) INSTALLER_SRC="$2"; shift 2 ;;
    --out)     OUT_ISO="$2"; shift 2 ;;
    --level)   ZSTD_LEVEL="$2"; shift 2 ;;
    --kernel)  KERNEL_VERSION="$2"; shift 2 ;;
    -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

die() { echo "ERROR: $*" >&2; exit 1; }

# mkinitramfs needs a real /proc, /sys and /dev inside the chroot; without them
# it silently produces an initrd casper cannot boot from.
PSEUDO_MOUNTED=0
mount_pseudo() {
  mountpoint -q "$ROOTFS/proc" || mount -t proc proc "$ROOTFS/proc"
  mountpoint -q "$ROOTFS/sys"  || mount -t sysfs sys "$ROOTFS/sys"
  if ! mountpoint -q "$ROOTFS/dev"; then
    mount --bind /dev "$ROOTFS/dev"
    # Keep the bind private: a shared mount would propagate the later umount
    # back to the host and take its /dev/pts down with it.
    mount --make-rprivate "$ROOTFS/dev" 2>/dev/null || true
  fi
  mountpoint -q "$ROOTFS/dev/pts" || mount --bind /dev/pts "$ROOTFS/dev/pts" 2>/dev/null || true
  PSEUDO_MOUNTED=1
}
umount_pseudo() {
  [ "$PSEUDO_MOUNTED" = 1 ] || return 0
  umount "$ROOTFS/dev/pts" 2>/dev/null || true
  umount "$ROOTFS/dev" 2>/dev/null || true
  umount "$ROOTFS/sys" 2>/dev/null || true
  umount "$ROOTFS/proc" 2>/dev/null || true
  PSEUDO_MOUNTED=0
}
trap umount_pseudo EXIT

[ "$(id -u)" -eq 0 ] || die "root required"
[ -d "$ROOTFS" ] || die "rootfs not found: $ROOTFS"
[ -d "$ROOTFS/opt/pincabos" ] || die "$ROOTFS does not look like a PinCabOS root"

TREE="$ROOTFS/tmp/live-iso"
SQUASHFS="$TREE/casper/filesystem.squashfs"
PAYLOAD_DST="$TREE/pincabos-payload"
START=$(date +%s)

echo "=== 1) Live rootfs preparation ==="
mount_pseudo
# casper drives the live boot; it must live inside the image we are about to
# compress, not on the build host.
# PINCABOS_ISO_LIVE_OUTILS_V1 : grub-mkrescue tourne dans le chroot (section 6),
# le rootfs doit donc porter GRUB EFI/BIOS, xorriso et mtools ; un cab ne les a
# pas forcement. On n installe que ce qui manque.
MANQUANTS=""
[ -x "$ROOTFS/usr/share/initramfs-tools/scripts/casper" ] || [ -d "$ROOTFS/usr/share/casper" ] || MANQUANTS="$MANQUANTS casper"
[ -x "$ROOTFS/usr/bin/grub-mkrescue" ] || MANQUANTS="$MANQUANTS grub-common"
[ -d "$ROOTFS/usr/lib/grub/x86_64-efi" ] || MANQUANTS="$MANQUANTS grub-efi-amd64-bin"
[ -d "$ROOTFS/usr/lib/grub/i386-pc" ] || MANQUANTS="$MANQUANTS grub-pc-bin"
[ -x "$ROOTFS/usr/bin/xorriso" ] || MANQUANTS="$MANQUANTS xorriso"
[ -x "$ROOTFS/usr/bin/mformat" ] || MANQUANTS="$MANQUANTS mtools"
if [ -n "$MANQUANTS" ]; then
  echo "  installing into the rootfs:$MANQUANTS"
  cp -a /etc/resolv.conf "$ROOTFS/etc/resolv.conf" 2>/dev/null || true
  chroot "$ROOTFS" env DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1 || true
  # shellcheck disable=SC2086
  chroot "$ROOTFS" env DEBIAN_FRONTEND=noninteractive \
    apt-get install -y -qq $MANQUANTS >/dev/null 2>&1 \
    || die "cannot install$MANQUANTS (no network in chroot?)"
fi

cat > "$ROOTFS/etc/casper.conf" <<'CASPER'
export USERNAME="pinball"
export USERFULLNAME="PinCabOS"
export HOST="pincabos-live"
export BUILD_SYSTEM="Ubuntu"
export FLAVOUR="PinCabOS"
CASPER

# Marker read by the units that must stay quiet on live media, notably
# pincabos-finalize-firstboot (the system doctor would re-enable lightdm and
# steal vt1 from the installer kiosk 45 s into the boot). The payload deletes
# it right after unsquashfs, so an installed system behaves normally.
echo "PinCabOS live media" > "$ROOTFS/etc/pincabos-live"

# PINCABOS_MEDIA_RESEAU_V1 : les fichiers netplan du cab d origine (IP fixe,
# renderer networkd) rendraient NetworkManager muet sur le media (devices
# « strictly unmanaged », vu en VM : « No suitable device found ») et suivraient
# le systeme installe. Mis de cote dans un sous-dossier que netplan ignore.
mkdir -p "$ROOTFS/etc/netplan"
if ls "$ROOTFS"/etc/netplan/*.yaml >/dev/null 2>&1; then
  mkdir -p "$ROOTFS/etc/netplan/pincabos-source"
  for f in "$ROOTFS"/etc/netplan/*.yaml; do
    case "$(basename "$f")" in 01-pincabos-live-dhcp.yaml) continue ;; esac
    echo "  netplan du cab d origine mis de cote : $(basename "$f")"
    mv -f "$f" "$ROOTFS/etc/netplan/pincabos-source/"
  done
fi
cat > "$ROOTFS/etc/netplan/01-pincabos-live-dhcp.yaml" <<'NETPLAN'
network:
  version: 2
  renderer: NetworkManager
NETPLAN
chmod 0600 "$ROOTFS/etc/netplan/01-pincabos-live-dhcp.yaml"

# Live installer components live outside the installed system: they are dropped
# into the rootfs here so that the squashfs carries them.
if [ -n "$INSTALLER_SRC" ] && [ -d "$INSTALLER_SRC" ]; then
  echo "  adding live installer components from $INSTALLER_SRC"
  ( cd "$INSTALLER_SRC" && tar -cf - . ) | ( cd "$ROOTFS" && tar -xf - )
fi

echo "=== 2) Live initrd ==="
if [ -z "$KERNEL_VERSION" ]; then
  # PINCABOS_ISO_LIVE_KVER_V1 : le live prenait toujours le noyau le plus recent du
  # rootfs. Des qu une reconstruction en installe un second, l ISO demarre sur un
  # noyau que le parc n a jamais essaye (07/09/2026 : 7.0.0-31 par-dessus le 29).
  KERNEL_VERSION="${PCO_LIVE_KVER:-$(ls "$ROOTFS/lib/modules" | sort -V | tail -1)}"
fi
[ -n "$KERNEL_VERSION" ] || die "no kernel found under $ROOTFS/lib/modules"
echo "  kernel: $KERNEL_VERSION"

# PINCABOS_SPLASH_MEDIA_V1 : le media demarre avec les memes galeries
# aleatoires que le cab (portrait sur la plus grande dalle, paysage ailleurs).
# Le theme doit etre dans le rootfs AVANT l initrd casper, qui l embarque.
if [ -x "$ROOTFS/usr/local/sbin/pincabos-splash-sync" ]; then
  chroot "$ROOTFS" /usr/local/sbin/pincabos-splash-sync --media --no-initrd --force \
    || echo "  AVERTISSEMENT : splash du media non prepare (theme existant conserve)"
fi

# Built to /tmp on purpose: /boot must keep the initrd of the installed system.
chroot "$ROOTFS" mkinitramfs -o /tmp/initrd-live.img "$KERNEL_VERSION" \
  || die "mkinitramfs failed"
chroot "$ROOTFS" sh -c 'lsinitramfs /tmp/initrd-live.img | grep -qc casper' \
  >/dev/null || die "casper missing from the generated initrd"

echo "=== 3) Boot tree ==="
rm -rf "$TREE"
mkdir -p "$TREE/casper" "$TREE/boot/grub/fonts" "$PAYLOAD_DST" "$TREE/.disk"
cp -f "$ROOTFS/boot/vmlinuz-$KERNEL_VERSION" "$TREE/casper/vmlinuz"
mv -f "$ROOTFS/tmp/initrd-live.img" "$TREE/casper/initrd"
echo "PinCabOS live" > "$TREE/.disk/info"

# Branded GRUB, same assets as the installer ISO.
cp -f "$ROOTFS/usr/share/grub/unicode.pf2" "$TREE/boot/grub/fonts/unicode.pf2" 2>/dev/null || true
for logo in "$ROOTFS/opt/pincabos/install/PCOSInstallWP.png" \
            "$ROOTFS/opt/pincabos/media/installer/PCOSInstallWP.png"; do
  [ -f "$logo" ] && { cp -f "$logo" "$TREE/boot/grub/pincabos-grub.png"; break; }
done

# PINCABOS_GRUB_FONDS_ALEATOIRES_V1
# Galerie de fonds GRUB (opt/pincabos/media/splash/grub*.jpg) : GRUB n a pas de
# hasard, mais datehook expose la seconde de l horloge ; on s en sert pour
# choisir le fond a chaque demarrage. Sans galerie : l illustration unique.
GRUB_FONDS=()
for f in "$ROOTFS"/opt/pincabos/media/splash/grub*.jpg "$ROOTFS"/opt/pincabos/media/splash/grub*.png; do
  [ -f "$f" ] || continue
  k=${#GRUB_FONDS[@]}
  cp -f "$f" "$TREE/boot/grub/pincabos-grub-$k.${f##*.}"
  GRUB_FONDS+=("pincabos-grub-$k.${f##*.}")
done
{
  cat <<'BRANDING'
if loadfont /boot/grub/fonts/unicode.pf2 ; then
  set gfxmode=auto
  insmod all_video
  insmod gfxterm
  insmod png
  insmod jpeg
  terminal_output gfxterm
fi
set menu_color_normal=white/black
set menu_color_highlight=white/black
set color_normal=white/black
set color_highlight=white/black
BRANDING
  n=${#GRUB_FONDS[@]}
  if [ "$n" -gt 0 ]; then
    echo "insmod datehook"
    echo "set pco_fond=/boot/grub/${GRUB_FONDS[0]}"
    k=1
    while [ "$k" -lt "$n" ]; do
      # seuil k*60/n : tranches egales de la minute
      echo "if [ \"\$SECOND\" -ge $(( k * 60 / n )) ]; then set pco_fond=/boot/grub/${GRUB_FONDS[$k]}; fi"
      k=$((k + 1))
    done
    echo 'background_image "$pco_fond"'
  else
    echo "if [ -f /boot/grub/pincabos-grub.png ]; then"
    echo "  background_image /boot/grub/pincabos-grub.png"
    echo "fi"
  fi
} > "$TREE/boot/grub/pincabos-branding.cfg"
echo "  fonds GRUB : ${#GRUB_FONDS[@]} dans la galerie"

# logo.nologo drops the kernel's Tux; the PinCabOS Plymouth splash stays.
# vt.global_cursor_default=0 hides the blinking cursor between splash and X.
COMMON="logo.nologo vt.global_cursor_default=0"
# PINCABOS_MEDIA_NOPROMPT_V1 : au redemarrage, casper demandait « retirez le
# media puis Entree », invisible sous le splash : ecran noir sans fin (vu en
# VM). noprompt : le media est ejecte et la machine redemarre d elle-meme.
QUIET="quiet splash loglevel=3 noprompt"
# PINCABOS_LIVE_CMDLINE_EXTRA_V1 : arguments noyau supplementaires pour un banc
# d essai (ex. video=Virtual-2:1280x800e pour forcer une 2e tete QEMU) ; vide en
# production, jamais ecrit sur le systeme installe.
EXTRA="${PCO_LIVE_CMDLINE_EXTRA:-}"
BLACKLIST="modprobe.blacklist=nouveau,nova_core,nova_drm,snd_hda_intel pcie_port_pm=off"

# PINCABOS_ISO_UN_SEUL_CHEMIN_V1
# Une seule entree : l'assistant graphique. Pas de mode live, pas d'installeur
# texte, pas de secours dessus. Si l'assistant ne s'affiche pas, la panne est
# annoncee en clair sur tty1 (pincabos-installer-failure), jamais masquee.
cat > "$TREE/boot/grub/grub.cfg" <<GRUBCFG
source /boot/grub/pincabos-branding.cfg
set default=0
set timeout=3
set timeout_style=menu
menuentry "Install PinCabOS" {
    linux /casper/vmlinuz boot=casper $COMMON pincabos.installer=gui systemd.unit=pincabos-gui-install.target $QUIET $BLACKLIST $EXTRA ---
    initrd /casper/initrd
}
GRUBCFG

echo "=== 4) Payload ==="
if [ -n "$PAYLOAD_SRC" ] && [ -d "$PAYLOAD_SRC" ]; then
  # The helper knows both shapes (see PINCABOS_LIVE_SQUASHFS_V1 in iso.sh):
  # finding casper/filesystem.squashfs is what puts it in live mode.
  cp -f "$PAYLOAD_SRC"/pincabos-v8.1g-install-cab-payload-to-target.sh "$PAYLOAD_DST/" 2>/dev/null || true
  cp -f "$PAYLOAD_SRC"/pincabos-plymouth-theme-overlay-v8.1g.* "$PAYLOAD_DST/" 2>/dev/null || true
  chmod 0755 "$PAYLOAD_DST"/pincabos-v8.1g-install-cab-payload-to-target.sh 2>/dev/null || true
  echo "  helper and Plymouth overlay copied from $PAYLOAD_SRC"
else
  echo "  no payload directory given: ISO will boot and install, without post-install helper"
fi

umount_pseudo
echo "=== 5) squashfs (zstd $ZSTD_LEVEL) ==="
# Excludes must stay RELATIVE to a single source directory: with two sources
# mksquashfs silently ignores them (15 GB instead of 3).
EXCLUDES=(
  "proc/*" "sys/*" "dev/*" "run/*" "tmp/*" "mnt/*" "media/*"
  "*/__pycache__" "*/__pycache__/*"
  "home/*/snap" "home/*/snap/*"
  "home/pinball/.cache" "home/pinball/.cache/*"
  "home/pinball/Downloads/*"
  "home/pinball/Tables" "home/pinball/Tables/*"
  "home/pinball/.config/vpinfe/cache" "home/pinball/.config/vpinfe/cache/*"
  "home/pinball/.config/vpinfe/vpinfe.log"
  "opt/pincabos/build" "opt/pincabos/build/*"
  "opt/pincabos/cache" "opt/pincabos/cache/*"
  "opt/pincabos/logs/*"
  "root/.cache" "root/.cache/*"
  # PINCABOS_IMAGE_SANS_BROUILLONS_V1 : nos scripts de travail (pincab-batch-v31,
  # v32, v32b, v33, v35b, v35c, v35d...) et les notes de conception de DEV/
  # partaient sur CHAQUE cabinet. Ce n'est pas une question de place — 1 Mo sur
  # 2,8 Go — mais le cabinet d'un utilisateur n'a pas a porter notre historique.
  "root/pincab-*" "root/pincabos-*"
  "DEV" "DEV/*"
  "var/cache/apt/*" "var/lib/apt/lists/*"
  "usr/sbin/policy-rc.d"
  # Not needed at runtime on a cab, and it all comes back with apt if wanted.
  "usr/share/doc" "usr/share/doc/*"
  "usr/share/man" "usr/share/man/*"
  "usr/share/cmake-4.2" "usr/share/cmake-4.2/*"
  "usr/share/icons/HighContrast" "usr/share/icons/HighContrast/*"
  # Hardware absent from any pincab.
  "usr/lib/firmware/qcom" "usr/lib/firmware/qcom/*"
  "usr/lib/firmware/mellanox" "usr/lib/firmware/mellanox/*"
  # Headers of kernels other than the shipped one (DKMS needs the current one).
  "usr/src/linux-headers-*"
  # Dated LedWiz/DOF debugging attempts; the active overlay is
  # vpinfe-dof-ledwiz-hidraw-stable and is kept.
  "opt/pincabos/overlays/libdof-*-2[0-9][0-9][0-9][0-9][0-9][0-9][0-9]-*"
  "opt/pincabos/overlays/libdof-*-2[0-9][0-9][0-9][0-9][0-9][0-9][0-9]-*/*"
)
# Keep the headers of the running kernel.
EXCLUDES+=( )
ARGS=()
for e in "${EXCLUDES[@]}"; do ARGS+=(-e "$e"); done
# Locales: keep only those the installer offers, plus the C locale.
for d in "$ROOTFS"/usr/share/locale/*/; do
  n="$(basename "$d")"
  case "$n" in en*|fr*|de*|it*|es*|C|C.*) ;; *) ARGS+=(-e "usr/share/locale/$n" "usr/share/locale/$n/*") ;; esac
done

rm -f "$SQUASHFS"
mksquashfs "$ROOTFS" "$SQUASHFS" \
  -comp zstd -Xcompression-level "$ZSTD_LEVEL" -b 1M \
  -noappend -no-progress -wildcards "${ARGS[@]}" \
  | grep -E "^Filesystem size" || true
[ -f "$SQUASHFS" ] || die "mksquashfs produced nothing"
stat -c %s "$SQUASHFS" | awk '{printf "  squashfs: %.2f GB\n", $1/1e9}'

# Checksum of what actually gets deployed.
( cd "$TREE/casper" && sha256sum filesystem.squashfs | sed "s#filesystem.squashfs#../casper/filesystem.squashfs#" ) > "$PAYLOAD_DST/pincabos-rootfs-cab-v8.1g.parts.sha256" 2>/dev/null || true

echo "=== 6) ISO ==="
mount_pseudo
rm -f "$ROOTFS/tmp/pincabos-live.iso"
# NOTE: after the "--", grub-mkrescue speaks NATIVE xorriso, not mkisofs:
# -iso-level / -V and friends are rejected there.
chroot "$ROOTFS" grub-mkrescue -o /tmp/pincabos-live.iso /tmp/live-iso \
  -- -volid PINCABOS_LIVE 2>&1 | grep -iE "FAILURE|error" | head -3 || true
[ -f "$ROOTFS/tmp/pincabos-live.iso" ] || die "grub-mkrescue failed"
mv -f "$ROOTFS/tmp/pincabos-live.iso" "$OUT_ISO"

echo
echo "=== Done in $(( ($(date +%s) - START) / 60 )) min ==="
stat -c %s "$OUT_ISO" | awk -v f="$OUT_ISO" '{printf "  %s\n  %.2f GB\n", f, $1/1e9}'
sha256sum "$OUT_ISO"
xorriso -indev "$OUT_ISO" -report_el_torito plain 2>/dev/null \
  | grep -c "El Torito boot img" | sed 's/^/  El Torito images (BIOS+UEFI): /'
