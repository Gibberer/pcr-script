from .image import ImageTask
from pcrscript.run_session import clock as time
from typing import TYPE_CHECKING
import re

from ..constants import *
from pcrscript.actions import *
from ..templates import ImageTemplate, BrightnessTemplate

if TYPE_CHECKING:
    from pcrscript import Robot
    from ..strategist import Member

from .base import TimeLimitTask, EventNews
from .registry import register
from .task_home import ToHomePage
from .task_combat import Combat

@register("luna_tower_clean")
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


@register("luna_tower_climbing")
class LunaTowerClimbing(ImageTask, TimeLimitTask):
    '''
    爬露娜塔
    '''
    class State(Enum):
        CONTINUE = 1
        BREAK = 2
        LEVEL = 3
        CORRIDOR = 4
        EX = 5

    @staticmethod
    def valid(event_news: EventNews, args=None) -> tuple:
        if LunaTowerClimbing.event_first_day(event_news.tower):
            return LunaTowerClimbing, args

    level_recognize_region = (334, 78, 414, 117)

    def _parse_level(self, ocr_result):
        results = ocr_result[0]
        if not results:
            return None
        for result in results:
            levels = re.findall(r'\d+', result[1][0])
            if levels:
                for level in levels:
                    if int(level) > 10:
                        return level

    def _goto_luna_clean(self):
        ToHomePage(self.robot).run()
        LunaTowerClean(self.robot).run()

    def _system_recommend_party(self, combat:Combat)->bool:
        self.action_squential(
            MatchAction("btn_use_blue", matched_actions=[ClickAction()], unmatch_actions=[ClickAction("btn_pass_party")]),
            SleepAction(1),
            ClickAction("btn_check_battle"),
            SleepAction(1),
        )
        return combat.run()

    def _check_state(self, screenshot) -> 'LunaTowerClimbing.State':
        if not hasattr(self, '_check_state_times'):
            self._check_state_times = 0
        if self.template_match(screenshot, ImageTemplate("symbol_luna_tower_lock") & ImageTemplate("btn_pass_party")):
            self._check_state_times = 0
            return LunaTowerClimbing.State.LEVEL
        match_special = 0
        while self.template_match(screenshot, ImageTemplate("btn_pass_party")) and match_special < 3:
            match_special += 1
            time.sleep(1)
        if match_special >= 3:
            self._check_state_times = 0
            h,w,_ = screenshot.shape
            ex_pass = False
            corridor_pass = False
            ex_region = self.adapted_region((70, 336, 247, 408), w, h)
            if not self.template_match(screenshot, BrightnessTemplate((776, 356, 849, 389), 130)):
                corridor_pass = True
            pass_poses = self.template_match(screenshot, ImageTemplate("symbol_pass", ret_count=-1))
            if pass_poses:
                for pos in pass_poses:
                    if self.in_region(ex_region, pos):
                        ex_pass = True
            if not corridor_pass:
                return LunaTowerClimbing.State.CORRIDOR
            if not ex_pass:
                return LunaTowerClimbing.State.EX
            return LunaTowerClimbing.State.BREAK
        if self._check_state_times > 3:
            self._check_state_times = 0
            return LunaTowerClimbing.State.BREAK
        else:
            self._check_state_times += 1
            return LunaTowerClimbing.State.CONTINUE


    def run(self, allow_system_recommend=False):
        try:
            from ..strategist import LunaTowerStrategist, Member
            from paddleocr import PaddleOCR
            from paddleocr.paddleocr import logger
            import logging
            logger.setLevel(logging.ERROR)
        except Exception as e:
            print("当前缺失依赖，该任务需要安装额外依赖才能运行")
            print(e)
            return
        self.total_step = '∞'
        self.action_squential(
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[ClickAction(template='btn_close'), ClickAction(pos=(50, 300))]),
            SleepAction(1),
            ClickAction(template="btn_luna_tower_entrance"),
            MatchAction(template="symbol_luna_tower", unmatch_actions=[ClickAction(template='btn_close')]),
        )
        identify_frame = self.driver.screenshot()
        state = self._check_state(identify_frame)
        if state == LunaTowerClimbing.State.CONTINUE or state == LunaTowerClimbing.State.BREAK:
            print("当前没有未解锁层数，应执行回廊扫荡")
            self._goto_luna_clean()
            return
        strategist = LunaTowerStrategist()
        start = time.time()
        print("开始拉取策略信息...")
        strategist.gather_information()
        print(f"生成露娜塔策略耗时：{time.time() - start}")
        ocr = PaddleOCR(use_angle_cls=True, lang="ch", gpu=False)
        h,w,_ = identify_frame.shape
        level_region = self.adapted_region(LunaTowerClimbing.level_recognize_region, w, h)
        combat = Combat(self.robot)
        while True:
            screenshot = self.driver.screenshot()
            if not self.template_match(screenshot, ImageTemplate("symbol_luna_tower")):
                time.sleep(1)
                continue
            state = self._check_state(screenshot)
            strategies = None
            if state == LunaTowerClimbing.State.CONTINUE:
                time.sleep(1)
                continue
            elif state == LunaTowerClimbing.State.BREAK:
                break
            elif state == LunaTowerClimbing.State.LEVEL:
                level = self._parse_level(ocr.ocr(screenshot[level_region[1]:level_region[3],level_region[0]:level_region[2]], cls=False))
                print(f"当前处理露娜塔层级: {level}")
                strategies = strategist.get_strategy(level)
            elif state == LunaTowerClimbing.State.EX:
                print(f"当前处理露娜塔EX")
                if self.template_match(screenshot, ImageTemplate("symbol_corridor")):
                    self.action_once(ClickAction(template="btn_luna_floor_ex"))
                    time.sleep(1)
                strategies = strategist.search_strategy("EX")
                if strategies:
                    tmp = []
                    for strategy in strategies:
                        strategy = strategy.model_copy()
                        # 目前策略获取所能获取的信息不包含多个队伍以及是否存在立即释放模式
                        # 但是在Luna塔EX层中通常为一个队伍并且为全Set所以这里特殊修改下
                        for member in strategy.party:
                            member.instant = True
                        strategy.party = [strategy.party, [Member(id=0, instant=True)], [Member(id=0, instant=True)]]
                        tmp.append(strategy)
                    strategies = tmp
            elif state == LunaTowerClimbing.State.CORRIDOR:
                print(f"当前处理露娜塔回廊")
                strategies = strategist.search_strategy("回廊")
            if not strategies:
                if allow_system_recommend:
                    print("无策略信息，尝试使用系统推荐组合")
                    self._system_recommend_party(combat)
                else:
                    raise RuntimeError("无处理对应层的策略信息")
            else:
                combat_success = False
                for strategy in strategies:
                    for _ in range(2):
                        self.action_squential(ClickAction(pos=(815,430)), SleepAction(1))
                        combat_success = combat.run(form=strategy.party)
                        if combat_success:
                            break
                if not combat_success:
                    # 使用系统推荐队伍 or 退出任务
                    if not allow_system_recommend or not self._system_recommend_party(combat):
                        raise RuntimeError("所有尝试组合皆推塔失败，退出任务")
            time.sleep(1)

        self._goto_luna_clean()
