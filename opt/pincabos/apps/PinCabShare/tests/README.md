# Tests PinCabShare V2

Tests ciblés :

```bash
python3 -m unittest discover -s /opt/pincabos/apps/PinCabShare/tests -p 'test_*.py' -v
```

Couverture principale :

- gate serveur valide ;
- serveur inaccessible => inter-CAB fermé ;
- gate désactivé/expiré/trop lointain => fermé ;
- mauvais session/room/nonce => fermé ;
- CAB local absent ou membre dupliqué => fermé ;
- client HTTPS obligatoire ;
- authentification `PinCabOS-Device` utilisée sans exposer le token ;
- vue locale `/home/pinball/PinCabShare` gérée uniquement par les labels autoritaires ;
- aucun partage SMB PinCabShare permanent ;
- export NFS dynamique limité aux IP exactes des pairs autorisés ;
- arrêt/fermeture du gate => mDNS, export, montages et liens gérés retirés, données locales conservées.

Le mode jeu Multiplayer reste hors périmètre de ces tests et ne doit pas être repris avant validation réelle CAB1↔CAB10.
