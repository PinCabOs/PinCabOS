#!/usr/bin/env bash
# PINCABOS_ISO_ETAPES_V1 — iso.sh : orchestrateur des etapes de construction de l ISO
#
# Avant : un script de 2 060 lignes, d un seul tenant ; une erreur a la 14e minute
# obligeait a tout recommencer. Maintenant : dix etapes relancables, chacune un
# fichier de opt/pincabos/script/iso/ (texte des anciennes sections, inchange),
# une bibliotheque commune (00-lib.sh : variables, die, run, cleanup_mounts), un
# journal par build et par etape, un marqueur GO par etape reussie.
#
#   iso.sh                 toutes les etapes, dans l ordre (comme avant)
#   iso.sh --liste         les etapes et leur etat (GO / a faire)
#   iso.sh --etape 40      une seule etape (numero ou nom : 40, 40-payload)
#   iso.sh --depuis 60     reprend a partir d une etape (les precedentes doivent avoir leur GO)
#   iso.sh --jusqua 70     s arrete apres cette etape
#   iso.sh --source DIR    photographie ce rootfs prepare (build-master.sh) au lieu du cab
#                          courant : plus besoin d un cab source (PINCABOS_ISO_SOURCE_V1)
#   --live accepte (compatibilite) ; --classic refuse (PINCABOS_ISO_MODELE_LIVE_V2)
set -Eeuo pipefail

# PINCABOS_RECETTE_IDEMPOTENTE_V3 : la construction tourne sans personne devant.
# L etape 95 propose une publication web et attendait une reponse sur l entree
# standard : elle a fige une construction 36 minutes (07/09/2026). Plus d entree.
exec < /dev/null

PCO_ISO_SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
export PCO_ISO_SCRIPT_DIR
ETAPES_DIR="$PCO_ISO_SCRIPT_DIR/iso"
[ -d "$ETAPES_DIR" ] || ETAPES_DIR="/opt/pincabos/script/iso"
[ -f "$ETAPES_DIR/00-lib.sh" ] || { echo "ERROR: etapes absentes : $ETAPES_DIR"; exit 1; }

SEULE=""; DEPUIS=""; JUSQUA=""; LISTE=0; SOURCE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --live) ;;
    --classic) echo "ERROR: le modele classique a ete retire (PINCABOS_ISO_MODELE_LIVE_V2) : l ISO est le systeme, voir iso-live.sh"; exit 2 ;;
    --liste) LISTE=1 ;;
    --etape) SEULE="${2:-}"; shift ;;
    --depuis) DEPUIS="${2:-}"; shift ;;
    --jusqua) JUSQUA="${2:-}"; shift ;;
    --source) SOURCE="${2:-}"; shift ;;
    -h|--help) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "ERROR: argument inconnu : $1"; exit 1 ;;
  esac
  shift
done

# etapes : NN-nom.sh, sauf la bibliotheque
mapfile -t ETAPES < <(cd "$ETAPES_DIR" && ls -1 [0-9][0-9]-*.sh | grep -v '^00-' | sort)
numero() { printf '%s' "${1%%-*}"; }
trouver() {   # numero ou nom -> fichier d etape
  local e
  for e in "${ETAPES[@]}"; do
    [ "$1" = "$e" ] || [ "$1" = "${e%.sh}" ] || [ "$1" = "$(numero "$e")" ] && { printf '%s' "$e"; return 0; }
  done
  return 1
}

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root"
  exit 1
fi

# PINCABOS_ISO_SOURCE_V1 : la source, verifiee avant tout, transmise aux etapes
if [ -n "$SOURCE" ]; then
  SOURCE="$(readlink -f "$SOURCE" 2>/dev/null || printf '%s' "$SOURCE")"
  [ -d "$SOURCE/opt/pincabos" ] || { echo "ERROR: --source $SOURCE : pas un rootfs PinCabOS (opt/pincabos absent)"; exit 1; }
  export PCO_ISO_SOURCE="$SOURCE"
fi
# variables communes (WORK, LOG_DIR, ...) : la lib, sans journal ni trap ici
PCO_ISO_LOG="" . "$ETAPES_DIR/00-lib.sh"
# les marqueurs GO vivent hors de $WORK : l etape 10 efface $WORK (rm -rf), et c est normal
ETAT_DIR="$LOG_DIR/etat"
mkdir -p "$LOG_DIR/etapes" "$ETAT_DIR"

if [ "$LISTE" -eq 1 ]; then
  for e in "${ETAPES[@]}"; do
    if [ -f "$ETAT_DIR/$(numero "$e").go" ]; then
      printf '  GO      %s  (%s)\n' "${e%.sh}" "$(cat "$ETAT_DIR/$(numero "$e").go")"
    else
      printf '  a faire %s\n' "${e%.sh}"
    fi
  done
  exit 0
fi

# selection
A_FAIRE=()
if [ -n "$SEULE" ]; then
  f="$(trouver "$SEULE")" || { echo "ERROR: etape inconnue : $SEULE (voir --liste)"; exit 1; }
  A_FAIRE=("$f")
else
  actif=1; [ -n "$DEPUIS" ] && actif=0
  for e in "${ETAPES[@]}"; do
    if [ "$actif" -eq 0 ]; then
      [ "$(numero "$e")" = "$(numero "$(trouver "$DEPUIS" || echo "$DEPUIS")")" ] && actif=1
    fi
    [ "$actif" -eq 1 ] && A_FAIRE+=("$e")
    if [ -n "$JUSQUA" ] && [ "$(numero "$e")" = "$(numero "$(trouver "$JUSQUA" || echo "$JUSQUA")")" ]; then
      break
    fi
  done
  [ "${#A_FAIRE[@]}" -gt 0 ] || { echo "ERROR: aucune etape selectionnee (--depuis/--jusqua)"; exit 1; }
fi

# reprise : les etapes precedant la premiere selectionnee doivent avoir leur GO
premiere="$(numero "${A_FAIRE[0]}")"
for e in "${ETAPES[@]}"; do
  [ "$(numero "$e")" \< "$premiere" ] || break
  [ -f "$ETAT_DIR/$(numero "$e").go" ] || echo "WARNING: etape ${e%.sh} sans GO : ses resultats sont supposes en place"
done

# un journal par build (comme avant : tout ce qui suit est journalise)
LOG="$LOG_DIR/iso-v8.1g-$(date +%Y%m%d-%H%M%S).log"
export PCO_ISO_LOG="$LOG"
exec > >(tee -a "$LOG") 2>&1

[ -n "$SEULE" ] || { [ -t 1 ] && clear || true; }
echo "==============================================================="
echo " PINCABOS — MASTER ISO BUILDER V8.1G ENGLISH"
echo " Clean -> Payload -> ISO-ready -> Live installer -> Bootable ISO"
echo "==============================================================="
echo "ISO model: $PCO_ISO_MODEL"
echo "Source: ${PCO_ISO_SOURCE:-/}"
echo
echo "Log:"
echo "$LOG"
echo "Etapes : $(printf '%s ' "${A_FAIRE[@]%.sh}")"

for e in "${A_FAIRE[@]}"; do
  n="$(numero "$e")"
  rm -f "$ETAT_DIR/$n.go"
  debut=$(date +%s)
  echo
  echo "###############################################################"
  echo "### ETAPE ${e%.sh}   $(date -Is)"
  echo "###############################################################"
  journal_etape="$LOG_DIR/etapes/$(basename "$LOG" .log)-$n.log"
  if bash "$ETAPES_DIR/$e" 2>&1 | tee "$journal_etape"; then
    duree=$(( $(date +%s) - debut ))
    mkdir -p "$ETAT_DIR" && date -Is > "$ETAT_DIR/$n.go"
    echo "GO [OK] etape ${e%.sh} terminee en ${duree}s"
  else
    duree=$(( $(date +%s) - debut ))
    echo
    echo "NOGO [***] etape ${e%.sh} en echec apres ${duree}s — journal : $journal_etape"
    echo "Reprendre : $0 --etape $n   puis   $0 --depuis $(printf '%s\n' "${ETAPES[@]}" | awk -v n="$e" '$0==n{getline; print substr($0,1,2); exit}')"
    exit 1
  fi
done

echo
echo "GO [OK] etapes terminees : $(printf '%s ' "${A_FAIRE[@]%.sh}")"
