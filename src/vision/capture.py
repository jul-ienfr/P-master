import ctypes
import logging
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

try:
    import dxcam
except ImportError:
    dxcam = None

try:
    from windows_capture import WindowsCapture

    WINDOWS_CAPTURE_AVAILABLE = True
except ImportError:
    WindowsCapture = None
    WINDOWS_CAPTURE_AVAILABLE = False

try:
    from PIL import ImageGrab
except ImportError:
    ImageGrab = None

try:
    import win32con
    import win32gui
    import win32ui
except ImportError:
    win32con = None
    win32gui = None
    win32ui = None

logger = logging.getLogger(__name__)

WINDOW_CAPTURE_AVAILABLE = win32gui is not None and win32ui is not None and win32con is not None
PRINTWINDOW_AVAILABLE = hasattr(ctypes, "windll") and hasattr(ctypes.windll, "user32")

WGC_RESTART_AFTER_EMPTY_S = 2.0
WGC_MAX_RESTARTS = 3


@dataclass(frozen=True)
class FrameMeta:
    """Métadonnées d'une frame capturée (horodatage + séquence + backend)."""

    seq: int
    monotonic: float
    backend: str


class WgcWindowCapture:
    """Capture Windows Graphics Capture (HWND vrai) — Phase 2.2.

    Avantages vs BitBlt/dxcam : le contenu de la fenêtre est capturé via le
    DWM même quand elle est occlusée ou minimisée, en DPI natif, sans
    lecture de pixels écran. Les frames arrivent BGRA sur un thread natif ;
    on ne garde que la dernière (copie BGR).
    """

    def __init__(self, hwnd: int):
        if not WINDOWS_CAPTURE_AVAILABLE:
            raise RuntimeError("windows-capture indisponible")
        self._lock = threading.Lock()
        self._latest: np.ndarray | None = None
        self._control = None
        self._hwnd = int(hwnd)
        self._closed = False
        self._start_session()

    def _start_session(self) -> None:
        capture = WindowsCapture(window_hwnd=int(self._hwnd), cursor_capture=False, draw_border=False)

        @capture.event
        def on_frame_arrived(frame, control):
            try:
                bgr = cv2.cvtColor(frame.frame_buffer, cv2.COLOR_BGRA2BGR)
            except Exception:
                return
            with self._lock:
                self._latest = bgr

        @capture.event
        def on_closed():
            with self._lock:
                self._closed = True

        self._control = capture.start_free_threaded()

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def restart(self) -> bool:
        """Redémarre la session WGC après une fermeture (fenêtre recréée, crash DWM)."""
        self.stop()
        with self._lock:
            self._latest = None
            self._closed = False
        try:
            self._start_session()
        except Exception as exc:
            logger.warning("Restart WGC impossible pour HWND %s: %s", self._hwnd, exc)
            with self._lock:
                self._closed = True
            return False
        return True

    def get_frame(self) -> np.ndarray | None:
        with self._lock:
            if self._latest is None:
                return None
            frame = self._latest
            self._latest = None  # consommée une seule fois (pipeline frame-driven)
            return frame

    def stop(self):
        control = self._control
        self._control = None
        if control is not None:
            try:
                control.stop()
            except Exception:
                pass


class ScreenCapture:
    def __init__(self, target_fps: int = 2, prefer_window_capture: bool = False):
        """
        Initialise la capture d'écran via DirectX.

        Args:
            target_fps: Le nombre d'images par seconde souhaité.
                        Pour le poker, 2 fps (une frame toutes les 0.5s) est l'idéal absolu
                        pour économiser 100% du CPU tout en réagissant assez vite.
        """
        self.target_fps = target_fps
        self.prefer_window_capture = bool(prefer_window_capture)
        self.region: tuple[int, int, int, int] | None = None
        self.window_hwnd: int | None = None
        self.backend = "none"
        self.capture_mode = "none"
        self._wgc_session = None
        self._wgc_failures = 0
        try:
            if dxcam is not None:
                self.camera = dxcam.create(output_color="BGR")
                self.backend = "dxcam"
                self.capture_mode = "dxcam"
                logger.info("DXcam initialise avec succes (Color space: BGR pour OpenCV)")
            elif ImageGrab is not None:
                self.camera = None
                self.backend = "imagegrab"
                self.capture_mode = "imagegrab"
                logger.warning("DXcam indisponible. Fallback sur PIL.ImageGrab pour la capture.")
            else:
                self.camera = None
                logger.error("Aucun backend de capture disponible (ni dxcam ni PIL.ImageGrab).")
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation de DXcam: {e}")
            self.camera = None
            if ImageGrab is not None:
                self.backend = "imagegrab"
                self.capture_mode = "imagegrab"
                logger.warning("Fallback sur PIL.ImageGrab suite a l'echec DXcam.")

        self.is_capturing = False
        self._frame_seq = 0
        self._wgc_empty_since: float | None = None

    @staticmethod
    def _is_valid_dxcam_region(region: tuple[int, int, int, int] | None) -> bool:
        if not isinstance(region, (tuple, list)) or len(region) != 4:
            return False
        try:
            left, top, right, bottom = [int(value) for value in region]
        except Exception:
            return False
        if right <= left or bottom <= top:
            return False
        if min(left, top, right, bottom) <= -30000:
            return False
        return True

    def start(self, region: tuple[int, int, int, int] | None = None, hwnd: int | None = None):
        """
        Démarre la capture d'écran en continu.

        Args:
            region: Tuple (left, top, right, bottom) définissant la zone de la table de poker.
                    Si None, capture tout l'écran.
        """
        if self.backend == "none":
            return False

        if not self.is_capturing:
            self.region = region
            self.window_hwnd = hwnd
            self._wgc_empty_since = None
            valid_dxcam_region = self._is_valid_dxcam_region(region)
            # Phase 2.2 — WGC en priorité pour un HWND : contenu vrai même
            # occlusé/minimisé, DPI natif. Fallback silencieux sur les
            # backends existants si la session ne démarre pas.
            if hwnd and WINDOWS_CAPTURE_AVAILABLE and self._try_start_wgc(hwnd):
                self.capture_mode = "wgc"
            elif (
                hwnd
                and WINDOW_CAPTURE_AVAILABLE
                and not (
                    self.backend == "dxcam"
                    and valid_dxcam_region
                    and not self.prefer_window_capture
                )
            ):
                self.capture_mode = "window"
            elif self.backend == "dxcam" and valid_dxcam_region:
                self.capture_mode = "dxcam"
            else:
                self.capture_mode = self.backend
            self.is_capturing = True
            if self.capture_mode == "wgc":
                area = f"Fenetre HWND (WGC): {hwnd}"
            elif self.capture_mode == "window":
                area = f"Fenetre HWND: {hwnd}"
            elif self.capture_mode == "dxcam":
                area = f"Région: {region}" if region else f"Fenetre HWND: {hwnd}"
            else:
                area = f"Région: {region}" if region else "Plein écran"
            logger.info(
                f"Capture demarree a {self.target_fps} FPS ({area}) via {self.capture_mode}"
            )
        return True

    def _try_start_wgc(self, hwnd: int) -> bool:
        try:
            session = WgcWindowCapture(hwnd)
        except Exception as exc:
            logger.warning("WGC indisponible pour HWND %s (%s), fallback.", hwnd, exc)
            return False
        # Une frame doit arriver rapidement ; sinon on considère la fenêtre
        # non-rendable et on retombe sur les backends écran.
        deadline = time.perf_counter() + 1.0
        while time.perf_counter() < deadline:
            if session.get_frame() is not None:
                logger.info("Session WGC active pour HWND %s", hwnd)
                self._wgc_session = session
                self._wgc_failures = 0
                return True
            time.sleep(0.05)
        session.stop()
        logger.warning("WGC: aucune frame pour HWND %s sous 1s, fallback.", hwnd)
        return False

    def _capture_window_frame(self) -> np.ndarray | None:
        if not WINDOW_CAPTURE_AVAILABLE or not self.window_hwnd:
            return None
        screen_dc_handle = None
        src_dc = None
        mem_dc = None
        bitmap = None
        try:
            client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(
                self.window_hwnd
            )
            width = max(0, client_right - client_left)
            height = max(0, client_bottom - client_top)
            if width <= 0 or height <= 0:
                return None

            screen_origin = win32gui.ClientToScreen(self.window_hwnd, (0, 0))
            is_iconic = False
            try:
                is_iconic = bool(win32gui.IsIconic(self.window_hwnd))
            except Exception:
                is_iconic = False

            screen_dc_handle = win32gui.GetDC(0)
            src_dc = win32ui.CreateDCFromHandle(screen_dc_handle)
            mem_dc = src_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(src_dc, width, height)
            mem_dc.SelectObject(bitmap)

            def _bitmap_to_frame() -> np.ndarray | None:
                bmp_info = bitmap.GetInfo()
                bmp_bytes = bitmap.GetBitmapBits(True)
                frame = np.frombuffer(bmp_bytes, dtype=np.uint8)
                if frame.size == 0:
                    return None
                frame = frame.reshape((bmp_info["bmHeight"], bmp_info["bmWidth"], 4))
                return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

            # Capture the actual window content first. Screen-pixel capture is faster,
            # but it can read another app if the poker table is overlapped or on a
            # compositor path that diverges from the visible desktop.
            render_result = 0
            if PRINTWINDOW_AVAILABLE:
                user32 = ctypes.windll.user32
                for flags in (3, 2, 1, 0):
                    try:
                        render_result = int(
                            user32.PrintWindow(self.window_hwnd, mem_dc.GetSafeHdc(), flags)
                        )
                    except Exception:
                        render_result = 0
                    if render_result == 1:
                        break

            if render_result == 1:
                frame = _bitmap_to_frame()
                if frame is not None and float(frame.std()) >= 2.0:
                    return frame

            if is_iconic:
                return None

            # Fallback to visible screen pixels only when direct window capture is unavailable.
            mem_dc.BitBlt((0, 0), (width, height), src_dc, screen_origin, win32con.SRCCOPY)
            return _bitmap_to_frame()
        except Exception as exc:
            logger.error("Echec de capture directe de la fenetre: %s", exc)
            return None
        finally:
            try:
                if bitmap is not None:
                    win32gui.DeleteObject(bitmap.GetHandle())
            except Exception:
                pass
            try:
                if mem_dc is not None:
                    mem_dc.DeleteDC()
            except Exception:
                pass
            try:
                if src_dc is not None:
                    src_dc.DeleteDC()
            except Exception:
                pass
            try:
                if screen_dc_handle is not None:
                    win32gui.ReleaseDC(0, screen_dc_handle)
            except Exception:
                pass

    def get_latest_frame(self) -> np.ndarray | None:
        """
        Récupère la dernière image capturée (non-bloquant).
        Retourne None si aucune nouvelle image n'est disponible.
        """
        frame, _meta = self.get_latest_frame_with_meta()
        return frame

    def get_latest_frame_with_meta(self) -> tuple[np.ndarray | None, FrameMeta | None]:
        """
        Récupère la dernière image capturée avec ses métadonnées
        (séquence, horodatage monotonic, backend). Retourne (None, None)
        si aucune nouvelle image n'est disponible.
        """
        if not self.is_capturing:
            return None, None

        # Throttle FPS AVANT tout grab : en mode imagegrab l'ancien code
        # capturait puis jetait la frame ; désormais rien n'est capturé.
        if not self._throttle_allows():
            return None, None

        if self.capture_mode == "wgc":
            return self._get_wgc_frame_with_meta()

        if self.capture_mode == "window":
            frame = self._capture_window_frame()
            if frame is None or frame.size == 0:
                return None, None
            return self._wrap_frame(frame, self._next_frame_meta())

        if self.capture_mode == "dxcam":
            if not self.camera:
                return None, None
            try:
                frame = self.camera.grab(region=self.region)
            except Exception as exc:
                logger.error("Echec de capture via dxcam.grab: %s", exc)
                return None, None
            if frame is None or getattr(frame, "size", 0) == 0:
                return None, None
            return self._wrap_frame(frame, self._next_frame_meta())

        if self.capture_mode == "imagegrab" and ImageGrab is not None:
            try:
                if self.region is None:
                    try:
                        screenshot = ImageGrab.grab(all_screens=True)
                    except TypeError:
                        screenshot = ImageGrab.grab()
                else:
                    screenshot = ImageGrab.grab(bbox=self.region)
                frame = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
            except Exception as exc:
                logger.error("Echec de capture via PIL.ImageGrab: %s", exc)
                return None, None
            return self._wrap_frame(frame, self._next_frame_meta())

        return None, None

    def _fallback_capture_mode(self) -> str:
        if WINDOW_CAPTURE_AVAILABLE and self.window_hwnd:
            return "window"
        if self.backend == "dxcam" and self._is_valid_dxcam_region(self.region):
            return "dxcam"
        return str(self.backend or "imagegrab")

    def _recover_wgc_session(self, session: WgcWindowCapture) -> None:
        """Restart de session WGC ou bascule automatique BitBlt après échecs."""
        self._wgc_failures += 1
        restarted = False
        if self._wgc_failures <= WGC_MAX_RESTARTS and hasattr(session, "restart"):
            try:
                restarted = bool(session.restart())
            except Exception as exc:
                logger.warning("Restart WGC en erreur: %s", exc)
                restarted = False
        if restarted:
            logger.info(
                "Session WGC redémarrée (%s/%s échecs).",
                self._wgc_failures,
                WGC_MAX_RESTARTS,
            )
            return
        previous_mode = self.capture_mode
        self.capture_mode = self._fallback_capture_mode()
        try:
            session.stop()
        except Exception:
            pass
        self._wgc_session = None
        logger.warning(
            "WGC mort après %s échecs (%s), bascule sur %s.",
            self._wgc_failures,
            previous_mode,
            self.capture_mode,
        )

    def _get_wgc_frame_with_meta(self) -> tuple[np.ndarray | None, FrameMeta | None]:
        session = self._wgc_session
        if session is None:
            return None, None

        dead = False
        closed = getattr(session, "closed", None)
        if callable(closed):
            try:
                dead = bool(closed)
            except Exception:
                dead = False
        elif closed is not None:
            dead = bool(closed)

        frame = None
        if not dead:
            frame = session.get_frame()
            if frame is None or frame.size == 0:
                now = time.perf_counter()
                empty_since = getattr(self, "_wgc_empty_since", None)
                if empty_since is None:
                    self._wgc_empty_since = now
                elif now - empty_since >= WGC_RESTART_AFTER_EMPTY_S:
                    dead = True
            else:
                self._wgc_empty_since = None

        if dead:
            self._wgc_empty_since = None
            self._recover_wgc_session(session)
            return None, None

        if frame is None or frame.size == 0:
            # Comme pour le mode window : une fenêtre non rendue ne produit
            # rien ; on laisse le pipeline gérer l'absence de frame.
            return None, None
        return self._wrap_frame(frame, self._next_frame_meta())

    def stop(self):
        """Arrête la capture."""
        if self._wgc_session is not None:
            self._wgc_session.stop()
            self._wgc_session = None
        if self.is_capturing:
            self.is_capturing = False
            logger.info("Capture ecran arretee.")

    def _throttle_allows(self) -> bool:
        """Throttle FPS AVANT le grab (aucune frame capturée puis jetée)."""
        if self.target_fps <= 0:
            return True
        now = time.perf_counter()
        last = getattr(self, "_last_capture_time", 0.0)
        if now - last < 1.0 / float(self.target_fps):
            return False
        self._last_capture_time = now
        return True

    def _next_frame_meta(self) -> FrameMeta:
        self._frame_seq = int(getattr(self, "_frame_seq", 0)) + 1
        return FrameMeta(
            seq=self._frame_seq,
            monotonic=time.monotonic(),
            backend=str(self.capture_mode or self.backend or "none"),
        )

    @staticmethod
    def _wrap_frame(frame: np.ndarray, meta: FrameMeta) -> tuple[np.ndarray, FrameMeta]:
        return frame, meta


# Exemple d'utilisation rapide si le script est exécuté directement
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cap = ScreenCapture(target_fps=2)

    # On démarre la capture (sur tout l'écran pour le test)
    if cap.start():
        try:
            print("Capture en cours... Appuyez sur 'q' dans la fenêtre pour quitter.")
            while True:
                frame = cap.get_latest_frame()
                if frame is not None:
                    # On affiche la frame réduite pour le test
                    preview = cv2.resize(frame, (960, 540))
                    cv2.imshow("Poker Bot - DXcam Preview", preview)

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
        finally:
            cap.stop()
            cv2.destroyAllWindows()
