from unittest import TestCase
import numpy as np

from pcrscript.game_ui.battle_status import portrait_states


class BattlePortraitTests(TestCase):
    portraits = [(196,400,282,485),(315,400,402,485),(438,400,522,485),
                 (557,400,643,485),(678,400,763,485)]

    def frame(self, *, fallen=(), dark_living=(), obscured=()):
        image=np.zeros((540,960,3),np.uint8)
        for index,(x1,y1,x2,y2) in enumerate(self.portraits):
            image[y1:y2,x1:x2]=(80,100,180)
            image[y2+10:y2+22,x1:x2]=30
            image[y2+10:y2+12,x1:x2]=220
            if index in fallen or index in dark_living:
                # KO faces stay colored; saturation is deliberately high.
                image[y1:y2,x1:x2]=(25,45,95)
            if index not in fallen:
                image[y2+13:y2+19,x1:x1+2]=(30,190,60)
            if index in obscured:
                image[y1:y2+22,x1:x2]=255
        return image

    def test_colored_fallen_portraits_have_empty_hp_bars(self):
        self.assertEqual(portrait_states(self.frame(fallen=(0,1,3)),self.portraits),
                         dict(living=[2,4],fallen=[0,1,3]))

    def test_dark_opening_and_minimum_visible_hp_are_alive(self):
        state=portrait_states(self.frame(dark_living=range(5)),self.portraits)
        self.assertEqual(state,dict(living=list(range(5)),fallen=[]))

    def test_bright_flash_or_missing_hp_bar_never_proves_survival(self):
        state=portrait_states(self.frame(obscured=(0,3)),self.portraits)
        self.assertEqual(state,dict(living=[1,2,4],fallen=[]))
        self.assertEqual(portrait_states(np.zeros((540,960,3),np.uint8),self.portraits),
                         dict(living=[],fallen=[]))

    def test_crop_outside_frame_is_unknown(self):
        self.assertEqual(portrait_states(np.zeros((10,10,3),np.uint8),self.portraits),
                         dict(living=[],fallen=[]))
