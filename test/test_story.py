from unittest import TestCase
from unittest.mock import Mock
from pcrscript.tasks.task_story import ClearStory

class StoryEntryTests(TestCase):
    def test_episode_entry_clicks_tile_below_new_badge_at_device_scale(self):
        for height in (540,1080):
            with self.subTest(height=height):
                task=ClearStory.__new__(ClearStory)
                task.define_height=540
                task.robot=Mock(deviceheight=height)
                task._read_template_pos_list=Mock(return_value=[(504,198*height/540)])
                task.resolve_sub_list()
                task.robot.driver.click.assert_called_once_with(504,233*height/540)
