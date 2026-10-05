"""Synthetic daily login board navigation; no device input."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import cv2 as cv
import numpy as np

from pcrscript.actions import ClickAction, MatchAction
from pcrscript.tasks.task_home import SkipLoginStamp, TaskPageNavigation
from pcrscript.game_ui.screen import EventScreen, EventUIError
from ui_fixtures import screen
from pcrscript.templates import BooleanTemplate
from pcrscript.runtime import run_script
from pcrscript.tasks import EventNews, NormalGacha


class LoginStampTests(TestCase):
    def test_stamp_board_skips_and_does_not_click_behind_overlay(self):
        icon = cv.imread('images/btn_skip.png')
        image = np.zeros((540, 960, 3), np.uint8)
        image[15:15+icon.shape[0], 880:880+icon.shape[1]] = icon
        driver = Mock()
        robot = SimpleNamespace(driver=driver, devicewidth=960, deviceheight=540)
        skip = SkipLoginStamp()
        skip._ocr = Mock(return_value=SimpleNamespace(txts=['应援', '印', '章']))
        action = MatchAction(BooleanTemplate(False),
                             unmatch_actions=(skip, ClickAction(pos=(90, 500))))
        action.bindTask(SimpleNamespace(define_width=960, define_height=540))
        action.do(image, robot)
        driver.click.assert_called_once_with(913.5, 38.0)

    def test_skip_icon_without_login_board_text_is_ignored(self):
        icon = cv.imread('images/btn_skip.png')
        image = np.zeros((540, 960, 3), np.uint8)
        image[15:15+icon.shape[0], 880:880+icon.shape[1]] = icon
        driver = Mock()
        robot = SimpleNamespace(driver=driver)
        skip = SkipLoginStamp()
        skip._ocr = Mock(return_value=SimpleNamespace(txts=['剧情画面']))
        skip.do(image, robot)
        self.assertFalse(skip.skip)
        driver.click.assert_not_called()

    def _run_daily(self, start):
        # Keep the real daily/login/actions/template flow; replace external
        # boundaries and stop at the first consuming task.
        blank = np.zeros((540, 960, 3), np.uint8)
        home = blank.copy()
        icon = cv.imread('images/shop.png')
        home[360:360+icon.shape[0], 680:680+icon.shape[1]] = icon
        modal = blank.copy()
        modal_icon = None
        if start in ('btn_close', 'btn_close_2', 'btn_cancel'):
            modal_icon = cv.imread(f'images/{start}.png')
            modal[240:240+modal_icon.shape[0], 450:450+modal_icon.shape[1]] = modal_icon
        state = {'page': start, 'seen': [], 'elapsed': 0}
        from dawn_labyrinth_fixtures import catalogue, guild, home as maze_home
        recognized = {'maze_catalogue': catalogue(), 'maze_guild': guild(), 'maze_home': maze_home()}
        def monotonic():
            state['elapsed'] += 10 if start in ('loading', 'unknown') else 1
            return state['elapsed']
        driver = Mock(get_screen_size=Mock(return_value=(960, 540)))
        def capture():
            # A cold launch stays on the loading screen for seven minutes.
            if state['page'] == 'loading' and state['elapsed'] >= 420:
                state['page'] = 'title'
            page = state['page']
            state['seen'].append(page)
            return (recognized[page].image if page in recognized else
                    home if page == 'home' else modal if page == start else blank)
        def observe(ui, image, **kwargs):
            ui.height, ui.width = image.shape[:2]
            ui.last = recognized.get(state['page'], EventScreen(image, []))
            return ui.last
        def click(x, y):
            # Loading ignores input; the title's bottom-left menu cannot enter.
            if state['page'] == 'maze_catalogue' and (x,y) == (584,477):
                state['page'] = 'maze_guild'
            elif state['page'] == 'maze_guild' and (x,y) == (30,30):
                state['page'] = 'maze_home'
            elif state['page'] == 'maze_home' and (x,y) == (90,500):
                state['page'] = 'home'
            elif state['page'] == 'title' and not (x < 200 and y > 460):
                state['page'] = 'home'
            elif state['page'] == start and modal_icon is not None:
                if 450 <= x < 450+modal_icon.shape[1] and 240 <= y < 240+modal_icon.shape[0]:
                    state['page'] = 'home'
        driver.screenshot.side_effect = capture
        driver.click.side_effect = click
        def task():
            self.assertEqual(state['page'], 'home')
            self.assertGreaterEqual(state['seen'].count('home'), 3)
        with patch('pcrscript.runtime.select_driver', return_value=driver), \
                patch('pcrscript.game_ui.screen.EventUI.observe', observe), \
                patch('pcrscript.runtime.fetch_event_news', return_value=EventNews()), \
                patch('pcrscript.run_session.clock.sleep'), \
                patch('pcrscript.run_session.clock.monotonic', side_effect=monotonic), \
                patch.object(NormalGacha, 'run', side_effect=task) as consume:
            if start == 'unknown':
                with self.assertRaisesRegex(RuntimeError, '未能在时限内进入游戏首页'):
                    run_script({'Task': {1: [['normal_gacha']]}})
                consume.assert_not_called()
            else:
                run_script({'Task': {1: [['normal_gacha']]}})
                consume.assert_called_once_with()
        return state['seen']

    def test_daily_leaves_maze_selectors_before_confirming_home(self):
        for start in ('maze_catalogue', 'maze_guild'):
            with self.subTest(start=start):
                seen = self._run_daily(start)
                self.assertIn('maze_home', seen)
                self.assertIn('home', seen)

    def test_known_selector_uses_only_its_exit_and_battle_preserves_the_screen(self):
        from dawn_labyrinth_fixtures import guild
        fallback = Mock()
        action = TaskPageNavigation(fallback)
        action.ui = Mock(observe=Mock(return_value=guild()))
        action.do(guild().image, Mock())
        action.ui.click.assert_called_once_with((30,30))
        fallback.bindTask.assert_not_called()
        action.ui.observe.return_value = screen(('菜单',900,30),('1:20',800,25))
        action.ui.click.reset_mock()
        with self.assertRaisesRegex(EventUIError, '未结算战斗'):
            action.do(guild().image, Mock())
        action.ui.click.assert_not_called()
        fallback.bindTask.assert_not_called()

    def test_daily_enters_from_loading_title_and_home_before_running_task(self):
        for start in ('loading', 'title', 'home'):
            with self.subTest(start=start):
                seen = self._run_daily(start)
                self.assertEqual(seen[0], start)
                self.assertIn('home', seen)
                if start == 'loading':
                    self.assertIn('title', seen)

    def test_unknown_entry_times_out_without_running_task(self):
        self._run_daily('unknown')

    def test_daily_closes_existing_modal_before_running_task(self):
        for button in ('btn_close', 'btn_close_2', 'btn_cancel'):
            with self.subTest(button=button):
                seen = self._run_daily(button)
                self.assertEqual(seen[0], button)
                self.assertIn('home', seen)
