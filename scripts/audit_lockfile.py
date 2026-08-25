"""Audit CVE du lockfile via l'API JSON PyPI (parallèle, timeout court).

Sortie : research/results/lockfile_audit.json + résumé console.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements" / "lock-audit.txt"
OUT = ROOT / "research" / "results" / "lockfile_audit.json"

PYPI = "https://pypi.org/pypi/{name}/{version}/json"


def parse_lock(path: Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        spec = line.split(";")[0].split(" ")[0]
        if "==" not in spec:
            continue
        name, _, version = spec.partition("==")
        entries.append((name.strip(), version.strip()))
    return entries


def fetch(name: str, version: str) -> tuple[str, str, list[dict]]:
    url = PYPI.format(name=name, version=version)
    req = urllib.request.Request(url, headers={"User-Agent": "poker-lockfile-audit"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        vulns = data.get("vulnerabilities") or []
        return name, version, [
            {
                "id": v.get("id"),
                "aliases": v.get("aliases", []),
                "fix_versions": v.get("fixed_in", []),
                "summary": (v.get("summary") or "")[:160],
            }
            for v in vulns
        ]
    except Exception as exc:
        return name, version, [{"error": str(exc)[:200]}]


def main() -> int:
    if not LOCK.exists():
        print(f"lock introuvable: {LOCK}")
        return 1
    packages = parse_lock(LOCK)
    print(f"{len(packages)} packages à auditer...")

    results = {}
    errors = 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        for name, version, vulns in pool.map(lambda p: fetch(*p), packages):
            results[f"{name}=={version}"] = vulns
            if vulns and "error" in vulns[0]:
                errors += 1

    affected = {k: v for k, v in results.items() if v and "error" not in v[0]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nPackages affectés : {len(affected)} / {len(packages)} (erreurs réseau: {errors})")
    total = sum(len(v) for v in affected.values())
    print(f"Advisories totaux : {total}\n")
    for key in sorted(affected):
        fixable = []
        for v in affected[key]:
            fixes = ",".join(v.get("fix_versions") or []) or "?"
            fixable.append(f"{v['id']} -> {fixes}")
        print(f"{key}: {'; '.join(fixable)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
