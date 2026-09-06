#!/usr/bin/env bash
set -Eeuo pipefail
# PINCABOS_PATHS_CONSUMER_V1
. /opt/pincabos/tools/pincabos-paths.sh
# PINCABOS_HYBRID_LAUNCH_CORE_V3_2_1
# PINCABOS_DIRECT_LAUNCH_MODES_V2

MODE="${1:-hybrid}"
shift || true

LAUNCHER_DIR="/opt/pincabos/launchers"
DETECTOR="${LAUNCHER_DIR}/pincabos-detect-table-modes.py"
CHOOSER="${LAUNCHER_DIR}/pincabos-hybrid-chooser.py"
ASSET="${LAUNCHER_DIR}/assets/PCOSGamesChoices.png"
MODE_HELPER="${PINCABOS_MODE_HELPER:-/usr/local/sbin/pincabos-hybrid-pup-mode}"
PUPPACK_TOOL="${PINCABOS_PUPPACK_TOOL:-/opt/pincabos/bin/pincabos-puppack-option}"
REAL_LAUNCHER="${PINCABOS_REAL_LAUNCHER:-/opt/pincabos/scripts/VPXlauncher.real.sh}"
PINBALL_UID="$PCO_UID"
CALLER_UID="$(id -u)"
SHARED_RUNTIME_DIR="/run/pincabos-hybrid-launcher"
USER_RUNTIME_BASE="${XDG_RUNTIME_DIR:-/run/user/${CALLER_UID}}"

# PINCABOS_HYBRID_RUNTIME_FIX_V1
# Le verrou partagé est préféré. Si ses droits sont incorrects ou si /run
# n'est pas encore préparé, le launcher utilise le runtime de l'utilisateur.
if [[ -d "$SHARED_RUNTIME_DIR" && -w "$SHARED_RUNTIME_DIR" ]]; then
    RUNTIME_DIR="$SHARED_RUNTIME_DIR"
elif [[ -d "$USER_RUNTIME_BASE" && -w "$USER_RUNTIME_BASE" ]]; then
    RUNTIME_DIR="${USER_RUNTIME_BASE}/pincabos-hybrid-launcher"
else
    RUNTIME_DIR="/tmp/pincabos-hybrid-launcher-${CALLER_UID}"
fi

# PINCABOS_HYBRID_LOG_PERMISSION_FIX_V2
SHARED_LOG_DIR="/var/log/pincabos-hybrid-launcher"
FALLBACK_LOG_DIR="${RUNTIME_DIR}/logs"

mkdir -p "$RUNTIME_DIR"

LOG_DIR="$FALLBACK_LOG_DIR"

#
# Le dossier partagé ne suffit pas :
# launcher.log peut avoir été créé auparavant par root.
#
# On utilise le log partagé seulement si le FICHIER est
# réellement inscriptible par l'utilisateur courant.
#
if [[ -d "$SHARED_LOG_DIR" && -w "$SHARED_LOG_DIR" ]]; then

    SHARED_LOG_FILE="${SHARED_LOG_DIR}/launcher.log"

    #
    # Création coopérative du fichier.
    #
    if [[ ! -e "$SHARED_LOG_FILE" ]]; then

        OLD_UMASK="$(umask)"
        umask 0002

        touch "$SHARED_LOG_FILE" \
            2>/dev/null \
            || true

        umask "$OLD_UMASK"

    fi

    #
    # Si le launcher tourne en root, il normalise lui-même
    # le fichier afin de ne pas casser le prochain lancement
    # exécuté par pinball.
    #
    if [[ "$EUID" -eq 0 && -e "$SHARED_LOG_FILE" ]]; then

        chown pinball:pinball \
            "$SHARED_LOG_FILE" \
            2>/dev/null \
            || true

        chmod 0664 \
            "$SHARED_LOG_FILE" \
            2>/dev/null \
            || true

    fi

    if [[ -w "$SHARED_LOG_FILE" ]]; then

        LOG_DIR="$SHARED_LOG_DIR"

    fi

fi


#
# Repli sûr par utilisateur.
#
mkdir -p "$LOG_DIR"

LOG="${LOG_DIR}/launcher.log"

if [[ ! -e "$LOG" ]]; then

    OLD_UMASK="$(umask)"
    umask 0002

    touch "$LOG"

    umask "$OLD_UMASK"

fi

LOCK="${RUNTIME_DIR}/launcher.lock"

if ! exec 8>"$LOCK"; then
    echo "NOGO [X] Impossible d'ouvrir le verrou du launcher : $LOCK" >&2
    exit 73
fi
flock -x 8

log() {
    local line="$*"
    printf '%s\n' "$line"
    printf '%s %s\n' "$(date -Is)" "$line" >> "$LOG" 2>/dev/null || true
    logger -t pincabos-hybrid-launcher -- "$line" 2>/dev/null || true
}

mode_helper() {
    if [[ "$EUID" -eq 0 ]]; then
        "$MODE_HELPER" "$@"
    else
        sudo -n "$MODE_HELPER" "$@"
    fi
}

find_table_argument() {
    local argument
    for argument in "$@"; do
        if [[ "${argument,,}" == *.vpx ]]; then
            printf '%s\n' "$argument"
            return 0
        fi
    done
    return 1
}

# PINCABOS_DIRECT_PUP_ROOT_V1
#
# PINCABOS_PUPVIDEOS_ALIAS_V1
# Le plugin PuP de VPX ne lit que le dossier "pupvideos" a cote de la table
# ("No global PUP folder configured; per-table 'pupvideos' used when
# present"). Un pack range sous un autre nom (Terminator 2 : "pinupvideo")
# etait detecte, propose au chooser, puis ignore par VPX : aucune fenetre
# PuP, et l'ecran du menu qui transparait sur le backglass. On pose un lien
# "pupvideos" vers le dossier reel. Le masquage du mode Original resout les
# liens (realpath) et connait deja ces noms.
ensure_pupvideos_alias() {
    local table="$1" directory root name
    directory="$(dirname -- "$table")"
    # PINCABOS_PUPVIDEOS_ALIAS_V2
    # Terminator 2 avait a la fois "pinupvideo/t2_l8" (501 fichiers) et un
    # "pupvideos/" VIDE, cree par le squelette d'import : VPX ne voyait que le
    # dossier vide. Un pupvideos vide est retire (rmdir echoue s'il ne l'est
    # pas) pour laisser la place au lien.
    if [[ -d "$directory/pupvideos" && ! -L "$directory/pupvideos" ]]; then
        if [[ -z "$(ls -A -- "$directory/pupvideos" 2>/dev/null)" ]]; then
            rmdir -- "$directory/pupvideos" 2>/dev/null || return 0
        else
            return 0
        fi
    fi
    [[ -L "$directory/pupvideos" ]] && return 0
    root="$(find_local_pup_root "$table" || true)"
    [[ -n "$root" && -d "$root" ]] || return 0
    name="${root##*/}"
    [[ "${name,,}" == "pupvideos" ]] && return 0
    if ln -s -- "$name" "$directory/pupvideos" 2>/dev/null; then
        log "PUP [=] Lien pupvideos -> $name pose (le plugin PuP de VPX ne lit que 'pupvideos')."
    else
        log "AVERTISSEMENT [!] Impossible de poser le lien pupvideos -> $name."
    fi
}

ensure_pack_rom_alias() {
    # PINCABOS_PUPVIDEOS_ROM_ALIAS_V3
    # Le plugin PuP de VPX cherche le pack dans pupvideos/<nom de ROM>. JP's
    # Transformers livre le sien sous "tf_180og" pour la ROM tf_180 : en mode
    # PuP rien ne s'affichait (backglass noir, DMD seul), le plugin ne trouvant
    # pas "pupvideos/tf_180". Quand aucun dossier ne porte le nom de la ROM et
    # qu'un seul pack existe, on pose un lien symbolique au nom de la ROM.
    local table="$1" directory pv rom="" pack n=0 only="" out
    directory="$(dirname -- "$table")"
    pv="$directory/pupvideos"
    [[ -d "$pv" ]] || return 0
    if [[ -z "${DETECT_ROM_FILES+x}" && -x "$DETECTOR" ]]; then
        out="$(python3 "$DETECTOR" --shell "$table" 2>/dev/null)" && eval "$out"
    fi
    while IFS= read -r pack; do
        [[ -n "$pack" ]] || continue
        rom="$(basename -- "$pack")"; rom="${rom%.*}"
        [[ -n "$rom" ]] && break
    done <<< "${DETECT_ROM_FILES:-}"
    [[ -n "$rom" ]] || return 0
    [[ -e "$pv/$rom" ]] && return 0
    while IFS= read -r pack; do
        [[ -n "$pack" && -d "$pack" ]] || continue
        case "$pack" in
            "$pv"/*) n=$((n + 1)); only="$pack" ;;
        esac
    done <<< "${DETECT_PUP_PACKS:-}"
    [[ "$n" -eq 1 ]] || return 0
    if ln -s -- "$(basename -- "$only")" "$pv/$rom" 2>/dev/null; then
        log "PUP [=] Lien pupvideos/$rom -> $(basename -- "$only") pose (le plugin PuP cherche le pack au nom de la ROM)."
    else
        log "AVERTISSEMENT [!] Impossible de poser le lien pupvideos/$rom -> $(basename -- "$only")."
    fi
}

# Ce finder NE choisit PAS le mode de jeu.
# Il sert seulement au bouton Legacy afin de masquer un
# éventuel dossier PuP local pendant l'exécution Original.
find_local_pup_root() {
    local table="$1"
    local directory
    local child
    local name

    directory="$(dirname -- "$table")"

    [[ -d "$directory" ]] || return 1

    while IFS= read -r -d '' child; do
        [[ -d "$child" ]] || continue

        name="${child##*/}"

        case "${name,,}" in
            pupvideos|pupvideo|pinupvideo|pinupvideos)
                printf '%s\n' "$child"
                return 0
                ;;
        esac

    done < <(
        find "$directory" \
            -mindepth 1 \
            -maxdepth 1 \
            -type d \
            -print0 2>/dev/null
    )

    return 1
}


run_chooser() {
    local result="$1" default="$2" timeout="$3"
    local command=(python3 "$CHOOSER" "$ASSET" "$result" "$default" "$timeout")
    rm -f "$result"

    if [[ "$EUID" -eq 0 ]]; then
        runuser -u "$PCO_USER" -- env \
            HOME="$PCO_HOME" \
            USER="$PCO_USER" \
            LOGNAME="$PCO_USER" \
            DISPLAY=:0 \
            XAUTHORITY="$PCO_XAUTHORITY" \
            XDG_RUNTIME_DIR="/run/user/${PINBALL_UID}" \
            SDL_VIDEO_X11_WMCLASS=PinCabOSHybridChooser \
            "${command[@]}"
    else
        env \
            DISPLAY="${DISPLAY:-:0}" \
            XAUTHORITY="${XAUTHORITY:-$PCO_XAUTHORITY}" \
            XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/${PINBALL_UID}}" \
            SDL_VIDEO_X11_WMCLASS=PinCabOSHybridChooser \
            "${command[@]}"
    fi
}

read_choice() {
    python3 - "$1" "$2" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
default = "pup" if sys.argv[2].startswith("pup") else "original"
try:
    choice = str(json.loads(path.read_text(encoding="utf-8")).get("choice", default)).lower()
except Exception:
    choice = default
print("pup" if choice.startswith("pup") else "original")
PY
}

if [[ "$MODE" != "hybrid" && "$MODE" != "original" && "$MODE" != "pup" ]]; then
    echo "Usage interne : $0 hybrid|original|pup [--detect-only] TABLE.vpx [arguments]" >&2
    exit 64
fi

DETECT_ONLY=0
FILTERED_ARGS=()
for argument in "$@"; do
    if [[ "$argument" == "--detect-only" ]]; then
        DETECT_ONLY=1
    else
        FILTERED_ARGS+=("$argument")
    fi
done

TABLE="$(find_table_argument "${FILTERED_ARGS[@]}")" || {
    log "NOGO [X] Aucun chemin .vpx reçu."
    exit 64
}

[[ -f "$TABLE" ]] || {
    log "NOGO [X] Table VPX absente : $TABLE"
    exit 65
}

[[ -x "$MODE_HELPER" ]] || {
    log "NOGO [X] Helper PuP absent : $MODE_HELPER"
    exit 65
}

[[ -x "$REAL_LAUNCHER" ]] || {
    log "NOGO [X] Launcher VPX réel absent : $REAL_LAUNCHER"
    exit 66
}

mode_helper recover >> "$LOG" 2>&1 || true


# =============================================================
# HYBRID = VPINFE = AUTODETECTION
# =============================================================

if [[ "$MODE" == "hybrid" ]]; then

    [[ -x "$DETECTOR" ]] || {
        log "NOGO [X] Détecteur absent : $DETECTOR"
        exit 65
    }

    eval "$(python3 "$DETECTOR" --shell "$TABLE")"

    log "TABLE=$DETECT_TABLE"
    log "MODE_DETECTE=$DETECT_MODE ORIGINAL=$DETECT_ORIGINAL PUP=$DETECT_PUP DEFAULT=$DETECT_DEFAULT"

    [[ -n "$DETECT_B2S" ]] && \
        log "B2S=$DETECT_B2S"

    [[ -n "$DETECT_PUP_ROOT" ]] && \
        log "PUP_ROOT=$DETECT_PUP_ROOT"

    if [[ "$DETECT_ONLY" == "1" ]]; then
        python3 "$DETECTOR" "$TABLE"
        exit 0
    fi

    # Le chooser n'est nécessaire que si la détection prouve
    # que les deux modes sont disponibles.
    if [[ "$DETECT_ORIGINAL" == "1" && "$DETECT_PUP" == "1" ]]; then

        [[ -x "$CHOOSER" ]] || {
            log "NOGO [X] Chooser absent : $CHOOSER"
            exit 65
        }

        [[ -f "$ASSET" ]] || {
            log "NOGO [X] Image absente : $ASSET"
            exit 65
        }
    fi

elif [[ "$DETECT_ONLY" == "1" ]]; then

    log "NOGO [X] --detect-only est reserve au mode Hybrid / VPinFE."
    exit 64
fi

SELECTED_MODE="$MODE"
FORCED_CHOICE="${PINCABOS_HYBRID_FORCE_CHOICE:-}"
FORCED_CHOICE="${FORCED_CHOICE,,}"
case "$FORCED_CHOICE" in
    puppack|pup-pack) FORCED_CHOICE="pup" ;;
esac

if [[ "$MODE" == "hybrid" ]]; then
    if [[ "$DETECT_ORIGINAL" == "1" && "$DETECT_PUP" == "1" ]]; then
        if [[ "$FORCED_CHOICE" == "original" || "$FORCED_CHOICE" == "pup" ]]; then
            SELECTED_MODE="$FORCED_CHOICE"
            log "HYBRID [TEST] Sélection forcée par script : $SELECTED_MODE (aucun chooser affiché)."
        else
            if [[ -n "$FORCED_CHOICE" ]]; then
                log "AVERTISSEMENT [!] PINCABOS_HYBRID_FORCE_CHOICE invalide : $FORCED_CHOICE"
            fi
            RESULT="${RUNTIME_DIR}/choice-$$.json"
            TIMEOUT="${PINCABOS_HYBRID_TIMEOUT:-$DETECT_TIMEOUT}"
            log "HYBRID [=] Original et PuP-Pack détectés : flippers pour sélectionner, Launch/Plunger pour confirmer."
            if run_chooser "$RESULT" "$DETECT_DEFAULT" "$TIMEOUT"; then
                SELECTED_MODE="$(read_choice "$RESULT" "$DETECT_DEFAULT")"
            else
                SELECTED_MODE="$DETECT_DEFAULT"
                log "AVERTISSEMENT [!] Le chooser a échoué; mode par défaut utilisé : $SELECTED_MODE"
            fi
            rm -f "$RESULT"
        fi
    elif [[ "$DETECT_PUP" == "1" ]]; then
        SELECTED_MODE="pup"
        log "HYBRID [√] PuP-Pack seulement : lancement direct."
    else
        SELECTED_MODE="original"
        log "HYBRID [√] Original seulement : lancement direct."
    fi
fi

# PINCABOS_BACKBOARD_RETOUR_V1
#
# A la sortie d'une table, le TeensyStripController garde la derniere image que
# DOF lui a envoyee : le backboard HD reste fige sur les effets de la table
# jusqu'au prochain evenement du frontend, soit dix secondes d'attente, soit
# jusqu'a ce que le joueur change de table. On efface le mur des que VPX rend la
# main ; VPinFE reprend ensuite avec le logo animé de la table survolee (les
# evenements DOF de son menu). Sans backboard, sans outil, ou si le port est
# deja repris : rien, jamais d'erreur, jamais de blocage.
eteindre_backboard() {
    local outil=/usr/local/sbin/pincabos-backboard-blank
    [[ -x "$outil" ]] || return 0
    "$outil" table >> "$LOG" 2>&1 || true
}

case "$SELECTED_MODE" in
    original)
        # =====================================================
        # PINCAB EXPLORER : PLAY LEGACY
        # =====================================================
        #
        # Le mode est DEJA choisi par le bouton.
        # Aucune autodétection ne décide Original/PuP ici.
        #
        HIDDEN=0
        DIRECT_PUP_ROOT=""

        restore_pup() {
            if [[ "$HIDDEN" == "1" ]]; then
                mode_helper show >> "$LOG" 2>&1 || true
                HIDDEN=0
            fi
        }

        # PINCABOS_RETOUR_FRONTEND_V1 : au retour de table, l'ecran restait
        # parfois noir (Alpha 3.77, playfield 4K NVIDIA) : le frontend n'est
        # pas redessine tant qu'il n'a pas retrouve le focus. On le lui rend
        # et on force un rafraichissement X ; sans effet quand tout va bien.
        reveiller_frontend() {
            [[ -n "${DISPLAY:-}" ]] || return 0
            if command -v xdotool >/dev/null 2>&1; then
                # PINCABOS_RETOUR_FRONTEND_V2 : VPinFE a trois fenetres (Table, BG, DMD) ;
                # la premiere venue etait BG ou DMD et le clavier partait sur l'autre
                # ecran (retex cab de Yann, 3.88 : alt-tab obligatoire apres la table).
                # La fenetre principale d'abord, une fenetre VPinFE quelconque sinon.
                local w
                w="$(xdotool search --onlyvisible --name '^VPinFE Table$' 2>/dev/null | head -1 || true)"
                [[ -n "$w" ]] || w="$(xdotool search --onlyvisible --name '^VPinFE' 2>/dev/null | head -1 || true)"
                if [[ -n "$w" ]]; then
                    xdotool windowactivate "$w" >/dev/null 2>&1 || true
                    log "RETOUR [=] frontend VPinFE reactive (fenetre $w : $(xdotool getwindowname "$w" 2>/dev/null))."
                fi
            fi
            command -v xrefresh >/dev/null 2>&1 && xrefresh >/dev/null 2>&1 || true
        }

        trap restore_pup EXIT INT TERM HUP

        DIRECT_PUP_ROOT="$(
            find_local_pup_root "$TABLE" || true
        )"

        if [[ -n "$DIRECT_PUP_ROOT" && -d "$DIRECT_PUP_ROOT" ]]; then

            log "LEGACY [=] PuP local masque : $DIRECT_PUP_ROOT"

            mode_helper hide \
                "$DIRECT_PUP_ROOT" \
                >> "$LOG" 2>&1

            HIDDEN=1

        else

            log "LEGACY [=] Aucun dossier PuP local a masquer."

        fi

        log "LEGACY [▶] Lancement Original direct."

        set +e

        env \
            PINCABOS_GAME_CHOICE=original \
            PINCABOS_PUP_ENABLED=0 \
            "$REAL_LAUNCHER" "${FILTERED_ARGS[@]}"

        RC=$?

        set -e

        eteindre_backboard
        restore_pup
        trap - EXIT INT TERM HUP
        reveiller_frontend

        exit "$RC"
        ;;
    pup)
        # =====================================================
        # PINCAB EXPLORER : PLAY PUPPACK
        # =====================================================
        #
        # Le mode est DEJA choisi par le bouton Play PUPPack.
        # Le détecteur n'a pas le droit de transformer ce choix
        # en NOGO.
        #
        # On restaure un éventuel PuP précédemment masqué puis
        # VPX/PuP applique la configuration réelle du pack :
        # vidéos, B2S éventuel, FullDMD, etc.
        #
        mode_helper show >> "$LOG" 2>&1 || true

        ensure_pupvideos_alias "$TABLE"
        ensure_pack_rom_alias "$TABLE"

        # PINCABOS_PUPPACK_GUARD_V1
        #
        # Un PuP-Pack arrive non configure de chez son auteur, et une table
        # importee d'un cabinet mieux equipe arrive configuree pour des
        # ecrans absents d'ici. Dans les deux cas le pack ne montre rien et
        # rien ne l'explique. On corrige quand c'est possible, on le dit
        # toujours, et l'etat d'origine reste restaurable.
        if [[ -x "$PUPPACK_TOOL" ]]; then
            PUPPACK_MESSAGE="$("$PUPPACK_TOOL" autofix "$TABLE" 2>&1 || true)"
            [[ -n "$PUPPACK_MESSAGE" ]] && log "$PUPPACK_MESSAGE"
        fi

        log "PUP [▶] Lancement PUPPack direct."

        # PINCABOS_BACKBOARD_RETOUR_V1 : ce mode partait en `exec`, donc rien ne
        # s'executait au retour de la table. Le lanceur attend maintenant la fin
        # de VPX, efface le mur et rend son code de sortie, comme le mode Original.
        set +e
        env \
            PINCABOS_GAME_CHOICE=pup \
            PINCABOS_PUP_ENABLED=1 \
            "$REAL_LAUNCHER" "${FILTERED_ARGS[@]}"
        RC=$?
        set -e

        eteindre_backboard

        exit "$RC"
        ;;
    *)
        log "NOGO [X] Mode final invalide : $SELECTED_MODE"
        exit 68
        ;;
esac
