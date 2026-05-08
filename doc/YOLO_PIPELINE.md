# Pipeline YOLO PokerStars

Le projet sait maintenant suivre deux chemins vision :

- backend `template` : base stable actuelle, calibrée sur tes tables PokerStars
- backend `yolo` : renfort optionnel quand un vrai modèle entraîné existe dans `models/`

Tu n’as pas besoin de comprendre YOLO pour l’utiliser. L’idée simple :

1. prendre des captures d’écran
2. les annoter
3. préparer un dataset
4. lancer l’entraînement
5. récupérer un modèle utilisable par PokerMaster

## 1. Importer tes captures

Exemple avec ton dossier `POKERSTAR CAPTURE` :

```bash
C:/Users/julie/AppData/Local/Programs/Python/Python312/python.exe scripts/import_capture_folder.py --source-dir "POKERSTAR CAPTURE" --destination-dir "dataset/raw_images" --prefix pokerstars
```

## 2. Générer les labels YOLO

### Option A: bootstrap local immédiat depuis le backend template

Si tu n’as pas de provider Vision configuré, tu peux déjà générer des pseudo-labels locaux :

```bash
C:/Users/julie/AppData/Local/Programs/Python/Python312/python.exe scripts/bootstrap_yolo_labels_from_template.py --raw-dir dataset/raw_images --labels-dir dataset/labels
```

Cette option est pratique pour démarrer vite avec tes captures PokerStars déjà calibrées.

### Option B: auto-annotation via provider Vision

Le projet a déjà un auto-annotateur :

```bash
C:/Users/julie/AppData/Local/Programs/Python/Python312/python.exe src/vision/auto_annotator.py --raw-dir dataset/raw_images --labels-dir dataset/labels
```

Si tu as configuré les providers Vision dans l’interface, tu peux aussi le lancer depuis PokerMaster.

## 3. Préparer le dataset train/val

```bash
C:/Users/julie/AppData/Local/Programs/Python/Python312/python.exe scripts/prepare_yolo_dataset.py --raw-dir dataset/raw_images --labels-dir dataset/labels --output-dir dataset/yolo_pokerstars
```

Ça crée :

- `dataset/yolo_pokerstars/images/train`
- `dataset/yolo_pokerstars/images/val`
- `dataset/yolo_pokerstars/labels/train`
- `dataset/yolo_pokerstars/labels/val`
- `dataset/yolo_pokerstars/data.yaml`

## 4. Entraîner le modèle

Version simple CPU :

```bash
C:/Users/julie/AppData/Local/Programs/Python/Python312/python.exe scripts/train_yolo_detector.py --data dataset/yolo_pokerstars/data.yaml --device cpu --epochs 40 --export-onnx
```

À la fin :

- les meilleurs poids sont copiés vers `models/poker_yolo_v11.pt`
- si `--export-onnx` est activé, un export est créé dans `models/poker_yolo_v11.onnx`

## 5. Ce que PokerMaster charge automatiquement

Le détecteur cherche désormais automatiquement :

1. `models/poker_yolo_v11.engine`
2. `models/poker_yolo_v11.onnx`
3. `models/poker_yolo_v11.pt`

Donc un export ONNX suffit déjà pour commencer.

## Classes utilisées

Le schéma actuel est défini dans [src/vision/yolo_schema.py](/mnt/c/Users/julie/Desktop/Poker-master/src/vision/yolo_schema.py) :

- `board_card`
- `hero_card`
- `pot_area`
- `stack_area`
- `player_name_area`
- `dealer_button`
- `fold_button`
- `call_button`
- `check_button`
- `bet_button`
- `raise_button`

## Limite importante

Le backend template reste aujourd’hui le plus fiable pour lire l’identité exacte des cartes.

Le pipeline YOLO posé ici sert surtout à :

- mieux localiser les zones,
- mieux repérer les boutons,
- préparer un vrai modèle vision dédié à ton setup.

Si on veut ensuite que YOLO lise aussi les cartes exactes de manière native, il faudra enrichir le dataset avec des classes fines par carte.
