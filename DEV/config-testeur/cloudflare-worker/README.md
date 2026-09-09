# PinCabOS Tester Upload — Cloudflare Worker

Worker : `pincabos-tester-upload`

Endpoint : `https://pincabos-tester-upload.pincabos.workers.dev/v1/tester-report`

Dépôt GitHub cible : `PinCabOs/PinCabOS`

## Secret GitHub

Le Worker utilise uniquement le secret Cloudflare :

`GITHUB_TOKEN`

Pour un **fine-grained Personal Access Token** GitHub :

- Resource owner : `PinCabOs`
- Repository access : **Only select repositories** → `PinCabOS`
- Repository permissions : **Issues → Read and write**
- Metadata : Read-only (automatique)

Aucun droit `Contents: write` n'est nécessaire au Worker : l'écriture du rapport dans le dépôt est faite ensuite par GitHub Actions avec son `github.token` temporaire.

## Rotation du secret

Depuis une machine déjà authentifiée à Cloudflare/Wrangler :

```bash
cd DEV/config-testeur/cloudflare-worker
npx wrangler secret put GITHUB_TOKEN
```

Coller le nouveau PAT uniquement dans l'invite Wrangler. Ne jamais l'écrire dans un fichier du dépôt.

## Déploiement

```bash
cd DEV/config-testeur/cloudflare-worker
npx wrangler deploy
```

## Validation

```bash
curl -fsS https://pincabos-tester-upload.pincabos.workers.dev/health
```

Résultat attendu :

```json
{"ok":true,"service":"pincabos-tester-upload","version":4,"repository":"PinCabOs/PinCabOS"}
```

Ensuite relancer **About → System Audit** sur un cabinet jumelé.

Le résultat final doit être `GO [OK] RAPPORT TRANSMIS`, avec un numéro et une URL d'Issue GitHub.

## Diagnostic 403

`github_http_403:Resource not accessible by personal access token` signifie que GitHub a reçu le credential, mais qu'il n'autorise pas l'action demandée sur la ressource cible.

Après le transfert du dépôt vers l'organisation `PinCabOs`, un ancien fine-grained PAT limité au propriétaire `KarotsSugarpie` ne donne plus l'accès requis au dépôt `PinCabOs/PinCabOS`. Il faut donc utiliser un token dont le **Resource owner est `PinCabOs`** et dont la permission **Issues est Read and write**.

La réponse d'erreur du Worker inclut aussi maintenant le dépôt cible et, lorsque GitHub le fournit, l'en-tête `X-Accepted-GitHub-Permissions` afin de faciliter les prochains diagnostics.
