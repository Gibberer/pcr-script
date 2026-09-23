from tempfile import TemporaryDirectory
from unittest import TestCase
from pcrscript.tasks.abyss_history import AbyssHistory,team_key
from pcrscript.tasks.abyss_retry import retry_decision
from pcrscript.tasks.party_variants import alternatives
from pcrscript.game_ui.abyss import AbyssStage
from pcrscript.tasks.task_abyss import source_set_alternative,repeated_casualty


class RetryTests(TestCase):
    def test_most_frequent_fallen_member_beats_one_recent_frontline_loss(self):
        trials=[dict(order=['a','b','c','d','e'],reason='暂停菜单确认减员1人，位置[3]'),
                dict(order=['a','b','x','d','e'],reason='暂停菜单确认减员1人，位置[3]'),
                dict(order=['a','b','x','d','z'],reason='暂停菜单确认减员1人，位置[4]')]
        self.assertEqual(repeated_casualty(trials),'d')

    def test_source_set_note_is_explicit_and_tried_at_most_once(self):
        source=dict(names=list('abcde'),notes='伤害不够的话试试 XXOOO 自动ON')
        self.assertEqual(source_set_alternative(source,[]),'XXOOO')
        tried=[dict(order=list('edcba'),formation={'set_adjustment':{'flags':'XXOOO'}})]
        self.assertIsNone(source_set_alternative(source,tried))
        self.assertIsNone(source_set_alternative(dict(names=list('abcde'),notes='猜一下怎么设置'),[]))

    def test_large_damage_gap_with_alive_team_never_plain_retries(self):
        samples=[dict(seconds=s,hp=700,max_hp=1000,dark_portraits=0) for s in [7,5,2]]
        self.assertEqual(retry_decision(samples,'战斗失败',1)['action'],'change_damage')

    def test_close_death_only_allows_one_same_team_retry(self):
        samples=[dict(seconds=20,hp=100,max_hp=1000,dark_portraits=1)]*3
        self.assertEqual(retry_decision(samples,'减员',1)['action'],'retry_once')
        self.assertEqual(retry_decision(samples,'减员',2)['action'],'change_survival')
        self.assertEqual(retry_decision([],'战斗失败',1)['action'],'change_damage')

    def test_restart_reduces_budget_and_does_not_forget_interrupted_team(self):
        with TemporaryDirectory() as folder:
            stage=AbyssStage('water',1,1);h=AbyssHistory(folder)
            self.assertEqual(h.budget(stage,6,2),6)
            h.start(stage,{'order':['a','b','c','d','e']},'evidence')
            h2=AbyssHistory(folder)
            self.assertEqual(h2.budget(stage,6,2),2)
            self.assertIn(team_key(['e','d','c','b','a']),h2.failed_teams(stage))
            self.assertEqual(AbyssHistory(folder,'other').trials(stage),[])

    def test_variants_keep_tank_and_sole_healer_and_exclude_tried(self):
        roles={n:dict(kind=1,damage=1,heal=False,tank=False,score=30) for n in 'abcdefg'}
        roles['a']['tank']=True;roles['b']['heal']=True
        choices=alternatives(list('abcde'),list('abcdefg'),roles,{team_key(list('abf de'.replace(' ','')))})
        self.assertTrue(choices)
        self.assertTrue(all('a' in c['order'] and 'b' in c['order'] for c in choices))
        self.assertTrue(all(team_key(c['order'])!=team_key(list('abfde')) for c in choices))

    def test_repeated_casualty_prioritizes_replacing_fallen_member(self):
        roles={n:dict(kind=1,damage=1,heal=False,tank=False,score=30,position=100+i*50)
               for i,n in enumerate('abcdef')}
        roles['a']['tank']=True;roles['b']['heal']=True
        roles['c']['score']=50
        roles['f'].update(heal=True,score=75)
        choices=alternatives(list('abcde'),list('abcdef'),roles,set(),survival=True,focus='c')
        self.assertEqual(choices[0]['outgoing'],'c')
        self.assertEqual(choices[0]['incoming'],'f')
        roles['c']['score']=90
        choices=alternatives(list('abcde'),list('abcdef'),roles,set(),survival=True,focus='c')
        self.assertEqual(choices[0]['outgoing'],'d')  # stronger support change wins

    def test_survival_keeps_front_character_without_taunt_tag(self):
        roles={n:dict(kind=1,damage=1,heal=n in 'bf',tank=False,score=30,
                      position=100+i*50) for i,n in enumerate('abcdef')}
        choices=alternatives(list('abcde'),list('abcdef'),roles,set(),survival=True)
        self.assertTrue(choices)
        self.assertTrue(all(choice['outgoing']!='a' for choice in choices))
