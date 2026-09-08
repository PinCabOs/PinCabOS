#!/usr/bin/env bash
# PINCABOS_ISO_ETAPES_V1 — etape 70-helper d iso.sh (texte de l ancienne section, inchange)
set -Eeuo pipefail
. "$(dirname "$(readlink -f "$0")")/00-lib.sh"
trap cleanup_mounts EXIT

echo
echo "=== 8) Payload helper (live model) ==="
# PINCABOS_PAYLOAD_SOMMES_RELATIVES_V1
# sha256sum ecrit le nom qu on lui donne. Avec un chemin ABSOLU de la machine
# de construction, le fichier de sommes grave sur le media nomme
# /opt/pincabos/build/live-.../payload-full/... — qui n existe evidemment pas
# sur le cabinet. L installateur fait « cd "$PAYLOAD_DIR" && sha256sum -c » et
# echoue sur « No such file or directory », l installation s arrete a la
# preparation (cab de Yann, 08/09/2026, ISO 4.63). Le fichier voisin
# parts.sha256 nomme deja « ../casper/filesystem.squashfs » en relatif : on
# fait pareil, en se placant dans le dossier de la charge utile.
( cd "$PAYLOAD_FULL" && sha256sum "$(basename "$ARCHIVE")" ) \
  > "$PAYLOAD_FULL/pincabos-rootfs-cab-v8.1g.sha256"
( cd "$PAYLOAD_FULL" && sha256sum "$(basename "$OVERLAY")" ) \
  > "$PAYLOAD_FULL/pincabos-plymouth-theme-overlay-v8.1g.sha256"

install -m 755 "$INSTALLER_SRC/pincabos-install-payload" "$PAYLOAD_FULL/pincabos-v8.1g-install-cab-payload-to-target.sh" \
  || die "payload helper missing: $INSTALLER_SRC/pincabos-install-payload"

bash -n "$PAYLOAD_FULL/pincabos-v8.1g-install-cab-payload-to-target.sh" \
  || die "Payload helper has a Bash syntax error"
# PINCABOS_ISO_HELPER_CONTINUATION_GUARD_V1
# `bash -n` ne voit pas une continuation cassee : une ligne finissant par
# deux backslashes est du Bash valide (argument litteral « \ ») mais coupe la
# commande en deux ; avec `set -e` le helper s'arrete et l'installation
# rend « Payload extraction/install failed (code 1) » (Alpha 3.12 a 3.46,
# commit adf4c1e du 01/09). On refuse de construire l'ISO dans ce cas.
if grep -nE '\\\\$' "$PAYLOAD_FULL/pincabos-v8.1g-install-cab-payload-to-target.sh"; then
  die "Payload helper: a line ends with a double backslash (broken continuation)"
fi
echo "GO [OK] payload helper syntax valid"
