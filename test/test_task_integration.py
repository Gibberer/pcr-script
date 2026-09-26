"""Task registry/configuration/dispatch regressions; never operate an emulator."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import Mock, patch

from pcrscript import Robot
from pcrscript.tasks import BaseTask, Caravan, GetGift, CampaignClean, RevivalEventOnce, find_taskclass
from pcrscript.tasks.registry import registered_tasks
from pcrscript.run_session import RunSession
from pcrscript.runtime import run_task_from_config


class TaskIntegrationTests(TestCase):
    def robot(self):
        return Robot(Mock(get_screen_size=Mock(return_value=(960, 540))), show_progress=False)

    def test_shared_imports_and_only_supported_tasks_registered(self):
        from pcrscript.tasks import TeamFormation, TeamFormationEx, Combat, Event, EventNews, TimeLimitTask
        expected = {'adventure_daily','arena','campaign_clean','caravan','dungeon_first_clear','upgrade_all_characters','max_character_bonds','abyss_push',
                    'clear_campaign_first_time','clear_story','common_adventure','free_gacha','get_gift',
                    'get_quest_reward','luna_tower_clean','normal_gacha',
                    'princess_arena','quick_clean','research','revival_event_once','schedule','shop_buy','team_battle','tohomepage'}
        self.assertEqual(set(registered_tasks()), expected)
        for name in expected:
            self.assertTrue(issubclass(find_taskclass(name), BaseTask))
        self.assertIs(find_taskclass('caravan'), Caravan)
        self.assertIs(find_taskclass('get_gift'), GetGift)
        self.assertIs(find_taskclass('campaign_clean'), CampaignClean)
        self.assertIs(find_taskclass('revival_event_once'), RevivalEventOnce)

    def test_daily_and_single_task_use_same_dispatch_and_keep_reports(self):
        robot = self.robot()
        robot._first_enter_check = Mock()
        with patch.object(Caravan, 'run', return_value={'status':'complete','remaining_dice':0}) as run:
            robot.run_task('caravan')
            result = robot.work([['caravan']])
        self.assertEqual(run.call_count, 2)
        self.assertEqual([r['report']['remaining_dice'] for r in result], [0,0])

    def test_config_is_shared_and_does_not_mutate_callers(self):
        robot = self.robot()
        config = {'Caravan':{'timeout':17,'max_rolls':3},'Gift':{'free_slots':650},'Task':{'a':[['get_gift']]}}
        original = copy.deepcopy(config)
        robot.configure(config)
        task = Caravan(robot)
        self.assertEqual(task.limit,3)
        task.options['max_rolls']=9
        self.assertEqual(robot.task_config['Caravan']['max_rolls'],3)
        self.assertEqual(GetGift(robot).target,650)
        self.assertEqual(config,original)
        self.assertNotIn(['caravan'],config['Task']['a'])

    def test_repeated_tasks_have_separate_evidence_and_result(self):
        with TemporaryDirectory() as root, RunSession('offline-tasks', root=root) as session:
            robot=self.robot()
            outputs=[]
            def run(task):
                outputs.append(task.ui.output)
                return {'status':'complete','remaining_dice':0}
            with patch.object(Caravan, 'run', run):
                robot.run_task('caravan')
                robot.run_task('caravan')
            self.assertNotEqual(outputs[0],outputs[1])
            self.assertEqual(outputs[0].parent,session.path/'tasks')
            for output in outputs:
                result=json.loads((output/'result.json').read_text(encoding='utf-8'))
                self.assertEqual(result['report']['remaining_dice'],0)
            self.assertIsNone(robot._task_output)

    def test_failure_is_not_replayed_or_reported_complete(self):
        robot=self.robot()
        with patch.object(Caravan,'run',side_effect=RuntimeError('after spending')) as run:
            with self.assertRaisesRegex(RuntimeError,'after spending'):
                robot.run_task('caravan')
            run.assert_called_once()
        self.assertEqual(robot.task_results[-1]['status'],'error')
        self.assertIsNone(robot._task_output)

    def test_cli_uses_registry_options_and_arguments(self):
        robot=self.robot()
        with patch('pcrscript.runtime.load_config',return_value={'Caravan':{'timeout':12,'max_rolls':4}}), \
             patch('pcrscript.runtime.robot_from_config',return_value=robot) as create, \
             patch.object(robot,'run_task',return_value={'status':'complete'}) as dispatch:
            run_task_from_config('ignored.yml','caravan',option_overrides={'max_rolls':5})
            self.assertEqual(create.call_args.args[0]['Caravan'],{'timeout':12,'max_rolls':5})
            dispatch.assert_called_once_with('caravan')

    def test_revival_preflight_skips_device_when_unavailable(self):
        with patch('pcrscript.runtime.load_config',return_value={}), \
             patch('pcrscript.news.fetch_event_news',return_value=Mock(revival=None)), \
             patch('pcrscript.runtime.robot_from_config') as connect:
            self.assertEqual(run_task_from_config('ignored.yml','revival_event_once')['status'],'unavailable')
            connect.assert_not_called()

    def test_story_substep_is_owned_by_task(self):
        task=CampaignClean(self.robot())
        task.enter=Mock(return_value=True)
        task.missions=Mock()
        with TemporaryDirectory() as root:
            task.ui.output=Path(root)
            self.assertEqual(task.run(only='missions')['status'],'complete')
        task.missions.assert_called_once()


if __name__ == '__main__':
    main()
