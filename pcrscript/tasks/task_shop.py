from .image import ImageTask
import copy
from typing import TYPE_CHECKING
import collections

from ..constants import *
from pcrscript.actions import *

if TYPE_CHECKING:
    from pcrscript import Robot

from .registry import register

@register("shop_buy", requires_home=True)
class ShopBuy(ImageTask):
    '''
    商店购买药水、道具等
    '''

    def run(self, rule:dict):
        '''
        rule: 购买规则
        '''
        actions = []
        # 首先进入商店页
        actions.append(ClickAction(template='shop'))
        actions.append(MatchAction(template='symbol_shop', unmatch_actions=[
                       ClickAction(pos=(77, 258)), ClickAction(template='shop')]))
        actions.append(SleepAction(1))
        tabs = collections.defaultdict(dict)
        for key, value in rule.items():
            if isinstance(key, int):
                tabs[key]['items'] = value
            else:
                tabs[int(key.split("_")[0])].update(value)
        Item = collections.namedtuple(
            "Item", ["pos", "threshold"], defaults=[0, -1])
        times = collections.defaultdict(int)
        item_total_count = collections.defaultdict(lambda:-1)
        for key in tabs:
            value = tabs[key]
            tabs[key] = []
            items = tabs[key]
            if 'items' in value:
                for normal_item in value['items']:
                    items.append(Item(normal_item))
            items.sort(key=lambda item: item.pos)
            if 'time' in value:
                times[key] = value['time']
            if 'total_item_count' in value:
                item_total_count[key] = value['total_item_count']
        for tab, items in tabs.items():
            tab_main_actions = []

            tab_actions = []

            line_count = 4
            line = 1
            slow_swipe = False
            for item in items:
                if item.threshold > 0:
                    slow_swipe = True
                    break
            last_line = 100000
            if slow_swipe:
                last_line = item_total_count[tab]
            for item in items:
                swipe_time = 0
                if item.pos > line * line_count:
                    for _ in range(int((item.pos - line * line_count - 1) / line_count) + 1):
                        if slow_swipe:
                            tab_actions += [
                                SwipeAction(start=(580, 377),
                                            end=(580, 114), duration=5000),
                                SleepAction(1)
                            ]
                        else:
                            tab_actions += [
                                SwipeAction(start=(580, 380),
                                            end=(580, 180), duration=300),
                                SleepAction(1)
                            ]
                        line += 1
                        swipe_time += 1
                if tab in (1, 9) and item.pos < 0:
                    click_pos = (860,126) # 全选按钮
                elif line == last_line:
                    click_pos = SHOP_ITEM_LOCATION_FOR_LAST_LINE[(
                        item.pos - 1) % line_count]
                else:
                    click_pos = SHOP_ITEM_LOCATION[(item.pos - 1) % line_count]

                if item.threshold <= 0:
                    if tab in (1, 9):
                        tab_actions += [
                            ClickAction(pos=(690, 125)),
                            SleepAction(0.5),
                        ]
                    tab_actions += [
                        ClickAction(pos=click_pos),
                        SleepAction(0.1)
                    ]
                else:
                    def condition_function(screenshot, item, click_pos):
                        return False

                    tab_actions += [
                        SleepAction(swipe_time * 1 + 1),
                        CustomIfCondition(condition_function, item, click_pos, meet_actions=[
                                          ClickAction(pos=click_pos)]),
                        SleepAction(0.8),
                    ]
            tab_actions += [
                ClickAction(pos=(700, 438)),
                SleepAction(0.2),
                MatchAction(template='btn_ok_blue',matched_actions=[ClickAction()], timeout=2),
                SleepAction(1.5),
                MatchAction(template='btn_ok_blue',matched_actions=[ClickAction()], timeout=2),
                SleepAction(1.5)
            ]
            tab_main_actions += tab_actions
            if times[tab]:
                for _ in range(times[tab] - 1):
                    copy_tab_actions = [
                        ClickAction(pos=(550, 440)),
                        SleepAction(0.2),
                        ClickAction(template='btn_ok_blue'),
                        SleepAction(1)
                    ]
                    copy_tab_actions += copy.deepcopy(tab_actions)
                    tab_main_actions += copy_tab_actions
            actions += [
                ClickAction(pos=SHOP_TAB_LOCATION[tab - 1]),
                SleepAction(1)
            ]
            actions += tab_main_actions
        self.action_squential(*actions)
