#!/usr/bin/env bash
# PinCabOS — lancement VPX permanent
# LED-Wiz : LIBUSB local isole
# DudesCab + UMX : HIDRAW

set -Eeuo pipefail
# PINCABOS_PATHS_CONSUMER_V1
. /opt/pincabos/tools/pincabos-paths.sh

PINBALL_USER="$PCO_USER"
PINBALL_HOME="$PCO_HOME"

# PINCABOS_VPX_STABLE_SYMLINK_V1
# $PCO_VPX_LINK (/opt/pinball/vpx) pointe vers le dossier moteur versionné.
# Auto-répare : si le lien manque ou est cassé, cible le dossier
# VPinballX_BGFX-* le plus récent du même emplacement (PINCABOS_RUNTIMES_OPT_V1).
VPX_HOME_LINK="$PCO_VPX_LINK"
if [[ ! -e "${VPX_HOME_LINK}/VPinballX_BGFX" ]]; then
  _newest="$(ls -dt "$(dirname "$VPX_HOME_LINK")"/VPinballX_BGFX-*-linux-x64 2>/dev/null | head -1 || true)"
  if [[ -n "${_newest}" ]]; then
    ln -sfn "${_newest}" "${VPX_HOME_LINK}"
    chown -h "$PINBALL_USER:$PINBALL_USER" "${VPX_HOME_LINK}" 2>/dev/null || true
  fi
fi

VPX_MAIN="$PCO_VPX_BIN"
VPX_ALT="${PCO_VPX_LINK}/VPinballX_BGFX.pincabos-original-paced2"
DOF_DIR="${PCO_VPX_PLUGINS}/dof"
OVERLAY="/opt/pincabos/overlays/libdof-ledwiz-hidraw-stable"
DOF_LOCAL="/opt/pincabos/overlays/libdof-ledwiz-hidraw-stable/libdof.so.0.4.7"
# PINCABOS_HIDAPI_SONAME_V1
# Le lien de soname (.so.0) est garanti par le paquet libhidapi-libusb0 quelle
# que soit sa version ; le nom de fichier versionne (.so.0.15.0) disparait a la
# premiere montee de version apt, et avec lui tous les lancements de table.
HIDUSB="/usr/lib/x86_64-linux-gnu/libhidapi-libusb.so.0"

DEFAULT_TABLE="${PCO_TABLES}/Attack from Mars (Bally 1995)/Attack from Mars (Midway 1995).vpx"

die() {
  echo "ERREUR: $*" >&2
  exit 1
}

if file "$VPX_MAIN" 2>/dev/null | grep -q 'ELF'; then
  VPX="$VPX_MAIN"
elif file "$VPX_ALT" 2>/dev/null | grep -q 'ELF'; then
  VPX="$VPX_ALT"
else
  die "Aucun binaire VPX ELF valide trouve."
fi

# Compatible avec:
# - appel direct: VPXlauncher.sh "/chemin/table.vpx"
# - appel VPinFE: VPXlauncher.sh -ini ... -tableini ... -play "/chemin/table.vpx"
ORIGINAL_ARGS=("$@")
TABLE=""

for ((i=0; i<${#ORIGINAL_ARGS[@]}; i++)); do
  if [[ "${ORIGINAL_ARGS[$i]}" == "-play" ]]; then
    (( i + 1 < ${#ORIGINAL_ARGS[@]} )) || die "Option -play sans table."
    TABLE="${ORIGINAL_ARGS[$((i + 1))]}"
    break
  fi
done

if [[ -n "$TABLE" ]]; then
  # VPinFE: preserve exactement -ini, -tableini et -play.
  VPX_ARGS=("${ORIGINAL_ARGS[@]}")
elif [[ ${#ORIGINAL_ARGS[@]} -eq 0 ]]; then
  TABLE="$DEFAULT_TABLE"
  VPX_ARGS=(-play "$TABLE")
else
  # Compatibilité lancement manuel historique.
  TABLE="${ORIGINAL_ARGS[0]}"
  VPX_ARGS=(-play "$TABLE" "${ORIGINAL_ARGS[@]:1}")
fi

# PINCABOS_VPX_PREFPATH_V1
# VPX versionne son dossier de préférences (~/.local/share/VPinballX/<maj.min>).
# Au passage 10.9/11.0 le moteur repartirait sur un dossier neuf pendant que
# PinCabOS/VPinFE continueraient de lire 10.8/ (désynchronisation silencieuse).
# Parade : chemin canonique stable + option officielle -PrefPath du standalone.
# Un symlink de compatibilité conserve l ancien chemin pour tous les lecteurs.
VPX_PREF_DIR="$PCO_VPX_PREF"
VPX_LEGACY_PREF="$PCO_VPX_LEGACY_PREF"
if [[ ! -e "${VPX_PREF_DIR}" ]]; then
  mkdir -p "$(dirname "${VPX_PREF_DIR}")"
  if [[ -d "${VPX_LEGACY_PREF}" && ! -L "${VPX_LEGACY_PREF}" ]]; then
    mv "${VPX_LEGACY_PREF}" "${VPX_PREF_DIR}"
  else
    mkdir -p "${VPX_PREF_DIR}"
  fi
fi
if [[ ! -e "${VPX_LEGACY_PREF}" ]]; then
  mkdir -p "$(dirname "${VPX_LEGACY_PREF}")"
  ln -sn "${VPX_PREF_DIR}" "${VPX_LEGACY_PREF}"
fi
chown -h "$PINBALL_USER:$PINBALL_USER" "${VPX_LEGACY_PREF}" 2>/dev/null || true
chown "$PINBALL_USER:$PINBALL_USER" "$(dirname "${VPX_PREF_DIR}")" "${VPX_PREF_DIR}" 2>/dev/null || true

[[ -x "$VPX" ]] || die "VPX absent: $VPX"
[[ -f "$TABLE" ]] || die "Table absente: $TABLE"
[[ -f "$DOF_LOCAL" ]] || die "libdof permanent absent."
[[ -f "$HIDUSB" ]] || die "backend LED-Wiz absent."

ENV_ARGS=(
  -u LD_PRELOAD
  HOME="$PINBALL_HOME"
  USER="$PINBALL_USER"
  LOGNAME="$PINBALL_USER"
  DISPLAY="${DISPLAY:-:0}"
  XAUTHORITY="$PINBALL_HOME/.Xauthority"
  XDG_RUNTIME_DIR="$PCO_RUNTIME_DIR"
  DBUS_SESSION_BUS_ADDRESS="$PCO_DBUS_ADDRESS"
  XDG_DATA_HOME="$PINBALL_HOME/.local/share"
  XDG_CONFIG_HOME="$PINBALL_HOME/.config"
  XDG_CACHE_HOME="$PINBALL_HOME/.cache"
  SDL_VIDEODRIVER="x11"
  LD_LIBRARY_PATH="$OVERLAY:$DOF_DIR"
  LD_PRELOAD="$DOF_LOCAL"
  LIBDOF_LEDWIZ_HIDAPI_LIBUSB="$HIDUSB"
)

if [[ "$(id -u)" -eq 0 ]]; then
  exec runuser -u "$PINBALL_USER" -- env "${ENV_ARGS[@]}" "$VPX" -PrefPath "${VPX_PREF_DIR}" "${VPX_ARGS[@]}"
fi

[[ "$(id -un)" == "$PINBALL_USER" ]] ||   die "Lance ce script comme root ou pinball."

exec env "${ENV_ARGS[@]}" "$VPX" -PrefPath "${VPX_PREF_DIR}" "${VPX_ARGS[@]}"
