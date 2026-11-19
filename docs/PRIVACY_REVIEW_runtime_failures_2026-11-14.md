# Revue de confidentialité — `dataset/runtime_failures`

Date : 14 novembre 2026. Périmètre : dépôt public `Poker-master`, commit
`fb68593` + modifications locales Phase 0.

## 1. Inventaire

| Élément | Valeur |
|---|---|
| `incidents.jsonl` | 49 Mo, 1 935 lignes JSON valides (0 erreur de parsing) |
| Images suivies | 164 PNG (20 Mo de frames + 2,5 Mo de crops) |
| Fichiers suivis au total | 165 |
| Catégories | `near_miss` 1 686, `incident` 249 |
| Sévérités | `warning` 1 894, `error` 41 |

Le JSONL contient l'état de table, les cartes du héros, le board, les tapis,
l'historique d'actions, les candidats OCR et les chemins d'artefacts. Les PNG
montrent des captures réelles de tables (pseudo des joueurs, cartes, tapis).

## 2. Recherche de secrets et d'identifiants

Balayage des 1 935 lignes avec des expressions régulières :

| Motif | Occurrences |
|---|---|
| Adresse e-mail | 0 |
| Adresse IPv4 | 0 |
| Clé API (`sk-`, `ghp_`, `AIza`, `xox*`, etc.) | 0 |
| En-tête `Bearer` | 0 |
| Webhook Discord | 0 |
| Chemin utilisateur Windows absolu (`C:\Users\...`) | 0 |
| Chemin `/home/...` | 0 |
| Nom d'utilisateur local (`julie`, insensible à la casse) | 17 lignes |

Les 17 occurrences de `julie` ne sont pas des métadonnées de chemin : ce sont
des lectures OCR bruitées (`julienf`, `RrUusersjulie`, `RarUsersJulie`) dans des
candidats de reconnaissance de texte, probablement parce qu'une zone de la
capture contenait un chemin ou un nom de session. Aucune clé, aucun jeton,
aucune adresse réseau n'a été trouvé.

## 3. Données tierces

- **Pseudo de joueurs** : 51 valeurs distinctes détectées dans les champs OCR
  (`Earney`, `DesertDa`, `kullaif`, `XXMFCxXX21`, `ThomasFrench`, `flashnp`,
  `jesus5618`, etc.). Certaines sont répétées plus de 200 fois.
- **Captures de table** : 164 PNG contenant les pseudos, les cartes, les tapis
  et l'historique visuel d'une session réelle.
- **Cartes du héros et board** : présents dans le JSONL et dans les crops
  `hero`, `pot`, `actions`.

Ces données ne sont pas des identifiants civils, mais elles appartiennent à des
tiers et à une session de jeu réelle. Leur publication dans un dépôt public
n'est pas couverte par la licence AGPL du code : la licence du code ne vaut pas
consentement des joueurs filmés.

## 4. Verdict

**Le dataset ne doit pas être distribué publiquement en l'état.** Il ne contient
pas de secret d'infrastructure, mais il contient des données de table tierces
et des captures d'écran. Pour un dépôt privé ou un usage local, le risque est
faible. Pour une distribution publique, il faut retirer le dataset de
l'historique, pas seulement de la copie de travail.

## 5. Remédiation recommandée

### Option A — garder le dataset privé (recommandée)

1. Retirer le répertoire du suivi Git :
   ```bash
   git rm -r --cached dataset/runtime_failures
   ```
2. Ajouter la règle d'ignorance (déjà faite dans `.gitignore`) :
   ```gitignore
   /dataset/runtime_failures
   ```
3. Committer la suppression. Les fichiers restent sur le disque local.
4. Si le dépôt a déjà été poussé publiquement, réécrire l'historique avec
   `git filter-repo` ou BFG, puis force-push après concertation. Sans rewrite,
   les blobs restent accessibles dans l'historique.

### Option B — publier une version assainie

1. Supprimer les champs `artifacts`, `candidates[].text`, `raw_text`,
   `resolved_text`, `name` et tout texte OCR libre.
2. Flouter ou supprimer les 164 PNG (les crops `hero`/`pot`/`actions` aussi).
3. Remplacer les pseudos par des identifiants synthétiques (`player_1`, ...).
4. Vérifier qu'aucune carte du héros ne permet de réidentifier une main jouée.
5. Relancer le balayage regex de la section 2 sur le fichier assaini.

### Option C — conserver pour la recherche interne

Garder le dataset hors du dépôt, dans un stockage chiffré ou un bucket privé,
avec une politique de rétention. C'est l'option la plus simple si les données
servent à calibrer la quantification des mises ou les incidents vision.

## 6. Prévention

- Les nouvelles captures doivent aller dans un chemin ignoré par Git
  (`dataset/runtime_failures` l'est désormais).
- Les tests sont isolés : `tests/conftest.py` redirige `POKER_BET_LOG_PATH` et
  `POKER_BLUEPRINT_MISS_LOG` vers un répertoire temporaire, donc la suite ne
  peut plus modifier `evidence/`.
- Avant toute publication, exécuter le balayage regex et vérifier
  `git ls-files dataset/` : aucun fichier de capture ne doit apparaître.
