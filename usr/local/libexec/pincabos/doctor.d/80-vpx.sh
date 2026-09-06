pco_section "VPX / PINMAME"

. /opt/pincabos/tools/pincabos-paths.sh

vpx_launcher=""
for candidate in /opt/pincabos/bin/vpx.sh /opt/pincabos/scripts/VPXlauncher.sh; do
  if [ -x "$candidate" ]; then
    vpx_launcher="$candidate"
    break
  fi
done

if [ -n "$vpx_launcher" ]; then
  pco_go "VPX launcher" "$vpx_launcher"
else
  pco_fail "VPX launcher" "aucun launcher exécutable"
fi

vpx_bin=""
for candidate in \
  "$PCO_VPX_BIN" \
  "$PCO_RUNTIMES"/VPinballX_BGFX-*/VPinballX_BGFX \
  "$PCO_HOME"/VPinballX_BGFX-*/VPinballX_BGFX \
  /opt/pincabos/apps/vpinball/*/VPinballX_BGFX \
  /opt/pincabos/apps/vpinball/*/VPinballX
 do
  for resolved in $candidate; do
    if [ -x "$resolved" ]; then
      vpx_bin="$resolved"
      break 2
    fi
  done
 done

if [ -n "$vpx_bin" ]; then
  pco_go "VPX exécutable" "$vpx_bin"

  missing_libs="$(ldd "$vpx_bin" 2>/dev/null | grep 'not found' || true)"
  if [ -z "$missing_libs" ]; then
    pco_go "VPX bibliothèques" "aucune bibliothèque manquante"
  else
    pco_fail "VPX bibliothèques" "$(echo "$missing_libs" | tr '\n' ' ')"
  fi
else
  pco_fail "VPX exécutable" "VPinballX_BGFX introuvable"
fi

ini=""
for candidate in \
  /home/pinball/.vpinball/VPinballX.ini \
  /home/pinball/.local/share/VPinballX/10.8/VPinballX.ini
 do
  if [ -f "$candidate" ]; then
    ini="$candidate"
    break
  fi
 done

if [ -n "$ini" ]; then
  pco_go "VPX INI" "$ini"
else
  pco_warn "VPX INI" "aucun fichier INI attendu"
fi

pinmame="$(find "$PCO_RUNTIMES" "$PCO_HOME" /opt/pincabos -xdev -type f \
  \( -name 'libpinmame.so*' -o -name 'pinmame' \) \
  -print -quit 2>/dev/null || true)"
if [ -n "$pinmame" ]; then
  pco_go "PinMAME" "$pinmame"
else
  pco_warn "PinMAME" "runtime non détecté"
fi
