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
from pcrscript.tasks.task_abyss import AbyssPush, validate_options, equipment_retrial, source_for_stage, recent_unreleased, recent_previous_win
from pcrscript.tasks.event_battle import BattleResult
from pcrscript.tasks.strategy_sources import discover_sources
from pcrscript.tasks.event_strategy import EventParty, MemberRequirement
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
    def test_deep_area_story_requires_portrait_text_and_skip_control(self):
        task=object.__new__(AbyssPush);task.ui=Mock()
        icon=cv.imread('images/btn_skip.png')
        image=np.zeros((540,960,3),np.uint8)
        image[19:19+icon.shape[0],865:865+icon.shape[1]]=icon
        story=screen(('前辈您完全不会用奇怪的眼神看待',470,430))
        story.image=image
        self.assertTrue(task.story_dialog(story))
        self.assertEqual(task.ui.click.call_args.args[0],(898.5,42.0))
        task.ui.reset_mock()
        self.assertFalse(task.story_dialog(EventScreen(image,[])))
        task.ui.click.assert_not_called()

    def test_enter_recovers_from_verified_deep_area_story(self):
        task=object.__new__(AbyssPush);task.deadline=float('inf');task.ui=Mock()
        story=screen(('剧情梗概',480,135),('跳过',580,430))
        task.ui.capture.side_effect=[story,map_screen()]
        task.ui.wait.return_value=map_screen()
        self.assertEqual(next_stage(task.enter('fire'))[0],AbyssStage('fire',3,1))
        self.assertEqual(task.ui.click.call_args.args[0].text,'跳过')

    def test_enter_cancels_stale_shard_purchase_before_replanning(self):
        task=object.__new__(AbyssPush);task.deadline=float('inf');task.ui=Mock()
        task.ui.capture.side_effect=[screen(('购买确认',480,42),('取消',370,479)),map_screen()]
        task.ui.wait.return_value=map_screen()
        self.assertEqual(next_stage(task.enter('fire'))[0],AbyssStage('fire',3,1))
        task.ui.expect_click.assert_called_once_with('取消',(250,440,490,515),exact=True)

    def test_enter_dismisses_post_win_clan_battle_cp_notice(self):
        task=object.__new__(AbyssPush);task.deadline=float('inf');task.ui=Mock()
        notice=screen(('挑战团队战吧',480,90),('团队战的挑战次数增加了1次',480,285),
                      ('取消',370,435),('前往团队战',585,435))
        task.ui.capture.side_effect=[notice,map_screen()]
        task.ui.wait.return_value=map_screen()
        self.assertEqual(next_stage(task.enter('fire'))[0],AbyssStage('fire',3,1))
        task.ui.expect_click.assert_called_once_with('取消',(260,400,490,475),exact=True)

    def test_enter_cancels_uncommitted_special_equipment_preview(self):
        task=object.__new__(AbyssPush);task.deadline=float('inf');task.ui=Mock()
        task.ui.capture.side_effect=[screen(('特别装备设定',480,42),('取消',145,479)),map_screen()]
        task.ui.wait.return_value=map_screen()
        self.assertEqual(next_stage(task.enter('fire'))[0],AbyssStage('fire',3,1))
        task.ui.expect_click.assert_called_once_with('取消',(35,445,265,520),exact=True)

    def test_failure_budget_counts_prior_runs_and_interrupted_trials(self):
        with TemporaryDirectory() as folder:
            stage=AbyssStage('fire',5,6)
            history=AbyssHistory(folder,'synthetic')
            self.assertEqual(history.budget(stage,6,2),6)
            history.data['stages'][history.key(stage)]=[{'progressed':False} for _ in range(4)] + [{}]
            history.save()
            resumed=AbyssHistory(folder,'synthetic')
            self.assertEqual(resumed.budget(stage,6,2),1)
            resumed.data['stages'][resumed.key(stage)].append({'progressed':False})
            self.assertEqual(resumed.budget(stage,6,2),0)

    def test_interrupted_win_reconciles_only_with_next_and_spent_attempt(self):
        import json
        import time
        with TemporaryDirectory() as folder:
            history=AbyssHistory(folder,'synthetic')
            prior=AbyssStage('fire',3,5)
            report=Path(folder)/'prior-report.json'
            trial=history.start(prior,{'order':['a','b','c','d','e']},report)
            report.write_text(json.dumps({'battles':[dict(history_id=trial['id'],
                stage={'element':'fire','chapter':3,'number':5},
                outcome='settled',before_remaining=2)]}),encoding='utf-8')
            current=AbyssStage('fire',3,6)
            self.assertIsNone(history.reconcile_previous_win(current,2))
            evidence=history.reconcile_previous_win(current,1)
            self.assertEqual(evidence['next'],'3-6')
            self.assertTrue(history.trials(prior)[-1]['progressed'])
            self.assertEqual(recent_previous_win(history,current,time.time()),['a','b','c','d','e'])

    def test_same_run_reuses_owned_attribute_candidates_after_loss(self):
        formation=object.__new__(AbyssFormation)
        formation._owned_candidates={'fire':['candidate-a','candidate-b']}
        formation.ui=Mock()
        self.assertEqual(formation.owned_candidates('fire'),['candidate-a','candidate-b'])
        formation.ui.assert_not_called()

    def test_alternative_does_not_reaudit_same_unready_incoming_member(self):
        formation=object.__new__(AbyssFormation)
        formation.owned_candidates=lambda element:['替补']
        formation.select=Mock(return_value=(False,{'unready':[
            {'character':'替补','reasons':['专武状态未知']}]}))
        choices=[dict(order=['原角1','替补'],incoming='替补',outgoing=outgoing)
                 for outgoing in ('原角2','原角3')]
        with patch('pcrscript.tasks.abyss_party.character_roles',return_value={}), \
             patch('pcrscript.tasks.abyss_party.alternatives',return_value=choices):
            party,audit=formation.alternative_trial(AbyssStage('fire',5,6),
                                                     {'order':['原角1','原角2','原角3']},set())
        self.assertIsNone(party)
        self.assertEqual(formation.select.call_count,1)
        self.assertEqual(len(audit['rejected']),2)

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

    def test_enter_returns_from_verified_character_detail(self):
        task=object.__new__(AbyssPush);task.deadline=float('inf');task.ui=Mock()
        task.ui.capture.side_effect=[screen(('角色详情',480,40),('确认',478,480)),map_screen()]
        task.ui.wait.return_value=map_screen()
        self.assertEqual(next_stage(task.enter('fire'))[0],AbyssStage('fire',3,1))
        task.ui.expect_click.assert_called_once_with('确认',(350,440,620,510),exact=True)

    def test_enter_closes_finished_star_animation_and_character_pages(self):
        task=object.__new__(AbyssPush);task.deadline=float('inf');task.ui=Mock()
        task.ui.capture.side_effect=[screen(('开花完成',480,400)),
                                     screen(('角色强化',100,40)),
                                     screen(('角色一览',100,40),('冒险',532,520)),map_screen()]
        task.ui.wait.return_value=map_screen()
        self.assertEqual(next_stage(task.enter('fire'))[0],AbyssStage('fire',3,1))
        clicks=[call.args[0] for call in task.ui.click.call_args_list]
        self.assertEqual(clicks[:2],[(480,420),(30,30)])
        self.assertEqual(clicks[2].text,'冒险')
        task.ui.expect_click.assert_not_called()

    def test_enter_character_list_uses_labeled_home_when_adventure_ocr_missing(self):
        task=object.__new__(AbyssPush);task.deadline=float('inf');task.ui=Mock()
        task.ui.capture.side_effect=[screen(('角色一览',100,40),('我的主页',80,522)),map_screen()]
        task.ui.wait.return_value=map_screen()
        self.assertEqual(next_stage(task.enter('fire'))[0],AbyssStage('fire',3,1))
        self.assertEqual(task.ui.click.call_args.args[0].text,'我的主页')

    def test_enter_cancels_stale_star_confirmation(self):
        task=object.__new__(AbyssPush);task.deadline=float('inf');task.ui=Mock()
        task.ui.capture.side_effect=[screen(('才能开花确认',480,42),('取消',370,480)),map_screen()]
        task.ui.wait.return_value=map_screen()
        self.assertEqual(next_stage(task.enter('fire'))[0],AbyssStage('fire',3,1))
        task.ui.expect_click.assert_called_once_with('取消',(250,440,490,515),exact=True)

    def test_enter_closes_verified_star_receipt(self):
        task=object.__new__(AbyssPush);task.deadline=float('inf');task.ui=Mock()
        task.ui.capture.side_effect=[screen(('才能开花完毕',480,42),('确认',480,480)),map_screen()]
        task.ui.wait.return_value=map_screen()
        self.assertEqual(next_stage(task.enter('fire'))[0],AbyssStage('fire',3,1))
        task.ui.expect_click.assert_called_once_with('确认',(350,440,620,510),exact=True)

    def test_enter_closes_stale_shard_source_list(self):
        task=object.__new__(AbyssPush);task.deadline=float('inf');task.ui=Mock()
        task.ui.capture.side_effect=[screen(('记忆碎片获取方法',480,42),('关闭',480,480)),map_screen()]
        task.ui.wait.return_value=map_screen()
        self.assertEqual(next_stage(task.enter('fire'))[0],AbyssStage('fire',3,1))
        task.ui.expect_click.assert_called_once_with('关闭',(350,440,620,510),exact=True)

    def test_enter_dismisses_completed_shard_purchase(self):
        task=object.__new__(AbyssPush);task.deadline=float('inf');task.ui=Mock()
        task.ui.capture.side_effect=[screen(('购买完毕',480,145),('确认',480,370)),map_screen()]
        task.ui.wait.return_value=map_screen()
        self.assertEqual(next_stage(task.enter('fire'))[0],AbyssStage('fire',3,1))
        task.ui.expect_click.assert_called_once_with('确认',(370,340,585,410),exact=True)

    def test_enter_closes_verified_shop_price_notice(self):
        task=object.__new__(AbyssPush);task.deadline=float('inf');task.ui=Mock()
        notice=screen(('确认所需的女神的秘石个数',480,145),
                      ('未奏希(夏日)的',480,240),('记忆碎片的已购数量变为20。',480,260),
                      ('1个对象道具的单价2个了。',480,280),('确认',480,370))
        task.ui.capture.side_effect=[notice,map_screen()]
        task.ui.wait.return_value=map_screen()
        self.assertEqual(next_stage(task.enter('fire'))[0],AbyssStage('fire',3,1))
        self.assertEqual(task.ui.click.call_args.args[0].text,'确认')

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

    def test_same_run_reuses_failed_audit_before_verifying_replacement(self):
        with TemporaryDirectory() as folder,patch('pcrscript.tasks.task_abyss.remaining',return_value=10):
            task=self.task(folder,[map_screen()]*4)
            task.options['max_battles']=2
            names=['a','b','c','d','e']
            task.formation.current_trial.return_value=(EventParty('synthetic','local',[]),
                {'order':names,'observed':[{'name':n,'level':100,'rank':20} for n in names]})
            task.push_area('fire')
            self.assertEqual(task.total_battles,2)
            task.formation.current_trial.assert_called_once()
            task.formation.alternative_trial.assert_called_once()
            self.assertEqual(task.report['battles'][1]['formation']['order'],['a','b','c','d','f'])

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

    def test_recent_previous_win_reuses_only_matching_live_roster(self):
        import time
        for current_order, should_search in ((['a','b','c','d','e'],False),
                                             (['a','b','c','d','f'],True)):
            with TemporaryDirectory() as folder,patch('pcrscript.tasks.task_abyss.remaining',return_value=10):
                task=self.task(folder,[map_screen(2),map_screen(3)])
                task.options['max_battles']=1
                task.open_stage.return_value=(AbyssStage('fire',3,2),Mock(blue_button=Mock(return_value=True)))
                task.history.data['stages']['fire/3-1']=[dict(
                    progressed=True,outcome='settled',finished_at=time.time(),
                    order=['a','b','c','d','e'])]
                task.formation.current_trial.return_value=(EventParty('synthetic','local',[]),
                                                            {'order':current_order})
                task.push_area('fire')
                self.assertEqual(task.search.called,should_search)
                self.assertEqual(task.combat.run.called,not should_search)
                self.assertEqual(recent_previous_win(task.history,AbyssStage('fire',3,2),time.time()),
                                 ['a','b','c','d','e'])

    def test_incomplete_exact_video_roster_uses_authorized_trial_branch(self):
        from pcrscript.tasks.strategy_document import abyss_candidate, empty_member, finalize
        with TemporaryDirectory() as folder,patch('pcrscript.tasks.task_abyss.remaining',return_value=10):
            task=self.task(folder,[map_screen(1),map_screen(2)])
            task.options['max_battles']=1
            document=finalize(dict(source='https://example.com/synthetic',
                scope=dict(element='fire',stage='3-1',chapters=[3,3]),
                scope_verified=True,region='cn',target_region='cn',
                members=[empty_member(name) for name in ['a','b','c','d','e']],
                identity_evidence=[dict(name=name,cid=1,seconds=second)
                                   for name in ['a','b','c','d','e'] for second in (1.0,2.0)],
                auto=dict(value=None,evidence=[],conflicts=[]),
                manual_actions=[],global_requirements=[]))
            task.source_parties=[abyss_candidate(document)]
            task.formation.source_trial.return_value=(EventParty('synthetic','local',[]),
                {'order':['a','b','c','d','e'],'build_basis':'local_trial_source_roster'})
            task.push_area('fire')
            task.formation.source_trial.assert_called_once()
            task.formation.current_trial.assert_not_called()
            self.assertEqual(task.report['battles'][0]['formation']['build_basis'],
                             'local_trial_source_roster')

    def test_source_selection_reaudits_replaced_saved_team(self):
        stage=AbyssStage('fire',5,4)
        source_names=['碧(工作服)','静流(情人节)','克莉丝提娜','矛依未','纯']
        saved_names=['涅妃=涅菈','凤凰','秋乃&咲恋','艾拉','纯']
        def trial(names):
            return (EventParty('synthetic','local',
                    [MemberRequirement(n,1,1,5,None,None,True,0) for n in names]),
                    {'order':names,'observed':[{'name':n,'stars':5} for n in names]})
        formation=object.__new__(AbyssFormation)
        formation.ui=Mock()
        formation.ui.capture.return_value=SimpleNamespace(image=np.zeros((540,960,3),np.uint8))
        formation.avatars=Mock()
        formation.avatars.query.return_value=[None]*5
        formation.occupied_slots=Mock(return_value=list(range(5)))
        formation.select=Mock(return_value=(True,{}))
        formation.current_trial=Mock(side_effect=[trial(saved_names),trial(source_names)])
        source=dict(source='synthetic',names=source_names,instant=[True]*5,required_stars=[None]*5)
        party,audit=formation.source_trial(stage,source)
        self.assertEqual(formation.current_trial.call_count,2)
        self.assertEqual(audit['order'],source_names)
        self.assertEqual([m.name for m in party.members],source_names)

        formation.current_trial=Mock(side_effect=[trial(saved_names),trial(saved_names)])
        party,audit=formation.source_trial(stage,source)
        self.assertIsNone(party)
        self.assertIn('选队后的五人身份与来源不一致，未开战',audit['unready'])

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
