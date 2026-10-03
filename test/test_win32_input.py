"""Synthetic native-window checks; never connect to an emulator."""
import ctypes
import numpy as np
from unittest import TestCase, main
from unittest.mock import Mock, patch

from win32 import win32api
from win32.lib import win32con

from pcrscript.driver import ADBDriver, DNDriver, Win32Driver, _physical_input_context


class NativeInputTests(TestCase):
    def test_near_black_native_surface_uses_the_verified_background_capture(self):
        driver = self.driver()
        stale = np.zeros((540, 960, 3), dtype=np.uint8)
        current = np.full_like(stale, 120)
        peer = Mock(screenshot=Mock(return_value=current))
        driver._scroll_fallback_driver = Mock(return_value=peer)
        with patch.object(Win32Driver, 'screenshot', return_value=stale):
            self.assertIs(driver.screenshot(), current)
        driver._scroll_fallback_driver.assert_called_once_with()
        peer.screenshot.assert_called_once_with(output='screen_shot.png')

    def test_visible_native_frame_does_not_require_an_adb_capture(self):
        driver = self.driver()
        current = np.full((540, 960, 3), 120, dtype=np.uint8)
        driver._scroll_fallback_driver = Mock()
        with patch.object(Win32Driver, 'screenshot', return_value=current):
            self.assertIs(driver.screenshot(), current)
        driver._scroll_fallback_driver.assert_not_called()

    def test_loading_frame_is_retained_when_background_connection_is_unverified(self):
        driver = self.driver()
        loading = np.zeros((540, 960, 3), dtype=np.uint8)
        driver._scroll_fallback_driver = Mock(side_effect=RuntimeError('ambiguous device'))
        with patch.object(Win32Driver, 'screenshot', return_value=loading):
            self.assertIs(driver.screenshot(), loading)

    def test_scroll_fallback_binds_only_the_unique_running_instance_and_connection(self):
        driver = self.driver()
        driver.adb_path, driver.dnpath, driver.device_name, driver.index = 'adb.exe', 'synthetic', '0', 0
        peer = Mock(get_screen_size=Mock(return_value=(960,540)))
        with patch('pcrscript.simulator.GeneralSimulator.get_devices', return_value=['synthetic-serial']), \
                patch('pcrscript.driver.subprocess.check_output', return_value='0,test,1,101,1,1,1,960,540\n'), \
                patch('pcrscript.driver.ADBDriver', return_value=peer):
            driver.swipe((907,237), (907,310), 300, fallback=True)
        peer.swipe.assert_called_once_with((907,237), (907,310), 300)

    def test_scroll_fallback_rejects_ambiguous_devices_instances_and_sizes(self):
        for devices, running, size in ((['a','b'], '0,test,1,101,1,1,1,960,540\n', (960,540)),
                (['a'], '0,test,1,101,1,1,1,960,540\n1,other,1,102,1,2,2,960,540\n', (960,540)),
                (['a'], '0,test,1,101,1,1,1,960,540\n', (1280,720))):
            driver = self.driver()
            driver.adb_path, driver.dnpath, driver.device_name, driver.index = 'adb.exe', 'synthetic', '0', 0
            peer = Mock(get_screen_size=Mock(return_value=size))
            with self.subTest(devices=devices, size=size), \
                    patch('pcrscript.simulator.GeneralSimulator.get_devices', return_value=devices), \
                    patch('pcrscript.driver.subprocess.check_output', return_value=running), \
                    patch('pcrscript.driver.ADBDriver', return_value=peer):
                with self.assertRaises(RuntimeError):
                    driver.swipe((907,237), (907,310), 300, fallback=True)
                peer.swipe.assert_not_called()

    def context(self):
        state = {'aware': False}
        def set_context(value):
            old = 2 if state['aware'] else 1
            state['aware'] = value != 1
            return old
        return state, Mock(side_effect=set_context)

    def driver(self):
        driver = DNDriver.__new__(DNDriver)
        driver.click_by_mouse = True
        driver.get_hwnd = Mock(return_value=101)
        driver.get_screen_size = Mock(return_value=(960, 540))
        driver.reset_hwnd = Mock()
        return driver

    def test_click_and_drag_keep_geometry_and_messages_in_one_dpi_context(self):
        state, setter = self.context()
        messages = []
        def rect(hwnd):
            return (100, 100, 1060, 640) if state['aware'] else (57, 57, 605, 365)
        def send(hwnd, message, flags, position):
            messages.append((message, position, state['aware'], flags))
        with patch.object(ctypes.windll.user32, 'SetThreadDpiAwarenessContext', setter), \
                patch('pcrscript.driver.win32gui.GetWindowRect', side_effect=rect), \
                patch('pcrscript.driver.win32api.SendMessage', side_effect=send), \
                patch('pcrscript.driver.time.sleep'), \
                patch.object(ADBDriver, 'click') as adb_click, \
                patch.object(ADBDriver, 'swipe') as adb_swipe:
            driver = self.driver()
            driver.click(480, 270)
            self.assertFalse(state['aware'])
            driver.swipe((100, 100), (400, 300), duration=200)
        self.assertEqual(messages[0][1], win32api.MAKELONG(480, 270))
        self.assertEqual([message for message, _, _, _ in messages[:3]],
                         [win32con.WM_MOUSEMOVE,win32con.WM_LBUTTONDOWN,win32con.WM_LBUTTONUP])
        self.assertEqual(messages[-2][:2], (win32con.WM_MOUSEMOVE, win32api.MAKELONG(400, 300)))
        self.assertEqual(messages[-1][:2], (win32con.WM_LBUTTONUP, win32api.MAKELONG(400, 300)))
        self.assertTrue(all(aware for _, _, aware, _ in messages))
        pressed = False
        for message, _, _, flags in messages:
            if message == win32con.WM_LBUTTONDOWN:
                pressed = True
            elif message == win32con.WM_LBUTTONUP:
                pressed = False
            elif message == win32con.WM_MOUSEMOVE:
                self.assertEqual(flags, win32con.MK_LBUTTON if pressed else 0)
        self.assertTrue(all(flags == 0 for message, _, _, flags in messages
                            if message == win32con.WM_LBUTTONUP))
        self.assertFalse(state['aware'])
        adb_click.assert_not_called()
        adb_swipe.assert_not_called()

    def test_exception_restores_the_callers_dpi_context(self):
        state, setter = self.context()
        with patch.object(ctypes.windll.user32, 'SetThreadDpiAwarenessContext', setter):
            with self.assertRaises(ValueError), _physical_input_context():
                self.assertTrue(state['aware'])
                raise ValueError('synthetic failure')
        self.assertFalse(state['aware'])
        self.assertEqual(setter.call_count, 2)

    def test_native_failure_preserves_the_existing_adb_fallback(self):
        state, setter = self.context()
        with patch.object(ctypes.windll.user32, 'SetThreadDpiAwarenessContext', setter), \
                patch('pcrscript.driver.win32gui.GetWindowRect', side_effect=RuntimeError('synthetic failure')), \
                patch.object(ADBDriver, 'click') as fallback:
            driver = self.driver()
            driver.click(123, 456)
        fallback.assert_called_once_with(123, 456)
        driver.reset_hwnd.assert_called_once()
        self.assertFalse(state['aware'])


if __name__ == '__main__':
    main()
