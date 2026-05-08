# Plan Architecture V1 Consolide et Checklist Go-Live

## Objectif

Ce document fige le plan consolide pour la V1 du bot poker en production.

Perimetre V1:
- 1 site
- 1 theme
- 1 table
- multi-resolution adaptative
- template-first
- lecteurs specialises par champ
- politique conservatrice locale: check si possible, sinon fold
- capture systematique des incidents et near-misses
- architecture preparee pour multi-site et multi-table plus tard

Principe directeur:
- aucune donnee critique ne doit dependre d'une seule frame, d'une seule bbox, d'un seul moteur ou d'un seul score
- la verite doit venir de la geometrie, des lecteurs specialises, de la fusion des preuves, de la validation poker et de la stabilisation temporelle

## Contexte reel du code

## Avancement deja realise

Elements deja implementes dans cette branche de travail:
- `src/runtime/evidence_models.py` cree avec:
  - `FieldCriticality`
  - `FIELD_CRITICALITY`
  - `FieldCandidate`
  - `FieldEvidence`
  - `FrameQualityReport`
  - `CropQualityReport`
  - `RuntimeReadiness`
- `src/vision/site_adapter.py` cree avec:
  - `ThemeProfile`
  - `FormatProfile`
  - `SiteAdapterProtocol`
  - `PokerStarsAdapter`
  - `get_active_adapter(...)`
- `src/runtime/table_session.py` cree avec isolation logique mono-table
- `src/vision/frame_quality.py` cree avec `analyze_frame_quality(...)`
- `src/vision/crop_quality.py` cree avec `analyze_crop_quality(...)`
- `src/runtime/frame_pipeline.py` enrichi pour exposer:
  - `frame_quality`
  - `crop_quality` pour le pot
  - `visual_changed`
  - `visual_changed_regions`
  - `visual_refresh_due`
  dans `CanonicalTableState.metadata["vision"]`
- `src/main.py` enrichi avec une evaluation explicite de `fallback_execution_readiness`
  - calculee
  - stricte
  - visible dans `last_decision_summary`
  - non intrusive: aucun clic conservateur automatique active a ce stade
- chaine numerique V1 deja en place pour `pot` et `stacks`
  - `src/vision/numeric_preprocessing.py`
  - `src/vision/numeric_reader.py`
  - `src/vision/numeric_parser.py`
  - `src/vision/numeric_validator.py`
  - `src/vision/numeric_consensus.py`
  - integration `pot` dans `frame_pipeline.py`
  - integration `stack` dans `_read_player_stack` de `main.py`
  - metadata `numeric_reader` exposees dans le runtime
- geometrie et regions V1 deja en place
  - `src/vision/preset_registry.py`
  - `src/vision/table_geometry.py`
  - `src/vision/region_proposals.py`
  - lecture geometrique depuis le manifest PokerStars
  - `RegionResolver` minimal pour `pot`, `hero`, `actions`, `board`, `table`
  - metadata `runtime_geometry`, `region_proposals`, `region_resolutions` exposees dans le runtime
- `RuntimeReadiness` et `PokerStateValidator` deja branches en mode observation
  - `src/runtime/poker_state_validator.py`
  - `src/runtime/readiness.py`
  - validation et readiness calculees dans `_build_resolved_runtime_state`
  - exposition dans `last_decision_summary`, `runtime bridge state` et `runtime status`
  - integration progressive dans la logique assisted/conservative
  - aucun basculement brutal de la politique de clic live a ce stade
- capture structuree des incidents et near-misses deja amorcee
  - `src/vision/runtime_failure_dataset.py`
  - enregistrement JSONL dans `dataset/runtime_failures/incidents.jsonl`
  - incidents et near-misses enrichis avec `decision`, `tracker`, `canonical_spot`, `runtime_readiness`, `fallback_execution_readiness`
  - sauvegarde visuelle initiale de `frame` et crops critiques `pot`, `hero`, `actions`
- replay offline v1 deja disponible
  - `src/scripts/replay_runtime_failures.py`
  - filtres par `incident_id`, `category`, `severity`
  - export d'un bundle review JSON offline
- lecture et stabilisation de pseudo deja amorcees
  - `src/vision/player_name_reader.py`
  - `src/runtime/player_identity_state.py`
  - integration progressive dans le chemin principal de lecture des joueurs
  - metadata `name_ocr.identity_state` et `name_ocr.player_name_reader` exposees par joueur
- `Go-Live Gate` chiffree initiale deja amorcee
  - `src/runtime/go_live_gate.py`
  - evaluation v2 basee sur `decision_count`, `block_rate`, `fallback_rate`, `rolling_latency_ms`, `incident_count`
  - prise en compte de `runtime_readiness` et `poker_state_validation`
  - seuils configurables cote module
  - checks detailles par critere avec verdict `go` / `no_go`
  - exposition dans `runtime bridge state` et `runtime status`
  - verrouillage du mode live `ready` si la gate est `blocked`
- outillage shadow mode complete et valide en reel
  - `scripts/enable_shadow_mode.ps1`
  - `scripts/enable_shadow_mode.cmd`
  - `scripts/collect_shadow_mode_report.ps1`
  - `scripts/collect_shadow_mode_report.cmd`
  - port runtime corrige sur `8005`
  - verification reelle de `operator.status == shadow`
  - rapport filtre par `runtime.session_id` courant pour ne plus melanger les anciennes sessions
  - fallback propre si l'API runtime est indisponible
  - affichage explicite quand la session courante est propre mais sans payload `readiness` detaille
- qualification terrain recente deja realisee et correctifs appliques
  - `stale_frame` anciennement dominant n'apparait plus comme incident recent de la session courante dans le rapport filtre
  - le pot n'est plus degrade par `crop_blurry` dans les sessions recentes observees
  - les near-miss `runtime_readiness_not_fully_valid` ne sont plus enregistres pour les etats `idle`, `waiting_next_hand`, `sitting_out`, `observing_hand`
  - fallback OCR du pot sur la region `preset_geometry` si la region prioritaire est trop faible ou rejetee
  - throttling des enregistrements repetitifs `runtime_readiness_not_fully_valid` pour reduire la charge synchrone inutile

Tests deja ajoutes et passes:
- `tests/test_evidence_models.py`
- `tests/test_site_adapter_contract.py`
- `tests/test_table_session.py`
- `tests/test_frame_quality.py`
- extensions dans `tests/test_frame_pipeline.py`
- extensions dans `tests/test_main_decision_gate_replay.py`
- `tests/test_numeric_reader.py`
- `tests/test_numeric_parser.py`
- `tests/test_main_stack_numeric_reader.py`
- `tests/test_preset_registry.py`
- `tests/test_table_geometry.py`
- `tests/test_region_proposals.py`
- `tests/test_runtime_failure_dataset.py`
- `tests/test_player_name_reader.py`
- extensions supplementaires recentes dans `tests/test_main_decision_gate_replay.py`
  - conservation du near-miss sur vrai spot degrade
  - absence de near-miss pour etat `idle/observation`

Composants deja solides et reutilisables:
- `src/bot/runtime_types.py`: `CanonicalTableState`, `CanonicalPlayer`
- `src/bot/sanity_checker.py`: `SanityChecker`, `GateResult`, `GateReason`, `ActionIntent`
- `src/vision/detector.py`: `TemplateFallbackDetector`, presets, anchor/scale logic
- `src/runtime/frame_pipeline.py`: `_convert_state_for_tracker`, confiance calculee, spot_id
- `src/runtime/loop.py`: boucle live, debouncing OCR, historique et incidents
- `src/vision/temporal_ocr.py`: stabilisation partielle
- `src/runtime/player_name_resolver.py`: nettoyage et resolution des pseudos
- `src/vision/observation_dataset.py`: collecte runtime d'images et metadata
- `src/vision/ocr.py`: OCR multi-engine

Vrais gaps restants a combler:
- geometrie encore partiellement hardcodee hors zones deja migrees
- `RuntimeReadiness` pas encore consommee partout par la politique live finale
- capture visuelle enrichie encore partielle (frames + crops critiques seulement)
- pas encore de `Visual Replay Harness` complet base sur images/crops
- `PlayerNameReader` et `PlayerIdentityState` encore minimaux
- `PokerStateValidator` encore minimal
- `Go-Live Gate` encore non couplee a un passage live strict
- la lecture `readiness` de session propre reste aujourd'hui derivee du contexte rapport et pas d'un payload runtime dedie toujours present
- les gros blocs JSON du snapshot peuvent encore contenir de vieux incidents historiques, meme si le rapport utile filtre maintenant la session courante

## Architecture cible V1

La cible V1 est composee de:
- `SiteAdapter` + `ThemeProfile` + `FormatProfile`
- `TableSession`
- `FrameQualityReport` + `CropQualityReport`
- `TableGeometry` + `GeometryNormalizer`
- `RegionProposal` + `RegionResolver`
- `CardReader` + `CardConsensus`
- `NumericReader` + `NumericParser` + `NumericValidator` + `NumericConsensus`
- `PlayerNameReader` + `PlayerIdentityState`
- `FieldCandidate` + `FieldEvidence`
- `RuntimeReadiness`
- `PokerStateValidator`
- `FallbackExecutionReadiness`
- `NearMissTracker` + `RuntimeFailureDataset`
- `Visual Replay Harness`
- `Shadow Mode`
- `Go-Live Gate`

## Objets de donnees a introduire

Objets de base:
- `FieldCriticality`
- `FieldCandidate`
- `FieldEvidence`
- `FrameQualityReport`
- `CropQualityReport`
- `RuntimeReadiness`

Roles:
- `FieldCriticality`: classe un champ `CRITICAL`, `IMPORTANT`, `CONTEXTUAL`, `DECORATIVE`
- `FieldCandidate`: represente une lecture candidate issue d'un moteur, d'un crop ou d'un pretraitement
- `FieldEvidence`: represente la decision finale par champ avec candidats, gagnant, raisons de rejet, qualite de crop et score final
- `FrameQualityReport`: decrit la qualite globale de la frame
- `CropQualityReport`: decrit la qualite d'un crop selon le type de champ
- `RuntimeReadiness`: verite du runtime pour savoir si la table est actionnable, degradee, conservatrice ou bloquee localement

## Taxonomie des champs

### CRITICAL
- hero cards
- boutons d'action
- tour du heros
- coherence street/board
- fenetre cible
- frame fraiche
- localisation du bouton cible au moment du clic

### IMPORTANT
- pot
- stack heros
- stack adversaire principal
- dealer button si utile dans le contexte decisionnel
- etat des joueurs actifs/foldes

### CONTEXTUAL
- stacks secondaires
- pseudos si utilises pour profiling
- details visuels annexes

### DECORATIVE
- pseudos si non utilises par la decision
- elements chat/UI sans impact live

## Plan consolide en 4 phases

## Phase 1

But: poser les fondations structurelles, le bouclier d'execution, et les objets de verite.

### 1. Contrat V1
Definir officiellement:
- site V1
- theme V1
- resolutions supportees
- budget CPU/GPU
- champs critiques
- politique conservatrice
- criteres go-live

### 2. Evidence Models
Creer:
- `FieldCriticality`
- `FieldCandidate`
- `FieldEvidence`
- `FrameQualityReport`
- `CropQualityReport`
- `RuntimeReadiness`

Statut actuel:
- fait

### 3. Site Adapter
Creer une couche fine:
- `SiteAdapter`
- `ThemeProfile`
- `FormatProfile`

Le moteur interne reste le `TemplateFallbackDetector`.

Statut actuel:
- fait pour `PokerStarsAdapter`

### 4. TableSession
Creer `TableSession` meme en mono-table V1.

Elle doit contenir:
- fenetre
- adapter
- etat vision
- tracker
- etat temporel
- incidents
- readiness
- dernier etat valide

Statut actuel:
- fait comme conteneur logique de base

### 5. FallbackExecutionReadiness
Creer explicitement le garde-fou du fallback conservateur.

Avant d'executer `check sinon fold`, le systeme doit verifier:
- bonne fenetre
- focus/fenetre foreground confirmes
- frame fraiche
- tour heros confirme
- stabilite des boutons sur plusieurs frames
- bouton cible localise et stable
- action reellement legale
- absence de conflit critique sur la table

Statut actuel:
- fait cote evaluation
- calcule et expose dans `last_decision_summary["fallback_execution_readiness"]`
- pas encore branche en execution automatique `check/fold`

### 6. Politique de cooldown et deduplication d'incidents
Definir:
- deduplication d'incidents
- cooldown local
- regroupement par signature d'incident
- controle du volume de captures

Sortie attendue Phase 1:
- les objets de preuve existent
- `SiteAdapter` existe
- `TableSession` existe
- `FallbackExecutionReadiness` est defini
- le systeme sait representer proprement une lecture, un doute et une readiness locale

## Phase 2

But: refondre la vision et la confiance sans casser les consommateurs existants.

### 1. FrameQualityReport
Creer la mesure qualite globale des frames:
- blur
- contraste
- luminosite
- fraicheur
- score global
- motif de degradation

Statut actuel:
- fait
- branche dans `frame_pipeline.py`

### 2. CropQualityReport
Creer la mesure qualite des crops differente selon le type de champ:
- carte
- stack
- pot
- pseudo
- bouton

Statut actuel:
- fait
- branche pour le crop `pot`

### 3. PresetRegistry
Creer une couche explicite de gestion des presets/manifests.

### 4. Migration geometrique integrale
Creer:
- `TableGeometry`
- `GeometryNormalizer`

Objectif:
- remplacer les zones hardcodees
- normaliser la table dans un espace canonique
- supporter plusieurs resolutions et DPI

Point critique:
la migration doit inclure aussi la logique de:
- `visual_changed_regions`
- cache visuel
- visual previews
- collecte observation

### 5. RegionProposal + RegionResolver
Pour chaque champ important/critique:
- produire plusieurs bbox candidates
- scorer les hypotheses
- choisir la meilleure
- conserver les alternatives

### 6. Migration `state_confidence` vers `RuntimeReadiness`
`RuntimeReadiness` devient la source de verite interne.

Pendant la migration:
- il expose une projection scalaire temporaire `state_confidence`
- les anciens consommateurs continuent a fonctionner
- la suppression du float est differee

### 7. Durcissement du lecteur de cartes
Ne pas recreer le lecteur depuis zero. Extraire et durcir l'existant depuis `detector.py`.

Ajouter:
- `CardReader`
- `CardConsensus`

Etats recommandes:
- `tentative`
- `confirmed`
- `locked`
- `stale`
- `quarantined`

### 8. Chaine numerique specialisee
Creer:
- `NumericPreprocessing`
- `NumericReader`
- `NumericParser`
- `NumericValidator`
- `NumericConsensus`

Le pipeline doit faire:
- plusieurs pretraitements
- plusieurs lectures
- parsing strict
- validation poker-aware
- stabilisation temporelle

Statut actuel:
- fait pour `pot`
- fait pour `stacks`
- stabilisation temporelle numerique explicite introduite

Sortie attendue Phase 2:
- geometrie adaptative en place
- regionnement robuste
- `RuntimeReadiness` comme moteur interne
- lecteur cartes durci
- chaine numerique specialisee en place
- `visual_changed_regions` preserve

## Phase 3

But: creer une boucle de qualite terrain irreprochable et un environnement de replay/debug.

### 1. AnnotationPipelineHardening
Fiabiliser l'outil d'annotation avant d'en dependre.

Inclure:
- correction des dettes type `CLASS_MAP` vs `YOLO_CLASS_MAP`
- typage strict
- validation de sortie
- revue humaine sur les cas non surs

Politique recommandee:
- auto-validation seulement au-dessus d'un seuil tres eleve
- le reste passe en file de revue humaine

### 2. ProactiveTelemetry
Journaliser plus que les erreurs finales:
- candidats concurrents
- rejets
- quarantaines
- conflits
- latences
- decisions conservatrices
- sorties du validateur

### 3. NearMissTracker
Capturer les presque-erreurs, pas seulement les erreurs fatales.

Declencheurs typiques:
- conflit multi-candidats fort
- desaccord inter-moteurs
- quarantaine d'une region
- changement visuel rejete
- bascule en conservateur
- incoherence temporaire rattrapee

A capturer:
- frame N-1
- frame N
- frame N+1 si disponible
- crops critiques
- bbox candidates
- candidates de lecture
- decision finale
- reasons

Avec:
- deduplication
- cooldown
- signature d'incident

### 4. RuntimeFailureDataset
Formaliser le stockage:
- incidents critiques
- fallbacks conservateurs
- quarantaines
- near-misses

### 5. Visual Replay Harness
Creer un environnement offline qui:
- recharge un dossier de frames/crops
- rejoue la pipeline vision
- rejoue la logique de readiness
- reproduit les incidents
- compare les sorties attendues et observees

### 6. Joueur / Pseudos
Creer:
- `PlayerNameReader`
- `PlayerIdentityState`

### 7. Refactor `TableTracker`
Le tracker doit etre refactore en machine d'etats explicite, mais en absorbant l'existant.

### 8. PokerStateValidator
Agrege:
- cartes
- boutons
- tour heros
- pot
- stacks
- street
- transitions
- frame quality
- crop quality
- readiness locale

Classes recommandees:
- `fully_valid`
- `degraded_valid`
- `soft_invalid`
- `hard_invalid`

Sortie attendue Phase 3:
- pipeline d'annotation fiabilise
- incidents et near-misses captures proprement
- replay harness operationnel
- tracker refactore
- validateur poker structure

## Phase 4

But: valider, durcir, deployer proprement la V1.

### 1. Shadow Mode
Le bot tourne:
- observe
- construit les preuves
- evalue la readiness
- capture les incidents
- ne clique pas

### 2. Go-Live Gate chiffree
Avant tout clic reel, il faut une vraie gate quantitative.

A minima, definir:
- exactitude cartes sur spots actionnables
- exactitude boutons sur spots actionnables
- exactitude pot
- exactitude stacks
- taux de fallback conservateur
- latence p95
- taux d'incidents critiques par heure
- taux d'oscillation etat/readiness
- stabilite multi-resolution

### 3. Depreciation finale `state_confidence`
Une fois:
- `RuntimeReadiness` adopte partout
- shadow mode valide
- benchmarks valides

Alors seulement:
- suppression du float legacy
- nettoyage des consommateurs restants

### 4. Go Live V1
Activation des clics avec:
- `FallbackExecutionReadiness`
- politique locale `check si possible, sinon fold`
- capture systematique des incidents
- near-miss tracking actif

### 5. Validation terrain longue
Apres go-live V1, prevoir:
- sessions longues
- revue des incidents
- corrections ciblees
- enrichissement dataset

## Ordre d'implementation recommande

1. contrat V1
2. `Evidence Models`
3. `SiteAdapter` + `ThemeProfile` + `FormatProfile`
4. `TableSession`
5. `FallbackExecutionReadiness`
6. `FrameQualityReport`
7. `CropQualityReport`
8. `PresetRegistry`
9. `TableGeometry` + `GeometryNormalizer`
10. migration `visual_changed_regions`
11. `RegionProposal` + `RegionResolver`
12. `CardReader` + `CardConsensus`
13. `NumericPreprocessing`
14. `NumericReader`
15. `NumericParser`
16. `NumericValidator`
17. `NumericConsensus`
18. `RuntimeReadiness` avec projection legacy `state_confidence`
19. `AnnotationPipelineHardening`
20. `ProactiveTelemetry`
21. `NearMissTracker`
22. `RuntimeFailureDataset`
23. `Visual Replay Harness`
24. `PlayerNameReader`
25. `PlayerIdentityState`
26. refactor `TableTracker`
27. `PokerStateValidator`
28. `Shadow Mode`
29. `Go-Live Gate`
30. suppression finale de `state_confidence`
31. `Go Live V1`

## Checklist Go-Live V1

Cette checklist repond a la question: le bot est-il pret a cliquer en live en V1 ?

## A. Perimetre gele

### A1. Site V1 fige
- [ ] le site V1 est explicitement choisi
- [ ] le theme V1 est explicitement choisi
- [ ] la variante `play money` / `real money` est explicitement definie
- [ ] le `FormatProfile` des nombres est documente
- [ ] les manifests/presets du site V1 sont versionnes

### A2. Resolutions supportees figees
- [ ] la liste des resolutions/DPI supportes V1 est ecrite
- [ ] chaque resolution supportee a au moins un corpus de validation
- [ ] chaque resolution supportee a ete testee en replay visuel
- [ ] chaque resolution supportee a ete testee en shadow mode reel

### A3. Scope V1 assume
- [ ] mono-table uniquement
- [ ] pas de multi-site actif
- [ ] pas de multi-theme actif
- [ ] pas de generalisation implicite hors perimetre

## B. Fondations architecture

### B1. Objets de preuve presents
- [ ] `FieldCriticality` existe
- [ ] `FieldCandidate` existe
- [ ] `FieldEvidence` existe
- [ ] `FrameQualityReport` existe
- [ ] `CropQualityReport` existe
- [ ] `RuntimeReadiness` existe

### B2. Verite runtime unifiee
- [ ] `RuntimeReadiness` est la source de verite interne
- [ ] l'ancien `state_confidence` n'est plus qu'une projection de compatibilite
- [ ] il n'existe pas deux moteurs de confiance concurrents
- [ ] les logs runtime exposent la readiness finale et ses raisons

### B3. Isolation mono-table correcte
- [ ] `TableSession` existe
- [ ] l'etat runtime critique est isole par session
- [ ] le design n'introduit pas de dependance implicite au global state pour la vision live

## C. Vision et capture

### C1. Capture fenetre sure
- [ ] la fenetre cible est retrouvee de maniere deterministe
- [ ] la fenetre lobby n'est jamais selectionnee a la place de la table
- [ ] le `HWND` cible est correctement verrouille tant qu'il reste valide
- [ ] le systeme detecte la perte de fenetre
- [ ] le systeme detecte un changement de fenetre non prevu

### C2. Fraicheur de frame
- [ ] chaque frame possede un age mesure
- [ ] les frames trop anciennes sont classees non actionnables
- [ ] la politique de fallback conservateur ne s'appuie jamais sur une frame trop vieille

### C3. Qualite globale de frame
- [ ] blur mesure
- [ ] contraste mesure
- [ ] luminosite mesuree
- [ ] qualite globale calculee
- [ ] la qualite de frame est journalisee
- [ ] une frame de mauvaise qualite peut faire baisser la readiness

### C4. Cache visuel et detection de changement
- [ ] la migration geometrique n'a pas casse `visual_changed_regions`
- [ ] les regions `table`, `board`, `pot`, `hero`, `actions` sont toujours coherentes
- [ ] le cache visuel fonctionne toujours apres migration
- [ ] les captures observation ne sont pas regressees

## D. Geometrie et regions

### D1. Geometrie normalisee
- [ ] les zones ne reposent plus sur des pourcentages hardcodes seulement
- [ ] la table est normalisee dans un espace canonique
- [ ] l'echelle et l'origine sont calculees de maniere fiable
- [ ] la geometrie supporte toutes les resolutions V1

### D2. Regions candidates
- [ ] chaque champ critique a plusieurs hypotheses de bbox quand necessaire
- [ ] un `RegionResolver` choisit explicitement la bbox retenue
- [ ] la bbox retenue est tracee
- [ ] les bbox rejetees sont explicables

### D3. Qualite des crops
- [ ] chaque crop critique a un `CropQualityReport`
- [ ] la qualite crop bouton est mesuree
- [ ] la qualite crop cartes est mesuree
- [ ] la qualite crop pot/stack est mesuree
- [ ] un crop trop mauvais peut bloquer la readiness locale

## E. Lecteur cartes

### E1. Lecteur cartes durci
- [ ] le lecteur cartes a ete extrait/durci depuis l'existant
- [ ] il est `template-first`
- [ ] il ne depend pas d'un OCR texte
- [ ] les metadonnees de confiance sont exposees

### E2. Consensus cartes
- [ ] etats `tentative/confirmed/locked/stale/quarantined` ou equivalent
- [ ] une seule frame aberrante n'efface pas des cartes confirmees
- [ ] les transitions board/street impossibles sont rejetees
- [ ] hero cards non confirmees rendent l'action normale impossible

### E3. Bench cartes
- [ ] corpus cartes de test disponible
- [ ] benchmark cartes offline execute
- [ ] benchmark cartes sur spots actionnables execute
- [ ] metriques actionnables conformes au seuil V1

## F. Lecteur numerique pot / stacks

### F1. Chaine numerique specialisee presente
- [ ] `NumericPreprocessing` existe
- [ ] `NumericReader` existe
- [ ] `NumericParser` existe
- [ ] `NumericValidator` existe
- [ ] `NumericConsensus` existe

### F2. Pretraitements multiples
- [ ] plusieurs variantes de crop sont testees
- [ ] le lecteur ne depend pas d'une seule representation visuelle
- [ ] les candidats issus de pretraitements differents sont traces

### F3. Parsing metier
- [ ] le format des montants du site V1 est explicitement gere
- [ ] separateurs milliers et decimales sont geres correctement
- [ ] les formats ambigus sont rejetes
- [ ] les caracteres hors alphabet attendu sont rejetes

### F4. Validation poker-aware
- [ ] variations de pot coherentes
- [ ] variations de stack coherentes
- [ ] erreurs d'ordre de grandeur bloquees
- [ ] les valeurs aberrantes passent en quarantaine
- [ ] les valeurs confirmees ne sont pas remplacees trop vite

### F5. Bench pot/stacks
- [ ] corpus pot/stacks de test disponible
- [ ] benchmark offline execute
- [ ] benchmark sur spots actionnables execute
- [ ] metriques actionnables conformes au seuil V1

## G. Boutons et tour de Hero

### G1. Detection boutons fiable
- [ ] les boutons d'action sont detectes de maniere stable
- [ ] les faux positifs de layout sont mesures
- [ ] la localisation du bouton cible est stable sur plusieurs frames
- [ ] l'existence du bouton est croisee avec les `legal_actions`

### G2. Tour du heros
- [ ] le systeme confirme explicitement que c'est le tour du heros
- [ ] le fallback conservateur ne se declenche jamais sans cette preuve
- [ ] les cas `layout ambigu` sont classes non actionnables

### G3. FallbackExecutionReadiness
- [ ] la readiness specifique du fallback existe
- [ ] `check/fold` n'est pas clique si la fenetre n'est pas sure
- [ ] `check/fold` n'est pas clique si le bouton n'est pas sur
- [ ] `check/fold` n'est pas clique si le tour du heros n'est pas confirme
- [ ] `check/fold` n'est pas clique si la frame est trop vieille
- [ ] `check/fold` n'est pas clique si l'etat est contradictoire

## H. Tracker et validation metier

### H1. Tracker deterministe
- [ ] le refactor du tracker absorbe l'existant, sans doublon de state machine
- [ ] les transitions de street sont explicites
- [ ] les resets de main sont explicites
- [ ] les transitions illegales sont detectees

### H2. Validateur poker
- [ ] `PokerStateValidator` existe
- [ ] il classe l'etat en `fully_valid / degraded_valid / soft_invalid / hard_invalid`
- [ ] il agrege cartes, pot, stacks, boutons, tour heros, frame quality
- [ ] un etat incoherent n'est jamais traite comme actionnable

### H3. Politique de readiness
- [ ] `RuntimeReadiness` contient une classe decisionnelle claire
- [ ] le runtime distingue `actionable`, `conservative`, `blocked local`
- [ ] la raison detaillee est toujours disponible

## I. Incidents, near-misses, telemetrie

### I1. Telemetrie structuree
- [ ] les candidats de lecture sont logges
- [ ] les rejets sont logges
- [ ] les latences sont loggees
- [ ] les incidents sont logges
- [ ] les metriques runtime sont visibles via l'API

Surfaces deja presentes a alimenter:
- `/runtime-snapshot`
- `/runtime-observation`
- `/runtime-history`
- `/runtime-history/export`
- `/runtime-observation/export`

### I2. RuntimeFailureDataset
- [ ] les incidents critiques sont sauvegardes
- [ ] les fallbacks conservateurs sont sauvegardes
- [ ] les crops critiques sont sauvegardes
- [ ] la decision finale est sauvegardee
- [ ] le contexte table est sauvegarde

### I3. NearMissTracker
- [ ] les presque-erreurs sont capturees
- [ ] les conflits multi-candidats sont captures
- [ ] les quarantaines sont capturees
- [ ] les desaccords moteurs sont captures
- [ ] les incidents sont dedupliques
- [ ] un cooldown local evite les avalanches de logs identiques

## J. Annotation et datasets

### J1. Outil d'annotation fiabilise
- [ ] les dettes connues de l'annotateur sont corrigees
- [ ] les mappings de classes sont coherents
- [ ] les sorties invalides sont rejetees
- [ ] la chaine d'annotation n'introduit pas de bruit massif

### J2. Human-in-the-loop annotation
- [ ] les labels critiques douteux ne sont jamais auto-valides
- [ ] il existe une file de revue humaine
- [ ] les cas critiques sont relus
- [ ] les datasets V1 ne contiennent pas de labels incertains en vrac

### J3. Datasets versionnes
- [ ] corpus cartes versionne
- [ ] corpus pot/stacks versionne
- [ ] corpus boutons versionne
- [ ] corpus incidents versionne
- [ ] corpus near-misses versionne

## K. Visual Replay Harness

### K1. Harness offline pret
- [ ] on peut rejouer des frames offline
- [ ] on peut rejouer des incidents captures
- [ ] on peut rejouer les near-misses
- [ ] on peut inspecter les sorties par champ
- [ ] on peut comparer resultat attendu vs observe

### K2. Corpus de replay
- [ ] corpus `golden`
- [ ] corpus `hard cases`
- [ ] corpus `fallback conservative`
- [ ] corpus multi-resolution
- [ ] corpus transitions de main

## L. Shadow Mode

Voir aussi:
- `doc/SHADOW_MODE_PROCEDURE.md`

### L1. Shadow mode complet
- [ ] le bot tourne sans cliquer
- [ ] la readiness est calculee comme en live
- [ ] la politique conservatrice est simulee/loggee
- [ ] les incidents sont captures
- [ ] les metriques sont persistées

### L2. Sessions longues
- [ ] au moins une session longue de validation est realisee
- [ ] stabilite metrique observee dans le temps
- [ ] pas d'explosion de logs/incidents
- [ ] pas de derive memoire/CPU significative

## M. Go-Live Gate chiffree

### M1. Metriques minimales a definir
- [ ] exactitude hero cards sur spots actionnables
- [ ] exactitude board sur spots actionnables
- [ ] exactitude boutons sur spots actionnables
- [ ] exactitude pot
- [ ] exactitude hero stack
- [ ] exactitude main villain stack
- [x] taux de fallback conservateur
- [x] latence p95 pipeline
- [x] taux d'incidents critiques par heure
- [x] taux d'oscillation readiness
- [ ] stabilite multi-resolution

### M2. Seuils ecrits
- [x] chaque metrique a un seuil minimal explicite
- [ ] chaque seuil est valide sur benchmark offline
- [ ] chaque seuil est valide sur shadow mode reel
- [x] le go-live est bloque si un seuil n'est pas atteint

## N. Go Live

### N1. Conditions avant clic live
- [ ] `RuntimeReadiness` est la verite interne
- [ ] `FallbackExecutionReadiness` est actif
- [ ] la politique `check si possible, sinon fold` est branchee
- [ ] la fenetre cible est securisee
- [ ] les incidents sont captures
- [ ] le near-miss tracking est actif
- [ ] les metriques go-live sont validees

### N2. Deploiement prudent
- [ ] activation progressive
- [ ] surveillance active des incidents
- [ ] export regulier de l'historique runtime
- [ ] revue humaine des premiers incidents live

## O. Post Go-Live

### O1. Depreciation finale
- [ ] suppression finale de `state_confidence` float legacy
- [ ] suppression des vieux chemins de confiance concurrents
- [ ] nettoyage des adaptateurs temporaires

### O2. Boucle d'amelioration
- [ ] les incidents live alimentent les datasets
- [ ] les near-misses alimentent les corpus hard cases
- [ ] le replay harness est utilise avant chaque amelioration importante
- [ ] les seuils go-live sont revalides a chaque evolution majeure

## Go / No-Go final

Le bot V1 est `Go` seulement si:
- [ ] toutes les sections A a N sont satisfaites
- [ ] aucun point critique non traite ne reste ouvert
- [ ] la politique fallback est sure
- [ ] la chaine numerique est fiable
- [ ] le replay harness confirme les cas durs
- [ ] le shadow mode long est propre
- [ ] les seuils go-live sont atteints

Sinon: `No-Go`.

## Ce qui ferait passer cette checklist au niveau industriel

Pour aller vers un niveau industriel encore plus eleve, ajouter:
- oracle differe non visuel, si disponible
- safety envelope formel
- budget de calcul explicite
- tests de chaos vision
- corpus gold standard versionne en CI
