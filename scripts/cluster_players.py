import asyncio
import logging
import os
import sys
from collections import defaultdict
import numpy as np

try:
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
except ImportError:
    KMeans = None

# Ajouter le répertoire racine au PYTHONPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.database import DatabaseManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("PlayerClustering")

async def run_clustering():
    if KMeans is None:
        logger.error("Scikit-learn n'est pas installé. Lancez: pip install scikit-learn")
        return

    logger.info("Démarrage du processus de profilage avancé (K-Means)...")
    db = DatabaseManager()
    await db.connect()

    if not db.pool:
        logger.warning("Connexion PostgreSQL indisponible. Fin du profilage.")
        return

    # Récupérer les joueurs avec suffisamment d'historique (ex: > 50 mains)
    query = """
        SELECT player_name, hands_played, observed_hands, vpip_count, pfr_count, raw_stats
        FROM players
        WHERE (hands_played > 50 OR observed_hands > 50)
    """
    
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(query)

    if len(rows) < 10:
        logger.warning(f"Pas assez de joueurs qualifiés ({len(rows)} < 10) pour lancer le K-Means.")
        await db.close()
        return

    # Préparation des données (Features extraction)
    player_names = []
    features = []

    for row in rows:
        name = row['player_name']
        sample_size = max(row['observed_hands'], row['hands_played'])
        
        vpip = float(row['vpip_count']) / sample_size if sample_size > 0 else 0.0
        pfr = float(row['pfr_count']) / sample_size if sample_size > 0 else 0.0
        gap = max(0.0, vpip - pfr)
        
        raw_stats = row['raw_stats'] if isinstance(row['raw_stats'], dict) else {}
        agg_actions = int(raw_stats.get('aggressive_actions', 0))
        pass_actions = int(raw_stats.get('passive_actions', 0))
        total_actions = agg_actions + pass_actions
        
        afq = float(agg_actions) / total_actions if total_actions > 0 else 0.0

        player_names.append(name)
        features.append([vpip, pfr, gap, afq])

    X = np.array(features)
    
    # Normalisation
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Déterminer le nombre de clusters (max 6 profils types de poker)
    n_clusters = min(6, len(X))
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = kmeans.fit_predict(X_scaled)

    # Analyse des centroids pour nommer les clusters
    centroids = kmeans.cluster_centers_
    original_centroids = scaler.inverse_transform(centroids)
    
    cluster_names = {}
    for i, centroid in enumerate(original_centroids):
        c_vpip, c_pfr, c_gap, c_afq = centroid
        
        # Logique de nommage basée sur les centres de gravité mathématiques
        if c_vpip > 0.40:
            name = "Maniac" if c_afq > 0.45 else "Whale"
        elif c_vpip > 0.28:
            name = "LooseAggressive" if c_pfr > 0.20 else "LoosePassive"
        elif c_vpip < 0.16:
            name = "TightAggressive" if c_pfr > 0.10 else "TightPassive" # Nit
        else:
            name = "RegAggressive" if c_afq > 0.35 else "RegPassive"
            
        cluster_names[i] = name
        logger.info(f"Cluster {i} identifié comme {name} (VPIP:{c_vpip:.2f}, PFR:{c_pfr:.2f}, AFq:{c_afq:.2f})")

    # Mise à jour de la base de données avec les nouveaux tags IA
    logger.info("Mise à jour des profils en base de données...")
    updates = 0
    async with db.pool.acquire() as conn:
        for name, label in zip(player_names, labels):
            new_type = cluster_names[label]
            await conn.execute(
                "UPDATE players SET player_type = $1 WHERE player_name = $2",
                new_type, name
            )
            updates += 1

    logger.info(f"Profilage terminé avec succès. {updates} joueurs mis à jour via Machine Learning.")
    await db.close()

if __name__ == "__main__":
    asyncio.run(run_clustering())