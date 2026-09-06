#!/usr/bin/env bash
# PINCABOS_ISO_ETAPES_V1 — etape 60-validation-payload d iso.sh (texte de l ancienne section, inchange)
set -Eeuo pipefail
. "$(dirname "$(readlink -f "$0")")/00-lib.sh"
trap cleanup_mounts EXIT

[ -n "${VPXTOOL_VERSION:-}" ] || die "VPXTOOL_VERSION absente de $ETAT_ENV : relancer l etape 40"
echo
echo "=== 7) Validate payload exclusions and boot contents ==="
# PINCABOS_ISO_GREP_SANS_SIGPIPE_V1 : `tar -tf | grep -q` sous pipefail rend l etat de tar
# (SIGPIPE) et non celui de grep : un contenu exclu pouvait passer inapercu. Liste prise une fois.
ARCHIVE_LISTE="$(tar -I zstd -tf "$ARCHIVE")"
tar -I zstd -tf "$ARCHIVE" \
  | grep -E '^./boot/(vmlinuz|initrd.img|grub)|^./lib/modules/' \
  | sed -n '1,120p'

if grep -q '^./home/pinball/Tables/' <<<"$ARCHIVE_LISTE"; then
  die "Tables included in payload"
fi
echo "OK: Tables excluded"

if grep -q '^./opt/pincabos/build/' <<<"$ARCHIVE_LISTE"; then
  die "/opt/pincabos/build included in payload"
fi
echo "OK: /opt/pincabos/build excluded"


# PINCABOS_PAYLOAD_TRANSIENT_VALIDATION_V1
echo "=== Validation fichiers transitoires exclus ==="

if tar -I zstd -tf "$ARCHIVE" | grep -E -q \
'^\./opt/pincabos/(\.git-rootfs(/|$)|backups(/|$)|tmp(/|$)|script/.*\.(bak|before)-|web/.*\.(bak|before)-)'
then
    die "Fichiers transitoires PinCabOS inclus dans le payload"
fi

echo "OK: .git-rootfs excluded"
echo "OK: /opt/pincabos/backups excluded"
echo "OK: /opt/pincabos/tmp excluded"
echo "OK: script/web backups excluded"


if grep -Eq '^\./swap\.img$|^\./swapfile$' <<<"$ARCHIVE_LISTE"; then
  echo "Bad swap entries:"
  tar -I zstd -tf "$ARCHIVE" | grep -E '^\./swap\.img$|^\./swapfile$' | sed -n '1,80p'
  die "swap included in payload"
fi
echo "OK: swap excluded"

if grep -Eq '/(venv|\.venv|virtualenv)(/|$)' <<<"$ARCHIVE_LISTE"; then
  echo "NOTICE: venv/virtualenv entries present in payload; allowed for WebApp runtime"
  tar -I zstd -tf "$ARCHIVE" | grep -E '/(venv|\.venv|virtualenv)(/|$)' | sed -n '1,80p'
else
  echo "NOTICE: no venv/virtualenv entries found; WebApp must use system Python or fallback"
fi

if grep -q '^./root/pincabos-v8' <<<"$ARCHIVE_LISTE"; then
  die "old /root payload included"
fi
echo "OK: old root payloads excluded"

echo
echo "=== Validate Python + PinCabOS WebApp in payload ==="
echo "PINCABOS_PAYLOAD_PYTHON_WEBAPP_VALIDATE_V3_PIPEFAIL_SAFE"

ARCHIVE_LIST_PYWEB="$WORK/payload-file-list-python-webapp.txt"
echo "Creating payload file list:"
echo "$ARCHIVE_LIST_PYWEB"
tar -I zstd -tf "$ARCHIVE" > "$ARCHIVE_LIST_PYWEB"

echo "--- vpxtool deterministic ISO validation ---"
for VPXTOOL_MEMBER in \
  "./opt/pincabos/apps/vpxtool/$VPXTOOL_VERSION/vpxtool" \
  "./opt/pincabos/apps/vpxtool/current" \
  "./opt/pincabos/bin/vpxtool"
do
  VPXTOOL_MEMBER_COUNT="$(grep -Fxc "$VPXTOOL_MEMBER" "$ARCHIVE_LIST_PYWEB" || true)"
  [ "$VPXTOOL_MEMBER_COUNT" -eq 1 ] \
    || die "vpxtool payload member count invalid ($VPXTOOL_MEMBER_COUNT): $VPXTOOL_MEMBER"
done
echo "GO [OK] vpxtool v$VPXTOOL_VERSION is present exactly once in payload"

echo "--- Python entries detected in payload ---"
grep -E '^\./usr/bin/python3($|[.0-9-])|^\./usr/lib/python3' "$ARCHIVE_LIST_PYWEB" | sed -n '1,80p' || true

if grep -Eq '^\./usr/bin/python3$|^\./usr/bin/python3[.0-9]+$|^\./usr/lib/python3' "$ARCHIVE_LIST_PYWEB"; then
  echo "OK: Python runtime present in payload"
else
  die "Python runtime missing from payload"
fi

grep -q '^\./opt/pincabos/web/app.py$' "$ARCHIVE_LIST_PYWEB" \
  || die "PinCabOS WebApp missing from payload: /opt/pincabos/web/app.py"

if grep -Eq '^\./etc/systemd/system/pincabos-webapp.service$|^\./lib/systemd/system/pincabos-webapp.service$|^\./usr/lib/systemd/system/pincabos-webapp.service$' "$ARCHIVE_LIST_PYWEB"; then
  echo "OK: pincabos-webapp.service present in payload"
else
  die "pincabos-webapp.service missing from payload"
fi

if grep -Eq '^\./usr/sbin/nginx$|^\./etc/nginx/' "$ARCHIVE_LIST_PYWEB"; then
  echo "NOTICE: nginx is present in payload"
else
  echo "NOTICE: nginx not present in payload; OK, PinCabOS WebApp runs direct without nginx"
fi

if grep -Eq '/(site-packages|dist-packages)/flask($|/)' "$ARCHIVE_LIST_PYWEB"; then
  echo "OK: Flask package present in payload"
else
  echo "WARNING: Flask package not detected in payload path scan"
  echo "Fallback WebApp may rely on official service runtime only."
fi

echo "OK: Python + WebApp payload validation passed"

echo
echo "=== Validate VPX runtime in payload ==="
echo "PINCABOS_PAYLOAD_VPX_VALIDATE_V1"

if [ -z "${ARCHIVE_LIST_PYWEB:-}" ] || [ ! -s "$ARCHIVE_LIST_PYWEB" ]; then
  ARCHIVE_LIST_PYWEB="$WORK/payload-file-list-python-webapp.txt"
  tar -I zstd -tf "$ARCHIVE" > "$ARCHIVE_LIST_PYWEB"
fi

echo "--- VPX payload entries ---"
grep -Ei 'VPinballX|VPinball|vpx\.sh|VPXlauncher|vpinball|PinMAME|VPinballX\.ini' "$ARCHIVE_LIST_PYWEB" | sed -n '1,240p' || true

if grep -Eq '^\./opt/pincabos/bin/vpx\.sh$|^\./opt/pincabos/scripts/VPXlauncher\.sh$' "$ARCHIVE_LIST_PYWEB"; then
  echo "OK: VPX launcher present in payload"
else
  die "VPX launcher missing from payload: /opt/pincabos/bin/vpx.sh or /opt/pincabos/scripts/VPXlauncher.sh"
fi

if grep -Eq 'VPinballX_BGFX$|VPinballX$|/VPinballX_BGFX$|/VPinballX$' "$ARCHIVE_LIST_PYWEB"; then
  echo "OK: VPX executable present in payload"
else
  die "VPX executable missing from payload"
fi

if grep -Eq '^\./home/pinball/\.vpinball/VPinballX\.ini$|^\./home/pinball/\.local/share/VPinballX/.*/VPinballX\.ini$|^\./home/pinball/\.pincabos/vpx/VPinballX\.ini$' "$ARCHIVE_LIST_PYWEB"; then
  echo "OK: VPX INI present in payload"
else
  echo "WARNING: VPX INI not found at expected path"
fi

if grep -Eq '^\./opt/pincabos/apps/vpinball/PinMAME($|/)|^\./home/pinball/\.pinmame($|/)' "$ARCHIVE_LIST_PYWEB"; then
  echo "OK: PinMAME/runtime files present in payload"
else
  echo "WARNING: PinMAME/runtime path not detected in payload"
fi

if grep -q '^\./home/pinball/Tables/' "$ARCHIVE_LIST_PYWEB"; then
  die "Tables were included unexpectedly"
else
  echo "OK: Tables still excluded"
fi

echo "OK: VPX payload validation passed"


echo
echo "=== Validate VPinFE packaged runtime in payload ==="
echo "PINCABOS_PAYLOAD_VPINFE_PACKAGED_RUNTIME_VALIDATE_V1"

if [ -z "${ARCHIVE_LIST_PYWEB:-}" ] || [ ! -s "$ARCHIVE_LIST_PYWEB" ]; then
  ARCHIVE_LIST_PYWEB="$WORK/payload-file-list-python-webapp.txt"
  tar -I zstd -tf "$ARCHIVE" > "$ARCHIVE_LIST_PYWEB"
fi

echo "--- VPinFE payload entries ---"
# PINCABOS_RUNTIMES_OPT_V1 : VPinFE sous /opt/pinball ; le compte du joueur pour
# une source pas encore migree (l'installateur migre sur la cible).
grep -Ei '^\./(opt|home)/pinball/vpinfe($|/)|^\./opt/pincabos/tools/run-vpinfe-systemd\.sh$|pincabos-vpinfe\.service' "$ARCHIVE_LIST_PYWEB" | sed -n '1,220p' || true

grep -Eq '^\./(opt|home)/pinball/vpinfe/' "$ARCHIVE_LIST_PYWEB" \
  || die "VPinFE runtime missing from payload: /opt/pinball/vpinfe"

grep -Eq '^\./(opt|home)/pinball/vpinfe/_internal/' "$ARCHIVE_LIST_PYWEB" \
  || die "VPinFE packaged _internal runtime missing from payload"

grep -q '^\./opt/pincabos/tools/run-vpinfe-systemd\.sh$' "$ARCHIVE_LIST_PYWEB" \
  || die "VPinFE launcher missing from payload: /opt/pincabos/tools/run-vpinfe-systemd.sh"

if grep -Eq '^\./etc/systemd/system/pincabos-vpinfe\.service$|^\./lib/systemd/system/pincabos-vpinfe\.service$|^\./usr/lib/systemd/system/pincabos-vpinfe\.service$' "$ARCHIVE_LIST_PYWEB"; then
  echo "OK: pincabos-vpinfe.service present in payload"
else
  die "pincabos-vpinfe.service missing from payload"
fi

echo "OK: VPinFE packaged runtime validation passed"


echo
echo "=== Validate WebApp runtime dependencies in payload ==="
echo "PINCABOS_PAYLOAD_WEBAPP_RUNTIME_VALIDATE_V3_PIPEFAIL_SAFE"

if [ -z "${ARCHIVE_LIST_PYWEB:-}" ] || [ ! -s "$ARCHIVE_LIST_PYWEB" ]; then
  ARCHIVE_LIST_PYWEB="$WORK/payload-file-list-python-webapp.txt"
  tar -I zstd -tf "$ARCHIVE" > "$ARCHIVE_LIST_PYWEB"
fi

if grep -Eq '^\./opt/pincabos/web/(\.venv|venv)/bin/python$|^\./opt/pincabos/(\.venv|venv)/bin/python$' "$ARCHIVE_LIST_PYWEB"; then
  echo "OK: WebApp/local PinCabOS venv python present in payload"
else
  echo "NOTICE: no WebApp/local venv python found in payload; will rely on system Python/fallback"
fi

if grep -Eq '/(site-packages|dist-packages)/flask($|/)' "$ARCHIVE_LIST_PYWEB"; then
  echo "OK: Flask package present somewhere in payload"
else
  echo "WARNING: Flask package not detected by archive path scan"
  echo "The fallback service may fail if Flask is only installed by another mechanism."
fi

tar -I zstd -tf "$OVERLAY" | grep '^usr/share/plymouth/themes/pincabos/pincabos.plymouth$' \
  || die "Plymouth overlay missing pincabos.plymouth"
echo "OK: Plymouth overlay valid"
