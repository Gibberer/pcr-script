from .image import ImageTask
from pcrscript.actions import *

from .base import TimeLimitTask, EventNews
from .registry import register

@register("luna_tower_clean", requires_home=True)
class LunaTowerClean(ImageTask, TimeLimitTask):
    '''
    露娜塔 回廊扫荡
    '''

    @staticmethod
    def valid(event_news: EventNews, args=None) -> tuple:
        if LunaTowerClean.event_valid(event_news.tower) and not LunaTowerClean.event_first_day(event_news.tower):
            return LunaTowerClean, args

    def run(self):
        actions = [
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[ClickAction(template='btn_close'), ClickAction(pos=(50, 300))]),
            SleepAction(1),
            ClickAction(template="btn_luna_tower_entrance"),
            MatchAction(template="symbol_luna_tower"),
            SleepAction(2),
            MatchAction(template='symbol_luna_tower_lock',matched_actions=[ThrowErrorAction("回廊未解锁")],timeout=5),
            ClickAction(pos=(815, 375)),
            SleepAction(0.5),
            ClickAction(template='btn_ok_blue'),
            MatchAction(template='btn_skip_ok', matched_actions=[ClickAction()], timeout=2, delay=0.1),
            SleepAction(1),
            MatchAction(template='btn_ok', matched_actions=[ClickAction()], timeout=2, delay=0.1),
            SleepAction(1),
            MatchAction(template='btn_ok', matched_actions=[ClickAction(), SleepAction(1)], timeout=1),
            MatchAction(template='btn_ok', matched_actions=[ClickAction(), SleepAction(1)], timeout=1),
            MatchAction(template='btn_cancel', matched_actions=[ClickAction(), SleepAction(1)], timeout=1),
            ]
        self.action_squential(*actions)
