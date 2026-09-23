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
from pcrscript.game_ui.guide_vision import GuideText, combat_team, combat_set, combat_auto, labeled_fields, formation_fields
from pcrscript.tasks.strategy_document import Evidence, empty_member, finalize, to_event_party, abyss_candidate
from pcrscript.tasks.strategy_video import choose_pages, observed_scope, parse_video_source, acquire_strategies
from pcrscript.tasks.task_abyss import AbyssPush, source_for_stage
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
        for key, value in [('global_requirements', [{'text':'属性等级99'}]), ('manual_actions',[{'text':'手动'}]), ('region','jp')]:
            with self.subTest(key=key), self.assertRaises(ValueError): to_event_party(dict(party, **{key:value}))

    def test_part_selection_and_contradictory_stage(self):
        source = dict(title='测试', pages=[dict(cid=1,part='练度要求'),dict(cid=2,part='水4-1'),dict(cid=3,part='火4-1')])
        self.assertEqual([p['cid'] for p in choose_pages(source,dict(task_type='abyss',stage='4-1',element='fire',max_pages_per_video=2))],[1,3])
        self.assertFalse(observed_scope([GuideText('火4-2',1,(0,0,10,10))], source['pages'][2], 'abyss')[1])

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
            api=Mock();api.getVideoInfo.return_value=dict(code=0,data=dict(bvid='BV0000000000',title='公主连结 测试',pages=[]))
            index=SimpleNamespace(names=['角色'],matrix=np.ones((1,1728),np.float32))
            with patch('pcrscript.tasks.strategy_video.discover_sources',return_value=dict(candidates=[dict(bvid='BV0000000000')])), patch('pcrscript.tasks.strategy_video.parse_video_source',return_value=dict(parties=[complete_party()],errors=[])) as parse:
                result=acquire_strategies(dict(task_type='abyss',area='测试',parsed_dir=folder),api=api,index=index)
                self.assertEqual(result['status'],'complete');parse.assert_called_once()
                self.assertTrue(Path(result['document']).is_file())

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
