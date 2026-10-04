"""Synthetic observations for failure deduplication; no account or guide data."""
from copy import deepcopy
from unittest import TestCase

from pcrscript.tasks.event_strategy import EventParty, MemberRequirement
from pcrscript.tasks.recollection_retry import trial_context, same_trial, remember_failure, mastery_snapshot


def synthetic_trial():
    names = [f'合成角色{i}' for i in range(5)]
    party = EventParty('synthetic', 'https://example.com/synthetic',
                       [MemberRequirement(n,100,10,5,False,False,True,100) for n in names])
    details = dict(order=names, observed={n:dict(name=n,level=100,rank=10,stars=5,
        skill_level=100,equipment=6,unique=False,unique2=False,identity_verified=True)
        for n in names}, special_equipment=dict(order=names,unknown=0,
        slots=[[True]*3 for _ in names], items=[[[50]*192 for _ in range(3)] for _ in names]))
    signature = dict(scope=dict(area='合成领域',floor=1),boss='合成首领',level=100,maximum_hp=1000000)
    return signature, party, details


class RecollectionRetryTests(TestCase):
    def mastery(self):
        from pcrscript.game_ui.role_mastery import ROLE_NODES, ROLE_TABS
        return [dict(role='attack',node=node,state=dict(level=3,value='7.50',
            title='【'+ROLE_TABS['attack'][0]+'】'+name+'Lv3'),evidence='synthetic.png')
            for node,name in enumerate(ROLE_NODES['attack'])]

    def test_mastery_stats_change_even_when_formation_power_does_not(self):
        nodes=self.mastery()
        first=trial_context(*synthetic_trial(),500000,mastery=nodes)
        second=trial_context(*synthetic_trial(),500000,mastery=deepcopy(nodes))
        self.assertTrue(same_trial(first,second))
        nodes[0]['state']['value']='7.8'
        changed=trial_context(*synthetic_trial(),500000,mastery=nodes)
        self.assertFalse(same_trial(first,changed))
        self.assertEqual(first['mastery']['attack']['0']['value'],'7.5')
        self.assertTrue(same_trial(changed,deepcopy(changed)))
        # Legacy/missing observations cannot themselves authorize another battle.
        self.assertTrue(same_trial(self.context(),changed))
        self.assertTrue(same_trial(changed,self.context()))

    def test_mastery_snapshot_requires_complete_identity_and_numbers(self):
        nodes=self.mastery()
        for altered in (nodes[:-1],nodes+[dict(role='unknown',node=0,state={})]):
            self.assertIsNone(mastery_snapshot(altered))
        for key,value in (('title','错误节点Lv3'),('level',True),('value','NaN'),('value','未知')):
            changed=deepcopy(nodes);changed[0]['state'][key]=value
            self.assertIsNone(trial_context(*synthetic_trial(),500000,mastery=changed),key)
        updated=deepcopy(nodes)
        for row in updated:row['evidence']='new_synthetic.png';row['state']['held']=999
        self.assertEqual(mastery_snapshot(nodes),mastery_snapshot(updated))
        # Optional strengthening observes the same nodes again; use final stats.
        updated[0]['state']['value']='8.1'
        self.assertEqual(mastery_snapshot(nodes+updated)['attack']['0']['value'],'8.1')
        updated[0]['state']['value']='8.10%'
        self.assertEqual(mastery_snapshot(updated)['attack']['0']['value'],'8.1%')

    def context(self):
        return trial_context(*synthetic_trial(),500000)

    def failure(self):
        return dict(trial_context=self.context(),progressed=False,settings_verified=True,
                    attempts_before=3,attempts_after=3,outcome='settled',result_outcome='failed',
                    after='synthetic_after.png',settings_evidence='synthetic_settings.png')

    def test_loadout_tolerates_animation_noise_but_detects_item_changes(self):
        first=self.context();second=deepcopy(first)
        second['special']['items'][0][0]=[55]*192
        self.assertTrue(same_trial(first,second))
        second['special']['items'][0][0]=[70]*192
        self.assertFalse(same_trial(first,second))

    def test_target_build_power_and_controls_changes_allow_a_new_trial(self):
        first=self.context()
        changes=[('power',500001),('auto',False),('instant',[False]*5),('settings_version',2)]
        for key,value in changes:
            second=deepcopy(first);second[key]=value
            self.assertFalse(same_trial(first,second),key)
        second=deepcopy(first);second['target']['scope']['floor']=2
        self.assertFalse(same_trial(first,second))
        second=deepcopy(first);second['members'][0]['skill_level']=101
        self.assertFalse(same_trial(first,second))

    def test_incomplete_live_observations_are_not_a_dedup_key(self):
        signature,party,details=synthetic_trial()
        for power in (None,0,'500000'):
            self.assertIsNone(trial_context(signature,party,details,power))
        for key,value in (('identity_verified',False),('name','其他衣装'),
                          ('skill_level',None),('unique',None)):
            changed=deepcopy(details);changed['observed']['合成角色0'][key]=value
            self.assertIsNone(trial_context(signature,party,changed,500000),key)
        for key,value in (('items',[]),('items',[[[1]],[]]),('slots',[]),('unknown',1)):
            changed=deepcopy(details);changed['special_equipment'][key]=value
            self.assertIsNone(trial_context(signature,party,changed,500000),key)
        self.assertFalse(same_trial(self.context(),{'special':{}}))

    def test_only_settled_failures_with_verified_settings_are_remembered(self):
        state={};remember_failure(state,self.failure())
        self.assertEqual(len(state['failed_trials']),1)
        for key,value in (('progressed',True),('settings_verified',False),('attempts_after',2),
                          ('trial_context',None),('result_outcome','clear')):
            record=self.failure();record[key]=value
            other={};remember_failure(other,record)
            self.assertFalse(other,key)
        record=self.failure();del record['attempts_after']
        other={};remember_failure(other,record);self.assertFalse(other)

    def test_only_confirmed_casualty_retreat_is_recorded(self):
        record=self.failure();record.pop('result_outcome');record['outcome']='retreated'
        for reason,expected in (('减员超出队伍容许值，尝试下一队',True),('SET设置失败',False),('战斗超时',False)):
            record['reason']=reason;state={};remember_failure(state,record)
            self.assertEqual(bool(state),expected)

    def test_context_is_frozen_deduplicated_and_bounded(self):
        signature,party,details=synthetic_trial()
        context=trial_context(signature,party,details,500000)
        details['special_equipment']['items'][0][0][0]=200
        signature['scope']['floor']=2
        self.assertEqual(context['special']['items'][0][0][0],50)
        self.assertEqual(context['target']['scope']['floor'],1)
        record=self.failure();state={}
        remember_failure(state,record);remember_failure(state,record)
        record['trial_context']['power']=1
        self.assertEqual(state['failed_trials'][0]['context']['power'],500000)
        for i in range(40):
            record['trial_context']['power']=100+i;remember_failure(state,record)
        self.assertEqual(len(state['failed_trials']),32)
        self.assertEqual(state['failed_trials'][-1]['context']['power'],139)

    def test_override_is_an_explicit_boolean(self):
        from pcrscript.tasks.recollection_flow import validate_options
        self.assertFalse(validate_options({},first_clear=True)['retry_failed_parties'])
        self.assertTrue(validate_options(dict(retry_failed_parties=True),first_clear=True)['retry_failed_parties'])
        for value in ('true',1,None):
            with self.assertRaises(ValueError):
                validate_options(dict(retry_failed_parties=value),first_clear=True)

    def test_complete_costume_names_match_normalized_formation_order(self):
        from pcrscript.game_ui.screen import normalized
        signature,party,details=synthetic_trial()
        name='合成角色（特殊衣装）'
        party.members[0].name=name
        status=details['observed'].pop('合成角色0');status['name']=name
        details['observed'][name]=status
        details['order'][0]=normalized(name)
        context=trial_context(signature,party,details,500000)
        self.assertIsNotNone(context)
        self.assertTrue(same_trial(context,deepcopy(context)))
