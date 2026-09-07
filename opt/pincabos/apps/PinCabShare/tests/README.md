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
- authentification `PinCabOS-Device` utilisée sans exposer le token.
