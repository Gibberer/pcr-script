"""Synthetic EX gear preview recognition; no account screenshots."""
from unittest import TestCase
import numpy as np

from pcrscript.game_ui.special_equipment import occupied_slots, preview_slots, SPECIAL_COLUMNS, SPECIAL_ROWS


class SpecialEquipmentTests(TestCase):
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
