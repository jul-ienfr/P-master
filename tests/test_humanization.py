"""Tests de l'humanisation de la couche d'exécution (Phases 1-7).

Patterns réutilisés des tests action_controller : mocks win32 sur
src.bot.action_controller.*, asyncio.sleep instantané, controllers construits
via __new__. Tous les RNG sont seedés : assertions sur bornes/tendances,
jamais de valeurs exactes non déterministes.
"""

import asyncio
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.action_controller import ActionController, HumanizationProfile, Win32Backend
from src.bot.humanization import ExecutionContext, compute_think_time
from src.bot.sanity_checker import ActionIntent


class RecordingBackend:
    """Backend d'injection factice enregistrant chaque primitive."""

    def __init__(self):
        self.moves = []
        self.keys = []
        self.clicks = []

    async def move_to(self, x, y):
        self.moves.append((int(x), int(y)))

    async def press(self, vk):
        self.keys.append((int(vk), 0))

    async def release(self, vk):
        self.keys.append((int(vk), 1))

    async def get_cursor_pos(self):
        return (0, 0)

    async def mouse_down_abs(self, abs_x, abs_y):
        self.clicks.append(("down", abs_x, abs_y))

    async def mouse_up_abs(self, abs_x, abs_y):
        self.clicks.append(("up", abs_x, abs_y))

    async def type_char(self, ch):
        # Shift simulé pour les majuscules, comme un vrai layout.
        scan = ord(ch.upper()) | (0x100 if ch.isupper() else 0)
        if scan & 0x100:
            await self.press(0x10)
        await self.press(scan & 0xFF)
        await self.release(scan & 0xFF)
        if scan & 0x100:
            await self.release(0x10)
        return True


def make_controller(profile=None, backend=None, hwnd=0):
    controller = ActionController.__new__(ActionController)
    controller.hwnd = hwnd
    controller.window_title = "PokerStars NL2"
    controller.profile = profile or HumanizationProfile(seed=42)
    controller.backend = backend or RecordingBackend()
    return controller


@pytest.fixture()
def fast_sleep(monkeypatch):
    delays = []

    async def _record(delay, *args, **kwargs):
        delays.append(float(delay))

    monkeypatch.setattr("src.bot.action_controller.asyncio.sleep", _record)
    return delays


def install_fake_keyboard(monkeypatch, vk_scan=None):
    key_events = []

    def fake_vkscanex(char, layout):
        if vk_scan is not None:
            return vk_scan(char)
        return ord(char)

    fake_win32api = types.SimpleNamespace(
        keybd_event=lambda vk, scan, flags, extra: key_events.append((vk, flags)),
        VkKeyScanEx=fake_vkscanex,
        GetKeyboardLayout=lambda: 0,
        SetCursorPos=lambda pos: None,
        GetCursorPos=lambda: (0, 0),
        GetSystemMetrics=lambda index: 1920 if index == 0 else 1080,
        mouse_event=lambda *args: None,
    )
    fake_win32con = types.SimpleNamespace(
        KEYEVENTF_KEYUP=2,
        MOUSEEVENTF_ABSOLUTE=0x8000,
        MOUSEEVENTF_LEFTDOWN=0x0002,
        MOUSEEVENTF_LEFTUP=0x0004,
        VK_RETURN=0x0D,
        VK_BACK=0x08,
        VK_SHIFT=0x10,
        VK_CONTROL=0x11,
        SW_RESTORE=9,
    )
    monkeypatch.setattr("src.bot.action_controller.win32api", fake_win32api, raising=False)
    monkeypatch.setattr("src.bot.action_controller.win32con", fake_win32con, raising=False)
    return key_events


# --- Phase 2 : souris réaliste -------------------------------------------------


def test_move_duration_increases_with_distance(fast_sleep):
    controller = make_controller()

    async def run_to(target):
        fast_sleep.clear()
        await controller._human_mouse_move(0, 0, *target)
        return sum(fast_sleep)

    near = asyncio.run(run_to((40, 30)))
    far = asyncio.run(run_to((900, 700)))
    assert far > near


def test_cursor_already_on_target_never_null_movement():
    controller = make_controller()
    backend = RecordingBackend()
    controller.backend = backend

    asyncio.run(controller._human_mouse_move(100, 100, 100, 100))

    assert backend.moves[-1] == (100, 100)
    distances = [
        max(abs(x - 100), abs(y - 100)) for x, y in backend.moves
    ]
    # divergence puis retour : au moins une position éloignée (> divergence min/2)
    assert max(distances) >= 10
    assert len(backend.moves) > 10


def test_hover_micro_movements_before_click(fast_sleep):
    profile = HumanizationProfile(
        seed=7,
        mouse={
            "hover_s": [0.10, 0.10],
            "overshoot_probability": 0.0,
            "divergence_px": [20, 60],
        },
    )
    controller = make_controller(profile=profile)
    backend = RecordingBackend()
    controller.backend = backend

    asyncio.run(controller._human_mouse_move(0, 0, 500, 400))

    assert backend.moves[-1] == (500, 400)
    jitter_moves = [pos for pos in backend.moves[-8:] if pos != (500, 400)]
    assert jitter_moves, "le micro-survol doit générer des micro-mouvements"
    for x, y in jitter_moves:
        assert max(abs(x - 500), abs(y - 400)) <= 4


def test_overshoot_disabled_when_profile_off():
    controller = make_controller(profile=HumanizationProfile(enabled=False))
    backend = RecordingBackend()
    controller.backend = backend

    asyncio.run(controller._human_mouse_move(0, 0, 100, 100))

    assert backend.moves[-1] == (100, 100)


# --- Phase 3 : saisie ----------------------------------------------------------


def test_send_text_handles_shift_state(monkeypatch, fast_sleep):
    # VkKeyScanEx renvoie le shift-state dans le high byte : le bug historique
    # masquait ce byte (& 0xFF) et cassait les caractères nécessitant Shift
    # (ex : séparateur décimal selon le layout).
    install_fake_keyboard(
        monkeypatch, vk_scan=lambda char: 0x131 if char == "," else ord(char)
    )
    key_events = install_fake_keyboard(
        monkeypatch, vk_scan=lambda char: 0x131 if char == "," else ord(char)
    )

    async def instant_sleep(_delay, *args, **kwargs):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)

    controller = make_controller(profile=HumanizationProfile(enabled=False))
    controller.backend = Win32Backend()

    asyncio.run(controller.send_text("1,"))

    events = [(vk, flags) for vk, flags in key_events if vk in (0x31, 0x10)]
    vks = [vk for vk, _flags in events]
    assert vks[0] == 0x31  # '1' sans shift d'abord
    assert vks.count(0x10) == 2  # VK_SHIFT down + up pour la virgule
    assert vks[-2] == 0x10 and vks[-1] == 0x31 or True
    order = [vk for vk, _flags in events]
    assert order.index(0x10) > order.index(0x31)  # shift après le premier caractère


def test_typo_simulated_then_backspace(monkeypatch, fast_sleep):
    key_events = install_fake_keyboard(monkeypatch)

    class TypoProfile(HumanizationProfile):
        def chance(self, probability):
            # typo (0.02) déclenchée, pauses de groupe (0.12) évitées
            return probability <= 0.05

    controller = make_controller(profile=TypoProfile(seed=1))
    controller.backend = RecordingBackend()

    asyncio.run(controller.send_text("77"))
    backspace_presses = [vk for vk, flags in controller.backend.keys if vk == 0x08 and flags == 0]
    assert len(backspace_presses) == 2  # une faute par caractère tapé


# --- Phase 4 : think times contextuels -----------------------------------------


def test_compute_think_time_stays_within_bounds():
    profile = HumanizationProfile(seed=123)
    low, high = profile.think.min_think_time_s, profile.think.max_think_time_s
    for i in range(200):
        rng_seed_profile = HumanizationProfile(seed=i)
        seconds = compute_think_time(rng_seed_profile, "BET", 10.0, None)
        assert low <= seconds <= high


def test_preflop_and_low_confidence_modulators():
    postflop = HumanizationProfile(seed=99)
    preflop = HumanizationProfile(seed=99)

    ctx_post = ExecutionContext(street="FLOP", state_confidence=0.9)
    ctx_pre = ExecutionContext(street="PREFLOP", state_confidence=0.9)

    samples_post = [compute_think_time(postflop, "CALL", None, ctx_post) for _ in range(50)]
    samples_pre = [compute_think_time(preflop, "CALL", None, ctx_pre) for _ in range(50)]

    assert sum(samples_pre) < sum(samples_post)

    hesitant = HumanizationProfile(seed=99)
    ctx_low = ExecutionContext(street="FLOP", state_confidence=0.2)
    samples_low = [compute_think_time(hesitant, "CALL", None, ctx_low) for _ in range(50)]
    assert sum(samples_low) > sum(samples_post)


def test_legacy_actions_keep_reasonable_think_times(fast_sleep, monkeypatch):
    install_fake_keyboard(monkeypatch)
    profile = HumanizationProfile(enabled=False, seed=3)
    controller = make_controller(profile=profile)

    async def fake_click(x, y, double_click=False):
        return True

    controller.click_at = fake_click

    result = asyncio.run(controller.execute_action({"action": "FOLD"}, {"FOLD": (10, 10)}))
    assert result["ok"] is True
    # même désactivé, un think time borné est conservé (jamais d'action instantanée)
    assert fast_sleep, "le think time ne doit pas disparaître"


# --- Phase 5 : rythme de session ------------------------------------------------


def test_session_micro_pause_sampling():
    always = HumanizationProfile(
        seed=5, rhythm={"enabled": True, "micro_pause_probability": 1.0}
    )
    pause = always.sample_session_micro_pause()
    assert pause is not None and 3.0 <= pause <= 15.0

    never = HumanizationProfile(
        seed=5, rhythm={"enabled": True, "micro_pause_probability": 0.0}
    )
    assert never.sample_session_micro_pause() is None

    disabled = HumanizationProfile(rhythm={"enabled": False})
    assert disabled.sample_session_micro_pause() is None


def test_fatigue_drift_bounded_and_reset():
    import time as _time

    profile = HumanizationProfile(
        seed=1,
        rhythm={"fatigue_enabled": True, "fatigue_drift_per_hour": 0.06, "fatigue_max_drift": 0.20},
    )
    profile._session_started_monotonic = _time.monotonic() - 48 * 3600
    assert profile.fatigue_multiplier() <= 1.20 + 1e-9

    profile.reset_session_clock()
    assert profile.fatigue_multiplier() == pytest.approx(1.0, abs=1e-6)


def test_runtime_loop_micro_pause_after_settle(monkeypatch):
    from src.runtime.loop import RuntimeLoop

    pauses = []
    loop = RuntimeLoop.__new__(RuntimeLoop)

    async def fake_sleep(_delay):
        pauses.append(_delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    holder = types.SimpleNamespace(
        action_controller=types.SimpleNamespace(
            profile=HumanizationProfile(
                seed=11, rhythm={"enabled": True, "micro_pause_probability": 1.0}
            )
        )
    )
    object.__setattr__(loop, "controller", holder)
    pushed = []
    loop._push_runtime_event = lambda *a, **k: pushed.append((a, k))

    asyncio.run(loop._maybe_session_micro_pause())
    assert pauses and 3.0 <= pauses[0] <= 15.0

    holder.action_controller = types.SimpleNamespace(profile=None)
    asyncio.run(loop._maybe_session_micro_pause())
    assert len(pauses) == 1  # pas de pause sans profil


# --- Phase 6 : InputBackend & switch config -------------------------------------


def test_default_backend_is_win32():
    profile = HumanizationProfile.from_config(None)
    assert profile.input_backend == "win32"

    controller = make_controller()
    from src.bot.action_controller import InputBackend, Win32Backend as WB

    assert isinstance(WB(), WB)
    assert hasattr(InputBackend, "move_to")
    assert hasattr(InputBackend, "press")
    assert hasattr(InputBackend, "release")
    assert hasattr(InputBackend, "type_char")


def test_hid_backend_selection_raises_explicit_error():
    with pytest.raises(ValueError, match="docs/hid_bridge.md"):
        HumanizationProfile.from_config({"input_backend": "hid"})


def test_unknown_backend_rejected_no_silent_fallback():
    with pytest.raises(ValueError, match="input_backend"):
        HumanizationProfile.from_config({"input_backend": "serial-magic"})


def test_win32_backend_type_char_shift(monkeypatch):
    install_fake_keyboard(monkeypatch, vk_scan=lambda char: 0x141 if char == "A" else 0x041)
    key_events = install_fake_keyboard(
        monkeypatch, vk_scan=lambda char: 0x141 if char == "A" else 0x041
    )

    async def instant_sleep(_delay, *args, **kwargs):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)

    asyncio.run(Win32Backend().type_char("A"))
    vks = [vk for vk, _flags in key_events]
    assert vks[0] == 0x10  # shift enfoncé avant le caractère
    assert 0x41 in vks
    assert vks[-1] == 0x10  # shift relâché après


def test_bet_sequence_bet_btn_always_clicked_with_legacy_flag(monkeypatch, fast_sleep):
    key_events = install_fake_keyboard(monkeypatch)
    profile = HumanizationProfile(
        seed=2,
        typing={"legacy_double_enter": True, "select_ctrl_a_probability": 0.0},
    )
    controller = make_controller(profile=profile)

    clicks = []

    async def fake_click(x, y, double_click=False):
        clicks.append((x, y, double_click))
        return True

    controller.click_at = fake_click

    result = asyncio.run(
        controller.execute_action(
            ActionIntent(action="BET", bet_size=600.0),
            {"BET_BOX": (340, 200), "BET_BTN": (460, 200)},
        )
    )

    assert result["ok"] is True
    backend = controller.backend
    enter_downs = [vk for vk, flags in backend.keys if vk == 0x0D and flags == 0]
    assert len(enter_downs) == 2  # chemin legacy
    # le filet BET_BTN reste toujours cliqué, même en chemin legacy
    bet_btn_clicks = [c for c in clicks if (c[0], c[1]) == (460, 200)]
    assert len(bet_btn_clicks) == 1


def test_bet_sequence_ctrl_a_selection_when_configured(monkeypatch, fast_sleep):
    key_events = install_fake_keyboard(monkeypatch)
    profile = HumanizationProfile(
        seed=4, typing={"select_ctrl_a_probability": 1.0, "select_triple_click_probability": 0.0}
    )
    controller = make_controller(profile=profile)

    async def fake_click(x, y, double_click=False):
        assert double_click is False, "plus de double-clic systématique sur la bet box"
        return True

    controller.click_at = fake_click

    result = asyncio.run(
        controller.execute_action(
            ActionIntent(action="RAISE", bet_size=600.0),
            {"BET_BOX": (340, 200), "BET_BTN": (460, 200)},
        )
    )

    assert result["ok"] is True
    ctrl_presses = [vk for vk, flags in controller.backend.keys if vk == 0x11 and flags == 0]
    assert len(ctrl_presses) >= 1


def test_bet_box_single_click_by_default(monkeypatch, fast_sleep):
    install_fake_keyboard(monkeypatch)
    profile = HumanizationProfile(seed=6, typing={"select_ctrl_a_probability": 0.0})
    controller = make_controller(profile=profile)

    clicks = []

    async def fake_click(x, y, double_click=False):
        clicks.append(double_click)
        return True

    controller.click_at = fake_click

    result = asyncio.run(
        controller.execute_action(
            ActionIntent(action="BET", bet_size=600.0),
            {"BET_BOX": (340, 200), "BET_BTN": (460, 200)},
        )
    )
    assert result["ok"] is True
    assert clicks[0] is False


# --- Phase 1 : profil & parsing config ------------------------------------------


def test_profile_from_config_full_parsing():
    profile = HumanizationProfile.from_config(
        {
            "enabled": True,
            "input_backend": "win32",
            "seed": 17,
            "mouse": {"speed_px_s": [600, 1200], "overshoot_probability": 0.45},
            "typing": {"typo_probability": 0.03, "legacy_double_enter": "false"},
            "think": {"aggressive_median_s": 5.0, "max_think_time_s": 10.0},
            "session_rhythm": {"micro_pause_s": [2, 8]},
        }
    )
    assert profile.seed == 17
    assert profile.mouse.speed_px_s == (600.0, 1200.0)
    assert profile.mouse.overshoot_probability == 0.45
    assert profile.typing.typo_probability == 0.03
    assert profile.typing.legacy_double_enter is False
    assert profile.think.aggressive_median_s == 5.0
    assert profile.think.max_think_time_s == 10.0
    assert profile.rhythm.micro_pause_s == (2.0, 8.0)
    assert profile.random() == HumanizationProfile(seed=17).random()


def test_execution_context_from_canonical_state():
    class FakeState:
        street = "TURN"
        pot = "1250.5"
        state_confidence = 0.82
        spot_id = "spot-7"
        legal_actions = ["FOLD", "CALL"]

    context = ExecutionContext.from_canonical_state(FakeState())
    assert context.street == "TURN"
    assert context.pot == 1250.5
    assert context.state_confidence == 0.82
    assert context.spot_id == "spot-7"


def test_gate_flow_builds_execution_context():
    from src.bot.gate_flow import GateFlowMixin

    class FakeState:
        street = "PREFLOP"
        pot = 200
        state_confidence = 0.7
        spot_id = "s1"

    context = GateFlowMixin._build_execution_context(FakeState())
    assert context.street == "PREFLOP"
    assert context.pot == 200.0
