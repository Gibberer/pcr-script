"""Synthetic raid pages; no account evidence or real strategies."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from ui_fixtures import screen, replay_ui, TaskReplayMixin
from pcrscript.game_ui import collaboration_raid as field
from pcrscript.game_ui.screen import EventUIError
from pcrscript.tasks.task_collaboration_raid import CollaborationRaid, validate_options
from pcrscript.tasks.collaboration_strategy import difficulty_scope, source_rejection, TITLE, BOSS
from pcrscript.tasks.strategy_sources import get_source_rules
from pcrscript.tasks.strategy_video import choose_pages, observed_scope
from pcrscript.game_ui.guide_vision import GuideText


def home(tickets=5):
    return screen((TITLE+'！', 170, 50), ('讨伐券', 700, 430), (str(tickets), 820, 430),
                  ('挑战', 740, 405), ('全体报酬', 603, 403), ('任务', 785, 32))


def missions(blue=False):
    return screen(('任务', 480, 42), ('限时任务：2026/10/23 11:00～2026/11/02 10:59', 480, 85),
                  ('全部收取', 590, 478), ('取消', 365, 478), blue=('全部收取',) if blue else ())


def detail(free=True):
    return screen(('BOSS详情', 113, 45), ('普通', 230, 45), ('模拟战', 750, 125),
                  ('实战', 865, 125), ('挑战', 840, 470), ('取消', 665, 470),
                  (BOSS+' 等级.25', 327, 270), ('100,000/100,000', 635, 338),
                  *((('完成初次讨伐前不消耗', 520, 482),) if free else (('跳过', 660, 470),)))


def sweep_detail():
    value = detail(False)
    value.items[1].text = '高难'
    extra = screen(('跳过伤害', 525, 390), ('120000000', 540, 412), ('使用5张', 755, 405),
                   ('讨伐券', 525, 455), ('5', 510, 480), ('0', 580, 480), blue=('使用5张',))
    value.items += extra.items
    value.image[380:430, 705:815] = extra.image[380:430, 705:815]
    return value


def confirmation(cost=5):
    return screen(('扫荡券确认', 480, 150), ('取消', 370, 375), ('确认', 590, 375),
                  ('消耗讨伐券', 330, 260), (str(cost), 450, 260),
                  ('消耗券', 330, 300), ('5', 450, 300), blue=('确认',))


def exchange(balance=101):
    return screen(('报酬交换', 140, 30), ('奖励券', 780, 444), (str(balance), 920, 444),
                  ('当前的列表', 625, 304), ('100次交换', 830, 365), ('使用100张', 830, 398),
                  ('1次交换', 610, 365), ('使用1张', 610, 398), blue=('100次交换', '1次交换'))


def exchange_confirmation(quantity=350, resets=0):
    return screen(('一键交换确认', 480, 88), (f'要批量兑换{quantity}张讨伐奖励券吗？', 480, 164),
                  ('即将重置的BOX数', 375, 228), (str(resets), 613, 228),
                  ('取消', 370, 434), ('交换', 590, 434), blue=('交换',))


def difficulty_menu(selected='困难'):
    x, y = {'普通': (279, 229), '困难': (499, 229), '高难': (279, 300)}[selected]
    return screen(('难度变更', 480, 147), ('取消', 370, 372), ('确认', 590, 372),
                  ('合成选择标记', x, y), blue=('确认', '合成选择标记'))


class RecognitionTests(TestCase):
    def test_detail_to_fight_uses_both_health_bars_and_rejects_new_attempt(self):
        from pcrscript.tasks.collaboration_strategy import ScopeContext
        scope = dict(boss=BOSS, difficulty='高难', level=100, maximum_hp=10000000)
        def bars(health, total=None):
            total = 80000000000000-10000000+health if total is None else total
            return [GuideText(str(total)+'/90000000000000', .99, (400, 40, 350, 25)),
                    GuideText(str(health)+'/10000000', .99, (600, 80, 200, 25))]
        c = ScopeContext()
        self.assertTrue(c.resolve(scope, True, bars(10000000), 0, False, dict(image='synthetic-detail'))[1])
        preparation = [GuideText('队伍编组', .99, (400, 30, 200, 30)),
                       GuideText('战斗开始', .99, (1000, 600, 150, 35))]
        self.assertFalse(c.resolve({}, False, preparation, 2, False, {})[1])
        self.assertTrue(c.resolve({}, False, bars(9000000), 5, True, {})[1])
        # A wrong OCR value is not evidence; a subsequent consistent frame
        # inside the bound can recover without adopting the wrong health.
        self.assertFalse(c.resolve({}, False, bars(1000000, 80000000000000), 6, True, {})[1])
        self.assertTrue(c.resolve({}, False, bars(8000000), 7, True, {})[1])
        self.assertFalse(c.resolve({}, False, bars(10000000), 8, True, {})[1])
        self.assertFalse(c.resolve({}, False, bars(7000000), 20, True, {})[1])

    def test_unknown_transition_clears_the_source_target(self):
        from pcrscript.tasks.collaboration_strategy import ScopeContext
        c = ScopeContext()
        c.resolve(dict(boss=BOSS, difficulty='高难'), True, [], 0, False, {})
        c.resolve({}, False, [GuideText('另一玩法', .99, (100, 30, 100, 30))], 1, False, {})
        self.assertFalse(c.scope)

    def test_year_before_full_set_is_not_a_timed_operation(self):
        from pcrscript.tasks.strategy_sources import timed_switch_requirement
        from pcrscript.tasks.strategy_video import manual_requirement, exact_full_set_claim
        title = '公主连结国服2026年10月剧情活动全Set一刀'
        self.assertFalse(timed_switch_requirement(title))
        self.assertFalse(manual_requirement(title, unparsed_settings=True))
        self.assertTrue(exact_full_set_claim(dict(title=title), dict(boss=BOSS), 'collaboration'))
        self.assertTrue(timed_switch_requirement('104全SET'))

    def test_required_metadata_blocks_media_before_download(self):
        from types import SimpleNamespace
        import numpy as np
        from pcrscript.tasks.strategy_video import parse_video_source
        with TemporaryDirectory() as folder:
            media = Mock()
            source = dict(bvid='BVSYNTHETIC', url='https://example.com/synthetic',
                          title='公主连结 国服 '+TITLE+' 高难攻略',
                          description='职能精通：全职业等级4及以上',
                          comment_complete=True, author_comments=[], pages=[dict(cid=1, part='高难', duration=4)])
            result = parse_video_source(source, dict(task_type='collaboration', parsed_dir=folder, skip_manual_media=True),
                SimpleNamespace(names=['合成角色'], matrix=np.ones((1, 1728))), api=Mock(), ocr=Mock(), media_fetcher=media)
            media.assert_not_called()
            self.assertEqual(result['parties'], [])
            self.assertTrue(result['global_requirements'])

    def test_parser_binds_two_combat_frames_and_preserves_unknown_build(self):
        from types import SimpleNamespace
        import numpy as np
        from pcrscript.tasks.strategy_video import parse_video_source
        from pcrscript.tasks.collaboration_strategy import parties_for_difficulty
        members = [dict(name='合成角色'+str(i), rectangle=[196+120*i, 400, 86, 85], score=.99) for i in range(5)]
        texts = [GuideText(BOSS+'等级.350', .99, (20, 20, 210, 25)),
                 GuideText('300000000/300000000', .99, (400, 70, 300, 25))]
        with TemporaryDirectory() as folder:
            source = dict(bvid='BVSYNTHETIC', url='https://example.com/synthetic', title='公主连结 国服 '+TITLE+' 高难攻略',
                          description='', comment_complete=True, author_comments=[], pages=[dict(cid=1, part='高难', duration=4)])
            capture = Mock()
            capture.read.side_effect = [(True, np.full((720, 1280, 3), n, np.uint8)) for n in (40, 80)]
            with patch('pcrscript.tasks.strategy_video.cv.VideoCapture', return_value=capture), \
                 patch('pcrscript.tasks.strategy_video.sample_seconds', return_value=[1, 2]), \
                 patch('pcrscript.tasks.strategy_video.frame_texts', return_value=texts), \
                 patch('pcrscript.tasks.strategy_video.battle_rectangles', return_value=[m['rectangle'] for m in members]), \
                 patch('pcrscript.tasks.strategy_video.combat_team', return_value=members), \
                 patch('pcrscript.tasks.strategy_video.formation_fields', return_value=[]), \
                 patch('pcrscript.tasks.strategy_video.combat_set', return_value=True), \
                 patch('pcrscript.tasks.strategy_video.combat_auto', return_value=True):
                result = parse_video_source(source, dict(task_type='collaboration', parsed_dir=folder),
                    SimpleNamespace(names=[m['name'] for m in members], matrix=np.ones((5, 1728))),
                    api=Mock(), ocr=Mock(), media_fetcher=lambda *a, **k: (Path(folder)/'synthetic.avi', dict(duration=4)))
            self.assertEqual(len(result['parties']), 1)
            self.assertEqual(result['parties'][0]['scope'], dict(boss=BOSS, difficulty='高难'))
            self.assertIsNone(result['parties'][0]['members'][0]['unique']['value'])
            self.assertFalse(parties_for_difficulty(result, '普通', allow_local_trials=False))
            adapted = parties_for_difficulty(result, '普通', allow_local_trials=True)
            self.assertEqual(len(adapted), 1)
            self.assertEqual(adapted[0].build_basis, 'local_trial')

    def test_numeric_source_identity_needs_exact_target_or_explicit_free_trial(self):
        from pcrscript.tasks.strategy_document import empty_member, Evidence, finalize
        from pcrscript.tasks.collaboration_strategy import parties_for_difficulty
        members = [empty_member('合成角色'+str(i)) for i in range(5)]
        for member in members:
            member['instant'].add(True, Evidence('https://example.com/synthetic'))
        raw = finalize(dict(task_type='collaboration', source='https://example.com/synthetic',
            scope=dict(boss=BOSS, level=100, maximum_hp=10000000), scope_verified=True,
            region='cn', target_region='cn', members=members, global_requirements=[], manual_actions=[],
            auto=dict(value=True, evidence=[dict(method='synthetic')], conflicts=[])))
        report = dict(parties=[raw])
        normal = dict(level=25, maximum_hp=100000)
        self.assertFalse(parties_for_difficulty(report, '普通', target=normal, allow_local_trials=False))
        self.assertEqual(len(parties_for_difficulty(report, '普通', target=normal, allow_local_trials=True)), 1)
        self.assertFalse(parties_for_difficulty(report, '高难', target=dict(level=350, maximum_hp=120000000), allow_local_trials=True))
        self.assertFalse(parties_for_difficulty(report, '普通', target=dict(level=25, maximum_hp=100000000), allow_local_trials=True))

    def test_activity_and_resource_identity(self):
        ui = Mock(number=lambda s, r: s.number(r))
        for n in (0, 5, 99):
            self.assertTrue(field.home(home(n)))
            self.assertEqual(field.tickets(ui, home(n)), n)
        other = home()
        other.items[0].text = '另一活动'
        self.assertFalse(field.home(other))
        self.assertIsNone(field.tickets(ui, other))

    def test_period_comes_from_full_year_and_server_timezone(self):
        self.assertEqual(field.period(missions()), (1792724400., 1793588399.))
        wave = missions()
        wave.items[1].text = wave.items[1].text.replace('～', '〜')
        self.assertEqual(field.period(wave), (1792724400., 1793588399.))
        invalid = missions()
        invalid.items[1].text = '限时任务：2026/10/23 11:00～2026/12/02 10:59'
        self.assertIsNone(field.period(invalid))

    def test_first_clear_requires_explicit_free_message_and_exact_boss(self):
        self.assertTrue(field.first_clear_free(detail()))
        self.assertFalse(field.first_clear_free(detail(False)))
        self.assertEqual(field.target(detail())['maximum_hp'], 100000)
        other = detail()
        other.items[6].text = '另一首领 等级.25'
        self.assertIsNone(field.target(other))

    def test_difficulty_scope_is_unique_and_not_hard_inside_very_hard(self):
        for text in ('高难', 'VH', 'Very Hard'):
            self.assertEqual(difficulty_scope(text), dict(boss=BOSS, difficulty='高难'))
        self.assertFalse(difficulty_scope('普通 困难 高难'))

    def test_source_rejects_other_period_region_and_unread_author_images(self):
        options = dict(period_start=1000000, period_end=2000000)
        source = dict(title='公主连结 国服 '+TITLE+' 攻略', description='', published_at=1100000)
        self.assertIsNone(source_rejection(source, options))
        for changes in (dict(published_at=1), dict(title='公主连结 日服 '+TITLE),
                        dict(comment_complete=False), dict(author_comments=[dict(images=['synthetic'])])):
            self.assertIsNotNone(source_rejection(dict(source, **changes), options))
        self.assertTrue(get_source_rules(dict(task_type='collaboration')).require_complete_comments)

    def test_all_pages_are_required_and_difficulty_title_does_not_prove_boss(self):
        source = dict(title=TITLE+' 高难', pages=[dict(cid=1, part='录像')])
        pages = choose_pages(source, dict(task_type='collaboration', max_pages_per_video=2))
        self.assertEqual(pages[0]['part'], source['title'])
        self.assertEqual(observed_scope([], pages[0], 'collaboration'), ({}, False))
        with self.assertRaises(ValueError):
            choose_pages(dict(source, pages=source['pages']*3), dict(task_type='collaboration', max_pages_per_video=2))


def fake_clock():
    ticks = iter(range(0, 10**6, 2))
    return Mock(monotonic=lambda: next(ticks), sleep=Mock(), time=Mock(return_value=0))


class RaidFlowTests(TaskReplayMixin, TestCase):
    def test_collective_reward_requires_all_three_matching_icon_quantities(self):
        reward = screen(('获得了佐贺偶像是传奇联动纪念10次扭蛋券×1', 480, 360),
                        ('超级不得了呢☆×1', 480, 384), ('宝石×200', 480, 407),
                        ('x1', 343, 294), ('x1', 538, 294), ('x200', 715, 294), ('挑战', 745, 406))
        self.frames([reward, home()])
        self.assertTrue(field.home(self.task.enter()))
        self.assertEqual(self.clicks(), ['获得了佐贺偶像是传奇联动纪念10次扭蛋券×1'])
        reward.items[5].text = 'x100'
        self.assertIsNone(field.collective_reward(reward))

    def test_one_key_exchange_checks_quantity_and_forbids_implicit_pool_reset(self):
        self.task.state['pending_exchange'] = dict(before=350, after=0, quantity=350)
        self.frames([exchange_confirmation(), screen(('交换结果', 480, 42), ('关闭', 480, 480)), exchange(0)])
        self.task.settle_exchange()
        self.assertEqual(self.clicks(), ['交换', '关闭'])
        self.assertEqual(self.task.report['remaining_reward_tickets'], 0)
        self.assertNotIn('pending_exchange', self.task.state)
        for quantity, resets, submitted in ((349, 0, False), (350, 1, False), (350, 0, True)):
            self.task.ui.click.reset_mock()
            self.task.state['pending_exchange'] = dict(before=350, after=0, quantity=350, final_submitted=submitted)
            self.frames([exchange_confirmation(quantity, resets)])
            with self.assertRaisesRegex(EventUIError, '未确认兑换'):
                self.task.settle_exchange()
            self.assertEqual(self.clicks(), [])
            self.assertIn('pending_exchange', self.task.state)

    def test_visible_unsubmitted_exchange_can_cancel_and_reconcile_unchanged_balance(self):
        self.frames([exchange_confirmation(), exchange(350), home(0)])
        self.assertTrue(field.home(self.task.enter()))
        self.assertEqual(self.clicks(), ['取消', (30, 30)])
        self.task.state['pending_exchange'] = dict(before=350, after=0, quantity=350)
        self.task.open_exchange = Mock(return_value=exchange(350))
        self.frames([home(0)])
        self.task.reconcile_pending(home(0), missions())
        self.assertNotIn('pending_exchange', self.task.state)
        self.assertEqual(self.task.report['history'][-1]['outcome'], 'cancelled_before_submission')

    def test_daily_login_receipt_waits_for_body_and_close_over_home(self):
        heading = ('获得活动登录奖励', 480, 147)
        body = ('已领取以下道具作为登录奖励。', 480, 188)
        partial = home()
        partial.items += screen(heading).items
        ready = home()
        ready.items += screen(heading, body, ('讨伐券×5', 410, 237), ('关闭', 480, 372)).items
        self.frames([partial, ready, home()])
        with patch('pcrscript.tasks.task_collaboration_raid.time.sleep'):
            self.assertTrue(field.home(self.task.enter()))
        self.assertEqual(self.clicks(), ['关闭'])
        self.task.ui.save.assert_called_with('daily_login_reward', ready)

    def test_daily_login_close_requires_the_receipt_body(self):
        incomplete = screen(('获得活动登录奖励', 480, 147), ('关闭', 480, 372))
        with patch('pcrscript.tasks.task_collaboration_raid.time.sleep'):
            self.assertTrue(self.task.combat_pre_dialog(incomplete))
        self.assertEqual(self.clicks(), [])
        unrelated = screen(('未知奖励', 480, 147), ('关闭', 480, 372))
        self.assertFalse(self.task.combat_pre_dialog(unrelated))
        self.assertEqual(self.clicks(), [])

    def test_automatic_gem_reward_dismisses_only_matching_amounts(self):
        reward = screen(('获得了宝石×450', 480, 360), ('x450', 518, 294), ('挑战', 745, 406))
        self.frames([reward, screen(('冒险', 540, 525)), home()])
        self.assertTrue(field.home(self.task.enter()))
        self.assertEqual(self.clicks(), ['获得了宝石×450'])
        reward.items[1].text = 'x400'
        self.assertIsNone(field.gem_reward(reward))

    def test_known_unlock_notice_closes_without_starting_another_battle(self):
        notice = screen(('困难解锁', 480, 147), ('困难已解锁。', 480, 273), ('关闭', 480, 372))
        self.frames([notice, home()])
        self.assertTrue(field.home(self.task.enter()))
        self.assertEqual(self.clicks(), ['关闭'])
        notice.items[1].text = '未知要求'
        self.assertIsNone(field.unlock_dialog(notice))
        story = screen(('剧情解锁', 480, 147), ('Re:Start SAGA', 490, 260),
                       ('已解锁。', 455, 280), ('关闭', 480, 372))
        self.assertIsNotNone(field.unlock_dialog(story))
        story.items[1].text = '另一活动'
        self.assertIsNone(field.unlock_dialog(story))

    def test_difficulty_switch_confirms_only_after_radio_selection(self):
        hard = detail()
        hard.items[1].text = '困难'
        hard.items.extend(screen(('难度变更', 365, 44)).items)
        self.task.enter = Mock(return_value=home())
        self.frames([hard, difficulty_menu(), difficulty_menu('普通'), detail()])
        self.assertEqual(field.difficulty(self.task.open_detail('普通')), '普通')
        self.assertEqual(self.clicks(), ['挑战', '难度变更', (279, 229), '确认'])
        self.assertFalse(field.selected_difficulty(difficulty_menu(), '高难'))

    def test_exchange_uses_displayed_cost_and_requires_receipt_and_balance(self):
        self.task.open_exchange = Mock(return_value=exchange())
        self.frames([screen(('交换结果', 480, 42), ('关闭', 480, 480)), exchange(1),
                     screen(('交换结果', 480, 42), ('关闭', 480, 480)), exchange(0), home()])
        self.task.exchange()
        self.assertEqual([p['quantity'] for p in self.task.report['exchanges']], [100, 1])
        self.assertEqual(self.task.report['remaining_reward_tickets'], 0)
        self.assertNotIn('pending_exchange', self.task.state)

    def test_exchange_wrong_balance_retains_pending_and_never_repeats(self):
        self.task.open_exchange = Mock(return_value=exchange())
        self.frames([screen(('交换结果', 480, 42), ('关闭', 480, 480)), exchange(101)])
        with self.assertRaisesRegex(EventUIError, '扣除'):
            self.task.exchange()
        self.assertIn('pending_exchange', self.task.state)
        self.assertEqual(self.clicks().count('100次交换'), 1)

    def test_last_allowed_exchange_batch_can_finish_at_zero(self):
        self.task.options['max_exchange_batches'] = 1
        self.task.open_exchange = Mock(return_value=exchange(100))
        self.frames([screen(('交换结果', 480, 42), ('关闭', 480, 480)), exchange(0), home()])
        self.task.exchange()
        self.assertEqual(self.task.report['remaining_reward_tickets'], 0)

    def test_sweep_requires_both_costs_receipt_and_exact_balance_change(self):
        self.task.report['remaining_tickets'] = 5
        self.frames([confirmation(), screen(('扫荡结果', 480, 42), ('关闭', 480, 480)), home(0)])
        self.task.sweep(sweep_detail())
        self.assertEqual(self.task.report['spent'], 5)
        self.assertEqual(self.task.report['remaining_tickets'], 0)
        self.assertNotIn('pending_spend', self.task.state)
        self.assertEqual(self.clicks(), ['使用5张', '确认', '关闭'])

    def test_skip_complete_animation_button_only_settles_existing_spend(self):
        self.task.report['remaining_tickets'] = 5
        self.task.state['pending_spend'] = dict(kind='sweep', before=5, after=0, quantity=5)
        result = screen(('扫荡结果', 480, 42), ('跳过完毕', 478, 478))
        self.frames([result, home(0)])
        self.task.settle_sweep()
        self.assertEqual(self.clicks(), ['跳过完毕'])
        self.assertEqual(self.task.report['spent'], 5)
        self.assertEqual(self.task.report['remaining_tickets'], 0)
        self.assertNotIn('pending_spend', self.task.state)

    def test_wrong_cost_never_confirms_and_uncertain_balance_never_replays(self):
        self.task.report['remaining_tickets'] = 5
        self.frames([confirmation(4)])
        with self.assertRaisesRegex(EventUIError, '消费不符'):
            self.task.sweep(sweep_detail())
        self.assertNotIn('确认', self.clicks())
        self.task.ui.click.reset_mock()
        self.frames([confirmation(), screen(('扫荡结果', 480, 42), ('关闭', 480, 480)), home(5)])
        with self.assertRaisesRegex(EventUIError, '余额刷新未确认'):
            self.task.sweep(sweep_detail())
        self.assertIn('pending_spend', self.task.state)
        self.assertEqual(self.clicks().count('确认'), 1)

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        robot = Mock(driver=Mock(device_name='synthetic'), task_config=dict(CollaborationRaid=dict(output=self.folder.name, state_dir=self.folder.name)), _task_output=None)
        self.task = CollaborationRaid(robot)
        self.task.ui = replay_ui(self.folder.name)
        self.task.ui.number.side_effect = lambda s, roi: s.number(roi)

    def skip_result_over_detail(self):
        value = sweep_detail()
        value.items += screen(('扫艺结果', 480, 42), ('跳过次数', 453, 92), ('5回', 558, 92),
                              ('5只击破！', 480, 135), ('确认', 478, 478)).items
        return value

    def test_misread_skip_result_title_is_a_receipt_not_the_detail_page(self):
        self.task.report.update(remaining_tickets=5, spent=0)
        self.task.state['pending_spend'] = dict(kind='sweep', before=5, after=0, quantity=5)
        self.frames([self.skip_result_over_detail(), home(0)])
        self.task.settle_sweep()
        self.assertEqual(field.skip_result(self.skip_result_over_detail()), 5)
        self.assertEqual(self.clicks(), ['确认'])
        self.assertEqual((self.task.report['spent'], self.task.report['remaining_tickets']), (5, 0))
        self.assertNotIn('pending_spend', self.task.state)

    def test_interrupted_skip_result_recovers_only_with_matching_balance(self):
        self.frames([self.skip_result_over_detail(), home(0)])
        self.assertTrue(field.home(self.task.enter()))
        self.assertEqual(self.clicks(), ['确认'])
        for balance, recovered in ((0, True), (5, False)):
            self.task.state = dict(pending_spend=dict(kind='sweep', before=5, after=0, quantity=5))
            if recovered:
                self.task.reconcile_pending(home(balance), missions())
                self.assertNotIn('pending_spend', self.task.state)
                self.assertTrue(self.task.report['history'][-1]['recovered'])
            else:
                with self.assertRaisesRegex(EventUIError, '扫荡消费仍未知'):
                    self.task.reconcile_pending(home(balance), missions())
                self.assertIn('pending_spend', self.task.state)

    def test_one_key_exchange_uses_displayed_cost_and_never_drips_single_batches(self):
        def one_key(cost, blue=True):
            return screen(('报酬交换', 140, 30), ('奖励券', 780, 444), ('350', 920, 444),
                          ('当前的列表', 625, 304), ('一键交换', 830, 365), ('使用'+str(cost)+'张', 830, 398),
                          ('1次交换', 610, 365), ('使用1张', 610, 398),
                          blue=('1次交换',) + (('一键交换',) if blue else ()))
        button, amount = field.exchange_action(one_key(350), 350)
        self.assertEqual((button.text, amount), ('一键交换', 350))
        self.assertEqual(field.exchange_action(one_key(100), 350)[1], 100)
        for page in (one_key(400), one_key(350, blue=False)):
            self.assertIsNone(field.exchange_action(page, 350))

    def test_item_receipt_closes_with_cancel_or_lone_confirm(self):
        text = '获得的报酬将会直接增加到持有道具中。'
        fading = screen((text, 475, 385))
        for close, position in (('取消', (365, 430)), ('确认', (480, 428))):
            self.task.ui.click.reset_mock()
            self.task.open_exchange = Mock(return_value=exchange(1))
            self.frames([fading, screen((text, 475, 385), (close, *position)), exchange(0), home()])
            self.task.exchange()
            self.assertEqual(self.clicks(), ['1次交换', close, (30, 30)])
            self.assertTrue(self.task.report['exchanges'][-1]['receipt'])

    def test_pool_reset_after_exchange_settles_with_matching_balance(self):
        self.task.open_exchange = Mock(return_value=exchange(1))
        complete = screen(('已获得第1轮报酬列表中的全部报酬。', 480, 283),
                          ('切换到下一个报酬列表。', 480, 318), ('确认', 480, 370))
        reset = screen(('重置完毕', 480, 146), ('重置了报酬列表。', 475, 254), ('确认', 477, 370))
        self.frames([complete, reset, exchange(0), home()])
        self.task.exchange()
        self.assertEqual(self.clicks(), ['1次交换', '确认', '确认', (30, 30)])
        self.assertNotIn('pending_exchange', self.task.state)
        self.assertEqual(self.task.report['remaining_reward_tickets'], 0)

    def test_swallowed_mission_tap_is_retried_only_from_verified_home(self):
        self.frames([home()]*3 + [missions()])
        with patch('pcrscript.tasks.task_collaboration_raid.time', fake_clock()):
            self.assertTrue(field.missions(self.task.open_missions(home())))
        self.assertEqual(self.clicks(), ['任务', '任务'])
        self.task.ui.click.reset_mock()
        self.frames([screen(('未知', 480, 270))]*30)
        with patch('pcrscript.tasks.task_collaboration_raid.time', fake_clock()):
            with self.assertRaisesRegex(EventUIError, '联动任务列表'):
                self.task.open_missions(home())
        self.assertEqual(self.clicks(), ['任务'])

    def test_ticket_budget_stop_is_complete_and_does_not_block_other_activities(self):
        task = self.task
        task.options['max_tickets'] = 3
        task.enter = Mock(return_value=home(8))
        task.initialize = Mock(return_value=home(8))
        task.open_detail = Mock(return_value=sweep_detail())
        task.collect, task.exchange = Mock(), Mock()

        def sweep(_):
            task.report['spent'] += 3
            task.report['remaining_tickets'] -= 3
        task.sweep = Mock(side_effect=sweep)
        with patch.object(field, 'first_clear_free', return_value=False), \
                patch.object(field, 'cleared', return_value=True):
            report = task.run()
        self.assertEqual((report['status'], report['remaining_tickets'], report['pending']), ('complete', 5, []))
        self.assertTrue(report['budget_limited'])
        task.sweep.assert_called_once()

    def test_invalid_budgets_fail_before_device(self):
        for value in (True, 0, -1, 1000):
            with self.assertRaises(ValueError):
                CollaborationRaid.prepare(dict(CollaborationRaid=dict(max_tickets=value)))
        with self.assertRaises(ValueError):
            validate_options(dict(first_clear='yes'))
        with self.assertRaises(ValueError):
            validate_options(dict(max_exchange_batches=201))

    def test_unavailable_account_party_advances_source_discovery(self):
        from pcrscript.tasks.task_collaboration_raid import NoUsableParty
        url = 'https://example.com/synthetic'
        self.task.sources = dict(parties=[dict(source=url)])
        self.task.try_first_clear = Mock(side_effect=[NoUsableParty('缺少角色'), detail(False)])
        self.task.open_detail = Mock(return_value=detail())
        result = self.task.first_clear(detail())
        self.assertFalse(field.first_clear_free(result))
        self.assertEqual(self.task.excluded_sources, {url})
        self.assertIsNone(self.task.sources)
        self.assertEqual(self.task.try_first_clear.call_count, 2)

    def test_entry_waits_through_a_footer_only_transition(self):
        adventure = screen(('冒险', 90, 30), ('联动讨伐', 412, 440))
        transition = screen(('冒险', 539, 525))
        self.frames([adventure, transition, home()])
        with patch('pcrscript.tasks.task_collaboration_raid.time.sleep'):
            self.assertTrue(field.home(self.task.enter()))
        self.assertEqual(self.clicks(), [(412, 406)])

    def test_unknown_source_cannot_start_a_free_battle(self):
        self.task.sources = dict(parties=[])
        with self.assertRaisesRegex(EventUIError, '没有通过'):
            self.task.first_clear(detail())
        self.assertFalse(self.clicks())

    def test_paid_detail_cannot_be_used_as_first_clear(self):
        with self.assertRaises(EventUIError):
            self.task.first_clear(detail(False))
        self.assertFalse(self.clicks())

    def test_zero_claims_require_disabled_button_and_do_not_submit(self):
        self.frames([home(), missions()])
        self.task.collect()
        self.assertEqual(self.clicks(), ['任务', '取消'])
        self.assertNotIn('pending_claim', self.task.state)

    def test_pending_submission_is_durable_and_never_replayed(self):
        self.task.options['state_dir'] = str(Path(self.folder.name)/'state')
        self.task.period = (1792724400., 1793588399.)
        self.frames([missions(), home()])
        with patch('pcrscript.tasks.task_collaboration_raid.time.time', return_value=1792750000):
            self.task.initialize(home())
            self.task.state['pending_spend'] = dict(before=5, after=4)
            self.task.save()
            self.frames([missions(), home()])
            with self.assertRaisesRegex(EventUIError, '上次未核对'):
                self.task.initialize(home())
        self.assertNotIn('挑战', self.clicks())
