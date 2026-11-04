"""CN guide boards as tower top trials, with synthetic sources and no device."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from pcrscript.tasks.tower_boards import board_plans, plans_from_rows, wanted_page, wanted_video

NAMES = ['合成'+str(i) for i in range(5)]
BVID = 'BV1234567890'


def api(*parts):
    client = Mock()
    client.search.return_value = dict(code=0, data=dict(result=[dict(result_type='video', data=[
        dict(bvid=BVID, title='【公主连结】<em>国服</em>露娜塔780顶层作业', pubdate=1)])]))
    client.getVideoInfo.return_value = dict(data=dict(pages=[dict(cid=i, part=p, duration=9) for i, p in enumerate(parts)]))
    return client


class ProvenOrderTests(TestCase):
    def test_a_real_knife_that_lowered_the_boss_goes_first(self):
        from pcrscript.tasks.tower_guides import prefer_proven
        plans = [dict(names=list('甲乙丙丁戊')), dict(names=list('己庚辛壬癸')), dict(names=list('子丑寅卯辰'))]
        def knife(names, before, after, simulate=False):
            return dict(names=list(names), simulate=simulate, before=dict(hp=[0, 0, 0, 0, before]), after=dict(hp=[0, 0, 0, 0, after]))
        battles = [knife('己庚辛壬癸', 71, 62), knife('子丑寅卯辰', 62, 70), knife('甲乙丙丁戊', 62, 50, simulate=True)]
        self.assertEqual(prefer_proven(plans, battles)[0]['names'], list('己庚辛壬癸'))
        self.assertEqual([p['names'][0] for p in prefer_proven(plans, battles)][1:], ['甲', '子'])


class ArticleGuideTests(TestCase):
    def test_no_article_urls_means_no_network_at_all(self):
        from pcrscript.tasks.tower_guides import load_guides
        http = Mock()
        self.assertEqual(load_guides(dict(guide_urls=[]), 780, Mock(), {}, http=http), [])
        self.assertEqual(load_guides({}, 700, Mock(), {}, http=http), [])
        http.get.assert_not_called()


class SlotGapTests(TestCase):
    def formation(self, order):
        from pcrscript.tasks.task_tower import TowerFormation
        formation = TowerFormation(Mock())
        formation.current_names = Mock(return_value=list(order))
        formation.occupied_slots = Mock(return_value=formation.slots)
        formation.avatars = Mock()
        return formation

    def test_one_unread_slot_is_the_member_just_picked(self):
        order = NAMES[:4]+[None]
        self.assertEqual(self.formation(order).settled_names(Mock(), None, NAMES), NAMES)

    def test_two_unread_slots_need_a_clear_pairing(self):
        import numpy as np
        frame = Mock(image=np.zeros((540, 960, 3), np.uint8))
        formation = self.formation(NAMES[:3]+[None, None])
        formation.avatars.assign_expected.return_value = [NAMES[4], NAMES[3]]
        self.assertEqual(formation.settled_names(frame, None, NAMES), NAMES[:3]+[NAMES[4], NAMES[3]])
        formation = self.formation(NAMES[:3]+[None, None])
        formation.avatars.assign_expected.return_value = None
        self.assertIn(None, formation.settled_names(frame, None, NAMES))

    def test_a_different_team_is_not_filled_in(self):
        order = ['其他']+NAMES[1:4]+[None]
        self.assertEqual(self.formation(order).settled_names(Mock(), None, NAMES), order)


class BoardPlanTests(TestCase):
    def test_only_ordinary_top_pages_are_read(self):
        self.assertTrue(wanted_page('顶层(不是EX)半血后每日磨血打法'))
        self.assertTrue(wanted_page('道中&普通顶层'))
        for part in ('顶层EX第一刀', 'EX难度实战-自用作业', '普通难度第一刀', '道中'):
            self.assertFalse(wanted_page(part), part)

    def test_only_this_servers_tower_videos_qualify(self):
        self.assertTrue(wanted_video('国服10.15露娜塔780顶层作业', 780))
        self.assertTrue(wanted_video('国服露娜塔780层顶层五刀阵容（非EX关）', 780))
        self.assertFalse(wanted_video('国服露娜塔780顶层ex不控血三刀', 780))
        self.assertFalse(wanted_video('日服露娜塔780顶层作业', 780))
        self.assertFalse(wanted_video('国服深渊讨伐战作业', 780))

    def test_grind_board_only_fights_the_boss_and_unread_set_defaults_on(self):
        plans = plans_from_rows([dict(names=NAMES, instant=None)], '半血后每日磨血', 's')
        self.assertEqual([(p['phase'], p['goal']) for p in plans], [(2, 'boss_damage'), (3, 'boss_damage')])
        self.assertEqual(set(plans[0]['instant'].values()), {True})

    def test_route_board_can_also_chip_shadows_and_keeps_fixed_set(self):
        plans = plans_from_rows([dict(names=NAMES, instant=[False, True, True, True, True])], '普通顶层', 's')
        self.assertEqual(plans[-1]['goal'], 'shadows')
        self.assertFalse(plans[0]['instant'][NAMES[0]])

    def test_grind_page_comes_first_and_results_are_cached(self):
        other = ['其他'+str(i) for i in range(5)]
        client = api('道中&普通顶层', '顶层(不是EX)半血后每日磨血', 'EX第一刀')
        with TemporaryDirectory() as folder:
            options = dict(guide_cache=folder, media_dir=folder)
            fetcher = Mock(return_value=(Path(folder)/'v.mp4', dict(duration=9)))
            reads = [[dict(names=NAMES, instant=None)], [dict(names=other, instant=None)]]
            with patch('pcrscript.tasks.tower_boards.read_board', side_effect=reads) as reader:
                plans, notes = board_plans(options, 780, Mock(), api=client, ocr=Mock(), media_fetcher=fetcher)
                self.assertEqual(plans[0]['names'], NAMES)
                self.assertIn('磨血', plans[0]['trial_reason'])
                self.assertEqual(reader.call_count, 2)
                self.assertEqual(len(notes), 2)
                board_plans(options, 780, Mock(), api=client, ocr=Mock(), media_fetcher=fetcher)
                self.assertEqual(reader.call_count, 2)
                client.search.assert_called()
                self.assertEqual(client.search.call_count, 2)  # Search is cached too.

    def test_empty_read_is_retried_once_the_portrait_index_grows(self):
        from types import SimpleNamespace
        client = api('顶层(不是EX)半血后每日磨血')
        with TemporaryDirectory() as folder:
            options = dict(guide_cache=folder, media_dir=folder)
            fetcher = Mock(return_value=(Path(folder)/'v.mp4', dict(duration=9)))
            cold, warm = SimpleNamespace(names=NAMES[:4]), SimpleNamespace(names=NAMES)
            with patch('pcrscript.tasks.tower_boards.read_board',
                       side_effect=[[], [dict(names=NAMES, instant=None)]]) as reader:
                self.assertEqual(board_plans(options, 780, cold, api=client, ocr=Mock(), media_fetcher=fetcher)[0], [])
                board_plans(options, 780, cold, api=client, ocr=Mock(), media_fetcher=fetcher)
                self.assertEqual(reader.call_count, 1)  # Same index: the empty read stands.
                plans, _ = board_plans(options, 780, warm, api=client, ocr=Mock(), media_fetcher=fetcher)
                self.assertEqual(reader.call_count, 2)
                self.assertEqual(plans[0]['names'], NAMES)

    def test_source_failure_is_reported_without_blocking_other_candidates(self):
        client = Mock()
        client.search.side_effect = RuntimeError('站点验证')
        with TemporaryDirectory() as folder:
            plans, notes = board_plans(dict(guide_cache=folder), 780, Mock(), api=client, ocr=Mock())
        self.assertEqual(plans, [])
        self.assertIn('站点验证', notes[0])
