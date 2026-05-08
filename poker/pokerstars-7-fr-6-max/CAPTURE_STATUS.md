PokerStars 7 FR 6-max preset generated from screenshots in `POKERSTAR CAPTURE`.

Calibration notes:
- anchor variants now include the original `topleft_corner`, a compact no-title-bar crop (`topleft_corner_compact`), and a live desktop crop (`topleft_corner_live`) captured from the April 12, 2026 runtime
- anchor offsets are now defined per variant because some captures start at the icon row while others still include the white title bar
- the compact anchor is constrained to the real frame origin so it cannot override the standard anchor inside titled captures
- `kc` and `6s` were refreshed from the April 12, 2026 live Mercury runtime because those ranks were still inherited from the old preset
- `jd`, `td`, and `th` were refreshed from the April 12, 2026 evening captures
- hero cards use dedicated `left_card_area` and `right_card_area`
- board cards use dedicated `board_card_areas` slots to avoid duplicate matches inside the full board strip

Native captures available:
- `2s`, `4h`, `5s`, `6s`, `7d`, `9d`, `9s`, `tc`, `td`, `th`, `jc`, `jd`, `jh`, `js`, `kc`, `ad`, `as`
- room anchors and buttons: `topleft_corner`, `fold_button`, `call_button`, `check_button`, `bet_button`, `raise_button`, `dealer_button`, `covered_card`, `my_turn`

Synthesized from native rank + suit captures:
- `2c`, `2d`, `2h`
- `4c`, `4d`, `4s`
- `5c`, `5d`, `5h`
- `7c`, `7h`, `7s`
- `9c`, `9h`
- `ts`
- `ac`, `ah`

Still inherited from the previous preset until more PokerStars captures are added:
- all cards with ranks `3`, `6`, `8`, `q`, `k`
- remaining unsynthesized combinations for those ranks
