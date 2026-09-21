"""Legacy map revival flow. Coordinates are normalized; unknown branches stop."""
import re
from pcrscript.run_session import clock as time

import cv2 as cv
import numpy as np

from ..game_ui.event_layout import event_layout, map_dialogue, legacy_hub
from ..game_ui.screen import EventUIError, normalized
from .event_battle import EventCombat
from .event_formation import EventFormation
from .event_strategy import load_parties
from ..templates import ImageTemplate


class RevivalMap:
    def __init__(self, runner):
        self.r = runner
        self.ui = runner.ui
        runner.combat_return = lambda s: event_layout(s) == 'map'
        runner.combat_dialog = self.dialog

    def dialog(self, s):
        if s.find('收取报酬', (250, 0, 710, 70), exact=True):
            self.ui.expect_click('关闭', (350, 445, 615, 515), exact=True)
            return True
        if map_dialogue(s):
            self.ui.click((775, 495))
            return True
        return False

    def home(self):
        for _ in range(45):
            self.r.check_deadline()
            s = self.ui.capture()
            if s.find('正在进行数据连接|加载中'):
                time.sleep(.6)
                continue
            if self.dialog(s) or self.r.entry_dialog(s) or self.r.story_dialog(s):
                continue
            if legacy_hub(s):
                self.ui.click(s.find('活动关卡', (450, 150, 670, 235)))
                continue
            if event_layout(s) == 'map':
                time.sleep(.6)
                stable = self.ui.capture()
                if event_layout(stable) == 'map' and not map_dialogue(stable):
                    return stable
                continue
            if s.find('BOSS详情|自动推进设定|队伍编组', (0, 0, 750, 80)) or s.find('剩余挑战次数'):
                self.ui.expect_click('取消', (200, 420, 930, 525), exact=True)
            elif s.find('自动推进报酬一览|自动推进结束|区域解锁|活动任务'):
                item = s.find('关闭|确认|确定', (200, 300, 800, 525), exact=True)
                if item:
                    self.ui.click(item)
                elif s.find('活动任务', (0, 0, 300, 70)):
                    self.ui.click((32, 30))
            elif s.find('获得道具|伤害报告|战斗胜利'):
                self.ui.expect_click('下一步', (700, 400, 950, 530), exact=True)
            else:
                time.sleep(.6)
        self.ui.save('map_home_unknown')
        raise EventUIError('无法返回复刻地图')

    def clear_quests(self, difficulty, last_stage):
        self.home()
        self.ui.expect_click(difficulty, (700, 55, 950, 105), exact=True)
        self.home()
        next_marker = ImageTemplate('revival_next', threshold=.8)
        for _ in range(3 if difficulty == '普通' else 0):
            self.ui.swipe((220, 250), (760, 250))
        for page in range(4 if difficulty == '普通' else 1):
            s = self.home()
            marker_text = s.find('下一关', (0, 110, 960, 400), exact=True)
            marker = marker_text.center if marker_text else next_marker.match(s.image)
            if marker:
                self.ui.click((marker[0], marker[1]+80))
                self.ui.wait(lambda f: f.find('自动推进下一个关卡'), '未通关关卡详情')
                # Require the blue check rather than toggling remembered settings.
                f = self.ui.capture()
                check = cv.cvtColor(f.image[316:351, 695:735], cv.COLOR_BGR2HSV)
                enabled = np.mean((check[:, :, 0] > 85) & (check[:, :, 0] < 125) & (check[:, :, 1] > 80)) > .15
                if not enabled:
                    self.ui.click((715, 334))
                self.ui.expect_click('挑战', (720, 420, 950, 525), exact=True)
                self.ui.wait(lambda f: f.find('队伍编组'), '首通编队')
                self.ui.expect_click('下一步', (720, 420, 950, 525), exact=True)
                self.ui.wait(lambda f: f.find('自动推进设定'), '自动推进')
                self.auto_advance()
                return self.verify_last(last_stage)
            self.ui.swipe((760, 250), (220, 250))
        return self.verify_last(last_stage)

    def verify_last(self, last_stage):
        s = self.home()
        label = s.find(re.escape(last_stage), (0, 150, 960, 470), exact=True)
        if not label:
            label = self.ui.read_region(s, (0,150,600,450)).find(re.escape(last_stage), exact=True)
        if not label and last_stage != '1-5':
            raise EventUIError('未定位最终关卡进行通关复核')
        # This event's five Hard nodes fit one screen. Its outlined map text
        # can evade OCR; the known node is safe only with a detail-title check.
        self.ui.click((label.center[0], label.center[1]-55) if label else (850,310))
        s = self.ui.wait(lambda f: f.find('剩余挑战次数'), '最终关卡详情')
        if not s.find(re.escape(last_stage), (40,25,560,80)):
            raise EventUIError('关卡详情编号与最终关卡不一致')
        hsv = cv.cvtColor(s.image, cv.COLOR_BGR2HSV)
        stars = sum(np.mean((hsv[25:48, x-8:x+9, 0] >= 15) &
                           (hsv[25:48, x-8:x+9, 0] <= 40) &
                           (hsv[25:48, x-8:x+9, 1] > 100)) > .5 for x in (765, 827, 890))
        self.ui.save('last_stage_verified', s)
        self.ui.expect_click('取消', (550, 420, 755, 525), exact=True)
        if not stars:
            raise EventUIError('最终关卡星数未确认，保留待完成')
        self.r.log(f'{last_stage} 最终关卡已通过，实测星数 {stars}')
        return self.home()

    def normal_boss_from_detail(self):
        s = self.ui.capture()
        if not s.find('BOSS详情', (0, 0, 750, 80)) or not s.find('普通', (0, 0, 300, 90), exact=True):
            raise EventUIError('未确认普通首领详情，不能用当前队伍开战')
        defeated = self.ui.number(s, (891, 28, 926, 56))
        if defeated is None:
            raise EventUIError('普通首领讨伐数未知')
        if defeated > 0:
            return self.home()
        self.ui.save('normal_boss_plan', s)
        self.ui.expect_click('挑战', (720, 420, 950, 525), exact=True)
        self.ui.wait(lambda f: f.find('队伍编组', (250, 0, 750, 80)), '普通首领编队')
        result = EventCombat(self.r).run()
        self.r.report['battles'].append({'boss': 'normal', **vars(result)})
        if result.outcome != 'settled':
            raise EventUIError('普通首领未成功：'+result.reason)
        self.verify_boss_defeated('普通')
        return self.home()

    def hard_trial_from_detail(self):
        s = self.ui.capture()
        if not s.find('BOSS详情', (0, 0, 750, 80)) or not s.find('混沌发电机') or s.number((675, 20, 725, 60)) != 50:
            raise EventUIError('未确认用户授权的本期等级50困难首领')
        count = self.ui.number(s, (891, 28, 926, 56))
        if count is None:
            raise EventUIError('首领已讨伐次数未知')
        if count > 0:
            return self.home()
        if (self.r.event.extras['event_id'] != self.r.options.get('hard_trial_event_id')
                or self.r.state.data.get('hard_trial_started')):
            raise EventUIError('本期困难首领试打未授权或已尝试，不能重复开战')
        self.r.report['hard_trial_started'] = True
        self.r.state.save(self.r.report)
        self.ui.save('hard_trial_plan', s)
        self.ui.expect_click('挑战', (720, 420, 950, 525), exact=True)
        self.ui.wait(lambda f: f.find('队伍编组'), '困难首领编队')
        result = EventCombat(self.r).run()
        self.r.report['battles'].append({'boss': 'hard', 'source': '用户授权本期一次试打', **vars(result)})
        self.r.state.save(self.r.report)
        if result.outcome != 'settled':
            raise EventUIError('困难首领试打未成功：'+result.reason)
        self.verify_boss_defeated('困难')
        return self.home()

    def verify_boss_defeated(self, label):
        detail = self.boss_detail(label)
        count = self.ui.number(detail, (891,28,926,56))
        if count is None or count < 1:
            raise EventUIError(label+'首领结算后未确认讨伐数增加')

    def auto_advance(self):
        """Start only from a visible native auto-advance settings dialog."""
        s = self.ui.capture()
        if not s.find('自动推进设定', (200, 0, 750, 80)):
            raise EventUIError('未确认自动推进设置')
        if not s.find('自动推进至活动关卡') or not s.find('消耗体力'):
            raise EventUIError('自动推进范围和消费无法确认')
        self.ui.save('auto_plan', s)
        self.ui.expect_click('不停止', (470, 265, 625, 320), exact=True)
        self.ui.expect_click('立即发动', (260, 360, 450, 425), exact=True)
        self.ui.expect_click('战斗开始', (480, 450, 710, 520), exact=True)
        end = time.monotonic()+600
        while time.monotonic() < end:
            self.r.check_deadline()
            s = self.ui.capture()
            if s.find('自动推进结束'):
                self.ui.save('auto_finished', s)
                if not s.find('由于是最终关卡'):
                    raise EventUIError('自动推进提前停止：'+s.text())
                self.ui.expect_click('确认', (250, 350, 750, 525), exact=True)
                return self.home()
            if s.find('体力回复|体力恢复|战斗失败|挑战失败'):
                raise EventUIError('自动推进受阻：'+s.text())
            # The game itself advances through victory and next-step screens.
            time.sleep(1)
        self.ui.save('auto_timeout')
        raise EventUIError('自动推进超时，停止追加操作')

    def run(self):
        if self.r.event.extras.get('original_event_id') != 10150:
            raise EventUIError('此地图活动尚无关卡数量与特殊剧情记录，不能套用旧活动')
        self.clear_quests('普通', '1-10')
        normal = self.boss_detail('普通')
        count = self.ui.number(normal, (891, 28, 926, 56))
        if count is None:
            raise EventUIError('普通首领讨伐次数未知')
        if count == 0:
            self.normal_boss_from_detail()
        else:
            self.home()
        self.clear_quests('困难', '1-5')
        self.boss_detail('困难')
        self.hard_trial_from_detail()
        if self.special_complete():
            # In this event SP unlocks after VH; VH becomes locked after its
            # daily clear and cannot be reopened just to inspect the counter.
            self.r.log('特别首领已通过，表演赛已解锁；前置高难亦已完成')
            return self.rewards()
        for label, difficulty in [('高难', 'very_hard'), ('特别', 'special')]:
            try:
                self.sourced_boss(label, difficulty)
            except EventUIError as error:
                from pcrscript.run_session import failure
                failure(error)
                self.r.report['pending'].append(str(error))
                self.hub()  # Continue rewards only after a known safe return.
        self.rewards()

    def special_complete(self):
        self.hub()
        for _ in range(4):
            s = self.ui.capture()
            if s.find('表演赛', (675,120,950,305)):
                self.ui.save('special_complete', s)
                return True
            if s.find('特别', (675,120,950,305), exact=True):
                return False
            # The boss list has its own scroll; re-entry resets it to Normal.
            self.ui.swipe((820,285), (820,145))
        return False  # Not yet unlocked is not proof of completion.

    def rewards(self):
        self.read_stories(False)
        self.read_stories(True)
        for round_index in range(5):
            self.missions()
            self.exchange()
            if round_index > 0 and self.mission_claims == 0:
                return
        raise EventUIError('兑换后活动任务仍有新奖励，达到结算循环上限')

    def read_stories(self, memories=False, already_open=False):
        if not already_open:
            s = self.hub()
            if memories:
                self.ui.click(s.find('水都的回忆', (450, 240, 680, 310)))
            else:
                self.ui.click((818, 348))
        previous = None
        unchanged = 0
        opened = 0
        prepared = False
        for step in range(400):
            self.r.check_deadline()
            s = self.ui.capture()
            in_list = (s.find('水都的回忆', (0, 0, 300, 70)) if memories else
                       s.find('活动剧情一览', (250, 0, 710, 70)))
            # The list's instructional text says 获得奖励; it is not a reward
            # popup and must not be closed by the generic story dialog handler.
            if self.dialog(s) or (not in_list and self.r.story_dialog(s)):
                continue
            if s.find('加载中|下载中|正在进行数据连接'):
                time.sleep(.7)
                continue
            if in_list:
                if not prepared:
                    for _ in range(6):
                        self.ui.swipe((830,180) if memories else (650,170), (830,460) if memories else (650,400))
                    prepared = True
                    continue
                roi = (460, 60, 910, 510) if memories else (250, 115, 690, 435)
                new = s.find('新内容|NEW|未读', roi)
                if new:
                    self.ui.save(f'{"memory" if memories else "story"}_{opened:02}', s)
                    self.ui.click((750 if memories else 500, min(new.center[1]+40, roi[3]-15)))
                    opened += 1
                    previous = None
                    unchanged = 0
                    continue
                signature = s.text(roi)
                unchanged = unchanged+1 if signature == previous else 0
                if unchanged >= 2:
                    self.ui.save('memories_checked' if memories else 'stories_checked', s)
                    if memories:
                        self.ui.click((32,30))
                    else:
                        self.ui.expect_click('关闭', (350, 445, 615, 515), exact=True)
                    self.r.log(f'{"水都回忆" if memories else "活动剧情"}已检查，本轮打开{opened}篇')
                    return self.hub()
                previous = signature
                self.ui.swipe((830, 460) if memories else (650,400), (830,170) if memories else (650,170))
            elif legacy_hub(s):
                self.ui.click((559,274) if memories else (818,348))
            else:
                time.sleep(.5)
        raise EventUIError('复刻剧情达到步骤上限，保留未完成状态')

    def missions(self, already_open=False):
        self.mission_claims = 0
        if not already_open:
            self.hub()
            self.ui.click((910,437))
        self.ui.wait(lambda s: s.find('活动任务', (0,0,300,70)), '活动任务', handle=self.dialog)
        for tab in ('每日','普通','特别','称号'):
            s = self.ui.capture()
            if self.dialog(s):
                s = self.ui.capture()
            self.ui.expect_click(tab, (300,0,950,50), exact=True)
            for _ in range(12):
                s = self.ui.capture()
                if self.dialog(s):
                    continue
                if s.find('正在进行数据连接'):
                    time.sleep(.5)
                    continue
                button = s.find('全部收取', (700,405,955,475), exact=True)
                if not button:
                    raise EventUIError('无法确认活动任务全部收取按钮')
                if not s.blue_button(button):
                    self.ui.save('missions_'+tab, s)
                    break
                self.ui.click(button, delay=1.5)
                self.mission_claims += 1
            else:
                raise EventUIError(tab+'任务领取达到上限')
        self.r.log('每日、普通、特别、称号的可领取任务已清空')
        return self.hub()

    def exchange(self, already_open=False):
        if not already_open:
            self.hub()
            self.ui.click((574,347))
        before = None
        consume = None
        total = 0
        for _ in range(240):
            self.r.check_deadline()
            s = self.ui.capture()
            if s.find('正在进行数据连接|加载中'):
                time.sleep(.7)
                continue
            if s.find('重置完毕') and s.find('重置了报酬列表'):
                self.ui.expect_click('确认', (250,300,730,515), exact=True)
                continue
            if s.find(r'已获得第\d+轮报酬列表中的全部报酬') and s.find('切换到下一个报酬列表'):
                self.ui.expect_click('确认', (250,350,730,515), exact=True)
                continue
            if s.find('当前的列表', (250,15,710,65), exact=True):
                remaining = s.all(r'剩余\d+/\d+', (590,85,705,430))
                if len(remaining) != 2 or any(not normalized(item.text).startswith('剩余0/') for item in remaining):
                    raise EventUIError('奖池未确认全部抽空，不提前重置报酬')
                self.ui.save('exchange_round_empty', s)
                self.ui.expect_click('重置', (350,445,615,515), exact=True)
                continue
            if s.find('查看已获得道具', (300,390,660,465)):
                self.ui.expect_click('查看已获得道具', (300,390,660,465), exact=True)
                continue
            if s.find('获得的报酬将会直接增加到持有道具中'):
                cancel = s.find('取消|确认', (250,390,710,465), exact=True)
                if cancel:
                    self.ui.click(cancel)
                else:
                    time.sleep(.7)  # Pool completion can replace this result mid-transition.
                continue
            if s.find('讨伐证交换', (0,0,300,65)) and s.find('讨伐证', (725,420,845,470), exact=True):
                current = self.ui.number(s, (850,425,943,462))
                if current is None:
                    single = s.find('1次交换', (520,330,710,385), exact=True)
                    batch = s.find(r'\d+次交换', (730,330,932,385))
                    if single and batch and not s.blue_button(single) and not s.blue_button(batch):
                        zero = self.ui.number(s, (909,431,929,454))
                        if zero == 0:
                            current = 0
                if current is None:
                    raise EventUIError('讨伐证余额无法确认')
                if before is not None:
                    if before-current != consume:
                        raise EventUIError('实际讨伐证扣除与按钮消费不一致，停止追加兑换')
                    total += consume
                if current == 0:
                    self.ui.save('exchange_empty', s)
                    self.r.log(f'本轮兑换 {total} 张讨伐证，余额已确认 0')
                    return self.hub()
                amount = s.find(r'使用\d+张', (730,383,932,419))
                button = s.find(r'\d+次交换', (730,330,932,385))
                if not amount or not button:
                    raise EventUIError('无法核验批量兑换次数和讨伐证消费')
                consume = int(re.search(r'\d+', normalized(amount.text))[0])
                if consume <= 0 or consume > min(current, 100) or int(re.search(r'\d+', normalized(button.text))[0]) != consume:
                    raise EventUIError('批量兑换消费超出余额')
                before = current
                self.ui.save('exchange_plan', s)
                self.ui.click(button, delay=1.5)
            else:
                time.sleep(.7)
        raise EventUIError('讨伐证兑换达到步骤上限')

    def boss_detail(self, label):
        s = self.hub() if label == '特别' else self.home()
        target = s.find(label, (680, 130, 940, 305) if label == '特别' else (0, 120, 960, 380), exact=True)
        if not target:
            raise EventUIError(f'未发现{label}首领入口')
        self.ui.click(target if label == '特别' else (target.center[0], target.center[1]-60))
        s = self.ui.wait(lambda f: f.find('BOSS详情', (0, 0, 300, 80)), '首领详情')
        pattern = label + (r'难度/阶段[123]' if label == '特别' else '')
        badge = s.find(pattern, (185,25,425,65), exact=True)
        if not badge:
            badge = self.ui.read_region(s, (185,25,425 if label == '特别' else 290,65)).find(pattern, exact=True)
        if not badge:
            raise EventUIError(f'未确认首领难度为{label}')
        if not s.find('混沌发电机'):
            raise EventUIError('当前首领与本期记录不一致')
        return s

    def hub(self):
        for _ in range(60):
            self.r.check_deadline()
            s = self.ui.capture()
            if self.dialog(s) or self.r.story_dialog(s) or self.r.entry_dialog(s):
                continue
            if legacy_hub(s):
                return s
            if s.find('活动剧情一览', (250, 0, 710, 70)):
                self.ui.expect_click('关闭', (350, 445, 615, 515), exact=True)
                continue
            if s.find('BOSS详情|队伍编组', (0, 0, 750, 80)):
                self.ui.expect_click('取消', (250, 420, 950, 525), exact=True)
            elif event_layout(s) == 'map' or s.find('活动任务|讨伐证交换|活动剧情|水都的回忆', (0, 0, 350, 80)):
                self.ui.click((32, 30))
            elif s.find('WIN|获得道具|伤害报告|战斗胜利'):
                self.ui.expect_click('下一步', (700, 400, 950, 530), exact=True)
            else:
                time.sleep(.5)
        raise EventUIError('无法返回复刻活动首页')

    def sourced_boss(self, label, difficulty):
        for attempt in range(self.r.options.get('max_boss_attempts', 6)):
            if difficulty == 'special':
                if self.special_complete():
                    self.r.log('特别首领已通过，表演赛已解锁')
                    return self.hub()
            detail = self.boss_detail(label)
            # SP has a different header; only VH exposes this kill counter.
            defeated = self.ui.number(detail, (891, 28, 926, 56)) if difficulty == 'very_hard' else None
            if defeated is not None and defeated > 0:
                self.r.log(f'{label}首领已讨伐，跳过')
                return self.home()
            if difficulty == 'very_hard' and defeated is None:
                raise EventUIError('高难首领讨伐次数无法确认')
            mode_box = detail.find(r'(?:模式|MODE|阶段)[123]', (0, 0, 960, 170))
            mode = int(re.search('[123]', normalized(mode_box.text))[0]) if mode_box else 1
            if difficulty == 'special' and not mode_box:
                raise EventUIError('特别战斗模式未知，不能套用作业')
            before_hp = detail.find(r'\d+/\d+', (250, 265, 720, 315))
            parties = load_parties(self.r.options.get('teams', 'cache/game/strategies/revival_teams.yml'), self.r.event.name, difficulty, mode)
            if not parties:
                self.r.report['pending'].append(f'{label}模式{mode}没有对应作业')
                return self.home()
            challenge = detail.find('挑战', (720, 420, 950, 525), exact=True)
            if not detail.blue_button(challenge):
                self.r.report['pending'].append(label+'挑战不可用，未购买或追加消费')
                return self.home()
            if attempt >= parties[0].max_attempts:
                self.r.report['pending'].append(label+'作业达到尝试上限')
                return self.home()
            self.ui.expect_click('挑战', (720, 420, 950, 525), exact=True)
            self.ui.wait(lambda s: s.find('队伍编组'), '首领编队')
            party = parties[0]
            ready, selection = EventFormation(self.ui).select(party)
            if not ready:
                self.r.report['pending'].append(f'{label}作业不达标：{selection}')
                return self.home()
            result = EventCombat(self.r).run(party, selection['order'])
            self.r.report['battles'].append({'boss': difficulty, 'mode': mode, 'source': party.source, **vars(result)})
            if result.outcome != 'settled':
                self.r.report['pending'].append(label+'未成功：'+result.reason)
                return self.home()
            self.home()
            if difficulty == 'very_hard':
                # VH locks its entry immediately after success. Verify the
                # newly accessible SP details instead of reopening that lock.
                self.special_complete()
                self.boss_detail('特别')
                self.r.log('高难已通过，特别首领详情已解锁')
                return self.home()
            if difficulty == 'special':
                if self.special_complete():
                    return self.hub()
                after = self.boss_detail(label)
                after_hp = after.find(r'\d+/\d+', (250, 265, 720, 315))
                if not before_hp or not after_hp or before_hp.text == after_hp.text:
                    self.r.report['pending'].append(label+'血量进度未确认，停止重试')
                    return self.home()
                self.home()
        self.r.report['pending'].append(label+'达到尝试上限')
