# PinCabShare V2

PinCabShare V2 est le partage automatique de fichiers entre les cabinets PinCabOS présents **dans le même Lobby Multiplayer réel**.

Il n'existe **aucun partage PinCabShare permanent sur le LAN**. La simple présence sur le même réseau, Avahi/mDNS ou une ancienne session Multiplayer ne suffit jamais à ouvrir le partage.

## Vue utilisateur

Quand CAB1 et CAB10 sont tous les deux autorisés par le gate serveur :

```text
/home/pinball/PinCabShare/
├── Ultimate PinCabOS — CAB1 -> /srv/pincabshare/data
└── VMCABOS — CAB10         -> /run/pincabshare-v2/mounts/CAB10
```

Les labels viennent de `pincabos.cc` (`cabinet_name + CAB##`). Aucun dossier CAB ne doit être créé manuellement.

Quand le gate est fermé, `/home/pinball/PinCabShare` reste vide. Les données locales demeurent intactes dans :

```text
/srv/pincabshare/data
```

## Autorité serveur

Le daemon réutilise l'identité PinCabOS Link existante :

```text
/var/lib/pincabos-link/device.json
```

Il consulte :

```text
GET https://pincabos.cc/api/device/pincabshare/state
```

avec fallback de compatibilité vers :

```text
GET https://pincabos.cc/api/device/multiplayer/share-gate
```

Le gate doit confirmer simultanément :

- session Multiplayer active ;
- correspondance exacte user ↔ CAB ;
- room Lobby active ;
- présence navigateur Lobby fraîche ;
- présence CAB PinCabShare fraîche ;
- 2 à 4 CAB présents ;
- CAB local inclus dans le groupe ;
- bail court valide (maximum accepté côté client : 12 s).

## Transport

PinCabShare V2 utilise :

- **HTTPS** : autorisation et liste des CAB ;
- **Avahi/mDNS** `_pincabshare._tcp` : découverte IPv4 uniquement ;
- **NFS** : transfert CAB↔CAB.

mDNS n'est jamais une autorité. Un pair découvert n'est accepté que si :

- son `cabinet_id` figure dans le gate HTTPS ;
- son `session_hash` correspond ;
- son `gate_tag` correspond lorsqu'un `share_nonce` est fourni ;
- son IPv4 appartient au même sous-réseau IPv4 que l'interface par défaut du CAB.

## Exports NFS dynamiques

Le fichier suivant n'existe que pendant un gate ouvert et seulement pour les IPv4 des pairs effectivement découverts et autorisés :

```text
/etc/exports.d/pincabshare-v2.exports
```

Il n'y a jamais d'export `/24`, `/16`, RFC1918 global ou `*`.

Le partage utilise `all_squash` avec l'UID/GID de `pinball`, `sync` et `no_subtree_check`.

## Fail-closed

Le daemon poll toutes les 2 secondes. Le bail serveur est court. Si le serveur devient injoignable, l'état ouvert n'est conservé que jusqu'à l'expiration du dernier bail déjà reçu.

Un gate explicitement fermé provoque immédiatement :

- retrait de `/etc/exports.d/pincabshare-v2.exports` ;
- retrait de `/etc/avahi/services/pincabshare-v2.service` ;
- démontage des NFS distants ;
- retrait des symlinks CAB gérés dans `/home/pinball/PinCabShare`.

Les données de `/srv/pincabshare/data` ne sont jamais supprimées.

Avec 3 ou 4 joueurs, un CAB stale est retiré individuellement. Les autres continuent tant qu'au moins deux CAB restent autorisés par le serveur.

## Installation

Dépendances :

```text
avahi-daemon
avahi-utils
nfs-common
nfs-kernel-server
```

Installation :

```bash
sudo /opt/pincabos/apps/PinCabShare/install.sh
```

Service :

```text
pincabshare-v2.service
```

Status runtime :

```text
/run/pincabshare-v2/status.json
```

## Frontières non négociables

PinCabShare V2 ne modifie pas :

- VPX privé ;
- BGFX privé ;
- VPinFE ;
- les tables ;
- le moteur de lancement Multiplayer.

Le mode jeu Multiplayer doit rester en pause jusqu'à validation réelle CAB1↔CAB10 : gate `open`, dossiers visibles dans les deux sens, écriture bidirectionnelle et fermeture automatique quand un joueur quitte le Lobby.
