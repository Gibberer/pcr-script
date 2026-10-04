"""Synthetic EX gear preview recognition; no account screenshots."""
from unittest import TestCase
from unittest.mock import Mock, patch
import numpy as np

from pcrscript.game_ui.screen import EventScreen, EventUIError, TextBox
from pcrscript.game_ui.special_equipment import (auto_equip_special, occupied_slots,
    preview_slots, SPECIAL_COLUMNS, SPECIAL_ROWS, PRIORITY_OPTIONS, configure_auto_priorities,
    selected_priority, validate_auto_priorities, cancel_special_equipment)


class SpecialEquipmentTests(TestCase):
    def test_equipment_navigation_closes_detail_and_swap_without_committing(self):
        for title,y,button in (('道具详情',40,'关闭'),('特别装备替换确认',90,'关闭'),('选择装备',40,'取消')):
            with self.subTest(title=title):
                screen=EventScreen(np.full((540,960,3),240,np.uint8),[
                    TextBox(title,1,[[400,y-10],[560,y-10],[560,y+10],[400,y+10]])])
                ui=Mock()
                self.assertTrue(cancel_special_equipment(ui,screen))
                self.assertEqual(ui.expect_click.call_args.args[0],button)
                self.assertEqual(ui.expect_click.call_count,1)

    def test_priorities_reject_unknown_category_stat_and_types(self):
        for value in (None, [], {'all': 'hp'}, {'armor': []}, {'armor': 'invented'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_auto_priorities(value)

    def test_priority_radio_needs_blue_center_not_outline_or_gray(self):
        image = np.full((540,960,3), 240, np.uint8)
        screen = EventScreen(image, [])
        self.assertFalse(selected_priority(screen, (290,195)))
        image[187:203,282:298]=(230,170,50)
        self.assertTrue(selected_priority(screen, (290,195)))
        image[187:203,282:298]=100
        self.assertFalse(selected_priority(screen, (290,195)))

    def priority_ui(self, *, visible=True, selected=True, readback=True):
        state=dict(page='settings', value='稀有度', radio=False)
        def capture():
            image=np.full((540,960,3),240,np.uint8)
            if state['page']=='settings':
                labels=[('自动特别装备设定',480,40),('防具',345,284),(state['value'],580,284)]
            else:
                labels=[('优先属性值',480,40)]
                if visible:
                    labels.append(('魔法防御力',365,195))
                if state['radio']:
                    image[187:203,282:298]=(230,170,50)
            return EventScreen(image,[TextBox(t,1,[[x-20,y-10],[x+20,y-10],[x+20,y+10],[x-20,y+10]])
                                      for t,x,y in labels])
        def wait(predicate, description, **kwargs):
            s=capture()
            if not predicate(s):
                raise EventUIError(description+'超时')
            return s
        def click(target):
            if isinstance(target,TextBox):
                state['page']='picker'
            else:
                state['radio']=selected
        def confirm(*args, **kwargs):
            state.update(page='settings', value='魔法防御力' if readback else '稀有度')
        ui=Mock(capture=capture, wait=wait, click=Mock(side_effect=click),
                expect_click=Mock(side_effect=confirm))
        return ui,capture()

    def test_priority_changes_only_requested_field_and_verifies_readback(self):
        ui,screen=self.priority_ui()
        result=configure_auto_priorities(ui,screen,{'armor':'magic_defense'})
        self.assertIsNotNone(result.find('魔法防御力',(480,264,690,304),exact=True))
        self.assertEqual(ui.click.call_args_list[-1].args,((290,195),))
        self.assertEqual(ui.expect_click.call_count,1)

    def test_unknown_radio_or_readback_stops_before_settings_confirmation(self):
        for options, confirmations in ((dict(visible=False),0),(dict(selected=False),0),(dict(readback=False),1)):
            with self.subTest(options=options):
                ui,screen=self.priority_ui(**options)
                with self.assertRaises(EventUIError):
                    configure_auto_priorities(ui,screen,{'armor':'magic_defense'})
                self.assertEqual(ui.expect_click.call_count,confirmations)

    def test_empty_priorities_preserve_saved_game_settings(self):
        ui,screen=self.priority_ui()
        self.assertIs(configure_auto_priorities(ui,screen,{}),screen)
        ui.click.assert_not_called()

    def test_unrecognized_auto_selection_cancels_preview_before_raising(self):
        state = dict(page='formation')
        titles = dict(formation='队伍编组', panel='特别装备设定',
                      settings='自动特别装备设定', preview='特别装备设定')
        def capture():
            labels = [(titles[state['page']], 480, 40)]
            if state['page'] == 'formation':
                labels.append(('特别装备', 615, 454))
            return EventScreen(np.full((540, 960, 3), 100, np.uint8), [
                TextBox(t, 1, [[x-20,y-10],[x+20,y-10],[x+20,y+10],[x-20,y+10]]) for t,x,y in labels])
        def wait(predicate, description, **kwargs):
            current = capture()
            self.assertTrue(predicate(current), description)
            return current
        def click(pattern, *args, **kwargs):
            transitions = {('panel', '自动装备'): 'settings', ('settings', '确认'): 'preview',
                           ('preview', '取消'): 'formation'}
            state['page'] = transitions[(state['page'], pattern)]
        ui = Mock(capture=capture, wait=wait)
        ui.click.side_effect = lambda pos: state.update(page='panel')
        ui.expect_click.side_effect = click
        selected = [[False]*3 for _ in range(5)]
        selected[0][0] = None
        with patch('pcrscript.game_ui.special_equipment.preview_slots', return_value=selected):
            with self.assertRaisesRegex(EventUIError, '未提交'):
                auto_equip_special(ui, ['合成角色'+str(i) for i in range(5)])
        self.assertEqual(state['page'], 'formation')
        self.assertEqual([c.args[0] for c in ui.expect_click.call_args_list], ['自动装备', '确认', '取消'])

    def test_dimmed_borrowed_item_is_resolved_against_empty_slot(self):
        before=np.full((540,960,3),100,np.uint8)
        preview=before.copy()
        x,y=SPECIAL_COLUMNS[0],SPECIAL_ROWS[0]
        preview[y-30:y+30,x-30:x+30]=160
        preview[y-30:y-27,x-30:x+30]=(50,50,200)
        self.assertIsNone(occupied_slots(preview)[0][0])
        states=preview_slots(before,preview,occupied_slots(before))
        self.assertIs(states[0][0],True)
        self.assertIs(states[1][0],False)
