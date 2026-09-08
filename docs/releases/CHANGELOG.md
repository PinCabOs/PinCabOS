# PinCabOS — Journal des versions

De la première version publiée (**Alpha 2.42**, 12 août 2026) à la **4.68**.

Chaque ligne commence par la version qui l'a apportée. Les corrections décrivent le symptôme tel qu'on le voyait.

---

# Alpha 4.54 → 4.68 — Installer sur un cabinet NVIDIA

Trois défauts qui **empêchaient l'installation depuis l'ISO**, dont deux sur toute machine NVIDIA. Si vous avez déjà essayé et abandonné, c'est cette version qu'il faut réessayer.

## Corrections

- **4.63 — L'assistant d'installation ne démarrait pas sur les cartes NVIDIA.** L'écran restait sur `failed to create screen resources`. Le média imposait à Xorg un pilote incompatible avec les cartes NVIDIA propriétaires, et ce réglage écrasait celui du pilote lui-même.
- **4.64 — L'installation s'arrêtait à la préparation.** Le fichier de vérification gravé sur le média désignait un chemin de la machine qui avait fabriqué l'ISO. Touchait **tous** les cabinets.
- **4.67 — Tous les cabinets installés s'appelaient `pincabos-live`.** Le nom du média était hérité tel quel.
- **4.57 — Le fronton animé ne démarrait jamais**, sur aucun cabinet : une boucle de dépendances cassée en silence.
- **4.57 — L'image de démarrage s'affichait à l'envers sur le playfield** juste avant le frontend.
- **4.57 — Un service de vérification du média tournait sur le système installé** et échouait à chaque démarrage.
- **4.55 — Le message « TOUTES LES DONNÉES SERONT EFFACÉES » s'affichait à tort**, y compris en installation dans l'espace libre. *(Remonté par Patrick.)*
- **4.66 — Les tables de démonstration ne s'effaçaient jamais** après votre premier import.
- **4.65 — Le logo du média d'installation s'affichait tourné.**
- **4.60 — VPX et le frontend utilisaient deux versions différentes de la bibliothèque DOF**, séparées de trois mois.
- **4.54 — La version de VPinFE remontée au serveur PinCabOS était toujours vide.**
- **4.62 — Une ISO ne pouvait plus être fabriquée** par-dessus une installation antérieure à la 4.54.

## Nouveautés

- **4.68 — Le raccord entre le logo de démarrage et le frontend est invisible.** Avant : plusieurs secondes d'écran noir.
- **4.67 — Chaque cabinet porte son propre nom**, dérivé de sa carte réseau (`pincabos-a865ed`). Un nom choisi par vous est conservé.
- **4.54 — Retour arrière possible sur VPX.** Les deux versions précédentes sont conservées.
- **4.61 — Les mises à jour peuvent atteindre les bibliothèques VPX/DOF**, jusque-là hors périmètre.

## ISO plus légère

- **4.58 — Un seul noyau au lieu de cinq**, sans documentation ni pages de manuel, et 5 langues au lieu de 182.
- **4.59 — Visuels de démarrage en palette 256 couleurs** : 41 Mo → 17 Mo.

| | avant | maintenant |
|---|---|---|
| taille de l'ISO | 3,0 Go | **2,6 Go** |
| noyaux embarqués | 5 | **1** |
| durée de fabrication | ~46 min | **~15 min** |

---

# Alpha 4.30 → 4.53 — Audio, DOF, PinCab Links

## Nouveautés

- **4.53 — PinCab Links.** Partage dynamique entre 2 et 4 cabinets d'une même session Multiplayer : les cabs autorisés apparaissent comme raccourcis dans le menu.
- **4.48 — Choisir le 7.1 dans l'assistant suffit à l'obtenir.** L'entrée ligne est réaffectée en sortie au premier démarrage.
- **4.35 — Tables de démonstration avec un B2S générique** (Miss Tilt, logos Visual Pinball et PinCabOS).

## Corrections

- **4.46 — L'assistant disait l'inverse du câblage SSF.** Latéraux et arrière étaient intervertis ; la position de chaque haut-parleur est maintenant décrite.
- **4.42 — Claquements dans les enceintes à l'initialisation.** Le profil audio n'est plus rejoué s'il n'a pas changé.
- **4.31 — Le son restait coupé au premier démarrage** et après un profil rejoué.
- **4.44 — La page Audio écrasait `vpinfe.ini` sur une seule ligne.** Garde-fou d'écriture et outil de réparation ajoutés.
- **4.45 — Le mur de LED restait allumé en sortie de table.** Il s'efface, et le frontend reprend la main.
- **4.43 — La configuration DOF n'était pas trouvée** faute d'être écrite à côté de `cabinet.xml`.
- **4.32 — Écran noir au démarrage** : le verrou du hotplug bloquait le frontend.
- **4.33 — La barre de chargement du playfield restait figée.**
- **4.30 — Le doctor pouvait couper une partie en cours** ou un frontend sain.
- **4.41 — Propriété des liens VPX/VPinFE corrigée** après le déplacement sous `/opt/pinball`.
- **4.49 / 4.50 — La fabrication d'ISO pouvait se bloquer sur une question** ou sur des paquets noyau figés.

---

# Alpha 4.01 → 4.29 — Recette d'image et découpage de la WebApp

## Nouveautés

- **4.05 — Recette des composants tiers.** VPX, VPinFE et libdof sont récupérés depuis les releases amont avec une version épinglée et une somme vérifiée, au lieu d'être copiés d'une machine.
- **4.04 — Modèles du compte du joueur** posés par l'installateur et au premier démarrage.
- **4.26 — Un seul modèle d'ISO**, le modèle live : l'image *est* le système.

## Corrections

- **4.06 — VPinFE embarquait un Chromium de 633 Mo** dont le cabinet n'a pas l'usage.
- **4.09 — Deux endroits écrivaient la configuration d'écrans** et se contredisaient.
- **4.17 / 4.18 — Pages GPU et Explorer cassées** après le découpage de la WebApp.
- **4.29 — Le démarrage VPinFE de l'ISO était retiré à tort** lors du nettoyage des réglages hérités.

## Sous le capot

- **4.11 → 4.25 — Découpage de la WebApp en modules.** Le fichier principal passe de 16 743 à 4 277 lignes, en treize lots, sans changement visible.
- **4.08 — Un seul écrivain pour les fichiers INI**, avec écriture atomique.
- **4.03 — Le compte du joueur sort du dépôt** (1 336 fichiers, 640 Mo).

---

# Alpha 3.x — L'installateur graphique

## Nouveautés

- **3.66 — L'assistant graphique devient le seul chemin d'installation.** Fini l'installateur texte.
- **3.66 — Étape Écrans** : déclaration du cabinet (backglass, full DMD, topper).
- **3.68 — Étape DMD matériel** quand il n'y a pas de full DMD (ZeDMD, PIN2DMD).
- **3.71 — Étape Toys et LED** : cartes détectées, contrôleurs de rubans en matrice ou en rubans.
- **3.87 — Étape Réseau** : la configuration de la cible est posée à l'installation.
- **3.62 — Le système s'appelle PinCabOS** partout où un humain le lit — GRUB, bannières, `os-release`.
- **3.44 — L'updater s'installe d'abord, puis se relance** : une release peut changer le mécanisme de mise à jour.
- **3.09 — La maintenance hebdomadaire met aussi à jour les paquets système.**
- **3.74 — Sauvegarde des configurations (HotFiles / PCOSCFG).**

## Corrections

- **3.59 — Le frontend démarrait en 33 s.** Il n'attend plus que ce qui lui sert : 14 s mesurées.
- **3.42 — PinCabOS n'écrit plus aucune coordonnée pour le DMD** : le placement dans l'art FullDMD est laissé à VPX.
- **3.41 — Le fronton restait noir sur un cab à deux écrans** en mode logué sans full DMD.
- **3.43 — ZeDMD n'était pas appliqué** quand le menu VPinFE était impossible (détection USB automatique).
- **3.46 — Campagne de tests du 3 septembre** : repli OpenGL après un crash, split sans PinMAME, retour du B2S Original.
- **3.60 — Une seule rotation, la physique.** Les rotations se cumulaient.
- **3.62 — NetworkManager seul maître de l'interface** : les fichiers netplan tiers sont repris.
- **3.75 — Retex cab 4K** : rotation de lecture limitée à la session, mode natif de la dalle.
- **3.77 — Cadences préférées, calibrations FullDMD/DMD dérivées** de la disposition choisie.
- **3.78 — « Retirez la clé USB » s'affichait avant le clic Redémarrer**, alors que le média servait encore.
- **3.95 — Le retour de table réactivait la mauvaise fenêtre** (backglass ou DMD au lieu du playfield).
- **3.15 → 3.33 — Chat A/V du cabinet stabilisé**, ainsi que l'interface Lobby et le backglass.
- **3.55 — La fabrication d'ISO relisait une archive de 20 Go** à chaque étape.

---

# Alpha 2.x — Les fondations

## Nouveautés

- **2.59 — Chemin stable du moteur VPX** et dossier de préférences découplé : une mise à jour de VPX ne perd plus vos réglages.
- **2.77 / 2.80 — VPX se met à jour depuis l'interface**, avec retour arrière.
- **2.68 — Configurateur B2S natif.**
- **2.86 — Page DOF Commander.**
- **2.85 — Édition complète des rubans LED et des splits MX** (DudesCab).
- **2.104 — Rôle topper de bout en bout**, avec réaction au branchement à chaud.
- **2.59 — Aperçu live à la demande** sur chaque tuile du tableau de bord.
- **2.72 — Onglet unique des mises à jour**, avec badge.
- **2.73 — Bibliothèque de tables paginée.**

## Corrections

- **2.90 — Sortie de table qui plantait** : une seule bibliothèque DOF pour le menu et le jeu.
- **2.95 — Les tables sans full DMD natif** posent le DMD réel sur l'écran FullDMD s'il existe.
- **2.95 — La configuration DudesCab n'était pas écrite** : un champ omis rendait l'écriture silencieusement inopérante.
- **2.54 — Connexion SSH root désactivée par défaut** sur chaque cabinet.
- **2.71 — L'installateur ne rappelait pas de retirer le média** avant le redémarrage.
- **2.77 — Les sauvegardes temporaires partaient dans l'ISO.**

---

## Limites connues

- Les cabinets **déjà installés** gardent le nom `pincabos-live` : rien ne rejoue le renommage après coup. Rattrapage prévu.
- Pendant l'installation, le logo n'apparaît que sur **un** écran — le média ne connaît pas encore votre disposition. Le cabinet installé l'affiche sur les trois.
- Le **premier** démarrage après installation dure environ 1 min 20 contre 45 s ensuite.
