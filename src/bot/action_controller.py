import asyncio
import ctypes
import ctypes.wintypes
import logging
import math
import os
import re
from typing import Any, Protocol

import win32api
import win32con
import win32gui

from src.bot.click_strategy import ForegroundClickStrategy, GhostClickStrategy
from src.bot.humanization import (
    ExecutionContext,
    HumanizationProfile,
    compute_think_time,
)
from src.bot.sanity_checker import ActionIntent

logger = logging.getLogger(__name__)
DEFAULT_POKER_WINDOW_KEYWORDS = ("NLHE", "Hold'em No Limit", "PokerStars")

_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def get_window_class_name(hwnd: int) -> str:
    """Classe de fenêtre Win32 (GetClassNameW), vide si indisponible."""
    try:
        buffer = ctypes.create_unicode_buffer(256)
        if ctypes.windll.user32.GetClassNameW(int(hwnd), buffer, 256):
            return str(buffer.value)
    except Exception:
        pass
    return ""


def get_window_process_name(hwnd: int) -> str:
    """Nom du process propriétaire (QueryFullProcessImageNameW), vide si refusé."""
    try:
        pid = ctypes.wintypes.DWORD(0)
        ctypes.windll.user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
        if not pid.value:
            return ""
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid.value)
        )
        if not handle:
            return ""
        try:
            size = ctypes.wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return ""
            return os.path.basename(str(buffer.value))
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ""


# --- CORRECTION DPI AWARENESS ---
# Per-monitor v2 quand disponible (multi-DPR correct), sinon fallback système.
try:
    _user32 = ctypes.windll.user32
    _dpi_ok = False
    if hasattr(_user32, "SetProcessDpiAwarenessContext"):
        try:
            _user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            _user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
            _dpi_ok = bool(
                _user32.SetProcessDpiAwarenessContext(
                    ctypes.c_void_p(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
                )
            )
        except Exception:
            _dpi_ok = False
    if not _dpi_ok:
        _user32.SetProcessDPIAware()
except Exception as e:
    logger.warning(f"Impossible de définir le DPI Awareness: {e}")


class InputBackend(Protocol):
    """Crochet d'extension d'injection d'entrées.

    Aujourd'hui : `Win32Backend` (SetCursorPos/mouse_event/keybd_event).
    Demain : un pont série HID (Arduino Pro Micro / KMBox) — voir docs/hid_bridge.md.
    Toute nouvelle implémentation n'a QUE ce contrat à respecter.
    """

    async def move_to(self, x: int, y: int) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def press(self, vk: int) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def release(self, vk: int) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def type_char(self, ch: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class Win32Backend:
    """Encapsulation des appels Win32 — déplacement pur, aucun changement de timing."""

    async def move_to(self, x: int, y: int) -> None:
        win32api.SetCursorPos((int(x), int(y)))

    async def press(self, vk: int) -> None:
        win32api.keybd_event(int(vk), 0, 0, 0)

    async def release(self, vk: int) -> None:
        win32api.keybd_event(int(vk), 0, win32con.KEYEVENTF_KEYUP, 0)

    async def get_cursor_pos(self) -> tuple[int, int]:
        return win32api.GetCursorPos()

    async def mouse_down_abs(self, abs_x: int, abs_y: int) -> None:
        win32api.mouse_event(
            win32con.MOUSEEVENTF_ABSOLUTE | win32con.MOUSEEVENTF_LEFTDOWN,
            int(abs_x),
            int(abs_y),
            0,
            0,
        )

    async def mouse_up_abs(self, abs_x: int, abs_y: int) -> None:
        win32api.mouse_event(
            win32con.MOUSEEVENTF_ABSOLUTE | win32con.MOUSEEVENTF_LEFTUP,
            int(abs_x),
            int(abs_y),
            0,
            0,
        )

    async def type_char(self, ch: str) -> bool:
        """Frappe complète d'un caractère, shift-state de VkKeyScanEx géré."""
        try:
            scan = int(win32api.VkKeyScanEx(ch, win32api.GetKeyboardLayout()))
        except Exception:
            scan = -1
        if scan == -1:
            logger.warning("SEND_TEXT | caractere non mappé sur ce layout : %r", ch)
            return False
        vk_code = scan & 0xFF
        needs_shift = bool((scan >> 8) & 0x01)
        if needs_shift:
            await self.press(win32con.VK_SHIFT)
        await self.press(vk_code)
        # Maintien naturel minimal de la touche.
        await asyncio.sleep(0.01)
        await self.release(vk_code)
        if needs_shift:
            await self.release(win32con.VK_SHIFT)
        return True


def _parse_window_title_keywords(raw_value: str) -> list[str]:
    tokens = str(raw_value or "").replace(",", "|").replace(";", "|").split("|")
    return [token.strip() for token in tokens if token and token.strip()]


def build_site_profile_matchers(site_profiles: dict[str, Any]) -> list[dict[str, Any]]:
    """Construit les matchers pondérés (regex titre / classe / process) depuis site_profiles."""
    matchers: list[dict[str, Any]] = []
    for site_name, raw_profile in (site_profiles or {}).items():
        if not isinstance(raw_profile, dict):
            continue
        matchers.append(
            {
                "site": str(site_name),
                "title_regex": str(raw_profile.get("title_regex") or "") or None,
                "window_class": str(raw_profile.get("window_class") or "") or None,
                "process_name": str(raw_profile.get("process_name") or "") or None,
            }
        )
    return matchers


def apply_site_profile_weights(
    matchers: list[dict[str, Any]],
    hwnd: int | None,
    title: str,
    detail: dict[str, int],
    log: logging.Logger | None = None,
) -> int:
    """Poids supplémentaires (regex/classe/process) ; retourne la somme ajoutée."""
    weight_total = 0
    class_name = get_window_class_name(hwnd) if hwnd else ""
    process_name = get_window_process_name(hwnd) if hwnd else ""
    for matcher in matchers:
        weight = 0
        regex = matcher.get("title_regex")
        if regex:
            try:
                if re.search(regex, title, re.IGNORECASE):
                    weight += 5
            except re.error:
                if log is not None:
                    log.warning(
                        "site_profiles.title_regex invalide pour %s", matcher.get("site")
                    )
        expected_class = matcher.get("window_class")
        if expected_class and class_name and class_name.lower() == expected_class.lower():
            weight += 4
        expected_process = matcher.get("process_name")
        if (
            expected_process
            and process_name
            and process_name.lower() == expected_process.lower()
        ):
            weight += 4
        if weight:
            detail[str(matcher.get("site"))] = weight
            weight_total += weight
    return weight_total


def score_window_signals(
    title: str,
    keywords: list[str],
    matchers: list[dict[str, Any]],
    hwnd: int | None = None,
) -> tuple[int, dict[str, int]]:
    """Score pondéré partagé : mots-clés de titre + regex + classe fenêtre + process."""
    base = sum(3 for keyword in keywords if keyword.lower() in str(title).lower())
    if "lobby" in str(title).lower():
        base -= 3
    detail: dict[str, int] = {"title_keywords": max(0, base)}
    if not matchers:
        return base, detail
    return base + apply_site_profile_weights(matchers, hwnd, title, detail, logger), detail


class ActionController:
    """
    Contrôleur d'actions conçu pour fonctionner DEPUIS l'hôte vers une Machine Virtuelle (VM)
    ou DANS une VM. Il simule des mouvements de souris humains (courbes de Bézier) pour
    déjouer l'analyse heuristique des anti-cheats.
    """

    def __init__(
        self,
        window_title_keywords: str = "VirtualBox",
        humanization: HumanizationProfile | None = None,
        input_backend: InputBackend | None = None,
        site_profiles: dict[str, Any] | None = None,
        ghost_clicks_enabled: bool = False,
    ):
        self.window_title_keywords = window_title_keywords
        self.hwnd = None
        self.window_title = ""
        self.profile = humanization or HumanizationProfile()
        self.backend = input_backend or Win32Backend()
        self.site_profiles = dict(site_profiles or {})
        self.ghost_clicks_enabled = bool(ghost_clicks_enabled)
        self._ghost_strategy: GhostClickStrategy | None = None
        self._primary_keywords = _parse_window_title_keywords(self.window_title_keywords)
        self._profile_matchers = build_site_profile_matchers(self.site_profiles)
        self._find_window()

    @staticmethod
    def _build_profile_matchers(site_profiles: dict[str, Any]) -> list[dict[str, Any]]:
        return build_site_profile_matchers(site_profiles)

    @property
    def click_strategy(self) -> ForegroundClickStrategy | GhostClickStrategy:
        if getattr(self, "ghost_clicks_enabled", False):
            if self._ghost_strategy is None:
                self._ghost_strategy = GhostClickStrategy(lambda: self.hwnd)
            return self._ghost_strategy
        return ForegroundClickStrategy(self)

    def _candidate_windows(self) -> list[tuple[int, str, tuple[int, int, int, int]]]:
        candidates: list[tuple[int, str, tuple[int, int, int, int]]] = []

        def enum_windows_callback(hwnd, context):
            if not win32gui.IsWindowVisible(hwnd):
                return

            title = win32gui.GetWindowText(hwnd)
            if not title.strip():
                return

            try:
                rect = win32gui.GetWindowRect(hwnd)
            except Exception:
                return
            candidates.append((hwnd, title, rect))

        win32gui.EnumWindows(enum_windows_callback, None)
        return candidates

    @staticmethod
    def _score_window_title(title: str, keywords: list[str]) -> int:
        normalized_title = title.lower()
        score = sum(3 for keyword in keywords if keyword.lower() in normalized_title)
        if "lobby" in normalized_title:
            score -= 3
        return score

    def _score_window_signals(
        self,
        hwnd: int,
        title: str,
        keywords: list[str] | None = None,
    ) -> tuple[int, dict[str, int]]:
        """Score pondéré : mots-clés de titre + classe fenêtre + process + regex titre."""
        if keywords is not None:
            effective_keywords = keywords
        else:
            effective_keywords = getattr(
                self,
                "_primary_keywords",
                _parse_window_title_keywords(getattr(self, "window_title_keywords", "")),
            )
        matchers = getattr(self, "_profile_matchers", None) or []
        base = self._score_window_title(title, effective_keywords)
        detail: dict[str, int] = {"title_keywords": max(0, base)}
        if not matchers:
            return base, detail
        return base + apply_site_profile_weights(
            matchers, hwnd, title, detail, logger
        ), detail

    def _select_best_window(
        self,
        keywords: list[str],
    ) -> tuple[int, str, tuple[int, int, int, int]] | None:
        matches = []
        for hwnd, title, rect in self._candidate_windows():
            score, _detail = self._score_window_signals(hwnd, title, keywords=keywords)
            if score <= 0:
                continue
            width = max(0, rect[2] - rect[0])
            height = max(0, rect[3] - rect[1])
            matches.append((score, width * height, hwnd, title, rect))

        if not matches:
            return None

        matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
        _, _, hwnd, title, rect = matches[0]
        return hwnd, title, rect

    def _find_window(self):
        """Cherche le handle (HWND) de la fenêtre cible."""
        primary_keywords = getattr(
            self,
            "_primary_keywords",
            _parse_window_title_keywords(getattr(self, "window_title_keywords", "")),
        )
        if not hasattr(self, "_primary_keywords"):
            self._primary_keywords = primary_keywords

        # LOCK HWND: Empêcher de sauter sur une autre fenêtre si celle-ci est toujours valide
        if getattr(self, "hwnd", None) and win32gui.IsWindow(self.hwnd):
            try:
                current_title = win32gui.GetWindowText(self.hwnd)
                score, _detail = self._score_window_signals(
                    int(self.hwnd), current_title, keywords=primary_keywords
                )
                if score > 0:
                    self.window_title = current_title
                    return
            except Exception:
                pass

        previous_hwnd = self.hwnd
        previous_title = self.window_title
        best_match = self._select_best_window(primary_keywords)

        if best_match is None:
            fallback_keywords = [
                keyword
                for keyword in DEFAULT_POKER_WINDOW_KEYWORDS
                if keyword not in primary_keywords
            ]
            best_match = self._select_best_window(fallback_keywords)

        if best_match is None:
            self.hwnd = None
            self.window_title = ""
            if previous_hwnd is not None or previous_title:
                logger.warning(
                    f"Impossible de trouver une fenêtre contenant '{self.window_title_keywords}'"
                )
            return

        self.hwnd, self.window_title, _ = best_match
        if self.hwnd != previous_hwnd or self.window_title != previous_title:
            logger.info(f"Fenêtre cible trouvée: '{self.window_title}' (HWND: {self.hwnd})")

    def refresh_window(self):
        self._find_window()
        return self.hwnd

    def get_window_rect(self, refresh: bool = False) -> tuple[int, int, int, int] | None:
        if refresh or not self.hwnd:
            self._find_window()
        if not self.hwnd:
            return None
        try:
            return win32gui.GetWindowRect(self.hwnd)
        except Exception:
            self.hwnd = None
            self.window_title = ""
            return None

    def get_client_rect(self, refresh: bool = False) -> tuple[int, int, int, int] | None:
        if refresh or not self.hwnd:
            self._find_window()
        if not self.hwnd:
            return None
        try:
            left, top = win32gui.ClientToScreen(self.hwnd, (0, 0))
            _, _, right, bottom = win32gui.GetClientRect(self.hwnd)
            return (left, top, left + right, top + bottom)
        except Exception:
            self.hwnd = None
            self.window_title = ""
            return None

    def _get_client_origin(self) -> tuple[int, int] | None:
        if not self.hwnd:
            return None
        try:
            return win32gui.ClientToScreen(self.hwnd, (0, 0))
        except Exception:
            return None

    @staticmethod
    def _get_foreground_window() -> int | None:
        try:
            hwnd = int(win32gui.GetForegroundWindow())
        except Exception:
            return None
        return hwnd if hwnd > 0 else None

    def _force_window_foreground(self) -> bool:
        if not self.hwnd:
            return False

        target_hwnd = int(self.hwnd)
        foreground_before = self._get_foreground_window()
        attached_threads: list[int] = []
        user32 = getattr(getattr(ctypes, "windll", None), "user32", None)
        kernel32 = getattr(getattr(ctypes, "windll", None), "kernel32", None)
        current_thread_id = 0

        try:
            if kernel32 is not None:
                try:
                    current_thread_id = int(kernel32.GetCurrentThreadId())
                except Exception:
                    current_thread_id = 0

            if user32 is not None and current_thread_id:
                target_thread_id = int(user32.GetWindowThreadProcessId(target_hwnd, 0) or 0)
                foreground_thread_id = (
                    int(user32.GetWindowThreadProcessId(int(foreground_before), 0) or 0)
                    if foreground_before
                    else 0
                )
                for thread_id in {target_thread_id, foreground_thread_id}:
                    if thread_id and thread_id != current_thread_id:
                        try:
                            attached = bool(
                                user32.AttachThreadInput(current_thread_id, thread_id, True)
                            )
                        except Exception:
                            attached = False
                        if attached:
                            attached_threads.append(thread_id)

            for operation in (
                lambda: win32gui.BringWindowToTop(target_hwnd),
                lambda: win32gui.SetWindowPos(
                    target_hwnd,
                    win32con.HWND_TOPMOST,
                    0,
                    0,
                    0,
                    0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
                ),
                lambda: win32gui.SetWindowPos(
                    target_hwnd,
                    win32con.HWND_NOTOPMOST,
                    0,
                    0,
                    0,
                    0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
                ),
                lambda: win32gui.SetForegroundWindow(target_hwnd),
            ):
                try:
                    operation()
                except Exception:
                    pass

            if user32 is not None:
                for operation in (
                    lambda: user32.SetForegroundWindow(target_hwnd),
                    lambda: user32.SetActiveWindow(target_hwnd),
                    lambda: user32.SetFocus(target_hwnd),
                ):
                    try:
                        operation()
                    except Exception:
                        pass

            foreground_after = self._get_foreground_window()
            if foreground_after == target_hwnd:
                return True

            try:
                win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
                win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
            except Exception:
                pass

            try:
                win32gui.SetForegroundWindow(target_hwnd)
            except Exception:
                pass

            return self._get_foreground_window() == target_hwnd
        finally:
            if user32 is not None and current_thread_id:
                for thread_id in reversed(attached_threads):
                    try:
                        user32.AttachThreadInput(current_thread_id, thread_id, False)
                    except Exception:
                        pass

    def _prepare_window_for_input(self) -> bool:
        if not self.hwnd:
            return True
        try:
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
        except Exception:
            pass
        focused = self._force_window_foreground()
        logger.info(
            "INPUT_PREPARE | hwnd=%s focused=%s title=%s",
            self.hwnd,
            "yes" if focused else "no",
            self.window_title,
        )
        return focused

    def _ease_out_quad(self, t):
        return t * (2 - t)

    def _profile(self) -> HumanizationProfile:
        """Profil d'humanisation courant (fallback neutre pour les instances de test)."""
        return getattr(self, "profile", None) or HumanizationProfile()

    def _backend(self) -> InputBackend:
        """Backend d'injection courant (défaut Win32 pour les instances de test)."""
        return getattr(self, "backend", None) or Win32Backend()

    @staticmethod
    def _minimum_jerk(t: float) -> float:
        """Profil de vitesse minimum-jerk : accélération/décélération naturelles."""
        return (t**3) * (10.0 - 15.0 * t + 6.0 * t * t)

    async def _human_mouse_move(self, start_x, start_y, target_x, target_y, duration=None):
        """
        Mouvement de souris humain : Bézier + profil minimum-jerk, durée issue de la
        loi de Fitts (vitesse tirée du profil), overshoot variable, jamais de mouvement
        nul si le curseur est déjà sur la cible, micro-survol avant le clic.
        """
        profile = self._profile()
        mouse_cfg = profile.mouse

        distance = ((target_x - start_x) ** 2 + (target_y - start_y) ** 2) ** 0.5

        # Curseur déjà sur la cible : petite divergence puis retour (jamais de mouvement nul).
        if profile.enabled and distance < 2.0:
            div_low, div_high = sorted(int(v) for v in mouse_cfg.divergence_px)
            magnitude = profile.randint(div_low, max(div_low, div_high))
            angle = profile.uniform(0.0, 2.0 * math.pi)
            away_x = target_x + int(magnitude * math.cos(angle))
            away_y = target_y + int(magnitude * math.sin(angle))
            await self._human_mouse_move(
                start_x, start_y, away_x, away_y, duration=duration
            )
            start_x, start_y = away_x, away_y
            distance = float(magnitude)

        if duration is None:
            speed = profile.uniform(*sorted(mouse_cfg.speed_px_s))
            duration = (distance / speed) if distance > 0 else mouse_cfg.move_min_duration_s
            duration = min(max(duration, mouse_cfg.move_min_duration_s), mouse_cfg.move_max_duration_s)

        steps = max(5, int(duration * 60))

        control_x = (
            start_x + (target_x - start_x) * profile.uniform(0.3, 0.7) + profile.randint(-150, 150)
        )
        control_y = (
            start_y + (target_y - start_y) * profile.uniform(0.3, 0.7) + profile.randint(-150, 150)
        )

        for i in range(1, steps + 1):
            t = self._minimum_jerk(i / steps)
            x = int((1 - t) ** 2 * start_x + 2 * (1 - t) * t * control_x + t**2 * target_x)
            y = int((1 - t) ** 2 * start_y + 2 * (1 - t) * t * control_y + t**2 * target_y)
            await self._backend().move_to(x, y)
            await asyncio.sleep(duration / steps)

        # Overshoot conservé mais probabiliste, amplitude pilotée par le profil.
        if profile.enabled and profile.chance(mouse_cfg.overshoot_probability):
            amplitude = max(1, int(mouse_cfg.overshoot_amplitude_px))
            ox = target_x + profile.randint(-amplitude, amplitude)
            oy = target_y + profile.randint(-amplitude, amplitude)

            o_steps = max(3, int(0.12 * 60))
            for i in range(1, o_steps + 1):
                t = self._ease_out_quad(i / o_steps)
                x = int(target_x + (ox - target_x) * t)
                y = int(target_y + (oy - target_y) * t)
                await self._backend().move_to(x, y)
                await asyncio.sleep(0.12 / o_steps)

            for i in range(1, o_steps + 1):
                t = self._ease_out_quad(i / o_steps)
                x = int(ox + (target_x - ox) * t)
                y = int(oy + (target_y - oy) * t)
                await self._backend().move_to(x, y)
                await asyncio.sleep(0.12 / o_steps)

        # Micro-survol sur la cible : micro-mouvements (< jitter px) avant le clic.
        if profile.enabled:
            hover_low, hover_high = sorted(mouse_cfg.hover_s)
            hover_duration = profile.uniform(hover_low, hover_high)
            hover_steps = max(2, int(hover_duration * 60))
            for _ in range(hover_steps):
                jx = target_x + profile.randint(-int(math.ceil(mouse_cfg.hover_jitter_px)), int(math.ceil(mouse_cfg.hover_jitter_px)))
                jy = target_y + profile.randint(-int(math.ceil(mouse_cfg.hover_jitter_px)), int(math.ceil(mouse_cfg.hover_jitter_px)))
                await self._backend().move_to(jx, jy)
                await asyncio.sleep(hover_duration / hover_steps)
        await self._backend().move_to(target_x, target_y)

    def _log_click_reference_offset(self) -> None:
        """Instrumentation P0 : écart repère fenêtre vs repère client au moment du clic.

        La frame capturée est en coordonnées CLIENT ; ce log permet de vérifier en
        session live que les fallback_coordinates calibrées restent cohérentes.
        """
        window_rect = self.get_window_rect()
        if window_rect is None:
            return
        origin = self._get_client_origin()
        if origin is None:
            return
        logger.info(
            "CLICK_ORIGIN | ref=client client_origin=(%s,%s) window_origin=(%s,%s) offset=(%s,%s)",
            origin[0],
            origin[1],
            window_rect[0],
            window_rect[1],
            origin[0] - window_rect[0],
            origin[1] - window_rect[1],
        )

    async def click_at(self, x: int, y: int, double_click: bool = False):
        """Clic aux coordonnées (x, y) de la frame, via la stratégie active.

        Repère unifié : coordonnées CLIENT (même origine que la capture), pas
        coordonnées fenêtre entière. Le mode ghost (`ghost_clicks_enabled`)
        envoie des messages Win32 sans déplacer le curseur.
        """
        strategy = self.click_strategy
        clicked = await strategy.click_at(x, y, double_click=double_click)
        if isinstance(strategy, GhostClickStrategy):
            logger.info(
                "CLICK_ATTEMPT | mode=ghost client=(%s,%s) hwnd=%s clicked=%s",
                x,
                y,
                strategy.hwnd,
                clicked,
            )
        return clicked

    async def _foreground_click_at(self, x: int, y: int, double_click: bool = False):
        """
        Effectue un clic PHYSIQUE (Hardware simulation) aux coordonnées absolues de l'écran,
        après conversion du repère client vers l'écran via ClientToScreen.
        Recommandé si le bot tourne sur l'hôte et cible la fenêtre de la VM.
        """
        # Si on vise une fenêtre spécifique (VM), on repart de l'origine CLIENT :
        # c'est le même repère que la capture (ClientToScreen + GetClientRect).
        if self.hwnd:
            client_origin = self._get_client_origin()
            if client_origin is None:
                logger.error(
                    "CLICK_ATTEMPT | impossible de recuperer l'origine client pour la fenetre cible."
                )
                return False
            target_x = client_origin[0] + x
            target_y = client_origin[1] + y
            self._log_click_reference_offset()
        else:
            target_x, target_y = x, y

        if not self._prepare_window_for_input():
            logger.error(
                "CLICK_ATTEMPT | aborted reason=window_not_foreground hwnd=%s title=%s",
                self.hwnd,
                self.window_title,
            )
            return False
        logger.info(
            "CLICK_ATTEMPT | client=(%s,%s) screen=(%s,%s) hwnd=%s title=%s",
            x,
            y,
            target_x,
            target_y,
            self.hwnd,
            self.window_title,
        )

        # Obtenir la position actuelle pour démarrer le mouvement
        backend = self._backend()
        current_x, current_y = await backend.get_cursor_pos()

        # Mouvement humain : durée issue de la loi de Fitts (distance/vitesse profil),
        # micro-survol inclus avant le clic.
        await self._human_mouse_move(current_x, current_y, target_x, target_y)

        # On rajoute un focus manuel de la fenêtre pour s'assurer que c'est bien elle qui reçoit le clic
        try:
            win32gui.SetForegroundWindow(self.hwnd)
        except Exception:
            pass

        # Clic Hardware Down/Up avec coordonnée physique absolue
        screen_width = win32api.GetSystemMetrics(0)
        screen_height = win32api.GetSystemMetrics(1)
        abs_x = int(target_x * 65535 / screen_width)
        abs_y = int(target_y * 65535 / screen_height)

        click_cfg = self._profile().mouse

        def _click_half_duration() -> float:
            low, high = sorted(click_cfg.click_down_s)
            median = max(0.02, (low + high) / 2.0)
            sigma = 0.4
            sampled = median * math.exp(sigma * (self._profile().uniform(-1.0, 1.0)))
            return min(max(sampled, low), high)

        down_s = _click_half_duration()
        await backend.mouse_down_abs(abs_x, abs_y)
        await asyncio.sleep(down_s)
        await backend.mouse_up_abs(abs_x, abs_y)

        if double_click:
            await asyncio.sleep(_click_half_duration())
            await backend.mouse_down_abs(abs_x, abs_y)
            await asyncio.sleep(_click_half_duration())
            await backend.mouse_up_abs(abs_x, abs_y)

        logger.debug(f"Clic physique généré ABSOLUTEMENT en ({target_x}, {target_y})")
        return True

    async def _select_bet_box_text(self, x: int, y: int):
        """Sélection du contenu de la bet box : rien (le clic simple initial suffit)
        par défaut ; Ctrl+A (~50 %) ou triple-clic (~10 %) occasionnels —
        plus de double-clic systématique."""
        if getattr(self, "ghost_clicks_enabled", False):
            return
        profile = self._profile()
        typing_cfg = profile.typing
        roll = profile.random()

        if not profile.enabled:
            return

        if roll < typing_cfg.select_triple_click_probability:
            # Le clic initial + un double-clic = triple-clic complet.
            await self.click_at(x, y, double_click=True)
            return

        if roll < (
            typing_cfg.select_triple_click_probability + typing_cfg.select_ctrl_a_probability
        ):
            backend = self._backend()
            await backend.press(win32con.VK_CONTROL)
            await asyncio.sleep(self._typing_delay(typing_cfg.key_delay_s))
            await backend.press(ord("A"))
            await asyncio.sleep(self._typing_delay(typing_cfg.key_delay_s))
            await backend.release(ord("A"))
            await asyncio.sleep(self._typing_delay(typing_cfg.key_delay_s))
            await backend.release(win32con.VK_CONTROL)
            await asyncio.sleep(self._typing_delay(typing_cfg.inter_key_delay_s))

    def _typing_delay(self, bounds: tuple[float, float]) -> float:
        """Délai de frappe log-normal borné (bursts locaux gérés par la médiane)."""
        low, high = sorted(bounds)
        median = max(0.005, (low + high) / 2.0)
        sampled = self._profile().sample_reaction_time(median, 0.35)
        return min(max(sampled, low * 0.5), high)

    async def send_text(self, text: str):
        """Frappe le texte via la stratégie active (humaine foreground ou ghost)."""
        return await self.click_strategy.send_text(text)

    async def press_return(self) -> None:
        """Valide avec Entrée via la stratégie active."""
        await self.click_strategy.press_return()

    async def _humanized_press_return(self) -> None:
        backend = self._backend()
        await backend.press(win32con.VK_RETURN)
        await asyncio.sleep(self._profile().uniform(0.03, 0.07))
        await backend.release(win32con.VK_RETURN)

    async def _humanized_send_text(self, text: str):
        """Frappe « burst » humaine via le backend d'injection : shift-state géré,
        délais log-normaux, pause occasionnelle entre groupes, faute de frappe simulée."""
        profile = self._profile()
        typing_cfg = profile.typing
        backend = self._backend()

        for index, char in enumerate(text):
            try:
                scan = int(win32api.VkKeyScanEx(char, win32api.GetKeyboardLayout()))
            except Exception:
                scan = -1
            if scan == -1:
                logger.warning("SEND_TEXT | caractere non mappé sur ce layout : %r", char)
                continue

            # Pause occasionnelle entre groupes de caractères (rythme par salves).
            if profile.enabled and index > 0 and profile.chance(typing_cfg.group_pause_probability):
                pause_low, pause_high = sorted(typing_cfg.group_pause_s)
                await asyncio.sleep(profile.uniform(pause_low, pause_high))

            # Faute de frappe simulée : doublon accidentel puis backspace avant la vraie frappe.
            if profile.enabled and profile.chance(typing_cfg.typo_probability):
                await backend.type_char(char)
                await asyncio.sleep(profile.uniform(0.10, 0.25))
                await backend.press(win32con.VK_BACK)
                await asyncio.sleep(self._typing_delay(typing_cfg.key_delay_s))
                await backend.release(win32con.VK_BACK)
                await asyncio.sleep(self._typing_delay(typing_cfg.inter_key_delay_s))

            await backend.type_char(char)
            await asyncio.sleep(self._typing_delay(typing_cfg.inter_key_delay_s))

    async def execute_action(
        self,
        action_request,
        coords_mapping: dict,
        jit_check=None,
        update_jit_baseline=None,
        context: ExecutionContext | None = None,
        **kwargs,
    ):
        async def _verify_jit(ignore_action_region: bool = False) -> bool:
            if jit_check is None:
                return True
            if asyncio.iscoroutinefunction(jit_check):
                allowed = await jit_check(ignore_action_region=ignore_action_region)
            else:
                allowed = jit_check(ignore_action_region=ignore_action_region)
            if not allowed:
                logger.error(
                    "JIT_CHECK | action=%s status=aborted reason=jit_check_failed", action_name
                )
                raise RuntimeError("JIT Check Failed")
            return True

        if isinstance(action_request, ActionIntent):
            action_intent = action_request
        else:
            action_intent = ActionIntent.from_payload(action_request)

        action_name = action_intent.action
        logger.info(
            "ACTION_REQUEST | action=%s bet_size=%s targets=%s",
            action_name,
            action_intent.bet_size,
            sorted(key for key, value in (coords_mapping or {}).items() if value),
        )

        # Think time contextuel : base par action × modulateurs street/pot/confiance × fatigue.
        profile = self._profile()
        think_time = compute_think_time(profile, action_name, action_intent.bet_size, context)

        logger.info(f"Bot en réflexion ({think_time:.2f}s)...")
        await asyncio.sleep(think_time)

        if action_name == "FOLD":
            coords = coords_mapping.get("FOLD")
            if coords:
                await _verify_jit()
                clicked = await self.click_at(*coords)
                if clicked:
                    logger.info("-> Action exécutée : FOLD")
                    return {"ok": True, "action": "FOLD", "target": tuple(coords)}
                logger.error("CLICK_RESULT | action=FOLD status=failed reason=fold_click_failed")
                return {
                    "ok": False,
                    "action": "FOLD",
                    "reason": "fold_click_failed",
                    "target": tuple(coords),
                }
            logger.warning("CLICK_RESULT | action=FOLD status=skipped reason=missing_fold_coords")
            return {"ok": False, "action": "FOLD", "reason": "missing_fold_coords"}

        elif action_name == "CALL" or action_name == "CHECK":
            coords = coords_mapping.get("CALL")
            if coords:
                await _verify_jit()
                clicked = await self.click_at(*coords)
                if clicked:
                    logger.info(f"-> Action exécutée : {action_name}")
                    return {"ok": True, "action": action_name, "target": tuple(coords)}
                logger.error(
                    "CLICK_RESULT | action=%s status=failed reason=call_click_failed", action_name
                )
                return {
                    "ok": False,
                    "action": action_name,
                    "reason": "call_click_failed",
                    "target": tuple(coords),
                }
            logger.warning(
                "CLICK_RESULT | action=%s status=skipped reason=missing_call_coords", action_name
            )
            return {"ok": False, "action": action_name, "reason": "missing_call_coords"}

        elif action_name == "ALL_IN" or "RAISE" in action_name or "BET" in action_name:
            text_box_coords = coords_mapping.get("BET_BOX")
            if text_box_coords:
                await _verify_jit()
                # Sélection de la bet box : clic simple par défaut ; Ctrl+A ou
                # triple-clic occasionnels remplacent l'ancien double-clic systématique.
                clicked = await self.click_at(*text_box_coords, double_click=False)
                if not clicked:
                    logger.error(
                        "CLICK_RESULT | action=%s status=failed reason=bet_box_click_failed",
                        action_name,
                    )
                    return {"ok": False, "action": action_name, "reason": "bet_box_click_failed"}
                await self._select_bet_box_text(*text_box_coords)

                # --- Dynamic BB Parsing for resilient betting ---
                import json
                import os
                import re

                bb_size = 200  # Fallback par defaut absolu
                active_regex = r"\d+[/,](\d+)\b"

                # 1. Selection automatique du profil du site depuis config.json
                if self.window_title:
                    try:
                        config_path = os.path.join(
                            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                            "config.json",
                        )
                        with open(config_path) as f:
                            cfg = json.load(f)
                            profiles = cfg.get("bot", {}).get("site_profiles", {})

                            # On cherche quel site correspond au titre de la fenetre actuelle
                            for site_name, profile in profiles.items():
                                if site_name.lower() in self.window_title.lower():
                                    bb_size = int(profile.get("default_bb", bb_size))
                                    active_regex = profile.get("stake_regex", active_regex)
                                    break
                    except Exception:
                        pass

                # 2. Extraction dynamique depuis le titre de la fenetre actuelle avec la regex du site
                if self.window_title:
                    match = re.search(active_regex, self.window_title)
                    if match:
                        try:
                            bb_size = int(match.group(1))
                        except ValueError:
                            pass

                target_amount = (
                    action_intent.bet_size
                    if action_intent.bet_size is not None
                    else float(3 * bb_size)
                )

                # Si le calcul OCR a fail (pot=0) et crashé à 1.0, on force une relance standard GTO (3 BB)
                if target_amount < bb_size:
                    logger.warning(
                        f"Correction Sizing: {target_amount} est inférieur à 1 BB ({bb_size}). Forcé à 3 BB."
                    )
                    target_amount = float(3 * bb_size)

                # Formatage du nombre (Entier si Play Money, Décimal sinon)
                if bb_size >= 10:
                    amount_to_bet = str(int(target_amount))
                else:
                    amount_to_bet = f"{target_amount:.2f}".rstrip("0").rstrip(".")

                logger.info("=========== HISTORIQUE MISE ===========")
                logger.info(f"  Action Requise    : {action_name}")
                logger.info(f"  BB détectée       : {bb_size}")
                logger.info(f"  Calcul IA brut    : {action_intent.bet_size}")
                logger.info(f"  Montant Final     : {amount_to_bet}")
                logger.info("=======================================")

                await self.send_text(amount_to_bet)

                await asyncio.sleep(self._profile().uniform(0.08, 0.30))

                # Validation : ENTER simple (le second ne reste actif que via le
                # flag legacy), puis clic BET_BTN systématique en filet final.
                enter_presses = 2 if self._profile().typing.legacy_double_enter else 1
                for _ in range(enter_presses):
                    await self.press_return()
                    await asyncio.sleep(self._profile().uniform(0.10, 0.25))

                # ET on clique le bouton physiques BET_BTN pour valider (Indispensable sur PokerStars récent)
                bet_btn_coords = coords_mapping.get("BET_BTN")
                if bet_btn_coords:
                    # La saisie du montant mute légitimement la zone d'action :
                    # on relâche la vérification sur cette région pour le check final.
                    await _verify_jit(ignore_action_region=True)
                    logger.info(
                        f"CLICK_ATTEMPT | Clic de sécurité sur le bouton BET_BTN en coords {bet_btn_coords}..."
                    )
                    await asyncio.sleep(self._profile().uniform(0.1, 0.3))
                    clicked_btn = await self.click_at(*bet_btn_coords, double_click=False)
                    if not clicked_btn:
                        logger.warning(
                            "CLICK_RESULT | Impossible de cliquer BET_BTN en cascade, validation incertaine."
                        )
                    else:
                        logger.info("CLICK_RESULT | Bouton BET_BTN cliqué avec succès.")
                else:
                    logger.warning(
                        "CLICK_RESULT | AUCUNE coordonnée pour BET_BTN. L'IA n'a pas vu le bouton final ! Seul ENTER a été pressé."
                    )

                logger.info(f"-> Action exécutée : {action_name} ({amount_to_bet}) validé")
                return {
                    "ok": True,
                    "action": action_name,
                    "target": "VK_RETURN+BET_BTN",
                    "bet_size": amount_to_bet,
                }
            logger.warning(
                "CLICK_RESULT | action=%s status=skipped reason=missing_bet_box_coords", action_name
            )
            return {"ok": False, "action": action_name, "reason": "missing_bet_box_coords"}

        logger.warning(
            "CLICK_RESULT | action=%s status=skipped reason=unsupported_action", action_name
        )
        return {"ok": False, "action": action_name, "reason": "unsupported_action"}
