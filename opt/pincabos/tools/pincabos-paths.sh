# PinCabOS — chemins et identite machine pour les scripts shell.
# PINCABOS_PATHS_V1
#
#   . /opt/pincabos/tools/pincabos-paths.sh
#   "$PCO_VPX_BIN" -PrefPath "$PCO_VPX_PREF" …
#
# Les valeurs viennent de /opt/pincabos/tools/pincabos_paths.py (source de
# verite, surcharge possible par /opt/pincabos/config/pincabos-paths.json).
# Idempotent : un second `source` ne recalcule rien.
if [ "${PCO_PATHS_LOADED:-0}" != "1" ]; then
    if _pco_exports="$(/usr/bin/python3 /opt/pincabos/tools/pincabos_paths.py --shell 2>/dev/null)"; then
        eval "$_pco_exports"
    else
        # Python indisponible ou module absent : valeurs de secours = la realite
        # d'un cabinet livre, pour ne jamais laisser un script sans chemin.
        export PCO_USER=pinball PCO_UID=1000 PCO_GID=1000 PCO_HOME=/home/pinball
        export PCO_DISPLAY=:0 PCO_XAUTHORITY=/home/pinball/.Xauthority
        export PCO_RUNTIME_DIR=/run/user/1000 PCO_DBUS_ADDRESS=unix:path=/run/user/1000/bus
        export PCO_ROOT=/opt/pincabos PCO_CONFIG=/opt/pincabos/config
        export PCO_ALIASES_ENV=/opt/pincabos/config/display-aliases.env
        export PCO_TABLES=/home/pinball/Tables
        # PINCABOS_RUNTIMES_OPT_V1 : VPX et VPinFE sous /opt/pinball ; un cabinet
        # pas encore migre les a toujours dans le compte du joueur.
        export PCO_RUNTIMES=/opt/pinball PCO_VPX_LINK_HOME=/home/pinball/vpx PCO_VPINFE_DIR_HOME=/home/pinball/vpinfe
        export PCO_VPX_LINK=/opt/pinball/vpx PCO_VPX_BIN=/opt/pinball/vpx/VPinballX_BGFX PCO_VPX_PLUGINS=/opt/pinball/vpx/plugins
        if [ ! -x "$PCO_VPX_BIN" ] && [ -x "$PCO_VPX_LINK_HOME/VPinballX_BGFX" ]; then
            export PCO_VPX_LINK="$PCO_VPX_LINK_HOME" PCO_VPX_BIN="$PCO_VPX_LINK_HOME/VPinballX_BGFX" PCO_VPX_PLUGINS="$PCO_VPX_LINK_HOME/plugins"
        fi
        # PINCABOS_VPX_LINK_V1 : lien absent (image nue) -> le bundle le plus recent
        if [ ! -x "$PCO_VPX_BIN" ] && [ -w "$PCO_RUNTIMES" ]; then
            _pco_vpx_dir="$(ls -d "$PCO_RUNTIMES"/VPinballX_BGFX-*/ 2>/dev/null | sort -V | tail -1)"
            [ -n "$_pco_vpx_dir" ] && ln -sfn "$(basename "$_pco_vpx_dir")" "$PCO_VPX_LINK" 2>/dev/null
            unset _pco_vpx_dir
        fi
        export PCO_VPX_PREF=/home/pinball/.pincabos/vpx PCO_VPX_INI=/home/pinball/.pincabos/vpx/VPinballX.ini
        export PCO_VPX_LEGACY_PREF=/home/pinball/.local/share/VPinballX/10.8
        export PCO_VPINFE_DIR=/opt/pinball/vpinfe PCO_VPINFE_BIN=/opt/pinball/vpinfe/vpinfe PCO_VPINFE_INI=/home/pinball/.config/vpinfe/vpinfe.ini
        if [ ! -x "$PCO_VPINFE_BIN" ] && [ -x "$PCO_VPINFE_DIR_HOME/vpinfe" ]; then
            export PCO_VPINFE_DIR="$PCO_VPINFE_DIR_HOME" PCO_VPINFE_BIN="$PCO_VPINFE_DIR_HOME/vpinfe"
        fi
        export PCO_PATHS_LOADED=1
    fi
    unset _pco_exports
fi
