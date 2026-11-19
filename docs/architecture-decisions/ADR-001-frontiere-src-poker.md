# ADR-001 — Frontière entre `src/` et `poker/`

**Statut :** Proposé
**Date :** 17 novembre 2026
**Décideur :** opérateur
**Specs liées :** `006-legacy-boundary`, `007-rust-core-migration`

## Contexte

Le dépôt contient deux bases Python :

- `src/` : runtime moderne V2 (vision, décision, API, solveur), ~34 600 lignes ;
- `poker/` : application historique PyQt6 et outils, ~26 300 lignes.

La CI mesure la couverture des deux avec un seuil global de 52 %. Le workflow
reconnaît que `poker/` est à ~12 % de couverture et dilue la métrique, alors que
`src/` est à ~84 %. Certains outils utiles (support Winamax, presets de sites)
vivent uniquement dans `poker/`, mais le runtime moderne ne les utilise pas.

Sans frontière explicite, chaque correctif peut diverger entre les deux bases,
et la couverture globale masque la qualité du code de production.

## Décision proposée

1. `src/` est la **seule base de production** pour le runtime, la vision, la
   stratégie et l'exécution.
2. `poker/` est déclaré **laboratoire historique** : il n'est pas appelé par le
   runtime de production. Il peut être utilisé pour des outils de développement
   ou des références, mais tout composant utile doit être migré vers `src/`.
3. La CI rapporte deux couvertures séparées : `src/` (seuil bloquant) et
   `poker/` (informatif, avec date de retrait).
4. Un plan de migration est établi pour les composants de `poker/` encore
   utiles : support Winamax, presets de sites, tests de capture.
5. À l'issue du plan, `poker/` est supprimé ou déplacé dans un dossier
   `legacy/` explicitement hors production.

## Conséquences

- Positives : une seule source de vérité, couverture représentative, suppression
  progressive de la dette, packaging simplifié.
- Négatives : effort de migration des outils Winamax et des presets ; risque de
  régression si un composant est supprimé trop tôt.
- Mitigation : tests de conformité par site avant toute suppression ; le dossier
  `poker/` reste lisible en lecture seule pendant la transition.

## Alternatives écartées

- **Fusionner immédiatement les deux bases** : trop risqué, pas de tests de
  parité.
- **Garder les deux bases indéfiniment** : coût de maintenance et ambiguïté de
  production.
- **Supprimer `poker/` immédiatement** : perte du support Winamax et des
  fixtures existantes.

## Critères de sortie

- `src/` couvert par un seuil bloquant indépendant.
- Adaptateur Winamax et fixtures migrés dans `src/`.
- Aucun import de production de `src/` vers `poker/`. — **satisfait et verrouillé
  le 19/11/2026** : la violation `src/api/routes_history.py` →
  `poker.decisionmaker.v2_contracts` a été corrigée par le déplacement des
  contrats V2 vers `src/contracts/v2_contracts.py` (les 23 importateurs du
  laboratoire, de `research/` et des tests pointent désormais vers `src/`) ;
  `tests/test_adr001_boundary.py` échoue sur tout import statique ou dynamique
  de `poker/` depuis `src/` (falsification vérifiée le 19/11/2026).
- `poker/` déplacé ou supprimé, avec un commit dédié.

## État au 19/11/2026

| Critère | État | Preuve |
|---|---|---|
| Seuil bloquant indépendant pour `src/` | **satisfait le 19/11/2026** | `python-tests.yml`, étape « Coverage src/ » : `coverage report --include="src/*" --fail-under=80` (mesuré 83 %), seuil global 52 % conservé à titre informatif |
| Adaptateur Winamax migré | non commencé (F-06, constat P1) | — |
| Aucun import `src/` → `poker/` | **satisfait** | `tests/test_adr001_boundary.py` (2 tests, falsifiés) |
| `poker/` déplacé ou supprimé | non commencé | — |
