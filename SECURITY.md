# Security Policy

## Posture

Ce projet pilote un client de poker en temps réel sur une machine Windows
locale. Surface d'attaque assumée : **localhost uniquement**.

- `gto_server` (Axum) n'écoute que sur `127.0.0.1:8765`, CORS allowlist
  `127.0.0.1:8765` / `127.0.0.1:8005`. Pas d'authentification : ne pas
  exposer ce port au-delà de la machine.
- PostgreSQL (`docker-compose.infra.yml`) : `127.0.0.1:5432` uniquement,
  mot de passe via `POKER_DB_PASSWORD` (placeholder `__CHANGE_ME__`).
- Aucun secret n'est committé : `config.json` ne contient que des
  placeholders `${VAR:-default}` ; les vraies valeurs vont dans
  l'environnement ou `config.local.json` (gitignored).

## Variables sensibles

| Variable | Usage |
|---|---|
| `POKER_DB_DSN` / `POKER_DB_PASSWORD` | DSN/mot de passe PostgreSQL |
| `OPENAI_API_KEY` / `GROQ_API_KEY` | Providers annotateur (optionnels, hors hot-path) |
| `POKER_AUTO_ANNOTATOR_API_KEY` | Annotateur local |

En cas de fuite accidentelle : révoquer/rotater la clé concernée
immédiatement, puis purger l'historique git si nécessaire.

## Garde-fous en place

- `eval()` interdit sur les payloads distants (`ast.literal_eval` uniquement)
- Tous les appels HTTP sortants ont un `timeout` + retry borné (`tenacity`)
- CI : gate `ruff --select E9,F63,F7,F82`, coverage minimale, `pip-audit`
  **bloquant** (le `continue-on-error` a été retiré le 26/08/2026 ; l'étape
  passe depuis le 20/11/2026 — 143 avis de sécurité ramenés à zéro par montée
  ciblée des dépendances, voir F-17), secrets exclus du tracking (`.gitignore`)
- CI : `cargo audit -D warnings` sur les **trois** lockfiles Rust (`Cargo.lock`,
  `gto_server/`, `python_bindings/`), job `audit` de `rust.yml` — ajouté le
  20/11/2026 (F-19). `-D warnings` couvre aussi les avis `unsound` et
  `unmaintained`, pas seulement les vulnérabilités. Les exemptions sont
  déclarées dans `.cargo/audit.toml` avec leur raison (aujourd'hui : `bincode`,
  non maintenu sans vulnérabilité publiée, qui porte le format binaire des
  arbres sérialisés)
- Requêtes SQL paramétrées (asyncpg `$1...`) — y compris patterns `LIKE`

## Signaler une vulnérabilité

Ouvrir une issue GitHub avec le label `security` ou contacter le
mainteneur directement. Ne pas publier de PoC détaillé avant correctif.

## Limitations connues

- Pas d'authentification sur l'API runtime locale (modèle mono-utilisateur)
- Les logs runtime (`log/runtime_history.jsonl`, `log/runtime_bridge/`)
  peuvent contenir des pseudos adverses — gitignored, ne pas partager
  sans redaction
- Le bundle portable embarque un interpréteur Python ; ne pas le distribuer
  avec un `config.local.json` rempli
