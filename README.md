# Poker GTO Integration

This repository has three user-facing pieces:

- `poker/`: the original desktop poker bot GUI and OCR pipeline
- `gto_server/`: the current Rust HTTP wrapper around the postflop solver
- `website/`: an optional Vite/React frontend

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

From the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements_win.txt
```

Notes:

- `PyQt6` and `tensorflow` are still the most fragile packages.
- Numeric OCR now uses `RapidOCR` with `onnxruntime`, so no separate local Tesseract install is required for the main path.
- The first OCR run downloads RapidOCR models into the active Python environment.
- You may also need the Microsoft Visual C++ Redistributable.

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

## 5. Optional website

The website is separate from the desktop bot.

```powershell
cd .\website
npm install
npm run dev
```

The React dependencies were adjusted to install cleanly with React 18.

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

## 10. Runtime RL toggle

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
- The website still talks to external API endpoints by default unless you reconfigure `website/src/views/config.tsx`.
