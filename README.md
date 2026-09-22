# Poker GTO Integration

This repository has three user-facing pieces:

- `poker/`: the archived V1 desktop poker bot GUI and OCR pipeline kept for compatibility
- `gto_server/`: the current Rust HTTP wrapper around the postflop solver
- `website/`: an optional Vite/React frontend

The canonical runtime path is now V2 under `src/`. The original `poker/` runtime is archived and should be treated as compatibility-only.

Recent architecture additions in this tree:

- Canonical V2 decision pipeline around `SpotSnapshot` / `SolveRequestV2` / `SolveResponseV2`
- Native-first solve orchestration with persistent disk cache and structured cache tiers
- Board-aware villain range model with calibration exports for offline analysis
- Decision gate support to block unsafe live clicks on incoherent, contradictory, or low-confidence OCR states
- Canonical tree preset catalog with prewarm hooks inspired by `desktop-postflop` and `wasm-postflop`
- Optional oracle backends for exact showdown validation, including `phevaluator` and Node-based JS bridges
- `research/` adapters for replay, simulator, benchmark, calibration, head-to-head, LBR, challenger workflows, and reusable validation suites
- Postflop compatibility bundles that export the canonical preset catalog for `desktop-postflop` / `wasm-postflop` style offline inspection
- A phase-2 automation layer with unified validation runners, persisted artifacts, and an extended offline RL lab

Documentation layout: `docs/` holds the current V2 documentation (French markdown). `doc/` is legacy V1 material (working plans and media assets referenced by the archived `archive/readme.rst`); do not add new documents there.

The desktop bot ships with bundled table profiles for PokerStars, PartyPoker and GGPoker, and its built-in table mapper can be used to add rooms such as Winamax, WPT Global, iPoker-style tables and CoinPoker.

There are now two ways to connect the solver core to Python:

- Current path: Python talks to `gto_server` over `http://127.0.0.1:8765`
- Native path: Python imports a Rust extension module built with `maturin` and `pyo3`

Use the server path if you want the setup that already exists in the tree. Use the native binding path if you want the lower-latency, single-process integration that is better suited to long-term Python packaging.

## Recommended Windows setup

Use these versions if you want the least friction:

- Python `3.11` x64
- Rust stable
- Node `20+`
- Microsoft Visual C++ Build Tools
- `maturin` for the native Python binding path

Do not use Python `3.12` for this project as-is: the current dependency set in this repository is not ready for it.

## 1. Create the Python environment

Preferred path — `uv` with the locked environment (`uv.lock`, reproducible):

```powershell
pip install uv
uv sync --extra dev
.\.venv\Scripts\Activate.ps1
```

Fallback — classic venv:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -e . --group dev
```

Notes:

- `pyproject.toml` + `uv.lock` are the single dependency source. The legacy mirror files (`requirements_win.txt`, `requirements_2026.txt`, `requirements_mac.txt`) have been removed — do not recreate them.
- **Contrainte GPU Pascal (GTX 10xx) : `onnxruntime-gpu` est figé à `1.19.2` (LTS, compute capability 6.1). Ne pas monter de version sans changer de GPU** ; `torch==2.8.0` avec inductor désactivé sur ces profils (voir `src/runtime/hardware.py`).
- Numeric OCR now uses `RapidOCR` with `onnxruntime`, so no separate local Tesseract install is required for the main path.
- The first OCR run downloads RapidOCR models into the active Python environment.
- You may also need the Microsoft Visual C++ Redistributable.

## Configuration & secrets

Never commit real credentials. Resolution order (see `src/config.py`):

1. Environment variables (`POKER_DB_DSN`, `OPENAI_API_KEY`, `GROQ_API_KEY`, ...)
2. `config.local.json` (gitignored — copy from `config.example.json`)
3. `config.json` (committed, placeholders `${VAR:-default}` only)
4. `config.example.json` (fallback template)

Key runtime toggles:

| Variable | Rôle |
|---|---|
| `POKER_DB_DSN` / `POKER_DB_MODE` | Connexion PostgreSQL (`auto`/`memory`/`postgres`) |
| `POKER_GTO_SERVER_URL` | URL du solver HTTP (défaut `http://127.0.0.1:8765/v2/solve`) |
| `POKER_GPU_PROFILE` | `auto` (défaut) / `3g` / `12g` / `cpu` — profil hardware forcé |
| `POKER_VRAM_CAP` | Fraction VRAM allouable (ex. `0.70`) |
| `POKER_REDIS_URL` | Cache L2 Redis optionnel pour les profils joueurs |
| `POKER_ENABLE_RL` / `POKER_ENABLE_VALIDATED_RL` | Toggles RL runtime |

## Hardware auto-adaptatif

Au boot, `src/runtime/hardware.py` détecte la VRAM et applique un profil
(3G / 12G / CPU) : cap mémoire PyTorch, `PYTORCH_CUDA_ALLOC_CONF`,
`cudnn.benchmark`, modèle YOLO cible, batch OCR, capture d'observation.
Aucun flag manuel requis ; `POKER_GPU_PROFILE` force un profil (CI, bench).
Le profil actif est loggé en `INFO` au démarrage.

## 2. Start the local GTO server

From the repository root:

```powershell
cargo run --release --manifest-path .\gto_server\Cargo.toml
```

Health check:

```powershell
Invoke-WebRequest http://127.0.0.1:8765/health
```

Expected response:

```text
gto_server OK
```

## 3. Native Python binding path

This is the direct Python-to-Rust route. It keeps the solver in Rust, but exposes it as a Python extension module instead of a localhost HTTP server.

Install `maturin` inside the virtual environment:

```powershell
python -m pip install maturin
```

Build the extension in editable mode from the repository root:

```powershell
maturin develop --release --manifest-path .\python_bindings\Cargo.toml
```

If you want a wheel instead of an editable install:

```powershell
maturin build --release --manifest-path .\python_bindings\Cargo.toml --out .\wheelhouse
```

Notes:

- These commands assume the binding crate lives in `python_bindings\Cargo.toml`.
- If you place the binding crate somewhere else, update the `--manifest-path` accordingly.
- `maturin develop` is the easiest option for local work because it installs the module into the active venv immediately.

## 4. Start the desktop bot

Preferred V2 launcher from the repository root:

```powershell
python .\main.py
```

Archived legacy launcher:

```powershell
$env:POKER_USE_LEGACY=1
python .\poker\main.py
```

The legacy launcher delegates to V2 by default unless `POKER_USE_LEGACY=1` is set.

Open a second terminal:

```powershell
.\.venv\Scripts\Activate.ps1
cd .\poker
python .\main.py
```

Convenience launchers from the repository root:

```powershell
.\start_direct.ps1
.\start_vbox.ps1 -VmName w1064
```

Notes:

- `start_direct.ps1` sets `control = Direct mouse control` in `poker/config.ini` before launch.
- `start_vbox.ps1` sets `control = <VmName>` in `poker/config.ini` before launch.
- If VirtualBox is unavailable at runtime, the bot now falls back to direct mouse control instead of failing during startup.
- `poker/` is archived legacy code and should only receive compatibility fixes.

## 5. Optional website

The website is separate from the desktop bot.

```powershell
cd .\website
npm install
npm run dev
```

The React dependencies were adjusted to install cleanly with React 18.

The frontend talks to the local runtime API at `http://127.0.0.1:8005` (override via `VITE_REACT_APP_API_URL`, see `website/.env.development`). The solver server runs separately at `http://127.0.0.1:8765` (see section 2). Legacy analytics views that have no local endpoint render a dismissible "not available in local mode" banner when the backend is unreachable.

Canonical V2 desktop launcher (Tauri shell, WSL-based build) from the repository root:

```powershell
.\launch_pokermaster_v2.cmd                  # auto-build if sources changed, then run
.\launch_pokermaster_v2.cmd -NoBuild         # run the existing binary without building
.\launch_pokermaster_v2.cmd -BuildDebug      # force a full debug build
.\launch_pokermaster_v2.cmd -BuildRelease    # force a full release build
.\launch_pokermaster_v2.cmd -Web             # web-only mode: Vite dev server, no Rust shell
.\launch_pokermaster_v2.ps1 -Detached        # background launch, log in launch_pokermaster_v2.log
```

`launch_pokermaster_v2.cmd` is a thin wrapper over `launch_pokermaster_v2.ps1`, which delegates the build to `launch_pokermaster_v2.sh` inside WSL. The old per-variant launchers (`*_nobuild`, `*_tauri_debug`, `*_web`) were removed; use the switches above.

## 6. Portable Windows bundle

Build a portable desktop bundle from the repository root:

```powershell
.\build_portable.ps1
```

Output:

- `portable\PokerMaster-portable`

Run it with:

```powershell
.\portable\PokerMaster-portable\start_direct.ps1
.\portable\PokerMaster-portable\start_vbox.ps1 -VmName w1064
```

Notes:

- The portable bundle fully targets direct mouse control.
- VirtualBox mode remains supported, but still requires VirtualBox to be installed on the host machine.
- The bundle auto-starts a bundled `gto_server.exe` when no native solver binding is installed.

## 7. Windows smoke test

To verify the Windows launch paths automatically from the repository root:

```powershell
.\smoke_test_windows.ps1
```

If PowerShell execution policy gets in the way, use:

```bat
.\smoke_test_windows.cmd
```

Optional VirtualBox check:

```powershell
.\smoke_test_windows.ps1 -VmName w1064
```

The script checks the Python environment, starts a local `gto_server`, smoke-tests the direct launch paths, and writes logs into `smoke-test-logs\`.

## 8. Refonte V2 validation

The refonte V2 stack now has reproducible validation runners:

```powershell
python .\research\run_validation_suite.py
python .\research\run_rl_lab.py
python .\scripts\run_refonte_ci.py
```

Artifacts are written into `research\results\`.

## 9. Optional PostgreSQL test integration

Most tests do not require PostgreSQL. The PostgreSQL-backed integration test stays optional and is skipped by default when the database is unavailable.

Typical local runs from the repository root:

```powershell
pytest
pytest -m "postgres" --run-postgres
pytest tests\test_database_postgres_integration.py --run-postgres --postgres-dsn "postgresql://user:password@localhost:5432/poker_db"
```

Supported test DSN sources, in priority order:

- `--postgres-dsn`
- `POKER_TEST_DSN`
- `POSTGRES_TEST_DSN`
- `DATABASE_URL`
- built-in local default from `tests/conftest.py`

Useful toggles:

- `POKER_RUN_POSTGRES_TESTS=1` to explicitly opt in
- `POKER_RUN_POSTGRES_TESTS=0` or `pytest --no-postgres` to force-skip

If PostgreSQL is requested but cannot be reached, pytest now reports which DSN inputs are supported so the failure mode is easier to diagnose.

## 10. Solver EV — unités & exemple chiffré

Le solver expose une chaîne unique `ev_chips → ev_bb → ev_bb_per_100 → $EV` (helpers purs `src/ev.rs`, doc `docs/esperance.md`).

| Unité (clé code) | Définition | Conversion | Quand l'utiliser |
|---|---|---|---|
| `ev_chips` | `hero_ev` brut chips (sortie solver) | — | Payoffs, AIVAT |
| `ev_bb` | EV en big blinds | `ev_chips / bb` | Pivot WR, edge a-f |
| `ev_bb_per_100` | WR normalisé /100 mains | `ev_bb × 100` | `P(profit)`, bench `probabilites.md` §2 |
| `ev_dollars` | Cash direct | `ev_chips × ($/bb / bb)` (`ev_bb_dollars` par profil) | Bankroll cash |
| `$EV` | ICM/bounty-adjusted | `ChipEV + BountyEV` (PKO C23, ICM C24) | MTT/PKO seul décide |

- `bb` dérivé par défaut de `effective_stack/100` (fallback 100bb deep, `tracing::warn` + `dollar_ev_note`). Renseigner `ev_bb_dollars` par `site_profiles` élève `ev_dollars` (sinon `None`).
- Rake (C20) `share=(pot-rake)/winners`, `rake=min(pot*rate,cap)` — 5% cap $3 → net $97 sur pot $100 ; omettre le rake surestime 1.5–4 bb/100 en micro.
- Gain mensuel : `€/mois = WR × (mains/100) × €/bb` (WR = `ev_bb_per_100`, `€/bb` = valeur d'une bb — NL10 0.10 €/bb, 600 mains/h ; table complète `esperance.md` §6, P aux mêmes volumes `probabilites.md` §2.2bis, rythme `ordre-conseille.md` §1).
- Vérifier en local :

```powershell
cargo run --example esperance
# S1 ev_chips=5.0 ev_bb=2.5 bb/100=250 $EV=0.05   (pot 100 eq 0.55 cost 50, NL2 bb=2 $/bb=0.02)
# S2 rake=3 net=97 ev_chips=38.2 ev_bb=19.1 $EV=0.38 (+BountyEV=0.06 BI)
# S3 regimes NL10 WR7 : 4h×5j 48k 336€ P95.6% | 6h×6j 86k 602€ P98.9% | 12h×6j 173k 1211€ th. / 865€ si WR 7→5 (tilt)
cargo run --example esperance -- --regime 6h6j
# NL10 6h×6j 86k mains WR7 → 602€ 4.18€/h P98.9% (voir docs/esperance.md §6)
```

Voir `examples/esperance.rs` (3 spots : S1/S2 + S3 régimes, `esperance.md` §6), `src/ev.rs`, `docs/esperance.md` §3-7, `docs/probabilites.md` §2.2bis, `docs/ordre-conseille.md` §1.

## 11. Runtime RL toggle

The live Python bot keeps RL enabled by default for backward compatibility, but you can disable it at runtime in environments where the RL stack should stay off outside tests.

- Config file: set `rl.enable` to `false` in `config.json`
- Environment override: set `POKER_ENABLE_RL=0`
- Optional related toggles: `POKER_AUTOLOAD_RL_MODEL=0` and `POKER_ENABLE_VALIDATED_RL=0`

Resolution order is: environment variable, then `config.json`, then the built-in default.

## Integration Notes

- The server path is the safest choice if you want a process boundary and simple runtime isolation.
- The native binding path is the better choice if you want to remove the local HTTP hop and package the solver more like a normal Python extension.
- Both paths still rely on the same Rust solver core.
- The native binding path still needs the Rust toolchain and a Windows-capable C++ build environment.

## Known limits

- OCR, Qt, and TensorFlow are still heavy local dependencies.
- Card recognition still relies on template matching / card-specific recognition, not generic OCR.
- Multi-way postflop solving is not fully handled by the Rust solver path.
- The website defaults to the local runtime API (`http://127.0.0.1:8005`); legacy analytics views that have no local endpoint show a dismissible "not available in local mode" banner instead of data.
