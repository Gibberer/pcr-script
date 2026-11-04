"""Synthetic revised tower UI, source selection and real-progress safety."""
from pathlib import Path
from hashlib import sha256
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import numpy as np
import cv2 as cv

from pcrscript.tasks.task_tower import LunaTowerClean, LunaTowerClimb, NoTowerCandidate, validate_options
from pcrscript.tasks.event_battle import BattleResult
from pcrscript.tasks.event_strategy import CharacterStatus
from pcrscript.tasks import Event, EventNews
from pcrscript.game_ui import tower as field
from pcrscript.game_ui.screen import EventUIError
from ui_fixtures import screen, replay_ui


def tower(floor=11, *, clear=False):
    labels = [('露娜之塔',125,30),('剧情故事',660,35),('通关队伍',845,103),
              (str(floor)+'层',370,102),(str(floor)+'阶',120,260),('挑战',810,432)]
    if clear:
        labels.append(('通关',120,292))
        labels.append((str(floor+1)+'阶',120,155))
    return screen(*labels)


def portrait(index,size):
    patch=np.random.default_rng(index+81).integers(25,240,(4,4,3),dtype=np.uint8)
    return cv.resize(patch,(size,size),interpolation=cv.INTER_LINEAR)


def recommendations():
    value=screen(('11层通关队伍一览',480,43),('立即发动',210,104),('胜利',210,140),
                  ('使用',778,139),('关闭',480,480),blue=('使用',))
    for i in range(5):value.image[96:164,266+81*i:334+81*i]=portrait(i,68)
    return value


def preview(*, complete=True):
    value = screen(('队伍编组使用确认',480,147),('确认使用这个队伍编组吗？',480,187),
                   ('取消',335,373),('在模拟战中使用',480,373),('在实战中使用',626,373),
                   blue=('在模拟战中使用','在实战中使用'))
    for i,x in enumerate((284,365,446,527,608)):
        if complete or i < 2:
            value.image[213:281,x:x+68]=portrait(i,68)
    return value


def formation(*, simulate=True):
    label = '模拟战开始' if simulate else '战斗开始'
    value=screen(('队伍编组',480,43),(label,850,453),('取消',710,453),
                 ('今天的编组角色数',665,413), *((('设定为模拟战。',700,498),) if simulate else ()), blue=(label,))
    for i in range(5):
        value.image[379:474,48+109*i:143+109*i]=portrait(i,95)
    return value


class TowerTests(TestCase):
    def setUp(self):
        temporary=TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.robot=SimpleNamespace(driver=Mock(),task_config={'LunaTower':{'state_dir':str(self.root/'state')}},_task_output=self.root)
        self.task=LunaTowerClimb(self.robot)
        self.task.ui=replay_ui(self.root)
        self.task.ui.scrollbar.return_value=False
        self.task.formation.ui=self.task.ui
        self.task.combat.ui=self.task.ui
        self.task.pause_battle_early=Mock(return_value=True)
        self.names=['合成甲','合成乙','合成丙','合成丁','合成戊']
        self.task.formation.avatars.query=Mock(return_value=self.names)

    def frames(self, values):
        frames=iter(values)
        self.task.ui.capture.side_effect=lambda *a,**kw: next(frames,values[-1])
        def wait(predicate,label,**kwargs):
            for _ in range(15):
                value=self.task.ui.capture()
                if predicate(value):return value
            raise EventUIError(label+'超时')
        self.task.ui.wait.side_effect=wait

    def test_exhausted_top_records_stop_instead_of_rescanning_budget(self):
        self.task.options.update(support_trials=False,tank_trials=False,free_recovery=False,max_candidates=20)
        self.task.avatar_manifest={}
        self.task.enter=Mock(return_value=tower())
        self.task.phase_battle=Mock(side_effect=NoTowerCandidate('没有新的完整游戏通关分队'))
        connection=Mock();connection.execute.return_value.fetchall.return_value=[(0,0)]
        with patch('pcrscript.tasks.tower_guides.load_guides',return_value=[]), \
             patch('pcrscript.tasks.task_tower.sqlite3.connect',return_value=connection):
            with self.assertRaises(NoTowerCandidate):self.task.climb_top(tower())
        self.assertEqual(self.task.phase_battle.call_count,1)

    def test_free_recovery_after_a_failed_knife_does_not_require_net_damage(self):
        self.task.options.update(support_trials=False,tank_trials=False,free_recovery=True,max_candidates=1)
        self.task.avatar_manifest={}
        self.task.state['phase_battles']=[dict(result='failed',phase=2,
            before=dict(floor=11,hp=[0,0,0,0,70]),after=dict(floor=11,hp=[0,0,0,0,71]))]
        self.task.enter=Mock(side_effect=[tower(),tower(clear=True),tower(clear=True)])
        self.task.recover_roles=Mock(return_value=True)
        self.task.phase_battle=Mock(side_effect=AssertionError('recover consumed roles first'))
        connection=Mock();connection.execute.return_value.fetchall.return_value=[(0,0)]
        with patch('pcrscript.tasks.tower_guides.load_guides',return_value=[]), \
             patch('pcrscript.tasks.task_tower.sqlite3.connect',return_value=connection):
            self.assertEqual(self.task.climb_top(tower())['status'],'complete')
        self.task.recover_roles.assert_called_once()
        self.task.phase_battle.assert_not_called()

    def test_free_recovery_keeps_enemy_progress_and_invalidates_old_trial(self):
        start=tower()
        start.items+=screen(('角色全回复',385,430),('1天仅能全回复角色1次。',575,435)).items
        dialog=screen(('角色全回复',480,147),('回复所有角色的生命值。',480,220),
            ('已编组角色的技能值也将被重置。',480,300),('支援角色不是重置的对象。',480,325),
            ('确认',590,372),blue=('确认',))
        receipt=screen(('角色全回复',480,147),('所有角色的生命值已回复。',480,260),('确认',480,373))
        self.task.state.update(phase_trial=dict(passed=True),phase_simulation=dict(passed=True),
                               phase_battles=[dict(result='failed')])
        self.frames([dialog,receipt,start])
        self.assertTrue(self.task.recover_roles(start))
        self.assertNotIn('phase_trial',self.task.state)
        self.assertNotIn('phase_simulation',self.task.state)
        self.assertEqual(self.task.state['role_recovery_battle_count'],1)
        self.assertEqual(self.task.report['free_recoveries'][0]['target'],field.target_signature(start))
        self.assertFalse(field.recovery_confirmation(screen(('角色全回复',480,147),('购买生命值',480,220))))

    def test_recovery_cooldown_does_not_click_or_reset_boss(self):
        start=tower()
        start.items+=screen(('角色全回复',385,430),('还剩17小时即可使用。',575,435)).items
        self.assertFalse(self.task.recover_roles(start))
        self.task.ui.click.assert_not_called()
        self.task.ui.expect_click.assert_not_called()

    def test_new_navigation_uses_special_quests_before_tower(self):
        self.frames([screen(('我的主页',75,515)),
                     screen(('冒险',100,30),('主线关卡',550,210),('特别关卡',735,172)),
                     screen(('特别关卡',130,30),('地下城',590,429),('露娜之塔',810,429)),tower()])
        result=self.task.enter()
        self.assertEqual(field.floor_number(result),11)
        clicks=self.task.ui.click.call_args_list
        self.assertEqual(clicks[0].args[0],(532,515))
        self.assertEqual([c.args[0].text for c in clicks[1:]],['特别关卡','露娜之塔'])

    def test_phase_real_requires_successful_phase_simulation(self):
        with self.assertRaisesRegex(EventUIError,'完整免费模拟'):
            self.task.phase_battle({},simulate=False)
        self.task.ui.click.assert_not_called()

    def test_initial_pause_only_clicks_observed_battle_menu(self):
        self.task.combat.match=Mock(side_effect=[(90,500),(900,25)])
        self.frames([formation(),formation()])
        with patch('pcrscript.tasks.task_tower.time.sleep'):
            self.assertTrue(LunaTowerClimb.pause_battle_early(self.task))
        self.task.ui.click.assert_called_once_with((900,25),delay=.1)

    def test_configuration_change_invalidates_proof_without_erasing_battle_ledger(self):
        self.task.state=dict(phase_trial={'passed':True},pending_battle={'floor':11},
                             phase_battles=[{'floor':10}])
        self.task.note_profile_change('合成甲',dict(name='合成甲',before=4,target=5,cost=0))
        self.assertEqual(self.task.state['profile_generation'],1)
        self.assertNotIn('phase_trial',self.task.state)
        self.assertEqual(self.task.state['pending_battle'],{'floor':11})
        self.assertEqual(self.task.state['phase_battles'],[{'floor':10}])

    def test_recover_settled_partial_real_phase_without_another_battle(self):
        from pcrscript.tasks.tower_guides import prefer_proven
        target=dict(floor=11,hp=[0,0,0,0,80])
        pending=dict(floor=11,phase=2,outcome='failed',target=target,names=list('abcde'),
                     before='cache/phase_real_before_0.png')
        self.task.state['pending_battle']=pending
        with patch.object(field,'target_signature',return_value=dict(floor=11,hp=[0,0,0,0,60])):
            self.task.recover_phase_result(tower(),pending)
        self.assertNotIn('pending_battle',self.task.state)
        record=self.task.state['phase_battles'][0]
        self.assertTrue(record['recovered'])
        self.assertEqual((record['before'],record['simulate'],record['result']),(target,False,'failed'))
        self.assertEqual(record['before_evidence'],'cache/phase_real_before_0.png')
        plans=[dict(names=list('vwxyz')),dict(names=list('abcde'))]
        self.assertEqual(prefer_proven(plans,self.task.state['phase_battles'])[0],plans[1])
        # Ledgers saved by the earlier recovery shape must not stop later runs.
        legacy=dict(pending,after=dict(floor=11,hp=[0,0,0,0,60]),recovered=True)
        self.assertEqual(prefer_proven(plans,[legacy]),plans)
        self.task.ui.click.assert_not_called()

    def test_unknown_phase_outcome_stays_pending(self):
        pending=dict(floor=11,phase=2,target=dict(floor=11,hp=[0,0,0,0,80]))
        self.task.state['pending_battle']=pending
        with self.assertRaisesRegex(EventUIError,'结算或目标未知'):
            self.task.recover_phase_result(tower(),pending)
        self.assertEqual(self.task.state['pending_battle'],pending)

    def test_capture_failure_does_not_turn_incomplete_free_trial_into_battle_proof(self):
        import subprocess
        self.task.enter=Mock(return_value=tower())
        self.task.phase_formation=Mock(return_value=(formation(),self.names))
        self.task.combat.run=Mock(side_effect=subprocess.TimeoutExpired('synthetic_capture',30))
        plan=dict(phase=2,goal='boss_damage',source='合成来源',names=self.names,
                  instant={n:True for n in self.names})
        with self.assertRaises(subprocess.TimeoutExpired):
            self.task.phase_battle(plan,simulate=True)
        self.assertNotIn('phase_trial',self.task.state)
        self.assertNotIn('pending_battle',self.task.state)
        self.assertEqual(self.task.state['runtime_failed_phase_trials'][0]['names'],self.names)
        self.assertNotIn('failed_phase_parties',self.task.state)

    def support_frames(self):
        initial=formation()
        initial.image[378:474,48:144]=0
        query=screen(('队伍编组',480,43),('支援',580,88),('重置',691,135),('合成提供者',110,317))
        query.image=initial.image.copy()
        final=formation()
        final.items.extend(screen(('…支援C',96,464)).items)
        self.frames([initial,initial,query,query,query,final])
        self.task.formation.current_names=Mock(side_effect=[self.names[1:],self.names])
        self.task.formation.search_rectangles=Mock(return_value=[(62,177,96,96)])
        self.task.formation.avatars.query=Mock(return_value=[self.names[0]])
        return query

    def test_support_provider_binding_does_not_require_tiny_badge_ocr(self):
        query=self.support_frames()
        with patch('pcrscript.tasks.task_tower.search_character_candidates',return_value=query):
            _,order,proof=self.task.formation.select_support(self.names[0],{})
        self.assertEqual(order,self.names)
        self.assertEqual(proof,dict(name=self.names[0],provider='合成提供者'))
        self.assertEqual(self.task.ui.click.call_args.args[0],(110,225))

    def test_different_support_provider_is_rejected_before_selection(self):
        query=self.support_frames()
        with patch('pcrscript.tasks.task_tower.search_character_candidates',return_value=query), \
             self.assertRaisesRegex(EventUIError,'同衣装支援'):
            self.task.formation.select_support(self.names[0],{},wanted=dict(provider='另一个提供者'))
        self.task.ui.click.assert_not_called()

    def test_settled_real_shadow_clear_is_progress_without_whole_floor_win(self):
        frame=formation(simulate=False)
        self.task.phase_formation=Mock(return_value=(frame,self.names))
        self.task.enter=Mock(return_value=tower())
        before=dict(floor=11,hp=[91]*5)
        after=dict(floor=11,hp=[0,0,0,0,91])
        expected=dict(passed=True,order=self.names,vitals=field.party_vitals(frame),
                      faces=field.formation_faces(frame),target=before)
        def fight(*a,**kw):
            self.task._result='failed'
            return BattleResult('failed')
        self.task.combat.run=Mock(side_effect=fight)
        plan=dict(phase=1,goal='shadows',source='synthetic',instant={n:True for n in self.names})
        with patch.object(field,'target_signature',side_effect=[before,after,after,after]):
            result=self.task.phase_battle(plan,simulate=False,expected=expected)
        self.assertFalse(result['won'])
        self.assertNotIn('pending_battle',self.task.state)
        self.assertEqual(self.task.report['cleared'],[])
        self.assertEqual(self.task.state['phase_battles'][0]['after'],after)

    def test_failed_result_navigation_ignores_win_illustration(self):
        frame=screen(('战斗失败',480,50),('WIN!',550,230),('前往露娜之塔',810,493))
        self.assertEqual(field.navigation_exit(frame).text,'前往露娜之塔')

    def test_title_interrupt_is_not_simulation_failure_or_victory(self):
        title=screen(('点击屏幕开始游戏',480,480),('主菜单',90,500))
        self.assertTrue(field.title(title))
        with self.assertRaisesRegex(EventUIError,'未完整结算'):
            self.task.combat_pre_dialog(title)
        self.assertTrue(self.task._combat_interrupted)
        self.assertIsNone(self.task._phase_trace)
        self.task.ui.click.assert_not_called()

    def test_top_label_requires_catalogue_maximum_and_selected_normal_tab(self):
        top=screen(('露娜之塔',125,30),('剧情故事',660,35),('通关队伍',845,103),
                   ('塔顶',361,101),('塔顶',120,260),('特别',450,101),('挑战',810,432),blue=('塔顶',))
        self.assertIsNone(field.floor_number(top))
        top.tower_max_floor=20
        self.assertEqual(field.floor_number(top),20)
        self.assertTrue(self.task.progressed(top,19))
        self.assertFalse(field.selected_cleared(top))
        top.items.extend(screen(('通关',120,292)).items)
        self.assertTrue(field.selected_cleared(top))
        top.image[80:122,315:410]=0
        self.assertIsNone(field.floor_number(top))
        listing=screen(('塔顶通关队伍一览',480,43),('关闭',480,480))
        listing.tower_max_floor=20
        self.assertTrue(field.recommendations(listing,20))
        self.assertFalse(field.recommendations(listing,19))
        self.assertEqual(field.navigation_exit(listing).text,'关闭')

    def test_top_multi_party_record_shares_mode_and_group_victory(self):
        view=screen(('塔顶通关队伍一览',480,43),('玩家等级',90,104),('立即发动',210,104),
                    ('胜利',210,375),('使用',778,139),('使用',778,250),('使用',778,361))
        for row in range(3):
            for i in range(5):
                view.image[96+111*row:164+111*row,266+81*i:334+81*i]=portrait(i+row*5,68)
        self.assertEqual(field.recommendation_rows(view),[])
        rows=field.recommendation_rows(view,grouped=True)
        self.assertEqual(len(rows),3)
        self.assertTrue(all(row.mode=='立即发动' and row.multi_party for row in rows))

    def test_no_corridor_skips_before_device_connection(self):
        snapshot=EventNews(tower=Event(0,10**12,'合成塔',dict(max_floor=20,cloister_quest_id=0)))
        with patch('pcrscript.news.fetch_event_news',return_value=snapshot), \
             patch('pcrscript.runtime.robot_from_config') as connect:
            from pcrscript.runtime import run_task_with_config
            result=run_task_with_config({},'luna_tower_clean')
        self.assertEqual(result['status'],'unavailable')
        self.assertIn('没有回廊',result['reason'])
        connect.assert_not_called()

    def test_split_special_quest_label_is_reread_before_navigation(self):
        adventure=screen(('冒险',100,30),('主线关卡',550,210),('特别',735,171),('关卡',735,189))
        next(i for i in adventure.items if i.text=='关卡').score=.94
        self.frames([adventure,screen(('特别关卡',130,30),('地下城',590,429),('露娜之塔',810,429)),tower()])
        self.task.ui.read_region.return_value=screen(('特别',735,171),('关卡',735,189))
        self.assertEqual(field.floor_number(self.task.enter()),11)
        self.assertEqual(self.task.ui.click.call_args_list[0].args[0],(735,180))

    def test_unlock_overlay_is_closed_before_using_background_floor(self):
        overlay=tower()
        overlay.items+=screen(('剧情解锁',480,147),('关闭',480,373)).items
        self.assertFalse(field.home(overlay))
        self.frames([overlay,tower()])
        self.assertEqual(field.floor_number(self.task.enter()),11)
        self.assertEqual(self.task.ui.click.call_args_list[0].args[0].text,'关闭')

    def test_preview_warning_does_not_reject_full_team_but_empty_slots_do(self):
        self.assertTrue(field.preview_complete(preview()))
        self.assertFalse(field.preview_complete(preview(complete=False)))
        self.assertIsNotNone(field.navigation_exit(preview()))

    def test_source_is_bound_to_floor_mode_and_five_members(self):
        self.frames([tower(),recommendations(),recommendations(),recommendations(),preview(),preview(),formation()])
        candidate=self.task.candidate(11,set())
        self.assertEqual(candidate['names'],self.names)
        self.assertEqual(candidate['mode'],'立即发动')
        self.assertIn('11层',candidate['source'])
        self.assertIn('在模拟战中使用',[c.args[0].text for c in self.task.ui.click.call_args_list])

    def test_missing_preview_never_enters_formation(self):
        self.frames([tower(),recommendations(),recommendations(),recommendations(),preview(complete=False),preview(complete=False),recommendations()])
        self.task.ui.scrollbar.return_value=False
        result=self.task.candidate(11,set())
        self.assertIsNone(result)
        self.assertIn('推荐预览缺员',self.task.report['rejected'][0]['reason'])
        self.assertNotIn('在模拟战中使用',[getattr(c.args[0],'text',None) for c in self.task.ui.click.call_args_list])

    def test_fading_preview_does_not_turn_owned_team_into_missing_members(self):
        fading=preview(complete=False)
        fading.image[175:200,275:685]=120
        self.frames([tower(),recommendations(),recommendations(),recommendations(),
                     fading,preview(),preview(),formation()])
        candidate=self.task.candidate(11,set())
        self.assertIsNotNone(candidate)
        self.assertEqual(self.task.report['rejected'],[])

    def test_real_recommendation_requires_fresh_simulation(self):
        key='立即发动:0'
        self.frames([tower(),recommendations(),recommendations(),recommendations(),preview()])
        with self.assertRaisesRegex(EventUIError,'没有当前进程通过'):
            self.task.candidate(11,set(),dict(key=key),simulate=False)

    def test_recommendation_entry_retries_only_on_verified_same_floor(self):
        self.task.enter=Mock(return_value=tower())
        def wait(predicate,label,**kwargs):
            handle=kwargs['handle']
            handle(tower(12))
            handle(preview())
            handle(tower())
            self.assertTrue(predicate(recommendations()))
            return recommendations()
        self.task.ui.wait.side_effect=wait
        self.assertTrue(field.recommendations(self.task.open_recommendations(11),11))
        self.assertEqual(self.task.ui.click.call_count,2)
        self.assertTrue(all(c.args[0].text=='通关队伍' for c in self.task.ui.click.call_args_list))

    def test_changed_or_missing_roster_blocks_start(self):
        self.task.formation.avatars.query.return_value=list(reversed(self.names))
        with self.assertRaisesRegex(EventUIError,'衣装或顺序'):
            self.task.verify_members(formation(),self.names,simulate=True)
        with self.assertRaisesRegex(EventUIError,'模拟／实战'):
            self.task.verify_members(formation(),self.names,simulate=False)

    def test_unknown_build_blocks_even_with_known_portraits(self):
        actual=[CharacterStatus(n,level=300,rank=30,stars=5,skill_level=300,
                               unique=False,unique2=False,identity_verified=True) for n in self.names]
        actual[2].unique2=None
        self.task.formation.inspect_current=Mock(return_value=actual)
        with self.assertRaisesRegex(EventUIError,'独立专武未核实'):
            self.task.audit(dict(names=self.names,floor=11,source='合成来源',mode='立即发动'))

    def test_unknown_public_names_require_live_skill_identity_before_battle(self):
        self.task.formation.avatars.query.return_value=[None]*5
        self.frames([tower(),recommendations(),recommendations(),recommendations(),preview(),preview(),formation()])
        candidate=self.task.candidate(11,set())
        self.assertEqual(candidate['names'],[None]*5)
        actual=[CharacterStatus(n,level=300,rank=30,stars=5,skill_level=300,
                               unique=False,unique2=False,identity_verified=True) for n in self.names]
        self.task.formation.inspect_current=Mock(return_value=actual)
        party=self.task.audit(candidate)
        self.assertEqual(candidate['names'],self.names)
        self.assertEqual([m.name for m in party.members],self.names)
        self.assertTrue(all(m.instant for m in party.members))

    def test_default_simulation_then_real_never_opens_attribute_or_equipment_pages(self):
        event=Event(0,10**12,'合成塔',dict(max_floor=11,schedule_id=1,cloister_quest_id=0))
        self.robot._event_news=EventNews(tower=event)
        self.task.options.update(target_floor=11,max_floors=1,auto_equip=False)
        self.task.enter=Mock(return_value=tower())
        faces=field.formation_faces(formation())
        candidate=dict(names=[None]*5,floor=11,source='游戏内11层通关队伍',mode='立即发动',
                       key='合成',formation_portraits=faces)
        self.task.candidate=Mock(side_effect=[dict(candidate),dict(candidate)])
        self.task.battle=Mock(side_effect=[True,tower(clear=True)])
        self.task.audit=Mock(side_effect=AssertionError('must not inspect builds'))
        self.task.formation.inspect_current=Mock(side_effect=AssertionError('must not open details'))
        connection=Mock();connection.execute.return_value.fetchall.return_value=[(0,0)]
        with patch('pcrscript.game_ui.avatar_assets.ensure_avatar_index',return_value=(self.task.formation.avatars,{})), \
             patch('pcrscript.tasks.task_tower.prepare_character_database',side_effect=AssertionError('no build preparation')), \
             patch('pcrscript.tasks.task_tower.prepare_special',side_effect=AssertionError('no equipment inspection')), \
             patch('pcrscript.tasks.task_tower.sqlite3.connect',return_value=connection):
            result=self.task.run()
        self.assertEqual(result['status'],'complete')
        self.assertEqual([c.kwargs['simulate'] for c in self.task.battle.call_args_list],[True,False])
        simulated,real=[c.args[0] for c in self.task.battle.call_args_list]
        self.assertEqual(simulated['combat_order'],real['combat_order'])
        self.assertEqual(self.task.battle.call_args_list[0].args[1].allow_deaths,4)
        self.task.audit.assert_not_called()
        self.task.formation.inspect_current.assert_not_called()

    def test_similar_frames_do_not_merge_different_characters(self):
        self.assertTrue(field.same_face(portrait(1,68),portrait(1,95)))
        self.assertFalse(field.same_face(portrait(1,68),portrait(2,95)))

    def test_formation_border_alignment_preserves_character_identity(self):
        source=recommendations()
        faces=field.recommendation_rows(source)[0].portraits
        actual=formation()
        actual.image[379:474,157:254]=0
        actual.image[379:474,159:254]=portrait(1,95)
        self.assertTrue(field.matches_formation(actual,faces))
        actual.image[379:474,159:254]=portrait(7,95)
        self.assertFalse(field.matches_formation(actual,faces))

    def test_changed_star_illustration_requires_same_independently_recognized_identity(self):
        faces=field.recommendation_rows(recommendations())[0].portraits
        actual=formation();actual.image[379:474,157:252]=portrait(7,95)
        index=Mock(query=Mock(side_effect=[self.names,self.names]))
        self.assertTrue(field.matches_formation(actual,faces,index))
        for replacement in (None,'另一角色','unit:123'):
            changed=list(self.names);changed[1]=replacement
            index.query.side_effect=[self.names,changed]
            self.assertFalse(field.matches_formation(actual,faces,index))

    def test_small_hp_or_tp_changes_invalidate_simulation_context(self):
        first,second=tower(),tower()
        first.image[289:299,315:345]=(20,200,20)
        second.image[289:299,315:344]=(20,200,20)
        self.assertNotEqual(field.target_signature(first),field.target_signature(second))
        first,second=formation(),formation()
        first.image[479:489,54:84]=(20,200,20)
        second.image[479:489,54:83]=(20,200,20)
        self.assertNotEqual(field.party_vitals(first),field.party_vitals(second))

    def test_enemy_hp_sampling_excludes_animated_background_for_all_five_slots(self):
        first,second=tower(),tower()
        bars=((317,408),(443,534),(568,659),(693,785),(819,910))
        for left,right in bars:
            first.image[293:297,left:right]=(20,200,20)
        second.image[:]=first.image
        for left,_ in bars:
            second.image[289:299,left-12:left]=(20,200,20)
        self.assertEqual(field.target_signature(first),field.target_signature(second))
        for left,right in bars:
            changed=tower();changed.image[:]=first.image
            changed.image[293:297,right-1:right]=0
            self.assertNotEqual(field.target_signature(first),field.target_signature(changed))

    def test_ub_animation_never_opens_a_story_menu(self):
        for value in [screen(('模拟战中',100,25),('菜单',900,25),('跳过',480,395)),
                      screen(('菜单',900,25),('深渊终结炸裂',480,70))]:
            self.assertFalse(self.task.story_dialog(value))
        self.task.ui.click.assert_not_called()
        with patch('pcrscript.tasks.task_story_event.CampaignClean.story_dialog',return_value=True) as story:
            self.assertTrue(self.task.story_dialog(screen(('跳过这个剧情吗',480,210))))
        story.assert_called_once()

    def test_low_confidence_floor_is_reread_locally(self):
        value=tower()
        next(i for i in value.items if i.text=='11层').score=.94
        self.task.ui.capture.return_value=value
        self.task.ui.read_region.return_value=screen(('11层',370,102))
        self.assertIsNone(field.floor_number(value))
        self.assertEqual(field.floor_number(self.task.capture()),11)
        self.task.ui.read_region.assert_called_once_with(value,(315,83,445,124),classify=False)

    def test_real_dispatch_persists_and_ambiguous_outcome_never_replays(self):
        self.frames([formation(simulate=False),tower()])
        self.task.state_path=self.root/'state.json'
        self.task.combat.run=Mock(return_value=BattleResult('settled'))
        candidate=dict(names=self.names,floor=11)
        with self.assertRaisesRegex(EventUIError,'未确认胜利'):
            self.task.battle(candidate,None,simulate=False)
        self.assertTrue(self.task.state_path.exists())
        self.assertEqual(self.task.state['pending_battle']['floor'],11)
        self.task.ui.capture.side_effect=None
        self.task.ui.capture.return_value=formation(simulate=False)
        with self.assertRaisesRegex(EventUIError,'未核账'):
            self.task.battle(candidate,None,simulate=False)
        self.task.ui.click.assert_called_once()

    def test_real_win_requires_actual_floor_progress(self):
        self.frames([formation(simulate=False),tower(12)])
        def combat(*args,**kwargs):
            self.task.observe_battle(screen(('WIN',480,120)))
            return BattleResult('settled')
        self.task.combat.run=Mock(side_effect=combat)
        self.task.battle(dict(names=self.names,floor=11),None,simulate=False)
        self.assertFalse(self.task.state.get('pending_battle'))
        self.assertEqual(self.task.report['cleared'][0]['floor'],11)

    def test_wrong_floor_and_simulation_never_count_real_progress(self):
        self.assertFalse(self.task.progressed(tower(),11))
        self.assertTrue(self.task.progressed(tower(clear=True),11))
        self.assertTrue(self.task.progressed(tower(12),11))
        self.frames([formation(),tower()])
        def combat(*args,**kwargs):
            self.task.observe_battle(screen(('WIN',480,120)))
            return BattleResult('settled')
        self.task.combat.run=Mock(side_effect=combat)
        self.assertTrue(self.task.battle(dict(names=self.names,floor=11),None,simulate=True))
        self.assertEqual(self.task.report['cleared'],[])
        self.assertNotIn('pending_battle',self.task.state)

    def test_recovery_keeps_unverified_real_battle_blocked(self):
        from pcrscript.run_session import atomic_json
        event=Event(0,10**12,'合成塔',dict(max_floor=20,schedule_id=1,cloister_quest_id=0))
        self.robot._event_news=EventNews(tower=event)
        key=sha256(str((self.robot.driver.device_name,1)).encode()).hexdigest()[:24]
        atomic_json(self.root/'state'/(key+'.json'),dict(pending_battle=dict(floor=11)))
        self.frames([tower()])
        result=self.task.run()
        self.assertEqual(result['status'],'blocked')
        self.assertIn('尚未核账',result['reason'])
        self.task.ui.click.assert_not_called()

    def test_confirmed_retreat_requires_restored_enemy_and_five_member_vitals(self):
        before=formation(simulate=False)
        path=self.root/'before.png';cv.imwrite(str(path),before.image)
        pending=dict(floor=11,outcome='retreated',before=str(path),
                     target=field.target_signature(tower()),vitals=field.party_vitals(before))
        import json
        pending=json.loads(json.dumps(pending))
        self.task.state={'pending_battle':pending}
        self.frames([before,tower()])
        self.task.recover_retreat(tower(),pending)
        self.assertNotIn('pending_battle',self.task.state)
        self.assertEqual(self.task.state['retreated'][0],pending)
        self.task.state={'pending_battle':pending}
        self.task.ui.click.reset_mock()
        with self.assertRaisesRegex(EventUIError,'敌方状态'):
            self.task.recover_retreat(tower(12),pending)
        self.task.ui.click.assert_not_called()
        self.assertIn('pending_battle',self.task.state)

    def test_corrupt_state_is_preserved_and_never_authorizes_replay(self):
        event=Event(0,10**12,'合成塔',dict(max_floor=20,schedule_id=1,cloister_quest_id=0))
        self.robot._event_news=EventNews(tower=event)
        key=sha256(str((self.robot.driver.device_name,1)).encode()).hexdigest()[:24]
        path=self.root/'state'/(key+'.json')
        path.parent.mkdir()
        path.write_text('{incomplete',encoding='utf-8')
        self.frames([tower()])
        report=self.task.run()
        self.assertEqual(report['status'],'blocked')
        self.assertEqual(path.read_text(encoding='utf-8'),'{incomplete')
        self.task.ui.click.assert_not_called()

    def test_invalid_budget_and_flag_rejected(self):
        for options in [dict(max_floors=True),dict(max_candidates=0),dict(target_floor=-1),dict(simulation_only=1)]:
            with self.subTest(options=options),self.assertRaises(ValueError):validate_options(options)

    def test_failed_simulation_returns_to_tower_instead_of_character_training(self):
        failure=screen(('战斗失败',480,55),('WIN!',480,250),('前往角色一览',580,493),('前往露娜之塔',810,493))
        self.assertEqual(field.battle_result(failure),'failed')
        self.assertEqual(self.task.combat_result_button(failure).text,'前往露娜之塔')

    def test_star_restore_returns_home_before_reentering_the_tower(self):
        plan=dict(stars={self.names[4]:5})
        calls=[]
        self.task.report['star_changes']=[dict(name=self.names[4],before=4,target=5,cost=0)]
        with patch.object(field,'reduced_star_badge',return_value=True),              patch('pcrscript.game_ui.character_stars.restore_unlocked_five',
                   side_effect=lambda *a,**k: calls.append('restore') or True),              patch('pcrscript.tasks.task_home.ToHomePage') as home,              patch.object(self.task,'enter',side_effect=lambda: calls.append('enter')):
            home.return_value.run.side_effect=lambda **k: calls.append('home')
            self.assertTrue(self.task.repair_temporary_stars(plan,tower(),self.names))
        self.assertEqual(calls,['restore','home','enter'])

    def test_uncertain_weapon_badge_uses_readonly_proof_and_reopens_source(self):
        actual=[CharacterStatus(n,level=300,rank=30,stars=5,skill_level=300,
                               unique=False,unique2=False,identity_verified=True) for n in self.names]
        actual[4].unique=actual[4].unique2=None
        confirmed=[CharacterStatus(n,level=300,rank=30,stars=5,skill_level=300,
                                  unique=False,unique2=False,identity_verified=True) for n in self.names]
        self.task.formation.inspect_current=Mock(side_effect=[actual,confirmed])
        candidate=dict(names=list(self.names),floor=11,source='合成来源',mode='立即发动',key='合成',vitals=[])
        # These boundaries are exercised separately by navigation and source
        # replay tests; here verify that only the explicit slot proof resolves
        # an unknown badge, and failure remains unable to start combat.
        with patch.object(self.task,'enter'), \
             patch.object(self.task,'candidate',return_value=dict(candidate)) as reopen, \
             patch('pcrscript.game_ui.character_equipment.inspect_unreleased_equipment',return_value='synthetic-proof') as inspect,              patch('pcrscript.tasks.task_home.ToHomePage') as home:
            party=self.task.audit(candidate)
        inspect.assert_called_once_with(self.task.ui,self.names[4])
        # The lookup is bracketed by the shared home navigator before the source reopens.
        self.assertEqual(home.return_value.run.call_count,2)
        reopen.assert_called_once()
        self.assertIn(self.names[4],self.task.formation.unreleased)
        self.assertTrue(all(m.unique is False and m.unique2 is False for m in party.members))
        self.task.ui.click.assert_not_called()
