# Contributing

## Setup

```powershell
pip install uv
uv sync --extra dev
.\.venv\Scripts\Activate.ps1
```

Python **3.11** obligatoire (pas 3.12). Rust stable pour `gto_server` /
`python_bindings`.

## Commandes de base

| Commande | Rôle |
|---|---|
| `uv run pytest` | Suite principale (`tests/`) |
| `uv run pytest --cov=src --cov=poker --cov-fail-under=35` | Avec coverage (gate CI) |
| `python scripts/run_refonte_ci.py` | Validation V2 complète (pytest + oracle JS/Rust + cargo) |
| `uv run ruff check src --select E9,F63,F7,F82` | Lint gate bloquant |
| `cargo test` / `cargo clippy` | Crate solver + serveur |
| `python research/run_validation_suite.py` | Oracle randomized + replay |

## Règles

1. **Toute modification comportementale vient avec des tests.** La suite
   doit rester verte : 0 failure, skips limités aux captures locales.
2. **Pas de secret en clair** : placeholders `${VAR:-default}` dans les
   configs committées, valeurs réelles en env ou `config.local.json`.
3. **Le chemin runtime canonique est V2 sous `src/`** — `poker/` est un
   archivé compatibilité ; ne pas y ajouter de fonctionnalité.
4. **Budget temps réel 1000 ms** : tout ajout au hot-path vision/solver
   doit justifier sa latence (règle : refusé si >200 ms ou >300 Mo VRAM).
5. **Comportement GTO protégé** : toute évolution solver/décision passe
   par `research/run_validation_suite.py` (oracle 500 mains, 0 mismatch).
6. Coverage : ne pas faire baisser le total ; la CI porte un gate qui
   monte par paliers (+5 pts/sprint vers 60%).

## Style

- Format : `black` (line-length 100) — adoption progressive, voir plan Phase 4.2
- Imports triés (`ruff I`), pas d'import inutilisé (`F401`)
- Docstrings courtes sur les modules nouveaux ; pas de commentaires narratifs

## Commits

Messages courts, préfixe conventionnel : `feat:`, `fix:`, `test:`,
`docs:`, `build:`, `chore:`, `ci:`. Un commit = une intention cohérente.
