# PokerMaster V1 Legacy Archive

This repository now treats the original desktop runtime under `poker/` as archived legacy code.

## Status

- Canonical runtime: `src/` V2 stack
- Legacy compatibility runtime: `poker/`
- Solver backend priority in V2: native binding -> `gto_server` -> safe fallback

## Legacy scope

The V1/legacy surface includes the historical PyQt desktop application and its original runtime entrypoint:

- `poker/main.py`
- the legacy GUI/runtime flow under `poker/gui/`, `poker/scraper/`, `poker/decisionmaker/`, and related helpers

This code remains in the repository for:

- user compatibility
- migration reference
- historical workflows that have not yet been removed

It is no longer the primary path for new runtime work.

## Launch policy

- Preferred launcher: `python .\main.py`
- Canonical runtime entrypoint: `src/main.py`
- Legacy launcher fallback: `python .\poker\main.py`

By default, `poker/main.py` delegates to the V2 runtime.

To force the archived legacy path:

```powershell
$env:POKER_USE_LEGACY=1
python .\poker\main.py
```

## Maintenance policy

- Bug fixes in `poker/` should be compatibility-only.
- Do not add new business logic to the legacy runtime when the same change belongs in V2.
- New runtime architecture work should target `src/` and associated V2 services.
