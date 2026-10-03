"""Synthetic EX gear preview recognition; no account screenshots."""
from unittest import TestCase
from unittest.mock import Mock, patch
import numpy as np

from pcrscript.game_ui.screen import EventScreen, EventUIError, TextBox
from pcrscript.game_ui.special_equipment import (auto_equip_special, occupied_slots,
    preview_slots, SPECIAL_COLUMNS, SPECIAL_ROWS)


class SpecialEquipmentTests(TestCase):
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
