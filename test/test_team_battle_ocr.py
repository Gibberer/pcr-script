"""Opt-in real OCR on generated numbers and banners; no account screenshots."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import cv2 as cv
import numpy as np

from pcrscript.game_ui.screen import EventScreen, EventUI, TextBox
from pcrscript.game_ui.team_battle import Boss, boss_detail, can_repeat, parse_remaining_time
from pcrscript.game_ui.team_battle_filter import restricted_cards


@unittest.skipUnless(os.environ.get('PCR_REAL_OCR_TEST') == '1', 'set PCR_REAL_OCR_TEST=1 for real OCR')
class TeamBattleOCRTests(unittest.TestCase):
    def test_generated_hidden_banners_use_actual_packed_ocr(self):
        from PIL import Image, ImageDraw, ImageFont
        fonts = ('C:/Windows/Fonts/msyh.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
        font_path = next((path for path in fonts if Path(path).is_file()), None)
        if font_path is None:
            self.skipTest('Chinese fixture font unavailable')
        image = Image.new('RGB',(960,540),(240,240,240))
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(font_path,13)
        positions = [(90,176),(192,176),(294,176)]
        for x,y in positions[:2]:
            draw.rectangle((x-44,y+22,x+43,y+46),fill=(55,80,155))
            draw.text((x-40,y+25),'限制实战使用',fill='white',font=font)
        with TemporaryDirectory() as folder:
            ui = EventUI(None,folder)
            ui.observe(np.asarray(image)[:,:,::-1].copy())
            # Full-frame text intentionally omitted: the actual packed crop
            # must recover both badges and keep the blank third strip absent.
            screen = EventScreen(ui.last.image,[])
            self.assertEqual(restricted_cards(ui,screen,positions),positions[:2])

    def test_generated_hp_and_return_times_through_real_engine(self):
        with TemporaryDirectory() as folder:
            ui = EventUI(None, folder)
            image = np.full((540, 960, 3), 240, np.uint8)
            cv.putText(image, '90000000/90000000', (492, 322), cv.FONT_HERSHEY_SIMPLEX,
                       .57, (20, 20, 20), 1, cv.LINE_AA)
            # Initialize the production engine; numeric reads below use its
            # actual detection/recognition models, not prefilled numeric boxes.
            ui.observe(image)
            headings = [TextBox(text, 1.0, [[x-30,y-10],[x+30,y-10],[x+30,y+10],[x-30,y+10]])
                        for text, x, y in [('魔物详情',105,42), ('合成首领',330,282)]]
            boss = boss_detail(EventScreen(image, headings), Boss(2, 1, 480), ui)
            self.assertEqual((boss.current_hp, boss.maximum_hp), (90_000_000, 90_000_000))
            for seconds, allowed in ((50, False), (58, False), (59, True), (77, True), (90, True)):
                with self.subTest(seconds=seconds):
                    frame = np.full_like(image, 240)
                    cv.putText(frame, f'{seconds//60}:{seconds%60:02d}', (835, 462),
                               cv.FONT_HERSHEY_SIMPLEX, .7, (20, 20, 20), 1, cv.LINE_AA)
                    returned = parse_remaining_time(EventScreen(frame, []), ui)
                    self.assertEqual(returned, seconds)
                    self.assertEqual(can_repeat(returned), allowed)
