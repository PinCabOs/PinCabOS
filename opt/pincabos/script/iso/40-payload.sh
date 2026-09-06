#!/usr/bin/env bash
# PINCABOS_ISO_ETAPES_V1 — etape 40-payload d iso.sh (texte de l ancienne section, inchange)
set -Eeuo pipefail
. "$(dirname "$(readlink -f "$0")")/00-lib.sh"
trap cleanup_mounts EXIT

echo
echo "=== 5) Build lean PinCabOS payload from current cabinet ==="

{
  echo "PinCabOS V8.1G LEAN CAB PAYLOAD"
  echo "Generated: $(date -Is)"
  echo
  echo "Excluded:"
  echo "/home/pinball/Tables"
  echo "/opt/pincabos/build"
  echo "/swap.img"
  echo "/swapfile"
  echo "venv/.venv/virtualenv preserved when needed for WebApp runtime"
  echo "node_modules"
  echo "__pycache__"
  echo "/root old payloads"
  echo "/opt/pincabos/cache"
  echo "/opt/pincabos/logs"
  echo "/var/tmp, /var/crash, /var/cache, /var/log, apt archives, journals"
  echo
  echo "Source: $PCO_ISO_SOURCE"
  findmnt "$PCO_ISO_SOURCE" || true
  echo
  ls -lah "$SRC"/boot/vmlinuz-* "$SRC"/boot/initrd.img-* 2>/dev/null || true
  echo
  ls -lah "$SRC/lib/modules"
  echo
  cat "$SRC/etc/default/grub"
  echo
  find "$SRC/usr/share/plymouth/themes/pincabos" -maxdepth 2 -type f | sort
} > "$MANIFEST"

sed -n '1,140p' "$MANIFEST"

# PINCABOS_ISO_LEAN_EXCLUSIONS_V2
# PINCABOS_PAYLOAD_LIVE_TAR_STABILITY_V2
# PINCABOS_ISO_AUDIO_PRIVACY_V1
#
# Prépare une copie neutre des VPinballX.ini sans noms de cartes audio.
# La configuration originale du cabinet source n'est jamais modifiée.

AUDIO_SANITIZE_STAGE="/tmp/pincabos-audio-sanitize-$$"
AUDIO_SANITIZE_LIST="/tmp/pincabos-audio-sanitize-list-$$"

rm -rf "$AUDIO_SANITIZE_STAGE"
rm -f "$AUDIO_SANITIZE_LIST"

mkdir -p \
  "$AUDIO_SANITIZE_STAGE/__PINCABOS_AUDIO_SANITIZED__"

: > "$AUDIO_SANITIZE_LIST"

python3 - \
  "$AUDIO_SANITIZE_STAGE/__PINCABOS_AUDIO_SANITIZED__" \
  "$AUDIO_SANITIZE_LIST" \
  "$PCO_ISO_SOURCE" <<'PINCABOS_AUDIO_PRIVACY_PY'
from pathlib import Path
import os
import re
import shutil
import sys

stage = Path(sys.argv[1])
list_file = Path(sys.argv[2])
source_root = Path(sys.argv[3] if len(sys.argv) > 3 else "/")   # PINCABOS_ISO_SOURCE_V1

sources = []

roots = [
    # PINCABOS_VPX_PREF_PATH_V1 : preferences VPX (-PrefPath) depuis Alpha 3.0x ;
    # ~/.local/share/VPinballX/10.8 n'est plus qu'un lien vers ce dossier, et
    # rglob ne suit pas les liens : sans cette racine le fichier reel partait
    # dans la photo avec les noms de cartes audio du master (garde audio).
    source_root / "home/pinball/.pincabos/vpx",
    source_root / "home/pinball/.local/share/VPinballX",
    source_root / "home/pinball/.vpinball",
    # PINCABOS_ISO_AUDIO_PRIVACY_MODELE_V1 : le modele du compte du joueur (#204) est
    # un VPinballX.ini comme les autres ; la validation refusait l archive.
    source_root / "opt/pincabos/templates/home/.local/share/VPinballX",
]

for root in roots:
    if not root.exists():
        continue

    sources.extend(
        candidate
        for candidate in root.rglob("VPinballX.ini")
        if candidate.is_file() and not candidate.is_symlink()
    )

hardware_audio_key = re.compile(
    r"^\s*("
    r"SoundDevice|"
    r"SoundDeviceBG|"
    r"MusicDevice|"
    r"Sound3DDevice|"
    r"AudioDevice|"
    r"AudioDeviceBG"
    r")\s*=.*$",
    re.IGNORECASE,
)

archive_members = []

for source in sorted(set(sources)):
    relative = source.relative_to(source_root)

    destination = stage / relative
    destination.parent.mkdir(parents=True, exist_ok=True)

    original = source.read_text(
        encoding="utf-8",
        errors="replace",
    )

    lines = original.splitlines(keepends=True)

    sanitized = "".join(
        line
        for line in lines
        if not hardware_audio_key.match(line)
    )

    destination.write_text(
        sanitized,
        encoding="utf-8",
    )

    source_stat = source.stat()

    os.chmod(
        destination,
        source_stat.st_mode & 0o7777,
    )

    os.chown(
        destination,
        source_stat.st_uid,
        source_stat.st_gid,
    )

    archive_members.append(
        "./__PINCABOS_AUDIO_SANITIZED__/"
        + str(relative)
    )

list_file.write_text(
    "".join(member + "\n" for member in archive_members),
    encoding="utf-8",
)

print(
    f"GO [√] VPinballX.ini neutralisés : "
    f"{len(archive_members)}"
)
PINCABOS_AUDIO_PRIVACY_PY

if [ "$?" -ne 0 ]; then
  die "Unable to prepare sanitized VPX audio configuration"
fi

# PINCABOS_VPXTOOL_ISO_EMBED_V1
#
# Every freshly built ISO must contain the exact vpxtool pinned by the same
# manifest used by the runtime updater.  Never depend on a manually installed
# copy on the source cabinet.  Download into /tmp, verify SHA-256, validate the
# binary, and overlay it into the payload TAR without modifying the cabinet.
VPXTOOL_STAGE="/tmp/pincabos-vpxtool-iso-$$"
VPXTOOL_PAYLOAD_ROOT="$VPXTOOL_STAGE/__PINCABOS_VPXTOOL_EMBEDDED__"
VPXTOOL_DOWNLOAD_DIR="$VPXTOOL_STAGE/download"
VPXTOOL_EXTRACT_DIR="$VPXTOOL_STAGE/extract"

test -s "$VPXTOOL_MANIFEST" \
  || die "vpxtool release manifest missing: $VPXTOOL_MANIFEST"

case "$(uname -m)" in
  x86_64|amd64) VPXTOOL_ARCH="x86_64" ;;
  aarch64|arm64) VPXTOOL_ARCH="aarch64" ;;
  *) die "Unsupported vpxtool build architecture: $(uname -m)" ;;
esac

rm -rf "$VPXTOOL_STAGE"
mkdir -p "$VPXTOOL_DOWNLOAD_DIR" "$VPXTOOL_EXTRACT_DIR" "$VPXTOOL_PAYLOAD_ROOT"

mapfile -t VPXTOOL_META < <(
  python3 - "$VPXTOOL_MANIFEST" "$VPXTOOL_ARCH" <<'PINCABOS_VPXTOOL_META_PY'
import json
import re
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
arch = sys.argv[2]
data = json.loads(manifest_path.read_text(encoding="utf-8"))
version = str(data.get("version") or "").strip().lstrip("v")
if not re.fullmatch(r"\d+(?:\.\d+){2,3}", version):
    raise SystemExit(f"invalid vpxtool version in manifest: {version!r}")
sha = str(data["sha256"][arch]).strip().lower()
if not re.fullmatch(r"[0-9a-f]{64}", sha):
    raise SystemExit(f"invalid vpxtool sha256 for {arch}")
base = str(data["release_base_template"]).format(version=version).rstrip("/")
name = str(data["archive_template"]).format(arch=arch, version=version)
print(version)
print(f"{base}/{name}")
print(sha)
PINCABOS_VPXTOOL_META_PY
)

[ "${#VPXTOOL_META[@]}" -eq 3 ] \
  || die "Unable to resolve vpxtool release metadata"

VPXTOOL_VERSION="${VPXTOOL_META[0]}"
pco_etat_ecrire VPXTOOL_VERSION   # relue par l etape 60 (validation)
VPXTOOL_URL="${VPXTOOL_META[1]}"
VPXTOOL_SHA256="${VPXTOOL_META[2]}"
VPXTOOL_ARCHIVE="$VPXTOOL_DOWNLOAD_DIR/vpxtool.tar.gz"

echo "Embedding vpxtool v$VPXTOOL_VERSION ($VPXTOOL_ARCH) into ISO payload"
wget -q --show-progress -O "$VPXTOOL_ARCHIVE" "$VPXTOOL_URL" \
  || die "Unable to download pinned vpxtool archive"

echo "$VPXTOOL_SHA256  $VPXTOOL_ARCHIVE" | sha256sum -c - \
  || die "vpxtool archive SHA-256 mismatch"

tar --no-same-owner --no-same-permissions -xzf "$VPXTOOL_ARCHIVE" \
  -C "$VPXTOOL_EXTRACT_DIR" \
  || die "Unable to extract pinned vpxtool archive"

VPXTOOL_SOURCE_BIN="$(find "$VPXTOOL_EXTRACT_DIR" -type f -name vpxtool -print -quit)"
[ -n "$VPXTOOL_SOURCE_BIN" ] && [ -f "$VPXTOOL_SOURCE_BIN" ] \
  || die "vpxtool binary missing from pinned archive"

VPXTOOL_VERSION_DIR="$VPXTOOL_PAYLOAD_ROOT/opt/pincabos/apps/vpxtool/$VPXTOOL_VERSION"
VPXTOOL_STAGED_BIN="$VPXTOOL_VERSION_DIR/vpxtool"
install -D -m 0755 "$VPXTOOL_SOURCE_BIN" "$VPXTOOL_STAGED_BIN"
ln -s "$VPXTOOL_VERSION" "$VPXTOOL_PAYLOAD_ROOT/opt/pincabos/apps/vpxtool/current"
mkdir -p "$VPXTOOL_PAYLOAD_ROOT/opt/pincabos/bin"
ln -s "/opt/pincabos/apps/vpxtool/current/vpxtool" \
  "$VPXTOOL_PAYLOAD_ROOT/opt/pincabos/bin/vpxtool"

VPXTOOL_VERSION_TEXT="$("$VPXTOOL_STAGED_BIN" --version 2>&1)"
printf '%s\n' "$VPXTOOL_VERSION_TEXT" | grep -Fq "v$VPXTOOL_VERSION" \
  || die "Staged vpxtool does not report v$VPXTOOL_VERSION"
"$VPXTOOL_STAGED_BIN" patch --help >/dev/null 2>&1 \
  || die "Staged vpxtool does not provide the patch command"

echo "GO [OK] vpxtool v$VPXTOOL_VERSION pinned and staged for ISO"

# PINCABOS_ROOT_GENERATED_PAYLOAD_EXCLUSIONS_V1
echo "Creating live cabinet payload with controlled TAR status."

set +e

tar \
  --checkpoint=10000 \
  --checkpoint-action=echo='archived %u entries...' \
  --acls \
  --xattrs \
  --numeric-owner \
  --one-file-system \
  --ignore-failed-read \
  --warning=no-file-changed \
  --exclude='./boot/efi' \
  --exclude='./boot/efi/*' \
  --exclude='./proc/*' \
  --exclude='./sys/*' \
  --exclude='./dev/*' \
  --exclude='./run/*' \
  --exclude='./tmp/*' \
  --exclude='./mnt/*' \
  --exclude='./media/*' \
  --exclude='./cdrom/*' \
  --exclude='./lost+found' \
  --exclude='./swap.img' \
  --exclude='./swapfile' \
  --exclude='./home/pinball/Tables' \
  --exclude='./home/pinball/Tables/*' \
  --exclude='./home/pinball/Backups/*' \
  --exclude='./home/pinball/pincabos-*' \
  --exclude='./home/pinball/vpinfe.pre-*' \
  --exclude='./home/pinball/*.avant-opt*' \
  --exclude='./home/pinball/Downloads/*' \
  --exclude='./home/pinball/.cache' \
  --exclude='./home/pinball/.cache/*' \
  --exclude='./home/pinball/Exports' \
  --exclude='./home/pinball/Exports/*' \
  --exclude='./home/pinball/.ssh' \
  --exclude='./home/pinball/.ssh/*' \
  --exclude='./home/pinball/.config/gh' \
  --exclude='./home/pinball/.config/gh/*' \
  --exclude='./home/pinball/.config/google-chrome' \
  --exclude='./home/pinball/.config/google-chrome/*' \
  --exclude='./home/pinball/.config/vpinfe/cache' \
  --exclude='./home/pinball/.config/vpinfe/cache/*' \
  --exclude='./home/pinball/.config/vpinfe/updates' \
  --exclude='./home/pinball/.config/vpinfe/updates/*' \
  --exclude='./home/pinball/.config/vpinfe/vpinfe.log' \
  --exclude='./home/pinball/.config/sunshine/credentials' \
  --exclude='./home/pinball/.config/pincabos/smb' \
  --exclude='./home/pinball/.config/pincabos/smb/*' \
  --exclude='./home/pinball/.config/pincabos/smb-sessions' \
  --exclude='./home/pinball/.config/pincabos/smb-sessions/*' \
  --exclude='./home/pinball/.local/share/Trash/*' \
  --exclude='./home/*/snap' \
  --exclude='./home/*/snap/*' \
  --exclude='./snap' \
  --exclude='./snap/*' \
  --exclude='./var/snap' \
  --exclude='./var/snap/*' \
  --exclude='./var/lib/snapd' \
  --exclude='./var/lib/snapd/*' \
  --exclude='./etc/asound.conf' \
  --exclude='./var/lib/alsa' \
  --exclude='./var/lib/alsa/*' \
  --exclude='./var/lib/pipewire' \
  --exclude='./var/lib/pipewire/*' \
  --exclude='./home/pinball/.asoundrc' \
  --exclude='./home/pinball/.config/pulse' \
  --exclude='./home/pinball/.config/pulse/*' \
  --exclude='./home/pinball/.config/pipewire' \
  --exclude='./home/pinball/.config/pipewire/*' \
  --exclude='./home/pinball/.config/wireplumber' \
  --exclude='./home/pinball/.config/wireplumber/*' \
  --exclude='./home/pinball/.local/state/pipewire' \
  --exclude='./home/pinball/.local/state/pipewire/*' \
  --exclude='./home/pinball/.local/state/wireplumber' \
  --exclude='./home/pinball/.local/state/wireplumber/*' \
  --exclude='./opt/pincabos/config/audio-router.json' \
  --exclude='./opt/pincabos/config/audio.json' \
  --exclude='./opt/pincabos/config/audio-ssf.json' \
  --exclude='./opt/pincabos/config/ssf-commander.json' \
  --exclude='./opt/pincabos/backups/*audio*' \
  --exclude='./opt/pincabos/backups/*audio*/*' \
  --exclude='./home/pinball/.local/share/VPinballX/*/VPinballX.ini' \
  --exclude='./home/pinball/.vpinball/VPinballX.ini' \
  --exclude='./home/pinball/.pincabos/vpx/VPinballX.ini' \
  --exclude='./opt/pincabos/templates/home/.local/share/VPinballX/*/VPinballX.ini' \
  --exclude='./opt/pincabos/config/screens/screens.json' \
  --exclude='./opt/pincabos/config/screens/bindings.json' \
  --exclude='./opt/pincabos/config/screens/display-bindings.json' \
  --exclude='./opt/pincabos/config/screens/display-role-bindings.json' \
  --exclude='./home/pinball/.config/monitors.xml' \
  --exclude='./var/log/journal/*' \
  --exclude='./var/cache/apt/archives/*.deb' \
  --exclude='./var/lib/apt/lists' \
  --exclude='./var/lib/apt/lists/*' \
  --exclude='./var/backups' \
  --exclude='./var/backups/*' \
  --exclude='./var/tmp/*' \
  --exclude='./var/crash/*' \
  --exclude='./root/.cache' \
  --exclude='./root/.cache/*' \
  --exclude='./root/*' \
  --exclude='./pincabos-rootfs-cab-*.tar.zst' \
  --exclude='./pincabos-rootfs-cab-*.tar.zst.part-*' \
  --exclude='./pincabos-rootfs-cab-*.sha256' \
  --exclude='./pincabos-rootfs-cab-*.manifest.txt' \
  --exclude='./pincabos-plymouth-theme-overlay-*.tar.zst' \
  --exclude='./pincabos-plymouth-theme-overlay-*.tar.zst.part-*' \
  --exclude='./pincabos-plymouth-theme-overlay-*.sha256' \
  --exclude='./payload-file-list-python-webapp.txt' \
  --exclude='./MANIFEST.txt' \
  --exclude='./var/lib/kdump' \
  --exclude='./var/lib/kdump/*' \
  --exclude='./var/lib/systemd/coredump' \
  --exclude='./var/lib/systemd/coredump/*' \
  --exclude='./home/pinball/.nv' \
  --exclude='./home/pinball/.nv/*' \
  --exclude='./home/pinball/.dbus' \
  --exclude='./home/pinball/.dbus/*' \
  --exclude='./opt/pincabos/runtime/live-gpu' \
  --exclude='./opt/pincabos/runtime/live-gpu/*' \
  --exclude='./opt/pincabos/script/*.bak' \
  --exclude='./opt/pincabos/script/*.bak-*' \
  --exclude='./opt/pincabos/script/*.backup' \
  --exclude='./opt/pincabos/script/*.orig' \
  --exclude='./opt/pincabos/script/*~' \
  --exclude='./root/pincabos-v8.1-cab-payload' \
  --exclude='./root/pincabos-v8.1-cab-payload/*' \
  --exclude='./root/pincabos-v8.1f-iso-ready' \
  --exclude='./root/pincabos-v8.1f-iso-ready/*' \
  --exclude='./root/pincabos-v8.1g-cab-payload' \
  --exclude='./root/pincabos-v8.1g-cab-payload/*' \
  --exclude='./root/pincabos-v8.1g-iso-ready' \
  --exclude='./root/pincabos-v8.1g-iso-ready/*' \
  --exclude='./opt/pincabos/build' \
  --exclude='./opt/pincabos/build/*' \
  --exclude='./opt/pincabos/tmp' \
  --exclude='./opt/pincabos/tmp/*' \
  --exclude='./opt/pincabos/apps/vpxtool' \
  --exclude='./opt/pincabos/apps/vpxtool/*' \
  --exclude='./opt/pincabos/bin/vpxtool' \
  --exclude='./opt/pincabos/.git-rootfs' \
  --exclude='./opt/pincabos/.git-rootfs/*' \
  --exclude='./opt/pincabos/backups' \
  --exclude='./opt/pincabos/backups/*' \
  --exclude='./opt/pincabos/script/*.bak-*' \
  --exclude='./opt/pincabos/script/*.before-*' \
  --exclude='./opt/pincabos/web/*.bak-*' \
  --exclude='./opt/pincabos/web/*.before-*' \
  --exclude='./opt/pincabos/cache' \
  --exclude='./opt/pincabos/cache/*' \
  --exclude='./opt/pincabos/logs/*' \
  --exclude='./var/cache/*' \
  --exclude='./var/log/*' \
  --exclude='*/node_modules' \
  --exclude='*/node_modules/*' \
  --exclude='*/__pycache__' \
  --exclude='*/__pycache__/*' \
  --exclude='./__pincabos_keep_webapp_venv_runtime_marker_never_matches__' \
  -I 'zstd -T0 -10' \
  -cpf "$ARCHIVE" \
  --transform='s#^\./__PINCABOS_AUDIO_SANITIZED__$#.#' \
  --transform='s#^\./__PINCABOS_AUDIO_SANITIZED__/#./#' \
  --transform='s#^\./__PINCABOS_VPXTOOL_EMBEDDED__$#.#' \
  --transform='s#^\./__PINCABOS_VPXTOOL_EMBEDDED__/#./#' \
  -C "$PCO_ISO_SOURCE" . \
  -C "$AUDIO_SANITIZE_STAGE" -T "$AUDIO_SANITIZE_LIST" \
  -C "$VPXTOOL_STAGE" \
    ./__PINCABOS_VPXTOOL_EMBEDDED__/opt/pincabos/apps/vpxtool \
    ./__PINCABOS_VPXTOOL_EMBEDDED__/opt/pincabos/bin/vpxtool

TAR_CREATE_RC="$?"

rm -rf "$AUDIO_SANITIZE_STAGE"
rm -f "$AUDIO_SANITIZE_LIST"
rm -rf "$VPXTOOL_STAGE"
set -e

echo
echo "=== Validate completed live payload archive ==="
echo "TAR_CREATE_RC=$TAR_CREATE_RC"

if [ "$TAR_CREATE_RC" -gt 1 ]; then
  die "Payload TAR creation failed with fatal status $TAR_CREATE_RC"
fi

if [ ! -s "$ARCHIVE" ]; then
  die "Payload archive is absent or empty: $ARCHIVE"
fi

echo "--- Zstandard integrity test ---"
zstd -t "$ARCHIVE"

echo "--- TAR stream readability test ---"
tar -I zstd -tf "$ARCHIVE" >/dev/null

# PINCABOS_ISO_AUDIO_PRIVACY_ARCHIVE_VALIDATION_V1

AUDIO_PRIVACY_FORBIDDEN_RE='^\./etc/asound\.conf$|^\./var/lib/alsa/|^\./var/lib/pipewire/|^\./home/pinball/\.asoundrc$|^\./home/pinball/\.config/(pulse|pipewire|wireplumber)(/|$)|^\./home/pinball/\.local/state/(pipewire|wireplumber)(/|$)|^\./opt/pincabos/config/(audio-router|audio|audio-ssf|ssf-commander)\.json$'

AUDIO_PRIVACY_FOUND="$(
  tar -I zstd -tf "$ARCHIVE" |
  grep -E "$AUDIO_PRIVACY_FORBIDDEN_RE" ||
  true
)"

if [ -n "$AUDIO_PRIVACY_FOUND" ]; then
  echo "$AUDIO_PRIVACY_FOUND"
  die "Personal audio state found inside payload"
fi

AUDIO_DEVICE_KEY_RE='^[[:space:]]*(SoundDevice|SoundDeviceBG|MusicDevice|Sound3DDevice|AudioDevice|AudioDeviceBG)[[:space:]]*='

while IFS= read -r VPX_INI_MEMBER; do
  [ -n "$VPX_INI_MEMBER" ] || continue

  if tar -I zstd -xOf "$ARCHIVE" "$VPX_INI_MEMBER" |
     grep -Eiq "$AUDIO_DEVICE_KEY_RE"
  then
    echo "Hardware audio key found in: $VPX_INI_MEMBER"
    die "Hardware-specific VPX audio configuration found"
  fi
done < <(
  tar -I zstd -tf "$ARCHIVE" |
  grep -E '/VPinballX\.ini$' ||
  true
)

echo "GO [√] Payload audio privacy validation passed"


echo "--- Completed live payload archive ---"
ls -lh "$ARCHIVE"

if [ "$TAR_CREATE_RC" -eq 1 ]; then
  echo "WARNING: TAR returned status 1 during live capture."
  echo "The completed archive passed both integrity tests."
else
  echo "OK: TAR completed with status 0."
fi

echo "GO [√] Live payload archive is structurally valid"
