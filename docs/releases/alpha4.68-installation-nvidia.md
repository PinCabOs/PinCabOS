# PinCabOS — Alpha 4.54 → 4.68

Quinze versions depuis la 4.53. Trois d'entre elles lèvent des défauts qui **empêchaient l'installation depuis l'ISO** — dont deux sur toute machine NVIDIA.

---

## Corrections

- **4.63 — L'assistant d'installation ne démarrait pas sur les cartes NVIDIA.** L'écran restait sur `failed to create screen resources`. Le média imposait à Xorg un pilote incompatible avec les cartes NVIDIA propriétaires, et ce réglage écrasait celui du pilote lui-même. Xorg choisit désormais seul.
- **4.64 — L'installation s'arrêtait à la préparation.** Le fichier de vérification gravé sur le média désignait un chemin de la machine qui avait fabriqué l'ISO. Touchait **tous** les cabinets, quelle que soit la carte graphique.
- **4.67 — Tous les cabinets installés s'appelaient `pincabos-live`.** Le nom du média était hérité tel quel : deux cabinets sur le même réseau portaient le même nom.
- **4.57 — Le fronton animé ne démarrait jamais.** Sur aucun cabinet, depuis toujours : une boucle de dépendances que systemd cassait en silence.
- **4.57 — L'image de démarrage s'affichait à l'envers sur le playfield** juste avant le frontend.
- **4.57 — Un service de vérification du média tournait sur le système installé** et échouait à chaque démarrage en cherchant un ISO absent.
- **4.55 — Le message « TOUTES LES DONNÉES SERONT EFFACÉES » s'affichait à tort.** Y compris quand vous choisissiez d'installer dans l'espace libre, un mode qui ne touche à aucune partition. *(Remonté par Patrick.)*
- **4.66 — Les tables de démonstration ne s'effaçaient jamais.** Le réglage livré était « toujours affichées » au lieu d'« automatique » : elles restaient après votre premier import.
- **4.65 — Le logo du média d'installation s'affichait tourné.** Un média ne connaît pas la disposition de vos écrans ; il affiche maintenant un visuel qui se lit sur n'importe lequel.
- **4.60 — VPX et le frontend utilisaient deux versions différentes de la bibliothèque DOF**, séparées de trois mois, selon que vous étiez en jeu ou dans le menu.
- **4.54 — La version de VPinFE remontée au serveur PinCabOS était toujours vide.**
- **4.62 — Une ISO ne pouvait plus être fabriquée** par-dessus une installation antérieure à la 4.54.

## Nouveautés

- **4.68 — Le raccord entre le logo de démarrage et le frontend est invisible.** L'image reste à l'écran jusqu'à ce que le frontend ait vraiment peint, puis s'efface en fondu. Avant : plusieurs secondes d'écran noir.
- **4.67 — Chaque cabinet porte son propre nom**, dérivé de sa carte réseau : `pincabos-a865ed`. Un nom que vous avez choisi vous-même est conservé.
- **4.54 — Retour arrière possible sur VPX.** Les dossiers portent leur nom (`vpx`, `vpinfe`) et les deux versions précédentes sont conservées (`vpx.bak`, `vpx.bak2`).
- **4.61 — Les mises à jour peuvent désormais atteindre les bibliothèques VPX/DOF.** Elles en étaient exclues : un cabinet gardait pour toujours celles de son ISO. *(Périmètre annoncé dans cette version, fichiers à la suivante.)*

## ISO plus légère et plus rapide

- **4.58 — Un seul noyau au lieu de cinq**, et plus de documentation, de pages de manuel ni des 182 langues dont l'installateur n'en propose que cinq.
- **4.59 — Visuels de démarrage en palette 256 couleurs** : 41 Mo → 17 Mo, sans différence visible. L'attente avant l'apparition du logo raccourcit d'autant.

| | avant | maintenant |
|---|---|---|
| taille de l'ISO | 3,0 Go | **2,6 Go** |
| noyaux embarqués | 5 | **1** |
| durée de fabrication | ~46 min | **~15 min** |

---

## Limites connues

- Les cabinets **déjà installés** gardent le nom `pincabos-live` : rien ne rejoue le renommage après coup. Rattrapage prévu.
- Pendant l'installation, le logo n'apparaît que sur **un** écran — le média ne connaît pas encore votre disposition. Le cabinet installé, lui, l'affiche sur les trois.
- Le **premier** démarrage après installation dure environ 1 min 20 contre 45 s ensuite : le système génère ses clés et sa configuration.
