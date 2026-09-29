# Spike Djev officiel — statut : UNVALIDATED (zéro appel live au 2026-09-28)

> Tant que ce fichier reste `UNVALIDATED`, tout le chemin Djev cloud est
> **observer pur + fail-open** (`mode: observer`, jamais d'enforcing via
> `gate_flow.py`). La bascule enforcing exige 1 appel officiel validé
> (curl ci-dessous OK) + `pytest tests/test_djev_gate.py` vert + eval A/B.

## 1. Appel de référence (quickstart officiel)

```bash
curl https://api.typesafe.ai/v1/systemone \
  -H "Authorization: Bearer $TYPESAFE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "jev-1.13.0",
    "state": "preflop NLHE, hero AKs BTN, pot 3.5bb, hero to act, no contradiction",
    "questions": {
      "go":    { "type": "noul",   "instructions": "The table state is complete and coherent: hero cards, pot and action buttons are all visible and readable, with no contradiction between fields." },
      "tier":  { "type": "choice", "instructions": "How deep should the solver think for this spot?", "criteria": { "fast": "Standard spot, shallow solve is enough.", "balanced": "Normal spot, default solve depth.", "deep": "Complex or high-stakes spot, deep solve warranted.", "other": "None of the above applies." } },
      "risky": { "type": "noul",   "instructions": "Acting now risks an irreversible costly mistake (misclick, wrong sizing, acting out of turn)." },
      "effort":{ "type": "score",  "instructions": "How much solver effort does this spot deserve?", "criteria": ["Trivial spot, minimal effort.", "Standard spot, normal effort.", "Critical high-leverage spot, maximum effort."] }
    }
  }'
```

Réponse attendue : `{ "model": "jev-1.13.0", "answers": { "go": {"noul": …}, "tier": {"choice": …, "confidence": …, "probabilities": …}, "risky": {"noul": …}, "effort": {"score": …, "confidence": …} }, "usage": { "input_tokens": …, "output_tokens": … } }`.

Clé : variable d'environnement `TYPESAFE_API_KEY` (**nom uniquement, jamais la
valeur** — ni en chat, ni en fichier, ni en dur). Sans clé : `djev_gate.query`
fail-open **sans appel réseau** (`fail-open: missing api key`).

## 2. Wire format constaté (à remplir après le 1er appel réel)

| Champ | Attendu (doc) | Constaté | Écart |
|---|---|---|---|
| `model` effectif | `jev-1.13.0` | — | — |
| `answers.go.noul` | float 0..1 | — | — |
| `answers.tier.choice` + `confidence` + `probabilities` | fast/balanced/deep | — | — |
| `answers.risky.noul` | float 0..1 | — | — |
| `answers.effort.score` + `confidence` | float | — | — |
| `usage.input_tokens` / `output_tokens` | entiers | — | — |
| Latence p50 observée | — | — | vs budget tier fast 400ms |
| Coût mesuré | $0.042/Mtok entrée, sortie gratuite | — | — |

## 3. Écarts proxy :4000 vs officiel (déjà absorbés dans `src/bot/djev_gate.py`)

| Écart | Proxy `:4000` | Officiel | Isolation |
|---|---|---|---|
| `base_url` | `http://127.0.0.1:4000` (+ `/v1/systemone` ajouté) | URL complète incluant `/v1/systemone` (reconnue telle quelle) | `djev_gate._endpoint` |
| `model` | `jev-1.13-free`, cost `0`, anonyme | `jev-1.13.0` piné (alias `jev-latest` mouvant) | `DjevGateConfig.model` |
| auth | aucune | `Bearer` depuis `os.environ[api_key_env]` | `djev_gate.query` |
| `state` | string-only (400 si objet) | objet accepté, mais on garde string-only (comparabilité) | `build_state` partagé |
| erreurs | 404 proxy | 401/422 fail-open direct ; 429/529 1 retry + `retry-after` | `djev_gate.query` |
| offline | `POKER_OFFLINE_MODE` → repli loopback | `offline_mode=true` + WAN → fail-open **sans appel** | `DjevGateConfig.from_env` + `query` |

## 4. Modèle piné

`jev-1.13.0` (stable). `jev-latest` et `jev-preview` = alias mouvants :
**interdits** dès que des seuils sont tunés (la doc prévient que `jev-preview`
peut changer sans préavis). Logger toujours `model` effectif + `probabilities`.

## 5. Pricing / limites (doc, non mesuré ici)

$42/Btok = **$0.042/Mtok, entrée seule, sortie gratuite** (`output_tokens`
compté dans `usage`). Rate limits **250k tok/s, 1200 req/min**, ajustables
sans préavis. `150ms`/`100x` = marketing, pas SLA. Enterprise :
`sales@typesafe.ai`.
