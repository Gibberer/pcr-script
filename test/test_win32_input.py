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
        driver._capture_consistency_checked = True
        with patch.object(Win32Driver, 'screenshot', return_value=current):
            self.assertIs(driver.screenshot(), current)
        driver._scroll_fallback_driver.assert_not_called()

    def test_full_old_native_page_switches_to_verified_current_capture(self):
        driver = self.driver()
        old = np.full((540,960,3), 40, dtype=np.uint8)
        current = np.full_like(old, 180)
        peer = Mock(screenshot=Mock(return_value=current))
        driver._scroll_fallback_driver = Mock(return_value=peer)
        with patch.object(Win32Driver, 'screenshot', return_value=old) as native:
            self.assertIs(driver.screenshot(), current)
            self.assertIs(driver.screenshot(), current)
        self.assertEqual(native.call_count, 1)
        self.assertEqual(peer.screenshot.call_count, 2)

    def test_stale_balance_on_otherwise_same_page_uses_current_background(self):
        driver=self.driver()
        old=np.full((540,960,3),120,dtype=np.uint8);current=old.copy()
        current[420:440,740:760]=200
        peer=Mock(screenshot=Mock(return_value=current))
        driver._scroll_fallback_driver=Mock(return_value=peer)
        with patch.object(Win32Driver,'screenshot',return_value=old):
            self.assertIs(driver.screenshot(),current)
            self.assertIs(driver.screenshot(),current)
        self.assertTrue(driver._use_background_capture)

    def test_unchanged_native_input_receipt_is_checked_without_replaying_input(self):
        driver = self.driver()
        native = np.full((540,960,3), 40, dtype=np.uint8)
        current = np.full_like(native, 180)
        peer = Mock(screenshot=Mock(side_effect=[native, current]))
        driver._scroll_fallback_driver = Mock(return_value=peer)
        with patch.object(Win32Driver, 'screenshot', return_value=native), \
                patch.object(Win32Driver, 'click') as click:
            self.assertIs(driver.screenshot(), native)
            driver.click(123,456)
            self.assertIs(driver.screenshot(), current)
        click.assert_called_once_with(123,456)
        self.assertEqual(peer.screenshot.call_count, 2)

    def test_capture_comparison_rejects_different_device_dimensions(self):
        driver = self.driver()
        native = np.full((540,960,3), 40, dtype=np.uint8)
        peer = Mock(screenshot=Mock(return_value=np.full((720,1280,3), 180, dtype=np.uint8)))
        driver._scroll_fallback_driver = Mock(return_value=peer)
        with patch.object(Win32Driver, 'screenshot', return_value=native):
            self.assertIs(driver.screenshot(), native)
        self.assertFalse(getattr(driver,'_use_background_capture',False))

    def test_loading_frame_is_retained_when_background_connection_is_unverified(self):
        driver = self.driver()
        loading = np.zeros((540, 960, 3), dtype=np.uint8)
        driver._scroll_fallback_driver = Mock(side_effect=RuntimeError('ambiguous device'))
        with patch.object(Win32Driver, 'screenshot', return_value=loading):
            self.assertIs(driver.screenshot(), loading)

    def test_scroll_fallback_binds_only_the_configured_connection(self):
        driver = self.driver()
        driver.adb_path, driver.dnpath, driver.device_name, driver.index = 'adb.exe', 'synthetic', '0', 0
        driver.adb_fallback_serial = 'synthetic-serial'
        peer = Mock(get_screen_size=Mock(return_value=(960,540)))
        with patch('pcrscript.simulator.GeneralSimulator.get_devices', return_value=['phone', 'synthetic-serial']), \
                patch('pcrscript.driver.ADBDriver', return_value=peer) as adb:
            driver.swipe((907,237), (907,310), 300, fallback=True)
        adb.assert_called_once_with('synthetic-serial', 'adb.exe')
        peer.swipe.assert_called_once_with((907,237), (907,310), 300)

    def test_scroll_fallback_rejects_missing_connection_and_wrong_size(self):
        for devices, size in ((['b'], (960,540)), (['a'], (1280,720))):
            driver = self.driver()
            driver.adb_path, driver.dnpath, driver.device_name, driver.index = 'adb.exe', 'synthetic', '0', 0
            driver.adb_fallback_serial = 'a'
            peer = Mock(get_screen_size=Mock(return_value=size))
            with self.subTest(devices=devices, size=size), \
                    patch('pcrscript.simulator.GeneralSimulator.get_devices', return_value=devices), \
                    patch('pcrscript.driver.ADBDriver', return_value=peer):
                with self.assertRaises(RuntimeError):
                    driver.swipe((907,237), (907,310), 300, fallback=True)
                peer.swipe.assert_not_called()

    def test_empty_serial_uses_only_the_exact_leidian_instance_query(self):
        driver = self.driver()
        driver.adb_path, driver.dnpath, driver.index = 'adb.exe', 'synthetic', 2
        peer = Mock(get_screen_size=Mock(return_value=(960,540)))
        with patch('pcrscript.driver.subprocess.check_output',return_value='emulator-5558\r\n') as query, \
             patch('pcrscript.simulator.GeneralSimulator.get_devices',return_value=['phone','emulator-5558']), \
             patch('pcrscript.driver.ADBDriver',return_value=peer) as adb:
            self.assertIs(driver._scroll_fallback_driver(),peer)
        self.assertEqual(query.call_args.args[0][1:],
                         ['adb','--index','2','--command','get-serialno'])
        adb.assert_called_once_with('emulator-5558','adb.exe')

    def test_single_same_sized_phone_is_not_a_verified_leidian_connection(self):
        for name in ('0', 'phone'):
            with self.subTest(name=name):
                driver = self.driver()
                driver.adb_path, driver.dnpath, driver.device_name, driver.index = 'adb.exe', 'synthetic', name, 0
                loading = np.zeros((540,960,3), np.uint8)
                peer = Mock(get_screen_size=Mock(return_value=(960,540)))
                with patch('pcrscript.simulator.GeneralSimulator.get_devices', return_value=['phone']), \
                     patch('pcrscript.driver.subprocess.check_output', return_value='0,test,1,101,1,1,1,960,540\n'), \
                     patch('pcrscript.driver.ADBDriver', return_value=peer) as adb, \
                     patch.object(Win32Driver, 'screenshot', return_value=loading):
                    with self.assertRaisesRegex(RuntimeError, 'Extra.adb_serial'):
                        driver.swipe((907,237), (907,310), 300, fallback=True)
                    self.assertIs(driver.screenshot(), loading)
                adb.assert_not_called()
                peer.screenshot.assert_not_called()
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

    def test_native_capture_uses_physical_pixels_and_restores_context(self):
        state, setter = self.context()
        driver = self.driver()
        source, memory, bitmap = Mock(), Mock(), Mock()
        source.CreateCompatibleDC.return_value = memory
        pixels = np.full((540, 960, 4), 120, dtype=np.uint8)
        bitmap.GetBitmapBits.return_value = pixels.tobytes()
        observed = []
        def observe(*args, **kwargs):
            observed.append(state['aware'])
        memory.BitBlt.side_effect = observe
        bitmap.CreateCompatibleBitmap.side_effect = observe
        with patch.object(ctypes.windll.user32, 'SetThreadDpiAwarenessContext', setter), \
                patch('pcrscript.driver.win32gui.GetWindowDC', return_value=201), \
                patch('pcrscript.driver.win32ui.CreateDCFromHandle', return_value=source), \
                patch('pcrscript.driver.win32ui.CreateBitmap', return_value=bitmap), \
                patch('pcrscript.driver.win32gui.ReleaseDC'), \
                patch('pcrscript.driver.win32gui.DeleteObject'), \
                patch.object(ADBDriver, 'screenshot') as fallback:
            image = Win32Driver.screenshot(driver)
        self.assertEqual(image.shape, (540, 960, 3))
        self.assertTrue((image == 120).all())
        self.assertEqual(observed, [True, True])
        self.assertFalse(state['aware'])
        self.assertEqual(setter.call_count, 2)
        fallback.assert_not_called()

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
