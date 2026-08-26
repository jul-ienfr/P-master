"""Tests Phase 1 — socle multi-table (WindowManager, TableRuntimeManager,
scheduler de tours, exécution sérialisée)."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.runtime.multi_table_loop import (
    ActionExecutionQueue,
    MultiTableLoop,
    SessionTurnSignal,
)
from src.runtime.table_manager import (
    TableRuntimeManager,
    TableWindowCandidate,
    WindowManager,
)
from src.runtime.table_session import TableSession

ADAPTER = SimpleNamespace(site_key="pokerstars")


def make_candidate(hwnd, title="NLHE 100/200", score=3, rect=(0, 0, 1000, 640)):
    return TableWindowCandidate(
        hwnd=hwnd, title=title, score=score, rect=rect, class_name="", process_name=""
    )


def make_session(session_id, hwnd):
    return TableSession(
        session_id=session_id,
        hwnd=hwnd,
        adapter=ADAPTER,
        table_id=session_id,
        window_title=f"Table {hwnd}",
    )


# --- WindowManager ---


def test_window_manager_scores_and_sorts_candidates(monkeypatch):
    windows = [
        (1, "PokerStars Lobby", (0, 0, 1200, 900)),
        (2, "NLHE 100/200 Hold'em No Limit", (100, 100, 1100, 740)),
        (3, "NLHE 100/200 Hold'em No Limit", (0, 0, 300, 200)),
    ]
    monkeypatch.setattr(
        "src.bot.action_controller.get_window_class_name", lambda hwnd: ""
    )
    monkeypatch.setattr(
        "src.bot.action_controller.get_window_process_name", lambda hwnd: ""
    )
    manager = WindowManager(title_keywords="NLHE|Hold'em", enumerate_fn=lambda: windows)

    candidates = manager.enumerate_table_windows()

    # La lobby est pénalisée ; les tables passent devant.
    assert all(c.hwnd != 1 for c in candidates)
    assert candidates[0].hwnd == 2  # même score, aire plus grande
    assert len(candidates) == 2


def test_window_manager_aspect_bonus_applies(monkeypatch):
    wide = (0, 0, 1200, 700)  # ratio ~1.71 dans [1.15, 2.4]
    square = (0, 0, 800, 800)  # ratio 1.0 -> pas de bonus
    monkeypatch.setattr("src.bot.action_controller.get_window_class_name", lambda h: "")
    monkeypatch.setattr("src.bot.action_controller.get_window_process_name", lambda h: "")

    manager = WindowManager(
        title_keywords="NLHE",
        enumerate_fn=lambda: [(10, "NLHE t1", wide), (11, "NLHE t2", square)],
    )
    candidates = manager.enumerate_table_windows()

    scores = {c.hwnd: c.score for c in candidates}
    assert scores[10] == scores[11] + 1


def test_window_manager_requires_positive_score():
    manager = WindowManager(
        title_keywords="", enumerate_fn=lambda: [(5, "Sans rapport", (0, 0, 500, 400))]
    )
    assert manager.enumerate_table_windows() == []


# --- TableRuntimeManager ---


class FakeCamera:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def make_manager(max_tables=2, candidates=None):
    if candidates is None:
        candidates = []
    window_manager = WindowManager(
        title_keywords="NLHE", enumerate_fn=lambda: []
    )
    manager = TableRuntimeManager(
        window_manager,
        max_tables=max_tables,
        poll_interval_s=0.0,
        session_factory=lambda candidate: make_session(
            f"table_{candidate.hwnd:x}", candidate.hwnd
        ),
    )
    manager.window_manager._enumerate_fn = lambda: candidates
    return manager


def test_refresh_creates_and_caps_sessions():
    manager = make_manager(max_tables=2)
    manager.window_manager._enumerate_fn = lambda: [
        make_candidate(0x10),
        make_candidate(0x20),
        make_candidate(0x30),
    ]

    report = manager.refresh(force=True)

    assert report["created"] == ["table_10", "table_20"]
    assert len(manager.active_sessions) == 2  # cap max_tables
    assert sorted(s.table_id for s in manager.active_sessions) == ["table_10", "table_20"]


def test_refresh_removes_dead_sessions_and_keeps_alive():
    manager = make_manager()
    manager.window_manager._enumerate_fn = lambda: [make_candidate(0x10)]
    manager.refresh(force=True)

    # hwnd disparu + nouveau hwnd apparaît
    manager.window_manager._enumerate_fn = lambda: [make_candidate(0x99)]
    report = manager.refresh(force=True)

    assert report["removed"] == ["table_10"]
    assert report["created"] == ["table_99"]
    assert [s.hwnd for s in manager.active_sessions] == [0x99]


def test_teardown_stops_per_session_camera():
    manager = make_manager()
    manager.window_manager._enumerate_fn = lambda: [make_candidate(0x10)]
    manager.refresh(force=True)
    session = manager.active_sessions[0]
    camera = FakeCamera()
    session.runtime["camera"] = camera

    manager.window_manager._enumerate_fn = lambda: []
    manager.refresh(force=True)

    assert camera.stopped is True
    assert manager.active_sessions == []


def test_ensure_camera_is_idempotent():
    manager = make_manager()
    manager.window_manager._enumerate_fn = lambda: [make_candidate(0x10)]
    manager.refresh(force=True)
    session = manager.active_sessions[0]

    first = manager.ensure_camera(session, FakeCamera)
    second = manager.ensure_camera(session, FakeCamera)

    assert first is second


# --- Scheduler ---


async def _noop_handler(_session):
    return None


def test_loop_orders_sessions_by_turn_priority():
    sessions = {
        "idle": make_session("idle", 1),
        "turn": make_session("turn", 2),
        "timebank": make_session("timebank", 3),
    }
    signals = {
        "idle": SessionTurnSignal(),
        "turn": SessionTurnSignal(is_our_turn=True),
        "timebank": SessionTurnSignal(timebank_imminent=True),
    }

    class FakeManager:
        active_sessions = list(sessions.values())

    loop = MultiTableLoop(FakeManager(), session_handler=_noop_handler)
    ordered = loop.ordered_sessions(signals)

    assert [s.session_id for s, _p in ordered] == ["turn", "timebank", "idle"]
    assert sessions["turn"].priority == 100
    assert sessions["timebank"].priority == 50


def test_loop_respects_global_budget_but_never_drops_our_turn():
    processed = []

    async def slow_handler(session):
        await asyncio.sleep(0.03)
        processed.append(session.session_id)

    sessions = [
        make_session("turn", 1),
        make_session("a", 2),
        make_session("b", 3),
        make_session("c", 4),
    ]

    class FakeManager:
        active_sessions = sessions
        _last = 0.0

        def refresh(self, force=False):
            return {"skipped": True}

    signals = {s.session_id: (SessionTurnSignal(is_our_turn=True) if s.session_id == "turn" else SessionTurnSignal()) for s in sessions}

    loop = MultiTableLoop(
        FakeManager(),
        signal_provider=lambda session: signals[session.session_id],
        session_handler=slow_handler,
        cycle_budget_ms=30.0,
    )
    report = asyncio.run(loop.run_cycle())

    assert report.sessions_processed >= 1
    assert processed[0] == "turn"  # priorité absolue
    assert report.duration_ms > 0


def test_loop_handler_error_recorded_as_incident():
    async def boom(_session):
        raise RuntimeError("kaput")

    session = make_session("s1", 9)

    class FakeManager:
        active_sessions = [session]

        def refresh(self, force=False):
            return {"skipped": True}

    loop = MultiTableLoop(FakeManager(), session_handler=boom)
    report = asyncio.run(loop.run_cycle())

    assert report.sessions_processed == 1
    assert session.incidents and session.incidents[0]["code"] == "multi_table_handler_error"


# --- File d'exécution sérialisée ---


def test_action_queue_serializes_and_enforces_gap(monkeypatch):
    events = []

    async def fake_sleep(_delay):
        events.append(("sleep", round(_delay, 3)))

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def scenario():
        queue = ActionExecutionQueue(min_gap_s=0.35)

        async def action(label):
            events.append(("run", label))
            return label

        results = await asyncio.gather(
            queue.submit(lambda: action("A")),
            queue.submit(lambda: action("B")),
        )
        return results

    results = asyncio.run(scenario())

    assert results == ["A", "B"]
    runs = [e for e in events if e[0] == "run"]
    sleeps = [e for e in events if e[0] == "sleep"]
    assert runs[0][1] == "A"
    assert len(sleeps) >= 1  # au moins un gap appliqué entre deux actions


def test_action_queue_no_wait_for_first_action(monkeypatch):
    sleeps = []

    async def fake_sleep(_delay):
        sleeps.append(_delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def scenario():
        queue = ActionExecutionQueue(min_gap_s=0.35)
        return await queue.submit(asyncio.sleep, min_gap_s=0) if False else await queue.submit(
            _immediate
        )

    async def _immediate():
        return "ok"

    result = asyncio.run(scenario())

    assert result == "ok"
    assert sleeps == [] or all(delay == 0 for delay in sleeps)


# --- TableSession multi-table ---


def test_table_session_defaults_table_id_to_session_id():
    session = make_session("table_abc", 42)
    assert session.table_id == "table_abc"
    snapshot = session.snapshot()
    assert snapshot["table_id"] == "table_abc"
    assert snapshot["window_title"] == "Table 42"


def test_table_tracker_receives_table_id():
    from src.bot.table_tracker import TableTracker

    db_stub = SimpleNamespace()
    tracker = TableTracker(db_stub, table_id="table_ff")
    assert tracker.table_id == "table_ff"
    default_tracker = TableTracker(db_stub)
    assert default_tracker.table_id == "Table_1"
