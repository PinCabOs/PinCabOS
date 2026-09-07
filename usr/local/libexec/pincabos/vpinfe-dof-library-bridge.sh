#!/usr/bin/env bash
set -Eeuo pipefail

# PINCABOS_PATHS_CONSUMER_V1
. /opt/pincabos/tools/pincabos-paths.sh

# PINCABOS_LIBDOF_UNIQUE_V1
# VPX et VPinFE pilotent le meme cabinet avec la meme configuration : ils
# doivent tourner sur le MEME binaire. Ils ont diverge trois mois (cab de Yann,
# 08/09/2026 : VPX sur le build d aout, VPinFE sur celui de juin) parce que
# VPinFE passait par un second overlay, et que opt/pincabos/overlays/ est hors
# du perimetre des mises a jour — l ecart etait invisible et non rattrapable.
OVERLAY="/opt/pincabos/overlays/libdof-canonical/libdof.so.0.4.7"
INTERNAL="$PCO_VPINFE_DIR/_internal"

[ -f "$OVERLAY" ] || exit 1
[ -d "$INTERNAL" ] || exit 1

for NAME in libdof.so libdof.so.0 libdof.so.0.4.7; do
  rm -f "$INTERNAL/$NAME"
  ln -s "$OVERLAY" "$INTERNAL/$NAME"
done
