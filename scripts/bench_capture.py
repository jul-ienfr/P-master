"""Bench latence capture — WGC (HWND) vs dxcam (écran).

Mesure la latence frame-à-frame de chaque backend sur une fenêtre réelle :
  python scripts/bench_capture.py [hwnd] [--frames N]

Sans hwnd, prend la première fenêtre VS Code visible.
Résultats attendus (GTX 1060, Win11) : WGC ~8-16 ms/frame à 60 Hz,
dxcam.grab ~4-10 ms mais lit les pixels écran (sensible à l'occlusion).
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np


def find_vscode_hwnd() -> int | None:
    try:
        import win32gui

        hwnds: list[int] = []

        def cb(hwnd, acc):
            title = win32gui.GetWindowText(hwnd)
            if win32gui.IsWindowVisible(hwnd) and title and "Visual Studio Code" in title:
                acc.append(hwnd)

        win32gui.EnumWindows(cb, hwnds)
        return hwnds[0] if hwnds else None
    except Exception:
        return None


def bench_wgc(hwnd: int, frames: int) -> dict:
    import cv2

    from src.vision.capture import WgcWindowCapture

    session = WgcWindowCapture(hwnd)
    latencies_ms = []
    convert_ms = []
    got = 0
    # La session produit en asynchrone (thread natif) : on mesure le débit
    # réel (wall time pour N frames consommées) + le coût de copie BGR.
    wall_start = time.perf_counter()
    deadline = wall_start + 15.0
    try:
        while got < frames and time.perf_counter() < deadline:
            t0 = time.perf_counter()
            frame = session.get_frame()
            if frame is None:
                time.sleep(0.002)
                continue
            t1 = time.perf_counter()
            cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)  # coût consommateur représentatif
            latencies_ms.append((t1 - t0) * 1000.0)
            convert_ms.append((time.perf_counter() - t1) * 1000.0)
            got += 1
        wall_s = time.perf_counter() - wall_start
    finally:
        session.stop()
    return {
        "backend": "wgc",
        "frames": got,
        "latencies": latencies_ms,
        "convert": convert_ms,
        "wall_s": wall_s,
    }


def bench_dxcam(region=None, frames: int = 200) -> dict:
    import dxcam

    camera = dxcam.create(output_color="BGR")
    latencies_ms = []
    convert_ms = []
    got = 0
    wall_start = time.perf_counter()
    deadline = wall_start + 15.0
    try:
        while got < frames and time.perf_counter() < deadline:
            t0 = time.perf_counter()
            frame = camera.grab(region=region)
            if frame is None:
                time.sleep(0.002)
                continue
            t1 = time.perf_counter()
            latencies_ms.append((t1 - t0) * 1000.0)
            convert_ms.append((time.perf_counter() - t1) * 1000.0)
            got += 1
        wall_s = time.perf_counter() - wall_start
    finally:
        try:
            camera.release()
        except Exception:
            pass
    return {
        "backend": "dxcam",
        "frames": got,
        "latencies": latencies_ms,
        "convert": convert_ms,
        "wall_s": wall_s,
    }


def summarize(result: dict) -> str:
    lats = result["latencies"]
    convs = result.get("convert", [])
    wall_s = result.get("wall_s", 0.0)
    fps = result["frames"] / wall_s if wall_s else 0.0
    if not lats:
        return f"{result['backend']}: aucune frame capturée"
    return (
        f"{result['backend']:>6} | {result['frames']:>4} frames | "
        f"debit {fps:6.1f} fps | "
        f"grab médiane {statistics.median(lats):6.2f} ms | "
        f"post-trait. médiane {statistics.median(convs):5.2f} ms"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("hwnd", nargs="?", type=lambda v: int(v, 0), default=None)
    parser.add_argument("--frames", type=int, default=100)
    args = parser.parse_args()

    hwnd = args.hwnd or find_vscode_hwnd()
    if not hwnd:
        print("Aucune fenêtre cible trouvée; passe un HWND en argument.")
        return 1
    print(f"Cible HWND {hwnd} — {args.frames} frames par backend\n")

    print(summarize(bench_wgc(hwnd, args.frames)))
    print(summarize(bench_dxcam(frames=args.frames)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
