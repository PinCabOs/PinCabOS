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

## PinCabShare V2 — barrière NFS pilotée par le Lobby

PinCabShare V2 remplace le modèle de confiance « tout le LAN » de l'ancien
mesh. Le cabinet ne fait aucune découverte Avahi/mDNS pour décider qui peut
accéder au partage.

Le watcher lit uniquement la politique `pincabshare` renvoyée par
`GET /api/device/multiplayer/state`, donc via l'identité appareil
`PinCabOS-Device` déjà authentifiée. La politique doit :

- être en version `2`;
- viser exactement la session Lobby active du cabinet;
- confirmer que ce cabinet appartient à la session;
- contenir de 1 à 3 CAB pairs avec une IPv4 privée exacte;
- avoir une durée de vie maximale de 90 secondes;
- ne pas être expirée.

Le cabinet maintient une table nftables dédiée `inet pincabshare_v2`. Seules
les IP exactes présentes dans la politique fraîche peuvent joindre NFS sur
TCP/UDP 2049. Toute autre source est bloquée pour ce port.

La politique est **fail-closed** : absence, expiration, mismatch de session,
IP publique, perte du serveur ou arrêt manuel du multijoueur => l'ensemble des
pairs autorisés est vidé. L'état local est publié dans
`sessions/pincabshare-v2.json`.

Cette barrière ne modifie et ne lance jamais le VPX privé, le BGFX privé ou
VPinFE. Elle ne transforme pas NFS en transport Internet : les pairs
PinCabShare V2 doivent être joignables en IPv4 privée; le transport
multijoueur Internet reste un chantier distinct.

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
