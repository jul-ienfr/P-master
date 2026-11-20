# Registre de migration Rust

**Version :** 1.0.0 — 17 novembre 2026
**Source de vérité :** constitution `.specify/memory/constitution.md` §II et §IX.

Ce registre liste les composants du système, leur langage actuel, leur statut de
migration et leur propriétaire. Un composant ne peut pas avoir deux
implémentations de production actives. Toute migration suit le cycle : contrat
et tests de parité → implémentation Rust → bascule derrière un flag → comparaison
sur rejeux → suppression de l'ancien chemin.

## Déjà en Rust

| Composant | Fichier | Statut | Notes |
|---|---|---|---|
| Solveur DCFR HU | `src/solver.rs` | Production | Budget mural, finalisation réservée |
| Solveur MCCFR multiway 3–6 | `src/multiway.rs` | Production | Spec `002` — branché au runtime, backend `multiway_mccfr`, réponses `sampled=true` et `converged=false` |
| Bankroll et risque | `src/bankroll.rs` | Production | Spec `004` — RoR, P(profit), Kelly, bankroll cible, move-up/down, limites de session ; 16 tests contre les formes fermées de `docs/probabilites.md` §2/§6 ; exposé par PyO3, `src/bot/session_manager.py` ne garde que l'horloge et les messages |
| Équité et évaluation | `src/equity.rs`, `src/ev.rs` | Production | |
| Arbre et abstraction de mises | `src/action_tree.rs`, `src/bet_size.rs` | Production | |
| Rake dans l'arbre | `src/gto_api.rs`, `src/tree.rs` | Production | C20 |
| MES / exploitabilité | `src/utility.rs` | Production | |
| API V2 et bindings | `src/v2_api.rs`, `python_bindings/` | Production | |

## À porter en priorité

| Composant | Langage actuel | Cible | Priorité | Spec | Critère de sortie |
|---|---|---|---|---|---|
| État canonique et validateurs | Python dispersé | Rust | P1 | `007` | Un seul `CanonicalState`, tests de propriété |
| Orchestrateur de politique | Python | Rust | P1 | `007` | Sélection d'action unique, testée sur rejeux |
| Journal de décision structuré | Python | Rust | P1 | `008` | Schéma versionné, corrélation `spot_id` |
| Post-traitement vision | Python | Rust | P2 | `005`, `007` | Fusion OCR et machine à états testées ; le format de montants par site est déclaré une seule fois (adaptateur) |
| Encodage/validation d'actions plateforme | Python | Rust | P2 | `005` | Contrat par site livré (`site_adapter.py` + `action_limits.py`) ; portage Rust des limites non engagé |
| Cache de spots | Python | Rust ou partagé | P2 | `007` | Clé versionnée, parité |

## À garder en Python

| Composant | Raison |
|---|---|
| Capture DXcam/WGC | API Windows, bindings natifs |
| Inférence YOLO/ONNX | Écosystème Python, GPU |
| Entraînement des modèles | Recherche, notebooks |
| Moteurs OCR (rapidocr/surya) | Dépendances lourdes, interfaces Python |
| API HTTP/asyncio | Intégration et observabilité |
| Contrats V2 partagés (`src/contracts/v2_contracts.py`) | Base de production unique depuis le 19/11/2026 (déplacé depuis `poker/decisionmaker/`) ; importé par le runtime, `research/` et le laboratoire ; aucune dépendance sortante |
| Interface opérateur | Itération rapide |
| Scripts de recherche | Reproductibilité scientifique |

## Règles

1. Toute nouvelle fonctionnalité chaude commence par une question de portage :
   peut-elle vivre en Rust sans bloquer la recherche ?
2. Un composant Python dans la boucle de décision doit avoir un budget de
   latence mesuré et une justification écrite.
3. Une migration sans test de parité n'est pas terminée.
4. Le registre est mis à jour dans la même pull request que le changement de
   comportement.
