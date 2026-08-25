# Triage CVE lockfile — 2026-08-24

Audit via `scripts/audit_lockfile.py` (API JSON PyPI, parallèle).
Snapshot complet : `lockfile_audit.json`.

**Résultat après bump aiohttp 3.12→3.14.3 : 2 packages affectés sur 125,
41 advisories (avant bump : 3 packages, 105).**

| Paquet | Version | Décision | Justification |
|---|---|---|---|
| aiohttp | 3.12.14 | **Fixé → 3.14.3** | API locale uniquement ; bump mineur sans rupture observée (suite verte) |
| pillow | 10.4.0 | Reporté | N'ingère que des captures d'écran locales produites par le runtime ; aucun input non fiable. Bump 10→12 risqué pour la chaîne OCR (à faire avec bench visuel dédié) |
| torch | 2.8.0 | Reporté | Advisories ciblant torchserve/chargement de modèles non fiables/distributed — hors usage (inférence locale de modèles propriétaires). PYSEC-2026-139 sans fix disponible. Plan Phase 1 : stabiliser torch, pas de churn |

Réévaluer pillow/torch lors du prochain sprint deps (bump groupé + bench
golden solves).
