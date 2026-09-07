# PinCabOS Alpha 4.53 — PinCab Links

Release de consolidation de **PinCab Links** après validation réelle CAB1 ↔ CAB10.

## PinCab Explorer

- `PinCabShare` reste le partage SMB historique du cabinet sur `/home/pinball/Share`.
- La couche CAB↔CAB dynamique est présentée sous **PinCab Links**.
- Les cabinets autorisés apparaissent directement comme raccourcis dans le menu avec leur nom de profil + `CAB##`.
- Exemple validé : `Ultimate PinCabOS — CAB1` et `VMCABOS — CAB10`.

## Autorité Lobby

PinCab Links s'ouvre uniquement pour 2 à 4 cabinets qui remplissent simultanément les conditions suivantes :

- membership réel dans la même room Lobby ;
- même session Multiplayer active ;
- correspondance exacte `user_id ↔ cabinet_id` ;
- bail device PinCab Links frais entretenu par le CAB authentifié.

La fraîcheur d'un onglet navigateur n'est pas utilisée comme autorité, afin d'éviter les faux négatifs causés par le throttling des timers en arrière-plan.

## Transport CAB↔CAB

- HTTPS vers `pincabos.cc` pour l'autorisation ;
- Avahi/mDNS pour la découverte IPv4 uniquement ;
- NFS dynamique vers l'IP exacte du pair autorisé ;
- aucun export NFS permanent `/24`, `/16`, RFC1918 global ou `*`.

Le gate est fail-closed : perte de membership/session/bail ou serveur invalide retire les annonces, exports, montages et liens gérés sans supprimer les données locales.

## Validation réelle

Validé avec :

- CAB1 : `192.168.254.237` ;
- CAB10 : `192.168.254.142` ;
- gate `open` des deux côtés ;
- `authorized_ids=[1,10]` ;
- découverte mDNS IPv4 mutuelle ;
- exports NFS limités à l'IP exacte de l'autre CAB ;
- montages NFS mutuels ;
- labels réels présents dans la vue dynamique.

## Frontières

Aucun changement aux fichiers ou configurations du VPX privé, BGFX privé ou VPinFE. Le moteur de lancement Multiplayer reste séparé de PinCab Links.
