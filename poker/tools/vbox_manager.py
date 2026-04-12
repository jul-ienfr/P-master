import time
import logging
import numpy as np
try:
    import virtualbox
except ImportError:
    virtualbox = None
from PIL import Image

from poker.tools.helper import get_config


VirtualBoxMouseBase = virtualbox.library.IMouse if virtualbox is not None else object


class VirtualBoxController(VirtualBoxMouseBase):
    def __init__(self):
        self.vm = None
        self.session = None
        self.logger = logging.getLogger('vm_control')
        self.logger.setLevel(logging.DEBUG)
        self.vbox = None
        self.control_name = 'Direct mouse control'
        self.vbox_ready = False

        try:
            config = get_config()
            self.control_name = config.config.get('main', 'control')
        except Exception:
            pass

        if virtualbox is None:
            self.logger.warning("virtualbox Python package is not installed")
            return
        super().__init__()
        try:
            self.vbox = virtualbox.VirtualBox()
            if self.control_name == 'Direct mouse control':
                return

            if self.control_name not in self.get_vbox_list():
                self.logger.warning("Configured virtual machine '%s' was not found", self.control_name)
                return

            self.start_vm()
            self.vbox_ready = self.session is not None
            if self.vbox_ready:
                self.logger.debug("VM session established successfully")
            else:
                self.logger.warning("Unable to establish a VirtualBox session for '%s'", self.control_name)

        except Exception as e:
            self.logger.error(str(e))

    def start_vm(self):
        try:
            if self.control_name != 'Direct mouse control':
                self.vm = self.vbox.find_machine(self.control_name)
                self.session = self.vm.create_session()
        except Exception as e:
            self.logger.warning(str(e))

    def get_vbox_list(self):
        if self.vbox is None:
            return []
        vm_list = [vm.name for vm in self.vbox.machines]
        return vm_list

    def is_ready(self):
        return self.vbox_ready

    def get_screenshot_vbox(self):
        h, w, _, _, _, _ = self.session.console.display.get_screen_resolution(0)
        png = self.session.console.display.take_screen_shot_to_array(0, h, w, virtualbox.library.BitmapFormat.png)
        open('screenshot_vbox.png', 'wb').write(png)  # pylint: disable=consider-using-with
        # image=Image.fromarray(png)
        # image.show()
        time.sleep(0.2)
        return Image.open('screenshot_vbox.png')

    def mouse_move_vbox(self, x, y, dz=0, dw=0):
        self.session.console.mouse.put_mouse_event_absolute(x, y, dz, dw, 0)

    def mouse_click_vbox(self, x, y, dz=0, dw=0):
        self.session.console.mouse.put_mouse_event_absolute(x, y, dz, dw, 0b1)
        time.sleep(np.random.uniform(0.4, 0.6, 1)[0])
        self.session.console.mouse.put_mouse_event_absolute(x, y, dz, dw, 0)

    def keyboard_type_vbox(self, text):
        """Type a string into the VirtualBox console."""
        # Note: Depending on the virtualbox ctypes binding, put_keys might act directly on strings.
        # Ensure we have the appropriate random delays between keystrokes in the calling function, 
        # or we put_keys for individual characters in `type_keyboard` inside MouseMover.
        try:
            self.session.console.keyboard.put_keys(text)
        except Exception as e:
            self.logger.warning("Failed to type keys in vbox: %s", str(e))

    def get_mouse_position_vbox(self):
        # todo: not working
        x = self.session.console.mouse_pointer_shape.hot_x()
        y = self.session.console.mouse_pointer_shape.hot_y()
        return x, y
