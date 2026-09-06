#!/usr/bin/env bash
set -Eeuo pipefail

# PINCABOS_PATHS_CONSUMER_V1
. /opt/pincabos/tools/pincabos-paths.sh

OVERLAY="/opt/pincabos/overlays/vpinfe-dof-ledwiz-hidraw-stable/libdof.so.0.4.7"
INTERNAL="$PCO_VPINFE_DIR/_internal"

[ -f "$OVERLAY" ] || exit 1
[ -d "$INTERNAL" ] || exit 1

for NAME in libdof.so libdof.so.0 libdof.so.0.4.7; do
  rm -f "$INTERNAL/$NAME"
  ln -s "$OVERLAY" "$INTERNAL/$NAME"
done
