"""Desktop protocol regression tests; no emulator or account data."""
import json
from contextlib import nullcontext
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

import yaml

from pcrscript import desktop
from pcrscript.run_session import RunSession, RunCancelled, atomic_json, clock


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.root_patch = patch.object(desktop, 'ROOT', self.root)
        self.root_patch.start()
        self.config = self.root / 'daily_config.yml'
        self.original = {
            'Accounts': [{'account': 'synthetic', 'password': 'synthetic-only'}],
            'Extra': {'dnpath': 'C:/synthetic'}, 'Unrecognized': {'future': 7},
            'Task': {1: [['get_gift', True], ['shop_buy', {1: [-1], '1_settings': {'time': 1}}]], 2: [['normal_gacha']]},
        }
        self.config.write_text(yaml.safe_dump(self.original), encoding='utf-8')

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()

    def test_config_roundtrip_preserves_accounts_other_groups_and_numeric_keys(self):
        view = json.loads(json.dumps(desktop.config_view(self.config)))
        self.assertNotIn('Accounts', view['options'])
        view['plan'][0]['enabled'] = False
        result = desktop.save_config(self.config, view)
        saved = desktop.read_config(self.config)
        self.assertEqual(saved['Accounts'], self.original['Accounts'])
        self.assertEqual(saved['Task'][2], self.original['Task'][2])
        self.assertEqual(saved['Task'][1][0][1], self.original['Task'][1][1][1])
        self.assertEqual(saved['Unrecognized'], self.original['Unrecognized'])
        self.assertFalse(result['plan'][0]['enabled'])
        self.assertEqual(desktop.read_config(self.config.with_suffix('.yml.bak')), self.original)

    def test_conflict_does_not_overwrite_external_edits(self):
        view = desktop.config_view(self.config)
        self.config.write_text(self.config.read_text(encoding='utf-8') + '\n# external edit\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '其他程序'):
            desktop.save_config(self.config, view)
        self.assertIn('# external edit', self.config.read_text(encoding='utf-8'))

    def test_invalid_task_and_arguments_do_not_write(self):
        for name, args in [('missing', []), ('get_gift', ['false']), ('shop_buy', []), ('shop_buy', [None])]:
            view = desktop.config_view(self.config)
            view['plan'] = [dict(enabled=True, name=name, args=args)]
            with self.assertRaises((ValueError, TypeError)):
                desktop.save_config(self.config, view)
        self.assertEqual(desktop.read_config(self.config), self.original)

    def test_saved_plan_yields_to_external_task_changes(self):
        view = desktop.config_view(self.config)
        view['plan'][0]['enabled'] = False
        desktop.save_config(self.config, view)
        config = desktop.read_config(self.config)
        config['Task'][1] = [['caravan']]
        self.config.write_text(yaml.safe_dump(config), encoding='utf-8')
        self.assertEqual(desktop.config_view(self.config)['plan'], [dict(enabled=True, name='caravan', args=[])])

    def test_metadata_excludes_internal_event_and_supports_typed_defaults(self):
        by_name = {item['name']: item for item in desktop.catalog()}
        self.assertEqual(by_name['revival_event_once']['parameters'], [])
        self.assertEqual(by_name['get_gift']['parameters'][0]['type'], 'boolean')
        self.assertTrue(by_name['get_gift']['parameters'][0]['default'])

    def test_workspace_categories_and_source_device_requirement(self):
        catalog = {item['name']: item for item in desktop.catalog()}
        for name in ('clear_story', 'dungeon_first_clear', 'upgrade_all_characters', 'dungeon_sources'):
            self.assertEqual(catalog[name]['category'], 'special')
        for name in ('get_gift', 'revival_event_once', 'clear_campaign_first_time'):
            self.assertEqual(catalog[name]['category'], 'daily')
        self.assertFalse(catalog['dungeon_sources']['requires_device'])
        with patch('pcrscript.run_session.RunSession', return_value=nullcontext()), \
             patch('pcrscript.runtime.run_task_with_config', return_value={}) as dispatch:
            desktop.execute(self.config, dict(task='dungeon_sources', options={}), '00000000-0000-0000-0000-000000000003')
        dispatch.assert_called_once_with({}, 'dungeon_sources')

    def test_only_one_registered_gift_task_and_labels_distinguish_reward_pages(self):
        entries = desktop.catalog()
        self.assertEqual([t['name'] for t in entries if 'gift' in t['name']], ['get_gift'])
        labels = {t['name']: t['label'] for t in entries}
        self.assertIn('礼物箱', labels['get_gift'])
        self.assertIn('首页任务', labels['get_quest_reward'])
        self.assertNotIn('campaign_reward_exchange', labels)
        with self.assertRaisesRegex(ValueError, '已并入'):
            desktop.validate_plan([dict(enabled=True, name='campaign_reward_exchange', args=[])])

    def test_dependency_check_reports_missing_and_wrong_versions(self):
        import importlib.metadata
        (self.root / 'requirements.txt').write_text('present==1.0\nmissing==2.0\nwrong==3.0\n', encoding='utf-8')
        def version(name):
            if name == 'missing':
                raise importlib.metadata.PackageNotFoundError(name)
            return '1.0'
        with patch('importlib.metadata.version', side_effect=version):
            report = desktop.environment_report()
        self.assertFalse(report['ready'])
        self.assertEqual(report['missing'], ['missing==2.0', 'wrong==3.0'])

    def test_action_status_preserves_chinese_text(self):
        with RunSession('unicode-test', root=self.root / 'cache/daily/runs') as session:
            session.event('action', name='领取礼物', target='收取确认')
            session.status()
            state = json.loads((session.path / 'status.json').read_text(encoding='utf-8'))
            self.assertIn('领取礼物', state['current_step'][1])
            self.assertNotIn('\\u', state['current_step'][1])

    def test_run_id_cannot_escape_run_root(self):
        with self.assertRaises(ValueError):
            desktop.run_folder('../outside')

    def test_single_task_uses_memory_options_without_reading_or_saving_config(self):
        before = {p: p.read_bytes() for p in self.root.glob('*') if p.is_file()}
        options = {'Extra': {'dnpath': 'C:/synthetic'}, 'Gift': {'timeout': 30}}
        with patch.object(desktop, 'read_config', side_effect=AssertionError('must not read YAML')), \
             patch('pcrscript.run_session.RunSession', return_value=nullcontext()), \
             patch('pcrscript.runtime.run_task_with_config', return_value={'status': 'complete'}) as dispatch:
            desktop.execute(self.root / 'does-not-exist.yml', dict(task='get_gift', args=[False], options=options), '00000000-0000-0000-0000-000000000001')
        dispatch.assert_called_once_with(options, 'get_gift', False)
        after = {p: p.read_bytes() for p in self.root.glob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_single_task_without_runtime_path_stops_before_device_connection(self):
        with patch('pcrscript.runtime.robot_from_config') as connect, patch.object(desktop, 'read_config', side_effect=AssertionError('must not read YAML')):
            with self.assertRaisesRegex(ValueError, '雷电路径'):
                desktop.execute(self.root / 'absent.yml', dict(task='caravan', options={}), '00000000-0000-0000-0000-000000000001')
            connect.assert_not_called()

    def test_daily_dispatch_uses_core_runtime(self):
        with (patch('pcrscript.run_session.RunSession', return_value=nullcontext()),
             patch('pcrscript.runtime.open_leidian_emulator', return_value=0) as start,
             patch('pcrscript.runtime.run_script') as run):
            desktop.execute(self.config, dict(task='daily'), '00000000-0000-0000-0000-000000000001')
        start.assert_called_once_with('C:/synthetic')
        run.assert_called_once_with(self.original, False)

    def test_memory_dispatch_keeps_callers_options_unchanged(self):
        from pcrscript.runtime import run_task_with_config
        options = {'Extra': {'dnpath': 'C:/synthetic'}, 'Caravan': {'timeout': 10}}
        with patch('pcrscript.runtime.robot_from_config') as connect:
            run_task_with_config(options, 'caravan', option_overrides={'timeout': 20})
        self.assertEqual(options['Caravan']['timeout'], 10)
        self.assertEqual(connect.call_args.args[0]['Caravan']['timeout'], 20)
        connect.return_value.run_task.assert_called_once_with('caravan')

    def test_new_config_starts_empty_and_generates_independent_file(self):
        view = desktop.new_config()
        self.assertEqual(view['plan'], [])
        self.assertNotIn('Accounts', view['options'])
        view['plan'] = [dict(enabled=True, name='caravan', args=[])]
        view['new'] = True
        destination = self.root / 'created.yml'
        desktop.save_config(destination, view)
        self.assertEqual(desktop.read_config(destination)['Task'], {1: [['caravan']]})
        self.assertEqual(desktop.read_config(destination)['Accounts'], [])
        self.assertEqual(desktop.read_config(self.config), self.original)

    def test_save_as_copies_private_fields_without_modifying_source(self):
        request = desktop.config_view(self.config)
        request.update(source=str(self.config), source_revision=request['revision'], revision='')
        request['plan'] = [dict(enabled=True, name='normal_gacha', args=[])]
        destination = self.root / 'copy.yml'
        desktop.save_config(destination, request)
        copied = desktop.read_config(destination)
        self.assertEqual(copied['Accounts'], self.original['Accounts'])
        self.assertEqual(copied['Task'][1], [['normal_gacha']])
        self.assertEqual(copied['Task'][2], self.original['Task'][2])
        self.assertEqual(desktop.read_config(self.config), self.original)
        with self.assertRaises(ValueError):
            desktop.save_config(destination, request)

    def test_every_task_has_description_and_entry_requirement(self):
        entries = desktop.catalog()
        self.assertTrue(all(len(t['description']) > 15 and t['entry'] for t in entries))
        self.assertEqual({t['name'] for t in entries}, set(desktop.DESCRIPTIONS))

    def test_gui_removes_only_default_home_separators(self):
        config = {'Task': {1: [['tohomepage'], ['schedule'], ['tohomepage', [90, 500], 30]]}}
        view = desktop.config_data(config, '')
        self.assertEqual([row['name'] for row in view['plan']], ['schedule', 'tohomepage'])

    def test_dispatch_returns_home_before_task_and_blocks_task_on_failure(self):
        from pcrscript import Robot
        from pcrscript.tasks import Schedule
        robot = Robot(Mock(get_screen_size=Mock(return_value=(960, 540))), show_progress=False)
        calls = []
        with patch('pcrscript.robot.ToHomePage.run', side_effect=lambda **kw: calls.append('home')) as home, \
             patch.object(Schedule, 'run', side_effect=lambda: calls.append('task')) as task:
            robot.run_task('schedule')
            self.assertEqual(calls, ['home', 'task'])
            home.assert_called_once_with(timeout=60)
            home.side_effect = RuntimeError('navigation timed out')
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                robot.run_task('schedule')
            self.assertEqual(task.call_count, 1)

    def test_dispatch_preserves_current_map_and_ocr_navigation(self):
        from pcrscript import Robot
        from pcrscript.tasks import CommonAdventure, Caravan
        robot = Robot(Mock(get_screen_size=Mock(return_value=(960, 540))), show_progress=False)
        with patch('pcrscript.robot.ToHomePage.run') as home, patch.object(CommonAdventure, 'run'), patch.object(Caravan, 'run'):
            robot.run_task('common_adventure')
            robot.run_task('caravan')
            home.assert_not_called()

    def test_daily_ignores_old_default_home_rows_but_keeps_custom_requests(self):
        from pcrscript import Robot
        robot = Robot(Mock(get_screen_size=Mock(return_value=(960, 540))), show_progress=False)
        with patch.object(robot, '_first_enter_check'), patch.object(robot, '_run_task') as dispatch:
            robot.work([['tohomepage'], ['schedule'], ['tohomepage'], ['tohomepage', [90, 500], 10]])
        self.assertEqual([call.args for call in dispatch.call_args_list], [('schedule', []), ('tohomepage', [[90, 500], 10])])

    def test_stop_exits_paused_session_and_releases_lock(self):
        root = self.root / 'cache/daily/runs'
        run_id = '00000000-0000-0000-0000-000000000001'
        with RunSession('synthetic', root=root, run_id=run_id) as session:
            with self.assertRaisesRegex(ValueError, '仍在运行'):
                desktop.ensure_idle()
            atomic_json(session.path / 'control.json', dict(id='pause-test', action='pause'))

            def send_stop():
                deadline = time.monotonic() + 3
                while session.state != 'paused' and time.monotonic() < deadline:
                    time.sleep(.01)
                desktop.control(run_id, 'stop')

            worker = threading.Thread(target=send_stop)
            worker.start()
            try:
                session.checkpoint()
                self.fail('停止应退出任务')
            finally:
                worker.join(timeout=4)
        state = json.loads((session.path / 'status.json').read_text(encoding='utf-8'))
        self.assertEqual(state['state'], 'cancelled')
        self.assertEqual(state['errors'], 0)
        desktop.ensure_idle()

    def test_stop_interrupts_cooperative_sleep(self):
        with RunSession('sleep-test', root=self.root / 'cache/daily/runs') as session:
            atomic_json(session.path / 'control.json', dict(id='stop-test', action='stop'))
            started = time.monotonic()
            clock.sleep(20)
            self.fail('停止不应等待完整 sleep')
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(session.state, 'cancelled')

    def test_cancelled_task_report_is_not_left_running(self):
        from pcrscript import Robot
        driver = Mock(get_screen_size=Mock(return_value=(960, 540)))
        with RunSession('cancel-task', root=self.root / 'cache/daily/runs') as session:
            robot = Robot(driver, show_progress=False)
            task = Mock()
            task.return_value.run.side_effect = RunCancelled('synthetic cancel')
            with patch('pcrscript.robot.find_taskclass', return_value=task):
                robot.run_task('synthetic')
        self.assertEqual(robot.task_results[0]['status'], 'cancelled')
        report = json.loads(next(session.path.glob('tasks/*/result.json')).read_text(encoding='utf-8'))
        self.assertEqual(report['status'], 'cancelled')
        self.assertEqual(session.errors, 0)

    def test_control_rejects_stale_heartbeat(self):
        run_id = '00000000-0000-0000-0000-000000000002'
        folder = desktop.run_folder(run_id)
        folder.mkdir(parents=True)
        atomic_json(folder / 'status.json', dict(state='running', heartbeat=time.time()-30))
        with self.assertRaisesRegex(ValueError, '心跳失联'):
            desktop.control(run_id, 'resume')
        self.assertFalse((folder / 'control.json').exists())


if __name__ == '__main__':
    unittest.main()
