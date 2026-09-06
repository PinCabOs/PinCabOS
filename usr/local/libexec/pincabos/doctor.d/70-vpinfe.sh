pco_section "VPINFE"

. /opt/pincabos/tools/pincabos-paths.sh
runtime="$PCO_VPINFE_DIR"
launcher="/opt/pincabos/tools/run-vpinfe-systemd.sh"

# PINCABOS_RUNTIMES_OPT_V1 : VPinFE vit sous /opt/pinball ; un cabinet installe
# avant est migre au demarrage, ou ici en reparation quand personne ne joue.
if [ -d "$PCO_VPINFE_DIR_HOME" ] && [ ! -L "$PCO_VPINFE_DIR_HOME" ]; then
  if pco_repairing && ! pco_partie_en_cours && [ -x /usr/local/sbin/pincabos-runtimes-opt ]; then
    if /usr/local/sbin/pincabos-runtimes-opt >/tmp/pincabos-runtimes-opt.log 2>&1; then
      pco_go "VPinFE emplacement" "migre sous $PCO_RUNTIMES"
      runtime="$PCO_RUNTIMES/vpinfe"
    else
      pco_warn "VPinFE emplacement" "migration en echec (voir /tmp/pincabos-runtimes-opt.log)"
    fi
  else
    pco_warn "VPinFE emplacement" "encore dans le compte du joueur : migration sous $PCO_RUNTIMES au prochain demarrage"
  fi
else
  pco_go "VPinFE emplacement" "$runtime"
fi

if [ -x "$runtime/vpinfe" ] && [ -d "$runtime/_internal" ]; then
  pco_go "VPinFE runtime" "exécutable + _internal présents"
else
  pco_fail "VPinFE runtime" "runtime incomplet dans $runtime"
fi

if [ -x "$launcher" ]; then
  pco_go "VPinFE launcher" "$launcher"
else
  pco_fail "VPinFE launcher" "absent ou non exécutable"
fi

old_dropin="/etc/systemd/system/pincabos-vpinfe.service.d/55-pincabos-screen-topology.conf"
if [ -e "$old_dropin" ]; then
  if pco_repairing; then
    rm -f "$old_dropin"
    systemctl daemon-reload
    pco_go "VPinFE drop-in" "ancien 55 supprimé"
  else
    pco_warn "VPinFE drop-in" "ancien 55 encore présent"
  fi
else
  pco_go "VPinFE drop-in" "aucun ancien 55"
fi

sanitizer="/usr/local/libexec/pincabos/pincabos-vpinfe-display-sanitize"
if pco_repairing && [ -x "$sanitizer" ]; then
  "$sanitizer" >/tmp/pincabos-vpinfe-sanitize.log 2>&1 || true
fi

if pco_service_exists pincabos-vpinfe.service; then
  if pco_repairing; then
    pco_enable_service pincabos-vpinfe.service || true
  fi

  if pco_service_active pincabos-vpinfe.service; then
    pco_go "VPinFE service" "actif"
  else
    pco_fail "VPinFE service" "état : $(pco_unit_state pincabos-vpinfe.service)"
  fi
else
  pco_fail "VPinFE service" "unité absente"
fi

# PINCABOS_DOCTOR_VPINFE_PORT_8001_V1
if ss -lnt 2>/dev/null | awk '{print $4}' | grep -Eq '(:|\])8001$'; then
  pco_go "VPinFE port" "8001 en écoute"
else
  pco_warn "VPinFE port" "8001 non détecté"
fi
