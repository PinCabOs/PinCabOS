# PinCab Links / PinCabShare V2

## Séparation utilisateur

Deux fonctions distinctes coexistent dans PinCab Explorer :

- **PinCabShare** : partage SMB historique du cabinet, conservé sur `/home/pinball/Share` ;
- **PinCab Links** : raccourcis CAB↔CAB dynamiques affichés directement dans le menu quand 2 à 4 cabinets sont autorisés dans le même Lobby Multiplayer réel.

La couche dynamique utilise toujours le runtime interne `pincabshare-v2`, mais son nom utilisateur est **PinCab Links**.

## Vue utilisateur

Dans un Lobby autorisé CAB1 + CAB10, PinCab Explorer affiche directement :

```text
PinCabShare
PinCab Links
  Ultimate PinCabOS — CAB1
  VMCABOS — CAB10
```

`PinCabShare` ouvre :

```text
/home/pinball/Share
```

Les raccourcis de `PinCab Links` proviennent de la vue dynamique :

```text
/home/pinball/PinCabShare/
├── Ultimate PinCabOS — CAB1 -> /srv/pincabshare/data
└── VMCABOS — CAB10         -> /run/pincabshare-v2/mounts/CAB10
```

Les labels viennent de `pincabos.cc` (`cabinet_name + CAB##`). Aucun dossier CAB n'est créé manuellement.

Quand le gate ferme, les raccourcis PinCab Links disparaissent. Les données locales demeurent intactes dans :

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
- membership réel du user dans la room Lobby exacte liée à la session ;
- room Lobby active ;
- bail CAB PinCab Links frais ;
- 2 à 4 CAB présents ;
- CAB local inclus dans le groupe ;
- bail court valide (maximum accepté côté client : 12 s).

La fraîcheur d'un onglet navigateur n'est pas utilisée comme autorité. Le CAB authentifié entretient lui-même son bail device en pollant le gate. Quitter la room retire le membership ; perdre le CAB ou le daemon fait expirer le bail rapidement.

## Transport PinCab Links

PinCab Links utilise :

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

Il n'y a jamais d'export `/24`, `/16`, RFC1918 global ou `*` créé par PinCab Links.

Le partage utilise `all_squash` avec l'UID/GID de `pinball`, `sync` et `no_subtree_check`.

Le SMB historique `PinCabShare` reste séparé et n'est pas utilisé comme autorité ou transport du mode CAB↔CAB dynamique.

## Fail-closed

Le daemon poll toutes les 2 secondes. Le bail serveur est court. Si le serveur devient injoignable, l'état ouvert n'est conservé que jusqu'à l'expiration du dernier bail déjà reçu.

Un gate explicitement fermé provoque immédiatement :

- retrait de `/etc/exports.d/pincabshare-v2.exports` ;
- retrait de `/etc/avahi/services/pincabshare-v2.service` ;
- démontage des NFS distants ;
- retrait des symlinks CAB gérés dans `/home/pinball/PinCabShare` ;
- disparition des raccourcis correspondants sous **PinCab Links** au prochain rendu de PinCab Explorer.

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

Patch WebApp idempotent :

```text
/opt/pincabos/apps/PinCabShare/webapp_patch.py
```

## Validation réelle CAB1 ↔ CAB10

Validé en test live :

- gate `open` des deux côtés ;
- `authorized_ids=[1,10]` ;
- découverte mDNS IPv4 CAB1 `.237` ↔ CAB10 `.142` ;
- export NFS limité à l'IP exacte du pair ;
- montage NFS CAB1 ↔ CAB10 ;
- labels réels `Ultimate PinCabOS — CAB1` et `VMCABOS — CAB10` créés dans la vue dynamique.

## Frontières non négociables

PinCab Links / PinCabShare V2 ne modifie pas :

- VPX privé ;
- BGFX privé ;
- VPinFE ;
- les tables ;
- le moteur de lancement Multiplayer.
