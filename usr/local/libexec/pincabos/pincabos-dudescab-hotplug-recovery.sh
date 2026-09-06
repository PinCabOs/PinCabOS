#!/usr/bin/env bash
set -Eeuo pipefail
shopt -s nullglob

MARKER="PINCABOS_DUDESCAB_HOTPLUG_RECOVERY_V1"
LOCK="/run/pincabos/dudescab-hotplug-recovery.lock"
VPINFE_SERVICE="pincabos-vpinfe.service"

install -d -m 0755 /run/pincabos

exec 9>"$LOCK"

if ! flock -n 9; then
    exit 0
fi

log() {
    local message="$*"

    echo "$(date -Is) $message"

    logger \
        -t pincabos-dudescab-hotplug \
        "$MARKER $message"
}

vpx_running() {
    pgrep -af \
        'VPinballX|VPinballX_BGFX|VPinballX_GL' \
        >/dev/null 2>&1
}

dof_helper_pids() {
    pgrep -f \
        'vpinfe/vpinfe --dof-helper' \
        2>/dev/null || true
}

helper_has_deleted_hidraw() {
    local pid
    local fd
    local target

    while read -r pid; do
        [ -n "$pid" ] || continue
        [ -d "/proc/$pid/fd" ] || continue

        for fd in /proc/"$pid"/fd/*; do
            target="$(readlink "$fd" 2>/dev/null || true)"

            if [[ "$target" == /dev/hidraw* ]] &&
               [[ "$target" == *" (deleted)" ]]
            then
                return 0
            fi
        done
    done < <(dof_helper_pids)

    return 1
}

show_helper_hidraw() {
    local pid
    local fd
    local target

    while read -r pid; do
        [ -n "$pid" ] || continue
        [ -d "/proc/$pid/fd" ] || continue

        for fd in /proc/"$pid"/fd/*; do
            target="$(readlink "$fd" 2>/dev/null || true)"

            if [[ "$target" == /dev/hidraw* ]]; then
                log "PID=$pid FD=$(basename "$fd") TARGET=$target"
            fi
        done
    done < <(dof_helper_pids)
}

log "Détection du retour DudesCab 2e8a:106f."

DEVICE_READY=0

for attempt in $(seq 1 40); do
    SERIAL_FOUND=0
    OUTPUT_FOUND=0
    MX_FOUND=0

    compgen -G \
        '/dev/serial/by-id/*DudesCab*-if00' \
        >/dev/null &&
        SERIAL_FOUND=1

    compgen -G \
        '/dev/input/by-id/*DudesCab*-if03-hidraw' \
        >/dev/null &&
        OUTPUT_FOUND=1

    compgen -G \
        '/dev/input/by-id/*DudesCab*-if04-hidraw' \
        >/dev/null &&
        MX_FOUND=1

    if [ "$SERIAL_FOUND" -eq 1 ] &&
       [ "$OUTPUT_FOUND" -eq 1 ] &&
       [ "$MX_FOUND" -eq 1 ]
    then
        DEVICE_READY=1
        break
    fi

    sleep 1
done

if [ "$DEVICE_READY" -ne 1 ]; then
    log "Interfaces DudesCab incomplètes après 40 secondes."
    exit 1
fi

log "Interfaces série, Outputs et Outputs MX disponibles."

POWER_HELPER="/usr/local/libexec/pincabos/pincabos-dudescab-no-autosuspend.sh"

if [ -x "$POWER_HELPER" ]; then
    "$POWER_HELPER" >/dev/null 2>&1 || true
fi

if ! helper_has_deleted_hidraw; then
    log "Aucun descripteur HIDRAW supprimé dans le DOF Helper."
    show_helper_hidraw
    exit 0
fi

log "DOF Helper bloqué sur une interface HIDRAW supprimée."
show_helper_hidraw

while vpx_running; do
    log "Table VPX active : récupération différée de 5 secondes."
    sleep 5
done

if ! helper_has_deleted_hidraw; then
    log "Le DOF Helper s’est rétabli avant le redémarrage."
    exit 0
fi

if ! systemctl is-active --quiet "$VPINFE_SERVICE"; then
    log "VPinFE inactif : aucun redémarrage requis."
    exit 0
fi

log "Aucune table VPX active. Redémarrage contrôlé de VPinFE."

systemctl restart "$VPINFE_SERVICE"

for attempt in $(seq 1 60); do
    if systemctl is-active --quiet "$VPINFE_SERVICE"; then
        break
    fi

    sleep 1
done

if ! systemctl is-active --quiet "$VPINFE_SERVICE"; then
    log "ERREUR : VPinFE n’est pas revenu actif."
    exit 1
fi

sleep 8

if helper_has_deleted_hidraw; then
    log "ERREUR : un descripteur HIDRAW supprimé demeure après redémarrage."
    show_helper_hidraw
    exit 1
fi

log "Récupération réussie : DOF Helper relié aux interfaces actuelles."
show_helper_hidraw
