# PinCabOS Alpha 4.54 → 4.68 — Installer sur un cabinet NVIDIA

Cette série lève trois défauts qui **empêchaient purement et simplement l'installation** de PinCabOS depuis l'ISO, dont deux invisibles jusqu'ici. Elle allège l'image, corrige le démarrage et donne enfin un nom propre à chaque cabinet.

Si vous avez déjà essayé d'installer PinCabOS sur une machine NVIDIA et abandonné : c'est cette version qu'il faut réessayer.

---

## L'assistant d'installation démarre enfin sur NVIDIA

**Le symptôme.** L'ISO démarrait, puis l'écran restait sur un message d'erreur :

```
(EE) failed to create screen resources
pincabos-gui-kiosk.service: restart counter is at 3
```

**La cause.** Le média imposait à Xorg le pilote `modesetting`, qui ne sait pas piloter une carte NVIDIA propriétaire — et ce réglage écrasait celui que le pilote NVIDIA installe lui-même. Le bon pilote était présent dans l'image depuis toujours ; notre propre configuration l'écartait.

**Aujourd'hui.** Xorg choisit seul. NVIDIA, Intel, AMD et machines virtuelles fonctionnent chacune avec le pilote qui leur convient.

## L'installation va jusqu'au bout

Juste après, l'installation s'arrêtait à la préparation :

```
sha256sum: /opt/pincabos/build/…/pincabos-plymouth-theme-overlay.tar.zst:
           No such file or directory
```

Le fichier de vérification gravé sur le média désignait un chemin de la machine qui avait fabriqué l'ISO — inexistant sur votre cabinet. Ce défaut-là touchait **tous** les cabinets, quelle que soit la carte graphique.

## Chaque cabinet porte son propre nom

Un cabinet installé s'appelait `pincabos-live` — le nom du média d'installation, hérité tel quel. Deux cabinets sur le même réseau portaient donc le même nom.

Désormais chacun prend le sien, dérivé de sa carte réseau : `pincabos-a865ed`. Si vous avez déjà baptisé votre machine, votre nom est conservé.

> Les cabinets **déjà installés** gardent `pincabos-live`. Le rattrapage viendra dans une prochaine version.

## Une ISO plus légère et plus rapide

| | avant | maintenant |
|---|---|---|
| taille de l'ISO | 3,0 Go | **2,6 Go** |
| noyaux embarqués | 5 | **1** |
| durée de fabrication | ~46 min | **~15 min** |

Le système ne trimballe plus quatre noyaux qui ne démarreront jamais, ni la documentation, les pages de manuel et les 182 langues dont l'installateur n'en propose que cinq. Les visuels de démarrage passent en palette de 256 couleurs : **41 Mo → 17 Mo**, sans différence visible à l'œil, ce qui raccourcit d'autant l'attente avant l'apparition du logo.

---

## Démarrage

**Le fronton animé fonctionne au menu.** Un service chargé de l'animation du backglass ne démarrait **jamais**, sur aucun cabinet, à cause d'une boucle de dépendances que systemd cassait en silence.

**Le raccord entre le logo de démarrage et le frontend est invisible.** L'image affichée pendant le chargement restait à l'écran jusqu'à ce que VPinFE ait vraiment peint, puis s'effaçait en fondu. Auparavant l'image apparaissait à l'envers sur le playfield, puis — après une première correction — laissait un écran noir de plusieurs secondes.

**Le logo du média d'installation s'affiche en paysage.** Un média ne connaît pas la disposition de vos écrans : il affiche désormais un visuel qui se lit sur n'importe lequel.

**Un service de vérification du média ne tourne plus sur le système installé.** Il échouait à chaque démarrage en cherchant un ISO absent.

---

## Installation

**Le message de confirmation dit la vérité.** À la dernière étape, « TOUTES LES DONNÉES SERONT EFFACÉES » s'affichait même quand vous aviez choisi d'installer dans l'espace libre — un mode qui ne touche à aucune partition. *(Merci à Patrick pour la remontée.)*

**Les tables de démonstration s'effacent toutes seules.** Le réglage livré était « toujours affichées » alors que le comportement documenté et recommandé est « automatique » : présentes tant que votre bibliothèque est vide, retirées dès votre premier import. Les trois choix restent offerts.

---

## Sous le capot

**VPX et le frontend utilisent enfin la même bibliothèque DOF.** Ils tournaient sur deux versions différentes séparées de trois mois, selon que vous étiez en jeu ou dans le menu. L'écart était invisible et, jusqu'ici, impossible à rattraper à distance.

**Les mises à jour peuvent désormais atteindre ces bibliothèques.** Elles étaient hors du périmètre : un cabinet gardait pour toujours celles de son ISO d'origine. *(Le périmètre est annoncé dans cette version ; les fichiers suivront à la prochaine, le temps que tout le parc en prenne connaissance.)*

**Les dossiers de VPX et VPinFE portent leur nom.** `vpx` et `vpinfe` au lieu d'un nom contenant le numéro de version, avec conservation des deux versions précédentes (`vpx.bak`, `vpx.bak2`) pour revenir en arrière. Au passage, la version de VPinFE remontée au serveur PinCabOS était toujours vide : elle est maintenant correcte.

---

## Pour les testeurs

Cette ISO est celle à utiliser pour un cabinet **NVIDIA** : c'était jusqu'ici impossible.

Après installation, deux points connus :

- le logo de démarrage n'apparaît que sur un écran pendant l'installation — le média ne connaît pas encore votre disposition ; le cabinet installé, lui, l'affiche sur les trois ;
- le premier démarrage après installation est plus long que les suivants (environ 1 min 20 contre 45 s) : le système génère ses clés et sa configuration.
