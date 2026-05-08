# Procedure Shadow Mode V1

## Objectif

Cette procedure sert a valider la V1 en conditions reelles sans autoriser de clic live autonome.

Le shadow mode doit permettre de verifier:
- la stabilite du runtime
- la qualite de `RuntimeReadiness`
- la qualite de `FallbackExecutionReadiness`
- le comportement de la `Go-Live Gate`
- la qualite des incidents et near-misses captures
- la disponibilite des artefacts visuels et du replay offline

Le principe est simple:
- le bot tourne
- il observe
- il calcule tout comme en live
- il n'execute pas de clic live autonome
- il journalise et capture les ecarts

## Prerequis

Avant de lancer une session shadow mode:
- verifier que le site V1 et le theme V1 sont bien ceux attendus
- verifier que la table cible est unique
- verifier que l'API runtime repond
- verifier que `dataset/runtime_failures/` est accessible en ecriture
- verifier que l'historique runtime est actif

Verifier les fichiers et dossiers:
- `config.json`
- `dataset/runtime_failures/`
- `log/`

Verifier les endpoints utiles:
- `GET http://127.0.0.1:8005/runtime-snapshot`
- `GET http://127.0.0.1:8005/runtime-history`
- `GET http://127.0.0.1:8005/runtime-history/export`
- `POST http://127.0.0.1:8005/bot-cockpit/operator`

## Configuration recommandeee

Pour une session shadow mode V1:
- `shadow_mode_enabled = true`
- `assisted_mode_enabled = false`
- `manual_override_enabled = false`
- `observation_mode_enabled = false`
- `paused = false`

Le mode effectif attendu est:
- `operator.status = shadow`

## Activation

Envoyer un patch operateur vers:
- `POST /bot-cockpit/operator`

Payload conseille:

```json
{
  "operator": {
    "shadow_mode_enabled": true,
    "assisted_mode_enabled": false,
    "observation_mode_enabled": false,
    "manual_override_enabled": false,
    "paused": false
  }
}
```

Un script PowerShell est disponible pour automatiser cette bascule:
- `scripts/enable_shadow_mode.ps1`

Et un lanceur double-clic Windows est disponible:
- `scripts/enable_shadow_mode.cmd`

Exemple:

```powershell
powershell -ExecutionPolicy Bypass -File "scripts/enable_shadow_mode.ps1"
```

Verifier ensuite dans `GET /runtime-snapshot`:
- `operator.status == "shadow"`
- `go_live_gate` present
- `readiness` presente
- `decision` present

## Duree recommandee

Faire au minimum:
- session courte: 10 a 15 minutes
- session moyenne: 30 minutes
- session longue: 60 a 120 minutes

Ordre recommande:
1. session courte pour verifier que tout remonte
2. session moyenne pour verifier les taux de blocage/fallback
3. session longue pour verifier la stabilite memoire/CPU et la qualite des incidents

## Ce qu'il faut surveiller en temps reel

### 1. Etat operateur
Dans `runtime-snapshot`:
- `operator.status`
- `operator.go_live_gate`

Attendu:
- `shadow`
- jamais `ready` en shadow mode

### 2. Runtime readiness
Dans `runtime-snapshot` et `runtime-status`:
- `readiness.state`
- `readiness.score`
- `readiness.reasons`

Attendu:
- alternance plausible entre `actionable`, `conservative`, `blocked_local`
- pas d'oscillation absurde a chaque frame

Signaux d'alerte:
- readiness presque toujours `blocked_local`
- readiness oscillante sans changement de scene
- score tres faible en permanence

### 3. Fallback execution readiness
Dans `decision.fallback_execution_readiness`:
- `status`
- `recommended_action`
- `reasons`

Attendu:
- cohérent avec l'etat de la table
- pas de `ready` dans des spots manifestement ambigus

### 4. Go-Live Gate
Dans `go_live_gate`:
- `status`
- `verdict`
- `reasons`
- `checks`

Attendu:
- en debut de session: souvent `blocked`
- apres accumulation d'echantillons: amelioration possible

Signaux d'alerte:
- `latency_too_high`
- `incident_count_too_high`
- `readiness_state_not_actionable`
- `validation_state_invalid`

### 5. Incidents / near-misses
Dans:
- `GET /runtime-history?kind=incidents`
- `dataset/runtime_failures/incidents.jsonl`

Attendu:
- incidents comprehensibles
- categories exploitables
- artefacts visuels disponibles quand presents

Signaux d'alerte:
- avalanche du meme incident
- incidents vides/inexploitables
- trop de `runtime_readiness_not_fully_valid`

## Ce qu'il faut exporter apres chaque session

### Export runtime history
Utiliser:
- `GET /runtime-history/export`

### Export incidents dataset
Conserver:
- `dataset/runtime_failures/incidents.jsonl`
- `dataset/runtime_failures/images/`
- `dataset/runtime_failures/crops/`

### Export review bundle
Utiliser le replay offline pour generer un bundle review si necessaire.

### Rapport shadow mode automatique
Un script PowerShell est disponible:
- `scripts/collect_shadow_mode_report.ps1`

Et un lanceur double-clic Windows est disponible:
- `scripts/collect_shadow_mode_report.cmd`

Exemple:

```powershell
powershell -ExecutionPolicy Bypass -File "scripts/collect_shadow_mode_report.ps1"
```

Le rapport est ecrit par defaut dans:
- `log/shadow_mode_report.md`

Comportement actuel du rapport:
- le rapport filtre les incidents sur la `runtime.session_id` courante
- les sections utiles pour juger la session actuelle sont:
  - `## Recent Incidents From API`
  - `## Recent Incidents JSONL`
- des incidents anciens peuvent encore apparaitre dans des blocs JSON embarques du snapshot brut; ils ne doivent pas etre interpretes comme des incidents de la session courante
- si la session courante est propre et n'a emis aucun payload `readiness` detaille, le rapport affiche explicitement:
  - `readiness.state: unavailable`
  - `readiness.score: n/a`
  - et une section `## Readiness` expliquant que la session courante est propre mais sans payload detaille exploitable

## Analyse minimale apres session

Apres une session shadow mode, verifier:

1. `go_live_gate.reasons`
- quelles raisons bloquent le plus souvent

2. `readiness.state`
- proportion de `actionable`
- proportion de `conservative`
- proportion de `blocked_local`

3. incidents dominants
- quels `incident_id` reviennent le plus

4. artefacts visuels
- les frames et crops sont-ils presents et lisibles

5. latence
- `rolling_latency_ms`
- eventuelles lenteurs anormales

## Critere de succes d'une session shadow mode

Une session shadow mode est exploitable si:
- le bot ne clique pas
- les snapshots runtime restent coherents
- les incidents sont capturables et lisibles
- la Go-Live Gate produit un verdict comprehensible
- les artefacts visuels sont bien enregistrés

## Critere de no-go immediate

Arreter la qualification et corriger avant de continuer si:
- le runtime devient instable
- la capture des incidents est vide ou corrompue
- les artefacts visuels sont absents
- la readiness est incoherente quasi en permanence
- la latence explose durablement
- les memes incidents se repetent massivement sans signal utile

## Procedure concrete recommandee

### Etape 1
Mettre le bot en `shadow` via `POST /bot-cockpit/operator`.

### Etape 2
Verifier dans `GET /runtime-snapshot`:
- `operator.status == shadow`
- `go_live_gate` present
- `runtime.session_id` presente

Note pratique:
- l'absence de payload `readiness` detaille sur une session propre et idle n'est pas un incident en soi
- dans ce cas, utiliser le rapport genere pour verifier que la session courante est propre et que les incidents recents sont vides

### Etape 3
Laisser tourner 10 a 15 minutes.

### Etape 4
Verifier:
- `GET /runtime-history?kind=incidents`
- `dataset/runtime_failures/incidents.jsonl`
- verifier les sections du rapport filtrees par session courante avant d'interpreter un incident ancien

### Etape 5
Verifier qu'il existe:
- des incidents ou near-misses exploitables
- des frames/crops quand necessaire

### Etape 6
Lancer une session 30 a 60 minutes.

### Etape 7
Exporter:
- runtime history
- incidents JSONL
- review bundle si besoin
- rapport shadow mode automatique

### Etape 8
Classer les causes principales:
- gate
- readiness
- numeric
- boutons
- geometrie
- pseudos

Important:
- ne pas classer comme probleme actif un `stale_frame` ou un `crop_blurry` vu seulement dans un bloc historique embarque si `## Recent Incidents From API` et `## Recent Incidents JSONL` sont propres pour la session courante

### Etape 9
Corriger uniquement les 1 ou 2 causes dominantes.

### Etape 10
Relancer une nouvelle session shadow mode.

## Regle de decision

Ne pas passer en live autonome tant que:
- les raisons de gate `blocked` ne sont pas comprises
- les incidents dominants n'ont pas ete traites
- les seuils shadow mode ne sont pas stabilises

Le shadow mode n'est pas un simple mode d'attente.
Il doit servir a:
- mesurer
- qualifier
- corriger
- requalifier

## Livrables a conserver apres chaque campagne

- export runtime history
- incidents JSONL
- artefacts images/crops
- review bundle
- note manuelle de synthese:
  - duree
  - site/theme
  - resolution
  - principales raisons de gate
  - incidents dominants
  - correctifs proposes
