#!/usr/bin/env bash
# ===========================================================================
#  PINCABOS — SLIM-MASTER  (PINCABOS_MASTER_ALLEGE_V1)
#
#  Amene le master aux dernieres mises a jour Ubuntu, puis lui retire ce qui
#  ne sert a rien sur un cab : les noyaux qui ne demarreront jamais, leurs
#  en-tetes, la documentation et les langues que l installateur ne propose pas.
#
#  A lancer AVANT iso.sh, sur le master prepare par build-master.sh :
#      sudo ./slim-master.sh /root/pco-master [--dry-run] [--sans-upgrade]
#
#  REFUSE de travailler sur / : ce script purge des noyaux, le passer sur un
#  cab en fonctionnement le rendrait indemarrable.
# ===========================================================================
set -Eeuo pipefail
exec < /dev/null          # PINCABOS_RECETTE_IDEMPOTENTE_V1 : personne devant

M="${1:?usage: slim-master.sh /chemin/du/master [--dry-run] [--sans-upgrade]}"
shift || true
DRY=0
UPGRADE=1
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --sans-upgrade) UPGRADE=0 ;;
    *) echo "ERREUR: argument inconnu : $a"; exit 1 ;;
  esac
done

[ "$(id -u)" -eq 0 ] || { echo "ERREUR: executer en root"; exit 1; }
M="$(readlink -f "$M")"
[ "$M" = "/" ] && { echo "ERREUR: refus de travailler sur / (ce script purge des noyaux)"; exit 1; }
[ -x "$M/usr/bin/dpkg" ] || { echo "ERREUR: $M ne ressemble pas a un rootfs"; exit 1; }
[ -d "$M/opt/pincabos" ] || { echo "ERREUR: $M n est pas un master PinCabOS"; exit 1; }

dire()  { printf '\n=== %s ===\n' "$*"; }
faire() { if [ "$DRY" -eq 1 ]; then echo "  [dry-run] $*"; else eval "$@"; fi; }
dans()  { if [ "$DRY" -eq 1 ]; then echo "  [dry-run] chroot: $*"; else chroot "$M" env DEBIAN_FRONTEND=noninteractive $*; fi; }

poids() { du -sh "$M" 2>/dev/null | cut -f1; }
AVANT="$(poids)"
dire "Master : $M ($AVANT)"

# --------------------------------------------------------------- montages
MONTES=""
monter() {
  local t
  for t in proc sys dev dev/pts; do
    mountpoint -q "$M/$t" && continue
    mkdir -p "$M/$t"
    case "$t" in
      proc) mount -t proc proc "$M/proc" ;;
      sys)  mount -t sysfs sys "$M/sys" ;;
      dev)  mount --bind /dev "$M/dev" ;;
      dev/pts) mount --bind /dev/pts "$M/dev/pts" ;;
    esac
    MONTES="$M/$t $MONTES"
  done
}
demonter() { local t; for t in $MONTES; do umount -l "$t" 2>/dev/null || true; done; }
trap demonter EXIT
[ "$DRY" -eq 1 ] || monter
[ -e "$M/etc/resolv.conf" ] || cp /etc/resolv.conf "$M/etc/resolv.conf" 2>/dev/null || true

# --------------------------------------------------- 1) mises a jour Ubuntu
if [ "$UPGRADE" -eq 1 ]; then
  dire "1) Dernieres mises a jour Ubuntu"
  # Les blocages (hold) posent le noyau du cab ; dans le master ils empechent
  # justement de prendre les mises a jour qu on vient chercher.
  TENUS="$(chroot "$M" apt-mark showhold 2>/dev/null | tr '\n' ' ' || true)"
  [ -n "$TENUS" ] && { echo "  paquets tenus, liberes le temps de la mise a jour : $TENUS"; dans apt-mark unhold $TENUS; }
  dans apt-get update -qq
  dans apt-get -y -qq -o Dpkg::Options::=--force-confold full-upgrade
  [ -n "$TENUS" ] && dans apt-mark hold $TENUS
else
  dire "1) Mises a jour Ubuntu : ignorees (--sans-upgrade)"
fi

# ------------------------------------------------------- 2) noyaux en trop
dire "2) Noyaux : on ne garde que celui qui demarrera"
GARDE="$(chroot "$M" sh -c 'ls -1 /lib/modules 2>/dev/null' | sort -V | tail -1)"
[ -n "$GARDE" ] || { echo "ERREUR: aucun noyau dans $M/lib/modules"; exit 1; }
echo "  noyau conserve : $GARDE"

# Tout paquet linux-{image,modules,headers}-<version> dont la version n est pas
# celle du noyau conserve. Les meta-paquets (…-generic sans version) restent :
# c est eux qui rameneront le prochain noyau.
# dpkg-query liste aussi les paquets CONNUS mais non installes (etat « un ») :
# les passer a apt purge le ferait echouer. On ne garde que les installes.
mapfile -t TROP < <(chroot "$M" dpkg-query -W -f='${db:Status-Abbrev} ${Package}\n' \
  'linux-image-[0-9]*' 'linux-modules-[0-9]*' 'linux-modules-extra-[0-9]*' \
  'linux-headers-[0-9]*' 2>/dev/null \
  | awk '$1 ~ /^[ih]i/ {print $2}' | grep -v -- "${GARDE%-generic}" || true)

if [ "${#TROP[@]}" -eq 0 ]; then
  echo "  rien a retirer"
else
  printf '  a purger (%s) :\n' "${#TROP[@]}"
  printf '    %s\n' "${TROP[@]}"
  dans apt-get -y -qq purge "${TROP[@]}"
fi
dans apt-get -y -qq autoremove --purge

# Restes hors dpkg (initrd fabriques a la main, modules orphelins)
dire "3) Restes de noyaux hors dpkg"
for v in $(ls -1 "$M/lib/modules" 2>/dev/null); do
  [ "$v" = "$GARDE" ] && continue
  echo "  modules orphelins : $v"
  faire "rm -rf '$M/lib/modules/$v'"
done
for f in "$M"/boot/vmlinuz-* "$M"/boot/initrd.img-* "$M"/boot/System.map-* "$M"/boot/config-*; do
  [ -e "$f" ] || continue
  case "$f" in *"$GARDE") continue ;; esac
  echo "  fichier de boot orphelin : $(basename "$f")"
  faire "rm -f '$f'"
done

# ------------------------------------------- 3bis) anciens bundles versionnes
dire "3bis) Anciens bundles de runtime (avant PINCABOS_RUNTIME_ROTATION_V1)"
# Le modele d avant nommait le dossier par sa version et posait un lien vpx
# dessus. Sur un master reconstruit, la recette remplace le lien par un vrai
# dossier vpx : l ancien bundle reste alors a cote, 372 Mo pour rien.
trouve=0
for d in "$M"/opt/pinball/VPinballX_BGFX-*/; do
  [ -d "$d" ] || continue
  trouve=1
  echo "  bundle versionne : $(basename "${d%/}") ($(du -sh "$d" 2>/dev/null | cut -f1))"
  faire "rm -rf '${d%/}'"
done
[ "$trouve" -eq 0 ] && echo "  aucun"

# ---------------------------------------------- 4) documentation et langues
dire "4) Documentation, pages de manuel, traductions"
# Les fichiers copyright restent : l image est redistribuee.
echo "  usr/share/doc  : $(du -sh "$M/usr/share/doc" 2>/dev/null | cut -f1) -> on ne garde que les copyright"
faire "find '$M/usr/share/doc' -type f ! -name copyright -delete 2>/dev/null || true"
faire "find '$M/usr/share/doc' -type d -empty -delete 2>/dev/null || true"
echo "  usr/share/man  : $(du -sh "$M/usr/share/man" 2>/dev/null | cut -f1) -> retire"
faire "rm -rf '$M/usr/share/man'/*"
# Les cinq langues de l installateur, plus le C par defaut.
LANGUES="C en en_GB en_US fr fr_FR de de_DE it it_IT es es_ES"
echo "  usr/share/locale : $(ls "$M/usr/share/locale" 2>/dev/null | wc -l) langues -> on garde $LANGUES"
if [ "$DRY" -eq 0 ]; then
  for d in "$M"/usr/share/locale/*/; do
    n="$(basename "$d")"
    case " $LANGUES " in *" $n "*) continue ;; esac
    rm -rf "$d"
  done
else
  echo "  [dry-run] suppression des autres langues"
fi

# --------------------------------------------------------- 5) caches divers
dire "5) Caches"
dans apt-get clean
for d in var/lib/apt/lists var/cache/apt/archives root/.cache var/crash var/log/journal; do
  [ -d "$M/$d" ] || continue
  echo "  $d : $(du -sh "$M/$d" 2>/dev/null | cut -f1)"
  faire "find '$M/$d' -mindepth 1 -delete 2>/dev/null || true"
done
echo "  __pycache__ : $(find "$M" -name __pycache__ -type d 2>/dev/null | wc -l) dossiers"
faire "find '$M' -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true"

# ------------------------------------------------------------------ bilan
demonter
dire "Bilan"
APRES="$(poids)"
echo "  avant : $AVANT"
echo "  apres : $APRES"
[ "$DRY" -eq 1 ] && echo "  (dry-run : rien n a ete modifie)"
echo
echo "  noyau embarque : $GARDE"
chroot "$M" dpkg -l 2>/dev/null | awk '/linux-(image|modules|headers)/ {print "    " $1, $2, $3}' || true
