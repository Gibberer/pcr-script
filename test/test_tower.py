"""Bounded tower entry checks through the production daily dispatcher."""
from unittest import TestCase
from unittest.mock import Mock, patch

import cv2 as cv
import numpy as np

from pcrscript import Robot
from pcrscript.runtime import summarize_daily
from pcrscript.tasks import BaseTask


class NextTask(BaseTask):
    def run(self):
        return dict(status='complete')


class TowerEntranceTests(TestCase):
    def replay(self, entrance_after=None, locked=False, adventure=True):
        now = [100.0]
        page = ['home']
        seen = []
        background = np.random.default_rng(41).integers(0, 80, (540, 960, 3), dtype=np.uint8)
        centers = {}

        def frame(*names):
            image = background.copy()
            for index, name in enumerate(names):
                icon = cv.imread(f'images/{name}.png')
                x, y = 80 + index * 270, 100
                h, w = icon.shape[:2]
                image[y:y+h, x:x+w] = icon
                centers[name] = (int(x + w/2), int(y + h/2))
            return image

        home = frame('tab_adventure') if adventure else background
        entrance = frame('btn_luna_tower_entrance')
        tower = frame('symbol_luna_tower', 'symbol_luna_tower_lock')

        def capture():
            seen.append(page[0])
            if len(seen) > 150:
                self.fail('tower entry did not stop within its bound')
            if page[0] == 'home':
                return home
            if page[0] == 'tower':
                return tower
            if entrance_after is not None and now[0] >= entrance_after:
                return entrance
            return background

        def click(x, y):
            if (x, y) == centers.get('tab_adventure') and page[0] == 'home':
                page[0] = 'adventure'
            elif (x, y) == centers.get('btn_luna_tower_entrance') and page[0] == 'adventure':
                page[0] = 'tower' if locked else 'loading'

        driver = Mock(get_screen_size=Mock(return_value=(960, 540)))
        driver.screenshot.side_effect = capture
        driver.click.side_effect = click
        robot = Robot(driver, show_progress=False)
        robot._first_enter_check = Mock()
        from pcrscript.tasks import LunaTowerClean
        classes = dict(luna_tower_clean=LunaTowerClean, next=NextTask)
        with patch('pcrscript.robot.ToHomePage.run'), \
                patch('pcrscript.robot.find_taskclass', side_effect=classes.get), \
                patch('pcrscript.run_session.clock.monotonic', side_effect=lambda: now[0]), \
                patch('pcrscript.run_session.clock.sleep', side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds)):
            records = robot.work([['luna_tower_clean'], ['next']])
        return records, driver, centers, now[0]

    def test_absent_entrance_is_unavailable_and_daily_continues_without_sweep(self):
        records, driver, centers, elapsed = self.replay()
        self.assertEqual([row['status'] for row in records], ['unavailable', 'complete'])
        self.assertIn('未识别到露娜塔入口', records[0]['report']['reason'])
        self.assertEqual(summarize_daily(records)['status'], 'complete')
        self.assertLess(elapsed, 120)
        driver.click.assert_called_once_with(*centers['tab_adventure'])

    def test_delayed_entrance_is_clicked_but_unconfirmed_page_never_sweeps(self):
        records, driver, centers, elapsed = self.replay(entrance_after=106)
        self.assertEqual([row['status'] for row in records], ['blocked', 'complete'])
        self.assertIn('未能确认露娜塔页面', records[0]['report']['reason'])
        self.assertEqual(driver.click.call_count, 2)
        driver.click.assert_any_call(*centers['btn_luna_tower_entrance'])
        self.assertLess(elapsed, 130)

    def test_present_entrance_keeps_existing_corridor_lock_guard(self):
        records, driver, _, _ = self.replay(entrance_after=100, locked=True)
        self.assertEqual([row['status'] for row in records], ['error', 'complete'])
        self.assertIn('回廊未解锁', records[0]['error'])
        self.assertEqual(driver.click.call_count, 2)

    def test_unconfirmed_adventure_is_blocked_instead_of_claiming_missing_tower(self):
        records, _, _, elapsed = self.replay(adventure=False)
        self.assertEqual([row['status'] for row in records], ['blocked', 'complete'])
        self.assertIn('未能确认冒险入口', records[0]['report']['reason'])
        self.assertLess(elapsed, 125)
