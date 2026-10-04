"""Offline checks for dynamic screenshot coordinates and explicit ADB selection."""
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, call, patch

import subprocess
import os

import cv2 as cv
import numpy as np

import daily_task
from pcrscript.actions import ClickAction, SwipeAction
from pcrscript.driver import ADBDriver
from pcrscript.game_ui.screen import EventUI
from pcrscript.robot import Robot
from pcrscript.runtime import open_leidian_emulator, select_driver
from pcrscript.simulator import DNSimulator, GeneralSimulator


class DeviceAdaptationTests(TestCase):
    def test_invalid_handle_retry_keeps_the_same_configured_console(self):
        path='C:/Program Files/synthetic'
        error=subprocess.CalledProcessError(-1073741816,'list2')
        with patch('pcrscript.leidian_console.subprocess.check_output',
                   side_effect=[error,'0,private,101,102,1,7,8,960,540,240\n']) as query:
            simulator=DNSimulator(path,useADB=False)
            self.assertEqual(simulator.get_devices(),['0'])
        self.assertEqual(query.call_count,2)
        for invocation in query.call_args_list:
            self.assertEqual(invocation.args[0],[os.path.join(path,'ldconsole.exe'),'list2'])
            self.assertEqual(invocation.kwargs['stdin'],subprocess.DEVNULL)
            self.assertEqual(invocation.kwargs['stderr'],subprocess.PIPE)

    def test_permanent_list_error_and_zero_handles_do_not_trigger_retries(self):
        for result in (subprocess.CalledProcessError(1,'list2'),
                       subprocess.TimeoutExpired('list2',15),'0,private,0,0,0,-1,-1,960,540,240\n'):
            with self.subTest(result=type(result).__name__), \
                 patch('pcrscript.leidian_console.subprocess.check_output') as query:
                if isinstance(result,Exception):query.side_effect=result
                else:query.return_value=result
                simulator=DNSimulator('C:/synthetic',useADB=False)
                self.assertFalse(simulator.get_devices())
                query.assert_called_once()

    def test_persistent_invalid_handle_has_a_finite_read_only_budget(self):
        error=subprocess.CalledProcessError(3221225480,'list2')
        with patch('pcrscript.leidian_console.subprocess.check_output',side_effect=error) as query:
            simulator=DNSimulator('C:/synthetic',useADB=False)
            self.assertIsNone(simulator.get_devices())
        self.assertEqual(query.call_count,3)
        self.assertEqual(simulator.last_discovery['exit_code'],'0xC0000008')

    def test_zero_window_handles_are_context_evidence_not_a_closed_emulator(self):
        raw = '0,private window title,0,0,0,-1,-1,960,540,240\n'
        with patch('pcrscript.simulator.subprocess.check_output', return_value=raw), \
                patch('pcrscript.simulator.GeneralSimulator.get_devices') as adb:
            simulator = DNSimulator('C:/synthetic', useADB=False)
            self.assertEqual(simulator.get_devices(), [])
            self.assertEqual(simulator.last_discovery['status'], 'not_visible')
            self.assertEqual(simulator.last_discovery['devices'][0]['width'], 960)
            self.assertNotIn('private window title', str(simulator.last_discovery))
            with self.assertRaisesRegex(RuntimeError, '不能证明模拟器未启动.*沙箱'):
                select_driver({'Extra': {'dnpath': 'C:/synthetic'}})
            adb.assert_not_called()

    def test_bad_list2_row_does_not_hide_a_later_live_window(self):
        raw = 'bad,row\n0,hidden,0,0,0,-1,-1,960,540,240\n2,live,101,102,1,7,8,960,540,240\n'
        with patch('pcrscript.simulator.subprocess.check_output', return_value=raw):
            simulator = DNSimulator('C:/synthetic', useADB=False)
            self.assertEqual(simulator.get_devices(), ['2'])
        self.assertEqual(simulator.last_discovery['malformed_rows'], 1)
        self.assertEqual(simulator.last_discovery['status'], 'visible')

    def test_list2_errors_retain_cause_without_switching_transport(self):
        errors = [FileNotFoundError('private path'), PermissionError('private path'),
                  subprocess.TimeoutExpired('list2', 15),
                  subprocess.CalledProcessError(3221225480, 'list2')]
        for error in errors:
            with self.subTest(error=type(error).__name__), \
                    patch('pcrscript.simulator.subprocess.check_output', side_effect=error), \
                    patch('pcrscript.simulator.GeneralSimulator.get_devices') as adb:
                simulator = DNSimulator('C:/synthetic', useADB=False)
                self.assertIsNone(simulator.get_devices())
                report = simulator.last_discovery
                self.assertEqual(report['status'], 'query_failed')
                self.assertEqual(report['error'], type(error).__name__)
                self.assertNotIn('private path', str(report))
                if isinstance(error, subprocess.CalledProcessError):
                    self.assertIn('0xC0000008', simulator.discovery_error())
                adb.assert_not_called()

    def test_agent_device_diagnosis_never_constructs_a_game_runner(self):
        from scripts.agent import game
        with patch('sys.argv', ['game.py', '--diagnose']), \
                patch('pcrscript.run_session.assert_inspection_allowed') as guard, \
                patch('pcrscript.runtime.load_config', return_value={'Extra': {'dnpath': 'C:/synthetic'}}), \
                patch('pcrscript.simulator.subprocess.check_output', return_value=''), \
                patch.object(game, 'runner_from_config') as runner, patch('builtins.print'):
            game.main()
        guard.assert_called_once()
        runner.assert_not_called()

    def test_daily_cli_only_runs_tasks_after_zero_launch_status(self):
        config = {'Extra': {'dnpath': 'C:/synthetic'}, 'Task': {1: [['normal_gacha']]}}
        for code in (-1, 1, 7, 0):
            with self.subTest(code=code), \
                    patch('sys.argv', ['daily_task.py', '--config', 'synthetic.yml']), \
                    patch.object(daily_task, 'load_config', return_value=config), \
                    patch.object(daily_task, 'open_leidian_emulator', return_value=code), \
                    patch.object(daily_task, 'run_script') as run:
                if code:
                    with self.assertRaisesRegex(RuntimeError, '雷电启动失败'):
                        daily_task.main()
                    run.assert_not_called()
                else:
                    daily_task.main()
                    run.assert_called_once_with(config)

    def test_leidian_start_preserves_spaces_in_installation_path(self):
        path = 'C:/Program Files/LDPlayer9'
        with patch.object(DNSimulator, '_get_process_descriptions', return_value=[]), \
                patch('pcrscript.simulator.subprocess.Popen') as start:
            DNSimulator(path).start()
        start.assert_called_once_with([os.path.join(path, 'dnplayer.exe')])

    def test_leidian_open_app_returns_actual_process_result(self):
        path = 'C:/Program Files/LDPlayer9'
        with patch('pcrscript.simulator.subprocess.run', return_value=Mock(returncode=7)) as run, \
                patch('pcrscript.simulator.os.system', return_value=7):
            result = DNSimulator(path).open_app('com.bilibili.priconne', device=2)
        self.assertEqual(result, 7)
        run.assert_called_once_with([os.path.join(path, 'ldconsole.exe'), 'runapp',
                                     '--index', '2', '--packagename', 'com.bilibili.priconne'], timeout=30)

    def test_failed_process_discovery_reports_an_actionable_error(self):
        with patch.object(DNSimulator, '_get_process_descriptions', return_value=None), \
                patch('pcrscript.simulator.subprocess.Popen') as start:
            with self.assertRaisesRegex(RuntimeError, '进程'):
                DNSimulator('C:/synthetic').start()
        start.assert_not_called()

    def test_transport_selection_is_explicit_and_rejects_ambiguous_adb(self):
        with patch('pcrscript.runtime.GeneralSimulator.get_devices', return_value=['phone-1', 'phone-2']):
            with self.assertRaisesRegex(RuntimeError, '多个 ADB'):
                select_driver({'Extra': {'dnpath': ''}})
            self.assertEqual(select_driver({'Extra': {'dnpath': '', 'adb_serial': 'phone-2'}}).device_name, 'phone-2')
            with self.assertRaisesRegex(RuntimeError, '未连接'):
                select_driver({'Extra': {'adb_serial': 'missing'}})
        driver = ADBDriver('phone-1')
        with patch('pcrscript.runtime.DNSimulator') as leiden:
            leiden.return_value.get_dirvers.return_value = [driver]
            self.assertIs(select_driver({'Extra': {'dnpath': 'C:/synthetic'}}), driver)
            leiden.assert_called_once_with('C:/synthetic', useADB=False)

    def test_adb_driver_reads_screenshot_and_size_without_temp_file(self):
        driver = ADBDriver('127.0.0.1:5555')
        sample = np.zeros((4, 6, 3), dtype=np.uint8)
        sample[0, 0] = (12, 34, 56)
        png = cv.imencode('.png', sample)[1].tobytes()
        with patch('pcrscript.driver.subprocess.run', side_effect=[Mock(stdout=b'Physical size: 960x540\n'), Mock(stdout=png)]) as adb:
            self.assertEqual(driver.get_screen_size(), (960, 540))
            self.assertEqual(tuple(driver.screenshot()[0, 0]), (12, 34, 56))
        self.assertEqual(adb.call_args_list[1].args[0], ['adb', '-s', '127.0.0.1:5555', 'exec-out', 'screencap', '-p'])

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

    def test_leidian_uses_its_bundled_adb_without_overriding_an_explicit_path(self):
        with TemporaryDirectory() as root:
            bundled = Path(root)/'adb.exe'
            bundled.touch()
            peer = Mock()
            with patch('pcrscript.runtime.DNSimulator.get_dirvers', return_value=[peer]), \
                    patch('pcrscript.runtime.GeneralSimulator.get_devices') as discovery:
                self.assertIs(select_driver({'Extra': {'dnpath': root}}), peer)
                self.assertEqual(peer.adb_path, str(bundled))
                self.assertIs(select_driver({'Extra': {'dnpath': root,
                    'adb_path': 'C:/explicit/adb.exe'}}), peer)
                self.assertEqual(peer.adb_path, 'C:/explicit/adb.exe')
            discovery.assert_not_called()

    def test_adb_can_route_unicode_input_through_explicit_leidian_console(self):
        with TemporaryDirectory() as root:
            console=Path(root)/'ldconsole.exe'
            console.touch()
            with patch('pcrscript.runtime.GeneralSimulator.get_devices',return_value=['phone-1']):
                driver=select_driver({'Extra': {'dnpath': '', 'adb_serial': 'phone-1',
                    'adb_unicode_console_path': str(console), 'adb_unicode_console_index': 2}})
            self.assertTrue(driver.supports_unicode_input)
            with patch('pcrscript.driver.subprocess.run',return_value=Mock(stdout=b'')) as command:
                driver.input('厄里斯')
            command.assert_called_once_with([str(console), 'action', '--index', '2',
                                             '--key', 'call.input', '--value', '厄里斯'],
                                            check=True, timeout=15,
                                            stdin=subprocess.DEVNULL, capture_output=True,
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def test_adb_unicode_console_must_exist(self):
        with self.assertRaisesRegex(ValueError,'adb_unicode_console_path'):
            select_driver({'Extra': {'dnpath': '',
                'adb_unicode_console_path': 'C:/missing/ldconsole.exe'}})

    def test_startup_recovers_in_existing_loop(self):
        error = subprocess.CalledProcessError(3221225480, ['ldconsole.exe', 'list2'])
        timeout = subprocess.TimeoutExpired('list2', 15)
        with patch('pcrscript.runtime.DNSimulator') as factory, \
                patch('pcrscript.runtime.time.sleep') as sleep:
            simulator = factory.return_value
            simulator.online.side_effect = [False, error, timeout, True]
            simulator.open_app.return_value = 0
            self.assertEqual(open_leidian_emulator('C:/synthetic'), 0)
        self.assertEqual(simulator.online.call_count, 4)
        self.assertEqual(sleep.call_args_list, [call(20), call(20), call(20), call(10)])
        simulator.open_app.assert_called_once_with('com.bilibili.priconne')

    def test_persistent_query_failure_stops_after_ten_attempts(self):
        error = subprocess.CalledProcessError(3221225480, ['ldconsole.exe', 'list2'])
        with patch('pcrscript.runtime.DNSimulator') as factory, \
                patch('pcrscript.runtime.time.sleep') as sleep:
            simulator = factory.return_value
            simulator.online.side_effect = error
            with self.assertRaisesRegex(RuntimeError, '0xC0000008') as raised:
                open_leidian_emulator('C:/synthetic')
        self.assertIs(raised.exception.__cause__, error)
        self.assertEqual(simulator.online.call_count, 10)
        self.assertEqual(sleep.call_args_list, [call(20)] * 9)
        simulator.open_app.assert_not_called()

    def test_permanent_configuration_failure_does_not_retry(self):
        with patch('pcrscript.runtime.DNSimulator') as factory, \
                patch('pcrscript.runtime.time.sleep') as sleep:
            simulator = factory.return_value
            simulator.online.side_effect = FileNotFoundError('missing console')
            with self.assertRaises(FileNotFoundError):
                open_leidian_emulator('C:/missing')
        simulator.online.assert_called_once()
        simulator.open_app.assert_not_called()
        sleep.assert_not_called()

    def test_offline_deadline_does_not_report_a_stale_query_error(self):
        error = subprocess.CalledProcessError(3221225480, ['ldconsole.exe', 'list2'])
        with patch('pcrscript.runtime.DNSimulator') as factory, \
                patch('pcrscript.runtime.time.sleep') as sleep:
            simulator = factory.return_value
            simulator.online.side_effect = [error] + [False] * 9
            self.assertEqual(open_leidian_emulator('C:/synthetic'), -1)
        self.assertEqual(simulator.online.call_count, 10)
        self.assertEqual(sleep.call_args_list, [call(20)] * 9)
        simulator.open_app.assert_not_called()
