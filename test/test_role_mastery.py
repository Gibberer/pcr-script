from unittest import TestCase
from unittest.mock import Mock
import numpy as np
from pcrscript.game_ui.screen import EventScreen, EventUIError, TextBox
from pcrscript.game_ui.role_mastery import integer_text, ticket_balance, draw_mastery_batch, reconcile_mastery_batch
from pcrscript.game_ui.role_mastery import node_state, reinforce_mastery_node, ROLE_NODES, NODE_POINTS
from pcrscript.game_ui.role_mastery import collect_mastery_rewards,reconcile_mastery_rewards
from pcrscript.tasks.role_mastery_preparation import validate_mastery_preparation, prepare_role_mastery


def screen(result=False, balance='3,650'):
    labels = ([('扭蛋结果',120,30),('获得精通一览',480,30),('持有精通券',590,377),(balance,800,377),
               ('确认',480,425) if balance=='0' else ('取消',370,435)]
              if result else [('精通扭蛋',120,30),('持有的券',550,441),(balance,750,441),
                              ('批量抽取',800,350),('消耗500张',800,390)])
    image=np.full((540,960,3),240,np.uint8)
    image[332:368,760:840]=(230,170,50)
    return EventScreen(image,[TextBox(t,1,[[x-20,y-10],[x+20,y-10],[x+20,y+10],[x-20,y+10]]) for t,x,y in labels])


def node_screen(level=2,value='6%',target='7.5%(+1.5%)',action='升级',cost='20',held='170',name='生命值提升'):
    labels=[('公主骑士强化',140,30),('批量强化',435,435),('增益型',450,184),
            ('【增益型】'+name+'Lv'+str(level),780,168),(value,760,288),(target,880,288),
            (cost,908,365),(held+'(其中可转换的数量23)',835,392),(action,750,435)]
    image=np.full((540,960,3),240,np.uint8);image[417:453,710:790]=(230,170,50)
    return EventScreen(image,[TextBox(t,1,[[x-20,y-10],[x+20,y-10],[x+20,y+10],[x-20,y+10]]) for t,x,y in labels])


def confirmation():
    labels=[('强化确认',480,42),('要消耗以下道具进行强化吗?',480,90),('确认',590,480)]
    image=np.full((540,960,3),240,np.uint8);image[462:498,550:630]=(230,170,50)
    return EventScreen(image,[TextBox(t,1,[[x-20,y-10],[x+20,y-10],[x+20,y+10],[x-20,y+10]]) for t,x,y in labels])


class NodeDevice:
    """Synthetic UI boundary: four nodes, real preparation and ledger logic."""
    def __init__(self,task):
        self.task=task;self.levels=[2]*4;self.node=0;self.dialog=False
        self.payments=[];self.interrupt=False;self.held='170'
    def capture(self):
        if self.dialog:return confirmation()
        level=self.levels[self.node]
        return node_screen(level,'6%' if level==2 else '7.5%',
            '7.5%(+1.5%)' if level==2 else '7.8%(+0.3%)',
            '升级' if level==2 else '强化','20',self.held,ROLE_NODES['buff'][self.node])
    def wait(self,predicate,*args,**kwargs):
        screen=self.capture()
        if not predicate(screen):raise EventUIError('unexpected synthetic page')
        return screen
    def click(self,point):
        if isinstance(point,TextBox):
            assert self.dialog and self.task.state['pending_mastery']['submitted']
            self.levels[self.node]=3;self.dialog=False;self.payments.append(self.node)
            if self.interrupt:
                self.interrupt=False
                raise RuntimeError('interrupted after submission')
        elif point in NODE_POINTS:self.node=NODE_POINTS.index(point)
    def expect_click(self,pattern,*args,**kwargs):
        assert pattern=='升级' and self.task.state['pending_mastery']
        self.dialog=True
    def read_region(self,screen,*args,**kwargs):return screen
    def save(self,*args):return 'synthetic-node.png'


class SharedMaterialDevice(NodeDevice):
    def __init__(self,task):
        super().__init__(task);self.stock=120;self.values=['6%']*4
    def capture(self):
        if self.dialog:return confirmation()
        level=self.levels[self.node];value=self.values[self.node]
        target='7.5%(+1.5%)' if level==2 else '7.8%(+0.3%)' if value=='7.5%' else '8.1%(+0.3%)'
        return node_screen(level,value,target,'升级' if level==2 else '强化',
                           '20' if level==2 else '40',str(self.stock),ROLE_NODES['buff'][self.node])
    def expect_click(self,pattern,*args,**kwargs):
        assert pattern in ('升级','强化') and self.task.state['pending_mastery']
        self.dialog=True
    def click(self,point):
        if isinstance(point,TextBox):
            pending=self.task.state['pending_mastery'];assert pending['submitted'] and self.dialog
            self.stock-=pending['before']['cost'];assert self.stock>=0
            self.levels[self.node]=pending['expected_level']
            self.values[self.node]=pending['expected_value']
            self.dialog=False;self.payments.append(self.node)
        else:super().click(point)


class RoleMasteryTests(TestCase):
    def quest_screen(self,enabled=True,receipt=False):
        labels = ([('收取报酬',480,42),('收取了以下道具。',480,90),('合成材料×100',480,180),('关闭',480,480)]
                  if receipt else [('强化任务',130,30),('全部收取',840,435)])
        image=np.full((540,960,3),240,np.uint8)
        if enabled:image[417:453,800:880]=(230,170,50)
        return EventScreen(image,[TextBox(t,1,[[x-20,y-10],[x+20,y-10],[x+20,y+10],[x-20,y+10]]) for t,x,y in labels])

    def test_free_earned_rewards_journal_before_claim_and_read_receipt(self):
        active=self.quest_screen();empty=self.quest_screen(False);receipt=self.quest_screen(receipt=True)
        ui=Mock();timeline=[]
        frames=iter([active,receipt,empty]);ui.capture.side_effect=lambda:next(frames)
        waits=iter([receipt,empty,node_screen()])
        ui.wait.side_effect=lambda predicate,*a,**kw:next(s for s in waits if predicate(s))
        ui.click.side_effect=lambda point:timeline.append('claim' if isinstance(point,TextBox) else 'back')
        ui.expect_click.side_effect=lambda *a,**kw:timeline.append('close')
        rows=collect_mastery_rewards(ui,begin=lambda r:timeline.append('begin'),
            observed=lambda r:timeline.append('receipt'),settled=lambda r:timeline.append('settled'))
        self.assertEqual(timeline,['begin','claim','receipt','close','settled','back'])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['rewards'],'合成材料×100')

    def test_empty_reward_list_returns_without_claim_or_pending_record(self):
        ui=Mock(capture=Mock(return_value=self.quest_screen(False)))
        ui.wait.side_effect=lambda predicate,*a,**kw:node_screen() if predicate(node_screen()) else None
        begin=Mock();settled=Mock()
        self.assertEqual(collect_mastery_rewards(ui,begin=begin,observed=Mock(),settled=settled),[])
        begin.assert_not_called();settled.assert_not_called();ui.click.assert_called_once_with((30,30))

    def test_pending_reward_receipt_recovers_without_claiming_again(self):
        ui=Mock(capture=Mock(return_value=self.quest_screen(receipt=True)))
        frames=iter([self.quest_screen(receipt=True),self.quest_screen(False)])
        ui.wait.side_effect=lambda predicate,*a,**kw:next(s for s in frames if predicate(s))
        settled=Mock();reconcile_mastery_rewards(ui,dict(kind='mastery_claim'),observed=Mock(),settled=settled)
        settled.assert_called_once();ui.click.assert_not_called()
        ui.expect_click.assert_called_once_with('关闭',(350,440,610,520),exact=True)

    def test_reward_receipt_saved_before_close_recovers_on_list_without_replay(self):
        ui=Mock(capture=Mock(return_value=self.quest_screen(receipt=True)))
        ui.wait.side_effect=[self.quest_screen(receipt=True),RuntimeError('interrupted after close')]
        saved=[]
        with self.assertRaisesRegex(RuntimeError,'after close'):
            reconcile_mastery_rewards(ui,dict(kind='mastery_claim'),observed=saved.append,settled=Mock())
        recovery=Mock(capture=Mock(return_value=self.quest_screen(False)));settled=Mock()
        reconcile_mastery_rewards(recovery,saved[0],observed=Mock(),settled=settled)
        settled.assert_called_once_with(saved[0]);recovery.click.assert_not_called()
        recovery.expect_click.assert_not_called();recovery.wait.assert_not_called()

    def test_node_priority_uses_shared_stock_after_all_required_levels(self):
        task=self.preparation_task();task.ui=SharedMaterialDevice(task);task.capture=task.ui.capture
        prepare_role_mastery(task,validate_mastery_preparation(dict(roles={'buff':3},
            strengthen_target_level=True,node_order={'buff':[3,0,2,1]})))
        self.assertEqual(task.ui.payments,[3,0,2,1,3])
        self.assertEqual(task.ui.levels,[3]*4)
        self.assertEqual(task.ui.values,['7.5%']*3+['7.8%'])
        self.assertEqual(task.ui.stock,0)

    def test_node_priority_rejects_duplicates_unknown_roles_and_boolean_nodes(self):
        for order in ({'buff':[0,0,2,3]},{'buff':[0,1,2]}, {'buff':[0,1,2,4]},
                      {'buff':[False,1,2,3]},{'speed':[0,1,2,3]}, {'buff':'0123'}):
            with self.subTest(order=order),self.assertRaises(ValueError):
                validate_mastery_preparation(dict(roles={'buff':3},node_order=order))

    def test_integer_thousands_accepts_ocr_dot_but_rejects_decimal_or_partial(self):
        for raw,value in (('3,650',3650),('3.150',3150),('0',0),('3500',3500),('1.5',None),('持有3,650',None),('2,30',None)):
            self.assertEqual(integer_text(raw),value)

    def test_ticket_reader_requires_screen_scope_and_unique_confident_value(self):
        self.assertEqual(ticket_balance(screen()),3650)
        self.assertEqual(ticket_balance(screen(True,'3.150')),3150)
        s=screen();s.items[-3].score=.94
        self.assertIsNone(ticket_balance(s))
        self.assertIsNone(ticket_balance(EventScreen(s.image,[])))

    def ui(self,after='3,150'):
        ui=Mock(capture=Mock(return_value=screen()))
        frames=iter([screen(True,after),screen(True,after),screen(False,after)])
        def wait(predicate,*args,**kwargs):
            for frame in frames:
                if predicate(frame):
                    return frame
            raise EventUIError('missing complete result')
        ui.wait.side_effect=wait
        ui.read_region.side_effect=lambda s,*args,**kwargs:s
        return ui

    def test_batch_persists_before_click_and_settles_exact_500(self):
        ui=self.ui();timeline=[]
        ui.click.side_effect=lambda *args:timeline.append('click')
        begin=lambda record:timeline.append(('begin',record['before']))
        settled=lambda record:timeline.append(('settled',record['after']))
        row=draw_mastery_batch(ui,remaining_budget=500,begin=begin,settled=settled)
        self.assertEqual(timeline,[('begin',3650),'click',('settled',3150)])
        self.assertEqual(row['cost'],500)
        self.assertEqual(ui.click.call_count,1)

    def test_unknown_or_conflicting_result_never_settles_or_replays(self):
        for after in ('3,149','3,650','1.5'):
            ui=self.ui(after);settled=Mock()
            with self.assertRaises(EventUIError):
                draw_mastery_batch(ui,remaining_budget=500,begin=Mock(),settled=settled)
            settled.assert_not_called()
            self.assertEqual(ui.click.call_count,1)
            if after!='1.5':ui.expect_click.assert_not_called()

    def test_budget_or_journal_failure_prevents_consumption(self):
        ui=self.ui()
        for budget in (True,0,None):
            with self.assertRaises(ValueError):
                draw_mastery_batch(ui,remaining_budget=budget,begin=Mock(),settled=Mock())
        with self.assertRaises(OSError):
            draw_mastery_batch(ui,remaining_budget=500,begin=Mock(side_effect=OSError()),settled=Mock())
        ui.click.assert_not_called()

    def test_last_partial_batch_consumes_only_displayed_held_tickets(self):
        ui=self.ui('0');before=screen(balance='150');before.items[-1].text='消耗150张'
        ui.capture.return_value=before
        row=draw_mastery_batch(ui,remaining_budget=150,begin=Mock(),settled=Mock())
        self.assertEqual((row['cost'],row['before'],row['after']),(150,150,0))
        ui=self.ui();ui.capture.return_value=before
        with self.assertRaises(EventUIError):
            draw_mastery_batch(ui,remaining_budget=149,begin=Mock(),settled=Mock())
        ui.click.assert_not_called()

    def test_zero_result_uses_numeric_fallback_and_confirmation_without_redraw(self):
        ui=Mock();result=screen(True,'0');result.items[-2].score=.94
        ui.read_region.return_value=EventScreen(result.image,[])
        ui.number.return_value=0
        frames=iter([result,screen(False,'0')])
        ui.wait.side_effect=lambda predicate,*args,**kwargs:next(s for s in frames if predicate(s))
        row=reconcile_mastery_batch(ui,dict(kind='mastery_gacha',before=150,
                                            expected_after=0,cost=150),settled=Mock())
        self.assertEqual(row['after'],0)
        ui.expect_click.assert_called_once_with('确认',(360,395,605,460),exact=True)
        ui.click.assert_not_called()

    def test_pending_result_waits_for_number_without_submitting_again(self):
        ui=self.ui()
        frames=iter([screen(True,''),screen(True,'3,150'),screen(False,'3,150')])
        ui.wait.side_effect=lambda predicate,*args,**kwargs:next(s for s in frames if predicate(s))
        settled=Mock()
        row=reconcile_mastery_batch(ui,dict(kind='mastery_gacha',before=3650,
                                            expected_after=3150,cost=500),settled=settled)
        self.assertEqual(row['after'],3150)
        settled.assert_called_once()
        ui.click.assert_not_called()

    def test_recovery_on_home_proves_deduction_without_cancel_or_draw(self):
        ui=self.ui()
        ui.wait.side_effect=lambda predicate,*args,**kwargs:screen(False,'3,150') if predicate(screen(False,'3,150')) else None
        row=reconcile_mastery_batch(ui,dict(kind='mastery_gacha',before=3650,
                                            expected_after=3150,cost=500),settled=Mock())
        self.assertEqual(row['after'],3150)
        ui.click.assert_not_called()
        ui.expect_click.assert_not_called()

    def test_invalid_pending_record_cannot_be_settled(self):
        ui=self.ui();settled=Mock()
        with self.assertRaises(ValueError):
            reconcile_mastery_batch(ui,dict(kind='mastery_gacha',before=3650,
                                            expected_after=3150,cost=1000),settled=settled)
        ui.wait.assert_not_called()
        settled.assert_not_called()

    def test_node_reader_distinguishes_level_from_stars_and_reads_increment(self):
        row=node_state(node_screen(),'buff')
        self.assertEqual((row['level'],row['value'],row['target'],row['cost']),(2,'6%','7.5%',20))
        self.assertIsNone(node_state(node_screen(),'speed'))
        self.assertIsNone(node_state(node_screen(cost='2?'),'buff'))
        plain=node_screen();plain.items[-2].text='37'
        self.assertEqual(node_state(plain,'buff')['held'],37)

    def test_node_upgrade_journals_confirmation_and_waits_through_old_frame(self):
        ui=Mock(capture=Mock(return_value=node_screen()));timeline=[]
        frames=iter([confirmation(),node_screen(),node_screen(3,'7.5%','7.8%(+0.3%)','强化','40')])
        ui.wait.side_effect=lambda predicate,*args,**kwargs:next(s for s in frames if predicate(s))
        ui.expect_click.side_effect=lambda *a,**k:timeline.append('preview')
        ui.click.side_effect=lambda *a,**k:timeline.append('confirm')
        row=reinforce_mastery_node(ui,'buff',0,begin=lambda r:timeline.append('begin'),
            submitted=lambda r:timeline.append('submitted'),settled=lambda r:timeline.append('settled'))
        self.assertEqual(timeline,['begin','preview','submitted','confirm','settled'])
        self.assertEqual((row['after']['level'],row['after']['value']),(3,'7.5%'))
        self.assertEqual(ui.click.call_count,1)

    def test_node_identity_or_short_materials_cannot_open_confirmation(self):
        for current,node in ((node_screen(),1),(node_screen(held='19'),0)):
            ui=Mock(capture=Mock(return_value=current));begin=Mock()
            with self.assertRaises(EventUIError):
                reinforce_mastery_node(ui,'buff',node,begin=begin,submitted=Mock(),settled=Mock())
            begin.assert_not_called();ui.expect_click.assert_not_called();ui.click.assert_not_called()

    def test_explicit_preparation_rejects_unknown_roles_budget_and_levels(self):
        self.assertEqual(validate_mastery_preparation({})['max_tickets'],0)
        for options in ({'roles':{'healer':3}},{'roles':{'buff':4}},{'roles':{'buff':True}},
                        {'max_tickets':True},{'max_tickets':-1},{'strengthen_target_level':1},
                        {'auto_gacha':True}):
            with self.assertRaises(ValueError):validate_mastery_preparation(options)

    def preparation_task(self):
        task=Mock(state={},report=dict(pending=[]),save=Mock())
        task.ui=NodeDevice(task);task.capture=task.ui.capture
        return task

    def test_production_preparation_trains_four_nodes_then_repeat_spends_nothing(self):
        task=self.preparation_task();options=validate_mastery_preparation({'roles':{'buff':3}})
        prepare_role_mastery(task,options)
        self.assertEqual(task.ui.payments,[0,1,2,3])
        self.assertEqual(task.ui.levels,[3]*4)
        self.assertNotIn('pending_mastery',task.state)
        self.assertEqual(len(task.report['mastery_preparation']['history']),4)
        prepare_role_mastery(task,options)
        self.assertEqual(task.ui.payments,[0,1,2,3])

    def test_consumed_node_recovers_without_replaying_confirm(self):
        task=self.preparation_task();task.ui.interrupt=True
        options=validate_mastery_preparation({'roles':{'buff':3}})
        with self.assertRaisesRegex(RuntimeError,'interrupted'):
            prepare_role_mastery(task,options)
        self.assertTrue(task.state['pending_mastery']['submitted'])
        prepare_role_mastery(task,options)
        self.assertEqual(task.ui.payments,[0,1,2,3])
        self.assertNotIn('pending_mastery',task.state)

    def test_zero_ticket_budget_blocks_missing_materials_without_payment(self):
        task=self.preparation_task();task.ui.held='0'
        prepare_role_mastery(task,validate_mastery_preparation({'roles':{'buff':3}}))
        self.assertEqual(task.ui.payments,[])
        self.assertEqual(len(task.report['pending']),4)

    def test_required_levels_precede_optional_use_of_shared_materials(self):
        task=self.preparation_task();task.ui=SharedMaterialDevice(task);task.capture=task.ui.capture
        prepare_role_mastery(task,validate_mastery_preparation(
            {'roles':{'buff':3},'strengthen_target_level':True}))
        self.assertEqual(task.ui.payments,[0,1,2,3,0])
        self.assertEqual(task.ui.levels,[3]*4)
        self.assertEqual(task.report['pending'],[])

    def test_consumption_settlement_does_not_depend_on_next_material_count(self):
        ui=Mock(capture=Mock(return_value=node_screen()))
        done=node_screen(3,'7.5%','7.8%(+0.3%)','强化','40');done.items[-2].text='?'
        frames=iter([confirmation(),done])
        ui.wait.side_effect=lambda predicate,*args,**kwargs:next(s for s in frames if predicate(s))
        self.assertIsNone(node_state(done,'buff'))
        row=reinforce_mastery_node(ui,'buff',0,begin=Mock(),submitted=Mock(),settled=Mock())
        self.assertEqual(row['after']['value'],'7.5%')
