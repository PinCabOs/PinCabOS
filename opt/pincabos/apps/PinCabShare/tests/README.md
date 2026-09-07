# Tests PinCabShare V2

Exécution ciblée :

```bash
python3 -m unittest discover -s /opt/pincabos/apps/PinCabShare/tests -p 'test_*.py' -v
```

Couverture principale :

- gate `open` valide avec 2 CAB ;
- gate serveur `closed` => fermeture immédiate ;
- TTL court obligatoire ;
- gate expiré/trop lointain => fermé ;
- CAB local absent ou membre dupliqué => fermé ;
- `share_nonce` invalide => fermé ;
- compatibilité avec l'alias live sans `expires_at` ;
- HTTPS obligatoire ;
- identité `PinCabOS-Device` utilisée sans exposer le token ;
- fallback `/api/device/pincabshare/state` -> `/api/device/multiplayer/share-gate` sur 404 ;
- les liens gérés sont supprimés au close, mais un dossier réel ou un symlink non géré n'est jamais détruit.

Les tests unitaires ne montent pas de NFS réel et ne touchent ni VPX, ni BGFX, ni VPinFE.
