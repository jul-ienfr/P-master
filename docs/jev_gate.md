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
Detail : le juge et l'autolabel timeoutent à 0.8 s sur états lourds →
`POKER_JEV_TIMEOUT_S=8..30` en batch offline (fail-open sinon, `unknown`, jamais d'erreur).

Tests : `tests/test_jev_expansion.py` (20 tests mockés : autolabel, juge,
attention, budgets tier, drift/détection/observer) + `tests/test_jev_gate.py`
(16) → 36 verts.

**Limites connues** : dataset `runtime_failures` unilatéral (0 cas `go`) — l'accord 1.00
ne couvre que le côté bloqué. Seuil 0.3 très conservateur en enforcing (bloque des
`go` 0.64–0.70 sur états cohérents synthétiques) : mesurer le taux de faux blocs en
session papier `POKER_JEV_MODE=enforcing` avant tout usage réel. Option seuil 0.5
discutée, non appliquée (configurable par l'utilisateur).
