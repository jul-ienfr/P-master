import json
import logging
import os
from copy import deepcopy
try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.10 compatibility
    from datetime import datetime, timezone

    UTC = timezone.utc

try:
    import asyncpg
except ImportError:
    asyncpg = None

from src.runtime.player_name_resolver import (
    is_placeholder_player_name,
    is_usable_player_name,
    sanitize_player_name,
)

logger = logging.getLogger(__name__)


def _coerce_json_object(value: object) -> dict:
    if isinstance(value, dict):
        return deepcopy(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return deepcopy(parsed) if isinstance(parsed, dict) else {}
    return {}


def _coerce_json_array(value: object) -> list:
    if isinstance(value, list):
        return deepcopy(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return []
        return deepcopy(parsed) if isinstance(parsed, list) else []
    return []


def _coerce_datetime_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(min(1.0, float(numerator) / float(denominator)), 4)


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


def _normalize_profile_name(player_name: str) -> str:
    sanitized = sanitize_player_name(player_name)
    if sanitized:
        return sanitized
    return str(player_name or "").strip()


def _is_observation_profile_name_supported(player_name: str) -> bool:
    normalized_name = sanitize_player_name(player_name)
    if not normalized_name:
        return False
    return is_usable_player_name(normalized_name) or is_placeholder_player_name(normalized_name)

class DatabaseManager:
    def __init__(
        self,
        dsn="postgresql://poker_bot:supersecretpassword@localhost:5432/poker_db",
        mode: str | None = None,
        persistence_path: str | None = None,
        persistence_enabled: bool = False,
    ):
        self.dsn = dsn
        self.pool = None
        self.mode = _normalize_db_mode(mode or os.getenv("POKER_DB_MODE"))
        self.backend = "uninitialized"
        self.players_memory: dict[str, dict] = {}
        self.hands_history_memory: list[dict] = []
        configured_path = persistence_path or os.getenv("POKER_OBSERVATION_STORE_PATH") or "log/observation_store.json"
        self.persistence_path = os.path.abspath(configured_path) if configured_path else ""
        self.persistence_enabled = bool(persistence_enabled)
        self.last_persisted_at: str | None = None
        self.persistence_error: str | None = None

    @staticmethod
    def _new_memory_player(player_name: str) -> dict:
        return {
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

    @property
    def is_available(self) -> bool:
        return self.backend in {"postgres", "memory"}

    @property
    def persistence_active(self) -> bool:
        return self.backend == "memory" and self.persistence_enabled and bool(self.persistence_path)

    def _persistence_snapshot(self) -> dict:
        if self.backend == "postgres":
            mode = "postgres"
        elif self.persistence_active:
            mode = "json_file"
        else:
            mode = "volatile_memory"
        return {
            "mode": mode,
            "enabled": bool(self.persistence_enabled),
            "path": self.persistence_path or None,
            "last_persisted_at": self.last_persisted_at,
            "error": self.persistence_error,
        }

    def _observation_store_payload(self) -> dict:
        return {
            "format": "runtime_observation_store_v1",
            "saved_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "players_memory": deepcopy(self.players_memory),
            "hands_history_memory": deepcopy(self.hands_history_memory),
        }

    def _load_local_persistence(self):
        if not self.persistence_active or not self.persistence_path:
            return
        if not os.path.exists(self.persistence_path):
            return

        try:
            with open(self.persistence_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as e:
            self.persistence_error = str(e)
            logger.warning("Impossible de charger la persistance locale d'observation: %s", e)
            return

        players_memory = payload.get("players_memory")
        hands_history_memory = payload.get("hands_history_memory")
        if isinstance(players_memory, dict):
            self.players_memory = deepcopy(players_memory)
        if isinstance(hands_history_memory, list):
            self.hands_history_memory = deepcopy(hands_history_memory)
        self.last_persisted_at = str(payload.get("saved_at") or "") or None
        self.persistence_error = None
        logger.info(
            "Observation locale rechargee depuis %s (%s joueurs, %s mains).",
            self.persistence_path,
            len(self.players_memory),
            len(self.hands_history_memory),
        )

    def _persist_local_state(self):
        if not self.persistence_active or not self.persistence_path:
            return

        payload = self._observation_store_payload()
        directory = os.path.dirname(self.persistence_path)
        temp_path = f"{self.persistence_path}.tmp"
        try:
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=True, indent=2)
            os.replace(temp_path, self.persistence_path)
            self.last_persisted_at = str(payload.get("saved_at") or "") or None
            self.persistence_error = None
        except Exception as e:
            self.persistence_error = str(e)
            logger.error("Impossible de persister l'observation locale dans %s: %s", self.persistence_path, e)
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass

    def _activate_memory_backend(self, reason: str):
        self.pool = None
        self.backend = "memory"
        logger.warning("Base PostgreSQL indisponible, bascule vers backend mémoire: %s", reason)
        self._load_local_persistence()

    def _get_memory_player(self, player_name: str) -> dict:
        player = self.players_memory.get(player_name)
        if player is None:
            player = self._new_memory_player(player_name)
            self.players_memory[player_name] = player
        return player

    @staticmethod
    def _touch_memory_player(player: dict):
        player["last_seen"] = datetime.now(UTC).isoformat(timespec="seconds")

    def _apply_observed_hand_cache(self, player_name: str, street: str):
        player = self._get_memory_player(player_name)
        raw_stats = player.setdefault("raw_stats", {})
        player["hands_played"] += 1
        player["observed_hands"] += 1
        raw_stats["observed_hands"] = int(raw_stats.get("observed_hands", 0) or 0) + 1
        raw_stats["last_observed_street"] = str(street or "UNKNOWN").upper()
        self._touch_memory_player(player)

    def _apply_player_action_cache(
        self,
        player_name: str,
        action: str,
        street: str,
        *,
        is_vpip: int,
        is_pfr: int,
        is_aggressive: int,
        is_passive: int,
        is_fold: int,
    ):
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

    def _append_hand_history_cache(self, table_name: str, board: list, actions: list):
        self.hands_history_memory.append({
            "hand_id": len(self.hands_history_memory) + 1,
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "table_name": table_name,
            "board": "".join(board),
            "actions": deepcopy(actions),
        })

    @staticmethod
    def _merge_counter_maps(primary: dict | None, secondary: dict | None) -> dict:
        merged: dict[str, int] = {}
        for source in (primary or {}, secondary or {}):
            if not isinstance(source, dict):
                continue
            for key, value in source.items():
                normalized_key = str(key)
                merged[normalized_key] = int(merged.get(normalized_key, 0) or 0) + int(value or 0)
        return merged

    @staticmethod
    def _rewrite_hand_actions_player_name(actions: list | None, source_name: str, target_name: str) -> tuple[list, bool]:
        normalized_source = sanitize_player_name(source_name)
        normalized_target = sanitize_player_name(target_name)
        rewritten_actions: list = []
        changed = False

        for action in _coerce_json_array(actions):
            if not isinstance(action, dict):
                rewritten_actions.append(deepcopy(action))
                continue
            normalized_action = deepcopy(action)
            if sanitize_player_name(normalized_action.get("player") or "") == normalized_source:
                normalized_action["player"] = normalized_target
                changed = True
            rewritten_actions.append(normalized_action)

        return rewritten_actions, changed

    @classmethod
    def _merge_raw_stats(cls, target_raw_stats: dict | None, source_raw_stats: dict | None) -> dict:
        target_raw = _coerce_json_object(target_raw_stats)
        source_raw = _coerce_json_object(source_raw_stats)
        merged = deepcopy(source_raw)
        merged.update(deepcopy(target_raw))

        merged["observed_hands"] = int(target_raw.get("observed_hands", 0) or 0) + int(source_raw.get("observed_hands", 0) or 0)
        merged["aggressive_actions"] = int(target_raw.get("aggressive_actions", 0) or 0) + int(source_raw.get("aggressive_actions", 0) or 0)
        merged["passive_actions"] = int(target_raw.get("passive_actions", 0) or 0) + int(source_raw.get("passive_actions", 0) or 0)
        merged["fold_actions"] = int(target_raw.get("fold_actions", 0) or 0) + int(source_raw.get("fold_actions", 0) or 0)
        merged["action_counts"] = cls._merge_counter_maps(target_raw.get("action_counts"), source_raw.get("action_counts"))
        merged["street_counts"] = cls._merge_counter_maps(target_raw.get("street_counts"), source_raw.get("street_counts"))
        merged["rl_ready"] = bool(target_raw.get("rl_ready", False) or source_raw.get("rl_ready", False))

        for key in ("last_action", "last_street", "last_observed_street"):
            merged[key] = str(target_raw.get(key) or source_raw.get(key) or "")

        return merged

    @classmethod
    def _merge_profile_rows(cls, source_profile: dict | None, target_profile: dict | None, target_name: str) -> dict:
        source = deepcopy(source_profile or cls._new_memory_player(target_name))
        target = deepcopy(target_profile or cls._new_memory_player(target_name))
        last_seen = max(
            str(source.get("last_seen") or ""),
            str(target.get("last_seen") or ""),
        ) or None
        target_player_type = str(target.get("player_type") or "")
        source_player_type = str(source.get("player_type") or "")
        if target_player_type not in {"", "Unknown"}:
            player_type = target_player_type
        elif source_player_type not in {"", "Unknown"}:
            player_type = source_player_type
        else:
            player_type = "Unknown"

        return {
            "player_name": target_name,
            "hands_played": int(source.get("hands_played", 0) or 0) + int(target.get("hands_played", 0) or 0),
            "observed_hands": int(source.get("observed_hands", 0) or 0) + int(target.get("observed_hands", 0) or 0),
            "vpip_count": int(source.get("vpip_count", 0) or 0) + int(target.get("vpip_count", 0) or 0),
            "pfr_count": int(source.get("pfr_count", 0) or 0) + int(target.get("pfr_count", 0) or 0),
            "three_bet_count": int(source.get("three_bet_count", 0) or 0) + int(target.get("three_bet_count", 0) or 0),
            "cbet_count": int(source.get("cbet_count", 0) or 0) + int(target.get("cbet_count", 0) or 0),
            "player_type": player_type,
            "raw_stats": cls._merge_raw_stats(target.get("raw_stats"), source.get("raw_stats")),
            "last_seen": last_seen,
        }

    def _hydrate_profile_snapshot(self, profile: dict):
        profile = deepcopy(profile)
        raw_stats = _coerce_json_object(profile.get("raw_stats"))
        profile["raw_stats"] = raw_stats
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

    @staticmethod
    def _normalize_player_row(row: dict) -> dict:
        normalized = deepcopy(row or {})
        normalized["raw_stats"] = _coerce_json_object(normalized.get("raw_stats"))
        if normalized.get("last_seen") is not None:
            normalized["last_seen"] = str(normalized.get("last_seen"))
        return normalized

    @staticmethod
    def _normalize_hand_row(row: dict) -> dict:
        normalized = deepcopy(row or {})
        normalized["actions"] = _coerce_json_array(normalized.get("actions"))
        if normalized.get("timestamp") is not None:
            normalized["timestamp"] = str(normalized.get("timestamp"))
        return normalized

    async def _init_connection_codecs(self, conn):
        for type_name in ("json", "jsonb"):
            await conn.set_type_codec(
                type_name,
                schema="pg_catalog",
                encoder=json.dumps,
                decoder=json.loads,
                format="text",
            )

    async def _refresh_memory_cache_from_postgres(self):
        if self.backend != "postgres" or not self.pool:
            return

        async with self.pool.acquire() as conn:
            player_rows = await conn.fetch("SELECT * FROM players")
            hand_rows = await conn.fetch(
                "SELECT hand_id, timestamp, table_name, board, actions FROM hands_history ORDER BY hand_id"
            )

        self.players_memory = {}
        for row in player_rows:
            normalized_row = self._normalize_player_row(dict(row))
            player_name = str(normalized_row.get("player_name") or "").strip()
            if player_name:
                self.players_memory[player_name] = normalized_row

        self.hands_history_memory = [
            self._normalize_hand_row(dict(row))
            for row in hand_rows
        ]

    async def _repair_stringified_postgres_payloads(self):
        if self.backend != "postgres" or not self.pool:
            return

        async with self.pool.acquire() as conn:
            invalid_hand_rows = await conn.fetch(
                """
                SELECT hand_id, actions
                FROM hands_history
                WHERE jsonb_typeof(actions) = 'string'
                ORDER BY hand_id
                """
            )
            for row in invalid_hand_rows:
                repaired_actions = _coerce_json_array(row.get("actions"))
                await conn.execute(
                    "UPDATE hands_history SET actions = $2::jsonb WHERE hand_id = $1",
                    int(row["hand_id"]),
                    repaired_actions,
                )

            invalid_player_rows = await conn.fetch(
                """
                SELECT player_name, raw_stats
                FROM players
                WHERE jsonb_typeof(raw_stats) = 'string'
                ORDER BY player_name
                """
            )
            for row in invalid_player_rows:
                repaired_raw_stats = _coerce_json_object(row.get("raw_stats"))
                await conn.execute(
                    "UPDATE players SET raw_stats = $2::jsonb WHERE player_name = $1",
                    str(row["player_name"]),
                    repaired_raw_stats,
                )

        if invalid_hand_rows or invalid_player_rows:
            logger.warning(
                "Reparation automatique de %s mains et %s profils avec JSON stringifie en PostgreSQL.",
                len(invalid_hand_rows),
                len(invalid_player_rows),
            )

    def summarize_observation(self, limit: int = 5) -> dict:
        normalized_limit = max(1, int(limit or 5))
        players = [
            self._hydrate_profile_snapshot(player)
            for player in self.players_memory.values()
            if _is_observation_profile_name_supported(str(player.get("player_name") or ""))
        ]
        players.sort(
            key=lambda player: (
                int((player.get("derived_profile") or {}).get("observed_hands", 0) or 0),
                float((player.get("derived_profile") or {}).get("reliability", 0.0) or 0.0),
                str(player.get("last_seen") or ""),
                str(player.get("player_name") or ""),
            ),
            reverse=True,
        )
        last_seen = max(
            (str(player.get("last_seen") or "") for player in players if player.get("last_seen")),
            default="",
        )
        named_players = [
            player for player in players
            if not is_placeholder_player_name(str(player.get("player_name") or ""))
        ]
        top_profile_source = named_players or players
        return {
            "backend": self.backend,
            "persistence": self._persistence_snapshot(),
            "player_count": len(players),
            "observed_hands": sum(
                int((player.get("derived_profile") or {}).get("observed_hands", 0) or 0)
                for player in players
            ),
            "hands_recorded": len(self.hands_history_memory),
            "last_seen": last_seen or None,
            "top_profiles": [
                {
                    "player_name": str(player.get("player_name") or ""),
                    "player_type": str(player.get("player_type") or "Unknown"),
                    "observed_hands": int((player.get("derived_profile") or {}).get("observed_hands", 0) or 0),
                    "vpip_rate": float((player.get("derived_profile") or {}).get("vpip_rate", 0.0) or 0.0),
                    "pfr_rate": float((player.get("derived_profile") or {}).get("pfr_rate", 0.0) or 0.0),
                    "aggression_frequency": float((player.get("derived_profile") or {}).get("aggression_frequency", 0.0) or 0.0),
                    "reliability": float((player.get("derived_profile") or {}).get("reliability", 0.0) or 0.0),
                    "last_seen": player.get("last_seen"),
                }
                for player in top_profile_source[:normalized_limit]
            ],
        }

    def export_observation_dataset(self, player_limit: int = 50, hand_limit: int = 100) -> dict:
        normalized_player_limit = max(1, int(player_limit or 50))
        normalized_hand_limit = max(1, int(hand_limit or 100))
        players = [
            self._hydrate_profile_snapshot(player)
            for player in self.players_memory.values()
            if _is_observation_profile_name_supported(str(player.get("player_name") or ""))
        ]
        players.sort(
            key=lambda player: (
                int((player.get("derived_profile") or {}).get("observed_hands", 0) or 0),
                float((player.get("derived_profile") or {}).get("reliability", 0.0) or 0.0),
                str(player.get("last_seen") or ""),
                str(player.get("player_name") or ""),
            ),
            reverse=True,
        )
        hands = list(self.hands_history_memory)
        hands.sort(key=lambda hand: str(hand.get("timestamp") or ""), reverse=True)
        return {
            "format": "runtime_observation_v1",
            "version": "1",
            "exported_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "backend": self.backend,
            "persistence": self._persistence_snapshot(),
            "summary": self.summarize_observation(limit=min(normalized_player_limit, 10)),
            "players": players[:normalized_player_limit],
            "hands": deepcopy(hands[:normalized_hand_limit]),
        }

    async def connect(self):
        """Initialise le pool de connexion à la base de données."""
        if self.mode == "memory":
            self.backend = "memory"
            logger.info("Backend mémoire activé explicitement pour la base de données.")
            self._load_local_persistence()
            return

        if asyncpg is None:
            if self.mode == "postgres":
                raise RuntimeError("asyncpg n'est pas installé et le mode postgres a été explicitement demandé.")
            self._activate_memory_backend("asyncpg non installé")
            return

        try:
            self.pool = await asyncpg.create_pool(self.dsn, init=self._init_connection_codecs)
            self.backend = "postgres"
            logger.info("Connexion à PostgreSQL établie.")
            await self._init_schema()
            await self._repair_stringified_postgres_payloads()
            await self._refresh_memory_cache_from_postgres()
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
        player_name = _normalize_profile_name(player_name)
        if not player_name:
            return
        normalized_street = str(street or "UNKNOWN").upper()
        self._apply_observed_hand_cache(player_name, normalized_street)
        if self.backend == "memory":
            self._persist_local_state()
            return

        if not self.pool:
            return

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
        player_name = _normalize_profile_name(player_name)
        if not player_name:
            return
        action = str(action_data.get("action", "") or "").upper()
        street = str(action_data.get("street", "UNKNOWN") or "UNKNOWN").upper()
        action_aliases = set(action.replace("/", "_").split("_")) if action else set()
        is_raise_like = "RAISE" in action_aliases
        is_bet_like = "BET" in action_aliases
        is_call_like = "CALL" in action_aliases
        is_check_like = "CHECK" in action_aliases
        is_all_in = action == "ALL_IN"

        # Logique simplifiée VPIP/PFR
        default_is_vpip = 1 if is_call_like or is_raise_like or is_bet_like else 0
        default_is_pfr = 1 if is_raise_like or is_bet_like else 0
        is_vpip = int(action_data.get("counts_towards_vpip", default_is_vpip) or 0)
        is_pfr = int(action_data.get("counts_towards_pfr", default_is_pfr) or 0)
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
        self._apply_player_action_cache(
            player_name,
            action,
            street,
            is_vpip=is_vpip,
            is_pfr=is_pfr,
            is_aggressive=is_aggressive,
            is_passive=is_passive,
            is_fold=is_fold,
        )

        if self.backend == "memory":
            self._persist_local_state()
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
                    raw_stats_patch,
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
        self._append_hand_history_cache(table_name, board, actions)
        if self.backend == "memory":
            self._persist_local_state()
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
                await conn.execute(query, table_name, "".join(board), list(actions))
        except Exception as e:
            logger.error(f"Erreur SQL lors de la sauvegarde de la main: {e}")

    async def get_player_profile(self, player_name: str):
        """Récupère le profil d'un joueur pour l'injecter dans le solver Rust."""
        if self.backend == "memory":
            memory_profile = self.players_memory.get(player_name)
            if not memory_profile:
                return None
            profile = memory_profile
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

                profile = self._normalize_player_row(dict(row))
        return self._hydrate_profile_snapshot(profile)

    async def merge_player_profiles(self, source_name: str, target_name: str):
        normalized_source = str(source_name or "").strip()
        normalized_target = str(target_name or "").strip()
        if not normalized_source or not normalized_target or normalized_source == normalized_target:
            return

        if self.backend == "memory":
            source_profile = self.players_memory.get(normalized_source)
            if not source_profile:
                return
            target_profile = self.players_memory.get(normalized_target)
            merged_profile = self._merge_profile_rows(source_profile, target_profile, normalized_target)
            self.players_memory[normalized_target] = merged_profile
            self.players_memory.pop(normalized_source, None)
            for hand in self.hands_history_memory:
                actions = hand.get("actions") if isinstance(hand, dict) else None
                rewritten_actions, changed = self._rewrite_hand_actions_player_name(actions, normalized_source, normalized_target)
                if changed and isinstance(hand, dict):
                    hand["actions"] = rewritten_actions
            self._persist_local_state()
            return

        if not self.pool:
            return

        try:
            async with self.pool.acquire() as conn:
                source_row = await conn.fetchrow(
                    "SELECT * FROM players WHERE player_name = $1",
                    normalized_source,
                )
                if not source_row:
                    return
                target_row = await conn.fetchrow(
                    "SELECT * FROM players WHERE player_name = $1",
                    normalized_target,
                )
                merged_profile = self._merge_profile_rows(
                    self._normalize_player_row(dict(source_row)),
                    self._normalize_player_row(dict(target_row)) if target_row else None,
                    normalized_target,
                )
                await conn.execute(
                    """
                    INSERT INTO players (
                        player_name,
                        hands_played,
                        observed_hands,
                        vpip_count,
                        pfr_count,
                        three_bet_count,
                        cbet_count,
                        player_type,
                        raw_stats,
                        last_seen
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, COALESCE($10::timestamp, CURRENT_TIMESTAMP))
                    ON CONFLICT (player_name) DO UPDATE SET
                        hands_played = EXCLUDED.hands_played,
                        observed_hands = EXCLUDED.observed_hands,
                        vpip_count = EXCLUDED.vpip_count,
                        pfr_count = EXCLUDED.pfr_count,
                        three_bet_count = EXCLUDED.three_bet_count,
                        cbet_count = EXCLUDED.cbet_count,
                        player_type = EXCLUDED.player_type,
                        raw_stats = EXCLUDED.raw_stats,
                        last_seen = EXCLUDED.last_seen
                    """,
                    merged_profile["player_name"],
                    int(merged_profile.get("hands_played", 0) or 0),
                    int(merged_profile.get("observed_hands", 0) or 0),
                    int(merged_profile.get("vpip_count", 0) or 0),
                    int(merged_profile.get("pfr_count", 0) or 0),
                    int(merged_profile.get("three_bet_count", 0) or 0),
                    int(merged_profile.get("cbet_count", 0) or 0),
                    str(merged_profile.get("player_type") or "Unknown"),
                    merged_profile.get("raw_stats") or {},
                    _coerce_datetime_value(merged_profile.get("last_seen")),
                )
                hand_rows = await conn.fetch(
                    "SELECT hand_id, actions FROM hands_history WHERE actions::text LIKE $1",
                    f'%\"{normalized_source}\"%',
                )
                for hand_row in hand_rows:
                    rewritten_actions, changed = self._rewrite_hand_actions_player_name(
                        hand_row.get("actions"),
                        normalized_source,
                        normalized_target,
                    )
                    if not changed:
                        continue
                    await conn.execute(
                        "UPDATE hands_history SET actions = $2::jsonb WHERE hand_id = $1",
                        int(hand_row["hand_id"]),
                        rewritten_actions,
                    )
                await conn.execute(
                    "DELETE FROM players WHERE player_name = $1",
                    normalized_source,
                )
        except Exception as e:
            logger.error("Erreur SQL lors de la fusion du profil %s -> %s: %s", normalized_source, normalized_target, e)

    async def close(self):
        if self.backend == "memory":
            self._persist_local_state()
        if self.pool:
            await self.pool.close()
            logger.info("Connexion PostgreSQL fermée.")
        self.pool = None
