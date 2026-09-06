#!/usr/bin/env bash
set -Eeuo pipefail

export GIT_PAGER=cat
export PAGER=cat
export GIT_EDITOR=true

GITDIR="/opt/pincabos/.git-rootfs"
REMOTE_OK="https://github.com/PinCabOS/PinCabOS.git"
LOCK="/run/lock/pincabos-gitpush.lock"
STAMP="$(date +%Y%m%d-%H%M%S)"

MODE="push"

case "${1:-}" in
    "")
        ;;
    --audit)
        MODE="audit"
        ;;
    *)
        echo "Usage: gitpush.sh [--audit]"
        exit 2
        ;;
esac

pgit() {
    git --no-pager \
        --git-dir="$GITDIR" \
        --work-tree=/ \
        "$@"
}

exec 9>"$LOCK"

if ! flock -n 9; then
    echo "NOGO [LOCK] Un gitpush est deja en cours."
    exit 1
fi

cd /

echo "================================================================"
echo " PINCABOS - GITPUSH"
echo " CABINET = SOURCE DE VERITE"
echo " GITHUB = MIROIR DISASTER RECOVERY"
echo "================================================================"

echo
echo "=== 1. GARDES ==="

[[ "$(id -u)" -eq 0 ]] || {
    echo "NOGO [ROOT]"
    exit 1
}

[[ "$(hostname)" == "PinCabOs" ]] || {
    echo "NOGO [HOST] $(hostname)"
    exit 1
}

[[ -d "$GITDIR" ]] || {
    echo "NOGO [GITDIR] $GITDIR absent"
    exit 1
}

REMOTE="$(pgit remote get-url origin)"
BRANCH="$(pgit symbolic-ref --short HEAD)"

echo "Hostname : $(hostname)"
echo "Lance par: ${SUDO_USER:-root}"
echo "Branch   : $BRANCH"
echo "Remote   : $REMOTE"
echo "Mode     : $MODE"

[[ "$REMOTE" == "$REMOTE_OK" ]] || {
    echo "NOGO [REMOTE]"
    exit 1
}

[[ "$BRANCH" == "main" ]] || {
    echo "NOGO [BRANCH]"
    exit 1
}

echo "GO [OK] Cible valide."

echo
echo "=== 2. FETCH GITHUB ==="

pgit fetch origin \
    '+refs/heads/main:refs/remotes/origin/main'

BASE="$(pgit rev-parse refs/remotes/origin/main)"

echo "GitHub main : $BASE"
echo "GitHub      : $(pgit log -1 --format='%h %s' "$BASE")"

#
# IMPORTANT :
# HEAD/index seulement.
# Jamais de checkout/reset --hard.
# Le filesystem du cabinet reste la source.
#
pgit reset --mixed "$BASE" >/dev/null

echo "GO [OK] Index propre."
echo "GO [OK] Filesystem cabinet intact."

echo
echo "=== 3. .GITIGNORE DISASTER RECOVERY ==="

#
# Si le .gitignore local n'existe pas, on prend celui de GitHub.
#
if [[ ! -f /.gitignore ]]; then
    pgit show "$BASE:.gitignore" > /.gitignore
fi

#
# Le SOURCE du builder doit être conservé.
#
sed -i '\|^/opt/pincabos/build/$|d' /.gitignore

add_ignore() {
    local RULE="$1"

    if ! grep -Fqx "$RULE" /.gitignore; then
        printf '%s\n' "$RULE" >> /.gitignore
    fi
}

# Git lui-même
add_ignore "/opt/pincabos/.git-rootfs/"

# Tables / contenu utilisateur
add_ignore "/home/pinball/Tables/"
add_ignore "/home/pinball/tables/"
add_ignore "/home/pinball/Imports/"
add_ignore "/home/pinball/Exports/"
add_ignore "/home/pinball/Downloads/"

# Python
add_ignore "**/.venv/"
add_ignore "**/venv/"
add_ignore "**/__pycache__/"
add_ignore "**/*.pyc"
add_ignore "**/*.pyo"

# Node
add_ignore "**/node_modules/"

# Backups
add_ignore "**/backup/"
add_ignore "**/backups/"
add_ignore "**/*-backup/"
add_ignore "**/*-backups/"
add_ignore "**/*.bak"
add_ignore "**/*.bak.*"
add_ignore "**/*.bak-*"
add_ignore "**/*.before-*"
add_ignore "**/*before-*"
add_ignore "**/*.orig"
add_ignore "**/*.old"
add_ignore "**/*.bundle"

add_ignore "/home/pinball/vpinfe.pre-*/"
add_ignore "/opt/pinball/"
add_ignore "/home/pinball/*.avant-opt*"
add_ignore "/home/pinball/pincabos-*-20*/"
add_ignore "/root/pincabos-final-safety-*/"
add_ignore "/root/pincabos-merge-preview-*/"
add_ignore "/root/pincabos-merge-preview-*.txt"

# Temp/cache
add_ignore "/opt/pincabos/tmp/"
add_ignore "/opt/pincabos/cache/"
add_ignore "/opt/pincabos/build/output/"
add_ignore "/opt/pincabos/build/known-good/"
add_ignore "/opt/pincabos/build/legacy-package-builder/pilot-*/"

# Logs
add_ignore "**/*.log"
add_ignore "**/logs/"

# Sessions / historiques
add_ignore "/home/*/.bash_history"
add_ignore "/root/.bash_history"
add_ignore "/home/*/.Xauthority"
add_ignore "/var/lib/lightdm/"
add_ignore "/home/*/.config/pulse/cookie"
add_ignore "/home/*/.config/gh/"
add_ignore "/root/.config/gh/"
add_ignore "/root/.config/vpinfe/"
add_ignore "/home/*/.local/share/Trash/"
add_ignore "/home/pinball/.local/state/wireplumber/"
add_ignore "**/*.lock"

# Secrets
add_ignore "/root/.ssh/"
add_ignore "/home/*/.ssh/"
add_ignore "/etc/ssh/ssh_host_*_key"
add_ignore "/etc/ssh/ssh_host_*_key.pub"
add_ignore "/etc/shadow"
add_ignore "/etc/shadow-"
add_ignore "/etc/gshadow"
add_ignore "/etc/gshadow-"
add_ignore "/etc/ssl/private/"
add_ignore "/etc/NetworkManager/system-connections/"
add_ignore "/opt/pincabos/config/admin-password.txt"
add_ignore "/opt/pincabos/config/webapp-secret.key"

# Linux regenerable
add_ignore "/etc/machine-id"
add_ignore "/etc/ld.so.cache"
add_ignore "/var/lib/NetworkManager/"
add_ignore "/var/lib/systemd/random-seed"
add_ignore "/var/lib/systemd/timers/"
add_ignore "/var/lib/logrotate/status"
add_ignore "/var/lib/plymouth/"
add_ignore "/var/lib/unattended-upgrades/"
add_ignore "/var/lib/ubuntu-advantage/"
add_ignore "/var/lib/dkms/"

# Runtime PinCabOS recreable
add_ignore "/var/lib/pincabos/batch-live-import/"
add_ignore "/var/lib/pincabos/batch-live/"
add_ignore "/var/lib/pincabos/media-recorder/history/"
add_ignore "/var/lib/pincabos/media-recorder/logs/"
add_ignore "/var/lib/pincabos/media-recorder/control.json"
add_ignore "/var/lib/pincabos/native-b2s-prelaunch-backups/"
add_ignore "/var/lib/pincabos/table-test/runs/"
add_ignore "/var/lib/pincabos/updates/"
add_ignore "/var/lib/pincabos-link/"

chmod 0644 /.gitignore
chown root:root /.gitignore

echo "GO [OK] Exclusions chargees."

echo
echo "=== 4. NETTOYAGE DU VIEUX BRUIT GITHUB ==="

#
# Retire de Git les fichiers déjà suivis qui sont maintenant ignorés.
# NE LES EFFACE PAS DU CABINET.
#
pgit ls-files \
    -ci \
    --exclude-standard \
    -z |
xargs -0 -r -n 200 \
    git \
    --git-dir="$GITDIR" \
    --work-tree=/ \
    rm -r -q \
    --cached \
    --ignore-unmatch --

echo "GO [OK] Bruit retire de l'index."
echo "GO [OK] Aucun fichier local supprime."

echo
echo "=== 5. CABINET -> INDEX GIT ==="

#
# Zones reconstructibles PinCabOS.
#
# Les fichiers GitHub purs DEV/.github/README restent intacts.
#
pgit add -A -- \
    .gitignore \
    etc \
    home/pinball \
    opt/pincabos \
    root \
    usr/local \
    var/lib/pincabos \
    bin \
    lib \
    lib64 \
    sbin

echo "GO [OK] RootFS utile indexe."

echo
echo "=== 6. FICHIERS ACTIFS A POUSSER ==="

ACTIVE="$(mktemp)"
BIG="$(mktemp)"

trap 'rm -f "$ACTIVE" "$BIG"' EXIT

#
# Seulement ajoutés/modifiés.
# Les suppressions d'anciens logs/backups sont légitimes.
#
pgit diff \
    --cached \
    --name-only \
    --diff-filter=ACMRT \
    > "$ACTIVE"

echo "Ajoutes/modifies : $(wc -l < "$ACTIVE")"

echo
echo "=== 7. GARDE ARTIFACTS ==="

BAD="$(
    grep -E \
    '(^|/)(\.venv|venv|__pycache__|node_modules)(/|$)|(^|/)(backup|backups)(/|$)|(^|/)[^/]*-backups?(/|$)|\.bak($|[.-])|\.bundle$|\.log$|(^|/)\.bash_history$|(^|/)\.Xauthority$|(^|/)\.config/gh/|pincabos-final-safety-|vpinfe\.pre-|pincabos-merge-preview-' \
    "$ACTIVE" \
    || true
)"

if [[ -n "$BAD" ]]; then
    echo "NOGO [ARTIFACT]"
    printf '%s\n' "$BAD"
    exit 1
fi

echo "GO [OK] Aucun backup/venv/log."

echo
echo "=== 8. GARDE SECRETS ==="

BAD="$(
    grep -E \
    '(^|/)\.ssh/|^etc/shadow|^etc/gshadow|^etc/ssl/private/|^etc/NetworkManager/system-connections/|^var/lib/NetworkManager/|webapp-secret\.key$|admin-password\.txt$|^etc/machine-id$|^var/lib/pincabos-link/' \
    "$ACTIVE" \
    || true
)"

if [[ -n "$BAD" ]]; then
    echo "NOGO [SECRET PATH]"
    printf '%s\n' "$BAD"
    exit 1
fi

FOUND_SECRET=0

while IFS= read -r FILE; do

    [[ -n "$FILE" ]] || continue
    [[ -f "/$FILE" ]] || continue

    if grep -Iq . "/$FILE"; then
        if grep -Eq \
            'github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' \
            "/$FILE"
        then
            echo "NOGO [SECRET CONTENT] /$FILE"
            FOUND_SECRET=1
        fi
    fi

done < "$ACTIVE"

(( FOUND_SECRET == 0 )) || exit 1

echo "GO [OK] Aucun token/private key."

echo
echo "=== 9. GARDE GIT IMBRIQUE ==="

GITLINKS="$(
    pgit ls-files -s |
    awk '$1 == "160000" {print $4}'
)"

if [[ -n "$GITLINKS" ]]; then
    echo "NOGO [GITLINK]"
    printf '%s\n' "$GITLINKS"
    exit 1
fi

echo "GO [OK] Aucun repo imbrique."

echo
echo "=== 10. GARDE 95 MiB ==="

while IFS= read -r FILE; do

    [[ -n "$FILE" ]] || continue

    SIZE="$(pgit cat-file -s ":$FILE" 2>/dev/null || echo 0)"

    if (( SIZE > 99614720 )); then
        printf '%s | %s octets\n' "$FILE" "$SIZE" >> "$BIG"
    fi

done < "$ACTIVE"

if [[ -s "$BIG" ]]; then
    echo "NOGO [>95 MiB]"
    cat "$BIG"
    exit 1
fi

echo "GO [OK] Tailles valides."

echo
echo "=== 11. VERSION ==="

VERSION="unknown"

if [[ -f /opt/pincabos/version.json ]]; then
    VERSION="$(
        python3 - <<'PY' 2>/dev/null || true
import json
p="/opt/pincabos/version.json"
try:
    d=json.load(open(p))
    for k in ("version","display_version","release","current"):
        if d.get(k):
            print(d[k])
            break
except Exception:
    pass
PY
    )"
fi

[[ -n "$VERSION" ]] || VERSION="unknown"

echo "Version cabinet : $VERSION"

echo
echo "=== 12. RESUME ==="

ADDED="$(pgit diff --cached --name-only --diff-filter=A | wc -l)"
MODIFIED="$(pgit diff --cached --name-only --diff-filter=M | wc -l)"
REMOVED="$(pgit diff --cached --name-only --diff-filter=D | wc -l)"
TOTAL="$(pgit diff --cached --name-only | wc -l)"

echo "Ajoutes          : $ADDED"
echo "Modifies         : $MODIFIED"
echo "Retires de GitHub: $REMOVED"
echo "Total            : $TOTAL"

if pgit diff --cached --quiet; then
    echo
    echo "================================================================"
    echo " GO [OK] GITHUB DEJA A JOUR"
    echo "================================================================"
    exit 0
fi

if [[ "$MODE" == "audit" ]]; then
    echo
    echo "================================================================"
    echo " AUDIT TERMINE - AUCUN COMMIT / PUSH"
    echo "================================================================"
    pgit diff --cached --stat
    exit 0
fi

echo
echo "=== 13. ANTI-COLLISION ==="

pgit fetch origin \
    '+refs/heads/main:refs/remotes/origin/main'

NOW="$(pgit rev-parse refs/remotes/origin/main)"

if [[ "$NOW" != "$BASE" ]]; then
    echo "NOGO [COLLISION]"
    echo "Avant : $BASE"
    echo "Maintenant : $NOW"
    exit 1
fi

echo "GO [OK] Main stable."

echo
echo "=== 14. COMMIT ==="

pgit commit \
    -m "sync(cab): PinCabOS ${VERSION} disaster-recovery ${STAMP}"

CAB_SHA="$(pgit rev-parse HEAD)"

echo "Commit : $CAB_SHA"

echo
echo "=== 15. PUSH ==="

pgit push origin HEAD:refs/heads/main

echo
echo "=== 16. VALIDATION ==="

pgit fetch origin \
    '+refs/heads/main:refs/remotes/origin/main'

FINAL="$(pgit rev-parse refs/remotes/origin/main)"

[[ "$CAB_SHA" == "$FINAL" ]] || {
    echo "NOGO [SHA]"
    echo "Local  : $CAB_SHA"
    echo "GitHub : $FINAL"
    exit 1
}

echo
echo "================================================================"
echo " GO [OK] GITHUB = MIROIR DU CABINET"
echo "================================================================"
echo "Version : $VERSION"
echo "Commit  : $FINAL"
echo "Ajoutes : $ADDED"
echo "Modifies: $MODIFIED"
echo "Retires : $REMOVED"
echo "================================================================"
