"""Tests du suivi de ranges villain (ratchet coverage, module V2 legacy)."""

from types import SimpleNamespace

from poker.decisionmaker.range_tracker import (
    DEFAULT_RANGE,
    PostflopAction,
    PreflopAction,
    RangeTrackerManager,
    VillainRange,
    _board_texture,
    _expand_token,
    _token_features,
    _token_rank,
)


def test_expand_token_handles_suited_spans_and_pairs():
    # Quirk legacy : bornes inversées dans _expand_token -> un span "A5s-A2s"
    # ne produit que la borne haute. Documenté tel quel (module archivé).
    assert _expand_token("A5s-A2s") == ["A5s"]
    # Paires de rangs différents : première lettre distincte -> non expansé.
    assert _expand_token("77-55") == ["77", "55"]
    assert _expand_token("AKs") == ["AKs"]
    # Longueurs incompatibles : tokens bruts.
    assert _expand_token("AK-QQ") == ["AK", "QQ"]


def test_token_rank_orders_pairs_above_kickers():
    assert _token_rank("AA") > _token_rank("KK")
    assert _token_rank("AKs") > _token_rank("AKo")
    assert _token_rank("") == (-1, -1, 0)


def test_token_features_flags():
    features = _token_features("AA")
    assert features["pair"] is True and features["premium"] is True

    ak = _token_features("AKs")
    assert ak["suited"] is True and ak["broadway"] is True and ak["premium"] is True

    a5 = _token_features("A5s")
    assert a5["wheel_ace"] is True

    connector = _token_features("76s")
    assert connector["connector"] is True


def test_board_texture_paired_monotone_connected():
    texture = _board_texture(["AH", "AD", "7C"])
    assert texture["paired"] is True

    monotone = _board_texture(["2H", "9H", "KH"])
    assert monotone["monotone"] is True

    two_tone = _board_texture(["2H", "9H", "KC"])
    assert two_tone["two_tone"] is True

    connected = _board_texture(["8D", "9C", "TH"])
    assert connected["connected"] is True
    assert connected["high_card_count"] == 1


def test_villain_range_seeds_sorted_weights():
    vr = VillainRange(position_utg=0, current_range="KK,AA")
    assert list(vr.weighted_tokens) == ["AA", "KK"]
    assert all(weight == 1.0 for weight in vr.weighted_tokens.values())


def test_update_preflop_narrows_to_action_range():
    vr = VillainRange(position_utg=0)
    vr.update_preflop(PreflopAction.THREE_BET)
    assert vr.preflop_action == PreflopAction.THREE_BET
    assert set(vr.weighted_tokens) == {"AA", "KK", "QQ", "AKs", "AKo"}
    assert "preflop:three_bet" in vr.action_history


def test_update_postflop_bet_boosts_premiums_and_fold_empties():
    vr = VillainRange(position_utg=2)
    before = dict(vr.weighted_tokens)

    vr.update_postflop(PostflopAction.BET, board=["AH", "KD", "2C"], street="Flop")
    # DEFAULT_RANGE ne contient pas de premiums : tout est dévalué ou évincé.
    assert vr.weighted_tokens.get("22", 0.0) < before.get("22", 1.0)

    vr.update_postflop(PostflopAction.FOLD, board=["AH", "KD", "2C"], street="Flop")
    assert vr.weighted_tokens == {}


def test_get_range_string_formats_partial_weights():
    vr = VillainRange(position_utg=0)
    vr.weighted_tokens = {"AA": 1.0, "KK": 0.75}
    text = vr.get_range_string()
    assert "AA" in text
    assert "KK:0.75" in text

    vr.weighted_tokens = {}
    assert vr.get_range_string() == "22:0.01"


def test_calibration_row_shape():
    vr = VillainRange(position_utg=1)
    vr.update_preflop(PreflopAction.OPEN_RAISE)
    row = vr.calibration_row(board=["2C", "7D", "JH"], street="Flop")
    assert row["position_utg"] == 1
    assert row["street"] == "Flop"
    assert row["preflop_action"] == "open_raise"
    assert row["range_size"] > 0
    assert len(row["top_tokens"]) <= 8


def test_reset_restores_default_range():
    vr = VillainRange(position_utg=0)
    vr.update_preflop(PreflopAction.LIMP)
    vr.reset()
    fresh = VillainRange(position_utg=0)
    assert vr.current_range == fresh.current_range
    assert set(vr.weighted_tokens) == set(fresh.weighted_tokens)
    assert vr.preflop_action is None
    assert vr.action_history == []


def _make_table(game_id="g1", board=None, stage="PreFlop", players=None, **extra):
    kwargs = dict(
        GameID=game_id,
        cardsOnTable=board or [],
        gameStage=stage,
        totalPotValue=10.0,
        minCall=0.0,
        minBet=0.0,
        position_utg_plus=0,
        total_players=6,
        other_players=players or [],
        first_raiser_utg=0,
        first_caller_utg=None,
        second_raiser_utg=None,
        other_player_has_initiative=False,
    )
    kwargs.update(extra)
    return SimpleNamespace(**kwargs)


def test_manager_creates_trackers_and_dedupes_by_fingerprint():
    manager = RangeTrackerManager()
    table = _make_table(players=[{"status": 1, "utg_position": 0}])

    manager.update_from_table(table)
    assert set(manager.trackers) == {0}
    tracker = manager.trackers[0]
    assert tracker.preflop_action == PreflopAction.OPEN_RAISE

    # Même état : aucun changement (fingerprint identique).
    actions_before = list(tracker.action_history)
    manager.update_from_table(table)
    assert tracker.action_history == actions_before


def test_manager_resets_on_new_game_id():
    manager = RangeTrackerManager()
    manager.update_from_table(_make_table(game_id="g1", players=[{"status": 1}]))
    assert manager.trackers

    manager.update_from_table(_make_table(game_id="g2", players=[{"status": 1}]))
    assert set(manager.trackers) == {0}


def test_manager_infers_postflop_actions():
    manager = RangeTrackerManager()

    check_table = _make_table(
        game_id="g1",
        board=["2C", "7D", "JH"],
        stage="Flop",
        players=[{"status": 1}],
        minCall=0.0,
    )
    manager.update_from_table(check_table)
    assert manager.trackers[0].postflop_actions[-1] == PostflopAction.CHECK

    call_table = _make_table(
        game_id="g1",
        board=["2C", "7D", "JH"],
        stage="Turn",
        players=[{"status": 1}],
        minCall=4.0,
    )
    manager.update_from_table(call_table)
    assert manager.trackers[0].postflop_actions[-1] == PostflopAction.CALL

    fold_table = _make_table(
        game_id="g1",
        board=["2C", "7D", "JH"],
        stage="River",
        players=[{"status": 0}],
        minCall=4.0,
    )
    manager.update_from_table(fold_table)
    assert manager.trackers[0].postflop_actions[-1] == PostflopAction.FOLD


def test_manager_primary_villain_prefers_tightest_range():
    manager = RangeTrackerManager()
    tight = VillainRange(position_utg=0, current_range="AA,KK")
    loose = VillainRange(position_utg=3, current_range=DEFAULT_RANGE)
    manager.trackers = {0: tight, 1: loose}

    assert manager.get_primary_villain_state() is tight
    assert manager.get_primary_villain_range() == tight.get_range_string()


def test_set_calibration_profile_propagates():
    manager = RangeTrackerManager()
    manager.update_from_table(_make_table(players=[{"status": 1}]))
    profile = {"flop:bet": 1.2}

    manager.set_calibration_profile(profile)
    assert manager.trackers[0].calibration_profile == profile
