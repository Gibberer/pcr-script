"""Offline checks for dynamic screenshot coordinates and explicit ADB selection."""
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import numpy as np

from pcrscript.actions import ClickAction, SwipeAction
from pcrscript.driver import ADBDriver
from pcrscript.game_ui.screen import EventUI
from pcrscript.robot import Robot
from pcrscript.runtime import select_driver
from pcrscript.simulator import GeneralSimulator


class DeviceAdaptationTests(TestCase):
    def test_event_ui_uses_captured_frame_for_ocr_and_coordinates(self):
        driver = Mock()
        driver.get_screen_size.side_effect = AssertionError('stale device metadata')
        driver.screenshot.return_value = np.zeros((720, 1280, 3), dtype=np.uint8)
        with TemporaryDirectory() as output, patch('pcrscript.game_ui.screen.time.sleep'):
            ui = EventUI(driver, output=output)
            self.assertEqual(ui.capture(ocr=False).image.shape[:2], (540, 960))
            ui.click((480, 270), delay=0)
            ui.swipe((240, 135), (720, 405))
        driver.get_screen_size.assert_not_called()
        driver.click.assert_called_once_with(640, 360)
        driver.swipe.assert_called_once_with((320, 180), (960, 540), 450)

    def test_legacy_actions_follow_latest_screenshot_size(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        driver = Mock(get_screen_size=Mock(return_value=(960, 540)))
        driver.screenshot.return_value = frame
        robot = Robot(driver, show_progress=False)
        click = ClickAction(pos=(480, 270)).bindTask(robot._dummy_task)
        swipe = SwipeAction((240, 135), (720, 405)).bindTask(robot._dummy_task)
        with patch('pcrscript.robot.time.sleep'):
            robot.action_squential(click, swipe, delay=0, net_error_check=False)
        driver.click.assert_called_once_with(640, 360)
        driver.swipe.assert_called_once_with((320, 180), (960, 540), 200)

    def test_adb_discovery_ignores_unauthorized_devices(self):
        output = 'List of devices attached\nphone-1\tdevice\nphone-2\tunauthorized\nphone-3\toffline\n'
        with patch('pcrscript.simulator.subprocess.run', return_value=Mock(stdout=output)) as command:
            self.assertEqual(GeneralSimulator('C:/tools/adb.exe').get_devices(), ['phone-1'])
        command.assert_called_once_with(['C:/tools/adb.exe', 'devices'], capture_output=True,
                                        text=True, check=True, timeout=15)

    def test_configured_adb_executable_is_used_for_device_actions(self):
        with patch('pcrscript.runtime.GeneralSimulator.get_devices', return_value=['phone-1']):
            driver = select_driver({'Extra': {'dnpath': '', 'adb_path': 'C:/tools/adb.exe',
                                              'adb_serial': 'phone-1'}})
        self.assertIsInstance(driver, ADBDriver)
        self.assertEqual(driver.adb_path, 'C:/tools/adb.exe')
        with patch('pcrscript.driver.subprocess.run', return_value=Mock(stdout=b'')) as command:
            driver.click(123, 45)
        self.assertEqual(command.call_args.args[0],
                         ['C:/tools/adb.exe', '-s', 'phone-1', 'shell', 'input', 'tap', '123', '45'])
