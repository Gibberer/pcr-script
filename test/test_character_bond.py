from unittest import TestCase
from unittest.mock import Mock

import numpy as np

from pcrscript.game_ui.screen import EventScreen, TextBox
from pcrscript.tasks.task_character_bond import gift_grades, gift_counts, verified_gift_counts, locked_story, MaxCharacterBonds
from pcrscript.game_ui.screen import EventUIError


def item(text, x, y):
    return TextBox(text, 1.0, [[x-8, y-8], [x+8, y-8], [x+8, y+8], [x-8, y+8]])


class StoryDevice:
    """Retained bottom viewport with a lock and an unread episode above it."""
    def __init__(self, *, unread=True, remains_locked=True):
        self.page=2;self.state='list';self.unread=unread;self.remains_locked=remains_locked
        self.opened=0;self.requirements=0;self.swipes=[]
    def capture(self):
        image=np.full((540,960,3),225+10*self.page,np.uint8)
        if self.state=='requirement':
            return EventScreen(image,[item('解锁条件',480,140),item('阅读合成主线剧情',480,220)])
        if self.state=='reward':
            return EventScreen(image,[item('报酬确认',480,70),item('合成首读奖励',480,220)])
        labels=[item('角色剧情',480,42),item('第'+str(self.page+1)+'话',430,145)]
        if self.page==0 and self.unread:labels.append(item('新内容',450,120))
        if self.page==2 and (self.unread or self.remains_locked):
            image[122:165,260:300]=(20,190,245)
            image[160:190,555:605]=(150,150,150)
        return EventScreen(image,labels)
    def wait(self,predicate,*args,**kwargs):
        value=self.capture()
        if not predicate(value):raise EventUIError('unexpected synthetic story page')
        return value
    def click(self,point,**kwargs):
        assert self.state=='list'
        if self.page==0 and self.unread:
            self.opened+=1;self.unread=False;self.state='reward'
        elif self.page==2:
            self.requirements+=1;self.state='requirement'
        else:raise AssertionError(point)
    def expect_click(self,pattern,*args,**kwargs):
        assert pattern=='关闭' and self.state in ('reward','requirement')
        self.state='list'
        self.page=2
    def swipe(self,start,end):
        assert self.state=='list'
        self.swipes.append((start,end))
        self.page=max(0,self.page-1) if end[1]>start[1] else min(2,self.page+1)
    def save(self,*args):return 'synthetic-story.png'


class StoryScanningTests(TestCase):
    def read(self,device):
        task=MaxCharacterBonds.__new__(MaxCharacterBonds)
        task.options={'max_story_steps_per_character':50}
        task.report=dict(pending=[],stories_read=[])
        task.check=Mock();task.save=Mock();task.ui=device
        record=dict(name='合成角色')
        task.read_stories(record)
        return task,record
    def test_retained_locked_bottom_does_not_skip_unread_episode_above(self):
        device=StoryDevice()
        task,record=self.read(device)
        self.assertEqual((device.opened,len(task.report['stories_read'])),(1,1))
        self.assertEqual(record['stories'],'blocked_by_prerequisite')
        self.assertEqual(record['story_requirements'][0]['episode'],'第3话')
        self.assertEqual(len(task.report['pending']),1)
        self.assertTrue(any(end[1]>start[1] for start,end in device.swipes))
        self.assertTrue(any(end[1]<start[1] for start,end in device.swipes))
    def test_only_locked_episode_is_reported_after_scanning_both_boundaries(self):
        device=StoryDevice(unread=False)
        task,record=self.read(device)
        self.assertEqual((device.opened,device.requirements),(0,1))
        self.assertEqual(record['stories'],'blocked_by_prerequisite')
        self.assertEqual(len(task.report['pending']),1)
        self.assertGreaterEqual(len(device.swipes),6)
    def test_lock_disappearing_after_read_does_not_leave_a_stale_prerequisite(self):
        device=StoryDevice(remains_locked=False)
        task,record=self.read(device)
        self.assertEqual((device.opened,len(task.report['stories_read'])),(1,1))
        self.assertEqual(record['stories'],'checked_to_end')
        self.assertNotIn('story_requirements',record)
        self.assertEqual(task.report['pending'],[])


class GiftPreviewTests(TestCase):
    def test_story_lock_requires_both_gold_lock_and_episode_label(self):
        image=np.zeros((540,960,3),np.uint8)
        image[122:165,260:300]=(20,190,245)
        image[160:190,555:605]=(150,150,150)
        episode=item('第1话',430,145)
        self.assertIs(locked_story(EventScreen(image,[episode])),episode)
        self.assertIsNone(locked_story(EventScreen(image,[])))
        self.assertIsNone(locked_story(EventScreen(np.zeros_like(image),[episode])))

    def test_gold_avatar_on_enabled_story_card_is_not_a_lock(self):
        image=np.full((540,960,3),255,np.uint8)
        image[122:165,260:300]=(20,190,245)
        self.assertIsNone(locked_story(EventScreen(image,[item('第1话',430,145)])))
    def task(self,options=None):
        task=MaxCharacterBonds.__new__(MaxCharacterBonds)
        task.options=options or {}
        task.report=dict(gifts_spent=[])
        return task

    def test_targeted_scope_preserves_exact_costumes_and_rejects_ambiguity(self):
        self.assertEqual(self.task({'focus_characters':['合成甲(夏日)','合成乙']}).focused_characters(),
                         ['合成甲(夏日)','合成乙'])
        for value in ([], '合成甲', [''], ['合成甲','合成甲']):
            with self.subTest(value=value),self.assertRaises(EventUIError):
                self.task({'focus_characters':value}).focused_characters()
        with self.assertRaises(EventUIError):
            self.task({'focus_character':'合成甲','focus_characters':['合成乙']}).focused_characters()

    def test_total_budget_includes_pending_and_confirmed_gifts_before_consumption(self):
        task=self.task({'max_gifts_total':100})
        task.report['gifts_spent']=[dict(status='confirmed',counts=[40]),dict(status='pending',counts=[30])]
        task.require_gift_budget([10,20])
        with self.assertRaises(EventUIError):task.require_gift_budget([31])
        with self.assertRaises(EventUIError):self.task({'max_gifts_total':True}).require_gift_budget([1])

    def test_gift_scope_is_separate_from_story_scope(self):
        task=self.task({'focus_characters':['合成甲','合成乙'], 'gift_characters':['合成乙']})
        self.assertEqual(task.gift_characters(task.focused_characters()),['合成乙'])
        task.options['gift_characters']=[]
        self.assertEqual(task.gift_characters(task.focused_characters()),[])
        for value in (['合成丙'], ['合成乙','合成乙'], '合成乙', [None]):
            task.options['gift_characters']=value
            with self.subTest(value=value),self.assertRaises(EventUIError):
                task.gift_characters(task.focused_characters())

    def test_story_only_member_cannot_enter_gift_flow(self):
        task=self.task({'gift_characters':['合成乙']})
        task.focus_character='合成甲'
        task.attempted=set();task.report.update(characters=[])
        task.detail=Mock();task.story_list=Mock();task.ui=Mock();task.save=Mock()
        task.give_gifts=Mock();task.read_stories=Mock();task.return_to_roster=Mock()
        task.process_detail()
        task.give_gifts.assert_not_called()
        task.read_stories.assert_called_once()
    def test_reads_two_distinct_levels_and_each_consumed_stack(self):
        screen = EventScreen(np.zeros((540, 960, 3), dtype=np.uint8), [
            item('品级1', 340, 225), item('品级8', 540, 225),
            item('×96', 405, 374), item('×162', 485, 374),
        ])
        self.assertEqual(gift_grades(screen), (1, 8))
        self.assertEqual(gift_counts(screen), [96, 162])

    def test_missing_level_or_cost_remains_unknown(self):
        screen = EventScreen(np.zeros((540, 960, 3), dtype=np.uint8), [item('品级8', 540, 225)])
        self.assertIsNone(gift_grades(screen))
        self.assertEqual(gift_counts(screen), [])

    def test_small_gift_count_requires_localized_read_of_visible_icon(self):
        image = np.zeros((540, 960, 3), dtype=np.uint8)
        image[326:367, 363:417] = (20, 50, 230)
        screen = EventScreen(image, [])
        ui = Mock(read_region=Mock(return_value=EventScreen(image, [item('x140', 405, 376)])))
        self.assertEqual(verified_gift_counts(ui, screen), [140])
        ui.read_region.assert_called_once()

    def test_low_confidence_count_retries_tighter_crop_without_lowering_threshold(self):
        image = np.zeros((540, 960, 3), dtype=np.uint8)
        image[326:367, 503:557] = (20, 50, 230)
        screen = EventScreen(image, [])
        weak = item('x28', 545, 376); weak.score = .79
        good = item('x28', 545, 376)
        ui = Mock(read_region=Mock(side_effect=[EventScreen(image, [weak]), EventScreen(image, [good])]))
        self.assertEqual(verified_gift_counts(ui, screen), [28])
        self.assertEqual(ui.read_region.call_count, 2)
        ui.read_region = Mock(return_value=EventScreen(image, [weak]))
        self.assertEqual(verified_gift_counts(ui, screen), [])

    def test_single_item_count_can_be_verified_in_short_label_crop(self):
        image = np.zeros((540, 960, 3), dtype=np.uint8)
        image[326:367, 363:417] = (20, 50, 230)
        screen = EventScreen(image, [])
        good = item('x1', 405, 376)
        ui = Mock(read_region=Mock(side_effect=[EventScreen(image, []),
                    EventScreen(image, []), EventScreen(image, [good])]))
        self.assertEqual(verified_gift_counts(ui, screen), [1])
        self.assertEqual(ui.read_region.call_count, 3)
