# Archives de benchmarks

Ces fichiers ne doivent pas être cités comme preuve actuelle.

## Bug d'équité Monte-Carlo

Les fichiers `slumbot_smoke*`, `slumbot_20*`, `slumbot_50*`,
`slumbot_debug*` ont été produits avant le correctif du 15 novembre 2026 :
`monte_carlo_equity` recevait le board sous forme de chaîne et traitait chaque
caractère comme une carte. Les équités étaient biaisées et le client pouvait se
bloquer.

## Bug d'unités du benchmark Slumbot

`slumbot_300_unit_bug.*` a été produit avant la conversion de la vue de
politique en gros blindes. La politique comparait `to_call` (en jetons, 50–100)
à `BIG_BLIND` (2 bb), donc elle abandonnait presque tout et le résultat
(−65,667 bb/100) ne mesure pas la politique mais ce bug.

`slumbot_300_units_pilot.*` est le premier essai après conversion (300 mains,
+36,667 bb/100, IC 95 % très large). Il est conservé comme preuve de la
variance, mais remplacé par l'échantillon de 1 000 mains.

## Canonique

Le benchmark canonique est `../slumbot_1000.jsonl` (1 000 mains, 0 erreur),
résumé dans `../slumbot_1000.summary.json`.
