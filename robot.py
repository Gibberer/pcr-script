from driver import Driver
from cv2 import cv2 as cv
import numpy as np
import time
from typing import Iterable, Tuple
import functools
import random
from config import *
from floordict import FloorDict

CHAPTER_1 = ((106, 281), (227, 237), (314, 331), (379, 235), (479, 294),
             (545, 376), (611, 305), (622, 204), (749, 245), (821, 353))
CHAPTER_2 = ((120, 410), (253, 410), (382, 378), (324, 274), (235, 216), (349, 162), (457, 229),
             (500, 319), (600, 375), (722, 370), (834, 348), (816, 227))
CHAPTER_2_ZOOM = ((48, 410), (180, 412), (302, 381), (256, 276), (157, 210), (275, 170), (377, 230),
                  (426, 321), (526, 377), (648, 377), (755, 341), (742, 226))
CHAPTER_3 = ((135, 185), (192, 309), (284, 229), (414, 230), (379, 343), (488, 411), (532, 289),
             (615, 194), (691, 272), (675, 390), (821, 339), (835, 211))
CHAPTER_4 = ((168,239),(259,312),(367,267),(487,340),(483,371),(605,345))
CHAPTER_4_ZOOM = ((44,200),(136,317),(246,266),(361,242),(349,375),(483,345))
CHAPTERS = (
    FloorDict({0: CHAPTER_1}),
    FloorDict({0: CHAPTER_2, 8: CHAPTER_2_ZOOM}),
    FloorDict({0: CHAPTER_3}),
    FloorDict({0: CHAPTER_4, 5: CHAPTER_4_ZOOM}),
)
CHAPTER_SYMBOLS = ('chapter1', 'chapter2', 'chapter3','chapter4')


class Action:
    def __init__(self):
        super().__init__()
        self._done = False

    def do(self, screenshot, robot):
        self._done = True

    def done(self) -> bool:
        return self._done


def trace(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        self._log("start {}".format(func.__name__.lstrip('_')))
        ret = func(self, *args, **kwargs)
        self._log("end {}".format(func.__name__.lstrip('_')))
        return ret
    return wrapper


num = 0


class Robot:
    def __init__(self, driver: Driver, name=None):
        super().__init__()
        self.driver = driver
        self.devicewidth, self.deviceheight = driver.getScreenSize()
        global num
        if not name:
            name = "Robot#{}".format(num)
            num += 1
        self._name = name

    @trace
    def changeaccount(self, account, password, logpath=None):
        if logpath:
            with open(logpath, 'a') as f:
                f.write("{}:{}\n".format(self._name, account))
        while True:
            screenshot = self.driver.screenshot()
            if self._find_match_pos(screenshot, 'welcome_main_menu'):
                # 当前是欢迎页，执行登录操作
                actions = (
                    MatchAction('edit_account', matched_actions=[ClickAction(), InputAction(
                        account)], unmatch_actions=[ClickAction(pos=self._pos(900, 25))],delay=0),
                    ClickAction(template='edit_password'),
                    InputAction(password),
                    ClickAction(template='btn_login')
                )
                self._action_squential(*actions)
                break
            else:
                # 在游戏里退出账号
                ret = self._find_match_pos(screenshot, 'btn_close')
                if ret:
                    self.driver.click(*ret)
                ret = self._find_match_pos(screenshot, 'tab_main_menu')
                if ret:
                    self._action_squential(
                        ClickAction(pos=ret),
                        ClickAction(template='btn_back_welcome'),
                        ClickAction(template='btn_ok_blue')
                    )
                ret = self._find_match_pos(
                    screenshot, 'btn_back_welcome')
                if ret:
                    self._action_squential(
                        ClickAction(template='btn_back_welcome'),
                        ClickAction(template='btn_ok_blue')
                    )
                ClickAction(pos=self._pos(50, 300)).do(screenshot, self)
            time.sleep(3)

    @trace
    def work(self, tasklist=None):
        # self._real_name_auth()
        self._tohomepage()
        # 第一次进入的时候等下公告
        time.sleep(3)
        ClickAction(template='btn_close').do(self.driver.screenshot(), self)
        if tasklist:
            for funcname, *args in tasklist:
                getattr(self, "_" + funcname)(*args)

    def _log(self, msg: str):
        print("{}: {}".format(self._name, msg))

    @trace
    def _real_name_auth(self, ids):
        '''
        实名认证
        Paramters:
        ---------
        ids: 从配置文件中读取的内容
        '''
        r = random.choice(ids)
        _id = r['id']
        name = r['name']
        start_time = time.time()
        self._action_squential(MatchAction('edit_real_name', matched_actions=[
                               ClickAction(), InputAction(name)], timeout=20))
        if time.time() - start_time > 20:
            return
        self._action_squential(
            ClickAction(template='edit_id_card'),
            InputAction(_id),
            ClickAction(template='btn_submit'),
            ClickAction(template='btn_confirm')
        )

    @trace
    def _choushilian(self):
        '''
        抽免费10连
        '''
        self._action_squential(
            ClickAction(template='niudan'),
            MatchAction('btn_setting_blue', matched_actions=[ClickAction()], unmatch_actions=[
                        ClickAction(template='btn_close')], timeout=5),
            MatchAction('btn_role_detail', unmatch_actions=[
                        ClickAction(template='btn_close')]),
            ClickAction(pos=self._pos(871, 355)),
            ClickAction(template='btn_ok_blue'),
            MatchAction('btn_skip', matched_actions=[ClickAction()], unmatch_actions=[
                        ClickAction(pos=self._pos(50, 300))]),
            MatchAction('btn_ok', matched_actions=[ClickAction()], unmatch_actions=[
                        ClickAction(pos=self._pos(50, 300))]),
            MatchAction('btn_setting_blue', matched_actions=[
                        ClickAction()], timeout=5),
        )

    @trace
    def _tohomepage(self,timeout=0):
        '''
        进入游戏主页面
        '''
        self._action_squential(MatchAction('shop', unmatch_actions=(
            ClickAction(template='btn_close'),
            ClickAction(template='tab_home_page'),
            ClickAction(pos=self._pos(50, 300)),
        ),timeout=timeout))

    @trace
    def _close_ub_animation(self):
        '''
        关闭ub动画
        '''
        self._action_squential(
            ClickAction(template='tab_main_menu'),
            ClickAction(template='btn_setting'),
            ClickAction(template='page_battle'),
            MatchAction('page_battle_selected'),
            ClickAction(pos=self._pos(772, 239)),
            ClickAction(pos=self._pos(772, 370)),
            ClickAction(template='btn_close')
        )

    @trace
    def _role_intensify(self):
        '''
        角色强化默认前五个
        '''
        self._action_squential(
            ClickAction(template='tab_role'),
            SleepAction(1),
            MatchAction('role_symbol'),
            SleepAction(1),
            ClickAction(pos=self._pos(177, 142)),
            SleepAction(1),
            MatchAction('role_intensify_symbol'),
            SleepAction(1)
        )
        # 已经进入强化页面
        actions = []
        for _ in range(5):
            actions.append(ClickAction(pos=self._pos(247, 337)))
            actions.append(MatchAction('btn_cancel', matched_actions=[
                           ClickAction(offset=self._pos(230, 0)), SleepAction(6)], timeout=3))
            actions.append(MatchAction('btn_ok', matched_actions=[
                           ClickAction(), SleepAction(3)], timeout=3))
            actions.append(ClickAction(pos=self._pos(374, 438)))
            actions.append(MatchAction(template='btn_ok_blue', matched_actions=[ClickAction(
            )], unmatch_actions=[ClickAction(template='btn_ok')], timeout=5, threshold=1.2*THRESHOLD))
            actions.append(SleepAction(1))
            actions.append(ClickAction(pos=self._pos(938, 268)))
            actions.append(SleepAction(1))
        self._action_squential(*actions)

    @trace
    def _get_quest_reward(self):
        '''
        获取任务奖励
        '''
        self._action_squential(
            ClickAction(template='quest'),
            SleepAction(3),
            MatchAction('btn_all_rec', matched_actions=[
                        ClickAction()], timeout=3),
            MatchAction('btn_close', matched_actions=[
                        ClickAction()], timeout=5),
            MatchAction('btn_ok', matched_actions=[ClickAction()], timeout=3)
        )

    @trace
    def _get_gift(self):
        '''
        领取礼物
        '''
        pass

    @trace
    def _buy_mana(self, count):
        '''
        购买mana
        '''
        # 先确认进入mana购买界面
        self._action_squential(
            SleepAction(1),
            ClickAction(pos=self._pos(187, 63)),
            MatchAction('icon_mana', unmatch_actions=[
                        ClickAction(pos=self._pos(50, 300))])
        )
        one = self._pos(*[598, 478])
        mul = self._pos(*[818, 477])
        actions = []
        if count >= 1:
            actions.append(ClickAction(pos=one))
            actions.append(SleepAction(.5))
            actions.append(ClickAction(template='btn_ok_blue'))
            actions.append(SleepAction(3))
        if count >= 10:
            actions.append(ClickAction(pos=mul))
            actions.append(SleepAction(.5))
            actions.append(ClickAction(template='btn_ok_blue'))
            actions.append(SleepAction(13))
        if count >= 20:
            actions.append(ClickAction(pos=mul))
            actions.append(SleepAction(.5))
            actions.append(ClickAction(template='btn_ok_blue'))
            actions.append(SleepAction(13))
        actions.append(ClickAction('btn_cancel'))
        self._action_squential(*actions)

    @trace
    def _saodang(self, chapter=1, level=1, count=1):
        self._entre_advanture()
        level_pos = self._move_to_chapter(chapter - 1)
        pos = level_pos[level - 1]
        actions = []
        actions.append(ClickAction(pos=self._pos(*pos)))
        actions.append(MatchAction('btn_challenge'))
        if count == -1:#click forever change to long press
            actions.append(SwipeAction(self._pos(877,330),self._pos(877,330), 6000))
        else:    
            for _ in range(count):
                actions.append(ClickAction(pos=self._pos(877, 330)))
        self._action_squential(*actions, delay=0)
        actions = []
        actions.append(ClickAction(pos=self._pos(757, 330)))
        actions.append(ClickAction(template='btn_ok_blue'))
        actions.append(ClickAction(template='btn_skip_ok'))
        actions.append(SleepAction(1))
        actions.append(ClickAction(template='btn_ok'))
        actions.append(SleepAction(1))
        actions.append(MatchAction(template='btn_ok',
                                   matched_actions=[ClickAction()], timeout=3))
        actions.append(SleepAction(1))
        actions.append(MatchAction(template='btn_ok',
                                   matched_actions=[ClickAction()], timeout=3))
        actions.append(SleepAction(2))
        actions.append(ClickAction(pos=self._pos(666, 457)))
        self._action_squential(*actions)

    @trace
    def _adventure(self, chapter, start, end=None, totalcount=1, checkguide=False):
        '''
        刷冒险
        Parameters
        ---------
        chapter: 冒险章节
        start: 起始关卡
        end: 结束关卡
        checkguide: 是否做跳过教程检测
        '''
        chapter = chapter - 1
        if not end:
            end = start
        # 从主页进入冒险页面
        self._entre_advanture()
        chapter_symbol = CHAPTER_SYMBOLS[chapter]
        check_auto = True
        count = 0
        while count < totalcount:
            level_pos = self._move_to_chapter(chapter)
            for i in range(start - 1, end):
                pos = level_pos[i]
                self._combat(pos, check_auto=check_auto)
                check_auto = False
                self._action_squential(
                    MatchAction(chapter_symbol, timeout=10),
                    SleepAction(3)
                )
                ClickAction(template='btn_close').do(
                    self.driver.screenshot(), self)
                if checkguide:
                    time.sleep(2)
                    self._skip_guide(chapter + 1, i + 1)
                level_pos = CHAPTERS[chapter][i]
            count += (end - start) + 1

    def _entre_advanture(self, normal=True):
        actions = []
        actions.append(MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
            ClickAction(template='btn_close')]))
        actions.append(SleepAction(2))
        actions.append(ClickAction(
            template='btn_main_plot', threshold=0.8*THRESHOLD))
        actions.append(SleepAction(2))
        if normal:
            actions.append(MatchAction('btn_normal_selected', unmatch_actions=[
                           ClickAction(template='btn_normal')]))
        self._action_squential(*actions)

    def _move_to_chapter(self, chapter_index):
        chapter_symbol = CHAPTER_SYMBOLS[chapter_index]
        # 移动到选中目标的关卡
        ret = self._find_match_template(CHAPTER_SYMBOLS, timeout=10)
        if not ret:
            return
        pos, _ = ret
        actions = []
        if chapter_index > pos:
            actions.append(MatchAction(chapter_symbol, unmatch_actions=[
                           ClickAction(pos=self._pos(928, 271)), SleepAction(3)], timeout=15))
        elif chapter_index < pos:
            actions.append(MatchAction(chapter_symbol, unmatch_actions=[
                           ClickAction(pos=self._pos(36, 271)), SleepAction(3)], timeout=15))
        # 确保移动到对应页面
        actions.append(SleepAction(1))
        self._action_squential(*actions)
        level_pos = CHAPTERS[chapter_index][0]
        if pos == chapter_index:
            # 修正level pos
            ret = self._find_match_pos(self.driver.screenshot(), 'peiko')
            if ret:
                bar = ret[0] + 15
                for i, pos in enumerate(level_pos):
                    if pos[0] > bar:
                        level_pos = CHAPTERS[chapter_index][i]
                        break
        return level_pos

    @trace
    def _skip_guide(self, chapter, level):
        if chapter == 1:
            if level in (4, 6) and self._find_match_pos(self.driver.screenshot(), 'kkr_guide'):
                if level == 4:
                    self._skip_guide_1_4()
                if level == 6:
                    self._skip_guide_1_6()
        elif chapter == 2:
            if level in (1, 2, 5, 8, 12) and self._find_match_pos(self.driver.screenshot(), 'kkr_guide'):
                if level == 1:
                    self._skip_guide_2_1()
                if level == 2:
                    self._skip_guide_2_2()
                if level == 5:
                    self._skip_guide_2_5()
                if level == 8:
                    self._skip_guide_2_8()
                if level == 12:
                    self._skip_guide_2_12()
        elif chapter == 3:
            if level in (1,) and self._find_match_pos(self.driver.screenshot(), 'kkr_guide'):
                if level == 1:
                    self._skip_guide_3_1()

    def _find_match_template(self, templates, timeout=15, delay=1) -> Tuple[int, str]:
        start_time = time.time()
        while True:
            if delay > 0:
                time.sleep(delay)
            screenshot = self.driver.screenshot()
            for i, template in enumerate(templates):
                ret = self._find_match_pos(screenshot, template)
                if ret:
                    return i, template
            if time.time() - start_time > timeout:
                break

    @trace
    def _combat(self, trigger_pos, check_auto=False):
        '''
        处理战斗界面相关
        '''
        actions = []
        actions.append(ClickAction(pos=self._pos(*trigger_pos)))
        actions.append(ClickAction(template='btn_challenge'))
        actions.append(ClickAction(template='btn_combat_start'))
        actions.append(SleepAction(5))
        if check_auto:
            actions.append(MatchAction(template='btn_caidan', matched_actions=[ClickAction(template='btn_speed'),
                                                                               ClickAction(template='btn_auto')], timeout=10))
        actions.append(SleepAction(35))
        actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
            ClickAction(template='btn_close'), ClickAction(pos=self._pos(200, 250))]))
        actions.append(SleepAction(1))
        actions.append(ClickAction('btn_next_step'))
        self._action_squential(*actions)

    @trace
    def _join_guild(self, guild_name):
        '''
        加入行会
        '''
        self._action_squential(
            ClickAction(template='guild'),
            SleepAction(1),
            MatchAction(template='join_guild_symbol',unmatch_actions=[ClickAction(pos=self._pos(50, 300))],timeout=10),
            ClickAction(pos=self._pos(50, 300)),
            SleepAction(3)
        )
        ret = self._find_match_pos(
            self.driver.screenshot(), 'join_guild_symbol')
        if not ret:
            self._log('Join guild failed: maybe aready have guild')
            return
        actions = []
        actions.append(ClickAction(pos=self._pos(860, 78)))
        actions.append(MatchAction(
            'btn_cancel', matched_actions=[SleepAction(1)]))
        actions.append(ClickAction(pos=self._pos(281, 142)))
        actions.append(ClickAction(pos=self._pos(380, 182)))
        actions.append(InputAction(guild_name))
        actions.append(ClickAction(pos=self._pos(585, 434)))
        actions.append(SleepAction(1))  # 收起软键盘
        actions.append(ClickAction(pos=self._pos(585, 434)))
        actions.append(SleepAction(3))
        actions.append(ClickAction(pos=self._pos(672, 160)))
        actions.append(SleepAction(1))
        actions.append(ClickAction(template='btn_join'))
        actions.append(ClickAction(template='btn_ok_blue'))
        actions.append(SleepAction(1))
        actions.append(ClickAction(template='btn_ok_blue'))
        actions.append(SleepAction(5))
        self._action_squential(*actions)

    @trace
    def _dungeon_mana(self):
        '''
        进入地下城，送mana
        '''
        actions = []
        actions.append(MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
            ClickAction(template='btn_close')]))
        actions.append(SleepAction(2))
        actions.append(ClickAction(template='dungeon'))
        actions.append(MatchAction('dungeon_symbol', matched_actions=[
                       ClickAction(offset=self._pos(100, 200))], timeout=10))  # 确认进入地下城
        actions.append(MatchAction(
            'btn_ok_blue', matched_actions=[ClickAction()], timeout=5))
        actions.append(SleepAction(3))
        actions.append(MatchAction('in_dungeon_symbol'))
        actions.append(ClickAction(pos=self._pos(668, 290)))
        actions.append(ClickAction(template='btn_challenge_dungeon'))
        actions.append(SleepAction(1))  # 选择4个人物
        actions.append(ClickAction(pos=self._pos(105, 170)))
        actions.append(ClickAction(pos=self._pos(224, 170)))
        actions.append(ClickAction(pos=self._pos(315, 170)))
        actions.append(ClickAction(pos=self._pos(432, 170)))
        actions.append(ClickAction(pos=self._pos(478, 89)))  # 点击支援
        actions.append(SleepAction(1))
        actions.append(ClickAction(pos=self._pos(105, 170)))
        actions.append(ClickAction(pos=self._pos(832, 453)))  # 进入战斗
        actions.append(MatchAction(
            'btn_ok_blue', matched_actions=[ClickAction()], timeout=5))
        actions.append(SleepAction(3))
        actions.append(MatchAction(
            'btn_caidan', matched_actions=[ClickAction()]))
        actions.append(ClickAction(template='btn_give_up'))
        actions.append(ClickAction(template='btn_give_up_blue'))
        actions.append(SleepAction(3))
        actions.append(MatchAction('in_dungeon_symbol'))
        actions.append(ClickAction(template='btn_withdraw'))
        actions.append(ClickAction(template='btn_ok_blue'))
        self._action_squential(*actions)

    @trace
    def _skip_guide_1_4(self):
        self._action_squential(
            self._create_skip_guide_action(),
            self._create_skip_guide_action(),
            self._create_skip_guide_action(),
            self._create_skip_guide_action(),
            ClickAction(template='btn_no_voice'),
            ClickAction(template='btn_menu'),
            ClickAction(template='btn_skip_with_text'),
            ClickAction(template='btn_skip_ok'),
            MatchAction('chapter1', unmatch_actions=[
                        ClickAction(pos=self._pos(480, 220))])
        )

    @trace
    def _skip_guide_1_6(self):
        self._action_squential(
            self._create_skip_guide_action(),
            self._create_skip_guide_action(),
            self._create_skip_guide_action(),
            self._create_skip_guide_action(),
            ClickAction(template='btn_no_voice'),
            ClickAction(template='btn_menu'),
            ClickAction(template='btn_skip_with_text'),
            ClickAction(template='btn_skip_ok'),
            MatchAction(template='btn_menu', matched_actions=[
                        ClickAction()], unmatch_actions=[ClickAction(pos=self._pos(480, 270))]),
            ClickAction(template='btn_skip_with_text'),
            ClickAction(template='btn_skip_ok'),
            SleepAction(1),
            MatchAction(template='btn_skip_ok', matched_actions=[
                        ClickAction()], unmatch_actions=[ClickAction(pos=self._pos(480, 270))]),
            ClickAction(template='btn_menu'),
            ClickAction(template='btn_skip_with_text'),
            ClickAction(template='btn_skip_ok'),
            MatchAction('chapter1', unmatch_actions=[
                        ClickAction(pos=self._pos(480, 220))])
        )

    @trace
    def _skip_guide_2_1(self):
        self._action_squential(
            self._create_skip_guide_action(),
            SleepAction(1),
            ClickAction(template='btn_menu'),
            ClickAction(template='btn_skip_with_text'),
            ClickAction(template='btn_skip_ok'),
            self._create_skip_guide_action(),
            ClickAction(template="btn_close")
        )
        # 回首页，这里稍微绕下远
        self._tohomepage()
        # 再回到冒险页面
        self._entre_advanture()

    @trace
    def _skip_guide_2_2(self):
        self._action_squential(
            self._create_skip_guide_action(),
            MatchAction('quest', unmatch_actions=[
                        ClickAction(pos=self._pos(310, 50))], timeout=10)  # 为了点几下屏幕没有好的标志位
        )
        # 再回到冒险页面
        self._entre_advanture()

    @trace
    def _skip_guide_2_5(self):
        self._action_squential(
            self._create_skip_guide_action(),
            self._create_skip_guide_action(),
            MatchAction('quest', unmatch_actions=[
                        ClickAction(pos=self._pos(310, 50))], timeout=5)  # 为了点几下屏幕没有好的标志位
        )
        # 回首页，这里稍微绕下远
        self._tohomepage()
        # 再去冒险
        self._entre_advanture()

    @trace
    def _skip_guide_2_8(self):
        self._action_squential(
            self._create_skip_guide_action(
                template='arrow_down_short', offset=(0, 50)),
        )
        # 回首页，这里稍微绕下远
        self._tohomepage()
        # 再去冒险
        self._entre_advanture()

    @trace
    def _skip_guide_2_12(self):
        self._action_squential(
            self._create_skip_guide_action(),
            self._create_skip_guide_action(template='arrow_down_dungeon'),
            MatchAction('btn_menu', matched_actions=[
                        ClickAction()], unmatch_actions=[ClickAction(pos=self._pos(480, 270))]),
            ClickAction(template='btn_skip_with_text'),
            ClickAction(template='btn_skip_ok'),
            MatchAction('in_dungeon_symbol', unmatch_actions=[
                        ClickAction(pos=self._pos(310, 50))]),
            MatchAction('quest', unmatch_actions=[
                        ClickAction(pos=self._pos(310, 50))],timeout=5),
            SleepAction(1),
            ClickAction(pos=self._pos(806, 432)),
            ClickAction(template='btn_ok_blue'),
        )
        # 回首页，这里稍微绕下远
        self._tohomepage(timeout=10)
        self._action_squential(
            MatchAction('to_activity', matched_actions=[
                        ClickAction()], timeout=5),
            SleepAction(3),
            ClickAction(pos=self._pos(362,374))
        )
        # 再去冒险
        self._entre_advanture()
        self._action_squential(
            MatchAction('btn_close', matched_actions=[
                        ClickAction()], timeout=5)
        )

    @trace
    def _skip_guide_3_1(self):
        self._action_squential(
            self._create_skip_guide_action(),
            self._create_skip_guide_action(),
            MatchAction('quest', unmatch_actions=[
                        ClickAction(pos=self._pos(310, 50))], timeout=5)  # 为了点几下屏幕没有好的标志位
        )
        # 再去冒险
        self._entre_advanture()

    def _create_skip_guide_action(self, template='arrow_down', offset=(0, 100), threshold=(7/8)*THRESHOLD) -> Action:
        return MatchAction(template, matched_actions=[ClickAction(offset=(
            self._pos(*offset))), SleepAction(3)], unmatch_actions=[ClickAction(pos=self._pos(100, 180))], threshold=threshold)

    def _pos(self, x, y) -> Tuple[int,int]:
        return(int((x/BASE_WIDTH)*self.devicewidth), int((y/BASE_HEIGHT)*self.deviceheight))

    def _action_squential(self, *actions: Iterable[Action], delay=0.2):
        for action in actions:
            while not action.done():
                action.do(self.driver.screenshot(), self)
                if delay > 0:
                    time.sleep(delay)

    def _find_match_pos(self, screenshot, template, threshold=THRESHOLD) -> Tuple[int, int]:
        name = template
        source: np.ndarray
        if isinstance(screenshot, np.ndarray):
            source = screenshot
        else:
            source = cv.imread(screenshot)
        template: np.ndarray = cv.imread("images/{}.png".format(template))
        # 这里需要对template resize，template是在960x540的设备上截屏的
        height, width = source.shape[:2]
        theight, twidth = template.shape[:2]
        fx = width/BASE_WIDTH
        fy = height/BASE_HEIGHT
        template = cv.resize(template, None, fx=fx, fy=fy,
                             interpolation=cv.INTER_AREA)
        theight, twidth = template.shape[:2]
        ret = cv.matchTemplate(source, template, cv.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(ret)
        # self._log("{}:{}:{}".format(name, max_val, threshold))
        if max_val > threshold:
            return (max_loc[0] + twidth/2, max_loc[1] + theight/2)
        else:
            return None


class MatchAction(Action):
    def __init__(self, template, matched_actions=None, unmatch_actions=None, delay=1, timeout=0, threshold=THRESHOLD):
        super().__init__()
        self.template = template
        self.matched_actions = matched_actions
        self.unmatch_action = unmatch_actions
        self.delay = delay
        self.threshold = threshold
        self.timeout = timeout
        self.starttime = 0

    def do(self, screenshot, robot: Robot):
        if self.starttime == 0:
            self.starttime = time.time()
        if self.delay > 0:
            time.sleep(self.delay)
        ret = robot._find_match_pos(
            screenshot, self.template, threshold=self.threshold)
        if ret:
            if self.matched_actions:
                for action in self.matched_actions:
                    action.pos = ret
                    action.do(screenshot, robot)
            self._done = True
        elif self.unmatch_action:
            for action in self.unmatch_action:
                action.do(screenshot, robot)
        if self.timeout > 0:
            if time.time() - self.starttime > self.timeout:
                self._done = True


class SleepAction(Action):
    def __init__(self, duration):
        super().__init__()
        self.duration = duration

    def do(self, *args):
        time.sleep(self.duration)
        self._done = True


class ClickAction(Action):
    def __init__(self, template=None, pos=None, offset=(0, 0), threshold=THRESHOLD):
        super().__init__()
        self.template = template
        self.pos = pos
        self.offset = offset
        self.threshold = threshold

    def do(self, screenshot, robot: Robot):
        if self.template:
            ret = robot._find_match_pos(
                screenshot, self.template, threshold=self.threshold)
            if ret:
                robot.driver.click(ret[0] + self.offset[0],
                                   ret[1] + self.offset[1])
                self._done = True
        else:
            if self.pos:
                robot.driver.click(self.pos[0] + self.offset[0],
                                   self.pos[1] + self.offset[1])
            self._done = True


class InputAction(Action):
    def __init__(self, text):
        super().__init__()
        self._text = text

    def do(self, screenshot, robot: Robot):
        robot.driver.input(self._text)
        self._done = True

class SwipeAction(Action):
    def __init__(self, start, end, duration):
        super().__init__()
        self.start = start
        self.end = end
        self.duration = duration 
    
    def do(self, screenshot, robot:Robot):
        robot.driver.swipe(self.start,self.end,self.duration)
        self._done = True
