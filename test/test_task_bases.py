"""Capability split regressions; no emulator or resource consumption."""
import time
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import Mock, patch

from daily_task import modify_task_list
from pcrscript import Robot
from pcrscript.actions import ClickAction
from pcrscript.tasks import (
    BaseTask, ImageTask, TimeLimitTask, Caravan, GetGift, CampaignClean,
    RevivalEventOnce, DungeonFirstClear, UpgradeAllCharacters, Event, EventNews, FreeGacha, find_taskclass,
)
from pcrscript.tasks.registry import registered_tasks


class ContextTask(BaseTask):
    config_section = 'Example'

    def run(self, *, value: int = 0) -> int:
        return value


class ImageProbe(ImageTask):
    def run(self) -> None:
        pass


class TaskBaseTests(TestCase):
    def robot(self) -> Robot:
        driver = Mock(get_screen_size=Mock(return_value=(1280, 720)))
        return Robot(driver, show_progress=False)

    def test_common_contract_needs_no_recognition_or_progress(self):
        robot = SimpleNamespace(driver=object(), task_config={'Example': {'timeout': 20}})
        task = ContextTask(robot)
        self.assertEqual(task(value=7), 7)
        self.assertEqual(task.task_options(), {'timeout': 20})
        for attr in ('define_width', 'define_height', 'set_progress', 'template_match',
                     'action_squential', 'action_once', 'adapted_region'):
            self.assertFalse(hasattr(task, attr), attr)

    def test_ocr_tasks_do_not_acquire_image_capabilities(self):
        robot = self.robot()
        with patch('pcrscript.tasks.image.ImageTask.__init__', side_effect=AssertionError('image base used')):
            for cls in (Caravan, GetGift, CampaignClean, RevivalEventOnce, DungeonFirstClear, UpgradeAllCharacters):
                task = cls(robot)
                self.assertIsInstance(task, BaseTask)
                self.assertNotIsInstance(task, ImageTask)
                self.assertFalse(hasattr(task, 'action_squential'))
                self.assertFalse(hasattr(task, 'define_width'))

    def test_existing_registered_image_tasks_keep_action_capabilities(self):
        ocr_names = {'caravan', 'get_gift', 'campaign_clean',
                     'clear_campaign_first_time', 'revival_event_once', 'dungeon_first_clear', 'upgrade_all_characters'}
        for name in set(registered_tasks()) - ocr_names:
            self.assertTrue(issubclass(find_taskclass(name), ImageTask), name)

    def test_image_coordinates_binding_and_progress_still_work(self):
        robot = self.robot()
        task = ImageProbe(robot)
        task.define_width, task.define_height = 960, 540
        task.set_progress(total_step='∞', num_step=2, show_progress=False)
        action = ClickAction(pos=(480, 270))
        with patch('pcrscript.robot.time.sleep'):
            task.action_squential(action)
        self.assertIs(action.task, task)
        robot.driver.click.assert_called_once_with(640, 360)
        self.assertEqual(task.num_step, 3)
        self.assertEqual(task.total_step, '∞')
        template = Mock(match=Mock(return_value=(100, 200)))
        self.assertEqual(task.template_match(None, template), (100, 200))
        template.set_define_size.assert_called_once_with(960, 540)

    def test_robot_legacy_actions_bind_image_context(self):
        robot = self.robot()
        action = ClickAction(pos=(robot._dummy_task.define_width // 2,
                                  robot._dummy_task.define_height // 2))
        robot._Robot__action_squential(action, delay=0)
        self.assertIsInstance(action.task, ImageTask)
        robot.driver.click.assert_called_once_with(640, 360)

    def test_time_limit_filter_is_independent_of_recognition(self):
        self.assertTrue(issubclass(FreeGacha, TimeLimitTask))
        self.assertTrue(issubclass(CampaignClean, TimeLimitTask))
        self.assertFalse(issubclass(CampaignClean, ImageTask))
        event = Event(time.time()-60, time.time()+600, 'synthetic')
        task_list = [['free_gacha', False], ['campaign_clean', True, False], ['caravan']]
        modify_task_list(EventNews(freeGacha=event), task_list)
        self.assertEqual(task_list[0], ['free_gacha', False])
        self.assertEqual(FreeGacha(self.robot()).num_step, 1)
        modify_task_list(EventNews(), task_list)
        self.assertEqual(task_list, [['campaign_clean', True, False], ['caravan']])


if __name__ == '__main__':
    main()
