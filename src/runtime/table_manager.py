"""Socle multi-table natif (Phase 1).

- `WindowManager` : énumération périodique de TOUTES les fenêtres tables
  candidates avec scoring pondéré (titre, classe, process, aspect-ratio).
- `TableRuntimeManager` : cycle de vie des `TableSession` (création,
  suppression à chaud, lock par hwnd) et attach des ressources légères par
  session (capture WGC dédiée + tracker). Les ressources lourdes (modèle
  YOLO, engines OCR, DB, decision maker) sont partagées.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.bot.action_controller import (
    _parse_window_title_keywords,
    build_site_profile_matchers,
    get_window_class_name,
    get_window_process_name,
    score_window_signals,
)
from src.runtime.table_session import TableSession
from src.vision.site_adapter import get_active_adapter

logger = logging.getLogger(__name__)

try:
    import win32gui

    WIN32GUI_AVAILABLE = True
except ImportError:  # pragma: no cover - plateforme non Windows
    win32gui = None  # type: ignore[assignment]
    WIN32GUI_AVAILABLE = False

# Bonus d'aspect-ratio : une fenêtre table est typiquement paysage modéré.
_ASPECT_MIN = 1.15
_ASPECT_MAX = 2.4


@dataclass(frozen=True)
class TableWindowCandidate:
    hwnd: int
    title: str
    rect: tuple[int, int, int, int]
    score: int
    class_name: str
    process_name: str

    @property
    def area(self) -> int:
        left, top, right, bottom = self.rect
        return max(0, right - left) * max(0, bottom - top)


class WindowManager:
    """Énumération scorée des fenêtres tables candidates."""

    def __init__(
        self,
        title_keywords: str = "",
        site_profiles: dict[str, Any] | None = None,
        enumerate_fn: Callable | None = None,
    ):
        self.title_keywords = str(title_keywords or "")
        self.site_profiles = dict(site_profiles or {})
        self._keywords = _parse_window_title_keywords(self.title_keywords)
        self._matchers = build_site_profile_matchers(self.site_profiles)
        self._enumerate_fn = enumerate_fn

    def _enumerate_windows(self) -> list[tuple[int, str, tuple[int, int, int, int]]]:
        if self._enumerate_fn is not None:
            return list(self._enumerate_fn())
        if not WIN32GUI_AVAILABLE:
            return []
        candidates: list[tuple[int, str, tuple[int, int, int, int]]] = []

        def callback(hwnd, _context):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if not title.strip():
                return
            try:
                rect = win32gui.GetWindowRect(hwnd)
            except Exception:
                return
            candidates.append((int(hwnd), title, tuple(int(v) for v in rect)))

        try:
            win32gui.EnumWindows(callback, None)
        except Exception as exc:
            logger.warning("EnumWindows a échoué: %s", exc)
        return candidates

    @staticmethod
    def _aspect_bonus(rect: tuple[int, int, int, int]) -> int:
        left, top, right, bottom = rect
        width = max(0, right - left)
        height = max(0, bottom - top)
        if width < 400 or height < 300:
            return 0
        ratio = width / float(height)
        return 1 if _ASPECT_MIN <= ratio <= _ASPECT_MAX else 0

    def score_candidate(
        self, hwnd: int, title: str, rect: tuple[int, int, int, int]
    ) -> TableWindowCandidate | None:
        score, _detail = score_window_signals(title, self._keywords, self._matchers, hwnd=hwnd)
        if score <= 0:
            return None
        # L'aspect-ratio n'est qu'un bonus : il ne crée pas de candidat à lui seul.
        score += self._aspect_bonus(rect)
        return TableWindowCandidate(
            hwnd=int(hwnd),
            title=title,
            rect=tuple(int(v) for v in rect),
            score=int(score),
            class_name=get_window_class_name(hwnd),
            process_name=get_window_process_name(hwnd),
        )

    def enumerate_table_windows(self) -> list[TableWindowCandidate]:
        scored: list[TableWindowCandidate] = []
        for item in self._enumerate_windows():
            if isinstance(item, TableWindowCandidate):
                scored.append(item)
                continue
            hwnd, title, rect = item
            candidate = self.score_candidate(hwnd, title, rect)
            if candidate is not None:
                scored.append(candidate)
        scored.sort(key=lambda item: (item.score, item.area), reverse=True)
        return scored


def default_session_factory(candidate: TableWindowCandidate) -> TableSession:
    adapter = get_active_adapter("pokerstars")
    session_id = f"table_{candidate.hwnd:x}"
    return TableSession(
        session_id=session_id,
        hwnd=candidate.hwnd,
        adapter=adapter,
        table_id=session_id,
        window_title=candidate.title,
        metadata={"score": candidate.score},
    )


class TableRuntimeManager:
    """Création/destruction des sessions par table, cap `max_tables`."""

    def __init__(
        self,
        window_manager: WindowManager,
        *,
        max_tables: int = 4,
        poll_interval_s: float = 1.0,
        session_factory: Callable[[TableWindowCandidate], TableSession] | None = None,
    ):
        self.window_manager = window_manager
        self.max_tables = max(1, int(max_tables))
        self.poll_interval_s = max(0.1, float(poll_interval_s))
        self.session_factory = session_factory or default_session_factory
        self.sessions: dict[str, TableSession] = {}
        self._last_refresh_monotonic: float = 0.0

    @property
    def active_sessions(self) -> list[TableSession]:
        return list(self.sessions.values())

    def refresh(self, *, force: bool = False, now: float | None = None) -> dict[str, Any]:
        now = time.monotonic() if now is None else float(now)
        if not force and (now - self._last_refresh_monotonic) < self.poll_interval_s:
            return {"created": [], "removed": [], "kept": len(self.sessions), "skipped": True}
        self._last_refresh_monotonic = now

        candidates = {
            candidate.hwnd: candidate for candidate in self.window_manager.enumerate_table_windows()
        }

        created: list[str] = []
        removed: list[str] = []

        for session_id, session in list(self.sessions.items()):
            alive = session.hwnd in candidates and session.hwnd is not None
            if alive:
                session.touch()
                continue
            self._teardown_session(session)
            removed.append(session_id)
            del self.sessions[session_id]

        for hwnd, candidate in candidates.items():
            if len(self.sessions) >= self.max_tables:
                break
            if any(session.hwnd == hwnd for session in self.sessions.values()):
                continue
            session = self.session_factory(candidate)
            self.sessions[session.session_id] = session
            created.append(session.session_id)
            logger.info(
                "TABLE_SESSION_CREATED | id=%s hwnd=%s title=%r score=%s",
                session.session_id,
                session.hwnd,
                session.window_title,
                candidate.score,
            )

        if created or removed:
            logger.info(
                "TABLE_REFRESH | actives=%s created=%s removed=%s",
                len(self.sessions),
                created,
                removed,
            )
        return {
            "created": created,
            "removed": removed,
            "kept": len(self.sessions) - len(created),
            "skipped": False,
        }

    def _teardown_session(self, session: TableSession) -> None:
        camera = session.runtime.get("camera")
        stop = getattr(camera, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass
        logger.info("TABLE_SESSION_REMOVED | id=%s hwnd=%s", session.session_id, session.hwnd)

    def ensure_camera(self, session: TableSession, capture_factory: Callable) -> Any:
        """Capture dédiée par session (WGC HWND), démarrée une seule fois."""
        camera = session.runtime.get("camera")
        if camera is not None:
            return camera
        camera = capture_factory()
        session.runtime["camera"] = camera
        return camera

    def snapshot_sessions(self) -> list[dict[str, Any]]:
        return [session.snapshot() for session in self.sessions.values()]
