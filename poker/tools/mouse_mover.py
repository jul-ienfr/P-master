import logging
import random
import time
import sys

import numpy as np

from poker import pymouse
from poker.tools.helper import get_config
from poker.tools.vbox_manager import VirtualBoxController

log = logging.getLogger(__name__)

def human_sleep(min_t, max_t):
    """Sleeps for a random duration between min_t and max_t, with a slight distribution bias."""
    try:
        if not get_config().config.getboolean('antidetection', 'enable_human_sleeps', fallback=True):
            time.sleep(np.random.uniform(min_t, max_t))
            return
    except:
        pass
    mean = (max_t + min_t) / 2.0
    std_dev = (max_t - min_t) / 4.0
    sleep_time = np.random.normal(mean, std_dev)
    # Clip the sleep_time to stay within bounds
    sleep_time = max(min_t, min(sleep_time, max_t))
    time.sleep(sleep_time)

def get_point_on_cubic_bezier(cp, t):
    u = 1 - t
    tt = t * t
    uu = u * u
    uuu = uu * u
    ttt = tt * t

    px = uuu * cp[0][0] + 3 * uu * t * cp[1][0] + 3 * u * tt * cp[2][0] + ttt * cp[3][0]
    py = uuu * cp[0][1] + 3 * uu * t * cp[1][1] + 3 * u * tt * cp[2][1] + ttt * cp[3][1]

    return int(px), int(py)

class MouseMover(VirtualBoxController):
    def __init__(self, vbox_mode):
        requested_vbox_mode = vbox_mode
        if vbox_mode:
            super().__init__()
            if not self.is_ready():
                log.warning("VirtualBox control requested but unavailable. Falling back to direct mouse control.")
                vbox_mode = False
        self.mouse = pymouse.PyMouse()
        self.vbox_mode = vbox_mode
        self.requested_vbox_mode = requested_vbox_mode
        self.old_x = int(np.round(np.random.uniform(0, 500, 1)))
        self.old_y = int(np.round(np.random.uniform(0, 500, 1)))

    def click(self, x, y):
        if self.vbox_mode:
            self.mouse_move_vbox(x, y)
            self.mouse_click_vbox(x, y)
        else:
            # win32api.SetCursorPos((x, y))
            self.mouse.move(x, y)
            self.mouse.click(x, y)

        human_sleep(0.01, 0.1)

    def scroll(self, amount, direction='down'):
        """Scrolls the mouse wheel or simulates reading by waiting."""
        try:
            from poker.tools.helper import get_config
            enable_scrolling = get_config().config.getboolean('antidetection', 'enable_scrolling', fallback=False)
            if not enable_scrolling:
                return
        except:
            return

        log.debug(f"Simulating reading/scrolling. Amount: {amount}")
        # Just simulate reading by sleeping. Real wheels logic can be added later easily based on local VM APIs.
        human_sleep(amount * 0.15, amount * 0.3)

    def mouse_mover(self, x1, y1, x2, y2):
        speed = 0.5
        distance = ((x2 - x1)**2 + (y2 - y1)**2)**0.5
        
        # Scale deviation according to distance, max deviation 150px
        deviation = min(distance * 0.3, 150)
        
        # Define base control points for Bezier curve
        cp = [
            (x1, y1),
            (x1 + (x2 - x1)*0.33 + random.uniform(-deviation, deviation), y1 + (y2 - y1)*0.33 + random.uniform(-deviation, deviation)),
            (x1 + (x2 - x1)*0.66 + random.uniform(-deviation, deviation), y1 + (y2 - y1)*0.66 + random.uniform(-deviation, deviation)),
            (x2, y2)
        ]
        
        # Determine number of steps
        steps = max(int(distance / 10), 10)
        
        for i in range(steps):
            t = i / float(steps - 1)
            
            x, y = get_point_on_cubic_bezier(cp, t)
            
            # Additional small tremble
            x += int(random.uniform(-2, 2))
            y += int(random.uniform(-2, 2))

            if self.vbox_mode:
                try:
                    self.mouse_move_vbox(x, y)
                except AttributeError:
                    raise RuntimeError("Virtual box not detected. Switch to direct mouse control in setup or open VirtualBox")
            else:
                self.mouse.move(x, y)

            # Humanized delay between mouse movements
            human_sleep(0.005 * speed, 0.015 * speed)

        # Ensure exact final coordinate
        if self.vbox_mode:
            self.mouse_move_vbox(x2, y2)
        else:
            self.mouse.move(x2, y2)

        self.old_x = x2
        self.old_y = y2

    def type_keyboard(self, text):
        """Type keys with human-like delays."""
        try:
            enable_typing_delay = get_config().config.getboolean('antidetection', 'enable_typing_delay', fallback=True)
        except:
            enable_typing_delay = True
            
        is_windows = sys.platform.startswith('win')
        shell = None
        if not self.vbox_mode and is_windows:
            try:
                import win32com.client
                shell = win32com.client.Dispatch("WScript.Shell")
            except ImportError:
                log.warning("win32com is required for local keyboard typing.")
            
        for char in text:
            if self.vbox_mode:
                self.keyboard_type_vbox(char)
            else:
                if shell:
                    # Basic mapping for special keys or direct send
                    shell.SendKeys(char)
                else:
                    log.warning("Keyboard typing bypassed: Not supported on this environment.")
            
            if enable_typing_delay:
                human_sleep(0.05, 0.25)
            else:
                time.sleep(0.01)

    def mouse_clicker(self, x2, y2, buttonToleranceX, buttonToleranceY):
        xrand = int(np.random.uniform(0, buttonToleranceX, 1)[0])
        yrand = int(np.random.uniform(0, buttonToleranceY, 1)[0])

        try:
            from poker.tools.helper import get_config
            enable_missclicks = get_config().config.getboolean('antidetection', 'enable_missclicks', fallback=False)
        except:
            enable_missclicks = False

        if enable_missclicks:
            # 2% chance to miss-click
            if random.random() < 0.02:
                miss_x = x2 + xrand + random.choice([random.randint(25, 45), -random.randint(25, 45)])
                miss_y = y2 + yrand + random.choice([random.randint(25, 45), -random.randint(25, 45)])
                
                log.debug("Intentional Miss-click initiated")
                if self.vbox_mode:
                    self.mouse_move_vbox(miss_x, miss_y)
                else:
                    self.mouse.move(miss_x, miss_y)
                human_sleep(0.01, 0.1)
                
                if self.vbox_mode:
                    self.mouse_click_vbox(miss_x, miss_y)
                else:
                    self.mouse.click(miss_x, miss_y)
                
                # Realize mistake, wait before correcting
                human_sleep(0.4, 0.8)

        if self.vbox_mode:
            self.mouse_move_vbox(x2 + xrand, y2 + yrand)
        else:
            self.mouse.move(x2 + xrand, y2 + yrand)

        human_sleep(0.1, 0.2)

        self.click(x2 + xrand, y2 + yrand)
        log.debug("Clicked: {0} {1}".format(x2 + xrand, y2 + yrand))

        human_sleep(0.1, 0.5)


class MouseMoverTableBased(MouseMover):
    def __init__(self, table_dict):
        config = get_config()

        try:
            mouse_control = config.config.get('main', 'control')
            if mouse_control != 'Direct mouse control':
                self.vbox_mode = True
            else:
                self.vbox_mode = False
        except:
            self.vbox_mode = False

        super().__init__(self.vbox_mode)

        self.table_dict = table_dict

    def move_mouse_away_from_buttons(self):
        x2 = int(np.round(np.random.uniform(1700, 2000, 1), 0)[0])
        y2 = int(np.round(np.random.uniform(10, 200, 1), 0)[0])

        human_sleep(0.5, 1.2)
        if not self.vbox_mode:
            (x1, y1) = self.mouse.position()
        else:
            x1 = self.old_x
            y1 = self.old_y
        x1 = 10 if x1 > 2000 else x1
        y1 = 10 if y1 > 1000 else y1

        try:
            log.debug("Moving mouse away: " + str(x1) + "," + str(y1) + "," + str(x2) + "," + str(y2))
            self.mouse_mover(x1, y1, x2, y2)
        except Exception as e:
            log.warning("Moving mouse away failed")

    def move_mouse_away_from_buttons_jump(self):
        x2 = int(np.round(np.random.uniform(1700, 2000, 1), 0)[0])
        y2 = int(np.round(np.random.uniform(10, 200, 1), 0)[0])

        try:
            log.debug("Moving mouse away via jump: " + str(x2) + "," + str(y2))
            if self.vbox_mode:
                self.mouse_move_vbox(x2, y2)
            else:
                self.mouse.move(x2, y2)
        except Exception as e:
            log.warning("Moving mouse via jump away failed" + str(e))

    def mouse_action(self, decision, topleftcorner, options=None):
        if decision == 'Check Deception':
            decision = 'Check'
        if decision == 'Call Deception':
            decision = 'Call'

        tlx = int(topleftcorner[0])
        tly = int(topleftcorner[1])

        log.debug("Mouse moving to: " + decision)
        log.debug(f"Top left corner position: {tlx} {tly}")

        if decision == "Fold":
            coo = self.table_dict['mouse_fold']
            self.take_action(coo['x1'] + tlx, coo['y1'] + tly, coo['x2'] + tlx, coo['y2'] + tly)

        elif decision == "Imback":
            human_sleep(0, 3)
            coo = self.table_dict['mouse_imback']
            self.take_action(coo['x1'] + tlx, coo['y1'] + tly, coo['x2'] + tlx, coo['y2'] + tly)

        elif decision == "resume_hand":
            human_sleep(0, 3)
            coo = self.table_dict['mouse_resume_hand']
            self.take_action(coo['x1'] + tlx, coo['y1'] + tly, coo['x2'] + tlx, coo['y2'] + tly)

        elif decision == "Call":
            coo = self.table_dict['mouse_call']
            self.take_action(coo['x1'] + tlx, coo['y1'] + tly, coo['x2'] + tlx, coo['y2'] + tly)

        elif decision == "Call2":
            coo = self.table_dict['mouse_call2']
            self.take_action(coo['x1'] + tlx, coo['y1'] + tly, coo['x2'] + tlx, coo['y2'] + tly)

        elif decision == "Check":
            coo = self.table_dict['mouse_check']
            self.take_action(coo['x1'] + tlx, coo['y1'] + tly, coo['x2'] + tlx, coo['y2'] + tly)

        elif decision == "Bet":
            coo = self.table_dict['mouse_raise']
            self.take_action(coo['x1'] + tlx, coo['y1'] + tly, coo['x2'] + tlx, coo['y2'] + tly)

        elif decision == "BetPlus":
            for i in range(int(options['increases_num'])):
                coo = self.table_dict['mouse_increase']
                self.take_action(coo['x1'] + tlx, coo['y1'] + tly, coo['x2'] + tlx, coo['y2'] + tly)

            coo = self.table_dict['mouse_raise']
            self.take_action(coo['x1'] + tlx, coo['y1'] + tly, coo['x2'] + tlx, coo['y2'] + tly)

        elif decision == "Bet Bluff":
            coo = self.table_dict['mouse_raise']
            self.take_action(coo['x1'] + tlx, coo['y1'] + tly, coo['x2'] + tlx, coo['y2'] + tly)

        elif decision == "Bet half pot":
            coo = self.table_dict['mouse_half_pot']
            self.take_action(coo['x1'] + tlx, coo['y1'] + tly, coo['x2'] + tlx, coo['y2'] + tly)

            coo = self.table_dict['mouse_raise']
            self.take_action(coo['x1'] + tlx, coo['y1'] + tly, coo['x2'] + tlx, coo['y2'] + tly)

        elif decision == "Bet pot":
            coo = self.table_dict['mouse_full_pot']
            self.take_action(coo['x1'] + tlx, coo['y1'] + tly, coo['x2'] + tlx, coo['y2'] + tly)

            coo = self.table_dict['mouse_raise']
            self.take_action(coo['x1'] + tlx, coo['y1'] + tly, coo['x2'] + tlx, coo['y2'] + tly)

        elif decision == "Bet max":
            coo = self.table_dict['mouse_all_in']
            self.take_action(coo['x1'] + tlx, coo['y1'] + tly, coo['x2'] + tlx, coo['y2'] + tly)

            coo = self.table_dict['mouse_raise']
            self.take_action(coo['x1'] + tlx, coo['y1'] + tly, coo['x2'] + tlx, coo['y2'] + tly)

        human_sleep(0.1, 0.3)
        self.move_mouse_away_from_buttons()

    def take_action(self, x1, y1, x2, y2):  #

        log.debug(f"Target position: {x1} {y1} {x2} {y2}")
        if not self.vbox_mode:
            (old_x1, old_y1) = self.mouse.position()
        else:
            old_x1 = self.old_x
            old_y1 = self.old_y

        self.mouse_mover(old_x1, old_y1, x1, y1)
        self.mouse_clicker(x1, y1, x2 - x1, y2 - y1)
