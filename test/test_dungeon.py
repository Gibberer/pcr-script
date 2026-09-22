"""Offline dungeon safety/progress checks; no emulator or real account data."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import Mock, patch
import json
import numpy as np
import requests
import yaml

from pcrscript.game_ui.screen import EventScreen, TextBox
from pcrscript.game_ui.dungeon import completed_card, progress, dungeon_map
from pcrscript.tasks.dungeon_party import DungeonFormation, load_plan, next_party, route_conflicts
from pcrscript.tasks.event_formation import EventFormation, skill_title_pattern
from pcrscript.tasks.task_dungeon import DungeonFirstClear
from pcrscript.tasks.event_battle import EventCombat, BattleResult
from pcrscript.game_ui.screen import EventUIError
from pcrscript.game_ui.character_equipment import inspect_unreleased_equipment
from pcrscript.tasks.event_strategy import CharacterStatus, MemberRequirement, EventParty, readiness
from pcrscript.extras.bilibili_api import BilibiliApi


def frame(*items):
    return EventScreen(np.zeros((540,960,3),np.uint8), [
        TextBox(text,1,[[x-5,y-5],[x+5,y-5],[x+5,y+5],[x-5,y+5]]) for text,x,y in items])


def synthetic_plan():
    return {'version':1,'area':'测试区域','parties':[
        {'id':key,'floor':floor,'phase':phase,'source':'https://example.com/synthetic',
         'members':[dict(name=f'测试角色{i}',level=10,rank=2,stars=3,unique=False,
                         unique2=False,instant=True,skill_level=10) for i in range(5)]}
        for key,floor,phase in [('first',1,''),('second',1,''),('spring',5,'测试春阶段'),('summer',5,'测试夏阶段')]]}


class DungeonTests(TestCase):
    def test_new_entry_rotates_old_ledger_once_and_never_discards_inflight(self):
        with TemporaryDirectory() as root:
            task=object.__new__(DungeonFirstClear)
            task.state_path=Path(root)/'account.json'
            task.state={'used':['old'], 'history':[{'party':'old'}], 'in_flight':None}
            task.begin_attempt();task.begin_attempt()
            archives=list((Path(root)/'archive').glob('*.json'))
            self.assertEqual(len(archives),1)
            self.assertEqual(json.loads(archives[0].read_text(encoding='utf8'))['used'],['old'])
            self.assertEqual(task.state['used'],[])
            task.state={'used':['active'],'in_flight':{'party':'active'}}
            with self.assertRaises(EventUIError):task.begin_attempt()
            self.assertEqual(task.state['used'],['active'])

    def test_final_reward_animation_can_return_to_completed_area_instead_of_next_floor(self):
        task=object.__new__(DungeonFirstClear)
        task.area='测试区域';task.story_dialog=Mock()
        cleared=frame(('地下城',100,30),('测试区域',827,325),('已完成！',827,82))
        task.ui=Mock();task.ui.wait.return_value=cleared
        map_screen=frame(('测试区域',160,30),('现在的阶数 5/5阶',700,435),('撤退',810,430))
        self.assertIs(task.detail(map_screen),cleared)
        task.ui.click.assert_not_called()

    def test_verified_area_recovers_inflight_final_battle_before_marking_complete(self):
        task=object.__new__(DungeonFirstClear)
        task.ui=Mock();task.save_state=Mock();task.report={'history':[]}
        task.state={'in_flight':{'party':'synthetic','before':{'floor':5,'hp':120,'available':20}}}
        self.assertEqual(task.finish_clear(frame())['status'],'complete')
        self.assertEqual(task.state['history'][0]['damage'],120)
        self.assertIsNone(task.state['in_flight'])
        self.assertTrue(task.state['complete'])

    def test_set_configuration_waits_for_final_pause_menu_geometry(self):
        from types import SimpleNamespace
        opening=frame(('主菜单',480,114),('进行中战斗',330,150),('返回',350,410))
        ready=frame(('主菜单',480,87),('进行中战斗',315,134),('返回',335,435),('AUTO开启',480,358))
        combat=object.__new__(EventCombat)
        combat.r=SimpleNamespace(check_deadline=Mock(),story_dialog=Mock(return_value=False))
        combat.ui=Mock();combat.ui.capture.side_effect=[opening,ready,ready]+[ready]*6
        combat.ui.wait.return_value=ready
        combat.paused_instant=Mock(return_value=False)
        members=[SimpleNamespace(name=f'test{i}',instant=False) for i in range(5)]
        with patch('pcrscript.tasks.event_battle.time.sleep'):
            self.assertTrue(combat.configure_paused(SimpleNamespace(members=members),[m.name for m in members]))
        combat.ui.click.assert_not_called()
        self.assertEqual(combat.ui.capture.call_count,9)
        for call in combat.paused_instant.call_args_list:
            self.assertIs(call.args[0],ready)

    def test_pause_failure_attempts_battle_retreat_instead_of_leaving_combat_running(self):
        from types import SimpleNamespace
        combat=object.__new__(EventCombat)
        combat.ui=Mock();combat.ui.capture.return_value=frame(('1:20',815,25))
        combat.r=SimpleNamespace(options={'battle_timeout':30},check_deadline=Mock())
        combat.match=Mock(return_value=None)
        combat.configure_paused=Mock(side_effect=EventUIError('pause unavailable'))
        combat.retreat=Mock(return_value=BattleResult('retreated'))
        self.assertEqual(combat.run(resume=True).outcome,'retreated')
        combat.retreat.assert_called_once()

    def test_blank_search_field_is_not_misreported_as_missing_character(self):
        formation=object.__new__(EventFormation)
        formation.ui=Mock()
        formation.ui.capture.return_value=frame(('队伍编组',480,40),('重置',690,135))
        formation.occupied_slots=Mock(return_value=[])
        formation.inspect=Mock(side_effect=AssertionError('must not inspect the unfiltered roster'))
        party=EventParty('synthetic','https://example.com',[
            MemberRequirement(f'测试角色{i}',1,1,3) for i in range(5)])
        with patch('pcrscript.tasks.event_formation.time.sleep'):
            with self.assertRaisesRegex(Exception,'搜索词未确认写入'):
                formation.select(party)
        self.assertEqual(formation.ui.driver.input.call_count,3)
        formation.inspect.assert_not_called()

    def test_route_conflicts_ignore_ordinary_floor_reuse(self):
        with TemporaryDirectory() as root:
            p=Path(root)/'plan.yml';p.write_text(yaml.safe_dump(synthetic_plan()),encoding='utf-8')
            plan=load_plan(p,'测试区域')
        self.assertEqual(route_conflicts(plan)['测试角色0'], ['spring','summer'])
        self.assertEqual(route_conflicts(plan[:3]), {})

    def test_reserved_finisher_requires_known_hp_below_gate(self):
        with TemporaryDirectory() as root:
            data=synthetic_plan();data['parties'][-1].update(role='finisher',max_hp=100)
            p=Path(root)/'plan.yml';p.write_text(yaml.safe_dump(data),encoding='utf-8')
            plan=load_plan(p,'测试区域')
        for hp in (None,101):
            self.assertIsNone(next_party(plan,5,'测试夏阶段',set(),hp))
        self.assertEqual(next_party(plan,5,'测试夏阶段',set(),100).key,'summer')

    def test_damage_ledger_is_saved_before_recovery_is_cleared(self):
        with TemporaryDirectory() as root:
            task=object.__new__(DungeonFirstClear)
            task.state_path=Path(root)/'state.json'
            record={'party':'synthetic','before':{'floor':5,'hp':500,'available':30},
                    'after':{'floor':5,'hp':350,'available':25},'outcome':'failed'}
            task.state={'in_flight':record,'used':['synthetic']}
            task.archive_battle(record)
            saved=json.loads(task.state_path.read_text(encoding='utf8'))
            self.assertIsNone(saved['in_flight'])
            self.assertEqual(saved['history'][0]['damage'],150)
            self.assertEqual(saved['history'][0]['characters_consumed'],5)

    def test_route_conflict_blocks_before_any_game_operation(self):
        with TemporaryDirectory() as root:
            p=Path(root)/'plan.yml';p.write_text(yaml.safe_dump(synthetic_plan()),encoding='utf-8')
            task=object.__new__(DungeonFirstClear)
            task.ensure_plan=lambda:load_plan(p,'测试区域')
            task.state={'used':[]};task.report={};task.ui=Mock()
            with self.assertRaisesRegex(Exception,'重复占用'):
                task.audit_route()
            self.assertEqual(task.ui.mock_calls,[])

    def test_verified_clear_records_remaining_damage_without_inventing_roster_count(self):
        task=object.__new__(DungeonFirstClear)
        task.state={'in_flight':{}};task.save_state=Mock()
        record={'before':{'floor':5,'hp':120,'available':20},'first_clear_verified':True}
        task.archive_battle(record)
        self.assertEqual(record['damage'],120)
        self.assertNotIn('characters_consumed',record)
        ordinary={'before':{'floor':4,'hp':120,'available':20},'first_clear_verified':True}
        task.archive_battle(ordinary)
        self.assertNotIn('damage',ordinary)

    def test_skill_note_is_optional_but_words_and_evolution_are_exact(self):
        s = frame(('测试技能+',650,250))
        self.assertIsNotNone(s.find(skill_title_pattern('测试技能+♪'), exact=True))
        self.assertIsNone(s.find(skill_title_pattern('测试技能♪'), exact=True))
        self.assertIsNone(s.find(skill_title_pattern('另一技能+♪'), exact=True))

    def test_defeat_returns_to_dungeon_not_character_training(self):
        task = object.__new__(DungeonFirstClear)
        s = frame(('战斗失败',480,50),('前往角色一览',580,495),('前往地下城',811,495))
        self.assertIs(task.combat_result_button(s), s.items[-1])
        self.assertIsNone(task.combat_result_button(frame(('前往地下城',811,495))))

    def test_character_lookup_does_not_retry_same_unknown_member_forever(self):
        from types import SimpleNamespace
        task = object.__new__(DungeonFirstClear)
        task.options = {'allow_local_trials': True}
        party = SimpleNamespace(members=[SimpleNamespace(name='测试角色')])
        task.formation = Mock()
        task.formation.observed = {'测试角色': CharacterStatus('测试角色', identity_verified=True)}
        task.formation.select.return_value = (False, {'unready': ['unknown']})
        task.formation.unreleased = {}
        task.ui = Mock(); task.detail = Mock(); task.enter = Mock()
        with patch('pcrscript.tasks.task_dungeon.inspect_unreleased_equipment', return_value='proof') as lookup:
            self.assertFalse(task.select_party(party, True)[0])
            lookup.assert_called_once()
        self.assertEqual(task.formation.select.call_count, 2)

    def test_current_build_trial_needs_authorization_and_known_live_values(self):
        data=synthetic_plan();entry=data['parties'][0]
        entry.update(build_basis='local_trial',use_current_build=True)
        entry['members']=[dict(name=f'测试角色{i}',instant=bool(i%2)) for i in range(5)]
        with TemporaryDirectory() as root:
            path=Path(root)/'trial.yml';path.write_text(yaml.safe_dump(data),encoding='utf-8')
            with self.assertRaises(ValueError):load_plan(path,'测试区域')
            plan=load_plan(path,'测试区域',allow_local_trials=True)
            self.assertTrue(plan[0].use_current_build)
            entry['build_basis']='source';path.write_text(yaml.safe_dump(data),encoding='utf-8')
            with self.assertRaises(ValueError):load_plan(path,'测试区域',allow_local_trials=True)
        f=object.__new__(DungeonFormation);f.use_current_build=True
        requested=MemberRequirement('测试角色',1,1,1,None,None,False)
        actual=CharacterStatus('测试角色',10,2,6,True,False,10,identity_verified=True)
        bound=f.resolve_requirement(requested,actual)
        self.assertFalse(bound.instant)
        self.assertEqual(readiness(bound,actual),[])
        actual.unique2=None
        self.assertTrue(readiness(f.resolve_requirement(requested,actual),actual))
        actual.unique2=False;actual.skill_level=None
        self.assertTrue(readiness(f.resolve_requirement(requested,actual),actual))

    def test_completed_region_does_not_require_usable_plan(self):
        with TemporaryDirectory() as root:
            task = object.__new__(DungeonFirstClear)
            task.area='测试区域';task.options={};task.state={}
            task.report={'history':[], 'pending':[]}
            task.ui=Mock(output=Path(root));task.save_state=Mock();task.check_deadline=Mock()
            task.enter=Mock(return_value=frame(('地下城',100,30),('测试区域',827,325),('已完成！',827,82)))
            task.ensure_plan=Mock(side_effect=AssertionError('must skip plan'))
            self.assertEqual(task.run()['status'],'already_complete')

    def test_unreleased_proof_expires_and_cannot_override_live_equipment(self):
        task=object.__new__(DungeonFormation)
        task.unreleased={'测试角色':(100,'fresh-evidence.png')}
        for now,known,expected in ((200,None,False),(401,None,None),(200,True,True)):
            actual=CharacterStatus('测试角色',identity_verified=True,unique=known)
            with self.subTest(now=now,known=known),patch.object(EventFormation,'inspect',return_value=actual), \
                 patch('pcrscript.tasks.dungeon_party.time.time',return_value=now):
                self.assertIs(task.inspect((0,0),full=False).unique,expected)

    def test_character_page_fallback_requires_full_memory_shard_identity(self):
        search=frame(('重置',689,90))
        search.image[145:255,45:305]=(0,0,255)
        for name,expected in (('测试角色','测试角色'),('测试角色(衣装)','测试角色')):
            ui=Mock()
            memory=frame((expected+'的记忆碎片',600,130))
            equipment=frame(('此专用装备1预定今后登场。',700,330))
            ui.capture.side_effect=[search,search,equipment]
            ui.wait.return_value=memory
            ui.save.return_value='evidence.png'
            with self.subTest(name=name),patch('pcrscript.game_ui.character_equipment.time.sleep'):
                result=inspect_unreleased_equipment(ui,name)
                self.assertEqual(result,'evidence.png' if name==expected else None)
                for call in ui.expect_click.call_args_list:
                    self.assertIn(call.args[0],('才能开花','专用装备'))

    def test_reward_animation_waits_for_next_floor_before_click(self):
        task = object.__new__(DungeonFirstClear)
        task.area = '测试区域'
        task.ui = Mock()
        animation = frame(('测试区域',120,30),('2/5阶',540,432),('撤退',813,430),('1层',690,330))
        ready = frame(('测试区域',120,30),('2/5阶',540,432),('撤退',813,430),('2层',650,320))
        detail = frame(('2/5阶',730,415),('500/500',590,337),('25/25',890,389))
        task.ui.wait.side_effect = [ready, detail]
        self.assertIs(task.detail(animation), detail)
        predicate = task.ui.wait.call_args_list[0].args[0]
        self.assertFalse(predicate(animation))
        self.assertFalse(predicate(ready))
        self.assertFalse(predicate(ready))
        self.assertTrue(predicate(ready))
        task.ui.click.assert_called_once_with(ready.items[-1])

    def test_only_known_reward_dialog_is_confirmed(self):
        task = object.__new__(DungeonFirstClear)
        task.ui = Mock()
        reward = frame(('收取报酬',480,42),('确认',480,480))
        self.assertTrue(task.story_dialog(reward))
        task.ui.click.assert_called_once_with(reward.items[1])

    def test_completed_mark_must_belong_to_target_card(self):
        s=frame(('地下城',100,30),('其他区域',360,325),('测试区域',827,325),('已完成！',330,82))
        self.assertFalse(completed_card(s,'测试区域'))
        self.assertTrue(completed_card(s,'其他区域'))
        self.assertIsNone(completed_card(s,'缺失区域'))

    def test_zero_entry_count_does_not_block_active_map(self):
        s=frame(('测试区域',120,30),('1/5阶',540,432),('0/1',740,432),('撤退',813,430))
        self.assertTrue(dungeon_map(s,'测试区域'))

    def test_progress_requires_independent_hp_floor_and_availability(self):
        s=frame(('2/5阶',730,415),('123/500',590,337),('20/25',890,389))
        self.assertEqual((progress(s).floor,progress(s).hp,progress(s).available),(2,123,20))
        self.assertIsNone(progress(frame(('2/5阶',730,415),('0/1',890,430))))
        self.assertIsNone(progress(frame(('2/5阶',730,415),('600/500',590,337),('20/25',890,389))))

    def test_queue_moves_to_next_party_and_never_crosses_phase(self):
        with TemporaryDirectory() as root:
            p=Path(root)/'plan.yml';p.write_text(yaml.safe_dump(synthetic_plan()),encoding='utf-8')
            plan=load_plan(p,'测试区域')
            self.assertEqual(next_party(plan,1,'',set()).key,'first')
            self.assertEqual(next_party(plan,1,'',{'first'}).key,'second')
            self.assertIsNone(next_party(plan,1,'',{'first','second'}))
            self.assertEqual(next_party(plan,5,'测试夏阶段',set()).key,'summer')
            self.assertIsNone(next_party(plan,5,'未知',set()))

    def test_plan_rejects_unknown_equipment_duplicate_ids_and_wrong_area(self):
        with TemporaryDirectory() as root:
            p=Path(root)/'plan.yml'
            for mutation in ('unknown','duplicate','area','phase'):
                data=synthetic_plan()
                if mutation=='unknown':del data['parties'][0]['members'][0]['unique2']
                if mutation=='duplicate':data['parties'][1]['id']='first'
                if mutation=='area':data['area']='其他区域'
                if mutation=='phase':data['parties'][2]['phase']=''
                p.write_text(yaml.safe_dump(data),encoding='utf-8')
                with self.subTest(mutation=mutation),self.assertRaises(ValueError):load_plan(p,'测试区域')

    def test_dungeon_slot_layout_does_not_change_event_layout(self):
        ui=Mock()
        with patch('pcrscript.tasks.event_formation.AvatarIndex'):
            d=DungeonFormation(ui);e=EventFormation(ui)
        self.assertEqual((d.slot_top,e.slot_top),(378,405))
        s=frame();s.image[388:467,58:134]=(0,0,255)
        self.assertEqual(d.occupied_slots(s),[d.slots[0]])


class PublicBilibiliTests(TestCase):
    def test_public_metadata_has_no_cookie_or_navigation_request(self):
        response=Mock();response.json.return_value={'code':0,'data':{}}
        with patch('pcrscript.extras.bilibili_api.requests.get',return_value=response) as get, \
             patch('pcrscript.extras.bilibili_api._cookie_path') as cookie:
            api=BilibiliApi(timeout=7);get.assert_not_called()
            api.getVideoInfo(bvid='BV1234567890')
            cookie.exists.assert_not_called()
            self.assertNotIn('Cookie',get.call_args.kwargs['headers'])
            self.assertEqual(get.call_args.kwargs['timeout'],7)

    def test_412_uses_public_page_and_validates_identity(self):
        blocked=Mock(status_code=412)
        blocked.raise_for_status.side_effect=requests.HTTPError(response=blocked)
        page=Mock(text='window.__INITIAL_STATE__='+json.dumps({'videoData':{'bvid':'BV1234567890','title':'test'}})+';')
        with patch('pcrscript.extras.bilibili_api.requests.get',side_effect=[blocked,page]) as get:
            self.assertEqual(BilibiliApi().getVideoInfo(bvid='BV1234567890')['data']['title'],'test')
            self.assertEqual(get.call_count,2)
            for call in get.call_args_list:self.assertNotIn('Cookie',call.kwargs['headers'])

    def test_public_playback_does_not_initialize_wbi_or_cookie(self):
        with patch('pcrscript.extras.bilibili_api.requests.get',return_value=Mock()) as get:
            BilibiliApi().getVideoPlay(123,bvid='BV1234567890')
            self.assertEqual(get.call_count,1)
            self.assertNotIn('Cookie',get.call_args.kwargs['headers'])
            self.assertEqual(get.call_args.kwargs['params']['fnval'],0)


if __name__=='__main__':main()
