"""Synthetic slot details; no account screenshots or device operations."""
from unittest import TestCase
from unittest.mock import Mock, patch
import cv2 as cv

from pcrscript.game_ui.ordinary_equipment import (SLOT_CENTERS, selected_slot,
    slot_fields, summarize_slots, read_slot_fields, inspect_ordinary_equipment)
from pcrscript.game_ui.screen import EventUIError
from test_dawn_labyrinth import screen


def slot(index, state='equipped'):
    value = screen(('角色强化', 125, 30), ('装备', 505, 75), ('一键装备', 250, 337),
                   ('38', 423, 398), ('365', 278, 426))
    value.image[:] = (80, 80, 80)
    x, y = SLOT_CENTERS[index]
    for left, top in ((x-40,y-41),(x+22,y-41),(x-40,y+19),(x+22,y+19)):
        cv.line(value.image, (left,top), (left+16,top), (255,255,255), 4)
        cv.line(value.image, (left,top), (left,top+16), (255,255,255), 4)
    if state == 'future':
        value.items += screen(('这件装备预定今后登场。', 695, 330), ('装备', 810, 437)).items
    else:
        value.items += screen(('合成装备R', 550, 127), ('装备属性值', 540, 263),
                              ('强化' if state == 'equipped' else '装备', 810, 437)).items
    return value


class OrdinaryEquipmentTests(TestCase):
    def test_details_belong_to_the_selected_slot_and_unknown_or_weak_text_stays_unknown(self):
        for i in range(6):
            value = slot(i)
            self.assertTrue(selected_slot(value,i))
            self.assertFalse(selected_slot(value,(i+1)%6))
            self.assertTrue(slot_fields(value,i)['equipped'])
            self.assertIsNone(slot_fields(value,(i+1)%6))
            value.items[-1].score = .94
            self.assertIsNone(slot_fields(value,i))

    def test_future_slot_is_distinct_from_available_empty_slot(self):
        future, empty = slot_fields(slot(0,'future'),0), slot_fields(slot(1,'empty'),1)
        self.assertEqual((future['available'],future['equipped']), (False,False))
        self.assertEqual((empty['available'],empty['equipped']), (True,False))

    def test_four_open_slots_are_complete_but_missing_or_duplicate_details_cannot_be_summarized(self):
        rows = [slot_fields(slot(i,'future' if i<2 else 'equipped'),i) for i in range(6)]
        self.assertEqual(summarize_slots(rows), dict(equipment=4,equipment_available=4))
        rows[2]['equipped'] = False
        self.assertEqual(summarize_slots(rows)['equipment'],3)
        for invalid in (rows[:-1], rows[:-1]+[rows[0]], rows+[rows[0]], [None]*6):
            with self.assertRaises(EventUIError):
                summarize_slots(invalid)

    def test_local_title_reread_keeps_slot_selection_and_other_live_evidence(self):
        value = slot(2)
        value.items[-3].score = .9
        ui = Mock(read_region=Mock(return_value=screen(('合成装备R',550,127))))
        self.assertTrue(read_slot_fields(ui,value,2)['equipped'])
        ui.read_region.assert_called_once()
        ui.read_region.return_value.items[0].score = .94
        self.assertIsNone(read_slot_fields(ui,value,2))

    def test_known_maximum_enhancement_proves_installed_slot_without_inventing_item_name(self):
        value = slot(4)
        value.items[-3].score = .9
        value.items += screen(('这件装备的强化阶段已达极限。',695,388)).items
        fields = slot_fields(value,4)
        self.assertTrue(fields['available'])
        self.assertTrue(fields['equipped'])
        self.assertIsNone(fields['name'])
        value.items[-1].score = .94
        self.assertIsNone(slot_fields(value,4))

    def test_reader_visits_each_slot_without_equipping_and_rejects_changed_rank(self):
        frames = [slot(i,'future' if i<2 else 'equipped') for i in range(6)]
        ui = Mock(capture=Mock(return_value=frames[0]), save=Mock(return_value='synthetic.png'))
        ui.number.side_effect = lambda s,roi: s.number(roi)
        ui.wait.side_effect = [frames[0]]+frames
        with patch('pcrscript.game_ui.ordinary_equipment.open_character_memory',return_value=frames[0]):
            result = inspect_ordinary_equipment(ui,'合成角色')
        self.assertEqual(result['values'],dict(equipment=4,equipment_available=4))
        self.assertEqual([call.args[0] for call in ui.click.call_args_list], list(SLOT_CENTERS))
        ui.expect_click.assert_called_once_with('装备',(465,55,545,95),exact=True)
        ui.wait.side_effect = [frames[0]]+frames
        changed = slot(0,'future'); changed.items[3].text = '37'
        ui.wait.side_effect = [frames[0],changed]
        with patch('pcrscript.game_ui.ordinary_equipment.open_character_memory',return_value=frames[0]), \
                self.assertRaisesRegex(EventUIError,'发生变化'):
            inspect_ordinary_equipment(ui,'合成角色')
