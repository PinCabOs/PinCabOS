# Config testeur PinCabOS

Ce répertoire contient le transport et les rapports matériels/configuration générés par le **System Audit** PinCabOS.

## Nomenclature

`<testeur>-<hostname>-<YYYYMMDD-HHMMSS>-issue<numero>-system-audit.txt`

Exemple :

`karots-sugarpie-pincabos-20260909-130241-issue123-system-audit.txt`

## Flux V4 — aucun token GitHub sur les cabinets

1. Le testeur lance l'audit depuis **About → System Audit** ou avec `pincabos-system-audit-launcher.sh` comme utilisateur `pinball`.
2. Le lanceur reçoit l'identité déjà validée par la WebApp ou la résout côté serveur via `pincabos-account-bridge context`.
3. Le nom utilisé est `user.display_name`, avec repli sur `user.username`.
4. Aucun `device_token` PinCabOS.cc n'est envoyé au navigateur ou au rapport.
5. Le lanceur télécharge `pincabos-system-audit-v4.sh` depuis la source canonique GitHub et lance le job en tâche détachée.
6. Une coupure SSH n'interrompt ni la collecte ni l'envoi.
7. L'audit collecte le matériel et la configuration en lecture seule.
8. IP, MAC, tokens, mots de passe, clés privées et credentials sont exclus ou masqués du rapport.
9. Le rapport est compressé en gzip, encodé en base64 et envoyé en HTTPS au Worker Cloudflare `pincabos-tester-upload`.
10. Aucun token GitHub, login GitHub ou secret d'upload n'est stocké sur le cabinet.
11. Le Worker possède `GITHUB_TOKEN` comme **secret Cloudflare** et crée une Issue de transport dans `PinCabOs/PinCabOS`, puis les commentaires/chunks.
12. Le commentaire final `PINCABOS_TESTER_REPORT_COMPLETE_V3` déclenche `.github/workflows/pincabos-tester-report-ingest.yml`.
13. Le workflow valide l'auteur, le schéma, les chunks, la taille et le SHA-256, reconstruit le `.txt`, commit uniquement sous `DEV/config-testeur/`, puis ferme l'Issue.

## Endpoint actif

`https://pincabos-tester-upload.pincabos.workers.dev/v1/tester-report`

Health check :

```bash
curl -fsS https://pincabos-tester-upload.pincabos.workers.dev/health
```

La réponse déployée doit indiquer le dépôt canonique :

```json
{"ok":true,"service":"pincabos-tester-upload","version":4,"repository":"PinCabOs/PinCabOS"}
```

## Commande officielle du testeur

À exécuter comme utilisateur `pinball` :

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/PinCabOs/PinCabOS/main/DEV/config-testeur/pincabos-system-audit-launcher.sh)
```

Sur un cabinet jumelé, aucun nom manuel n'est demandé : l'identité PinCabOS.cc est résolue automatiquement.

Le journal de suivi est conservé sous :

`/home/pinball/.cache/pincabos-tester-report/`

## Credential GitHub du Worker

Le secret Cloudflare s'appelle **`GITHUB_TOKEN`**. Pour un fine-grained PAT, la configuration minimale est :

- Resource owner : `PinCabOs`
- Repository access : `PinCabOS` uniquement
- Repository permissions : `Issues` → **Read and write**
- `Metadata` → Read-only (automatique)

Le token ne doit jamais être ajouté au dépôt, au code JavaScript ou au cabinet.

Voir `cloudflare-worker/README.md` pour la rotation et le déploiement.

## Fichiers canoniques actifs

- `pincabos-system-audit-launcher.sh` : lanceur V4 résilient SSH/WebApp et résolution d'identité.
- `pincabos-system-audit-v4.sh` : audit matériel/configuration et transport HTTPS vers Cloudflare.
- `cloudflare-worker/src/index.js` : passerelle Cloudflare vers GitHub Issues.
- `cloudflare-worker/wrangler.toml` : configuration Worker + rate limiter.
- `pincabos-tester-report-ingest-v3.py` : validateur/reconstructeur exécuté par GitHub Actions.
- `.github/workflows/pincabos-tester-report-ingest.yml` : ingestion et commit automatique du rapport.

## Héritage

`pincabos-system-audit.sh` est conservé comme référence de l'ancien transport direct GitHub. Le lanceur officiel ne l'utilise plus.
