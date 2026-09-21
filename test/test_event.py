"""Offline replay checks. These tests never connect to the emulator."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch, Mock
import json

import cv2 as cv
import numpy as np

from pcrscript.game_ui.screen import EventScreen, TextBox, EventUIError, EventUI
from pcrscript.tasks.event_battle import boss_cleared, boss_mode, quest_stars, EventBattles, EventCombat
from pcrscript.tasks.event_formation import count_stars
from pcrscript.tasks.event_strategy import MemberRequirement, CharacterStatus, readiness, load_parties
from pcrscript.tasks.task_story_event import CampaignClean
from pcrscript.tasks.event_sweep import HardSweep
from pcrscript.driver import DNDriver, ADBDriver
from pcrscript.simulator import DNSimulator
from pcrscript.tasks import CampaignClean, ClearCampaignFirstTime
from pcrscript.game_ui.avatars import AvatarIndex, search_card_rectangles, face_crop
from pcrscript.game_ui.equipment import EquipmentBadges

FIXTURES = Path(__file__).parent / "fixtures/story_event"


def frame(*items):
    return EventScreen(np.zeros((540, 960, 3), np.uint8), [
        TextBox(t, 1, [[x-10, y-8], [x+10, y-8], [x+10, y+8], [x-10, y+8]])
        for t, x, y in items])


def fixture(name, crop=None):
    screen = EventScreen(np.zeros((540, 960, 3), np.uint8),
                        [TextBox(**i) for i in json.loads((FIXTURES/(name+".json")).read_text(encoding="utf-8"))])
    if crop:
        x1, y1, x2, y2 = crop
        screen.image[y1:y2, x1:x2] = cv.imread(str(FIXTURES/(name+"_crop.png")))
    return screen


class ReplayUI:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.clicks = []
    def capture(self):
        return next(self.frames)
    def click(self, item, **kwargs):
        self.clicks.append(item.text if isinstance(item, TextBox) else item)
    def save(self, *args):
        pass
    def number(self, screen, roi):
        return screen.number(roi)
    def wait(self, predicate, *args, **kwargs):
        s = self.capture()
        assert predicate(s)
        return s


class EventRecognitionTests(TestCase):
    def test_entry_diamonds_against_marked_and_cleared_live_crops(self):
        for name in ("stories", "memoirs", "missions"):
            for kind in ("marked", "clear"):
                with self.subTest(entry=name, state=kind):
                    crop = cv.imread(str(FIXTURES/f"{name}_{kind}.png"))
                    h, w = crop.shape[:2]
                    self.assertEqual(EventScreen(crop, []).notification((0, 0, w, h)), kind == "marked")

    def test_rotating_star_frame_never_means_no_equipment(self):
        badges = EquipmentBadges()
        for i in range(5):
            self.assertIsNone(badges.read(cv.imread(str(FIXTURES/f"badge_0_{i}.png")), (0, 0, 100, 100)))

    def test_real_equipment_badges_include_mixed_colour(self):
        badges = EquipmentBadges()
        results = [badges.read(cv.imread(str(FIXTURES/f"badge_4_{i}.png")), (0, 0, 100, 100)) for i in range(5)]
        self.assertEqual(results, [(False, False), (True, False), (True, True), (True, False), (True, False)])
        self.assertEqual(badges.read(cv.imread(str(FIXTURES/"badge_none_nefi.png")), (0, 0, 100, 100)), (False, False))
        self.assertEqual(badges.read(cv.imread(str(FIXTURES/"badge_none_aira.png")), (0, 0, 100, 100)), (False, False))

    def test_actual_home_and_stage_stars(self):
        self.assertTrue(fixture("event_home").event_home)
        s = fixture("event_levels", (490, 160, 580, 465))
        self.assertTrue(s.event_quests)
        rows = s.all(r"活动关卡[HN]-\d+", (580, 150, 850, 450))
        self.assertEqual(len(rows), 4)
        self.assertEqual([quest_stars(s, row) for row in rows], [3]*4)

    def test_actual_boss_clear_marks_are_per_row(self):
        s = fixture("boss_list")
        for label in ("剧本模式", "特别", r"特别战斗\+"):
            row = s.find(label, (740, 200, 930, 400), exact=True)
            self.assertIsNotNone(row)
            self.assertTrue(boss_cleared(s, row))
        # Losing one clear marker must not borrow the neighbouring row's mark.
        s.items = [i for i in s.items if not ("通关" in i.text and 275 < i.center[1] < 300)]
        self.assertFalse(boss_cleared(s, s.find("特别", exact=True)))

    def test_actual_special_plus_mode(self):
        self.assertEqual(boss_mode(fixture("boss_plus")), 1)

    def test_actual_character_stars(self):
        self.assertEqual(count_stars(fixture("own_character", (589, 103, 705, 129)).image), 5)

    def test_disabled_claim_button(self):
        s = frame(("全部收取", 843, 440))
        s.image[414:465, 740:947] = cv.imread(str(FIXTURES/"missions_crop.png"))
        self.assertFalse(s.blue_button(s.items[0]))

    def test_unknown_number_is_not_zero(self):
        self.assertIsNone(frame().number((800, 420, 950, 470)))

    def test_isolated_one_retries_crop_when_full_frame_omits_it(self):
        ui = EventUI.__new__(EventUI)
        ui._ocr = Mock(return_value=SimpleNamespace(txts=["1"], scores=np.array([.99])))
        self.assertEqual(ui.number(frame(), (775, 395, 840, 436)), 1)

    def test_crop_does_not_guess_between_two_numeric_results(self):
        ui = EventUI.__new__(EventUI)
        ui._ocr = Mock(return_value=SimpleNamespace(txts=["1", "2"], scores=np.array([.99, .99])))
        self.assertIsNone(ui.number(frame(), (775, 395, 840, 436)))

    def test_real_ocr_reads_thin_one_and_isolated_zero(self):
        from rapidocr import RapidOCR
        ui = EventUI.__new__(EventUI)
        ui._ocr = RapidOCR(params={"EngineConfig.onnxruntime.intra_op_num_threads": 2,
                                  "EngineConfig.onnxruntime.inter_op_num_threads": 1})
        for filename, expected in (("sweep_count_one.png", 1), ("exchange_zero.png", 0)):
            picture = cv.imread(str(FIXTURES/filename))
            h, w = picture.shape[:2]
            self.assertEqual(ui.number(EventScreen(picture, []), (0, 0, w, h)), expected)


class SweepReplayTests(TestCase):
    def test_normal_settlement_without_stamina_stops_sweeping_without_raising(self):
        r = CampaignClean.__new__(CampaignClean)
        r.report = {"pending": []}
        bulk = frame(("关卡一览", 480, 40), ("活动关卡N-10", 112, 158), ("取消", 582, 480))
        r.ui = ReplayUI([self.confirm("活动关卡N-10", "20"), bulk, frame(("活动关卡·首领", 155, 30))])
        self.assertFalse(r.settle_sweep("活动关卡N-10", 2, 10))
        self.assertTrue(r.report["pending"])
        self.assertEqual(r.ui.clicks, ["挑战", "取消"])

    def run_replay(self, frames, name="活动关卡H-3", count=2, remaining=3):
        r = CampaignClean.__new__(CampaignClean)
        r.ui = ReplayUI(frames)
        with patch("pcrscript.tasks.task_story_event.time.sleep"):
            r.settle_sweep(name, count, 20, remaining, 58)
        return r.ui.clicks

    @staticmethod
    def confirm(name="活动关卡H-3", cost="40"):
        return frame(("一键扫荡确认", 480, 40), (name, 120, 118),
                     (cost, 245, 357), ("挑战", 590, 480))

    def test_return_to_bulk_requires_decreased_remaining(self):
        bulk = frame(("关卡一览", 480, 40), ("活动关卡H-3", 112, 158),
                     ("1/3", 471, 184), ("18", 319, 402), ("取消", 582, 480))
        final = frame(("活动关卡·首领", 155, 30))
        clicks = self.run_replay([self.confirm(), self.confirm(), bulk, final])
        self.assertEqual(clicks, ["挑战", "取消"])

    def test_stale_bulk_never_repeats_spending(self):
        bulk = frame(("关卡一览", 480, 40), ("活动关卡H-3", 112, 158), ("3/3", 471, 184))
        with self.assertRaisesRegex(EventUIError, "变化未能核实"):
            self.run_replay([self.confirm(), bulk])

    def test_missing_leading_one_in_confirmation_title_still_checks_cost(self):
        for cost in ("40", "60"):
            confirm = self.confirm(cost=cost)
            confirm.items[0].text = "键扫荡确认"
            if cost == "60":
                with self.assertRaisesRegex(EventUIError, "计划不一致"):
                    self.run_replay([confirm])
            else:
                bulk = frame(("关卡一览", 480, 40), ("活动关卡H-3", 112, 158),
                             ("1/3", 471, 184), ("取消", 582, 480))
                clicks = self.run_replay([confirm, bulk, frame(("活动关卡·首领", 155, 30))])
                self.assertEqual(clicks, ["挑战", "取消"])

    def test_connecting_overlay_waits_for_server_counter_update(self):
        loading = frame(("关卡一览", 480, 40), ("正在进行数据连接", 830, 35),
                        ("活动关卡H-3", 112, 158), ("3/3", 471, 184))
        settled = frame(("关卡一览", 480, 40), ("活动关卡H-3", 112, 158),
                        ("1/3", 471, 184), ("18", 319, 402), ("取消", 582, 480))
        clicks = self.run_replay([self.confirm(), loading, settled, frame(("活动关卡·首领", 155, 30))])
        self.assertEqual(clicks, ["挑战", "取消"])

    def test_resume_from_result_never_starts_another_sweep(self):
        result = frame(("扫荡结果", 480, 40), ("确认", 480, 480))
        settled = frame(("关卡一览", 480, 40), ("活动关卡H-3", 112, 158),
                        ("1/3", 471, 184), ("18", 319, 402), ("取消", 582, 480))
        clicks = self.run_replay([result, settled, frame(("活动关卡·首领", 155, 30))])
        self.assertEqual(clicks, ["确认", "取消"])

    def test_wrong_stage_or_cost_is_rejected_before_click(self):
        for name, cost in (("活动关卡N-3", "40"), ("活动关卡H-3", "60")):
            with self.subTest(name=name, cost=cost), self.assertRaisesRegex(EventUIError, "计划不一致"):
                self.run_replay([self.confirm(name, cost)])


class HardBulkTests(TestCase):
    @staticmethod
    def bulk(counts=(3, 3, 3), insufficient=False):
        items = [("关卡一览", 480, 40), ("全部勾选", 850, 110),
                 ("3", 808, 416), ("一键扫荡", 810, 480), ("取消", 585, 480)]
        for stage, y, count in zip((3, 2, 1), (158, 222, 286), counts):
            items += [(f"活动关卡H-{stage}", 112, y), (f"{count}/3", 470, y+26)]
        if insufficient:
            items.append(("体力不足", 105, 474))
        s = frame(*items)
        s.blue_button = lambda button: True
        return s

    @staticmethod
    def preview(plan, spend=None):
        items = [("一键扫荡确认", 480, 40), (str(spend if spend is not None else sum(plan.values())*20), 245, 357),
                 ("挑战", 590, 480)]
        for (name, count), y in zip(plan.items(), (118, 184, 250)):
            items += [(name, 120, y), (str(count), 880, y+25)]
        return frame(*items)

    def runner(self, frames):
        ui = ReplayUI(frames)
        ui.expect_click = Mock()
        return SimpleNamespace(ui=ui, quests=Mock(), check_deadline=Mock(), log=Mock(), report={"pending": []})

    def test_three_stages_are_selected_and_consumed_in_one_confirmation(self):
        plan = {f"活动关卡H-{i}": 3 for i in (1, 2, 3)}
        r = self.runner([self.bulk(), self.bulk(), self.preview(plan),
                         frame(("扫荡结果", 480, 40), ("确认", 480, 480)),
                         self.bulk((0, 0, 0)), frame(("活动关卡·首领", 155, 30))])
        HardSweep(r).run()
        self.assertEqual(r.ui.clicks, [(851, 174), (851, 238), (851, 302), "一键扫荡", "挑战", "确认"])
        r.quests.assert_called_once()
        self.assertEqual(r.report["pending"], [])  # No stamina digits in any frame.

    def test_exhausted_day_exits_without_selecting_or_scrolling(self):
        r = self.runner([self.bulk((0, 0, 0)), frame(("活动关卡·首领", 155, 30))])
        self.assertTrue(HardSweep(r).run())
        self.assertEqual(r.ui.clicks, [])

    def test_insufficient_stamina_stops_bulk_without_single_stage_retries(self):
        r = self.runner([self.bulk(), self.bulk(insufficient=True), frame(("活动关卡·首领", 155, 30))])
        self.assertFalse(HardSweep(r).run())
        self.assertEqual(len(r.ui.clicks), 3)
        self.assertTrue(any("体力不足" in text for text in r.report["pending"]))

    def test_normal_stage_wrong_count_or_cost_never_confirms_spending(self):
        plan = {f"活动关卡H-{i}": 3 for i in (1, 2, 3)}
        wrong_stage = {**plan, "活动关卡N-10": 3}
        wrong_count = {**plan, "活动关卡H-2": 2}
        for actual, cost in ((wrong_stage, 240), (wrong_count, 160), (plan, 200)):
            r = self.runner([self.preview(actual, cost)])
            with self.assertRaisesRegex(EventUIError, "未确认消费"):
                HardSweep(r).settle(plan)
            self.assertEqual(r.ui.clicks, [])

    def test_mixed_remaining_attempts_follow_exact_preview_and_settlement(self):
        plan = {"活动关卡H-1": 1, "活动关卡H-2": 2, "活动关卡H-3": 3}
        preview = self.preview(plan)
        r = self.runner([preview, preview, self.bulk((0, 0, 0)), frame(("活动关卡·首领", 155, 30))])
        with patch("pcrscript.tasks.event_sweep.time.sleep"):
            HardSweep(r).settle(plan)
        self.assertEqual(r.ui.clicks, ["挑战"])

    def test_stale_remaining_counts_never_trigger_another_consumption(self):
        plan = {f"活动关卡H-{i}": 3 for i in (1, 2, 3)}
        r = self.runner([self.preview(plan), self.bulk()])
        with self.assertRaisesRegex(EventUIError, "停止重复消费"):
            HardSweep(r).settle(plan)
        self.assertEqual(r.ui.clicks, ["挑战"])


class StrategyTests(TestCase):
    def test_unknown_build_and_missing_unique_are_rejected(self):
        need = MemberRequirement("怜（新年）", 352, 38, 6, unique=True, skill_level=352)
        self.assertGreaterEqual(len(readiness(need, CharacterStatus(need.name))), 5)
        actual = CharacterStatus(need.name, 352, 38, 6, True, False, 352, identity_verified=True)
        self.assertEqual(readiness(need, actual), [])
        actual.unique = False
        self.assertTrue(any("专武1开启状态不符" in reason for reason in readiness(need, actual)))

    def test_six_star_and_both_unique_switches_are_exact_requirements(self):
        need = MemberRequirement("角色", 352, 38, 5)
        actual = CharacterStatus("角色", 352, 38, 5, False, False, 352, identity_verified=True)
        self.assertEqual(readiness(need, actual), [])
        for key, value in (("stars", 6), ("unique", True), ("unique2", True), ("unique2", None)):
            with self.subTest(key=key, value=value):
                changed = CharacterStatus(**{**vars(actual), key: value})
                self.assertTrue(readiness(need, changed))

    def test_variant_is_not_interchangeable(self):
        self.assertTrue(readiness(MemberRequirement("怜（新年）", 1, 1, 1), CharacterStatus("怜", 352, 38, 6)))

    def test_unknown_event_never_reuses_party(self):
        # Synthetic schema fixture, independent of private runtime caches.
        with TemporaryDirectory() as root:
            path = Path(root)/'teams.json'
            self.assertEqual(load_parties(path, '测试活动', 'special_plus', 1), [])
            path.write_text(json.dumps({'events':[{'match':'测试活动','special_plus':[{
                'name':'测试队伍','source':'https://example.invalid/strategy','modes':[1],
                'members':[{'name':f'测试角色{i}','level':1,'rank':1,'stars':1,
                            'unique':False,'unique2':False} for i in range(5)]
            }]}]}),encoding='utf-8')
            self.assertEqual(load_parties(path, '另外一期活动', 'special_plus', 1), [])
            self.assertEqual(load_parties(path, '测试活动', 'special_plus', 2), [])
            parties = load_parties(path, '测试活动', 'special_plus', 1)
            self.assertTrue(parties)
            self.assertTrue(all(len(p.members) == 5 and p.source.startswith('https://') for p in parties))
        self.assertNotIn("unique_level", MemberRequirement.__dataclass_fields__)

    def test_stale_calendar_preserves_daily_and_first_clear_arguments(self):
        for cls in (CampaignClean, ClearCampaignFirstTime):
            self.assertEqual(cls.valid(SimpleNamespace(hatsune=None), [True, False]), (cls, [True, False]))


class AvatarTests(TestCase):
    def test_event_bonus_arrows_do_not_hide_cards(self):
        for number, count in ((0, 1), (2, 6)):
            image = np.zeros((540, 960, 3), np.uint8)
            image[170:285, 40:905] = cv.imread(str(FIXTURES/f"search_{number}_crop.png"))
            self.assertEqual(len(search_card_rectangles(image)), count)

    def test_incremental_identity_and_unknown_rejection(self):
        rng = np.random.default_rng(3)
        pictures = [rng.integers(0, 256, (64, 64, 3), dtype=np.uint8) for _ in range(3)]
        with TemporaryDirectory() as folder:
            index = AvatarIndex(folder)
            index.add("角色A", pictures[0])
            index.add("角色A（新年）", pictures[1])
            self.assertEqual(index.query(pictures), ["角色A", "角色A（新年）", None])
            index.add("新增角色", pictures[2])
            reloaded = AvatarIndex(folder)
            self.assertEqual(reloaded.query(pictures)[2], "新增角色")


class WorkflowTests(TestCase):
    def test_cleared_story_memoir_and_mission_entries_never_open_pages(self):
        r = CampaignClean.__new__(CampaignClean)
        s = fixture("event_home")
        for name, (x1, y1, x2, y2) in (("stories", (692, 355, 738, 402)),
                                      ("memoirs", (78, 253, 120, 301)), ("missions", (787, 3, 832, 45))):
            s.image[y1:y2, x1:x2] = cv.imread(str(FIXTURES/f"{name}_clear.png"))
        r.home = Mock(return_value=s)
        r.log = Mock()
        r.ui = Mock()
        r.stories()
        r.memoirs()
        r.missions()
        r.ui.click.assert_not_called()
        r.ui.wait.assert_not_called()
        r.ui.swipe.assert_not_called()

    def test_zero_tickets_on_home_never_opens_exchange(self):
        r = CampaignClean.__new__(CampaignClean)
        r.home = Mock(return_value=frame(("0", 295, 357)))
        r.ui = Mock()
        r.log = Mock()
        r.exchange()
        r.ui.click.assert_not_called()

    def test_main_quest_map_returns_to_adventure_before_checking_event(self):
        r = CampaignClean.__new__(CampaignClean)
        r.check_deadline = Mock()
        r.log = Mock()
        r.ui = ReplayUI([frame(("主线关卡", 110, 30)),
                         frame(("主线关卡", 700, 240), ("剧情活动", 411, 420)),
                         fixture("event_home")])
        self.assertTrue(r.enter())
        self.assertEqual(r.ui.clicks, [(32, 30), "剧情活动"])

    def test_daily_login_receipt_is_closed_before_enter_or_home(self):
        for method in ("enter", "home"):
            with self.subTest(method=method):
                r = CampaignClean.__new__(CampaignClean)
                r.check_deadline = Mock()
                r.log = Mock()
                receipt = fixture("event_login_reward")
                # OCR may also see labels behind the modal. Its close action
                # must take priority over accepting that background as home.
                receipt.items.extend(fixture("event_home").items)
                r.ui = ReplayUI([receipt, fixture("event_home"), fixture("event_home")])
                self.assertTrue(getattr(r, method)())
                self.assertEqual(r.ui.clicks, ["关闭"])

    def test_login_handler_does_not_accept_unrelated_dialogs(self):
        r = CampaignClean.__new__(CampaignClean)
        r.ui = ReplayUI([])
        self.assertFalse(r.entry_dialog(frame(("购买体力", 480, 148), ("关闭", 480, 372))))
        self.assertEqual(r.ui.clicks, [])

    def test_login_receipt_missing_close_stops_without_blind_clicks(self):
        r = CampaignClean.__new__(CampaignClean)
        r.ui = ReplayUI([])
        with self.assertRaisesRegex(EventUIError, "关闭按钮"):
            r.entry_dialog(frame(("获得活动登录奖励", 480, 148)))
        self.assertEqual(r.ui.clicks, [])

    def test_retreat_uses_battle_menu_and_stops_at_boss_details(self):
        ui = ReplayUI([frame(("btn_menu_text", 900, 25)), frame(("btn_giveup", 480, 300)),
                       frame(("btn_giveup_blue", 590, 390)), fixture("boss_plus")])
        combat = EventCombat.__new__(EventCombat)
        combat.ui = ui
        combat.r = SimpleNamespace(log=Mock())
        combat.match = lambda key, screen: key if screen.find(key) else None
        result = combat.retreat("测试减员")
        self.assertEqual(result.outcome, "retreated")
        self.assertEqual(ui.clicks, ["btn_menu_text", "btn_giveup", "btn_giveup_blue"])

    def test_disabled_battle_start_is_not_clicked(self):
        combat = EventCombat.__new__(EventCombat)
        combat.ui = ReplayUI([frame(("战斗开始", 847, 452))])
        self.assertEqual(combat.run().outcome, "blocked")
        self.assertEqual(combat.ui.clicks, [])

    def test_boss_detail_cancel_uses_the_left_aligned_title(self):
        r = CampaignClean.__new__(CampaignClean)
        r.ui = ReplayUI([fixture("boss_plus"), fixture("event_home")])
        r.ui.expect_click = Mock()
        self.assertTrue(r.home().event_home)
        r.ui.expect_click.assert_called_once_with("取消", (550, 420, 950, 520), exact=True)

    def test_old_event_layout_is_skipped_without_new_layout_clicks(self):
        r = CampaignClean.__new__(CampaignClean)
        r.check_deadline = Mock()
        r.log = Mock()
        r.ui = ReplayUI([frame(("活动剧情", 810, 430), ("报酬交换", 270, 415))])
        self.assertFalse(r.enter())
        self.assertEqual(r.ui.clicks, [])

    def test_absent_event_entry_is_checked_on_three_frames(self):
        r = CampaignClean.__new__(CampaignClean)
        r.check_deadline = Mock()
        r.log = Mock()
        r.ui = ReplayUI([frame(("主线关卡", 700, 240)) for _ in range(3)])
        with patch("pcrscript.tasks.task_story_event.time.sleep"):
            self.assertFalse(r.enter())
        self.assertEqual(r.ui.clicks, [])

    def test_daily_missions_precede_exchange_and_follow_sweep(self):
        r = CampaignClean.__new__(CampaignClean)
        r.options = {}
        r.report = {"pending": [], "steps": [], "battles": []}
        r.enter = Mock(return_value=True)
        r.home = Mock()
        sequence = []
        for name in ("sweep", "stories", "memoirs", "missions", "exchange"):
            setattr(r, name, Mock(side_effect=lambda name=name: sequence.append(name)))
        with TemporaryDirectory() as folder, patch("pcrscript.tasks.event_battle.EventBattles") as battles:
            battles.return_value.first_clear.side_effect = lambda: sequence.append("first_clear")
            battles.return_value.bosses.side_effect = lambda: sequence.append("bosses")
            r.ui = SimpleNamespace(output=Path(folder), save=Mock())
            self.assertEqual(r.run()["status"], "complete")
            battles.assert_not_called()
        self.assertEqual(sequence, ["sweep", "stories", "memoirs", "missions", "exchange"])

    def test_cleared_bosses_never_start_a_replay(self):
        battles = EventBattles.__new__(EventBattles)
        battles.ui = Mock()
        battles.r = SimpleNamespace(home=Mock(return_value=fixture("event_home")),
                                    quests=Mock(return_value=fixture("boss_list")),
                                    report={}, options={}, log=Mock())
        battles.bosses()
        battles.ui.click.assert_not_called()
        battles.ui.expect_click.assert_not_called()



class DriverTests(TestCase):
    def test_no_adb_fallback_for_both_screenshot_formats(self):
        d = DNDriver.__new__(DNDriver)
        d.click_by_mouse = True
        with patch("pcrscript.driver.subprocess.Popen") as popen:
            for png in (True, False):
                with patch.object(ADBDriver, "png", png), self.assertRaises(RuntimeError):
                    ADBDriver.screenshot(d)
            popen.assert_not_called()

    def test_no_adb_fallback_when_ldconsole_fails(self):
        with patch("pcrscript.simulator.subprocess.check_output", side_effect=OSError("missing")), \
                patch("pcrscript.simulator.GeneralSimulator.get_devices") as adb:
            self.assertIsNone(DNSimulator("missing", useADB=False).get_devices())
            adb.assert_not_called()


if __name__ == "__main__":
    main()
