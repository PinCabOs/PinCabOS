#!/usr/bin/env bash
set -Eeuo pipefail
# PINCABOS_PATHS_CONSUMER_V1
. /opt/pincabos/tools/pincabos-paths.sh

exec /usr/sbin/runuser -u "$PCO_USER" -- /usr/bin/env -u LD_PRELOAD \
  HOME="$PCO_HOME" \
  USER="$PCO_USER" \
  LOGNAME="$PCO_USER" \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  DISPLAY=:0 \
  XAUTHORITY="$PCO_XAUTHORITY" \
  XDG_RUNTIME_DIR="$PCO_RUNTIME_DIR" \
  DBUS_SESSION_BUS_ADDRESS="$PCO_DBUS_ADDRESS" \
  LD_LIBRARY_PATH=/opt/pincabos/overlays/libdof-canonical \
  VPINFE_DOF_DIR=/opt/pincabos/overlays/libdof-canonical \
  LIBDOF_LEDWIZ_HIDAPI_LIBUSB=/usr/lib/x86_64-linux-gnu/libhidapi-libusb.so.0 \
  "$PCO_VPINFE_BIN"
