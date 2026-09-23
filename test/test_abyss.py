"""Synthetic recognition and bounded progression regressions; no game input."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import numpy as np
import cv2 as cv

from pcrscript.game_ui.screen import EventScreen, TextBox, EventUIError
from pcrscript.game_ui.abyss import AbyssStage, next_stage, detail_stage, remaining, advanced
from pcrscript.tasks.task_abyss import AbyssPush, validate_options, equipment_retrial, source_for_stage, recent_unreleased
from pcrscript.tasks.event_battle import BattleResult
from pcrscript.tasks.strategy_sources import discover_sources
from pcrscript.tasks.event_strategy import EventParty
from pcrscript.tasks.abyss_party import AbyssFormation, archive_observations
from pcrscript.tasks.abyss_history import AbyssHistory
from test_strategy_sources import fake_api


def screen(*labels):
    return EventScreen(np.zeros((540, 960, 3), np.uint8), [
        TextBox(text, 1, [[x-10,y-7],[x+10,y-7],[x+10,y+7],[x-10,y+7]]) for text,x,y in labels])


def map_screen(number=1):
    return screen(('深域关卡', 110, 30), ('红焰深域', 110, 65), ('NEXT',475,230),
                  (f'3-{number}',475,385), ('10/10',673,442), ('3-9',780,270))


class AbyssTests(TestCase):
    def test_same_run_reuses_owned_attribute_candidates_after_loss(self):
        formation=object.__new__(AbyssFormation)
        formation._owned_candidates={'fire':['candidate-a','candidate-b']}
        formation.ui=Mock()
        self.assertEqual(formation.owned_candidates('fire'),['candidate-a','candidate-b'])
        formation.ui.assert_not_called()

    def test_stable_map_allows_small_ocr_box_jitter(self):
        task=object.__new__(AbyssPush);task.deadline=float('inf');task.ui=Mock()
        task.ui.capture.return_value=map_screen()
        def wait(predicate, *args, **kwargs):
            results=[]
            for x in (475,490,489,490):
                s=screen(('深域关卡',110,30),('红焰深域',110,65),('NEXT',490,230),('3-1',x,385))
                results.append(predicate(s))
            self.assertEqual(results,[False,False,False,True])
            return s
        task.ui.wait.side_effect=wait
        self.assertEqual(next_stage(task.enter('fire'))[0],AbyssStage('fire',3,1))

    def test_stable_map_tolerates_one_missed_next_frame(self):
        task=object.__new__(AbyssPush);task.deadline=float('inf');task.ui=Mock()
        task.ui.capture.return_value=map_screen()
        def wait(predicate,*args,**kwargs):
            frames=[map_screen(),screen(('深域关卡',110,30),('红焰深域',110,65)),
                    map_screen(),map_screen()]
            self.assertEqual([predicate(s) for s in frames],[False,False,False,True])
            return frames[-1]
        task.ui.wait.side_effect=wait
        self.assertEqual(next_stage(task.enter('fire'))[0],AbyssStage('fire',3,1))

    def test_boss_label_below_taller_artwork(self):
        s=screen(('深域关卡',110,30),('苍波深域',110,65),('NEXT',475,173),
                 ('BOSS',475,320),('1-10',477,366),('2-1',665,384))
        self.assertEqual(next_stage(s)[0],AbyssStage('water',1,10))

    def test_later_audit_cannot_overwrite_old_battle_evidence(self):
        from pcrscript.tasks.event_strategy import CharacterStatus
        with TemporaryDirectory() as folder:
            output=Path(folder);original=output/'character.png';original.write_bytes(b'first')
            status=CharacterStatus('synthetic',evidence=str(original))
            archive_observations([status],output,'fire_synthetic')
            original.write_bytes(b'next')
            self.assertEqual(Path(status.evidence).read_bytes(),b'first')

    def test_failure_returns_to_deep_map_not_character_training(self):
        task=object.__new__(AbyssPush)
        s=screen(('战斗失败',480,60),('才能开花',700,350),('前往深域关卡',834,490))
        self.assertEqual(task.combat_result_button(s).text,'前往深域关卡')

    def test_stamina_recovery_prompt_is_cancelled_without_purchase(self):
        task=object.__new__(AbyssPush);task.ui=Mock()
        prompt=screen(('体力不足。',475,250),('要回复吗？',480,280),('取消',370,370))
        task.ui.wait.side_effect=lambda predicate,description,handle:handle(prompt)
        with self.assertRaisesRegex(EventUIError,'体力不足，已取消'):
            task.wait_formation('深域编队')
        self.assertEqual(task.ui.click.call_args.args[0].text,'取消')
    def test_partial_title_uses_local_ocr_without_guessing_requested_stage(self):
        task=object.__new__(AbyssPush);task.ui=Mock()
        partial=screen(('红焰深域3-',150,48),('推荐公主骑士品级',750,40),('取消',665,455),('挑战',840,455))
        task.ui.read_region.return_value=screen(('红焰深域3-6',150,48))
        self.assertEqual(task.read_detail(partial),AbyssStage('fire',3,6))
        task.ui.read_region.assert_called_once()
        self.assertEqual(detail_stage(partial),AbyssStage('fire',3,6))

    def test_verified_avatar_trial_does_not_open_skills(self):
        with TemporaryDirectory() as folder, patch('pcrscript.tasks.event_formation.skill_names', side_effect=AssertionError('unnecessary skill lookup')):
            formation=object.__new__(AbyssFormation)
            detail=screen(('角色详情',480,40),('测试角色',620,80),('355',560,115),('38',790,115))
            formation.ui=Mock(output=Path(folder))
            formation.ui.capture.return_value=detail
            formation.ui.wait.return_value=detail
            formation.ui.save.return_value=Path(folder)/'proof.png'
            formation.avatars=Mock();formation.avatars.query.return_value=['测试角色']
            formation.badges=Mock();formation.badges.observe.return_value=((True,False),detail)
            formation.observed={}
            with patch('pcrscript.tasks.event_formation.count_stars',return_value=5):
                actual=formation.inspect((96,452),rectangle=(48,405,96,96),verify_skills=False)
            self.assertTrue(actual.identity_verified)
            self.assertIsNone(actual.skill_level)
            formation.ui.click.assert_not_called()
            self.assertTrue(actual.unique)
            # The final selected-slot verification must keep the same rule;
            # the shared base used to re-enable skill inspection here.
            observed=formation.inspect_current(full=False)
            self.assertEqual(len(observed),5)
            self.assertTrue(all(a.identity_verified for a in observed))

    def test_recent_same_party_uses_live_badges_without_reopening_details(self):
        from pcrscript.tasks.event_strategy import CharacterStatus
        from pcrscript.run_session import clock as time
        formation=object.__new__(AbyssFormation)
        formation.ui=Mock();formation.ui.capture.return_value=screen()
        formation.ui.save.return_value=Path('synthetic-live-badges.png')
        formation.occupied_slots=Mock(return_value=formation.slots)
        formation.avatars=Mock();formation.avatars.query.return_value=['a','b','c','d','e']
        formation.badges=Mock();formation.badges.read.return_value=(True,False)
        formation.observed={name:CharacterStatus(name,identity_verified=True,unique=True,
                            unique2=False,observed_at=time.time()) for name in 'abcde'}
        result=formation.inspect_current(full=True)
        self.assertEqual([a.name for a in result],list('abcde'))
        self.assertEqual(formation.badges.read.call_count,10)
        formation.ui.swipe.assert_not_called()

    def test_limited_shop_only_cancels_observed_shop(self):
        task=object.__new__(AbyssPush);task.ui=Mock()
        shop=screen(('限定商店',480,42),('取消',594,475),('一键购买',803,475))
        self.assertTrue(task.combat_pre_dialog(shop))
        self.assertEqual(task.ui.click.call_args.args[0].text,'取消')
        task.ui.reset_mock()
        self.assertFalse(task.combat_pre_dialog(screen(('未知确认',480,42),('取消',594,475))))
        task.ui.click.assert_not_called()

    def test_next_association_and_unknowns(self):
        self.assertEqual(next_stage(map_screen())[0], AbyssStage('fire',3,1))
        self.assertEqual(remaining(map_screen()),10)
        self.assertIsNone(next_stage(screen(('深域关卡',110,30),('3-1',475,385))))
        self.assertIsNone(remaining(screen(('未知',673,442))))
        detail=screen(('红焰深域3-1',180,45),('9/10',544,456))
        self.assertEqual(detail_stage(detail),AbyssStage('fire',3,1))
        self.assertEqual(remaining(detail,detail=True),9)
        self.assertFalse(advanced(AbyssStage('fire',3,1),AbyssStage('water',4,1)))

    def test_occluded_next_uses_unique_existing_arrow_template(self):
        s=screen(('深域关卡',110,30),('红焰深域',110,65),('3-6',624,253))
        template=cv.imread(str(Path(__file__).resolve().parents[1]/'images/revival_next.png'))[18:35,17:38]
        s.image[103:120,614:635]=template
        self.assertEqual(next_stage(s)[0],AbyssStage('fire',3,6))
        s.image[103:120,300:321]=template
        self.assertIsNone(next_stage(s))

    def test_map_artwork_can_hide_next_letters_below_tabs(self):
        s=screen(('深域关卡',110,30),('紫冥深域',110,65),('3-4',589,365))
        template=cv.imread(str(Path(__file__).resolve().parents[1]/'images/revival_next.png'))[18:35,17:38]
        s.image[222:239,577:598]=template
        self.assertEqual(next_stage(s)[0],AbyssStage('dark',3,4))

    def test_options_reject_unbounded_retries_and_wrong_types(self):
        for option in ({'max_failures_per_stage':51},{'max_battles':0},{'timeout':True},
                       {'elements':['fire','fire']},{'allow_local_trials':'yes'}):
            with self.assertRaises(ValueError): validate_options(option)

    def test_special_equipment_change_allows_only_one_fresh_source_try(self):
        names=['a','b','c','d','e']
        prior=[{'order':names,'progressed':False,'formation':{}}]
        self.assertTrue(equipment_retrial(names,prior))
        prior.append({'order':names,'progressed':False,'formation':{'special_equipment':{'slots':[[True]*3 for _ in names]}}})
        self.assertFalse(equipment_retrial(names,prior))

    def test_failed_source_remains_seed_for_a_new_team(self):
        stage=AbyssStage('fire',4,6)
        used={'element':'fire','chapters':[1,7],'names':['a','b','c','d','e']}
        fresh={'element':'fire','chapters':[1,7],'names':['a','b','c','d','f']}
        failed={'|'.join(sorted(used['names']))}
        # Prefer an untouched guide team, but retain the failed team as an
        # audited starting point when it is the only applicable source.
        self.assertIs(source_for_stage([used,fresh],stage,failed,[]),fresh)
        self.assertIs(source_for_stage([used],stage,failed,[]),used)

    def test_unreleased_proof_needs_recent_existing_evidence(self):
        import json
        with TemporaryDirectory() as folder:
            root=Path(folder);proof=root/'proof.png';proof.write_bytes(b'evidence')
            cache=root/'unreleased.json'
            cache.write_text(json.dumps({'version':1,'proofs':{
                'recent':{'time':100,'evidence':str(proof)},
                'expired':{'time':1,'evidence':str(proof)},
                'missing':{'time':100,'evidence':str(root/'missing.png')},
            }}),encoding='utf-8')
            self.assertEqual(recent_unreleased(cache,110,30),{'recent':(100,str(proof))})

    def task(self, folder, maps):
        task=object.__new__(AbyssPush)
        task.options=validate_options(dict(allow_local_trials=True,discover_sources=False,max_battles=5,max_failures_per_stage=3))
        task.report=dict(areas={},battles=[],pending=[],source_searches=[])
        task.total_battles=0
        task.history=AbyssHistory(folder)
        task._battle_samples=[]
        task.source_parties=[]
        task.deadline=float('inf')
        task.ui=Mock(output=Path(folder));task.ui.save.return_value=Path(folder)/'evidence.png'
        task.enter=Mock(side_effect=maps)
        detail=Mock();detail.blue_button.return_value=True
        task.open_stage=Mock(return_value=(AbyssStage('fire',3,1),detail))
        task.search=Mock()
        task.formation=Mock()
        task.formation.current_trial.return_value=(EventParty('synthetic','local',[]),{'order':['a','b','c','d','e']})
        task.formation.alternative_trial.side_effect=[(EventParty('synthetic','local',[]),{'order':['a','b','c','d',name]}) for name in ['f','g','h','i']]
        task.equip_special=Mock(return_value={'slots':[[True]*3 for _ in range(5)],'empty':0,'unknown':0})
        task.combat=Mock();task.combat.run.return_value=BattleResult('settled')
        return task

    def test_three_no_progress_results_stop_even_when_settled(self):
        with TemporaryDirectory() as folder,patch('pcrscript.tasks.task_abyss.remaining',return_value=10):
            task=self.task(folder,[map_screen()]*6)
            task.push_area('fire')
            self.assertEqual(task.total_battles,3)
            self.assertEqual(task.report['areas']['fire']['failures'],{'3-1':3})
            self.assertEqual(task.search.call_count,1)
            self.assertTrue(all(not b['progressed'] for b in task.report['battles']))

    def test_resource_block_does_not_retry(self):
        with TemporaryDirectory() as folder,patch('pcrscript.tasks.task_abyss.remaining',return_value=10):
            task=self.task(folder,[map_screen()]*2)
            task.combat.run.return_value=BattleResult('blocked','体力不足')
            task.push_area('fire')
            self.assertEqual(task.total_battles,1)

    def test_only_changed_next_counts_as_progress_and_global_limit_stops(self):
        with TemporaryDirectory() as folder,patch('pcrscript.tasks.task_abyss.remaining',return_value=10):
            task=self.task(folder,[map_screen(1),map_screen(2)])
            task.options['max_battles']=1
            task.push_area('fire')
            self.assertEqual(task.report['areas']['fire']['cleared'],['3-1'])
            self.assertEqual(task.total_battles,1)

    def test_unready_or_disabled_trials_never_start(self):
        for enabled in (True,False):
            with TemporaryDirectory() as folder,patch('pcrscript.tasks.task_abyss.remaining',return_value=10):
                task=self.task(folder,[map_screen()])
                task.options['allow_local_trials']=enabled
                task.formation.current_trial.return_value=(None,{'unready':['unknown']})
                task.push_area('fire');task.combat.run.assert_not_called()

    def test_zero_attempts_never_open_stage(self):
        with TemporaryDirectory() as folder,patch('pcrscript.tasks.task_abyss.remaining',return_value=0):
            task=self.task(folder,[map_screen()])
            task.push_area('fire');task.open_stage.assert_not_called()

    def test_stopped_area_does_not_skip_other_elements(self):
        with TemporaryDirectory() as folder:
            task=self.task(folder,[])
            task.enter=Mock()
            def stopped(element):task.report['areas'][element]={'status':'stopped'}
            task.push_area=Mock(side_effect=stopped)
            task.run()
            self.assertEqual([c.args[0] for c in task.push_area.call_args_list],list(task.options['elements']))


class GenericSourcesTests(TestCase):
    def test_verification_required_is_reported_without_retries(self):
        with TemporaryDirectory() as folder:
            api=fake_api();api.search.return_value={'code':0,'data':{'v_voucher':'synthetic'}}
            result=discover_sources(dict(task_type='abyss',area='测试区域',cache_dir=folder),api=api)
            self.assertEqual(result['status'],'blocked')
            self.assertIn('站点验证',result['errors'][0]['error'])
            api.search.assert_called_once();api.getVideoInfo.assert_not_called()

    def test_shared_lookup_is_internal_and_works_without_device(self):
        from pcrscript.tasks import find_taskclass
        self.assertIsNone(find_taskclass('strategy_sources'))
        with TemporaryDirectory() as folder:
            result=discover_sources(dict(task_type='event',area='测试区域',cache_dir=folder),api=fake_api())
            self.assertEqual(result['status'],'complete')

    def test_collection_is_verified_by_parts_not_just_search_title(self):
        with TemporaryDirectory() as folder:
            api=fake_api()
            api.search.return_value['data']['result'][0]['data'][0]['title']='深域全属性合集'
            info=api.getVideoInfo.return_value['data']
            info['title']='公主连结 国服 深域全属性合集'
            info['pages']=[dict(page=1,cid=1,part='测试区域3-1')]
            result=discover_sources(dict(task_type='abyss',area='测试区域',stage='3-1',category_terms=['深域'],cache_dir=folder),api=api)
            self.assertEqual(len(result['candidates']),1)
            self.assertEqual(api.search.call_count,2)

    def test_task_and_stage_cache_isolation_and_exact_stage(self):
        with TemporaryDirectory() as folder:
            api=fake_api()
            api.getVideoInfo.return_value['data']['title']='公主连结 国服 测试区域 深域 3-1'
            options=dict(task_type='abyss',area='测试区域',stage='3-1',category_terms=['深域'],cache_dir=folder)
            first=discover_sources(options,api=api)
            self.assertEqual(len(first['candidates']),1)
            other=discover_sources(dict(options,task_type='event'),api=api)
            self.assertNotEqual(first['catalog'],other['catalog'])
            api.getVideoInfo.return_value['data']['title']='公主连结 国服 测试区域 深域 3-10'
            wrong=discover_sources(dict(options,max_age_hours=0),api=api)
            self.assertFalse(wrong['candidates'])
            self.assertTrue(Path(wrong['previous_catalog']).exists())

    def test_missing_scope_fails_before_network(self):
        api=Mock()
        with self.assertRaises(ValueError):discover_sources({'area':'测试区域'},api=api)
        api.search.assert_not_called()
