# Recette d'image PinCabOS — composants tiers

Le rootfs de l'ISO ne porte plus les bundles VPX et VPinFE copiés d'un cab :
ils viennent des releases officielles, **version épinglée** et **somme SHA-256
vérifiée** (`components.json`). libdof patché (backboard, Dude's Cab) vient du
dépôt (`opt/pincabos/overlays/libdof-canonical`) et remplace la copie vendored
des deux bundles, exactement comme sur les cabs. Les modèles du compte du joueur
(vpinfe.ini, DOF, tableau de bord…) suivent via `pincabos_home_templates.py`.

Ce dossier n'est **pas livré** aux cabs (hors périmètre OTA) : c'est l'outillage
de construction.

## Usage

```bash
# rootfs d'une image en cours de construction (ex. banc WSL : /root/pco-master)
python3 image/fetch_components.py apply --rootfs /root/pco-master
python3 image/fetch_components.py apply --rootfs /root/pco-master --dry-run
python3 image/fetch_components.py apply --rootfs /root/pco-master --only vpinfe
python3 image/fetch_components.py verify --cache /root/image-cache   # sommes des archives
python3 image/fetch_components.py list
```

Le cache (`--cache`, défaut `/root/image-cache` ou `PCO_IMAGE_CACHE`) garde les
archives ; une archive présente et vérifiée n'est pas retéléchargée.

## Ce que fait `apply`

| Composant | Source | Posé dans le rootfs |
|-----------|--------|---------------------|
| `vpx` | release GitHub vpinball (`VPinballX_BGFX-…-linux-x64-Release.tar.gz`) | `opt/pinball/VPinballX_BGFX-<version>-linux-x64/` + lien `opt/pinball/vpx` (et `home/pinball/vpx` de compatibilité) |
| `vpinfe` | release GitHub superhac/vpinfe, variante **slim** (`vpinfe-v…-linux-x64-slim.zip`, sans le Chromium embarqué de 633 Mo : les fenêtres VPinFE tournent dans le Google Chrome du système) | `opt/pinball/vpinfe/` (et lien `home/pinball/vpinfe` de compatibilité) |
| `libdof` | `opt/pincabos/overlays/libdof-canonical/libdof.so.0.4.7` (md5 contrôlé) | copie dans `plugins/dof` de VPX ; liens `vpinfe/_internal/libdof.so*` vers l'overlay VPinFE |
| modèles | `opt/pincabos/templates/home` | ce qui manque dans `home/pinball` (jamais d'écrasement) |

Toute somme inattendue arrête le composant (`NOGO`) : une release amont
republiée sous le même nom se voit tout de suite.

## Mettre à jour un composant

1. Relever l'URL de l'asset dans la release amont et sa somme :
   `curl -sL <url> | sha256sum`.
2. Mettre à jour `url`, `archive`, `sha256`, `install`, `links` (VPX : le nom du
   dossier porte la version), et les `copies` de `libdof`.
3. `python3 -m unittest opt/pincabos/tests/test_image_recette.py`.
4. Construire une ISO de banc et jouer une installation neuve en VM.

## Reste à faire (recette complète)

- Liste des paquets apt épinglée et construction du rootfs depuis zéro
  (aujourd'hui : rootfs hérité d'un cab, remis à niveau à la main).
- Overlay `/etc` minimal (lightdm, X11, netplan live, sudoers).
- Banc QEMU deux têtes versionné et action CI qui joue une installation neuve.
