# PinCabShare V2

PinCabShare comporte volontairement **deux couches indépendantes**.

## 1. SMB local — toujours actif

Le dossier local du cabinet est :

```text
/srv/pincabshare/data
```

Il est publié en permanence sur le réseau privé sous le partage SMB :

```text
\\<IP-DU-CAB>\PinCabShare
```

Ce partage reste disponible même si :

- aucun Lobby n'est ouvert ;
- `pincabos.cc` est inaccessible ;
- le Multiplayer est arrêté ;
- aucun autre cabinet PinCabOS n'est connecté.

Le partage force les écritures sous l'utilisateur/groupe `pinball` et est limité aux plages privées RFC1918.

## 2. CAB↔CAB automatique — uniquement dans le même Lobby

La couche intercab utilise **SMB/CIFS uniquement** avec une découverte mDNS temporaire `_pincabshare._tcp`.

Le daemon interroge directement :

```text
GET https://pincabos.cc/api/device/pincabshare/state
```

avec l'identité `PinCabOS-Device` déjà provisionnée par PinCabOS Link. Il ne dépend pas d'un vieux `current.json` pour décider si le partage doit rester ouvert.

Le serveur construit un `pincabshare-gate/v2` à partir de la présence réelle du Lobby (`lobby_members.last_seen_at`). Le gate n'est valide que si :

- le CAB authentifié appartient à la session Multiplayer active ;
- son utilisateur est encore réellement présent dans le Lobby Web ;
- le `room_code` et le `session_id` correspondent ;
- le gate contient entre 2 et 4 présences Lobby fraîches ;
- le CAB local fait partie de ces membres ;
- le `share_nonce` commun est valide ;
- l'expiration très courte n'est pas dépassée.

Sans gate valide, en cas de perte du Lobby ou si `pincabos.cc` devient inaccessible :

- aucune annonce `_pincabshare._tcp` ;
- tous les montages CIFS distants sont démontés ;
- tous les liens distants disparaissent de `/home/pinball/PinCabShare`.

Le SMB local, lui, **reste actif en permanence**.

## Vue utilisateur

Exemple CAB1 lorsqu'un Lobby contient CAB1 et CAB10 :

```text
/home/pinball/PinCabShare/
├── Ultimate PinCabOS — CAB1 -> /srv/pincabshare/data
└── VMCABOS — CAB10         -> /run/pincabshare/mounts/CAB10
```

Avec 3 ou 4 CAB, un dossier portant le vrai nom du cabinet et son `CAB##` apparaît pour chaque CAB découvert et autorisé dans le même gate.

Lorsqu'un CAB quitte le Lobby, perd sa présence ou disparaît du réseau, son montage et son lien distant sont retirés. Les autres CAB valides peuvent continuer à échanger tant qu'ils sont au moins deux.

## Fail-closed

La couche CAB↔CAB se ferme notamment si :

- le serveur est injoignable ;
- l'authentification device échoue ;
- la présence Lobby expire ;
- le gate est expiré ou anormalement loin dans le futur ;
- le nonce, le room code ou la session sont invalides ;
- le CAB local n'est pas membre ;
- moins de deux CAB ont une présence Lobby fraîche.

## Sécurité projet

PinCabShare ne modifie pas :

- VPX privé ;
- BGFX privé ;
- VPinFE ;
- les fichiers de table ;
- le moteur de lancement Multiplayer.

Branche de développement :

```text
chatgpt/multiplayer-pincabshare-v2-20260906
```
