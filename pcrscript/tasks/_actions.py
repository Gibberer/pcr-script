from typing import TYPE_CHECKING

from ..constants import *
from pcrscript.actions import *
from ..templates import ImageTemplate

if TYPE_CHECKING:
    from pcrscript import Robot
    from ..strategist import Member

def _combat_actions(check_auto=False, combat_duration=35, interval=1):
    actions = []
    actions.append(ClickAction(template='btn_challenge'))
    actions.append(SleepAction(1))
    actions.append(ClickAction(template='btn_combat_start'))
    actions.append(MatchAction(template='btn_blue_settle',matched_actions=[ClickAction(),SleepAction(1),ClickAction(template='btn_combat_start')], timeout=5))
    actions.append(IfCondition('symbol_restore_power',
                               meet_actions=[
                                ClickAction(pos=(370, 370)),
                                SleepAction(2),
                                ClickAction(pos=(680, 454)),
                                SleepAction(2),
                                ThrowErrorAction("No power!!!")]))
    if check_auto:
        actions.append(MatchAction(template='btn_menu_text', matched_actions=[ClickAction(template='btn_speed'),
                                                                               ClickAction(template='btn_auto')], timeout=10))
    actions.append(SleepAction(combat_duration))
    actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
        ClickAction(template='btn_close'),ClickAction(template='btn_cancel'), ClickAction(pos=(200, 250))], delay=interval))
    actions.append(SleepAction(3))
    actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
        ClickAction(template='btn_close'),ClickAction(template='btn_cancel'),ClickAction(template='btn_ok_blue')]))
    actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
        ClickAction(template='btn_close'),ClickAction(template='btn_cancel'),ClickAction(template='btn_ok_blue')], timeout=3))
    return actions


def _clean_oneshot_actions(duration=0):
    return [
            MatchAction('btn_challenge'),
            SwipeAction((840, 360), (840, 360), duration) if duration > 0 else SleepAction(0.5),
            ClickAction(pos=(757, 360)),
            SleepAction(0.5),
            ClickAction(template='btn_ok_blue'),
            SleepAction(0.5),
            ClickAction(template='btn_skip_ok'),
            SleepAction(1),
            ClickAction(template='btn_ok'),
            SleepAction(1),
            MatchAction(template='btn_ok',
                        matched_actions=[ClickAction(), SleepAction(1)], timeout=1),
            MatchAction(template='btn_ok',
                        matched_actions=[ClickAction(), SleepAction(1)], timeout=1),
            MatchAction(template='btn_cancel', matched_actions=[
                ClickAction(), SleepAction(1)], timeout=1),  # 限时商店
            MatchAction(template='btn_cancel', matched_actions=[
                ClickAction(), SleepAction(1)], timeout=1),  # 可能有二次弹窗
            SleepAction(2),
            ClickAction(pos=(666, 457))
        ]


def _enter_adventure_actions(difficulty=Difficulty.NORMAL, campaign=False):
    actions = []
    actions.append(MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
        ClickAction(template='btn_close'), ClickAction(pos=(15, 200))]))
    actions.append(SleepAction(2))
    if campaign:
        actions.append(MatchAction(template=['story_campaign_symbol', 'story_campaign_reprint_symbol'], matched_actions=[ClickAction()]))
    else:
        actions.append(ClickAction(ImageTemplate('btn_main_plot',threshold=0.8*THRESHOLD)))
    actions.append(SleepAction(2))
    unmatch_actions = [ClickAction(ImageTemplate('btn_close', threshold=0.6)),
                       ClickAction('btn_skip_blue'),
                       ClickAction('btn_novocal_blue'),
                       ClickAction('symbol_menu_in_story'),
                       ClickAction('btn_skip_in_story')]
    if campaign:
        unmatch_actions += [
            IfCondition(ImageTemplate('symbol_campaign_home',threshold=0.8*THRESHOLD),
                        meet_actions=[ClickAction(pos=(560, 170))],
                        unmeet_actions=[ClickAction(pos=(15, 200))])]
    if difficulty == Difficulty.NORMAL:
        unmatch_actions = [ClickAction(
            template=ImageTemplate('btn_normal', threshold=0.9))] + unmatch_actions
        actions.append(MatchAction('btn_normal_selected',
                                   unmatch_actions=unmatch_actions))
    elif difficulty == Difficulty.HARD:
        unmatch_actions = [ClickAction(
            template=ImageTemplate("btn_hard", threshold=0.9))] + unmatch_actions
        actions.append(MatchAction('btn_hard_selected',
                                   unmatch_actions=unmatch_actions))
    else:
        unmatch_actions = [ClickAction(
            template=ImageTemplate("btn_very_hard", threshold=0.9))] + unmatch_actions
        actions.append(MatchAction('btn_very_hard_selected',
                                   unmatch_actions=unmatch_actions))
    return actions
