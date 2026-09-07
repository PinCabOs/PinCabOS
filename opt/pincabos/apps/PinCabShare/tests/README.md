# Tests PinCabShare V2 / PinCab Links

Ces tests couvrent la logique pure et les garde-fous du module CAB sans nécessiter de montage NFS réel.

Exécution :

```bash
cd /opt/pincabos/apps/PinCabShare
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Couverture :

- validation du gate court (`gate=open/closed`, 2–4 CAB, TTL, labels) ;
- client HTTPS Device-auth et fallback d'endpoint ;
- vue locale et nettoyage fail-closed ;
- patch WebApp idempotent : `PinCabShare` reste le SMB `/home/pinball/Share`, tandis que `PinCab Links` expose les CAB dynamiques dans le menu ;
- aucune dépendance ou modification de VPX privé, BGFX privé ou VPinFE.

Les tests réseau NFS/mDNS réels restent des tests d'intégration cabinet. Le test live CAB1 `.237` ↔ CAB10 `.142` a confirmé le gate, la découverte IPv4, les exports NFS par IP exacte, les montages et les deux labels dynamiques.
