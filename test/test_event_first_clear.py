"""Synthetic first-entry and first-clear safety checks; no account data."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from test_event import frame, fixture, ReplayUI
from pcrscript.tasks.task_story_event import CampaignClean
from pcrscript.tasks.event_first_clear import EventFirstClear
from pcrscript.tasks.event_battle import EventBattles, boss_locked
from pcrscript.game_ui.screen import EventUIError


class FirstEntryTests(TestCase):
    def test_disabled_boss_story_skip_advances_visible_dialogue(self):
        r = CampaignClean.__new__(CampaignClean)
        r.ui = ReplayUI([])
        s = frame(('菜单', 918, 45), ('记录', 775, 140), ('跳过', 885, 140),
                  ('合成角色', 280, 403))
        s.image[110:155, 845:925] = (145, 140, 130)
        self.assertTrue(r.story_dialog(s))
        self.assertEqual(r.ui.clicks, ['菜单', (780, 488)])

    def test_loading_home_badges_are_not_movie_captions(self):
        r = CampaignClean.__new__(CampaignClean)
        r.ui = ReplayUI([])
        self.assertFalse(r.story_dialog(frame(('新内容', 400, 490))))
        self.assertEqual(r.ui.clicks, [])

    def test_interrupted_native_settlement_returns_to_list_without_replaying_battle(self):
        class SettlementUI(ReplayUI):
            def expect_click(self, pattern, roi, exact=False):
                s = self.capture()
                item = s.find(pattern, roi, exact=exact)
                assert item is not None
                self.click(item)
        r = CampaignClean.__new__(CampaignClean)
        r.report = {}
        r.check_deadline = Mock()
        r.log = Mock()
        end = frame(('自动推进结束', 480, 148), ('由于是最终关卡，自动推进停止。', 480, 238),
                    ('13', 555, 200), ('160', 677, 311), ('确认', 480, 370))
        loot = frame(('获得道具', 480, 150), ('初次通关', 120, 235), ('下一步', 840, 480))
        summary = frame(('自动推进报酬一览', 480, 40), ('关闭', 480, 480))
        unlock = frame(('自动推进解锁内容一览', 480, 148), ('关闭', 480, 370))
        quests = frame(('活动关卡·首领', 150, 30))
        summary.items.extend(quests.items)
        unlock.items.extend(quests.items)
        r.ui = SettlementUI([end, end, loot, summary, summary, unlock, unlock, quests])
        self.assertTrue(r.enter())
        self.assertEqual(r.ui.clicks, ['确认', '下一步', '关闭', '关闭'])
        self.assertEqual(r.report['recovered_first_clear']['spent'], 160)
        self.assertEqual(r.report['recovered_first_clear']['cleared'], 13)

    def test_live_event_identity_requires_consistent_title_and_dates(self):
        r = CampaignClean.__new__(CampaignClean)
        r.report = {}
        r.ui = Mock()
        def home(title):
            return frame((title, 470, 400), ('举办时间:09/29~10/22', 480, 446), ('帮助', 920, 50))
        help_screen = frame(('帮助', 480, 40), ('合成活动的标题名称', 320, 173))
        r.ui.capture.return_value = help_screen
        r.home = Mock(side_effect=[home('合成活动的标题名祢'), home('合成活动的标题名祢')])
        with patch('pcrscript.tasks.task_story_event.time.sleep'):
            self.assertEqual(r.event_identity(), '合成活动的标题名称')
        r.home = Mock(side_effect=[home('合成活动的标题名称'), home('另一个合成活动名称')])
        with patch('pcrscript.tasks.task_story_event.time.sleep'), self.assertRaisesRegex(EventUIError, '多帧'):
            r.event_identity()
        r.home = Mock(return_value=frame(('合成活动的标题名称', 470, 400)))
        with self.assertRaisesRegex(EventUIError, '举办时间'):
            r.event_identity()

    def test_tutorials_precede_home_recognition_and_login_receipt(self):
        pages = [
            ('活动限定剧情登场！', '在活动中，可以观看特别的剧情。'),
            ('挑战剧情关卡和首领战吧！', '试试挑战活动关卡和首领战吧。'),
            ('在公会管理协会可以使用活动奖励券', '在奖励兑换处，可以使用活动奖励券交换各种道具。'),
            ('分为3种难度的首领战！', '首领战共设有三种难度。'),
        ]
        for method in ('enter', 'home'):
            r = CampaignClean.__new__(CampaignClean)
            r.check_deadline = Mock()
            r.log = Mock()
            screens = []
            for title, body in pages:
                s = frame((title, 340, 55), ('可可萝', 280, 403), (body, 460, 434))
                s.items.extend(fixture('event_home').items)
                screens.append(s)
            r.ui = ReplayUI(screens + [fixture('event_login_reward'), fixture('event_home'), fixture('event_home')])
            self.assertTrue(getattr(r, method)())
            self.assertEqual(r.ui.clicks, [(780, 488)] * 4 + ['关闭'])

    def test_incomplete_or_unrelated_tutorial_is_not_clicked(self):
        r = CampaignClean.__new__(CampaignClean)
        r.ui = ReplayUI([])
        for items in (
            [('活动限定剧情登场！', 340, 55)],
            [('可可萝', 280, 403), ('购买体力', 460, 434)],
            [('活动限定剧情登场！', 340, 55), ('可可萝', 280, 403)],
        ):
            self.assertFalse(r.entry_dialog(frame(*items)))
        self.assertEqual(r.ui.clicks, [])


class FirstClearTests(TestCase):
    def test_current_team_requires_explicit_trial_opt_in(self):
        run = self.make_runner()
        with self.assertRaisesRegex(EventUIError, '未允许'):
            run.audit_party()
        self.assertEqual(run.ui.clicks, [])

    def test_auto_advance_leaves_combat_controls_to_game_and_checks_end_reason(self):
        for reason, succeeds in [('由于是最终关卡，自动推进结束', True), ('战斗失败，自动推进结束', False)]:
            run = self.make_runner()
            settings = self.plan_frame()
            settings.items.extend(frame(('立即发动', 365, 293), ('战斗开始', 590, 480)).items)
            settings.image[279:306, 274:301] = (255, 150, 50)
            settings.image[460:501, 540:641] = (255, 150, 50)
            battle = frame(('菜单', 900, 30), ('1:20', 800, 30))
            end = frame(('自动推进结束', 480, 148), (reason, 480, 238), ('确认', 480, 370),
                        ('13', 555, 200), ('160', 677, 311))
            run.ui = ReplayUI([settings, settings, battle, end])
            run.ui.expect_click = Mock()
            run.b.combat = SimpleNamespace(match=lambda key, screen: screen.find('菜单'))
            run.r.entry_dialog = Mock(return_value=False)
            run.r.story_dialog = Mock(return_value=False)
            with patch.object(run, 'audit_party'), patch('pcrscript.tasks.event_first_clear.time.sleep'):
                if succeeds:
                    self.assertIn('最终关卡', run.advance()['end_reason'])
                else:
                    with self.assertRaisesRegex(EventUIError, '提前停止'):
                        run.advance()
            self.assertEqual(run.ui.clicks, ['立即发动', '战斗开始'])
            run.r.story_dialog.assert_not_called()

    def make_runner(self, budget=200):
        r = SimpleNamespace(options={'max_first_clear_stamina': budget}, report={},
                            check_deadline=Mock(), report_progress=Mock(), log=Mock(), home=Mock())
        ui = ReplayUI([])
        b = SimpleNamespace(r=r, ui=ui, quest_catalog=Mock())
        return EventFirstClear(b)

    def plan_frame(self, cost='160', stamina='834', target='H-3'):
        return frame(('自动推进设定', 480, 40),
                     (f'自动推进至活动关卡{target}时，最多消耗以下的体力。', 400, 125),
                     (cost, 455, 157), (stamina, 685, 157))

    def test_plan_checks_endpoint_and_remaining_budget(self):
        run = self.make_runner()
        self.assertEqual(run.plan(self.plan_frame()), {'target': 'H-3', 'max_cost': 160, 'stamina_before': 834})
        run.spent = 50
        with self.assertRaisesRegex(EventUIError, '上限'):
            run.plan(self.plan_frame())
        run.spent = 0
        with self.assertRaisesRegex(EventUIError, '终点发生变化'):
            run.plan(self.plan_frame(target='H-4'))

    def test_recovered_partial_receipt_counts_toward_budget(self):
        run = self.make_runner()
        run.r.report['recovered_first_clear'] = {'spent': 60, 'cleared': 6, 'final': False}
        recovered = EventFirstClear(run.b)
        with self.assertRaisesRegex(EventUIError, '上限'):
            recovered.plan(self.plan_frame())
        self.assertEqual(recovered.ui.clicks, [])

    def test_missing_numbers_or_insufficient_stamina_never_click(self):
        for cost, stamina in [('?', '834'), ('160', '?'), ('160', '100'), ('0', '834')]:
            run = self.make_runner()
            with self.assertRaises(EventUIError):
                run.plan(self.plan_frame(cost, stamina))
            self.assertEqual(run.ui.clicks, [])

    def test_already_cleared_catalog_never_starts_battle(self):
        run = self.make_runner()
        run.b.quest_catalog.return_value = {'活动关卡N-1': 3, '活动关卡H-3': 3}
        run.run()
        self.assertEqual(run.ui.clicks, [])

    def test_no_progress_never_starts_second_attempt(self):
        run = self.make_runner()
        run.b.quest_catalog.return_value = {'活动关卡N-1': 0, '活动关卡N-2': 0}
        run.r.quests = Mock(return_value=frame(('824/413', 720, 25)))
        with patch.object(run, 'open_formation'), patch.object(run, 'advance', return_value={
                'stamina_before': 834, 'max_cost': 160, 'result': {'spent': 10}}) as advance:
            with self.assertRaisesRegex(EventUIError, '进度未变化'):
                run.run()
            advance.assert_called_once()

    def test_missing_final_stage_is_not_complete(self):
        run = self.make_runner()
        run.target = 'H-3'
        run.b.quest_catalog.return_value = {'活动关卡N-1': 3, '活动关卡H-1': 3}
        with self.assertRaisesRegex(EventUIError, '最终关卡'):
            run.run()


class ScenarioSupportTests(TestCase):
    def test_boss_lock_does_not_borrow_neighbouring_row(self):
        s = frame(('特别', 825, 302), ('特别战斗+', 825, 371))
        s.image[342:370, 731:759] = (30, 180, 230)
        self.assertFalse(boss_locked(s, s.items[0]))
        self.assertTrue(boss_locked(s, s.items[1]))

    def test_fixed_support_requires_two_matching_identifications(self):
        initial = frame(('队伍编组', 480, 40), ('支援', 585, 88))
        screen = frame(('队伍编组', 480, 40), ('在首领战（剧本模式）中，最多可编入5名', 780, 490),
                       ('支援角色。此外，也不会消耗玛那。', 780, 505))
        for second, valid in [(['角色甲', '角色乙', '角色丙', '角色丁', '角色戊'], True),
                              (['角色甲', '角色乙', '角色丙', '角色丁', None], False),
                              (['角色甲', '角色乙', '角色丙', '角色丁', '角色己'], False)]:
            b = EventBattles.__new__(EventBattles)
            b.r = SimpleNamespace(options={}, report={}, check_deadline=Mock())
            b.ui = ReplayUI([initial, screen, screen, screen])
            b.formation = SimpleNamespace(occupied_slots=lambda s: list(range(5)),
                                          slots=[(96+109*i, 452) for i in range(5)], slot_top=405)
            index = Mock()
            index.query.side_effect = [['角色甲', '角色乙', '角色丙', '角色丁', '角色戊'], second]
            with patch('pcrscript.game_ui.avatar_assets.ensure_avatar_index', return_value=(index, {})), \
                    patch('pcrscript.tasks.event_battle.time.sleep'):
                if valid:
                    party, selection = b.scenario_support()
                    self.assertEqual(party.build_basis, 'fixed_support')
                    self.assertEqual(selection['order'], second)
                else:
                    with self.assertRaises(EventUIError):
                        b.scenario_support()
            self.assertEqual(b.ui.clicks, ['支援'])
