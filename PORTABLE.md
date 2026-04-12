# Portable Bundle

This repository can produce a portable Windows bundle for the direct-control mode.

## Build

From the repository root:

```powershell
.\build_portable.ps1
```

The bundle is created in `portable\PokerMaster-portable`.

## Run

Inside the generated bundle:

```powershell
.\start_direct.ps1
.\start_vbox.ps1 -VmName w1064
```

## What Is Bundled

- the desktop app built with PyInstaller
- `config.ini`, `config_default.ini`, and the Qt `.ui` files
- `tessdata`
- `gto_server.exe` when `gto_server\target\release\gto_server.exe` exists at build time

The app will try the native Python solver binding first. If it is unavailable, it will try to auto-start a bundled `gto_server.exe`.

## Limits

- Direct mouse control is the only fully portable mode.
- VirtualBox support still depends on a system installation of VirtualBox on the host machine.
- If VirtualBox is requested but unavailable, runtime falls back to direct mouse control.
