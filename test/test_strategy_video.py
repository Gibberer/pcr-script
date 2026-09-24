"""Synthetic source/media evidence; no real guide or account fixtures."""
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import cv2 as cv
import numpy as np

from pcrscript.game_ui.avatars import AvatarIndex, face_crop
from pcrscript.game_ui.avatar_assets import ensure_avatar_index
from pcrscript.game_ui.guide_vision import GuideText, combat_team, formation_team, wide_special_equipment_team, combat_set, combat_auto, labeled_fields, formation_fields
from pcrscript.tasks.strategy_document import Evidence, empty_member, finalize, to_event_party, abyss_candidate, event_parties, event_trial_parties, dungeon_plan
from pcrscript.tasks.strategy_video import choose_pages, observed_scope, parse_video_source, acquire_strategies, task_source_options, texts_in_view, sample_seconds, frame_texts
from pcrscript.tasks.strategy_party_pool import boss_parties, next_boss_party
from pcrscript.tasks.strategy_trial import TrialFormation
from pcrscript.tasks.event_strategy import CharacterStatus
from pcrscript.tasks.task_abyss import AbyssPush, source_for_stage
from pcrscript.tasks.abyss_party import AbyssFormation
from pcrscript.tasks.task_dungeon import DungeonFirstClear
from pcrscript.game_ui.abyss import AbyssStage


def complete_party():
    members = [empty_member('角色'+str(i)) for i in range(5)]
    for member in members:
        for key, value in dict(level=100, rank=10, stars=5, unique=True, unique2=False,
                               skill_level=100, instant=True).items():
            member[key].add(value, Evidence('https://example.com/synthetic', method='synthetic'))
    return finalize(dict(source='https://example.com/synthetic', scope=dict(element='fire', stage='4-1', chapters=[4,4]),
                         scope_verified=True, region='cn', target_region='cn', members=members,
                         auto=dict(value=True,evidence=[dict(method='synthetic')],conflicts=[])))


class VideoStrategyTests(TestCase):
    def test_wide_video_samples_brief_formation_and_equipment_screens(self):
        samples = sample_seconds(96, 50, wide=True)
        self.assertIn(2.0, samples)
        self.assertIn(3.5, samples)
        self.assertLessEqual(len(samples), 50)
        self.assertNotIn(2.0, sample_seconds(96, 50))

    def test_identical_frame_reuses_ocr_only_with_saved_image(self):
        with TemporaryDirectory() as folder,patch('pcrscript.tasks.strategy_video.read_text',
                return_value=[GuideText('队伍编组',1,(1,2,3,4))]) as read:
            image=Path(folder)/'frame.jpg'
            frame=np.zeros((720,1280,3),np.uint8)
            self.assertEqual(frame_texts(frame,image,Mock())[0].text,'队伍编组')
            self.assertEqual(frame_texts(frame,image,Mock())[0].text,'队伍编组')
            self.assertEqual(read.call_count,1)
            frame[0,0]=255
            frame_texts(frame,image,Mock())
            self.assertEqual(read.call_count,2)
            image.unlink()
            frame_texts(frame,image,Mock())
            self.assertEqual(read.call_count,3)

    def test_wide_combat_projects_set_labels_into_cropped_view(self):
        labels = [GuideText('立即', 1, (413, 514, 33, 17)),
                  GuideText('发动', 1, (413, 528, 34, 23))]
        projected = texts_in_view(labels, 1280, 115, 1049)
        view = np.zeros((540, 960, 3), np.uint8)
        view[382:418, 270:314] = (255, 180, 0)
        self.assertTrue(combat_set(view, {'rectangle': (196, 396, 89, 89)}, projected))
        self.assertIsNone(combat_set(view, {'rectangle': (316, 396, 89, 89)}, projected))

    def test_formation_roster_requires_page_labels_and_five_distinct_portraits(self):
        with TemporaryDirectory() as directory:
            index = AvatarIndex(directory, load_existing=False)
            image = np.zeros((540, 960, 3), dtype=np.uint8)
            expected = [f'合成角色{i}' for i in range(5)]
            for i, name in enumerate(expected):
                box = (96+109*i-48, 405, 96, 96)
                patch = np.random.default_rng(i+1).integers(0, 256, (48, 62, 3), dtype=np.uint8)
                x, y, w, h = box
                image[y+round(h*.23):y+round(h*.73), x+round(w*.18):x+round(w*.82)] = patch
                index.add(name, patch, persist=False)
            labels = [GuideText('队伍编组', .99, (0, 0, 80, 20)),
                      GuideText('当前的成员', .99, (0, 0, 80, 20))]
            self.assertEqual([row['name'] for row in formation_team(image, labels, index)], expected)
            self.assertEqual(formation_team(image, labels[:1], index), [])
            image[427:475, 501:563] = image[427:475, 392:454]
            self.assertEqual(formation_team(image, labels, index), [])

    def test_wide_special_equipment_roster_requires_dialog_and_distinct_portraits(self):
        with TemporaryDirectory() as directory:
            index = AvatarIndex(directory, load_existing=False)
            image = np.zeros((540, 960, 3), dtype=np.uint8)
            expected = [f'合成角色{i}' for i in range(5)]
            boxes = [(round(88+178.5*i), 108, 72, 72) for i in range(5)]
            for i, (name, (x, y, w, h)) in enumerate(zip(expected, boxes)):
                patch = np.random.default_rng(i+51).integers(0, 256, (36, 46, 3), dtype=np.uint8)
                image[y+round(h*.23):y+round(h*.73), x+round(w*.18):x+round(w*.82)] = patch
                index.add(name, patch, persist=False)
            labels = [GuideText('特别装备设定', .99, (0, 0, 80, 20)),
                      GuideText('可变更队伍角色的特别装备。', .99, (0, 0, 160, 20))]
            self.assertEqual([row['name'] for row in wide_special_equipment_team(image, labels, index)], expected)
            self.assertEqual(wide_special_equipment_team(image, labels[:1], index), [])
            x, y, w, h = boxes[-1]
            x0, y0, _, _ = boxes[-2]
            image[y+round(h*.23):y+round(h*.73), x+round(w*.18):x+round(w*.82)] = image[y0+round(h*.23):y0+round(h*.73), x0+round(w*.18):x0+round(w*.82)]
            self.assertEqual(wide_special_equipment_team(image, labels, index), [])

    def test_fields_never_default_and_weapon_stars_are_not_rarity(self):
        self.assertEqual(labeled_fields(''), {})
        self.assertEqual(labeled_fields('专310'), {'unique': True})
        self.assertEqual(labeled_fields('专武2:5星'), {'unique2': True})
        self.assertEqual(labeled_fields('5星 Lv100 Rank10 技能100 专武1有 专武2无 SET关'),
                         dict(stars=5, level=100, rank=10, skill_level=100, unique=True, unique2=False, instant=False))
        self.assertNotIn('level', labeled_fields('属性等级180'))

    def test_conflict_survives_later_repeated_observations(self):
        member = empty_member('角色')
        for value in (True, False, True):
            member['unique'].add(value, Evidence('synthetic', seconds=float(value)))
        self.assertIsNone(member['unique'].value)
        self.assertEqual(len(member['unique'].conflicts), 3)
        party = complete_party()
        party['members'][0]['unique'] = asdict(member['unique'])
        with self.assertRaises(ValueError): to_event_party(party)

    def test_ready_conversion_preserves_source_and_exact_stage(self):
        party = complete_party()
        self.assertEqual(to_event_party(party).members[0].unique2, False)
        candidate = abyss_candidate(party)
        self.assertIs(source_for_stage([candidate], AbyssStage('fire',4,1),set(),[]), candidate)
        self.assertIsNone(source_for_stage([candidate], AbyssStage('fire',4,2),set(),[]))
        alias=dict(party,members=[dict(party['members'][0],name='涅妃＝涅菈'),*party['members'][1:]])
        self.assertEqual(abyss_candidate(alias)['names'][0],'涅妃=涅菈')
        for key, value in [('global_requirements', [{'text':'属性等级99'}]), ('manual_actions',[{'text':'手动'}]), ('region','jp')]:
            with self.subTest(key=key), self.assertRaises(ValueError): to_event_party(dict(party, **{key:value}))

    def test_exact_incomplete_abyss_roster_only_seeds_authorized_auto_trial(self):
        stage = AbyssStage('fire', 5, 2)
        document = finalize(dict(source='https://example.com/5-2',
            scope=dict(element='fire', stage='5-2', chapters=[5, 5]),
            scope_verified=True, region='unknown', target_region='cn',
            members=[empty_member('角色'+str(i)) for i in range(5)],
            identity_evidence=[dict(name='角色'+str(i), cid=1, seconds=second)
                               for i in range(5) for second in (1.0, 2.0)],
            auto=dict(value=None, evidence=[], conflicts=[]),
            manual_actions=[], global_requirements=[]))
        candidate = abyss_candidate(document)
        self.assertIsNone(source_for_stage([candidate], stage, set(), []))
        self.assertIs(source_for_stage([candidate], stage, set(), [], allow_local_trials=True), candidate)
        self.assertIsNone(source_for_stage([abyss_candidate(dict(document,identity_evidence=[]))],
                                           stage, set(), [], allow_local_trials=True))
        for change in (dict(manual_actions=[{'text':'半自动'}]),
                       dict(global_requirements=[{'text':'属性等级750'}]),
                       dict(scope_verified=False), dict(region='jp'),
                       dict(auto=dict(value=False, evidence=[], conflicts=[]))):
            with self.subTest(change=change):
                rejected = abyss_candidate(dict(document, **change))
                self.assertIsNone(source_for_stage([rejected], stage, set(), [], allow_local_trials=True))

        class TrialStub(AbyssFormation):
            def source_trial(self, stage, source, *, recover=True):
                if not source.get('document'):
                    self.trial_source = source
                    return object(), {'order': source['names']}
                return super().source_trial(stage, source, recover=recover)

        stub = object.__new__(TrialStub)
        party, audit = stub.source_trial(stage, candidate)
        self.assertIsNotNone(party)
        self.assertEqual(stub.trial_source['instant'], [True]*5)
        self.assertEqual(audit['build_basis'], 'local_trial_source_roster')
        self.assertEqual(len([a for a in audit['assumptions'] if 'SET未知' in a]), 5)

    def test_part_selection_and_contradictory_stage(self):
        source = dict(title='测试', pages=[dict(cid=1,part='练度要求'),dict(cid=2,part='水4-1'),dict(cid=3,part='火4-1')])
        self.assertEqual([p['cid'] for p in choose_pages(source,dict(task_type='abyss',stage='4-1',element='fire',max_pages_per_video=2))],[1,3])
        self.assertFalse(observed_scope([GuideText('火4-2',1,(0,0,10,10))], source['pages'][2], 'abyss')[1])

    def test_abyss_compilation_pages_require_visible_target_scope(self):
        source = dict(title='公主连结 国服深域1-7图合集', pages=[
            dict(cid=1,part='国服深域1-7图合集'), dict(cid=2,part='风7-10 全自动')])
        options = dict(task_type='abyss',stage='5-1',element='fire')
        self.assertEqual([p['cid'] for p in choose_pages(source,options)],[1])
        self.assertEqual(observed_scope([GuideText('火5-1',.99,(0,0,10,10))],source['pages'][0],'abyss'),
                         (dict(element='fire',stage='5-1',chapters=[5,5]),True))
        self.assertEqual(observed_scope([],source['pages'][0],'abyss'),({},False))
        self.assertEqual(choose_pages(dict(source,title='公主连结 水深域1-7图'),options),[])
        exact=dict(title='公主连结 红焰深域 火5-1至5-10',pages=[dict(cid=3,part='5-1'),dict(cid=4,part='5-2')])
        chosen=choose_pages(exact,options)
        self.assertEqual([p['cid'] for p in chosen],[3])
        self.assertEqual(chosen[0]['original_part'],'5-1')
        cut=dict(exact,pages=[dict(cid=3,part='5-1'),dict(cid=4,part='5-6（改星')])
        cut_options=dict(options,stage='5-6')
        self.assertEqual([p['cid'] for p in choose_pages(cut,cut_options)],[4])
        self.assertEqual(observed_scope([],chosen[0],'abyss'),
                         (dict(element='fire',stage='5-1',chapters=[5,5]),True))
        manual=dict(exact,pages=[dict(cid=5,part='5-1（半自动）')])
        self.assertEqual(choose_pages(manual,options)[0]['original_part'],'5-1（半自动）')

    def test_chapter_range_parts_are_not_mistaken_for_exact_stages(self):
        source=dict(title='公主连结 水深域1-7图作业一图流',pages=[
            dict(cid=1,part='6-7'),dict(cid=2,part='1-5')])
        options=dict(task_type='abyss',element='water',stage='3-6')
        self.assertEqual([p['cid'] for p in choose_pages(source,options)],[2])
        self.assertEqual([p['cid'] for p in choose_pages(source,dict(options,stage='6-7'))],[1])
        self.assertEqual([p['cid'] for p in choose_pages(source,dict(options,stage='1-5'))],[2])
        self.assertEqual(choose_pages(source,dict(options,stage='8-1')),[])
        self.assertEqual(observed_scope([],source['pages'][1],'abyss'),({},False))
        self.assertEqual(observed_scope([GuideText('公主连结简中服水深域1-5图参考作业',1,(0,0,200,25))],
                                        source['pages'][1],'abyss'),({},False))

    def test_event_scope_rejects_other_modes_and_incomplete_build(self):
        options = task_source_options('revival', {'source_urls': []},
            area='合成活动', difficulty='special', mode=2)
        self.assertEqual((options['area'], options['difficulty'], options['mode']),
                         ('合成活动', 'special', 2))
        pages = [dict(cid=1, part='特别战斗 模式1'), dict(cid=2, part='特别战斗 模式2'),
                 dict(cid=3, part='高难 模式2')]
        self.assertEqual([p['cid'] for p in choose_pages(dict(title='合成活动', pages=pages),
                         dict(options, max_pages_per_video=2))], [2])
        self.assertFalse(observed_scope([GuideText('特别战斗 模式1', 1, (0,0,10,10))],
            pages[1], 'revival')[1])
        party = complete_party()
        party['scope'] = dict(area='合成活动', difficulty='special', mode=2)
        report = dict(parties=[party])
        self.assertEqual(len(event_parties(report, '合成活动', 'special', 2)), 1)
        self.assertEqual(event_parties(report, '合成活动', 'special', 1), [])
        party['members'][0]['unique']['value'] = None
        self.assertEqual(event_parties(report, '合成活动', 'special', 2), [])
        trials = event_trial_parties(report, '合成活动', 'special', 2)
        self.assertEqual(len(trials), 1)
        self.assertEqual(trials[0].build_basis, 'local_trial')
        self.assertEqual(trials[0].max_attempts, 1)
        self.assertEqual(event_trial_parties(report, '合成活动', 'special', 1), [])
        formation = object.__new__(TrialFormation)
        formation.use_current_build = True
        self.assertEqual(formation.member_readiness(trials[0].members[0],
            CharacterStatus(trials[0].members[0].name, identity_verified=True)), [])
        self.assertTrue(formation.member_readiness(trials[0].members[0],
            CharacterStatus('别的角色', identity_verified=False)))

    def test_boss_pool_searches_by_default_and_local_requires_opt_in(self):
        party = complete_party()
        party['scope'] = dict(area='合成活动', difficulty='special', mode=2)
        with patch('pcrscript.tasks.strategy_party_pool.load_parties', return_value=[to_event_party(party)]) as local, \
             patch('pcrscript.tasks.strategy_party_pool.acquire_strategies', return_value=dict(parties=[party])) as acquire:
            found, report = boss_parties({'discover_sources': False, 'use_local_teams': True}, kind='revival', area='合成活动', difficulty='special',
                mode=2, default_path='unused.yml')
            self.assertEqual(len(found), 1)
            self.assertIsNone(report)
            acquire.assert_not_called()
            attempts = {(2, found[0].name): found[0].max_attempts}
            self.assertIsNone(next_boss_party(found, attempts, 2))
            found, report = boss_parties({}, kind='revival', area='合成活动', difficulty='special',
                mode=2, default_path='unused.yml')
            self.assertGreaterEqual(len(found), 2)
            self.assertEqual(found[0].build_basis, 'source')
            self.assertEqual(found[1].build_basis, 'local_trial')
            self.assertIsNotNone(report)
            acquire.assert_called_once()
            local.assert_called_once()

    def test_trial_pool_adds_role_substitution_without_claiming_ownership(self):
        party = complete_party()
        party['scope'] = dict(area='合成活动', difficulty='special', mode=2)
        party['members'][0]['unique']['value'] = None
        alternate = dict(order=['替补']+[m['name'] for m in party['members'][1:]],
                         outgoing='角色0', incoming='替补', reason='技能职责替补')
        with patch('pcrscript.tasks.strategy_party_pool.acquire_strategies', return_value=dict(parties=[party])), \
             patch('pcrscript.tasks.strategy_party_pool.AvatarIndex', return_value=SimpleNamespace(names=['替补'])), \
             patch('pcrscript.tasks.strategy_party_pool.character_roles', return_value={'替补': {}}), \
             patch('pcrscript.tasks.strategy_party_pool.alternatives', return_value=[alternate]):
            found, _ = boss_parties({}, kind='event', area='合成活动', difficulty='special',
                                    mode=2, default_path='unused.yml')
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0].build_basis, 'local_trial')
        self.assertEqual(found[1].members[0].name, '替补')
        self.assertIn('账号实时核验可用性', found[1].assumptions[-1])

    def test_dungeon_can_build_same_source_trial_route_from_partial_video(self):
        parties = []
        for group, (floor, phase) in enumerate([(1,''),(2,''),(3,''),(4,''),
                                                  (5,'春'),(5,'夏'),(5,'秋'),(5,'冬')]):
            members = [empty_member(f'角色{group}-{i}') for i in range(5)]
            parties.append(finalize(dict(source='https://example.com/synthetic',
                scope=dict(area='四彩的灵峰', floor=floor, phase=phase), scope_verified=True,
                region='unknown', target_region='cn', members=members, auto={})))
        self.assertEqual(dungeon_plan(dict(parties=parties), '四彩的灵峰'), [])
        route = dungeon_plan(dict(parties=parties), '四彩的灵峰', allow_local_trials=True)
        self.assertEqual(len(route), 8)
        self.assertTrue(all(entry.use_current_build for entry in route))
        parties[-1]['scope_verified'] = False
        self.assertEqual(dungeon_plan(dict(parties=parties), '四彩的灵峰',
                                      allow_local_trials=True), [])

    def test_dungeon_part_titles_support_textless_multi_page_route(self):
        options = task_source_options('dungeon', {})
        self.assertGreaterEqual(options['max_pages_per_video'], 8)
        pages = [dict(cid=i+1, part=title) for i, title in enumerate(
            ['第1层','第2层','第3层','第4层','四色妖狐·春',
             '四色妖狐·夏','四色妖狐·秋','四色妖狐·冬'])]
        self.assertEqual(len(choose_pages(dict(pages=pages), options)), 8)
        self.assertEqual(observed_scope([], pages[0], 'dungeon'),
                         (dict(floor=1, phase=''), True))
        self.assertEqual(observed_scope([], pages[4], 'dungeon'),
                         (dict(floor=5, phase='四色妖狐·春'), True))

    def test_synthetic_combat_identity_and_blank_rejection(self):
        with TemporaryDirectory() as folder:
            index = AvatarIndex(folder)
            frame = np.zeros((540,960,3),np.uint8)
            rng = np.random.default_rng(51)
            for i in range(5):
                x,y=191+i*120,392
                card = cv.resize(rng.integers(0,256,(12,12,3),np.uint8),(100,100),interpolation=cv.INTER_NEAREST)
                frame[y:y+100,x:x+100]=card
                cv.rectangle(frame,(x,y),(x+99,y+99),(255,255,0),3)
                index.add('角色'+str(i),face_crop(frame,(x,y,100,100)),persist=False)
            self.assertEqual([m['name'] for m in combat_team(frame,index)],['角色'+str(i) for i in range(5)])
            self.assertEqual(combat_team(np.zeros_like(frame),index),[])
            self.assertEqual(formation_fields(frame,[],index,Mock()),[])

    def test_split_set_label_and_no_absence_inference(self):
        image = np.zeros((540,960,3),np.uint8)
        image[378:420,270:310]=(255,220,0)
        member=dict(rectangle=[190,392,100,100])
        texts=[GuideText('立即',.99,(277,382,27,15)),GuideText('发动',.99,(277,397,27,15))]
        self.assertTrue(combat_set(image,member,texts))
        self.assertIsNone(combat_set(image,member,[]))
        labels=[GuideText('自动',1,(897,405,40,24))]
        image[400:435,890:945]=(255,220,0)
        self.assertTrue(combat_auto(image,labels))
        image[400:435,890:945]=255
        self.assertFalse(combat_auto(image,labels))
        self.assertIsNone(combat_auto(image,[]))

    def test_empty_avatar_bootstrap_cache_and_expired_revalidation(self):
        with TemporaryDirectory() as folder:
            http=Mock()
            image=np.random.default_rng(5).integers(0,255,(100,100,3),np.uint8)
            raw=cv.imencode('.webp',image)[1].tobytes()
            listing=Mock(text='100111.webp 100131.webp 100211.webp',status_code=200)
            def get(url,**kwargs):
                if url.endswith('/'):return listing
                return Mock(content=raw,status_code=200,headers={'ETag':'v1'})
            http.get.side_effect=get
            options=dict(directory=folder,database=str(Path(folder)/'test.db'))
            with patch('pcrscript.game_ui.avatar_assets.ensure_database',return_value={'version':1}), patch('pcrscript.game_ui.avatar_assets.identities',return_value={1001:'角色A',1002:'角色B'}):
                index,report=ensure_avatar_index(options,http=http)
                self.assertTrue(report['complete']);self.assertEqual(set(index.names),{'角色A','角色B'})
                calls=http.get.call_count
                self.assertTrue(ensure_avatar_index(options,http=http)[1]['cache_hit'])
                self.assertEqual(http.get.call_count,calls)
                ensure_avatar_index(dict(options,max_age_hours=0),http=http)
                self.assertEqual(http.get.call_args.kwargs['headers'],{'If-None-Match':'v1'})

    def test_formal_prepare_does_not_create_robot(self):
        report=dict(status='partial',parties=[],pending=['缺失培养'])
        with patch('pcrscript.tasks.task_abyss.acquire_strategies',return_value=report):
            self.assertIs(AbyssPush.prepare(dict(Abyss=dict(prepare_only=True,sources=dict(stage='4-1'))))[2],report)
        with patch('pcrscript.tasks.strategy_video.acquire_strategies',return_value=report):
            self.assertIs(DungeonFirstClear.prepare(dict(Dungeon=dict(prepare_only=True)))[2],report)

    def test_search_candidates_are_parsed_not_just_preferred_urls(self):
        with TemporaryDirectory() as folder:
            api=Mock();api.getVideoInfo.return_value=dict(code=0,data=dict(bvid='BV0000000000',title='公主连结 火4-1',pages=[dict(cid=1,part='火4-1')]))
            index=SimpleNamespace(names=['角色'],matrix=np.ones((1,1728),np.float32))
            with patch('pcrscript.tasks.strategy_video.discover_sources',return_value=dict(candidates=[dict(bvid='BV0000000000')])), patch('pcrscript.tasks.strategy_video.parse_video_source',return_value=dict(parties=[complete_party()],errors=[])) as parse:
                result=acquire_strategies(dict(task_type='abyss',area='测试',stage='4-1',element='fire',parsed_dir=folder),api=api,index=index)
                self.assertEqual(result['status'],'complete');parse.assert_called_once()
                self.assertTrue(Path(result['document']).is_file())

    def test_irrelevant_preferred_video_does_not_exhaust_parse_budget(self):
        with TemporaryDirectory() as folder:
            api=Mock()
            api.getVideoInfo.side_effect=lambda bvid: dict(code=0,data=dict(bvid=bvid,
                title='公主连结 水深域' if bvid=='BVWATER' else '公主连结 火4-1',
                pages=[dict(cid=1,part='水4-1' if bvid=='BVWATER' else '火4-1')]))
            index=SimpleNamespace(names=['角色'],matrix=np.ones((1,1728),np.float32))
            with patch('pcrscript.tasks.strategy_video.preferred_sources',return_value=([
                    dict(bvid='BVWATER',user_provided=True),dict(bvid='BVLINKED',user_provided=False)],[])), \
                 patch('pcrscript.tasks.strategy_video.discover_sources',return_value=dict(candidates=[dict(bvid='BVFIRE')])), \
                 patch('pcrscript.tasks.strategy_video.parse_video_source',return_value=dict(parties=[complete_party()],errors=[])) as parse:
                result=acquire_strategies(dict(task_type='abyss',area='红焰深域',stage='4-1',element='fire',
                    source_urls=['https://example.com/synthetic'],max_videos=1,parsed_dir=folder),api=api,index=index)
            self.assertEqual(result['status'],'complete')
            self.assertEqual(result['skipped_sources'][0]['bvid'],'BVWATER')
            self.assertEqual(parse.call_count,1)
            self.assertEqual(parse.call_args.args[0]['bvid'],'BVFIRE')

    def test_video_to_document_with_synthetic_frames_and_explicit_fields(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'sample.avi'
            writer=cv.VideoWriter(str(path),cv.VideoWriter_fourcc(*'MJPG'),2,(960,540))
            for i in range(10):writer.write(np.full((540,960,3),30+i,np.uint8))
            writer.release()
            members=[dict(name='角色'+str(i),rectangle=[190+i*120,390,100,100],score=.99) for i in range(5)]
            texts=[GuideText('角色'+str(i)+':5星Lv100Rank10技能100专武1有专武2无SET开',1,(0,0,100,20)) for i in range(5)]
            source=dict(bvid='BV0000000000',url='https://example.com/synthetic',title='公主连结 国服',pages=[dict(cid=1,part='火4-1',duration=5)])
            index=SimpleNamespace(names=[m['name'] for m in members],matrix=np.ones((5,1728),np.float32))
            with patch('pcrscript.tasks.strategy_video.read_text',return_value=texts),patch('pcrscript.tasks.strategy_video.combat_team',return_value=members),patch('pcrscript.tasks.strategy_video.combat_auto',return_value=True):
                report=parse_video_source(source,dict(task_type='abyss',stage='4-1',element='fire',parsed_dir=folder),index,api=Mock(),ocr=Mock(),media_fetcher=lambda *a,**k:(path,dict(duration=5)))
            self.assertEqual(report['status'],'complete')
            self.assertEqual(len(to_event_party(report['parties'][0]).members),5)
            self.assertEqual(report['parties'][0]['identity_evidence'][0]['rectangle'],[253,520,133,133])

    def test_compilation_table_retains_members_without_claiming_stage(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'table.avi'
            writer=cv.VideoWriter(str(path),cv.VideoWriter_fourcc(*'MJPG'),2,(960,540))
            for i in range(10):writer.write(np.full((540,960,3),30+i,np.uint8))
            writer.release()
            names=['角色'+str(i) for i in range(5)]
            row=dict(element='fire',names=names,required_stars=[None]*5,
                confidence=[[(n,.99)] for n in names],instant=[True]*5,chapters=None)
            source=dict(bvid='BV0000000000',url='https://example.com/synthetic',
                title='公主连结 国服深域1-7图合集',pages=[dict(cid=1,part='深域合集',duration=5)])
            index=SimpleNamespace(names=names,matrix=np.ones((5,1728),np.float32))
            with patch('pcrscript.tasks.strategy_video.read_text',return_value=[GuideText('一队通用',1,(0,0,100,20))]), \
                 patch('pcrscript.tasks.strategy_video.combat_team',return_value=[]), \
                 patch('pcrscript.tasks.strategy_tables.universal_row',return_value=row):
                report=parse_video_source(source,dict(task_type='abyss',stage='5-1',element='fire',parsed_dir=folder),
                    index,api=Mock(),ocr=Mock(),media_fetcher=lambda *a,**k:(path,dict(duration=5)))
            self.assertEqual([m['name'] for m in report['parties'][0]['members']],names)
            self.assertFalse(report['parties'][0]['scope_verified'])
            self.assertEqual(report['parties'][0]['readiness'],'incomplete')

    def test_chapter_table_keeps_roster_and_exception_notes(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'table.avi'
            writer=cv.VideoWriter(str(path),cv.VideoWriter_fourcc(*'MJPG'),2,(960,540))
            for i in range(10):writer.write(np.full((540,960,3),30+i,np.uint8))
            writer.release()
            names=['角色'+str(i) for i in range(5)]
            row=dict(element='water',names=names,required_stars=[None]*5,
                     confidence=[[(n,.99)] for n in names],instant=[True]*5,
                     chapters=[1,3],notes='3-10替换角色',excluded_stages=['3-10'])
            source=dict(bvid='BV0000000000',url='https://example.com/synthetic',
                        title='公主连结 水深域1-7图作业一图流',pages=[
                            dict(cid=1,part='6-7',duration=5),dict(cid=2,part='1-5',duration=5)])
            index=SimpleNamespace(names=names,matrix=np.ones((5,1728),np.float32))
            texts=[GuideText('前三章',1,(0,0,100,20)),
                   GuideText('公主连结简中服水深域1-5图参考作业',1,(0,0,200,20))]
            with patch('pcrscript.tasks.strategy_video.read_text',return_value=texts), \
                 patch('pcrscript.tasks.strategy_video.combat_team',return_value=[]), \
                 patch('pcrscript.tasks.strategy_tables.universal_row',return_value=row):
                report=parse_video_source(source,dict(task_type='abyss',stage='3-6',element='water',parsed_dir=folder),
                    index,api=Mock(),ocr=Mock(),media_fetcher=lambda *a,**k:(path,dict(duration=5)))
            self.assertEqual([p['cid'] for p in report['pages']],[2])
            party=report['parties'][0]
            self.assertEqual([m['name'] for m in party['members']],names)
            self.assertEqual(party['scope'],{'element':'water','chapters':[1,3]})
            self.assertEqual(abyss_candidate(party)['excluded_stages'],['3-10'])
            self.assertIsNone(source_for_stage([abyss_candidate(party)],AbyssStage('water',3,6),set(),[],allow_local_trials=True))

    def test_wide_combat_crop_retains_identity_but_not_auto_claim(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'wide.avi'
            writer=cv.VideoWriter(str(path),cv.VideoWriter_fourcc(*'MJPG'),2,(1280,590))
            for i in range(10):writer.write(np.full((590,1280,3),30+i,np.uint8))
            writer.release()
            names=['角色'+str(i) for i in range(5)]
            found=[dict(name=n,rectangle=[190+i*120,390,100,100],score=.99) for i,n in enumerate(names)]
            source=dict(bvid='BV0000000000',url='https://example.com/synthetic',
                title='公主连结 红焰深域 火5-1至5-10',pages=[dict(cid=1,part='5-1',duration=5)])
            index=SimpleNamespace(names=names,matrix=np.ones((5,1728),np.float32))
            with patch('pcrscript.tasks.strategy_video.read_text',return_value=[]), \
                 patch('pcrscript.tasks.strategy_video.combat_team',return_value=found) as combat:
                report=parse_video_source(source,dict(task_type='abyss',stage='5-1',element='fire',parsed_dir=folder),
                    index,api=Mock(),ocr=Mock(),media_fetcher=lambda *a,**k:(path,dict(duration=5)))
            self.assertTrue(combat.call_args.kwargs['relaxed'])
            party=report['parties'][0]
            self.assertEqual([m['name'] for m in party['members']],names)
            self.assertIsNone(party['auto']['value'])
            self.assertEqual(party['readiness'],'incomplete')
            self.assertGreater(party['identity_evidence'][0]['rectangle'][0],300)
            source['pages'][0]['part']='5-1（半自动）'
            with patch('pcrscript.tasks.strategy_video.read_text',return_value=[]), \
                 patch('pcrscript.tasks.strategy_video.combat_team',return_value=found):
                manual=parse_video_source(source,dict(task_type='abyss',stage='5-1',element='fire',parsed_dir=folder),
                    index,api=Mock(),ocr=Mock(),media_fetcher=lambda *a,**k:(path,dict(duration=5)))
            self.assertEqual(manual['parties'][0]['manual_actions'][0]['text'],'5-1（半自动）')
            self.assertTrue(any('手动' in reason for reason in manual['parties'][0]['pending']))

    def test_wide_combat_reads_auto_on_uncropped_edge(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'wide-auto.avi'
            writer=cv.VideoWriter(str(path),cv.VideoWriter_fourcc(*'MJPG'),2,(1280,590))
            frame=np.full((590,1280,3),35,np.uint8)
            frame[437:468,1205:1255]=(255,220,0)
            for _ in range(10):writer.write(frame)
            writer.release()
            names=['角色'+str(i) for i in range(5)]
            found=[dict(name=n,rectangle=[190+i*120,390,100,100],score=.99) for i,n in enumerate(names)]
            source=dict(bvid='BV0000000001',url='https://example.com/synthetic',
                title='公主连结 红焰深域 火5-1至5-10',pages=[dict(cid=2,part='5-4',duration=5)])
            index=SimpleNamespace(names=names,matrix=np.ones((5,1728),np.float32))
            labels=[GuideText('自动',.99,(1209,539,45,31))]
            with patch('pcrscript.tasks.strategy_video.read_text',return_value=labels), \
                 patch('pcrscript.tasks.strategy_video.combat_team',return_value=found):
                report=parse_video_source(source,dict(task_type='abyss',stage='5-4',element='fire',parsed_dir=folder),
                    index,api=Mock(),ocr=Mock(),media_fetcher=lambda *a,**k:(path,dict(duration=5)))
            self.assertTrue(report['parties'][0]['auto']['value'])
            self.assertEqual(len(report['parties'][0]['auto']['evidence'])>=2,True)

    def test_manual_part_metadata_survives_video_download_failure(self):
        with TemporaryDirectory() as folder:
            source=dict(bvid='BV0000000000',url='https://example.com/synthetic',
                title='公主连结 红焰深域 火5-3至5-10',pages=[dict(cid=1,part='5-3（半自动）',duration=5)])
            index=SimpleNamespace(names=['角色'],matrix=np.ones((1,1728),np.float32))
            report=parse_video_source(source,dict(task_type='abyss',stage='5-3',element='fire',parsed_dir=folder),
                index,api=Mock(),ocr=Mock(),media_fetcher=Mock(side_effect=RuntimeError('下载中断')))
            self.assertEqual(report['manual_actions'][0]['text'],'5-3（半自动）')
            self.assertEqual(report['manual_actions'][0]['evidence']['method'],'part_title')
            self.assertEqual(len(report['errors']),1)
            source['pages'][0]['part']='5-3（改星'
            report=parse_video_source(source,dict(task_type='abyss',stage='5-3',element='fire',parsed_dir=folder),
                index,api=Mock(),ocr=Mock(),media_fetcher=Mock(side_effect=RuntimeError('下载中断')))
            self.assertEqual(report['manual_actions'][0]['text'],'5-3（改星')

    def test_automatic_abyss_skips_download_for_explicit_manual_part(self):
        self.assertTrue(task_source_options('abyss',dict(elements=['wind'],sources=dict(stage='2-10')))
                        ['skip_manual_media'])
        self.assertFalse(task_source_options('abyss',dict(elements=['wind'],prepare_only=True,
                         sources=dict(stage='2-10')))['skip_manual_media'])
        with TemporaryDirectory() as folder:
            source=dict(bvid='BV0000000000',url='https://example.com/synthetic',
                title='公主连结 翠岚深域 风2-1至2-10',
                pages=[dict(cid=1,part='2-10（半自动剩80万血）',duration=120)])
            index=SimpleNamespace(names=['角色'],matrix=np.ones((1,1728),np.float32))
            fetch=Mock(side_effect=AssertionError('manual media must not download'))
            report=parse_video_source(source,dict(task_type='abyss',stage='2-10',element='wind',
                parsed_dir=folder,skip_manual_media=True),index,api=Mock(),ocr=Mock(),media_fetcher=fetch)
            fetch.assert_not_called()
            self.assertEqual(report['manual_actions'][0]['text'],'2-10（半自动剩80万血）')
            self.assertEqual(report['pages'][0]['skipped'],'标题要求手动操作或未核实TP+2，自动任务不下载此分P')
            source['pages'][0]['part']='2-10（有TP+2，稳轴）'
            report=parse_video_source(source,dict(task_type='abyss',stage='2-10',element='wind',
                parsed_dir=folder,skip_manual_media=True),index,api=Mock(),ocr=Mock(),media_fetcher=fetch)
            fetch.assert_not_called()
            self.assertEqual(report['manual_actions'][0]['text'],'2-10（有TP+2，稳轴）')
            source['pages'][0]['part']='2-10（简易1押）'
            report=parse_video_source(source,dict(task_type='abyss',stage='2-10',element='wind',
                parsed_dir=folder,skip_manual_media=True),index,api=Mock(),ocr=Mock(),media_fetcher=fetch)
            fetch.assert_not_called()
            self.assertEqual(report['manual_actions'][0]['text'],'2-10（简易1押）')

    def test_automatic_abyss_skips_long_media_before_download(self):
        self.assertTrue(task_source_options('abyss',dict(elements=['wind'],sources=dict(stage='2-10')))
                        ['skip_long_media'])
        self.assertFalse(task_source_options('abyss',dict(elements=['wind'],prepare_only=True,
                         sources=dict(stage='2-10')))['skip_long_media'])
        with TemporaryDirectory() as folder:
            source=dict(bvid='BV0000000000',url='https://example.com/synthetic',
                title='公主连结 翠岚深域 风2-1至2-10',
                pages=[dict(cid=1,part='深域合集',duration=1183)])
            index=SimpleNamespace(names=['角色'],matrix=np.ones((1,1728),np.float32))
            fetch=Mock(side_effect=AssertionError('long media must not download'))
            report=parse_video_source(source,dict(task_type='abyss',stage='2-10',element='wind',
                parsed_dir=folder,skip_long_media=True,max_video_seconds=240),
                index,api=Mock(),ocr=Mock(),media_fetcher=fetch)
            fetch.assert_not_called()
            self.assertEqual(report['pages'][0]['skipped'],'分P时长超出自动解析上限，未下载')
            self.assertEqual(report['pages'][0]['duration'],1183)
            self.assertEqual(report['pages'][0]['max_video_seconds'],240)

    def test_automatic_abyss_preserves_description_tp_requirement(self):
        with TemporaryDirectory() as folder:
            source=dict(bvid='BV0000000000',url='https://example.com/synthetic',
                title='公主连结 翠岚深域 风2-10',
                description='2-10的轴刚需TP+2大师点',
                pages=[dict(cid=1,part='风2-10',duration=120)])
            index=SimpleNamespace(names=['角色'],matrix=np.ones((1,1728),np.float32))
            fetch=Mock(side_effect=AssertionError('unverified setting must not download'))
            report=parse_video_source(source,dict(task_type='abyss',stage='2-10',element='wind',
                parsed_dir=folder,skip_manual_media=True),index,api=Mock(),ocr=Mock(),media_fetcher=fetch)
            fetch.assert_not_called()
            self.assertEqual(report['manual_actions'][0]['evidence']['method'],'source_description')
            self.assertIn('TP+2',report['pages'][0]['skipped'])

    def test_event_video_requires_matching_event_and_mode(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'event.avi'
            writer = cv.VideoWriter(str(path), cv.VideoWriter_fourcc(*'MJPG'), 2, (960,540))
            for i in range(10):
                writer.write(np.full((540,960,3), 30+i, np.uint8))
            writer.release()
            members = [dict(name='角色'+str(i), rectangle=[190+i*120,390,100,100], score=.99)
                       for i in range(5)]
            texts = [GuideText('角色'+str(i)+':5星Lv100Rank10技能100专武1有专武2无SET开',
                               1,(0,0,100,20)) for i in range(5)]
            source = dict(bvid='BV0000000000', url='https://example.com/synthetic',
                title='公主连结 国服 合成活动', pages=[dict(cid=1,part='特别战斗 模式2',duration=5)])
            index = SimpleNamespace(names=[m['name'] for m in members], matrix=np.ones((5,1728),np.float32))
            with patch('pcrscript.tasks.strategy_video.read_text',return_value=texts), \
                 patch('pcrscript.tasks.strategy_video.combat_team',return_value=members), \
                 patch('pcrscript.tasks.strategy_video.combat_auto',return_value=True):
                report = parse_video_source(source, dict(task_type='event', area='合成活动',
                    difficulty='special', mode=2, parsed_dir=folder), index, api=Mock(),
                    ocr=Mock(), media_fetcher=lambda *a,**k:(path,dict(duration=5)))
            self.assertEqual(len(event_parties(report, '合成活动', 'special', 2)), 1)
            self.assertEqual(event_parties(report, '合成活动', 'special', 1), [])

    def test_video_without_frame_text_can_seed_marked_trial_from_avatars(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'silent.avi'
            writer = cv.VideoWriter(str(path), cv.VideoWriter_fourcc(*'MJPG'), 2, (960,540))
            for i in range(10):
                writer.write(np.full((540,960,3), 30+i, np.uint8))
            writer.release()
            members = [dict(name='角色'+str(i), rectangle=[190+i*120,390,100,100], score=.99)
                       for i in range(5)]
            source = dict(bvid='BV0000000000', url='https://example.com/synthetic',
                title='公主连结 国服 合成活动', pages=[dict(cid=1,part='特别战斗 模式2',duration=5)])
            index = SimpleNamespace(names=[m['name'] for m in members], matrix=np.ones((5,1728),np.float32))
            with patch('pcrscript.tasks.strategy_video.read_text',return_value=[]), \
                 patch('pcrscript.tasks.strategy_video.combat_team',return_value=members):
                report = parse_video_source(source, dict(task_type='event', area='合成活动',
                    difficulty='special', mode=2, parsed_dir=folder), index, api=Mock(),
                    ocr=Mock(), media_fetcher=lambda *a,**k:(path,dict(duration=5)))
            self.assertEqual(event_parties(report, '合成活动', 'special', 2), [])
            trials = event_trial_parties(report, '合成活动', 'special', 2)
            self.assertEqual(len(trials), 1)
            self.assertTrue(all(member.instant for member in trials[0].members))
            self.assertTrue(any('SET未知' in note for note in trials[0].assumptions))
