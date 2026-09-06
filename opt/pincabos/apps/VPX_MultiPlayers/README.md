# VPX MultiPlayers — LAB

Ce composant fournit le parcours local testable du multijoueur PinCabOS sans
utiliser VPinFE et sans écrire dans l'installation VPX privée.

## Limite actuelle

Cette étape valide l'orchestration, le code de room, l'identité du cabinet,
les états `PREPARE / READY / START / STOP` et le lancement isolé. Elle ne
prétend pas encore synchroniser la physique VPX entre deux cabinets. Le
transport cab-à-cab, les snapshots et le transfert d'autorité restent un POC
ultérieur.

## Arborescence runtime

Tout ce qui appartient au mode LAB demeure sous :

```text
/opt/pincabos/apps/VPX_MultiPlayers/
├── engine/          copie complète du runtime VPX dédiée au LAB
├── config/          configuration et PrefPath dédiés
├── data/            XDG_DATA_HOME dédié
├── cache/           XDG_CACHE_HOME dédié
├── home/            HOME dédié
├── tables-test/     tables de test seulement
├── sessions/        état public local, sans jeton
└── logs/            journaux du composant
```

Le lanceur force aussi `-PrefPath .../config/vpx`. Le binaire, le `HOME`, les
répertoires XDG et les tables sont donc tous isolés de la partie privée.

## Installation sur un cabinet de test

Le script refuse d'écraser un moteur déjà copié. Il copie la totalité du
dossier source en lecture seule, compare le SHA-256 du binaire avant/après,
puis active seulement le nouvel agent.

```bash
sudo bash /opt/pincabos/apps/VPX_MultiPlayers/install.sh \
  /opt/pinball/VPinballX_BGFX-10.8.1-5436-af26b2d93-linux-x64
```

Après installation :

```bash
sudo /opt/pincabos/apps/VPX_MultiPlayers/bin/pincabos-multiplayer-agent doctor
sudo /opt/pincabos/apps/VPX_MultiPlayers/bin/pincabos-multiplayer-agent status
```

La page **PinCabOS Link → VPX MultiPlayers — LAB** donne ensuite accès à :

- créer/activer la partie depuis la room Lobby active;
- rejoindre avec le code de six caractères;
- vérifier la table de test et annoncer `PRÊT`;
- démarrer/arrêter si ce cabinet appartient au capitaine;
- lancer uniquement une table située sous `tables-test/`.

## Retour arrière

`uninstall.sh` arrête et retire le service et la règle sudo dédiée. Le moteur,
les tables et les journaux isolés sont volontairement conservés pour permettre
l'audit ou une réinstallation. Le VPX privé et VPinFE ne sont jamais touchés.
