from .image import ImageTask
from pcrscript.run_session import clock as time
from typing import TYPE_CHECKING
import numpy as np
import sqlite3
import os

from ..constants import *
from pcrscript.actions import *
from ..templates import ImageTemplate, CharaIconTemplate, BrightnessTemplate

if TYPE_CHECKING:
    from pcrscript import Robot
    from ..strategist import Member


class TeamFormation(ImageTask):
    '''
    设置队伍编组
    '''
    current_team_region = (30, 400, 590, 510)
    current_team_region_separated = [
        (47,405,147,500),
        (156,405,252,500),
        (267,405,364,500),
        (376,405,471,500),
        (486,405,580,500),
    ]
    chara_mapping = None

    def _gen_chara_mapping(self):
        if TeamFormation.chara_mapping:
            return TeamFormation.chara_mapping
        ret = {}
        try:
            db_potential = "cache/redive_cn.db"
            if not os.path.exists(db_potential):
                from .news import fetch_event_news
                fetch_event_news()
            with sqlite3.connect(db_potential) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT unit_id, unit_name FROM unit_profile")
                for id, name in cursor.fetchall():
                    ret[int(id/100)] = name
                cursor.close()
                TeamFormation.chara_mapping = ret
        except Exception as e:
            print("获取角色名失败", e)
        return ret

    def _in_team_formation(self):
        for _ in range(3):
            screenshot = self.driver.screenshot()
            if self.template_match(screenshot, ImageTemplate("symbol_team_formation")):
                return True
            time.sleep(2)

    def _check_current_form(self, form:list['Member'])->tuple[list[int], list[int]]:
        screenshot = self.driver.screenshot()
        h,w,_ = screenshot.shape
        mask = np.zeros((h,w), dtype=np.uint8)
        team_region = self.adapted_region(TeamFormation.current_team_region, w, h)
        mask[team_region[1]:team_region[3],team_region[0]:team_region[2]] = 0xFF
        add_ids = [mem.id for mem in form]
        remove_regions = [self.adapted_region(region, w, h) for region in TeamFormation.current_team_region_separated]
        for index in range(len(add_ids)-1,-1,-1):
            id = add_ids[index]
            pos = self.template_match(screenshot, CharaIconTemplate(id, mask=mask))
            if pos:
                add_ids.pop()
                for i, region in enumerate(remove_regions):
                    if self.in_region(region, pos):
                        remove_regions.pop(i)
                        break
        return add_ids, remove_regions

    def run(self, formation:list['Member'])->bool:
        if not formation:
            print("未设置期望编组")
            return
        if not self._in_team_formation():
            print("未在编队界面")
            return
        add_ids, remove_regions = self._check_current_form(formation)
        for region in remove_regions:
            pos = self.center_region(region)
            self.driver.click(*pos)
            time.sleep(0.5)
        if add_ids:
            # 使用搜索功能
            self.set_progress(total_step=2*len(add_ids))
            name_mapping = self._gen_chara_mapping()
            self.action_squential(SwipeAction(start=(480, 150), end=(480,350)), SleepAction(1))
            for id in add_ids:
                self.action_squential(
                    ClickAction(pos=(480, 135)),
                    SleepAction(0.5),
                    InputAction(name_mapping[id]),
                    SleepAction(0.5),
                    ClickAction(pos=(110, 220)), # 丧失焦点
                    SleepAction(0.5),
                    ClickAction(template=CharaIconTemplate(id)), # 选择匹配人物
                    ClickAction(pos=(690, 135)),
                )
        add_ids, remove_regions = self._check_current_form(formation)
        if add_ids or remove_regions:
            # 如果还存在需要操作的步骤说明未变更为预期队伍组合，可能账号没有预期编队的角色。
            return False
        return True


class TeamFormationEx(TeamFormation):
    '''
    多个队伍编队
    '''

    def run(self, formations:list[list['Member']]):
        if not formations:
            print("未设置期望编组")
            return
        if not self._in_team_formation():
            print("未在编队界面")
            return
        self.set_progress(total_step="∞")

        for i in range(len(formations)):
            for region in TeamFormationEx.current_team_region_separated:
                pos = self.center_region(region)
                self.driver.click(*pos)
                time.sleep(0.5)
            if i + 1 < len(formations):
                self.action_squential(
                    ClickAction(pos=(834, 448)),
                    SleepAction(1),
                )
        for _ in range(len(formations) - 1):
            self.action_squential(
                ClickAction(pos=(673, 441)),
                SleepAction(1),
            )

        for i,formation in enumerate(formations):
            member = formation[0]
            if member.id >= 1000:
                add_ids, remove_regions = self._check_current_form(formation)
                for region in remove_regions:
                    pos = self.center_region(region)
                    self.driver.click(*pos)
                    time.sleep(0.5)
                if add_ids:
                    # 使用搜索功能
                    name_mapping = self._gen_chara_mapping()
                    self.action_squential(SwipeAction(start=(480, 185), end=(480,350)), SleepAction(1))
                    for id in add_ids:
                        self.action_squential(
                            ClickAction(pos=(480, 200)),
                            SleepAction(0.5),
                            InputAction(name_mapping[id]),
                            SleepAction(0.5),
                            ClickAction(pos=(110, 290)), # 丧失焦点
                            SleepAction(0.5),
                            ClickAction(template=CharaIconTemplate(id)), # 选择匹配人物
                            ClickAction(pos=(690, 200)),
                        )
                add_ids, remove_regions = self._check_current_form(formation)
                if add_ids or remove_regions:
                    # 如果还存在需要操作的步骤说明未变更为预期队伍组合，可能账号没有预期编队的角色。
                    return False
            else:
                # 非法formation，可能队伍不需要，随便点击几个角色加入
                actions = []
                for j in range((i-1)*4,i*4):
                    actions.append(ClickAction(pos=(112 + j*100, 250)))
                    actions.append(SleepAction(1))
                self.action_squential(*actions)
            if i + 1 < len(formations):
                self.action_squential(
                    ClickAction(pos=(834, 448)),
                    SleepAction(0.5),
                )
        return True


class Combat(ImageTask):
    '''
    普通战斗场景任务
    '''
    unit_regions = (
        (678,400,763,485),
        (557,400,643,485),
        (438,400,522,485),
        (315,400,402,485),
        (196,400,282,485),
    )

    def _check_dead_count(self, screenshot:np.ndarray, member_num):
        dead_count = 0
        for region in Combat.unit_regions[:member_num]:
            if not self.template_match(screenshot, BrightnessTemplate(region, 80)):
                dead_count += 1
        return dead_count

    def run(self, form:list['Member']|list[list['Member']]=None, giveup=1, member_num=5):
        '''
        Args:
            form: 提供队伍组合信息。
            giveup: 如果战斗中死亡人数大于{giveup}的数值时，放弃战斗，该数值默认为1。
            member_num: 参与战斗的人数，如果已经提供了{form}那么本参数不发生效果。
        '''
        self.set_progress(total_step=3)
        self.action_squential(
            MatchAction(template='btn_challenge', matched_actions=[ClickAction()], timeout=1),
        )
        if form:
            if isinstance(form[0], list):
                ret = TeamFormationEx(self.robot).run(form)
                form = form[0] # 暂时战斗中操作不支持多队伍
            else:
                ret = TeamFormation(self.robot).run(form)
            member_num = len(form)
            if not ret:
                print("编组失败")
                return False
        self.action_squential(
            ClickAction(template='btn_combat_start'),
            MatchAction(template='btn_blue_settle',matched_actions=[ClickAction(),SleepAction(1),ClickAction(template='btn_combat_start')], timeout=3),
            IfCondition('symbol_restore_power',
                               meet_actions=[
                                ClickAction(pos=(370, 370)),
                                SleepAction(2),
                                ClickAction(pos=(680, 454)),
                                SleepAction(2),
                                ThrowErrorAction("No power!!!")]),
            MatchAction(template='btn_menu_text'),
        )
        success = True
        set_instant = False
        while True:
            screenshot = self.driver.screenshot()
            if self.template_match(screenshot, ImageTemplate('btn_next_step')):
                break
            pos = self.template_match(screenshot, ImageTemplate('btn_close') | ImageTemplate('btn_cancel'))
            if pos:
                self.driver.click(*pos)
            self.action_once(ClickAction(pos=(200, 250)))
            if self.template_match(screenshot, ImageTemplate('btn_menu_text')):
                if self._check_dead_count(screenshot, member_num) >= giveup:
                    success = False
                    self.action_squential(
                        ClickAction(pos=(900, 25)),
                        SleepAction(1),
                        ClickAction('btn_giveup'),
                        SleepAction(0.5),
                        ClickAction('btn_giveup_blue')
                        )
                    break
                if form and not set_instant:
                    regions = [self.adapted_region(region, screenshot.shape[1], screenshot.shape[0]) for region in Combat.unit_regions]
                    for i,mem in enumerate(form):
                        if mem.instant:
                            region = regions[i]
                            self.driver.click((region[0]+region[2])//2, (region[1]+region[3])//2)
                            time.sleep(0.2)
                    set_instant = True
            time.sleep(0.5)
        if success:
            self.action_squential(
                MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
                    ClickAction(template=ImageTemplate('btn_close') | ImageTemplate('btn_cancel')),]),
                SleepAction(1),
                MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
                    ClickAction(template=ImageTemplate('btn_close') | ImageTemplate('btn_cancel') | ImageTemplate('btn_ok_blue')),])
            )
        return success
