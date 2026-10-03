"""Synthetic current-event metadata, scope transitions and source switch gates."""
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import numpy as np

from pcrscript.constants import SERVER_TIMEZONE
from pcrscript.game_ui.guide_vision import GuideText
from pcrscript.game_ui.screen import EventUIError
from pcrscript.tasks.base import Event
from pcrscript.tasks.event_strategy import CharacterStatus, EventParty, MemberRequirement
from pcrscript.tasks.strategy_document import Evidence, empty_member, finalize
from pcrscript.tasks.strategy_video import choose_pages, parse_video_source, acquire_strategies
from pcrscript.tasks.subjugation_guides import (source_options, source_rejection, queries,
    visible_scope, relevant_statements, ScopeContext, parties_for_target, damage_reference)
from pcrscript.tasks.subjugation_party import guide_party
from pcrscript.tasks.task_abyss_subjugation import AbyssSubjugation


START = datetime(2026, 10, 2, 12, tzinfo=SERVER_TIMEZONE).timestamp()
EVENT = Event(START, START+5*86400, '合成任务',
              dict(title='合成深渊', talent_id=2, abyss_id=123))


def texts(*labels):
    return [GuideText(t, 1, (100, 50+i*30, 150, 20)) for i, t in enumerate(labels)]


def trial_report():
    members = [empty_member('合成角色'+str(i)) for i in range(5)]
    for i, member in enumerate(members):
        member['instant'].add(i != 0, Evidence('https://example.com/synthetic'))
    raw = finalize(dict(task_type='subjugation', source='https://example.com/synthetic',
        scope=dict(kind='outpost', difficulty='高难'), scope_verified=True,
        region='cn', target_region='cn', members=members,
        auto=dict(value=False, evidence=[dict(method='synthetic')], conflicts=[]),
        global_requirements=[], manual_actions=[]))
    return dict(parties=[raw])


class SubjugationGuideTests(TestCase):
    def test_next_source_batch_reaches_the_fifth_public_search_result(self):
        with TemporaryDirectory() as folder:
            ids = [f'BV{i:010d}' for i in range(5)]
            title = '公主连结 国服10月水属性深渊讨伐战 合成深渊'
            api = Mock()
            api.search.return_value = dict(code=0, data=dict(result=[dict(result_type='video',
                data=[dict(bvid=bvid, title=title) for bvid in ids])]))
            api.getVideoInfo.side_effect = lambda *, bvid: dict(code=0, data=dict(
                bvid=bvid, title=title, desc='', pubdate=START+100,
                pages=[dict(cid=1, page=1, part='前哨高难', duration=2)]))
            def parse(source, *args, **kwargs):
                report = trial_report() if source['bvid'] == ids[-1] else dict(parties=[])
                report['errors'] = []
                return report
            runner = SimpleNamespace(options=dict(discover_sources=True, source_urls=[], allow_local_trials=True,
                sources=dict(cache_dir=str(Path(folder)/'sources'), parsed_dir=str(Path(folder)/'parsed'), max_videos=4)),
                source_pools={}, inspected_sources={}, event=EVENT, report={}, formation=Mock(),
                report_progress=Mock(), check_deadline=Mock(), save=Mock())
            with patch('pcrscript.tasks.task_abyss_subjugation.prepare_avatars'), \
                 patch('pcrscript.tasks.strategy_video.BilibiliApi', return_value=api), \
                 patch('pcrscript.tasks.strategy_video.preferred_sources', return_value=([], [])), \
                 patch('pcrscript.tasks.strategy_video.parse_video_source', side_effect=parse) as parser:
                self.assertEqual(AbyssSubjugation.source_parties(runner, 'outpost', difficulty='高难'), [])
                found = AbyssSubjugation.source_parties(runner, 'outpost', difficulty='高难', advance=True)
            self.assertEqual(len(found), 1)
            self.assertEqual([c.args[0]['bvid'] for c in parser.call_args_list], ids)
            self.assertEqual([len(r['report']['inspected_sources']) for r in runner.report['sources']], [4, 1])

    def test_actual_boss_and_difficulty_scope_have_separate_source_caches(self):
        runner = SimpleNamespace(options=dict(discover_sources=True, source_urls=[], allow_local_trials=True),
            source_pools={}, inspected_sources={}, event=EVENT, report={}, formation=Mock(),
            report_progress=Mock(), check_deadline=Mock(), save=Mock())
        def acquire(options, **kwargs):
            report = trial_report()
            report['parties'][0]['scope'] = dict(kind='boss', boss=options['boss'], difficulty=options['difficulty'])
            return report
        with patch('pcrscript.tasks.task_abyss_subjugation.prepare_avatars'), \
             patch('pcrscript.tasks.strategy_video.acquire_strategies', side_effect=acquire) as fetch:
            for boss, difficulty in (('合成首领甲', '普通'), ('合成首领甲', '普通'),
                                     ('合成首领甲', '困难'), ('合成首领乙', '普通')):
                self.assertEqual(len(AbyssSubjugation.source_parties(
                    runner, 'boss', boss, 1, difficulty=difficulty)), 1)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual([(c.args[0]['boss'], c.args[0]['difficulty']) for c in fetch.call_args_list],
                         [('合成首领甲', '普通'), ('合成首领甲', '困难'), ('合成首领乙', '普通')])

    def test_higher_outpost_guide_requires_account_trial_permission(self):
        report = trial_report()
        options = source_options({}, EVENT, difficulty='普通')
        self.assertEqual(parties_for_target(report, options, allow_local_trials=False), [])
        candidate = parties_for_target(report, options, allow_local_trials=True)[0]
        self.assertTrue(any('高难' in note and '普通' in note for note in candidate.assumptions))
        report['parties'][0]['scope'] = dict(kind='boss', difficulty='极难', boss='合成首领')
        self.assertEqual(parties_for_target(report, options, allow_local_trials=True), [])

    def test_complete_current_difficulty_guide_needs_no_account_trial_permission(self):
        report = trial_report()
        raw = report['parties'][0]
        for member in raw['members']:
            for key, value in dict(level=100, rank=10, stars=5, skill_level=100,
                                   unique=True, unique2=False).items():
                member[key] = dict(value=value, evidence=[dict(method='synthetic')], conflicts=[])
        for kind in ('outpost', 'boss'):
            options = source_options({}, EVENT, kind=kind, boss='合成首领', difficulty='普通')
            raw['scope'] = dict(kind=kind, difficulty='普通')
            if kind == 'boss':
                raw['scope']['boss'] = '合成首领'
            with self.subTest(kind=kind):
                candidate = parties_for_target(report, options, allow_local_trials=False)[0]
                self.assertEqual(candidate.build_basis, 'source')
                self.assertIs(candidate.auto, False)
                self.assertIs(candidate.members[0].instant, False)
                raw['scope']['difficulty'] = '极难' if kind == 'boss' else '高难'
                self.assertEqual(parties_for_target(report, options, allow_local_trials=False), [])
                adapted = parties_for_target(report, options, allow_local_trials=True)[0]
                self.assertEqual(adapted.build_basis, 'local_trial')

    def test_searched_sources_keep_the_authors_supplement_before_video_parsing(self):
        with TemporaryDirectory() as folder:
            options = source_options({}, EVENT, kind='boss', boss='合成首领', boss_number=1)
            options['parsed_dir'] = folder
            api = Mock()
            api.getVideoInfo.return_value = dict(code=0, data=dict(bvid='BVSYNTHETIC',
                title='公主连结10月水属性深渊讨伐战', desc='-', pubdate=START+100,
                pages=[dict(cid=1, part='Boss1', duration=2)]))
            comment = dict(text='3王需要等级突破', reply_id=12, owner_id='34')
            parsed = dict(parties=[], errors=[], source='https://example.com/synthetic')
            with patch('pcrscript.tasks.strategy_video.discover_sources', return_value=dict(candidates=[dict(bvid='BVSYNTHETIC')])), \
                 patch('pcrscript.tasks.strategy_video.preferred_sources', return_value=([dict(author_comments=[comment])], [])), \
                 patch('pcrscript.tasks.strategy_video.parse_video_source', return_value=parsed) as parse:
                acquire_strategies(options, api=api, index=Mock())
                self.assertEqual(parse.call_args.args[0]['author_comments'], [comment])

    def test_target_relevant_metadata_manual_and_borrow_requirements_block_parties(self):
        for field in ('description', 'author_comments'):
            for statement in ('Boss2 手动轴', '需要借角色', 'Boss2 1:05关闭自动', 'Boss1 手动轴'):
                with self.subTest(field=field, statement=statement), TemporaryDirectory() as folder:
                    options = source_options({}, EVENT, kind='boss', boss='合成首领', boss_number=2)
                    options.update(parsed_dir=folder, skip_manual_media=False)
                    source = dict(bvid='BVSYNTHETIC', url='https://example.com/synthetic',
                        title='公主连结 国服 合成深渊', pages=[dict(cid=1, part='Boss2', duration=4)])
                    source[field] = statement if field == 'description' else [dict(text=statement, reply_id=12)]
                    boxes = [(100+i*120, 390, 100, 100) for i in range(5)]
                    members = [dict(name=f'合成角色{i}', rectangle=list(b), score=.99) for i, b in enumerate(boxes)]
                    index = SimpleNamespace(names=[m['name'] for m in members], matrix=np.ones((5,1728),np.float32))
                    capture = Mock()
                    capture.read.side_effect = [(True, np.full((540,960,3), i*20, np.uint8)) for i in range(4)]
                    labels = [texts('BOSS详情', '高难', '合成首领', '80000000/80000000')]*2+[
                        texts(timer, '79000000/80000000') for timer in ('1:29', '1:28')]
                    with patch('pcrscript.tasks.strategy_video.cv.VideoCapture', return_value=capture), \
                         patch('pcrscript.tasks.strategy_video.sample_seconds', return_value=[.5,1.5,2.5,3.5]), \
                         patch('pcrscript.tasks.strategy_video.frame_texts', side_effect=labels), \
                         patch('pcrscript.tasks.strategy_video.battle_rectangles', side_effect=[[]]*2+[boxes]*2), \
                         patch('pcrscript.tasks.strategy_video.combat_team', side_effect=[[]]*2+[members]*2), \
                         patch('pcrscript.tasks.strategy_video.formation_fields', return_value=[]), \
                         patch('pcrscript.tasks.strategy_video.combat_auto', return_value=True), \
                         patch('pcrscript.tasks.strategy_video.combat_set', return_value=True):
                        report = parse_video_source(source, options, index, api=Mock(), ocr=Mock(),
                            media_fetcher=lambda *a, **k: (Path(folder)/'synthetic.avi',dict(duration=4)))
                    self.assertEqual(len(report['parties']), 1)
                    actions = report['parties'][0]['manual_actions']
                    applies = not statement.startswith('Boss1')
                    self.assertEqual(len(parties_for_target(report, options, allow_local_trials=True)), int(not applies))
                    if applies:
                        self.assertEqual(actions[0]['text'], statement)
                        self.assertIsNone(actions[0]['evidence']['cid'])
                        self.assertEqual(actions[0]['evidence']['method'],
                                         'source_description' if field == 'description' else 'author_comment:12')
                    else:
                        self.assertEqual(actions, [])

    def test_production_skips_media_for_manual_source_metadata(self):
        for field in ('title', 'description', 'author_comments'):
            with self.subTest(field=field), TemporaryDirectory() as folder:
                options = source_options({}, EVENT, kind='boss', boss='合成首领', boss_number=2)
                options['parsed_dir'] = folder
                source = dict(bvid='BVSYNTHETIC', url='https://example.com/synthetic',
                    title='公主连结 国服 合成深渊', pages=[dict(cid=1, part='Boss2', duration=4)])
                source[field] = [dict(text='需要借角色', reply_id=12)] if field == 'author_comments' else '需要借角色'
                index = SimpleNamespace(names=['合成角色'], matrix=np.ones((1,1728),np.float32))
                fetch = Mock(side_effect=AssertionError('Unsupported source must not download media'))
                report = parse_video_source(source, options, index, api=Mock(), ocr=Mock(), media_fetcher=fetch)
                self.assertEqual(report['parties'], [])
                self.assertTrue(report['manual_actions'])
                fetch.assert_not_called()

    def test_nonmatching_boss_video_cache_is_bound_to_the_requested_boss(self):
        with TemporaryDirectory() as folder:
            options = source_options({}, EVENT, kind='boss', boss='合成首领')
            options['parsed_dir'] = folder
            source = dict(bvid='BVSYNTHETIC', url='https://example.com/synthetic',
                          title='公主连结 国服 合成深渊', pages=[dict(cid=1, part='Boss1', duration=2)])
            index = SimpleNamespace(names=['合成角色'], matrix=np.ones((1,1728),np.float32))
            capture = Mock()
            capture.read.side_effect = [(True, np.full((540,960,3), i*20, np.uint8)) for i in range(2)]
            fetcher = Mock(return_value=(Path(folder)/'synthetic.avi', dict(duration=2)))
            with patch('pcrscript.tasks.strategy_video.cv.VideoCapture', return_value=capture), \
                 patch('pcrscript.tasks.strategy_video.sample_seconds', return_value=[.5,1.5]), \
                 patch('pcrscript.tasks.strategy_video.frame_texts', return_value=[]), \
                 patch('pcrscript.tasks.strategy_video.battle_rectangles', return_value=[]), \
                 patch('pcrscript.tasks.strategy_video.combat_team', return_value=[]), \
                 patch('pcrscript.tasks.strategy_video.formation_fields', return_value=[]):
                first = parse_video_source(source, options, index, api=Mock(), ocr=Mock(), media_fetcher=fetcher)
                self.assertEqual(first['parties'], [])
                self.assertEqual(first['errors'], [])
                second = parse_video_source(source, options, index, api=Mock(), ocr=Mock(), media_fetcher=fetcher)
                self.assertTrue(second['cache_hit'])
                self.assertEqual(fetcher.call_count, 1)
                capture.read.side_effect = [(True, np.full((540,960,3), i*20, np.uint8)) for i in range(2)]
                third = parse_video_source(source, dict(options, boss='另一个合成首领'), index,
                                           api=Mock(), ocr=Mock(), media_fetcher=fetcher)
                self.assertFalse(third['cache_hit'])
                self.assertEqual(fetcher.call_count, 2)

    def test_another_plan_gear_dialog_is_isolated_but_common_requirements_still_apply(self):
        cases = [('前哨打法1', 'outpost', '特别装备五星要求', 1),
                 ('前哨练度', 'outpost', '特别装备五星要求', 0),
                 ('前哨注意事项', 'outpost', '特别装备五星要求', 0),
                 ('前哨其他信息', 'outpost', '等级突破要求', 0),
                 ('前哨打法1通用说明', 'outpost', '特别装备五星要求', 0),
                 ('Boss通用说明', 'boss', '特别装备五星要求', 0),
                 ('Boss通用说明', 'boss', '1:05关闭自动', 0)]
        for first_title, kind, constraint, eligible in cases:
            with self.subTest(first_title=first_title, constraint=constraint), TemporaryDirectory() as folder:
                options = source_options({}, EVENT, kind=kind, boss='合成首领', boss_number=1)
                options['parsed_dir'] = folder
                source = dict(bvid='BVSYNTHETIC', url='https://example.com/synthetic',
                    title='公主连结 国服 合成深渊',
                    author_comments=[dict(text='3王需要等级突破')],
                    pages=[dict(cid=1, part=first_title, duration=2),
                           dict(cid=2, part=('前哨' if kind == 'outpost' else 'Boss1')+'打法2', duration=4)])
                boxes = [(100+i*120, 390, 100, 100) for i in range(5)]
                members = [dict(name=f'合成角色{i}', rectangle=list(b), score=.99) for i, b in enumerate(boxes)]
                index = SimpleNamespace(names=[m['name'] for m in members], matrix=np.ones((5,1728),np.float32))
                capture = Mock()
                capture.read.side_effect = [(True, np.full((540,960,3), i*20, np.uint8)) for i in range(6)]
                detail = texts('前哨关卡', '高难') if kind == 'outpost' else texts(
                    'BOSS详情', '高难', '合成首领', '80000000/80000000')
                labels = [texts(constraint)]*2+[detail]*2+[
                    texts(timer, '79000000/80000000') for timer in ('1:29', '1:28')]
                with patch('pcrscript.tasks.strategy_video.cv.VideoCapture', return_value=capture), \
                     patch('pcrscript.tasks.strategy_video.sample_seconds', side_effect=[[.5,1.5],[.5,1.5,2.5,3.5]]), \
                     patch('pcrscript.tasks.strategy_video.frame_texts', side_effect=labels), \
                     patch('pcrscript.tasks.strategy_video.battle_rectangles', side_effect=[[]]*4+[boxes]*2), \
                     patch('pcrscript.tasks.strategy_video.combat_team', side_effect=[[]]*4+[members]*2), \
                     patch('pcrscript.tasks.strategy_video.formation_fields', return_value=[]), \
                     patch('pcrscript.tasks.strategy_video.combat_auto', return_value=True), \
                     patch('pcrscript.tasks.strategy_video.combat_set', return_value=True):
                    report = parse_video_source(source, options, index, api=Mock(), ocr=Mock(),
                        media_fetcher=lambda *a, **k: (Path(folder)/'synthetic.avi',dict(duration=4)))
                self.assertEqual(len(report['parties']), 1)
                self.assertEqual(len(parties_for_target(report, options, allow_local_trials=True)), eligible)
                if not eligible:
                    rows = report['parties'][0]['global_requirements']+report['parties'][0]['manual_actions']
                    self.assertTrue(any(r['text'] == constraint and r['evidence']['cid'] == 1 for r in rows))

    def test_metadata_rejects_old_month_other_talent_or_unknown_publication(self):
        options = source_options({}, EVENT)
        source = dict(title='公主连结 国服2026年10月水属性深渊讨伐战', published_at=START+100)
        self.assertIsNone(source_rejection(source, options))
        for change in (dict(published_at=START-8*86400), dict(published_at=None),
                       dict(title='公主连结2026年9月水属性深渊讨伐战'),
                       dict(title='公主连结10月火属性深渊讨伐战')):
            self.assertIsNotNone(source_rejection(dict(source, **change), options))
        self.assertIn('10月', queries(options)[0])
        self.assertEqual(options['event_id'], 123)
        self.assertEqual(options['parse_timeout'], 1800)
        self.assertEqual(source_options({}, EVENT, kind='boss')['parse_timeout'], 300)
        self.assertEqual(source_options({'sources': {'parse_timeout': 600}}, EVENT,
                                        kind='boss')['parse_timeout'], 600)

    def test_front_pages_retain_original_labels_without_assigning_high_tier(self):
        source = dict(pages=[dict(cid=i, part=p) for i, p in enumerate(
            ('[Boss 1]全自动', '前哨打法1', '前哨打法2', '属性练度'))])
        pages = choose_pages(source, source_options({}, EVENT))
        self.assertEqual([p['part'] for p in pages], ['属性练度', '前哨打法1', '前哨打法2'])
        self.assertEqual(visible_scope([], pages[1], {}), ({}, False))
        self.assertEqual(visible_scope(texts('前哨关卡', '高难'), pages[1], {}),
                         (dict(kind='outpost', difficulty='高难'), True))
        self.assertEqual(visible_scope(texts('前哨关卡', '普通'), dict(part='前哨高难'), {}),
                         ({'conflict': True}, False))
        self.assertEqual(visible_scope(texts('BOSS详情', '高难', '合成首领等级100'),
                                       dict(part='Boss1全自动'), dict(boss='合成首领')),
                         (dict(kind='boss', difficulty='高难', boss='合成首领'), True))

    def test_numbered_parts_prioritize_the_current_boss_without_proving_identity(self):
        source = dict(pages=[dict(cid=i, part=p) for i, p in enumerate(
            ('1王方案一', '1王方案二', '1王方案三', '1王方案四', '[Boss 2]全自动', '2王备用', '3王方案一'))])
        options = source_options({}, EVENT, kind='boss', boss='合成首领', boss_number=2)
        pages = choose_pages(source, options)
        self.assertEqual([p['part'] for p in pages], ['[Boss 2]全自动', '2王备用'])
        self.assertEqual(visible_scope([], pages[0], options), ({}, False))
        self.assertEqual(visible_scope(texts('BOSS详情', '高难', '别的首领等级475'), pages[0], options), ({}, False))

    def test_common_notes_survive_named_and_numbered_boss_selection(self):
        for target in ('合成首领打法1', 'Boss2打法1'):
            with self.subTest(target=target):
                source = dict(pages=[dict(cid=i, part=title) for i, title in enumerate((
                    'Boss通用说明', '2王注意事项', '3王培养要求', '前哨注意事项', target))])
                options = source_options({}, EVENT, kind='boss', boss='合成首领', boss_number=2)
                pages = choose_pages(source, options)
                self.assertEqual([p['part'] for p in pages], ['Boss通用说明', '2王注意事项', target])

    def test_requirement_page_budget_blocks_the_source_instead_of_truncating_notes(self):
        pages = [dict(cid=i, part='通用说明'+str(i), duration=2) for i in range(1, 5)]
        pages.append(dict(cid=5, part='Boss1打法1', duration=4))
        source = dict(pages=pages)
        options = source_options({}, EVENT, kind='boss', boss='合成首领', boss_number=1)
        with self.assertRaisesRegex(ValueError, 'max_pages_per_video=4'):
            choose_pages(source, options)
        self.assertEqual([p['cid'] for p in choose_pages(source, dict(options, max_pages_per_video=5))],
                         [1, 2, 3, 4, 5])
        with TemporaryDirectory() as folder:
            options['parsed_dir'] = folder
            api = Mock()
            api.getVideoInfo.return_value = dict(code=0, data=dict(bvid='BVSYNTHETIC',
                title='公主连结10月水属性深渊讨伐战', desc='-', pubdate=START+100, pages=pages))
            with patch('pcrscript.tasks.strategy_video.discover_sources', return_value=dict(candidates=[dict(bvid='BVSYNTHETIC')])), \
                 patch('pcrscript.tasks.strategy_video.preferred_sources', return_value=([], [])), \
                 patch('pcrscript.tasks.strategy_video.parse_video_source') as parse:
                report = acquire_strategies(options, api=api, index=Mock())
            self.assertEqual(report['status'], 'blocked')
            self.assertEqual(report['parties'], [])
            self.assertTrue(any('max_pages_per_video=4' in e['error'] for e in report['errors']))
            parse.assert_not_called()

    def test_unread_or_truncated_common_notes_cannot_authorize_a_parsed_combat_party(self):
        for failure in ('download', 'unknown_notes', 'duration_skip', 'truncated', 'empty', 'partial', 'aspect', 'ocr_empty'):
            with self.subTest(failure=failure), TemporaryDirectory() as folder:
                options = source_options({}, EVENT)
                options.update(parsed_dir=folder, skip_long_media=failure != 'truncated')
                source = dict(bvid='BVSYNTHETIC', url='https://example.com/synthetic',
                    title='公主连结 国服 合成深渊', pages=[
                        dict(cid=1, part='前哨其他信息' if failure == 'unknown_notes' else '通用说明',
                             duration=601 if failure in ('duration_skip', 'truncated') else 2),
                        dict(cid=2, part='前哨打法1', duration=4)])
                boxes = [(100+i*120, 390, 100, 100) for i in range(5)]
                members = [dict(name=f'合成角色{i}', rectangle=list(b), score=.99) for i, b in enumerate(boxes)]
                index = SimpleNamespace(names=[m['name'] for m in members], matrix=np.ones((5,1728),np.float32))
                frames = [(True, np.full((540,960,3), i*20, np.uint8)) for i in range(6)]
                note_frames = {'download': [], 'unknown_notes': [], 'duration_skip': [], 'truncated': frames[:2], 'ocr_empty': frames[:2],
                    'empty': [(False, None)]*2, 'partial': [frames[0], (False, None)],
                    'aspect': [(True, np.zeros((540,2000,3), np.uint8))]*2}[failure]
                readable = 2 if failure in ('truncated', 'ocr_empty') else 1 if failure == 'partial' else 0
                capture = Mock()
                capture.read.side_effect = note_frames+frames[2:]
                labels = [[] if failure == 'ocr_empty' else texts('说明正文')]*readable+[texts('前哨关卡', '高难')]*2+[
                    texts('1:29'), texts('1:28')]
                def fetch(api, bvid, page, *args, **kwargs):
                    if failure in ('download', 'unknown_notes') and page['cid'] == 1:
                        raise OSError('synthetic download failure')
                    return Path(folder)/'synthetic.avi', dict(duration=page['duration'])
                with patch('pcrscript.tasks.strategy_video.cv.VideoCapture', return_value=capture), \
                     patch('pcrscript.tasks.strategy_video.sample_seconds', side_effect=lambda duration, *a, **k: [.5,1.5,2.5,3.5] if duration == 4 else [.5,1.5]), \
                     patch('pcrscript.tasks.strategy_video.frame_texts', side_effect=labels), \
                     patch('pcrscript.tasks.strategy_video.battle_rectangles', side_effect=[[]]*(readable+2)+[boxes]*2), \
                     patch('pcrscript.tasks.strategy_video.combat_team', side_effect=[[]]*(readable+2)+[members]*2), \
                     patch('pcrscript.tasks.strategy_video.formation_fields', return_value=[]), \
                     patch('pcrscript.tasks.strategy_video.combat_auto', return_value=True), \
                     patch('pcrscript.tasks.strategy_video.combat_set', return_value=True):
                    report = parse_video_source(source, options, index, api=Mock(), ocr=Mock(), media_fetcher=fetch)
                self.assertEqual(len(report['parties']), 1)
                self.assertEqual(parties_for_target(report, options, allow_local_trials=True), [])
                self.assertTrue(any(r['evidence']['cid'] == 1 and '未完整解析' in r['text']
                    for r in report['parties'][0]['global_requirements']))

    def test_boss_detail_accepts_separate_full_name_and_level_but_not_a_truncated_name(self):
        options = dict(boss='合成首领(多部位)')
        labels = texts('BOSS详情', '极难')+[
            GuideText(options['boss'], .99, (430, 300, 200, 25)),
            GuideText('等级:475', .9, (640, 300, 70, 25))]
        self.assertEqual(visible_scope(labels, {}, options),
            (dict(kind='boss', difficulty='极难', boss=options['boss']), True))
        labels[2] = GuideText('合成首领(多部', .99, (430, 300, 200, 25))
        self.assertEqual(visible_scope(labels, {}, options), ({}, False))

    def test_damage_reference_uses_only_the_verified_plan_and_preserves_evidence(self):
        scope = dict(kind='boss', boss='合成首领', difficulty='极难')
        page = dict(cid=1, part='【2王】全SET，3.7亿')
        reference = damage_reference(page, scope, 1000000000, 'https://example.com/synthetic')
        self.assertEqual(reference['damage'], 370000000)
        self.assertEqual(reference['scope'], scope)
        self.assertEqual(reference['evidence'][0]['text'], page['part'])
        for title, damage in (('一刀击杀', 1000000000), ('2刀击杀', 500000000),
                              ('三刀击杀', 333333334)):
            self.assertEqual(damage_reference(dict(page, part=title), scope, 1000000000, '')['damage'], damage)
        self.assertEqual(damage_reference(dict(page, part='三刀击杀'), scope, None, ''), {})
        self.assertEqual(damage_reference(dict(page, part='3亿或4亿'), scope, 1000000000, ''), {})
        self.assertEqual(damage_reference(page, dict(kind='outpost', difficulty='高难'), 1000000000, ''), {})
        raw = trial_report()['parties'][0]
        raw.update(scope=scope, damage_reference=reference)
        options = source_options({}, EVENT, kind='boss', boss='合成首领', difficulty='极难')
        candidate = parties_for_target(dict(parties=[raw]), options, allow_local_trials=True)[0]
        self.assertEqual(candidate.damage_reference, reference)
        self.assertEqual(candidate.allow_deaths, 0)

    def test_visible_front_detail_links_only_continuous_battle_countdown(self):
        context = ScopeContext()
        scope = dict(kind='outpost', difficulty='高难')
        proof = dict(source='https://example.com/synthetic', seconds=1)
        context.resolve(scope, True, texts('前哨关卡', '高难'), 1, False, proof)
        self.assertEqual(context.resolve({}, False, texts('1:29'), 4, True, proof)[:2], (scope, True))
        self.assertEqual(context.resolve({}, False, texts('1:20'), 8, True, proof)[:2], (scope, True))
        self.assertEqual(context.resolve({}, False, texts('1:30'), 10, True, proof)[:2], ({}, False))
        self.assertEqual(context.resolve({}, False, texts('1:10'), 12, True, proof)[:2], ({}, False))

    def test_boss_name_in_body_still_requires_detail_header_and_exact_difficulty(self):
        labels = texts('BOSS详情', '高难')+[
            GuideText('合成首领等级.475', 1, (440, 310, 180, 24))]
        options = dict(boss='合成首领')
        self.assertEqual(visible_scope(labels, dict(part='Boss1'), options),
                         (dict(kind='boss', difficulty='高难', boss='合成首领'), True))
        self.assertEqual(visible_scope(labels[1:], dict(part='Boss1'), options), ({}, False))
        labels[1] = GuideText('极难', 1, (240, 50, 100, 24))
        self.assertEqual(visible_scope(labels, dict(part='Boss1'), options),
                         (dict(kind='boss', difficulty='极难', boss='合成首领'), True))

    def test_higher_boss_source_keeps_its_tier_and_requires_explicit_account_trials(self):
        report = trial_report()
        raw = report['parties'][0]
        raw['scope'] = dict(kind='boss', difficulty='极难', boss='合成首领')
        options = source_options({}, EVENT, kind='boss', boss='合成首领')
        self.assertEqual(parties_for_target(report, options, allow_local_trials=False), [])
        candidates = parties_for_target(report, options, allow_local_trials=True)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].build_basis, 'local_trial')
        self.assertIn('极难', candidates[0].assumptions[-1])
        self.assertEqual(raw['scope']['difficulty'], '极难')
        exact = parties_for_target(report, dict(options, difficulty='极难'), allow_local_trials=True)
        self.assertEqual(len(exact), 1)
        self.assertFalse(any('极难' in note for note in exact[0].assumptions))
        self.assertEqual(parties_for_target(report, dict(options, boss='其他首领'),
                                           allow_local_trials=True), [])
        raw['global_requirements'] = [dict(text='合成未知装备要求')]
        self.assertEqual(parties_for_target(report, options, allow_local_trials=True), [])

    def test_scope_clears_on_result_unknown_transition_or_boss_hp_change(self):
        for transition in (texts('WIN!'), texts('别的页面')):
            context = ScopeContext()
            scope = dict(kind='outpost', difficulty='高难')
            context.resolve(scope, True, texts('前哨关卡'), 1, False, {})
            context.resolve({}, False, transition, 3, False, {})
            self.assertEqual(context.resolve({}, False, texts('1:29'), 4, True, {})[:2], ({}, False))
        context = ScopeContext()
        scope = dict(kind='boss', difficulty='高难', boss='合成首领')
        context.resolve(scope, True, texts('80000000/80000000'), 1, False, {})
        self.assertEqual(context.resolve({}, False, texts('80000000/90000000', '1:29'), 4, True, {})[:2], ({}, False))
        context.resolve(scope, True, texts('80,000,000/80,000,000'), 1, False, {})
        self.assertEqual(context.resolve({}, False, texts('79,000,000/80,000,000', '1:29'), 4, True, {})[:2], (scope, True))

    def test_brief_combat_hud_occlusion_skips_frame_without_losing_verified_detail(self):
        scope = dict(kind='boss', difficulty='极难', boss='合成首领')
        context = ScopeContext()
        context.resolve(scope, True, texts('80000000/80000000'), 1, False, {})
        self.assertEqual(context.resolve({}, False, texts('79000000/80000000', '1:29'), 4, True, {})[:2], (scope, True))
        self.assertEqual(context.resolve({}, False, texts('1:28'), 6, True, {})[:2], ({}, False))
        self.assertEqual(context.resolve({}, False, texts('78000000/80000000'), 7, True, {})[:2], ({}, False))
        self.assertEqual(context.resolve({}, False, texts('77000000/80000000', '1:25'), 9, True, {})[:2], (scope, True))
        self.assertEqual(context.resolve({}, False, texts('特效遮挡'), 18, True, {})[:2], ({}, False))
        self.assertEqual(context.resolve({}, False, texts('76000000/80000000', '1:20'), 19, True, {})[:2], ({}, False))

    def test_boss_hud_keeps_scope_when_ub_animation_hides_the_card_row(self):
        scope = dict(kind='boss', difficulty='极难', boss='合成首领')
        for identity, expected in (('合成首领', (scope, True)), ('另一个首领', ({}, False))):
            with self.subTest(identity=identity):
                context = ScopeContext()
                context.resolve(scope, True, texts('80000000/80000000'), 1, False, {})
                context.resolve({}, False, texts('79000000/80000000', '1:29'), 4, True, {})
                result = context.resolve({}, False, texts(identity, '78000000/80000000', '1:28'), 6, False, {})
                self.assertEqual(result[:2], expected)

    def test_targeted_source_conditions_do_not_apply_to_other_bosses_or_outposts(self):
        statement = '共同要求大师点\n3王需要等级突破\n前哨需要特别装备'
        self.assertEqual(relevant_statements(statement, dict(kind='boss', boss_number=1)), '共同要求大师点')
        self.assertEqual(relevant_statements(statement, dict(kind='boss', boss_number=3)), '共同要求大师点\n3王需要等级突破')
        self.assertEqual(relevant_statements(statement, dict(kind='outpost')), '共同要求大师点\n前哨需要特别装备')
        self.assertIn('等级突破', relevant_statements(statement, dict(kind='boss')))

    def test_standard_formation_equipment_dialog_keeps_detail_but_not_an_unknown_page(self):
        scope = dict(kind='boss', difficulty='极难', boss='合成首领')
        context = ScopeContext()
        context.resolve(scope, True, texts('80000000/80000000'), 1, False, {})
        self.assertEqual(context.resolve({}, False, texts('特别装备设定', '可变更队伍角色的特别装备。'), 3, False, {})[:2], (scope, True))
        self.assertEqual(context.resolve({}, False, texts('未知装备页'), 4, False, {})[:2], ({}, False))

    def test_trial_requires_cn_exact_scope_fixed_settings_and_no_unsupported_conditions(self):
        options = source_options({}, EVENT)
        report = trial_report()
        candidates = parties_for_target(report, options, allow_local_trials=True)
        self.assertEqual(len(candidates), 1)
        self.assertIs(candidates[0].auto, False)
        self.assertIs(candidates[0].members[0].instant, False)
        self.assertIsNone(candidates[0].members[0].stars)
        self.assertEqual(parties_for_target(report, options, allow_local_trials=False), [])
        for field, value in (('region', 'unknown'), ('scope_verified', False),
                             ('global_requirements', [{'text': '合成未核验条件'}]),
                             ('manual_actions', [{'text': '合成手动轴'}])):
            with self.subTest(field=field):
                raw = dict(report['parties'][0], **{field: value})
                self.assertEqual(parties_for_target(dict(parties=[raw]), options, allow_local_trials=True), [])
        raw = report['parties'][0]
        raw['members'][0]['instant']['conflicts'] = [dict(value=True)]
        self.assertEqual(parties_for_target(report, options, allow_local_trials=True), [])

    def test_live_trial_preserves_source_switches_and_known_six_star_requirement(self):
        seed = parties_for_target(trial_report(), source_options({}, EVENT), allow_local_trials=True)[0]
        current = EventParty('synthetic-current', '游戏合成队伍',
            [MemberRequirement(m.name, 100, 10, 5, True, False, True, 100) for m in seed.members],
            build_basis='local_trial')
        order = [m.name for m in current.members]
        runner = SimpleNamespace(formation=Mock(), report_progress=Mock(), report={}, check_deadline=Mock(), event=EVENT, options={}, save=Mock())
        with patch('pcrscript.tasks.subjugation_party.prepare_avatars'), \
             patch('pcrscript.tasks.subjugation_party.require_event_talent'), \
             patch.object(runner.formation, 'source_trial', return_value=(current, {'order':order, 'observed':[asdict(CharacterStatus(m.name, **{key:getattr(m,key) for key in ('level','rank','stars','skill_level','unique','unique2')}, identity_verified=True)) for m in current.members]})):
            party, actual_order = guide_party(runner, seed, Mock())
            self.assertEqual(actual_order, order)
            self.assertIs(party.auto, False)
            self.assertIs(party.members[0].instant, False)
            self.assertEqual(party.source, seed.source)
            seed.members[0].stars = 6
            with self.assertRaisesRegex(EventUIError, '攻略要求不符'):
                guide_party(runner, seed, Mock())

    def test_shared_trial_replacement_keeps_audited_build_instead_of_absent_units_requirements(self):
        seed = parties_for_target(trial_report(), source_options({}, EVENT), allow_local_trials=True)[0]
        seed.members[0].stars = 6
        seed.damage_reference = dict(damage=40000000, scope=dict(kind='boss', boss='合成首领'),
                                     evidence=[dict(source='https://example.com/synthetic')])
        names = ['合成替补']+[m.name for m in seed.members[1:]]
        current = EventParty('synthetic-adapted', '游戏合成队伍',
            [MemberRequirement(n, 100, 10, 5, True, False, i != 0, 100) for i, n in enumerate(names)],
            build_basis='local_trial')
        def trial(stage, source):
            source['names'][0] = names[0]
            source['adaptations'] = [dict(missing=seed.members[0].name, replacement=names[0], reason='合成同属性同职能依据')]
            return current, dict(order=names, observed=[asdict(CharacterStatus(m.name,
                **{key:getattr(m,key) for key in ('level','rank','stars','skill_level','unique','unique2')},
                identity_verified=True)) for m in current.members])
        runner = SimpleNamespace(formation=Mock(), report_progress=Mock(), report={}, check_deadline=Mock(), event=EVENT, options={}, save=Mock())
        with patch('pcrscript.tasks.subjugation_party.prepare_avatars'), \
             patch('pcrscript.tasks.subjugation_party.require_event_talent'), \
             patch.object(runner.formation, 'source_trial', side_effect=trial):
            party, order = guide_party(runner, seed, Mock())
            self.assertEqual(order, names)
            self.assertEqual(party.members[0].stars, 5)
            self.assertIs(party.members[0].instant, False)
            self.assertTrue(any('合成替补' in note for note in party.assumptions))
            self.assertEqual(party.damage_reference, {})
            self.assertEqual(seed.damage_reference['damage'], 40000000)
