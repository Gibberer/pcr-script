import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock
from types import SimpleNamespace
import numpy as np
from pcrscript.game_ui.character_stars import five_star_shards, unlocked_stars, active_stars, purchase_receipt, price_tier_notice, star_confirmation_ready, star_result_step, star_upgrade_settled, buy_shards, reduce_purchase_amount
from pcrscript.game_ui.screen import EventUIError, EventScreen, TextBox


class StarBudgetTests(TestCase):
    def test_max_purchase_is_reduced_to_exact_missing_shards(self):
        def dialog(amount):
            rows=[('购买确认',480,42),('珠希(夏日)的记忆碎片',350,125),
                  ('重置',315,310),('MAX',645,310),(str(amount),480,310)]
            return EventScreen(np.zeros((540,960,3),np.uint8),[
                TextBox(text,1,[[x-8,y-8],[x+8,y-8],[x+8,y+8],[x-8,y+8]])
                for text,x,y in rows])
        ui=Mock();ui.capture.side_effect=[dialog(n) for n in range(19,9,-1)]
        result,amount=reduce_purchase_amount(ui,dialog(20),'珠希(夏日)',20,10)
        self.assertEqual(amount,10)
        self.assertEqual(result.find('10',(440,290,520,329),exact=True).text,'10')
        self.assertEqual(ui.click.call_count,10)
        ui=Mock();ui.capture.return_value=dialog(20)
        with self.assertRaisesRegex(EventUIError,'递减未核实'):
            reduce_purchase_amount(ui,dialog(20),'珠希(夏日)',20,10)

    def test_price_tier_notice_requires_same_outfit_and_explicit_price(self):
        def notice(name):
            rows=[('确认所需的女神的秘石个数',480,145),
                  (name+'的',480,240),('记忆碎片的已购数量变为20。',480,260),
                  ('1个对象道具的单价2个了。',480,280),('确认',480,370)]
            return EventScreen(np.zeros((540,960,3),np.uint8),[
                TextBox(text,1,[[x-8,y-8],[x+8,y-8],[x+8,y+8],[x-8,y+8]])
                for text,x,y in rows])
        self.assertEqual(price_tier_notice(notice('未奏希(夏日)'),'未奏希(夏日)').text,'确认')
        with self.assertRaises(EventUIError):
            price_tier_notice(notice('未奏希(夏日)'),'静流(情人节)')

    def test_shard_source_scrolls_until_exact_shop_entry(self):
        def source(show_shop):
            rows=[('记忆碎片获取方法',480,40),('未奏希(夏日)的记忆碎片',375,115)]
            if show_shop:rows.append(('女神的秘石商店',440,345))
            return EventScreen(np.zeros((540,960,3),np.uint8),[
                TextBox(text,1,[[x-8,y-8],[x+8,y-8],[x+8,y+8],[x-8,y+8]])
                for text,x,y in rows])
        ui=Mock()
        ui.capture.side_effect=[source(False),source(True)]
        ui.wait.side_effect=[source(False),EventUIError('shop reached')]
        with self.assertRaisesRegex(EventUIError,'shop reached'):
            buy_shards(ui,'未奏希(夏日)',77,{},lambda:None,True)
        ui.swipe.assert_called_once_with((600,405),(600,300))
        self.assertEqual(ui.click.call_args.args[0].text,'女神的秘石商店')

    def test_upgrade_animation_and_result_are_separate_steps(self):
        def screen(items):
            return EventScreen(np.zeros((540,960,3),np.uint8),[
                TextBox(text,1,[[x-8,y-8],[x+8,y-8],[x+8,y+8],[x-8,y+8]])
                for text,x,y in items])
        self.assertEqual(star_result_step(screen([('开花完成',480,397)])),'animation')
        result=star_result_step(screen([('才能开花完毕',480,42),('确认',480,478)]))
        self.assertEqual(result.text,'确认')
        self.assertIsNone(star_result_step(screen([('角色强化',100,40)])))

    def test_upgrade_result_must_be_dismissed_before_star_count_commits(self):
        image=np.zeros((540,960,3),np.uint8)
        for x in (171,212,253):image[318:350,x-12:x+12]=(0,190,255)
        def result(title):
            return EventScreen(image,[TextBox(title,1,[[80,30],[140,30],[140,50],[80,50]])])
        role=result('角色强化')
        self.assertFalse(star_upgrade_settled(role,3,False))
        self.assertTrue(star_upgrade_settled(role,3,True))
        popup=EventScreen(image,[TextBox('角色强化',1,[[80,30],[140,30],[140,50],[80,50]]),
                                 TextBox('才能开花完毕',1,[[400,30],[560,30],[560,55],[400,55]]),
                                 TextBox('确认',1,[[450,460],[510,460],[510,500],[450,500]])])
        self.assertFalse(star_upgrade_settled(popup,3,True))

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
        screen.items[4].text='1×.150'
        self.assertTrue(star_confirmation_ready(screen,150))
        self.assertFalse(star_confirmation_ready(screen,120))

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
        small=EventScreen(np.zeros((540,960,3),np.uint8),[
            TextBox(text,1,[[x-8,y-8],[x+8,y-8],[x+8,y+8],[x-8,y+8]])
            for text,x,y in [('购买完毕',480,147),('消耗女神的秘石×33',480,205),
                ('购买了栞（游骑兵）的记忆碎片×11。',480,225),
                ('13,233',527,303),('13,200',660,303)]])
        self.assertEqual(purchase_receipt(small,'栞(游骑兵)',11,33,13233,0,
                         lambda _screen,roi:0 if roi[0]<600 else 11),
                         {'owned_after':11,'after':13200})
        with self.assertRaises(EventUIError):
            purchase_receipt(small,'栞(游骑兵)',11,33,13233,0,
                             lambda _screen,roi:0 if roi[0]<600 else 12)

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
