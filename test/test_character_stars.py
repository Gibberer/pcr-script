import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from types import SimpleNamespace
import numpy as np
from pcrscript.game_ui.character_stars import five_star_shards, unlocked_stars, active_stars, purchase_receipt, star_confirmation_ready, star_result_step
from pcrscript.game_ui.screen import EventUIError, EventScreen, TextBox


class StarBudgetTests(TestCase):
    def test_upgrade_animation_and_result_are_separate_steps(self):
        def screen(items):
            return EventScreen(np.zeros((540,960,3),np.uint8),[
                TextBox(text,1,[[x-8,y-8],[x+8,y-8],[x+8,y+8],[x-8,y+8]])
                for text,x,y in items])
        self.assertEqual(star_result_step(screen([('开花完成',480,397)])),'animation')
        result=star_result_step(screen([('才能开花完毕',480,42),('确认',480,478)]))
        self.assertEqual(result.text,'确认')
        self.assertIsNone(star_result_step(screen([('角色强化',100,40)])))

    def test_four_star_dialog_has_unlabeled_shard_icon(self):
        import cv2 as cv
        image=np.zeros((540,960,3),np.uint8)
        image[460:500,545:635]=cv.cvtColor(np.full((40,90,3),(105,220,230),np.uint8),cv.COLOR_HSV2BGR)
        entries=[('消耗玛那',98,280),('40,000',213,280),('904,602,092',370,280),
                 ('必要道具',98,315),('×120',100,390),('才能开花',588,478)]
        screen=EventScreen(image,[TextBox(text,1,[[x-8,y-8],[x+8,y-8],[x+8,y+8],[x-8,y+8]])
                                  for text,x,y in entries])
        self.assertTrue(star_confirmation_ready(screen,120))
        self.assertFalse(star_confirmation_ready(screen,150))
        screen.items[4].text='×.150'
        self.assertTrue(star_confirmation_ready(screen,150))

    def test_purchase_requires_matching_item_and_two_balance_deltas(self):
        entries=[('购买完毕',480,147),('消耗女神的秘石×555',480,205),
                 ('购买了静流（情人节）的记忆碎片×111。',480,225),
                 ('9',545,270),('120',672,270),('14,847',527,303),('14,292',660,303)]
        screen=EventScreen(np.zeros((540,960,3),np.uint8),[
            TextBox(text,1,[[x-8,y-8],[x+8,y-8],[x+8,y+8],[x-8,y+8]]) for text,x,y in entries])
        self.assertEqual(purchase_receipt(screen,'静流(情人节)',111,555,14847,9),
                         {'owned_after':120,'after':14292})
        with self.assertRaises(EventUIError):
            purchase_receipt(screen,'静流(情人节)',112,555,14847,9)

        zero_entries=[row for row in entries if row[0]!='9']
        zero_entries[3]=('150',672,270)
        zero_entries[4]=('14,292',527,303)
        zero_entries[5]=('13,542',660,303)
        zero_entries[1]=('消耗女神的秘石×750',480,205)
        zero_entries[2]=('购买了静流（情人节）的记忆碎片×150。',480,225)
        zero=EventScreen(np.zeros((540,960,3),np.uint8),[
            TextBox(text,1,[[x-8,y-8],[x+8,y-8],[x+8,y+8],[x-8,y+8]])
            for text,x,y in zero_entries])
        self.assertEqual(purchase_receipt(zero,'静流(情人节)',150,750,14292,0,
                                          lambda _screen,_roi:0),
                         {'owned_after':150,'after':13542})

    def test_blue_changed_stars_are_unlocked_without_being_active(self):
        image=np.zeros((540,960,3),np.uint8)
        for index,x in enumerate((171,212,253,294,335)):
            image[318:350,x-12:x+12]=(0,190,255) if index<3 else (255,150,0)
        screen=SimpleNamespace(image=image)
        self.assertEqual(unlocked_stars(screen),5)
        self.assertIs(type(unlocked_stars(screen)),int)
        self.assertEqual(active_stars(screen),3)

    def test_budget_ends_at_five_and_requires_live_next_cost(self):
        with TemporaryDirectory() as folder:
            db=str(Path(folder)/'test.db')
            with sqlite3.connect(db) as c:
                c.execute('CREATE TABLE unit_data(unit_id INTEGER,unit_name TEXT)')
                c.execute('CREATE TABLE unit_rarity(unit_id INTEGER,rarity INTEGER,consume_num INTEGER)')
                c.execute("INSERT INTO unit_data VALUES(1,'测试角色')")
                c.executemany('INSERT INTO unit_rarity VALUES(1,?,?)',[(4,12),(5,15),(6,50)])
            c.close()
            self.assertEqual(five_star_shards('测试角色',3,4,12,db),23)
            self.assertEqual(five_star_shards('测试角色',np.int64(3),4,12,db),23)
            with self.assertRaises(EventUIError):five_star_shards('测试角色',3,4,13,db)
            with self.assertRaises(EventUIError):five_star_shards('未知角色',3,4,12,db)
