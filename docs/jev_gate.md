# JevGate — second avis via Jev (proxy :4000 `/v1/systemone`)

Second avis calibré branché **après** le gate heuristique (`src/bot/gate_flow.py`).
Jev ne voit que du **texte** (phrase d'état), jamais d'image/screenshot.
POC offline d'abord ; jamais dans le solveur GTO ni en live argent réel sans session papier.

## Wire format (validé le 2026-09-22, campagne T1–T6 — ne pas modifier sans retester)

- Endpoint : `POST http://127.0.0.1:4000/v1/systemone`
- Header : `Content-Type: application/json` seul (pas d'auth côté client).
- Body : `{"model": "jev-1.13-free", "state": <string>, "questions": {...}}`
  - `state` **DOIT être une string** (objet → `400 missing required field: 'state' (string)`).
  - Types autorisés : **`noul` / `choice` / `score` uniquement** (`boolean`, `text` → `400`).
  - `model` **requis** (absent → `404` ; dispos : `jev-1.13`, `jev-1.13-free`).
  - `choice` exige `criteria` **objet** ; `score` exige `criteria` **array**.
- Réponse : `{model, answers: {go: {noul}, tier: {choice, confidence}, risky: {noul},
  effort: {score, confidence}}, usage, cost}`. Champs absents → `None`, jamais d'exception.
- Modèle : **`jev-1.13-free` uniquement** (anonyme, `cost: "0"`).
  `jev-1.13` (payant, pool Zen) → `402 Insufficient account funds` constaté le 2026-09-22.

Set de questions poker (`build_questions()`, cf. `src/bot/jev_gate.py`) :

| id | type | rôle |
|----|------|------|
| `go` | noul | État table complet et cohérent (héros, pot, boutons visibles et lisibles) |
| `tier` | choice fast/balanced/deep | Lecture mécanique / analyse de street / état incohérent |
| `risky` | noul | Clic = argent réel engagé sur état incertain (> 0.7 → escalade forcée) |
| `effort` | score 0..3 | Niveau de revue nécessaire (`["almost none","some","a lot","as much as possible"]`) |

## Configuration

Bloc `bot.jev_gate` de `config.json` (voir `config.example.json`), puis env, puis overrides.
Précédence : **overrides > env > fichier**.

| clé / env | défaut | effet |
|-----------|--------|-------|
| `mode` / `POKER_JEV_MODE` | `observer` | `observer` (log accord/désaccord, ne change rien) · `enforcing` (peut bloquer un go heuristique) · `off` (zéro appel) |
| `model` / `POKER_JEV_MODEL` | `jev-1.13-free` | Ne pas passer au payant sans provisionner le pool |
| `timeout_s` / `POKER_JEV_TIMEOUT_S` | `0.8` | Timeout strict ; dépassement → fail-open (heuristique gardée) |
| `base_url` / `POKER_JEV_BASE_URL` | `http://127.0.0.1:4000` | Proxy local OpenCode adapté Jev |

Mode inconnu → repli `observer` (warning loggué). **Jamais de clé en dur**
(le free n'en demande pas ; cf. règle sécurité).

## Options déploiement / backend / multimodal (étape 1 : parsing seul, zéro réseau)

Tout est optionnel dans `bot.jev_gate` (voir `config.example.json`) ; défauts =
comportement actuel. Précédence inchangée : **overrides > env > fichier**.
La logique live (`decide`/`query`/`apply_policy`, wire format) est **intouchée**.

| clé / env | défaut | effet |
|-----------|--------|-------|
| `deployment` / `POKER_JEV_DEPLOYMENT` | `single` | `single` (tout sur TABLE-WIN) · `dual` (TABLE-WIN → SRV-LINUX via `lan`, repli `single` si `lan.base_url` vide) |
| `backend` / `POKER_JEV_BACKEND` | `cloud` | `cloud` (Jev actuel) · `local` (clone LLM2Jev sur JUG) · `auto` (choix ultérieur, Phase 3+) |
| `min_upgrade_confidence` / `POKER_JEV_MIN_UPGRADE` | `0.3` | Bar basse de blocage (exposée en option, valeur live inchangée) |
| `min_downgrade_confidence` / `POKER_JEV_MIN_DOWNGRADE` | `0.6` | Bar haute garde-fou tier (exposée en option, valeur live inchangée) |
| `risky_threshold` / `POKER_JEV_RISKY` | `0.7` | Seuil escalade forcée (exposé en option, valeur live inchangée) |
| `lan.base_url` / `POKER_JEV_LAN_URL` | `""` | URL serveur JUG (ex. `http://192.168.1.10:30000`), vide = pas de LAN |
| `lan.model` / `POKER_JEV_LAN_MODEL` | `qwen2.5-vl-3b` | Modèle local cible (parsing seul) |
| `lan.timeout_text_s` / `POKER_JEV_LAN_TIMEOUT_TEXT_S` | `1.0` | Timeout requêtes texte vers JUG (parsing seul) |
| `lan.timeout_image_s` / `POKER_JEV_LAN_TIMEOUT_IMAGE_S` | `15.0` | Timeout requêtes image offline vers JUG (parsing seul) |
| `lan.api_key_env` / `POKER_JEV_LAN_KEY_ENV` | `POKER_JEV_LAN_KEY` | **Nom** de la var d'env portant la clé LAN — jamais la valeur, jamais en dur |
| `multimodal.mode` / `POKER_JEV_MULTIMODAL` | `text_only` | `text_only` (actuel) · `crops_offline` (batch offline, Phase 3+) · `crops_live` **verrouillé** (repli `text_only` + warning tant que Phase 3 non validée) |
| `multimodal.max_images` / — | `3` | Clampé 1–8 (parsing seul) |
| `multimodal.crop_size_px` / — | `160` | Taille crops (parsing seul) |
| `multimodal.jpeg_quality` / — | `80` | Qualité JPEG crops (parsing seul) |
| `usages.<nom>.enabled` / — | `true` | Interrupteur par usage existant (`autolabel`, `judge`, `report`, `attention`, `tier_budget`, `drift`) ; non listé = actif ; inconnu = inactif |
| `usages.<nom>.timeout_s` / — | `15.0` | Timeout batch offline par usage (parsing seul) |

Valeurs inconnues (`deployment`, `backend`, `multimodal.mode`) → repli sûr
(`single` / `cloud` / `text_only`, warning loggué). Aucun appel réseau ajouté :
`query()` utilise toujours `base_url`/`model`/`timeout_s` historiques.

## Politique (transposée de `.claude/skills/jev-model-router/hooks/policy.ts`)

- `min_upgrade_confidence = 0.3` : bar basse pour **bloquer** (bloquer coûte peu).
- `min_downgrade_confidence = 0.6` : bar haute pour assouplir (jamais utilisée seule).
- `risky > 0.7` : escalade forcée, quel que soit le reste.
- **Asymétrie** : Jev peut bloquer un « go » heuristique, mais ne peut **jamais**
  forcer un « go » si l'heuristique bloque. Sans confiance mesurée → heuristique gardée.
- **Garde-fou tier** (correctif 2026-09-23) : si Jev déclare lui-même l'état lisible
  (`tier` fast/balanced) mais que P(!go) atteint la bar basse 0.3, les signaux se
  contredisent → blocage exigé seulement à la **bar haute 0.6**. La bar basse 0.3
  ne s'applique que si `tier` = deep ou absent. `risky > 0.7` reste une escalade
  forcée, quel que soit le tier. Sweep : 3/12 faux blocs (0.25) → 0/12 attendu
  (les 3 spots bloqués à tort avaient tier fast + conf 0.33–0.59 < 0.6).
- **Fail-open** : timeout, proxy down, réponse malformée → `verdict None`,
  décision heuristique inchangée. Jev ne casse jamais le gate (`try/except` global
  dans `gate_flow.py` + `JEV_INCOHERENT_STATE` préservant `action_intent`/`confidence`).

## Gate IA unifiée — `bot.ai_gate` (Jev legacy + Djev officiel)

Routeur unique validé contre `docs/ai_gate.schema.json`
(trois normaliseurs : Python `src/bot/ai_router.py`, TS
`website/src/lib/aiGateConfig.ts`, Rust `website/src-tauri/src/lib.rs`).
`bot.jev_gate` reste un **alias compat** (miroir du bloc `jev`, ne pas étendre :
toute nouveauté va dans `ai_gate`). Fail-open strict partout.

| clé / env | défaut (lock LAN/Offline strict) | effet |
|-----------|------------------------------|-------|
| `provider` | `jev` | Lock : proxy local gratuit sans clé, cloud **désactivé par choix** (jamais proposé) ; `auto` = LAN Djev prioritaire si offline, cloud Djev si clé présente, sinon Jev proxy `:4000`, sinon fail-open |
| `offline_mode` / `POKER_OFFLINE_MODE` | `true` | Lock : loopback uniquement (`127.0.0.1`/`localhost`/`::1`), **JAMAIS d'egress WAN** (fallbacks cloud tombés, Djev marqué offline, base Jev non-loopback rebasculée sur le proxy loopback) |
| `cloud_fallback` / `POKER_DJEV_CLOUD_FALLBACK` | `false` | Lock : cloud désactivé par choix (forcé `false` si `offline_mode`) |
| `djev.base_url` / `POKER_DJEV_BASE_URL` | `http://127.0.0.1:4000` | Lock LAN : proxy local gratuit sans clé (cloud officiel `https://api.typesafe.ai/v1/systemone` documenté mais non appelé en offline) |
| `djev.cloud_url` / `POKER_DJEV_CLOUD_URL` | `https://api.typesafe.ai/v1/systemone` | URL cloud officielle |
| `djev.lan_url` / `POKER_DJEV_LAN_URL` | `http://127.0.0.1:4000` | URL LAN prioritaire (sonde santé loopback uniquement, 250 ms, jamais bloquante) |
| `djev.model` | `jev-1.13.0` | Version pinée (`jev-latest`/`jev-preview` = alias mouvants, NE PAS utiliser avec des seuils tunés) |
| `djev.api_key_env` | `TYPESAFE_API_KEY` | **Nom** de la variable d'environnement portant la clé — jamais la valeur, jamais en dur |
| `djev.timeout_s` | `5.0` | Timeout requêtes Djev (plancher 0.5 s, plafond 60 s) |
| `djev.mode` | `observer` | `observer` / `enforcing` / `off` (même asymétrie que Jev : peut bloquer un go, jamais forcer) |
| `djev.min_upgrade_confidence` / `min_downgrade_confidence` / `risky_threshold` | `0.3` / `0.6` / `0.7` | Seuils par risque Djev (mêmes bornes 0–1 que Jev) |

Zéro réseau effectif côté config : la sonde santé LAN au `set` est un ping
TCP loopback borné (250 ms, échec silencieux, jamais bloquant) ;
`offline_mode=true` + URL morte `http://127.0.0.1:9` ⇒ aucun egress WAN.
Zéro clé en dur : `TYPESAFE_API_KEY` = nom seul, jamais la valeur.

## Validation (2026-09-22, proxy live, modèle free, coût 0)

- `scripts/eval_jev_gate.py --mode observer --limit 50` : accord 49/49 = 1.00,
  p50 532 ms, p95 718 ms (budget 800 ms OK), 1 fail-open, coûts `['0']`.
- `--mode enforcing --limit 50` : accord 47/47 = 1.00, p50 516 ms, p95 688 ms,
  3 fail-open (TimeoutError ~800 ms, heuristique gardée).
- `tests/test_jev_gate.py` : 15 tests mockés (wire format, politique + garde-fou tier, fail-open, modes).
- `pytest tests/test_jev_gate.py tests/test_main_decision_gate_replay.py` : 72 verts.

## Extension — 6 usages Jev (2026-09-23, implémenté, live observer validé coût 0)

Offline d'abord (aucun effet live), live en observer uniquement.

| # | usage | module | réseau live ? |
|---|-------|--------|---------------|
| 1 | Autolabel incidents (cause + sévérité) | `scripts/jev_autolabel_incidents.py` | non (offline, `--limit/--out`, corpus source jamais modifié) |
| 2 | Juge de sessions papier (A vs B) | `scripts/jev_judge_sessions.py` (`--a/--b`, `--batch-a/--batch-b/--store`) | non (offline, lit `RuntimeHistoryStore.export_records/batches` incl. `.bak`) |
| 3 | Rapports de session en langage naturel | chat gratuit (`muse-spark-1.3-contributor-free` via `/v1/chat/completions`, texte résumé offline uniquement) | hors boucle live |
| 4 | Routeur d'attention multi-tables | `src/bot/jev_attention.py` (`suggest_attention_order`) | lecture seule, tie-break ex-aequo `OUR_TURN` uniquement, zéro appel si < 2 ex-aequo ou top < `OUR_TURN` ou `off` ; jamais de clic, jamais de `signal_provider` |
| 5 | Budget solveur piloté par tier | `DecisionMaker._apply_jev_tier_budget` (fast 400 / balanced = base / deep 2500 ms, clamp 256–9000, budget seul jamais logique GTO), branché via `jev_tier` du flow précédent dans `gate_flow.py` | zéro appel supplémentaire (réutilise la décision du gate) |
| 6 | Détecteur de drift temporel | `src/bot/jev_drift.py` (`detect_drift` 5 règles pures + `confirm_with_jev` tier deep ou risky > 0.7 + `observer_drift_check` zéro appel) ; hook consultatif dans `gate_flow.py` (`summary["drift"]` + event `drift_pause_advised`, jamais de blocage) | zéro appel supplémentaire |

Validation live (proxy :4000, `jev-1.13-free`, coût `"0"`, aveugle seed 11, 26/26 plausibles) :
stale 6/6 (`stale_frame` ~0.95, sev ~1.57) ; loop 8/8 (`loop_error` ~0.88, sev ~1.87) ;
vision 6-8/8 (`vision_degraded` 0.85-0.98, sev ~1.37) ;
readiness 8/8 plausibles — STRUCT (héros présent/absent, 13 % du corpus) →
`state_incoherent` ~0.98, IDLE cohérents → `conservative_block`, pot flou →
`vision_degraded`. Leçon : 78 % des readiness n'ont qu'un micro-écart float
(0.333 vs 0.25) → signalé `confidence drift (minor)`, jamais `DIVERGE`.
Juge (même campagne, `POKER_JEV_TIMEOUT_S=30`) : paires identiques → `tie`
conf 1.0 (`b_healthier` 0.09-0.10) ; paires contrastées (batch 0 incident vs
batch 2 incidents) → verdict correct des deux côtés (`a` conf 1.0 /
`b_healthier` 0.03 quand le propre est en A, `b` conf 1.0 / `b_healthier` 0.93
quand il est en B — pas de biais de position).
Observer live (meme campagne, `POKER_JEV_TIMEOUT_S=30`, cout `"0"` mesure) :
attention 2 tables ex-aequo OUR_TURN (alpha lisible pot 150 conf 0.9 vs beta
floue pot unreadable conf 0.2) -> pick beta d'abord (`['beta','alpha']`,
avis seul, zero clic) ; drift synthetique street FLOP fixe board 2->3 pot
100->150 -> `street_stalled` detecte pur, confirme live tier deep +
risky 0.78 -> pause conseillee, wrapper `observer_drift_check` consultatif
sans appel supplementaire ; budgets tier verifies fast 400 / balanced base /
deep 2500 ms (clamp 256-9000, zero appel, reutilise la decision du gate).
Rapports (chat gratuit `muse-spark-1.3-contributor-free` via
`/v1/chat/completions`, timeout 60 s, offline) : batch 2 propre (0 incident)
-> « session saine, aucune anomalie » sans hallucination ; batch 0 (2
`vision_quality_degraded`) -> pointe exactement les 2 degradations vision et
recommande de controler la chaine capture. Factuel des deux cotes.
Detail : le juge et l'autolabel timeoutent à 0.8 s sur états lourds →
`POKER_JEV_TIMEOUT_S=8..30` en batch offline (fail-open sinon, `unknown`, jamais d'erreur).

toujours non touchés.

Tests : `tests/test_jev_expansion.py` (20 tests mockés : autolabel, juge,
attention, budgets tier, drift/détection/observer) + `tests/test_jev_gate.py`
(17 : + `test_policy_boundary_partial_degradation_blocks_on_risky` figeant la
strictness frontière — 5 cas risky-forcé + 1 blocage confiant) → 37 verts
(+ 78 replay gate : 76 existants + 2 câblage live
`test_jev_enforcing_blocks_incoherent_go_without_network` et
`test_jev_off_makes_no_call_in_live_flow`, mock `jev_decide` zéro réseau —
enforcing bloque en `JEV_INCOHERENT_STATE` avec `action_intent` préservé,
off n'appelle jamais).

**Limites connues** : dataset `runtime_failures` unilatéral (0 cas `go`) — l'accord 1.00
ne couvre que le côté bloqué. Enforcing mesuré sur 24 états synthétiques
aveugles (seed 11, `POKER_JEV_TIMEOUT_S=30`, mode enforcing, coût `"0"`) :
cohérents (héros visibles, pot lisible, conf 0.80-0.95) → go 0.62-0.86,
tier fast → **0/12 faux blocs** (garde-fou tier) ; incohérents (héros absents,
pot illisible, contradictions) → go 0.02-0.06, tier deep, risky ~0.89 →
**12/12 vrais blocs**, 0 manqué, 0 fail-open. Reste à confirmer sur session
papier réelle (`POKER_JEV_MODE=enforcing`) avant tout usage réel — les états
synthétiques ne remplacent pas le corpus. Option seuil 0.5 discutée, non
appliquée (configurable par l'utilisateur).

**Tri stale_frame (2026-09-23, corpus 185 incidents, offline)** : ages min 1719 /
p10 1994 / méd 7531 / p90 8006 / max 8547 ms ; > 2000 ms : 166, > 5000 ms : 161,
1250–2500 ms : 22. 159/185 viennent d'une seule session
(`runtime-20260415T120632Z-393d9825`, spot `live:IDLE:idle`, gaps méd 23 s max
3186 s → table figée/absence, pas capture lente). Le petit cluster actionnable
(~24 PREFLOP, pots 23/8000/14428, ages 1719–2172 ms) rame ~2 s vs seuil 1250 ms
(`main.py` `max_live_frame_age_s`, fallback readiness `frame_fresh <= 300 ms`
dans `gate_flow.py`). Verdict : seuil 1250 ms **gardé** (relever légitimerait
les frames figées) ; incident `stale_frame` enrichi (`street` +
`actionable_spot`) pour trancher figé vs actionnable au prochain tri.

**Tri near_miss (2026-09-23, corpus 1686 near_miss, offline)** : strates par
métadonnées de validation résolues (street, héros, légales) — **A idle-vrai
1380** (`IDLE,0,0` : 1177 `live:IDLE:idle` + 202 `waiting_next_hand` + 1
observing), **B héros-présent 178** (164 `PREFLOP,2,1` + 11 `PREFLOP,2,0` + 2
`PREFLOP,2,2` + 1 `TURN,2,1`), **C boutons-sans-héros 127** (123
`PREFLOP,0,1` + 2 `FLOP,0,1` + 2 `IDLE,0,1`), + 1 résidu
`FLOP:observing_hand:pot-0.0:no_buttons`. 163/178 de B et 87/127 de C viennent
de la session figée `runtime-20260415T120632Z-393d9825`. États : 1679
`degraded_valid` **zéro-reason** (règle validateur `conf < 0.6`) + 7
`soft_invalid` (4 `missing_postflop_pot`, 3 `legal_actions_without_buttons`) ;
readiness 1686/1686 `conservative` (`degraded_fields` : `state_confidence`
1456 + `pot` 203 — règle `conf < 0.45`). Mécanisme B : `spot_id` ctx =
**spot observé pré-résolution** (`live:IDLE:idle`, fallback sans
board/héros/pot → boutons strippés) tandis que street/héros/légales résolues
viennent de la fusion tracker-wins — staleness observé-vs-tracker, cosmétique
pour le tri (`resolved_street` loggué). C = boutons sans héros, ambigu réel,
à garder enregistré. Garde-fou : le suppresseur
`_should_record_runtime_readiness_failure` (idle/waiting/sitting/observing)
**pré-date le corpus** (bundle 030d9c7, mai 2026) — appliqué
rétroactivement il tait la strate A en live, B/C passent
(`active_hand`/`actionable_without_hero`). Arbitrage Jev live (campagne
aveugle) : la confiance domine, **aucune pénalité de spot IDLE** — la garde
n'est **pas** étendue à `actionable_without_hero`. Verdict : seuils `< 0.6` /
`< 0.45` **non touchés** (ils pilotent le gating conservative live ;
changement conditionné à la session papier tâche 2), zéro changement code.

**Session papier enforcing (2026-09-23, proxy live, free, coût `"0"`)** :
pas de table live disponible — rejouée offline via `eval_jev_gate.py`
(`--mode enforcing`) : corpus 12 near_miss (`POKER_JEV_TIMEOUT_S=30`,
0 fail-open) → accord heuristique/Jev **12/12 = 1.00** (go 0.02-0.03,
tier deep, risky 0.81-0.86, blocage confirmé des deux côtés) ; 6 états
cohérents synthétiques (héros visibles, pot lisible, conf 0.85-0.93) →
go 0.90-0.94, tier fast, risky 0.12-0.22 → **0/6 faux blocs** ; 6 états
frontière (héros flou, pot illisible, boutons partiels, 1 carte, conf 0.35,
contradiction pot 500→50) → Jev bloque 6/6 (risky > 0.7 forcé ×5, blocage
confiant ×1) — position **plus stricte** que l'heuristique sur dégradations
partielles, à trancher en session papier réelle (table live). Latences :
p50 ~800 ms, p95 1.4 s (budget 800 ms **dépassé** — fail-open couvre en
live, timeout 0.8 s par défaut). Corollaire seuils : corpus 100 %
non-actionnable (0 état `actionable=True` sur 1935) — la confirmation
0-faux-bloc sur états **réels** reste due ; seuils `< 0.6` / `< 0.45`
toujours non touchés.
