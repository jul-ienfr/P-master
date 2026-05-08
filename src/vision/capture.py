import ctypes
import logging
import time
from typing import Optional, Tuple

import cv2
import numpy as np

try:
    import dxcam
except ImportError:
    dxcam = None

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
PRINTWINDOW_AVAILABLE = hasattr(ctypes, "windll") and hasattr(getattr(ctypes, "windll"), "user32")

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
        self.region: Optional[Tuple[int, int, int, int]] = None
        self.window_hwnd: Optional[int] = None
        self.backend = "none"
        self.capture_mode = "none"
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

    @staticmethod
    def _is_valid_dxcam_region(region: Optional[Tuple[int, int, int, int]]) -> bool:
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

    def start(self, region: Optional[Tuple[int, int, int, int]] = None, hwnd: Optional[int] = None):
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
            valid_dxcam_region = self._is_valid_dxcam_region(region)
            if hwnd and WINDOW_CAPTURE_AVAILABLE and not (self.backend == "dxcam" and valid_dxcam_region and not self.prefer_window_capture):
                self.capture_mode = "window"
            elif self.backend == "dxcam" and valid_dxcam_region:
                self.capture_mode = "dxcam"
            else:
                self.capture_mode = self.backend
            self.is_capturing = True
            if self.capture_mode == "window":
                area = f"Fenetre HWND: {hwnd}"
            elif self.capture_mode == "dxcam":
                area = f"Région: {region}" if region else f"Fenetre HWND: {hwnd}"
            else:
                area = f"Région: {region}" if region else "Plein écran"
            logger.info(f"Capture demarree a {self.target_fps} FPS ({area}) via {self.capture_mode}")
        return True

    def _capture_window_frame(self) -> Optional[np.ndarray]:
        if not WINDOW_CAPTURE_AVAILABLE or not self.window_hwnd:
            return None
        screen_dc_handle = None
        src_dc = None
        mem_dc = None
        bitmap = None
        try:
            client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(self.window_hwnd)
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

            def _bitmap_to_frame() -> Optional[np.ndarray]:
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
                        render_result = int(user32.PrintWindow(self.window_hwnd, mem_dc.GetSafeHdc(), flags))
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

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """
        Récupère la dernière image capturée (non-bloquant).
        Retourne None si aucune nouvelle image n'est disponible.
        """
        if not self.is_capturing:
            return None

        if self.capture_mode == "window":
            if self.target_fps > 0:
                now = time.perf_counter()
                if not hasattr(self, "_last_capture_time"):
                    self._last_capture_time = 0.0
                if now - self._last_capture_time < 1.0 / self.target_fps:
                    return None
                self._last_capture_time = now
            return self._capture_window_frame()

        if self.capture_mode == "dxcam":
            if not self.camera:
                return None
            try:
                if self.target_fps > 0:
                    now = time.perf_counter()
                    if not hasattr(self, "_last_capture_time"):
                        self._last_capture_time = 0.0
                    if now - self._last_capture_time < 1.0 / self.target_fps:
                        return None
                    self._last_capture_time = now
                return self.camera.grab(region=self.region)
            except Exception as exc:
                logger.error("Echec de capture via dxcam.grab: %s", exc)
                return None

        if self.capture_mode == "imagegrab" and ImageGrab is not None:
            try:
                if self.region is None:
                    try:
                        screenshot = ImageGrab.grab(all_screens=True)
                    except TypeError:
                        screenshot = ImageGrab.grab()
                else:
                    screenshot = ImageGrab.grab(bbox=self.region)
                frame = np.array(screenshot)
                if self.target_fps > 0:
                    now = time.perf_counter()
                    if not hasattr(self, "_last_capture_time"):
                        self._last_capture_time = 0.0
                    if now - self._last_capture_time < 1.0 / self.target_fps:
                        return None
                    self._last_capture_time = now
                return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            except Exception as exc:
                logger.error("Echec de capture via PIL.ImageGrab: %s", exc)
                return None

        return None

    def stop(self):
        """Arrête la capture."""
        if self.is_capturing:
            self.is_capturing = False
            logger.info("Capture ecran arretee.")

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
                
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
        finally:
            cap.stop()
            cv2.destroyAllWindows()
