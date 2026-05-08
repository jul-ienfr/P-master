import asyncio
import uuid

import pytest


def run(coro):
    return asyncio.run(coro)


@pytest.mark.integration
@pytest.mark.postgres
def test_postgres_database_manager_persists_profiles_and_history(postgres_database_manager):
    manager = postgres_database_manager
    suffix = uuid.uuid4().hex[:8]
    player_name = f"it_postgres_player_{suffix}"
    table_name = f"it_postgres_table_{suffix}"

    async def scenario():
        await manager.record_observed_hand(player_name, street="preflop")
        await manager.update_player_action(
            player_name,
            {"action": "raise/bet", "street": "preflop"},
        )
        await manager.update_player_action(
            player_name,
            {"action": "call", "street": "flop"},
        )
        await manager.insert_hand_history(
            table_name,
            ["Ah", "Kd", "2c"],
            [{"player": player_name, "action": "RAISE/BET", "street": "PREFLOP"}],
        )

        profile = await manager.get_player_profile(player_name)

        assert manager.backend == "postgres"
        assert profile is not None
        assert profile["player_name"] == player_name
        assert profile["hands_played"] == 1
        assert profile["observed_hands"] == 1
        assert profile["vpip_count"] == 2
        assert profile["pfr_count"] == 1
        assert profile["derived_profile"]["observed_hands"] == 1
        assert profile["derived_profile"]["vpip_rate"] == 1.0
        assert profile["derived_profile"]["pfr_rate"] == 1.0
        assert profile["derived_profile"]["last_action"] == "CALL"
        assert profile["derived_profile"]["last_street"] == "FLOP"
        assert profile["derived_profile"]["last_observed_street"] == "PREFLOP"
        assert profile["derived_profile"]["street_counts"] == {"PREFLOP": 1, "FLOP": 1}
        assert profile["derived_profile"]["action_counts"] == {"RAISE/BET": 1, "CALL": 1}

        async with manager.pool.acquire() as conn:
            hand_row = await conn.fetchrow(
                "SELECT table_name, board, actions FROM hands_history WHERE table_name = $1 ORDER BY hand_id DESC LIMIT 1",
                table_name,
            )

            assert hand_row is not None
            assert hand_row["table_name"] == table_name
            assert hand_row["board"] == "AhKd2c"
            assert hand_row["actions"][0]["player"] == player_name

            await conn.execute("DELETE FROM hands_history WHERE table_name = $1", table_name)
            await conn.execute("DELETE FROM players WHERE player_name = $1", player_name)

    run(scenario())
