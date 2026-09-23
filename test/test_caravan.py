"""Caravan consumption boundaries; no emulator operations."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import Mock, patch
import cv2 as cv
import numpy as np
from pcrscript.game_ui.screen import EventScreen, TextBox, EventUIError
from pcrscript.game_ui.caravan import board, triple_mode, disabled_roll, progress, fastest_turn, helpful_food, surplus_food
from pcrscript.tasks.task_caravan import Caravan


def screen(*items):
    return EventScreen(np.zeros((540, 960, 3), np.uint8), [
        TextBox(t, 1, [[x-10,y-5],[x+10,y-5],[x+10,y+5],[x-10,y+5]])
        for t,x,y in items])


def board_screen(count=10, mode='off'):
    s = screen(('驾车游',110,30),('经过回合',90,200),('4回合',205,225),
               ('还剩54格',190,275),('投骰子',875,412),(str(count),914,317))
    s.image[429:455,818:903] = cv.imread(str(Path(__file__).parent / f'fixtures/caravan/triple_{mode}.png'))
    return s


class CaravanTests(TestCase):
    def runner(self, folder):
        r = Caravan(SimpleNamespace(driver=Mock(get_screen_size=Mock(return_value=(960,540)))),
                          dict(output=folder))
        r.ui.capture = Mock()
        r.ui.click = Mock()
        r.ui.save = Mock()
        r.ui.number = lambda s, roi: s.number(roi)
        return r

    def test_real_toggle_fixtures(self):
        self.assertIs(triple_mode(board_screen(mode='on')), True)
        self.assertIs(triple_mode(board_screen()), False)
        self.assertIsNone(triple_mode(screen()))

    def test_hidden_zero_badge_requires_explicit_tooltip(self):
        with TemporaryDirectory() as folder, patch('pcrscript.tasks.task_caravan.time.sleep'):
            r=self.runner(folder)
            s=board_screen(); s.items.pop()
            fixtures=Path(__file__).parent/'fixtures/caravan'
            s.image[402:422,711:780]=cv.imread(str(fixtures/'food_label.png'))
            s.image[334:382,890:925]=cv.imread(str(fixtures/'die_enabled.png'))
            self.assertFalse(disabled_roll(s))
            s.image[334:382,890:925]=cv.imread(str(fixtures/'die_disabled.png'))
            self.assertTrue(disabled_roll(s))
            tooltip=EventScreen(s.image,s.items+screen(('未持有骰子。',480,235)).items)
            r.ui.capture.side_effect=[s,tooltip,s]
            result=r.run()
            self.assertEqual((result['remaining_dice'],result['spent']),(0,0))
            r.ui.click.assert_called_once_with((874,372))
            # A dim overlay cannot authorize a query of the roll button.
            s.image[402:422,711:780]//=2
            self.assertFalse(disabled_roll(s))

    def test_board_recovers_missing_roll_label(self):
        s=screen(('驾车游',110,30),('经过回合',90,200),
                 ('同时掷3个',850,440),('食用料理',750,413))
        self.assertTrue(board(s))
        self.assertFalse(board(screen(('驾车游',110,30),('经过回合',90,200))))

    def test_zero_requires_two_observations_and_no_clicks(self):
        with TemporaryDirectory() as folder, patch('pcrscript.tasks.task_caravan.time.sleep'):
            r = self.runner(folder)
            r.ui.capture.side_effect = [board_screen(0),board_screen(0)]
            self.assertEqual(r.run()['status'], 'complete')
            r.ui.click.assert_not_called()

    def test_skip_preview_and_balance_are_both_verified(self):
        with TemporaryDirectory() as folder, patch('pcrscript.tasks.task_caravan.time.sleep'):
            r=self.runner(folder)
            preview=screen(('跳过确认',480,42),('15',654,342),('0',700,342),('跳过',590,480))
            r.ui.capture.side_effect=[board_screen(15),preview,preview,board_screen(0),board_screen(0)]
            result=r.run()
            self.assertEqual((result['spent'],result['skips']),(15,1))
            self.assertEqual(r.ui.click.call_count,2)

    def test_stale_skip_cancelled_and_wrong_cost_rejected(self):
        with TemporaryDirectory() as folder:
            r=self.runner(folder)
            preview=screen(('跳过确认',480,42),('29',654,342),('13',700,342),('返回',370,480),('跳过',590,480))
            self.assertTrue(r.modal(preview))
            self.assertEqual(r.ui.click.call_args.args[0].text,'返回')
            r.probe=True; r.report['remaining_dice']=29
            with self.assertRaisesRegex(EventUIError,'消费预览'):
                r.modal(preview)
            self.assertIsNone(r.pending)

    def test_pursuing_ship_expands_status_panel(self):
        s=screen(('驾车游',110,30),('经过回合',90,160),('6回合',205,182),
                 ('班迪鲨号',90,208),('2格子前',200,232),('还剩18格',190,280),('投骰子',875,412))
        self.assertTrue(board(s))
        self.assertEqual(progress(s),(6,18))

    def test_enabled_triple_is_disabled_before_roll(self):
        with TemporaryDirectory() as folder, patch('pcrscript.tasks.task_caravan.time.sleep'):
            r = self.runner(folder)
            r.ui.capture.side_effect = [board_screen(1,'on'),board_screen(1),board_screen(0),board_screen(0)]
            result=r.run()
            self.assertEqual(result['spent'],1)
            self.assertEqual([c.args[0] for c in r.ui.click.call_args_list],[(821,443),(874,372)])

    def test_three_dice_drop_is_error_not_success(self):
        with TemporaryDirectory() as folder, patch('pcrscript.tasks.task_caravan.time.sleep'):
            r = self.runner(folder)
            r.ui.capture.side_effect = [board_screen(4),board_screen(1)]
            with self.assertRaisesRegex(EventUIError,'消费不符'):
                r.run()
            self.assertEqual(r.ui.click.call_count,1)

    def test_missing_number_never_means_zero(self):
        with TemporaryDirectory() as folder:
            r = self.runner(folder)
            s=board_screen(); s.items.pop()
            r.ui.capture.return_value=s
            with self.assertRaisesRegex(EventUIError,'无法确认'):
                r.run()
            r.ui.click.assert_not_called()

    def test_minigame_result_small_modal(self):
        with TemporaryDirectory() as folder:
            r = self.runner(folder)
            s=screen(('跳过报酬',480,147),('跳过小游戏，',480,183),('关闭',480,373))
            self.assertTrue(r.modal(s))
            self.assertEqual(tuple(r.ui.click.call_args.args[0].center),(480,373))

    def test_minigame_with_practice_button_skip_moves_up(self):
        with TemporaryDirectory() as folder:
            r=self.runner(folder)
            s=screen(('有扰乱道具！？挑战接水果游戏！',400,50),('跳过',880,250),('练习',880,355),('开始',855,490))
            self.assertTrue(r.modal(s))
            self.assertEqual(r.ui.click.call_args.args[0].text,'跳过')

    def test_checkpoint_pursuit_result(self):
        with TemporaryDirectory() as folder:
            r=self.runner(folder)
            self.assertTrue(r.modal(screen(('奖励一览',480,42),('到达所花费的回合数',200,315),('确认',480,480))))
            self.assertEqual(r.ui.click.call_args.args[0].text,'确认')

    def test_skip_rewards_and_fastest_record(self):
        with TemporaryDirectory() as folder:
            r=self.runner(folder)
            self.assertTrue(r.modal(screen(('跳过奖励',480,42),('赛季最快到达回合数',200,315),('确认',480,480))))
            self.assertEqual(r.ui.click.call_args.args[0].text,'确认')
        self.assertEqual(fastest_turn(screen(('赛季最快到达纪录',120,352),('9回合',205,378))),9)
        self.assertIsNone(fastest_turn(screen()))

    def test_unknown_food_not_confirmed(self):
        with TemporaryDirectory() as folder:
            r=self.runner(folder)
            s=screen(('食用确认',480,42),('未知效果',480,300),('确认',585,480))
            with self.assertRaises(EventUIError): r.modal(s)
            r.ui.click.assert_not_called()

    def test_food_effects(self):
        self.assertTrue(helpful_food('本回合掷出的骰子点数必定为“2”。并且，跳过下个回合的计数。'))
        self.assertFalse(helpful_food('点数必定为“2”。'))

    def test_shop_returns_without_buying(self):
        with TemporaryDirectory() as folder:
            r=self.runner(folder)
            s=screen(('里程商店',480,42),('购买',400,360),('返回地图',400,480))
            self.assertTrue(r.modal(s))
            self.assertEqual(r.ui.click.call_args.args[0].text,'返回地图')

    def test_shorter_fork_selected(self):
        with TemporaryDirectory() as folder:
            r=self.runner(folder)
            s=screen(('距离检查点',330,134),('50',330,156),
                     ('距离检查点',625,274),('40',625,296))
            self.assertTrue(r.modal(s))
            r.ui.click.assert_called_once_with((625,344))

    def test_companion_extra_roll_not_triple_toggle(self):
        with TemporaryDirectory() as folder:
            r=self.runner(folder)
            s=screen(('同伴效果发生！',220,30),('增加投掷次数',620,378))
            self.assertTrue(r.modal(s))
            self.assertEqual(r.ui.click.call_args.args[0].text,'增加投掷次数')

    def test_reroll_keeps_good_or_sufficient_result(self):
        with TemporaryDirectory() as folder:
            r=self.runner(folder)
            for distance,value,expected in [(6,4,(339,388)),(2,2,(339,388)),(6,2,'重新投掷')]:
                r.last_distance=distance
                s=screen(('同伴效果发生！',220,30),('可重掷1次骰子',210,70),
                         (str(value),340,388),('重新投掷',620,450))
                self.assertTrue(r.modal(s))
                clicked=r.ui.click.call_args.args[0]
                self.assertEqual(getattr(clicked,'text',clicked),expected)

    def test_companion_faces_chooses_larger_verified_value(self):
        with TemporaryDirectory() as folder:
            r=self.runner(folder)
            s=screen(('同伴效果发生！',220,30),('应用骰子的正面或反面',220,85),('4',340,388),('or',480,388),('3',620,388))
            self.assertTrue(r.modal(s))
            r.ui.click.assert_called_once_with((339,388))
            s.items[-1]=screen(('2',620,388)).items[0]
            with self.assertRaisesRegex(EventUIError,'正反面'):
                r.modal(s)
            s.items.pop(2)
            self.assertTrue(r.modal(s))
            r.ui.click.assert_called_with((620,388))
            self.assertFalse(r.modal(screen(('同伴效果发生！',220,30),('应用骰子的正面或反面',220,85))))

    def test_reward_dice_counted_once_even_on_repeated_frame(self):
        with TemporaryDirectory() as folder, patch('pcrscript.tasks.task_caravan.time.sleep'):
            r=self.runner(folder)
            reward=screen(('活动加成！',480,168),('获得1个骰子。',460,270))
            r.ui.capture.side_effect=[board_screen(1),reward,reward,board_screen(1),board_screen(0),board_screen(0)]
            result=r.run()
            self.assertEqual((result['spent'],result['gained'],result['remaining_dice']),(2,1,0))

    def test_paid_shortcut_declined_then_confirmed(self):
        with TemporaryDirectory() as folder:
            r=self.runner(folder)
            self.assertTrue(r.modal(screen(('是否支付里程通过“近道”？',480,147),('不通过',337,335),('通过',620,335))))
            self.assertEqual(r.ui.click.call_args.args[0].text,'不通过')
            self.assertTrue(r.modal(screen(('将不开启“近道”直接离开。',480,248),('离开',590,372))))
            self.assertEqual(r.ui.click.call_args.args[0].text,'离开')

    def test_old_gacha_confirmation_cancelled_before_spending(self):
        with TemporaryDirectory() as folder:
            r=self.runner(folder)
            s=screen(('里程扭蛋目前正在开放。',480,200),('取消',370,480),('投骰子',590,480))
            self.assertTrue(r.modal(s))
            self.assertEqual(r.ui.click.call_args.args[0].text,'取消')

    def test_food_list_scrolls_to_offscreen_use_button(self):
        with TemporaryDirectory() as folder:
            r=self.runner(folder)
            r.ui.swipe=Mock()
            first=screen(('持有的料理',480,42),('跳过下个回合的计数。',270,399),('关闭',480,480))
            self.assertTrue(r.modal(first))
            r.ui.swipe.assert_called_once()
            second=screen(('持有的料理',480,42),('跳过下个回合的计数。',270,210),('食用',395,285))
            self.assertTrue(r.modal(second))
            self.assertEqual(r.ui.click.call_args.args[0].text,'食用')

    def test_surplus_policy_preserves_travel_food(self):
        self.assertTrue(surplus_food('开启品级3的里程商店。'))
        self.assertFalse(surplus_food('可跳过料理格子移动。效果持续2回合。'))
        self.assertFalse(surplus_food('未知料理'))

    def test_sale_result_precedes_background_inventory(self):
        with TemporaryDirectory() as folder:
            r=self.runner(folder)
            r.sale_before=12; r.sale_confirmed=True
            s=screen(('出售完毕',480,148),('获得了500里程。',480,270),('确认',480,435),
                     ('持有数已满。请选择要出售的料理。',480,85),('料理持有数11/10',480,110),('出售',395,285))
            self.assertTrue(r.modal(s))
            self.assertEqual(r.ui.click.call_args.args[0].text,'确认')
            self.assertEqual(r.sale_before,12)

    def test_old_sale_confirmation_cancelled(self):
        with TemporaryDirectory() as folder:
            r=self.runner(folder)
            self.assertTrue(r.modal(screen(('出售确认',480,148),('取消',370,435),('确认',590,435))))
            self.assertEqual(r.ui.click.call_args.args[0].text,'取消')

    def test_food_override_cancelled_and_list_closed(self):
        with TemporaryDirectory() as folder:
            r=self.runner(folder)
            self.assertTrue(r.modal(screen(('确认食用',480,148),('生效中的效果将被覆盖。',480,270),('取消',370,435),('确认',590,435))))
            self.assertEqual(r.ui.click.call_args.args[0].text,'取消')
            self.assertTrue(r.modal(screen(('持有的料理',480,42),('关闭',480,480))))
            self.assertEqual(r.ui.click.call_args.args[0].text,'关闭')
            self.assertEqual(r.report['foods'],0)


if __name__ == '__main__':
    main()
