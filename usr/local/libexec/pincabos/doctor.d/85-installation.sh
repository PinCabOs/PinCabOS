pco_section "INSTALLATION"

# PINCABOS_DOCTOR_PREMIER_DEMARRAGE_V1
# Ce que l'assistant a promis doit avoir atteint le systeme qui tourne. Chaque
# controle ici correspond a une soiree perdue par un testeur le 09/09/2026 :
# l'echec existait, il etait journalise, et rien ne le remontait.

. /opt/pincabos/tools/pincabos-paths.sh 2>/dev/null || true
CFG=/opt/pincabos/config
FLAGS=/opt/pincabos/flags

# --- 1. les rejeux du premier demarrage ont-ils abouti ? -------------------
# Ces drapeaux sont CONSERVES tant que l'application echoue : leur presence
# apres plusieurs demarrages veut dire que le rejeu ne passe pas.
for couple in "inputs-installer.pending|mappage des boutons|Map Commander" \
              "dmd-installer.pending|DMD materiel|la page DMD"; do
  drapeau=${couple%%|*}; reste=${couple#*|}; quoi=${reste%%|*}; ou=${reste##*|}
  if [ -f "$FLAGS/$drapeau" ]; then
    pose=$(date -r "$FLAGS/$drapeau" '+%d/%m %H:%M' 2>/dev/null || echo "?")
    demarrages=$(journalctl --list-boots --no-pager 2>/dev/null | wc -l)
    if [ "${demarrages:-0}" -gt 2 ]; then
      pco_fail "$quoi" "choisi a l'installation ($pose), toujours pas applique apres $demarrages demarrages — refaites-le dans $ou"
    else
      pco_warn "$quoi" "choisi a l'installation ($pose), sera applique au prochain demarrage"
    fi
  else
    pco_go "$quoi" "applique (aucun rejeu en attente)"
  fi
done

# --- 2. le DMD materiel est-il vraiment vu ? -------------------------------
# Flo, 09/09/2026 : ZeDMD Wi-Fi configure, adresse correcte, appareil joignable
# au ping — et VPinFE journalisait « No displays found by libdmdutil » toutes
# les dix secondes depuis le premier demarrage, sans que rien ne le dise.
mode=$(python3 - "$CFG/zedmd.json" <<'PY' 2>/dev/null
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("mode", "off"))
except Exception:
    print("off")
PY
)
if [ "${mode:-off}" = "off" ]; then
  pco_go "DMD materiel" "aucun declare"
else
  refus=$(journalctl -u pincabos-vpinfe -b --no-pager 2>/dev/null \
          | grep -c "No displays found by libdmdutil")
  if [ "${refus:-0}" -gt 0 ]; then
    pco_fail "DMD materiel" "$mode declare, mais VPinFE ne trouve aucun afficheur ($refus refus depuis le demarrage) — verifiez l'appareil et la page DMD"
  else
    pco_go "DMD materiel" "$mode, VPinFE l'a ouvert"
  fi
fi

# --- 3. la rotation du playfield a-t-elle ete appliquee ? ------------------
# La rotation vit dans screens.json et n'est posee que par xrandr, au boot.
voulue=$(python3 - "$CFG/screens/screens.json" <<'PY' 2>/dev/null
import json, sys
try:
    print(str(json.load(open(sys.argv[1])).get("playfield_rotation", "0")).strip() or "0")
except Exception:
    print("0")
PY
)
if [ "${voulue:-0}" = "0" ]; then
  pco_go "Rotation du playfield" "aucune demandee"
else
  attendu=normal
  case "$voulue" in 90) attendu=right ;; 180) attendu=inverted ;; 270) attendu=left ;; esac
  reel=$(pco_as_pinball xrandr --query 2>/dev/null \
         | awk '/ connected/ {for (i=1;i<=NF;i++) if ($i ~ /^(normal|left|right|inverted)$/) {print $i; exit}}')
  if [ -z "$reel" ]; then
    pco_warn "Rotation du playfield" "${voulue}° demandee, etat xrandr illisible"
  elif [ "$reel" = "$attendu" ]; then
    pco_go "Rotation du playfield" "${voulue}° appliquee ($reel)"
  else
    pco_fail "Rotation du playfield" "${voulue}° choisie a l'installation, xrandr est en « $reel » — la topologie n'a pas ete rejouee"
  fi
fi

# --- 4. les toys declares ont-ils des definitions d'effets ? ---------------
# Patrick, 09/09/2026 : ses rubans repondaient au menu mais restaient noirs en
# table. Un controleur porte un numero LedWiz ; sans directoutputconfig<N>.ini,
# DOF n'a rien a jouer dessus. Ces fichiers viennent du DOF Config Tool.
inv="$CFG/dof/hardware-inventory.json"
if [ ! -s "$inv" ]; then
  pco_go "Definitions d'effets DOF" "aucun controleur de rubans declare"
else
  numeros=$(python3 - "$inv" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    raise SystemExit(0)
for a in d.get("devices", []):
    if a.get("enabled"):
        n = a.get("ledwiz_number")
        if n:
            print(n)
PY
)
  manquants=""
  for n in $numeros; do
    trouve=0
    for d in /home/pinball/.local/share/VPinballX/*/directoutputconfig \
             /home/pinball/.pincabos/vpx/directoutputconfig; do
      [ -f "$d/directoutputconfig$n.ini" ] && trouve=1 && break
    done
    [ "$trouve" = 0 ] && manquants="$manquants $n"
  done
  if [ -n "$manquants" ]; then
    pco_fail "Definitions d'effets DOF" "LedWiz$manquants declare(s) sans directoutputconfig — ces sorties resteront noires en table. Importez votre configuration depuis la page DOF."
  elif [ -n "$numeros" ]; then
    pco_go "Definitions d'effets DOF" "LedWiz $(echo $numeros | tr '\n' ' ')couvert(s)"
  else
    pco_go "Definitions d'effets DOF" "aucun controleur actif"
  fi
fi
