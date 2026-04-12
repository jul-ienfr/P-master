# 🏆 Plan d'Implémentation "Super-Bot" Poker 2026 : GTO & Exploitatif

Ce document détaille l'architecture cible et la marche à suivre pas-à-pas pour transformer le bot actuel en une machine de guerre autonome, résiliente et inexploitable, en utilisant les meilleures technologies disponibles en 2026.

---

## 👁️ Phase 1 : Moteur de Vision & OCR Résilient (La Fondation)
**Technologies :** Python, DXcam (ou Windows Desktop Duplication), YOLOv11 / RT-DETR, DocTR (Mindee), ONNX/TensorRT.

### 1.1 Capture d'écran Ultra-Low Latency
- [ ] Remplacer les librairies de capture CPU (MSS, PIL) par `DXcam`.
- [ ] Implémenter un worker asynchrone de capture d'écran tournant à ~30/60 FPS ciblant uniquement la fenêtre du client de poker.
- [ ] Mettre en place un système de redimensionnement/normalisation de la frame pour préparer l'inférence.

### 1.2 Détection d'objets (Cartes, Bouton, Zones) avec YOLO
- [ ] Créer un compte Roboflow et initialiser un nouveau projet de détection d'objets.
- [ ] Récolter un dataset de ~1000 captures d'écran de tables avec différents thèmes, tailles, et animations.
- [ ] Annoter les bounding boxes (Bouton Dealer, Cartes de Table, Cartes du Héros, Zones de Stacks, Zones de Mises).
- [ ] Entraîner un modèle `YOLOv11-nano` (ou `RT-DETR`) sur les données.
- [ ] Exporter le modèle au format `ONNX` ou `TensorRT`.
- [ ] Intégrer le modèle dans le pipeline Python via `ultralytics` ou `onnxruntime` pour remplacer la logique actuelle de Template Matching.

### 1.3 OCR Nouvelle Génération avec DocTR
- [ ] Remplacer l'ancien OCR (Tesseract/EasyOCR) par `DocTR` (Architecture Transformer ViT).
- [ ] Découper la frame en "crops" (morceaux) à partir des Bounding Boxes détectées par YOLO (Crop du Stack, Crop du Pot, Crop des Noms).
- [ ] Passer ces "crops" dans DocTR pour extraire les entiers (Jetons, Pots) et le texte (Noms des joueurs).
- [ ] Implémenter un filtre de nettoyage (Regex) pour corriger les erreurs mineures (ex: "S" au lieu de "5").

---

## 🧠 Phase 2 : Data-Mining, HUD & Profilage (La Mémoire)
**Technologies :** PostgreSQL 16+ (JSONB), Redis, Python (asyncpg), scikit-learn.

### 2.1 Infrastructure de Données
- [ ] Créer un fichier `docker-compose.yml` dédié à l'infrastructure (PostgreSQL + Redis).
- [ ] Concevoir le schéma de base de données PostgreSQL :
  - Table `players` (ID, Name, Total_Hands, VPIP, PFR, 3Bet, AF, etc.)
  - Table `hands_history` (utilisation de colonnes `JSONB` pour stocker le déroulé complet des actions).
- [ ] Développer une classe Python `DatabaseManager` utilisant `asyncpg` pour des requêtes non bloquantes.

### 2.2 Ingestion des Données Temps Réel
- [ ] Mettre en place un stream `Redis Pub/Sub`. Le Moteur de Vision envoie un JSON d'état à chaque changement d'action.
- [ ] Créer un daemon `Tracker.py` qui écoute Redis et insère/met à jour l'historique dans PostgreSQL à la fin de chaque main.

### 2.3 IA de Profilage (Clustering)
- [ ] Implémenter un script d'analyse tournant en tâche de fond qui recalcule les statistiques (VPIP, PFR, Aggression Factor) de tous les joueurs.
- [ ] Utiliser `scikit-learn` (K-Means ou algorithme par règles strictes) pour assigner un TAG (Nit, TAG, LAG, Station, Whale, Maniac) à chaque joueur en fonction de ses stats.
- [ ] Mettre ce profil en cache (Redis) pour un accès ultra-rapide in-game.

---

## ⚙️ Phase 3 : IA "Node-Locking" & Solveur Rust (Le Cerveau)
**Technologies :** Rust, PyO3, Algorithme DCFR (Discounted CFR) ou CFR+, Node-Locking.

### 3.1 Audit et Mise à jour du Solver Rust
- [ ] Auditer `src/solver.rs` et `src/action_tree.rs` pour vérifier l'implémentation actuelle de l'algorithme CFR.
- [ ] (Optionnel) Migrer l'algorithme vers `Discounted CFR (DCFR)` pour une convergence plus rapide sur quelques secondes de réflexion.
- [ ] Implémenter la fonctionnalité de **Node-Locking** dans le solver Rust : permettre de forcer les fréquences d'une branche de l'arbre de jeu (ex: forcer le "Fold" de Villain à 10% si c'est une Calling Station).

### 3.2 Bridge Python-Rust
- [ ] Modifier l'API `src/gto_api.rs` exposée via PyO3 pour accepter les profils des joueurs en argument d'entrée.
- [ ] Dans Python, avant chaque décision, requêter le profil de l'adversaire depuis Redis/Postgres.
- [ ] Moduler les ranges (ajuster la matrice de probabilités) selon le profil avant d'appeler le solver Rust.

### 3.3 Calibrage du Temps de Réflexion
- [ ] Mettre en place un benchmark pour s'assurer que le calcul de la Maximal Exploitative Strategy (MES) prend moins de ~1 à 2 secondes pour ne pas "Time Out" à la table.

---

## 🤖 Phase 4 : Auto-Sélecteur de Tables & Actions (Le Grinder)
**Technologies :** Python, Windows UIAutomation, API Win32, state-machine (Transitions).

### 4.1 Interactions Invisibles (Win32API)
- [ ] Supprimer `pyautogui`.
- [ ] Implémenter un module `ActionController` utilisant `uiautomation` ou `Win32API` (PostMessage/SendMessage) pour envoyer les inputs de clic et de texte en arrière-plan (sans accaparer la souris de l'utilisateur).
- [ ] Tester le clic des boutons (Fold, Call, Raise) et la saisie du montant de mise sur une table en arrière-plan.

### 4.2 Auto-Selecteur (Lobby Scraper)
- [ ] Créer une State Machine (`Transitions`) pour gérer les états du bot : LOBBY_IDLE, SCANNING, JOINING, PLAYING, LEAVING.
- [ ] Utiliser le pipeline YOLO+DocTR pour lire le Lobby du logiciel de poker.
- [ ] Croiser les noms lus dans le Lobby avec la base de données PostgreSQL.
- [ ] Implémenter l'algorithme de Bumhunting : "Rejoindre la table SI un joueur a le tag Whale OU SI Average VPIP > 40%".

### 4.3 Règles de Bankroll & Stop-Loss
- [ ] Coder des règles de sortie strictes (Quitter si : perte > X caves, si le fish quitte la table, si temps de session > Y heures).

---

## 🛠 Phase 5 : Intégration, Tests & Déploiement
**Technologies :** Pytest, Logger, Docker.

- [ ] Unifier tous les modules dans une boucle principale asynchrone (Main Event Loop `asyncio`).
- [ ] Mettre à jour `tests/` et `smoke_test_windows.ps1` pour tester le bon fonctionnement de la communication Rust/Python, de la Vision et de Postgres.
- [ ] Implémenter un logger structuré riche pour suivre les décisions GTO dans le dossier `log/`.
- [ ] (Optionnel) Créer un dashboard Web léger pour surveiller le bot à distance.
