import json
import logging
import os
from copy import deepcopy
from datetime import UTC, datetime

try:
    import asyncpg
except ImportError:
    asyncpg = None

logger = logging.getLogger(__name__)


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _classify_player_style(vpip: float, pfr: float, aggression_frequency: float) -> str:
    if vpip >= 0.38:
        if aggression_frequency >= 0.45 or pfr >= 0.24:
            return "LooseAggressive"
        return "LoosePassive"
    if vpip <= 0.18:
        if aggression_frequency >= 0.38 or pfr >= 0.16:
            return "TightAggressive"
        return "TightPassive"
    if aggression_frequency >= 0.42 or pfr >= 0.2:
        return "RegAggressive"
    if aggression_frequency <= 0.22 and pfr <= 0.12:
        return "RegPassive"
    return "Balanced"


def _normalize_db_mode(mode: str | None) -> str:
    normalized = str(mode or "auto").strip().lower()
    if normalized in {"memory", "stub", "inmemory"}:
        return "memory"
    if normalized in {"postgres", "postgresql"}:
        return "postgres"
    return "auto"

class DatabaseManager:
    def __init__(self, dsn="postgresql://poker_bot:supersecretpassword@localhost:5432/poker_db", mode: str | None = None):
        self.dsn = dsn
        self.pool = None
        self.mode = _normalize_db_mode(mode or os.getenv("POKER_DB_MODE"))
        self.backend = "uninitialized"
        self.players_memory: dict[str, dict] = {}
        self.hands_history_memory: list[dict] = []

    @property
    def is_available(self) -> bool:
        return self.backend in {"postgres", "memory"}

    def _activate_memory_backend(self, reason: str):
        self.pool = None
        self.backend = "memory"
        logger.warning("Base PostgreSQL indisponible, bascule vers backend mémoire: %s", reason)

    def _get_memory_player(self, player_name: str) -> dict:
        player = self.players_memory.get(player_name)
        if player is None:
            player = {
                "player_name": player_name,
                "hands_played": 0,
                "observed_hands": 0,
                "vpip_count": 0,
                "pfr_count": 0,
                "three_bet_count": 0,
                "cbet_count": 0,
                "player_type": "Unknown",
                "raw_stats": {},
                "last_seen": None,
            }
            self.players_memory[player_name] = player
        return player

    @staticmethod
    def _touch_memory_player(player: dict):
        player["last_seen"] = datetime.now(UTC).isoformat(timespec="seconds")

    async def connect(self):
        """Initialise le pool de connexion à la base de données."""
        if self.mode == "memory":
            self.backend = "memory"
            logger.info("Backend mémoire activé explicitement pour la base de données.")
            return

        if asyncpg is None:
            if self.mode == "postgres":
                raise RuntimeError("asyncpg n'est pas installé et le mode postgres a été explicitement demandé.")
            self._activate_memory_backend("asyncpg non installé")
            return

        try:
            self.pool = await asyncpg.create_pool(self.dsn)
            self.backend = "postgres"
            logger.info("Connexion à PostgreSQL établie.")
            await self._init_schema()
        except Exception as e:
            if self.mode == "postgres":
                raise
            self._activate_memory_backend(str(e))

    async def _init_schema(self):
        """Crée les tables nécessaires si elles n'existent pas."""
        if self.backend != "postgres" or not self.pool:
            return
        async with self.pool.acquire() as conn:
            # Table des joueurs avec JSONB pour stocker dynamiquement d'autres stats
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS players (
                    player_name VARCHAR(255) PRIMARY KEY,
                    hands_played INT DEFAULT 0,
                    observed_hands INT DEFAULT 0,
                    vpip_count INT DEFAULT 0,
                    pfr_count INT DEFAULT 0,
                    three_bet_count INT DEFAULT 0,
                    cbet_count INT DEFAULT 0,
                    player_type VARCHAR(50) DEFAULT 'Unknown',
                    raw_stats JSONB DEFAULT '{}'::jsonb,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await conn.execute(
                "ALTER TABLE players ADD COLUMN IF NOT EXISTS observed_hands INT DEFAULT 0;"
            )

            # Table d'historique des mains (log complet de l'action)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS hands_history (
                    hand_id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    table_name VARCHAR(255),
                    board VARCHAR(15),
                    actions JSONB NOT NULL
                );
            """)
            logger.info("Schéma PostgreSQL vérifié et initialisé.")

    async def record_observed_hand(self, player_name: str, street: str = "UNKNOWN"):
        """Incrémente une seule fois par main la taille d'échantillon du joueur."""
        if self.backend == "memory":
            player = self._get_memory_player(player_name)
            raw_stats = player.setdefault("raw_stats", {})
            player["hands_played"] += 1
            player["observed_hands"] += 1
            raw_stats["observed_hands"] = int(raw_stats.get("observed_hands", 0) or 0) + 1
            raw_stats["last_observed_street"] = str(street or "UNKNOWN").upper()
            self._touch_memory_player(player)
            return

        if not self.pool:
            return

        normalized_street = str(street or "UNKNOWN").upper()
        query = """
            INSERT INTO players (player_name, hands_played, observed_hands, raw_stats, last_seen)
            VALUES (
                $1,
                1,
                1,
                jsonb_build_object('observed_hands', 1, 'last_observed_street', $2::text),
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (player_name) DO UPDATE SET
                hands_played = players.hands_played + 1,
                observed_hands = COALESCE(players.observed_hands, 0) + 1,
                raw_stats = jsonb_set(
                    jsonb_set(
                        COALESCE(players.raw_stats, '{}'::jsonb),
                        ARRAY['observed_hands'],
                        to_jsonb(COALESCE((players.raw_stats->>'observed_hands')::int, 0) + 1),
                        true
                    ),
                    ARRAY['last_observed_street'],
                    to_jsonb($2::text),
                    true
                ),
                last_seen = CURRENT_TIMESTAMP
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, player_name, normalized_street)
        except Exception as e:
            logger.error(f"Erreur SQL lors de l'observation de la main pour {player_name}: {e}")

    async def update_player_action(self, player_name: str, action_data: dict):
        """Met à jour les compteurs du joueur en temps réel."""
        action = str(action_data.get("action", "") or "").upper()
        street = str(action_data.get("street", "UNKNOWN") or "UNKNOWN").upper()
        action_aliases = set(action.replace("/", "_").split("_")) if action else set()
        is_raise_like = "RAISE" in action_aliases
        is_bet_like = "BET" in action_aliases
        is_call_like = "CALL" in action_aliases
        is_check_like = "CHECK" in action_aliases
        is_all_in = action == "ALL_IN"

        # Logique simplifiée VPIP/PFR
        is_vpip = 1 if is_call_like or is_raise_like or is_bet_like else 0
        is_pfr = 1 if is_raise_like or is_bet_like else 0
        is_aggressive = 1 if is_raise_like or is_bet_like or is_all_in else 0
        is_passive = 1 if is_call_like or is_check_like else 0
        is_fold = 1 if action == "FOLD" else 0
        raw_stats_patch = {
            "action_counts": {action: 1},
            "street_counts": {street: 1},
            "aggressive_actions": is_aggressive,
            "passive_actions": is_passive,
            "fold_actions": is_fold,
            "last_action": action,
            "last_street": street,
        }

        if self.backend == "memory":
            player = self._get_memory_player(player_name)
            raw_stats = player.setdefault("raw_stats", {})
            action_counts = raw_stats.setdefault("action_counts", {})
            street_counts = raw_stats.setdefault("street_counts", {})
            player["vpip_count"] += is_vpip
            player["pfr_count"] += is_pfr
            action_counts[action] = int(action_counts.get(action, 0) or 0) + 1
            street_counts[street] = int(street_counts.get(street, 0) or 0) + 1
            raw_stats["aggressive_actions"] = int(raw_stats.get("aggressive_actions", 0) or 0) + is_aggressive
            raw_stats["passive_actions"] = int(raw_stats.get("passive_actions", 0) or 0) + is_passive
            raw_stats["fold_actions"] = int(raw_stats.get("fold_actions", 0) or 0) + is_fold
            raw_stats["last_action"] = action
            raw_stats["last_street"] = street
            self._touch_memory_player(player)
            return

        if not self.pool:
            return
        
        query = """
            INSERT INTO players (player_name, hands_played, observed_hands, vpip_count, pfr_count, raw_stats, last_seen)
            VALUES ($1, 0, 0, $2, $3, $4::jsonb, CURRENT_TIMESTAMP)
            ON CONFLICT (player_name) DO UPDATE SET
                vpip_count = players.vpip_count + $2,
                pfr_count = players.pfr_count + $3,
                raw_stats = jsonb_set(
                    jsonb_set(
                        jsonb_set(
                            jsonb_set(
                                jsonb_set(
                                    jsonb_set(
                                        COALESCE(players.raw_stats, '{}'::jsonb),
                                        ARRAY['action_counts', $5],
                                        to_jsonb(COALESCE((players.raw_stats->'action_counts'->>$5)::int, 0) + 1),
                                        true
                                    ),
                                    ARRAY['street_counts', $6],
                                    to_jsonb(COALESCE((players.raw_stats->'street_counts'->>$6)::int, 0) + 1),
                                    true
                                ),
                                ARRAY['aggressive_actions'],
                                to_jsonb(COALESCE((players.raw_stats->>'aggressive_actions')::int, 0) + $7),
                                true
                            ),
                            ARRAY['passive_actions'],
                            to_jsonb(COALESCE((players.raw_stats->>'passive_actions')::int, 0) + $8),
                            true
                        ),
                        ARRAY['fold_actions'],
                        to_jsonb(COALESCE((players.raw_stats->>'fold_actions')::int, 0) + $9),
                        true
                    ),
                    ARRAY['last_action'],
                    to_jsonb($5::text),
                    true
                ),
                last_seen = CURRENT_TIMESTAMP
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    query,
                    player_name,
                    is_vpip,
                    is_pfr,
                    json.dumps(raw_stats_patch),
                    action,
                    street,
                    is_aggressive,
                    is_passive,
                    is_fold,
                )
        except Exception as e:
            logger.error(f"Erreur SQL lors de l'update du joueur {player_name}: {e}")

    async def insert_hand_history(self, table_name: str, board: list, actions: list):
        """Insère une main terminée dans l'historique."""
        if self.backend == "memory":
            self.hands_history_memory.append({
                "hand_id": len(self.hands_history_memory) + 1,
                "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
                "table_name": table_name,
                "board": "".join(board),
                "actions": deepcopy(actions),
            })
            return

        if not self.pool:
            return
        
        query = """
            INSERT INTO hands_history (table_name, board, actions) 
            VALUES ($1, $2, $3::jsonb)
        """
        try:
            async with self.pool.acquire() as conn:
                # Stockage du board complet sous forme de string ex: "AhKd2c"
                await conn.execute(query, table_name, "".join(board), json.dumps(actions))
        except Exception as e:
            logger.error(f"Erreur SQL lors de la sauvegarde de la main: {e}")

    async def get_player_profile(self, player_name: str):
        """Récupère le profil d'un joueur pour l'injecter dans le solver Rust."""
        if self.backend == "memory":
            memory_profile = self.players_memory.get(player_name)
            if not memory_profile:
                return None
            profile = deepcopy(memory_profile)
            raw_stats = profile.get("raw_stats") or {}
        elif not self.pool:
            return None
        else:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM players WHERE player_name = $1", 
                    player_name
                )
                if not row:
                    return None

                profile = dict(row)
            raw_stats = profile.get("raw_stats") or {}

        hands_played = int(profile.get("hands_played") or 0)
        observed_hands = int(profile.get("observed_hands") or raw_stats.get("observed_hands", 0) or 0)
        vpip_count = int(profile.get("vpip_count") or 0)
        pfr_count = int(profile.get("pfr_count") or 0)
        aggressive_actions = int(raw_stats.get("aggressive_actions", 0) or 0)
        passive_actions = int(raw_stats.get("passive_actions", 0) or 0)
        total_posture_actions = aggressive_actions + passive_actions
        action_counts = raw_stats.get("action_counts") or {}
        sample_hands = observed_hands if observed_hands > 0 else hands_played

        vpip_rate = _safe_rate(vpip_count, sample_hands)
        pfr_rate = _safe_rate(pfr_count, sample_hands)
        aggression_frequency = _safe_rate(aggressive_actions, total_posture_actions)
        aggression_ratio = round(aggressive_actions / max(passive_actions, 1), 3)
        reliability = round(min(1.0, observed_hands / 120.0), 3) if observed_hands > 0 else round(min(0.15, hands_played / 500.0), 3)
        style = _classify_player_style(vpip_rate, pfr_rate, aggression_frequency)

        profile["player_type"] = style if profile.get("player_type") in (None, "", "Unknown") else profile.get("player_type")
        profile["derived_profile"] = {
            "hands_played": sample_hands,
            "observed_hands": observed_hands,
            "action_samples": hands_played,
            "vpip_rate": vpip_rate,
            "pfr_rate": pfr_rate,
            "gap_rate": round(max(0.0, vpip_rate - pfr_rate), 4),
            "aggression_frequency": aggression_frequency,
            "aggression_ratio": aggression_ratio,
            "fold_rate": _safe_rate(int(raw_stats.get("fold_actions", 0) or 0), sample_hands),
            "reliability": reliability,
            "style": style,
            "action_counts": action_counts,
            "street_counts": raw_stats.get("street_counts") or {},
            "last_action": raw_stats.get("last_action", ""),
            "last_street": raw_stats.get("last_street", ""),
            "last_observed_street": raw_stats.get("last_observed_street", ""),
            "rl_ready": bool(raw_stats.get("rl_ready", False)),
        }
        return profile

    async def close(self):
        if self.pool:
            await self.pool.close()
            logger.info("Connexion PostgreSQL fermée.")
        self.pool = None
