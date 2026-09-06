pco_section "DOF"

# PINCABOS_DOF_GLOBALCONFIG_V1 : un cabinet.xml qui declare des controleurs n'est lu
# par libdof que si GlobalConfig_B2SServer.xml le designe. Sans lui : AutoConfig,
# et les rubans (Teensy, Wemos) restent eteints (cab de Yann, 06/09/2026).
dof_vus=0
for d in /home/pinball/.local/share/VPinballX/*/directoutputconfig /home/pinball/.pincabos/vpx/directoutputconfig; do
  [ -f "$d/cabinet.xml" ] || continue
  grep -q '</[A-Za-z]*Controller>' "$d/cabinet.xml" 2>/dev/null || continue
  dof_vus=$((dof_vus + 1))
  if [ -f "$d/GlobalConfig_B2SServer.xml" ] && grep -q 'cabinet\.xml' "$d/GlobalConfig_B2SServer.xml"; then
    pco_go "DOF GlobalConfig" "$d"
  elif pco_repairing && [ -x /opt/pincabos/tools/pincabos-dof ]; then
    if /opt/pincabos/tools/pincabos-dof global-config >/tmp/pincabos-dof-globalconfig.log 2>&1; then
      pco_go "DOF GlobalConfig" "pose dans $d"
    else
      pco_fail "DOF GlobalConfig" "pose impossible dans $d (voir /tmp/pincabos-dof-globalconfig.log)"
    fi
  else
    pco_warn "DOF GlobalConfig" "absent dans $d : DOF passe en AutoConfig et ignore les controleurs declares"
  fi
done
if [ "$dof_vus" -eq 0 ]; then
  pco_go "DOF cabinet.xml" "aucun controleur declare (AutoConfig)"
fi
