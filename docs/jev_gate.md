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
- **Fail-open** : timeout, proxy down, réponse malformée → `verdict None`,
  décision heuristique inchangée. Jev ne casse jamais le gate (`try/except` global
  dans `gate_flow.py` + `JEV_INCOHERENT_STATE` préservant `action_intent`/`confidence`).

## Validation (2026-09-22, proxy live, modèle free, coût 0)

- `scripts/eval_jev_gate.py --mode observer --limit 50` : accord 49/49 = 1.00,
  p50 532 ms, p95 718 ms (budget 800 ms OK), 1 fail-open, coûts `['0']`.
- `--mode enforcing --limit 50` : accord 47/47 = 1.00, p50 516 ms, p95 688 ms,
  3 fail-open (TimeoutError ~800 ms, heuristique gardée).
- `tests/test_jev_gate.py` : 12 tests mockés (wire format, politique, fail-open, modes).
- `pytest tests/test_jev_gate.py tests/test_main_decision_gate_replay.py` : 69 verts.

**Limites connues** : dataset `runtime_failures` unilatéral (0 cas `go`) — l'accord 1.00
ne couvre que le côté bloqué. Seuil 0.3 très conservateur en enforcing (bloque des
`go` 0.64–0.70 sur états cohérents synthétiques) : mesurer le taux de faux blocs en
session papier `POKER_JEV_MODE=enforcing` avant tout usage réel. Option seuil 0.5
discutée, non appliquée (configurable par l'utilisateur).
