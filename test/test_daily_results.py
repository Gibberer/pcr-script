"""Daily business summaries and exit codes, using synthetic tasks only."""
import copy
import json
from contextlib import redirect_stdout
from io import StringIO
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import daily_task
from pcrscript import Robot, desktop
from pcrscript.run_session import RunSession
from pcrscript.runtime import run_script, summarize_daily
from pcrscript.tasks import BaseTask, EventNews, FreeGacha


class PartialTask(BaseTask):
    def run(self):
        return dict(status='partial', pending=['合成未完成项'])


class LegacyTask(BaseTask):
    def run(self):
        return None


class ErrorTask(BaseTask):
    def run(self):
        raise RuntimeError('合成结算错误')


class DailyResultTests(TestCase):
    def test_counts_preserve_repeated_tasks_and_unverified_endings(self):
        records = [dict(task='repeat', status='finished'),
                   dict(task='repeat', status='complete'),
                   dict(task='blocked', status='blocked', report=dict(reason='前置条件未知'))]
        report = summarize_daily(records)
        self.assertEqual(report['status'], 'partial')
        self.assertFalse(report['verified'])
        self.assertEqual(report['counts'], dict(finished=1, complete=1, blocked=1))
        self.assertEqual([item['index'] for item in report['tasks']], [1, 2, 3])
        self.assertEqual(report['tasks'][-1]['reasons'], ['前置条件未知'])
        for records, status, verified in (
            ([dict(task='old', status='finished')], 'finished', False),
            ([dict(task='known', status='already_complete')], 'complete', True),
            ([dict(task='preview', status='preview')], 'finished', False),
            ([], 'finished', False),
        ):
            with self.subTest(status=status, records=records):
                actual = summarize_daily(records)
                self.assertEqual((actual['status'], actual['verified']), (status, verified))

    def test_real_daily_dispatch_writes_summary_and_keeps_original_plan(self):
        config = dict(Task={1: [['free_gacha', False], ['partial'], ['legacy'], ['partial']]})
        original = copy.deepcopy(config)
        driver = Mock(get_screen_size=Mock(return_value=(960, 540)))
        classes = dict(partial=PartialTask, legacy=LegacyTask, free_gacha=FreeGacha)
        with TemporaryDirectory() as root, RunSession('synthetic-daily', root=root) as session:
            robot = Robot(driver, show_progress=False)
            robot._first_enter_check = Mock()
            with patch('pcrscript.runtime.Robot', return_value=robot), \
                 patch('pcrscript.runtime.select_driver', return_value=driver), \
                 patch('pcrscript.runtime.fetch_event_news', return_value=EventNews()), \
                 patch('pcrscript.runtime.find_taskclass', side_effect=classes.get), \
                 patch('pcrscript.robot.find_taskclass', side_effect=classes.get):
                report = run_script(config)
            self.assertEqual(report['counts'], dict(partial=2, finished=1))
            self.assertEqual(report['tasks'][0]['reasons'], ['合成未完成项'])
            self.assertEqual(json.loads((session.path/'summary.json').read_text(encoding='utf-8')), report)
            events = [json.loads(line) for line in (session.path/'events.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(sum(event['kind'] == 'daily.result' for event in events), 1)
        self.assertEqual(config, original)

    def test_daily_errors_still_continue_and_remain_in_final_summary(self):
        driver = Mock(get_screen_size=Mock(return_value=(960, 540)))
        classes = dict(error=ErrorTask, legacy=LegacyTask)
        with TemporaryDirectory() as root:
            with self.assertRaises(SystemExit) as exit:
                with RunSession('synthetic-error', root=root) as session:
                    robot = Robot(driver, show_progress=False)
                    robot._first_enter_check = Mock()
                    with patch('pcrscript.runtime.Robot', return_value=robot), \
                         patch('pcrscript.runtime.select_driver', return_value=driver), \
                         patch('pcrscript.runtime.fetch_event_news', return_value=EventNews()), \
                         patch('pcrscript.runtime.find_taskclass', side_effect=classes.get), \
                         patch('pcrscript.robot.find_taskclass', side_effect=classes.get):
                        report = run_script(dict(Task={1: [['error'], ['legacy']]}))
            self.assertEqual(exit.exception.code, 1)
            saved = json.loads((session.path/'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(saved, report)
            self.assertEqual(report['counts'], dict(error=1, finished=1))
            self.assertEqual(report['tasks'][0]['reasons'], ['合成结算错误'])

    def test_daily_cli_business_exit_does_not_create_an_error_incident(self):
        for status in ('partial', 'blocked', 'error'):
            with self.subTest(status=status), TemporaryDirectory() as root:
                sessions = []
                def session(name):
                    value = RunSession(name, root=root)
                    sessions.append(value)
                    return value
                with patch('pcrscript.run_session.RunSession', side_effect=session), \
                     patch.object(daily_task, 'main', return_value=dict(status=status)), \
                     redirect_stdout(StringIO()), self.assertRaises(SystemExit) as exit:
                    daily_task.cli()
                self.assertEqual(exit.exception.code, 2)
                snapshot = json.loads((sessions[0].path/'status.json').read_text(encoding='utf-8'))
                self.assertEqual((snapshot['state'], snapshot['errors']), ('finished', 0))
                self.assertFalse(list(sessions[0].path.glob('incident-*')))

    def test_gui_daily_uses_the_same_business_exit_after_releasing_session(self):
        with TemporaryDirectory() as root:
            sessions = []
            def session(name, **kwargs):
                value = RunSession(name, root=root, **kwargs)
                sessions.append(value)
                return value
            config = dict(Extra=dict(dnpath='C:/synthetic'), Task={1: [['get_gift']]})
            with patch('pcrscript.run_session.RunSession', side_effect=session), \
                 patch.object(desktop, 'read_config', return_value=config), \
                 patch('pcrscript.runtime.open_leidian_emulator', return_value=0), \
                 patch('pcrscript.runtime.run_script', return_value=dict(status='partial')), \
                 redirect_stdout(StringIO()), self.assertRaises(SystemExit) as exit:
                desktop.execute('unused.yml', dict(task='daily'), '00000000-0000-0000-0000-000000000001')
            self.assertEqual(exit.exception.code, 2)
            self.assertEqual(json.loads((sessions[0].path/'status.json').read_text(encoding='utf-8'))['errors'], 0)
            self.assertFalse(list(sessions[0].path.glob('incident-*')))
