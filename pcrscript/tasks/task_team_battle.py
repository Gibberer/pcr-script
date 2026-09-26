"""Daily team battle with a proven simulation before every real attack."""
from __future__ import annotations

from hashlib import sha256
import json

import cv2 as cv
import numpy as np

from .base import BaseTask, Event, EventNews, TimeLimitTask
from .event_formation import EventFormation
from .registry import register
from ..game_ui.avatars import feature
from ..game_ui.screen import EventUI, EventUIError, normalized
from ..game_ui.special_equipment import auto_equip_special
from ..game_ui.team_battle import Boss, boss_detail, can_repeat, map_bosses, map_ready, meets_reference, parse_remaining_time, priority, recommendation_damage, recommendation_time, result_damage
from ..run_session import clock as time


def validate_options(options: dict) -> dict:
    value = dict(options)
    for key, default, upper in (('timeout', 3600, 7200), ('battle_timeout', 220, 600),
                                ('max_real_attacks', 3, 3), ('max_simulations', 12, 40)):
        number = value.setdefault(key, default)
        if type(number) is not int or not 1 <= number <= upper:
            raise ValueError(f'TeamBattle.{key}必须是1到{upper}的整数')
    if type(value.setdefault('simulation_only', False)) is not bool:
        raise ValueError('TeamBattle.simulation_only必须是布尔值')
    return value


class BossChanged(EventUIError):
    """The guild changed the selected boss before its simulated plan was used."""


class TaskDeadline(EventUIError):
    """The task budget expired between safe actions."""


ORPHAN_EXTENSION = '__visible_extension_team__'


@register('team_battle', requires_home=True)
class TeamBattle(TimeLimitTask):
    config_section = 'TeamBattle'

    @staticmethod
    def map_clear(screen):
        # Reward chest animation leaves the map OCR visible behind a dark veil.
        return bool(map_ready(screen) and np.mean(screen.image[395:455, 300:665]) > 110)

    @staticmethod
    def valid(event_news: EventNews, args=None):
        if TeamBattle.event_valid(event_news.clanBattle):
            return TeamBattle, [event_news.clanBattle]
        return None

    @classmethod
    def prepare(cls, config, event: Event | None = None):
        validate_options(config.get(cls.config_section, {}))
        if event is None:
            from ..news import fetch_event_news
            event = fetch_event_news().clanBattle
        return (event,), {}, None if cls.event_valid(event) else {'status': 'unavailable'}

    def __init__(self, robot):
        super().__init__(robot)
        self.options = validate_options(self.task_options())
        self.ui = EventUI(self.driver, self.options.get('output', 'cache/daily/team_battle'))
        self.deadline = time.monotonic() + self.options['timeout']
        self.report = dict(status='running', battles=[], pending=[], simulations=[], attempts=0,
                           normal_attacks=0, extension_attacks=0)
        self.formation = EventFormation(self.ui)
        self.teams = {}
        self.tried = set()
        self.tried_teams = set()
        self.spent = set()
        self.carry = None

    def save_report(self):
        (self.ui.output/'report.json').write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')

    def check_deadline(self):
        if time.monotonic() >= self.deadline:
            raise TaskDeadline('团队战任务达到运行时限，剩余挑战待下次运行')

    def popup(self, screen) -> bool:
        """Dismiss only a visible modal button, including the two first-entry dialogs."""
        if screen.find('报酬确认', (300, 0, 655, 85), exact=True):
            button = screen.find('确认', (365, 440, 590, 520), exact=True)
            if button:
                self.ui.click(button)
                return True
        if screen.find('首领魔物等级.*提升', (240, 110, 720, 180)):
            button = screen.find('关闭', (350, 335, 610, 410), exact=True)
            if button:
                self.ui.click(button)
                return True
        if screen.find('剩余时间返还通知', (300, 110, 655, 190), exact=True):
            button = screen.find('关闭', (365, 335, 590, 415), exact=True)
            if button:
                self.ui.click(button)
                return True
        button = screen.find('关闭|确认|我知道了', (320, 390, 680, 525), exact=True)
        if self.map_clear(screen) and (button is None or normalized(button.text) != '关闭'):
            return False
        if button and (screen.find('团队战|行会模式|CP|挑战次数|玩法说明')
                       or screen.find('关闭', (320, 390, 680, 525), exact=True)):
            self.ui.save('team_battle_entry_dialog', screen)
            self.ui.click(button)
            return True
        if not map_ready(screen) and screen.find('团队战|玩法说明|行会模式'):
            close = screen.find('关闭|×|X', (780, 15, 955, 130), exact=True)
            if close:
                self.ui.save('team_battle_entry_dialog', screen)
                self.ui.click(close)
                return True
        return False

    def enter(self):
        for _ in range(50):
            self.check_deadline()
            screen = self.ui.capture()
            if self.popup(screen):
                continue
            if self.map_clear(screen):
                return screen
            if screen.find('冒险', (30, 0, 175, 65), exact=True):
                entry = screen.find('团队战', (790, 210, 950, 355), exact=True)
                if not entry:
                    return None
                self.ui.click(entry)
            elif screen.find('冒险', (475, 475, 595, 535), exact=True):
                self.ui.click(screen.find('冒险', (475, 475, 595, 535), exact=True))
            else:
                time.sleep(.6)
        raise EventUIError('团队战入口或首次弹窗无法确认')

    def map(self):
        for _ in range(35):
            self.check_deadline()
            screen = self.ui.capture()
            if self.map_clear(screen):
                return screen
            if self.popup(screen):
                continue
            time.sleep(.5)
        raise EventUIError('团队战地图未恢复')

    def count(self, screen, roi):
        value = self.ui.number(screen, roi)
        if value is None or value < 0:
            raise EventUIError('团队战次数无法确认')
        return value

    def counts(self, screen):
        return self.count(screen, (397, 391, 431, 424)), self.count(screen, (558, 393, 581, 421))

    def open_boss(self, boss: Boss):
        screen = self.map()
        visible = next((b for b in map_bosses(screen) if b.lane == boss.lane and b.lap == boss.lap), None)
        if visible is None:
            raise BossChanged('目标首领已变化，停止使用旧模拟战结果')
        self.ui.click((visible.x, 270))
        screen = self.ui.wait(lambda s: s.find('魔物详情', (25, 15, 245, 78), exact=True), '团队战魔物详情')
        return boss_detail(screen, visible), screen

    def all_bosses(self, screen):
        result = []
        for boss in map_bosses(screen):
            detail, _ = self.open_boss(boss)
            result.append(detail)
            self.ui.expect_click('取消', (560, 425, 755, 505), exact=True)
            self.map()
        return result

    def wait_bosses(self, screen):
        bosses = self.all_bosses(screen)
        if bosses:
            return screen, bosses
        # Other guild members can defeat all five bosses while this task is
        # entering. The map briefly has only chests, then reward/stage dialogs,
        # before the next lap becomes visible.
        defeated = len(screen.all('已击败', (0, 170, 960, 360)))
        limit = min(self.deadline, time.monotonic() + (300 if defeated >= 3 else 20))
        while time.monotonic() < limit:
            time.sleep(2)
            screen = self.map()
            bosses = self.all_bosses(screen)
            if bosses:
                return screen, bosses
        return screen, []

    def mode(self, screen, simulate: bool):
        is_simulation = bool(screen.find('设定为模拟战|模拟战无法获得报酬', (245, 395, 900, 480)))
        if is_simulation != simulate:
            target = '模拟战' if simulate else '实战'
            button = screen.find(target, (690, 84, 925, 132), exact=True)
            if not button:
                raise EventUIError('团队战模式切换按钮未知')
            self.ui.click(button)
            screen = self.ui.capture()
        is_simulation = bool(screen.find('设定为模拟战|模拟战无法获得报酬', (245, 395, 900, 480)))
        if is_simulation != simulate:
            raise EventUIError('团队战模拟/实战模式未核对')
        return screen

    def team(self, screen):
        if not screen.find('队伍编组', (300, 0, 650, 70), exact=True):
            raise EventUIError('推荐队伍未进入编队页面')
        if len(self.formation.occupied_slots(screen)) != 5:
            return None
        labels = tuple(normalized(screen.text((x-48, 399, x+47, 426))) for x, _ in self.formation.slots)
        if any(not label or len(label) > 10 for label in labels):
            return None
        portraits = tuple(feature(screen.image[428:470, x-30:x+32]) for x, _ in self.formation.slots)
        for key, prior in self.teams.items():
            if labels == prior['labels'] and all(float(a @ b) >= .82
                                                 for a, b in zip(portraits, prior['portraits'])):
                return key
        key = f'team-{1 + max((int(old[5:]) for old in self.teams if old.startswith("team-")
                                 and old[5:].isdigit()), default=0)}'
        self.teams[key] = dict(labels=labels, portraits=portraits)
        return key

    def unavailable_team(self, key):
        chosen = self.teams[key]
        return any(label == old_label and float(face @ old_face) >= .72
                   for old_key in self.spent
                   for label, face in zip(chosen['labels'], chosen['portraits'])
                   for old_label, old_face in zip(self.teams[old_key]['labels'], self.teams[old_key]['portraits']))

    @staticmethod
    def used_member_marked(screen):
        if screen.find('参加团队战', (35, 465, 585, 515)):
            return True
        for x in (96, 205, 314, 423, 532):
            hsv = cv.cvtColor(screen.image[482:505, x-48:x+48], cv.COLOR_BGR2HSV)
            red = ((hsv[:, :, 0] < 12) | (hsv[:, :, 0] > 170)) & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 60)
            if float(np.mean(red)) > .4:
                return True
        return False

    @staticmethod
    def recommendation_signature(screen, button):
        y = button.center[1]
        patch = screen.image[max(185, y-75):min(425, y+32), 175:625]
        return sha256(patch.tobytes()).hexdigest()

    @staticmethod
    def recommendation_owned(screen, button):
        """A missing character is an empty gray portrait in the recommendation row."""
        center = button.center[1]-33
        if center-24 < 185 or center+24 > 421:
            return False
        if screen.find('未持有|限制实战使用|已参加团队战', (175, center-50, 625, center+50)):
            return False
        for x in (224, 312, 402, 491, 581):
            patch = cv.cvtColor(screen.image[center-24:center+24, x-22:x+22], cv.COLOR_BGR2HSV)
            if float(np.mean((patch[:, :, 1] > 55) & (patch[:, :, 2] > 80))) < .15:
                return False
        return True

    def recommendation_restricted(self, screen, button):
        # The portrait badges are too small for reliable full-frame OCR.
        center = button.center[1]-33
        roi = (175, center-35, 625, center+35)
        enlarged = self.ui.read_region(screen, roi)
        return bool(enlarged.find('未持有|限制实战使用|已参加团队战', roi))

    @staticmethod
    def recommendation_list(screen):
        return bool(screen.find('推荐编组', (380, 15, 570, 70), exact=True)
                    and screen.find('高级', (520, 145, 745, 180), exact=True))

    @staticmethod
    def recommendation_save_state(screen, button):
        """Locate this row's save checkbox and read its blue check mark."""
        y = button.center[1]
        label = screen.find('保存队伍', (810, max(185, y-70), 910, y-25), exact=True)
        if label is None:
            raise EventUIError('推荐队伍保存开关无法定位')
        x, check_y = round(label.center[0]), round(label.center[1]+39)
        if not (835 <= x <= 880 and 220 <= check_y <= 420):
            raise EventUIError('推荐队伍保存开关位置异常')
        patch = cv.cvtColor(screen.image[check_y-8:check_y+8, x-8:x+8], cv.COLOR_BGR2HSV)
        blue = float(np.mean((patch[:, :, 0] > 90) & (patch[:, :, 0] < 130)
                             & (patch[:, :, 1] > 100) & (patch[:, :, 2] > 60)))
        if blue >= .25:
            return (x, check_y), True
        if blue <= .08:
            return (x, check_y), False
        raise EventUIError('推荐队伍保存开关状态无法确认')

    def ensure_recommendation_unsaved(self, screen, button):
        position, saved = self.recommendation_save_state(screen, button)
        if saved:
            self.ui.click(position)
            self.ui.wait(lambda s: self.recommendation_list(s)
                         and self.recommendation_save_state(s, button)[1] is False,
                         '取消保存推荐队伍', timeout=8)

    def recommendation(self, wanted=None, boss_hp=None):
        """Use advanced recommendations; a missing or occupied member rejects the row."""
        self.ui.expect_click('推荐编组', (770, 20, 925, 70), exact=True)
        screen = self.ui.wait(lambda s: s.find('推荐编组', (380, 15, 570, 70), exact=True), '团队战推荐编组')
        advanced = screen.find('高级', (520, 145, 745, 180), exact=True)
        if not advanced:
            raise EventUIError('推荐编组高级标签未知')
        self.ui.click(advanced)
        for _ in range(24):
            self.check_deadline()
            screen = self.ui.capture()
            if not self.recommendation_list(screen):
                raise EventUIError('推荐编组列表已离开，停止滑动')
            buttons = sorted(screen.all('使用', (625, 195, 800, 425)),
                             key=lambda button: recommendation_time(screen, button.center[1]) or 10_000)
            for button in buttons:
                signature = self.recommendation_signature(screen, button)
                if signature in self.tried and wanted is None:
                    continue
                estimate = recommendation_time(screen, button.center[1])
                reference = recommendation_damage(screen, button.center[1])
                # A row at the bottom can show "使用" while its damage or time
                # is clipped. Revisit it after a short scroll instead of
                # recording it as a rejected recommendation.
                if estimate is None or reference is None:
                    continue
                if ((boss_hp is not None and reference > boss_hp)
                        or (boss_hp is not None and reference == boss_hp
                            and 2*estimate+8 > 110)):
                    self.tried.add(signature)
                    continue
                if not self.recommendation_owned(screen, button):
                    self.tried.add(signature)
                    continue
                if self.recommendation_restricted(screen, button):
                    self.tried.add(signature)
                    continue
                self.ensure_recommendation_unsaved(screen, button)
                self.ui.click(button)
                time.sleep(1.5)
                formation = self.ui.wait(lambda s: self.formation_ready(s)
                                         or (s.find('未持有|无法使用|无法编组', (250, 135, 750, 395))
                                             and s.find('关闭|确认|取消', (250, 370, 720, 525), exact=True)
                                             and not s.find('队伍编组', (300, 0, 650, 70), exact=True)),
                                         '推荐队伍使用', timeout=15)
                if not self.formation_ready(formation):
                    self.tried.add(signature)
                    close = formation.find('关闭|确认|取消', (250, 370, 720, 525), exact=True)
                    if not close:
                        raise EventUIError('推荐队伍不可用弹窗缺少可识别关闭按钮')
                    self.ui.click(close)
                    self.ui.wait(lambda s: s.find('推荐编组', (380, 15, 570, 70), exact=True), '推荐队伍不可用返回')
                    continue
                names = self.team(formation)
                if (names and (wanted is None or names == wanted)
                        and names not in self.tried_teams
                        and not self.unavailable_team(names)
                        and not self.used_member_marked(formation)):
                    self.teams[names]['estimated_seconds'] = estimate
                    self.teams[names]['reference_damage'] = reference
                    self.tried.add(signature)
                    self.tried_teams.add(names)
                    return names
                self.tried.add(signature)
                self.ui.expect_click('取消', (630, 425, 775, 500), exact=True)
                screen = self.ui.wait(lambda s: s.find('推荐编组', (380, 15, 570, 70), exact=True), '返回推荐编组')
            before = self.ui.capture()
            if not self.recommendation_list(before):
                raise EventUIError('推荐编组列表已离开，停止滑动')
            old = sha256(before.image[185:425, 35:915].tobytes()).digest()
            # The center of the row contains portraits; holding there opens a
            # character page. The damage column has no portrait hit target.
            self.ui.swipe((120, 360), (120, 260), duration=250)
            after = self.ui.wait(lambda s: self.recommendation_list(s)
                                 or s.find('角色强化', (30, 0, 195, 65), exact=True),
                                 '推荐列表滑动后页面', timeout=8)
            if not self.recommendation_list(after):
                raise EventUIError('推荐列表滑动进入角色页面，停止后续输入')
            if sha256(after.image[185:425, 35:915].tobytes()).digest() == old:
                break
        self.ui.expect_click('关闭', (375, 445, 585, 510), exact=True)
        return None

    def equipped(self, names):
        result = auto_equip_special(self.ui, list(self.teams[names]['labels']))
        if result['unknown']:
            raise EventUIError('推荐队伍的特别装备槽位无法核对')
        return result

    @staticmethod
    def formation_ready(screen):
        return bool(screen.find('队伍编组', (300, 0, 650, 70), exact=True)
                    and not screen.find('魔物详情', (25, 15, 245, 78), exact=True)
                    and not screen.find('确认使用延长时间', (300, 0, 650, 75), exact=True))

    def open_formation(self, *, use_extension: bool = False, returned_time: int | None = None):
        self.ui.expect_click('挑战', (755, 420, 920, 500), exact=True)
        screen = self.ui.wait(lambda s: self.formation_ready(s)
                              or s.find('确认使用延长时间', (300, 0, 650, 75), exact=True),
                              '团队战挑战方式')
        if screen.find('确认使用延长时间', (300, 0, 650, 75), exact=True):
            if use_extension:
                value = screen.find(r'\d:\d{2}', (300, 178, 360, 215), exact=True)
                if value is None:
                    raise EventUIError('延长挑战的可用时间无法确认')
                minutes, seconds = map(int, normalized(value.text).split(':'))
                if seconds >= 60 or not 0 < minutes*60+seconds <= 90:
                    raise EventUIError('延长挑战时间无效')
                self.extension_time = minutes*60+seconds
                if returned_time is not None and self.extension_time != returned_time:
                    raise EventUIError('延长挑战时间与上次实战回执不一致')
                patch = cv.cvtColor(screen.image[379:410, 346:381], cv.COLOR_BGR2HSV)
                checked = float(np.mean((patch[:, :, 0] > 85) & (patch[:, :, 0] < 120)
                                        & (patch[:, :, 1] > 90) & (patch[:, :, 2] > 100))) > .12
                if not checked:
                    self.ui.click((363, 393))
                self.ui.expect_click('挑战', (590, 145, 700, 215), exact=True)
            else:
                self.ui.expect_click('挑战', (590, 260, 700, 330), exact=True)
            screen = self.ui.wait(self.formation_ready,
                                  '团队战编队')
        elif use_extension:
            raise EventUIError('额外挑战没有显示延长时间选择')
        time.sleep(1.5)
        screen = self.ui.capture()
        if not self.formation_ready(screen):
            screen = self.ui.wait(self.formation_ready, '团队战编队过渡完成')
        return screen

    def battle(self, simulate: bool, names, *, use_extension: bool = False,
               reference_damage: int | None = None, boss_hp: int | None = None):
        screen = self.ui.capture()
        label = '模拟战开始' if simulate else '战斗开始'
        button = screen.find(label, (775, 415, 940, 495), exact=True)
        if not screen.blue_button(button):
            raise EventUIError('团队战开战按钮不可用；未确认可用五人队伍')
        self.ui.save('team_battle_before_'+('simulation' if simulate else 'real'), screen)
        self.ui.click(button)
        started_at = time.monotonic()
        deadline = time.monotonic() + self.options['battle_timeout']
        started = False
        while time.monotonic() < deadline:
            screen = self.ui.capture()
            text = normalized(screen.text())
            if screen.find('团队战开始确认', (300, 0, 650, 75), exact=True):
                if simulate or not use_extension or not screen.find('要使用返还时间进行团队战吗', (285, 65, 690, 115)):
                    raise EventUIError('团队战开战确认与选定的挑战方式不符')
                confirm = screen.find('战斗', (475, 445, 705, 520), exact=True)
                if confirm is None:
                    patch = cv.cvtColor(screen.image[458:495, 545:645], cv.COLOR_BGR2HSV)
                    if float(np.mean((patch[:, :, 0] > 85) & (patch[:, :, 0] < 120)
                                     & (patch[:, :, 1] > 90) & (patch[:, :, 2] > 180))) < .5:
                        raise EventUIError('延长挑战最终确认按钮不可用')
                    confirm = (590, 478)
                elif not screen.blue_button(confirm):
                    raise EventUIError('延长挑战最终确认按钮不可用')
                self.ui.save('team_battle_extension_confirm', screen)
                self.ui.click(confirm)
                started_at = time.monotonic()
                continue
            if not simulate and screen.find('获得挑战报酬', (300, 95, 720, 215)):
                self.ui.save('team_battle_reward', screen)
                self.ui.click((480, 390))
                continue
            if ('模拟战中' if simulate else '伤害合计') in text and screen.find('菜单', (840, 0, 960, 60), exact=True):
                started = True
            settled_win = bool(screen.find('WIN|战斗胜利', (275, 70, 685, 250))
                               or (screen.find('伤害比例', (330, 430, 545, 510))
                                   and screen.find('100[.]00%', (450, 440, 575, 510))
                                   and screen.find('返还时间', (685, 420, 850, 475))))
            if settled_win:
                if simulate and '模拟战的战斗结果' not in text:
                    time.sleep(.4)
                    continue
                remaining = parse_remaining_time(screen)
                if remaining is None and not use_extension:
                    time.sleep(.4)
                    continue
                next_button = screen.find('下一步', (700, 445, 920, 520), exact=True)
                if next_button is None:
                    time.sleep(.4)
                    continue
                evidence = str(self.ui.save('team_battle_win_'+str(len(self.report['simulations'])+len(self.report['battles'])), screen))
                elapsed_wall = time.monotonic() - started_at
                self.ui.click(next_button)
                self.map_after_battle()
                return dict(win=True, remaining=remaining, elapsed_wall=round(elapsed_wall, 1),
                            reference_met=meets_reference(None, reference_damage, boss_hp, True),
                            evidence=evidence)
            if (screen.find('RESULT', (300, 0, 680, 140), exact=True)
                    and screen.find('伤害比例', (330, 430, 545, 510))
                    and (not simulate or screen.find('模拟战的战斗结果', (300, 425, 690, 475)))):
                ratio = screen.find(r'\d{1,3}(?:\.\d+)?%', (450, 440, 575, 510), exact=True)
                next_button = screen.find('下一步', (690, 435, 935, 520), exact=True)
                if ratio and next_button:
                    damage_ratio = float(normalized(ratio.text)[:-1])
                    if 0 <= damage_ratio < 100:
                        actual_damage = result_damage(screen)
                        if actual_damage is None:
                            raise EventUIError('团队战结算伤害无法确认')
                        evidence = str(self.ui.save('team_battle_'+('simulation' if simulate else 'real')+'_partial', screen))
                        self.ui.click(next_button)
                        self.map_after_battle()
                        return dict(win=False, damage_ratio=damage_ratio,
                                    actual_damage=actual_damage,
                                    reference_met=meets_reference(actual_damage, reference_damage,
                                                                  boss_hp, False), evidence=evidence)
            if (screen.find('LOSE|战斗失败|TIMEUP|时间到', (230, 50, 740, 360), exact=True)
                    and screen.find('下一步', (690, 435, 935, 520), exact=True)
                    and not screen.find('菜单', (840, 0, 960, 60), exact=True)):
                evidence = str(self.ui.save('team_battle_loss', screen))
                next_button = screen.find('下一步', (690, 435, 935, 520), exact=True)
                if next_button:
                    self.ui.click(next_button)
                    self.map_after_battle()
                return dict(win=False, evidence=evidence)
            if started and self.map_clear(screen):
                raise EventUIError('战斗返回地图但结算未确认')
            time.sleep(.4)
        raise EventUIError('团队战战斗结果超时；实战不得自动撤退')

    def map_after_battle(self):
        """Reward and returned-time dialogs may appear after the map first renders."""
        end = time.monotonic() + 35
        latest = None
        while time.monotonic() < end:
            screen = self.ui.capture()
            if self.popup(screen):
                latest = None
                continue
            if self.map_clear(screen):
                latest = screen
                if map_bosses(screen):
                    return screen
            time.sleep(.6)
        if latest is not None:
            return latest
        raise EventUIError('团队战战后地图与奖励弹窗未结算')

    def prepare_boss(self, boss: Boss, simulate: bool):
        current, screen = self.open_boss(boss)
        if (current.name, current.current_hp, current.maximum_hp) != (boss.name, boss.current_hp, boss.maximum_hp):
            self.ui.expect_click('取消', (560, 425, 755, 505), exact=True)
            raise BossChanged('首领身份或血量已变化，旧模拟战无效')
        return self.mode(screen, simulate)

    def try_boss(self, boss: Boss, cp_before: int, extension_before: int, wanted=None,
                 available_time: int | None = None, *, simulation_only: bool = False):
        orphan_extension = wanted == ORPHAN_EXTENSION
        if wanted is None:
            self.tried = set()
            self.tried_teams = set()
        for _ in range(self.options['max_simulations']-len(self.report['simulations'])):
            self.check_deadline()
            self.prepare_boss(boss, True)
            if wanted is None:
                names = self.recommendation(boss_hp=boss.current_hp)
            else:
                formation = self.open_formation(use_extension=True, returned_time=available_time)
                if orphan_extension:
                    available_time = self.extension_time
                    names = self.team(formation)
                    if names is None:
                        raise EventUIError('延长挑战未显示可核验的五人队伍')
                else:
                    names = None
                    for _ in range(5):
                        names = self.team(formation)
                        if names == wanted:
                            break
                        time.sleep(.6)
                        formation = self.ui.capture()
                    else:
                        raise EventUIError('追击未保留首次挑战的五人编队')
            if names is None:
                self.ui.expect_click('取消', (560, 425, 755, 505), exact=True)
                self.map()
                return None
            gear = self.equipped(names)
            reference = self.teams[names].get('reference_damage') if wanted is None else None
            simulation = self.battle(True, names, use_extension=wanted is not None,
                                     reference_damage=reference, boss_hp=boss.current_hp)
            self.report['simulations'].append(dict(boss=boss.name, lane=boss.lane, lap=boss.lap,
                                                   team_key=names, team=self.teams[names]['labels'],
                                                   estimated_seconds=self.teams[names].get('estimated_seconds'),
                                                   reference_damage=reference,
                                                   equipment=gear, **simulation))
            self.save_report()
            if simulation_only:
                return simulation
            if not (simulation['win'] or simulation.get('reference_met')):
                if wanted is not None:
                    return None
                continue
            if wanted is None and simulation['win'] and boss.full and not can_repeat(simulation['remaining']):
                continue
            if wanted is not None and (available_time is None or
                                       simulation['elapsed_wall']+8 > available_time):
                return None
            if time.monotonic() + self.options['battle_timeout'] + 60 >= self.deadline:
                raise TaskDeadline('团队战剩余运行时间不足以安全完成实战，待下次运行')
            self.prepare_boss(boss, False)
            current = self.open_formation(use_extension=wanted is not None,
                                          returned_time=available_time)
            for _ in range(5):
                if self.team(current) == names:
                    break
                time.sleep(.6)
                current = self.ui.capture()
            else:
                raise EventUIError('实战未保留模拟战的五人编队，停止开战')
            if wanted is None and self.used_member_marked(current):
                raise EventUIError('实战编队包含已参加团队战的角色，停止开战')
            real_gear = self.equipped(names)
            if real_gear['slots'] != gear['slots']:
                raise EventUIError('实战与模拟战的特别装备不同，停止开战')
            current = self.ui.capture()
            if self.team(current) != names:
                raise EventUIError('实战编队与模拟战五人不一致')
            self.report['in_flight'] = dict(boss=boss.name, lane=boss.lane, lap=boss.lap,
                                            team_key=names, team=self.teams[names]['labels'], cp_before=cp_before)
            self.save_report()
            real = self.battle(False, names, use_extension=wanted is not None,
                               reference_damage=reference, boss_hp=boss.current_hp)
            after = self.map()
            cp_after, extension_after = self.counts(after)
            if wanted is None and cp_after != cp_before-1:
                raise EventUIError('普通挑战后 CP 变化与预期不符，停止后续实战')
            if wanted is not None and (cp_after != cp_before or extension_after != extension_before-1):
                raise EventUIError('额外挑战后次数变化与预期不符，停止后续实战')
            row = dict(boss=boss.name, lane=boss.lane, lap=boss.lap,
                       team_key=names, team=self.teams[names]['labels'],
                       cp_before=cp_before, cp_after=cp_after, extension_after=extension_after,
                       simulation=simulation, equipment=real_gear, **real)
            self.report['battles'].append(row)
            self.report['attempts'] += 1
            self.report['remaining_normal'] = cp_after
            self.report['remaining_extension'] = extension_after
            self.report.pop('in_flight', None)
            self.save_report()
            return row
        return None

    def run(self, event: Event | None = None):
        try:
            self.report_progress('检查团队战开放状态与地图')
            if event is None:
                from ..news import fetch_event_news
                event = fetch_event_news().clanBattle
            if not self.event_valid(event):
                self.report['status'] = 'unavailable'
                return self.report
            screen = self.enter()
            if screen is None:
                self.report['status'] = 'unavailable'
                return self.report
            if self.options['simulation_only']:
                screen = self.map()
                cp, extension = self.counts(screen)
                self.report['remaining_normal'] = cp
                self.report['remaining_extension'] = extension
                _, bosses = self.wait_bosses(screen)
                if bosses:
                    minimum = min(boss.lap for boss in bosses)
                    for boss in sorted(bosses, key=lambda b: priority(b, minimum), reverse=True):
                        self.report_progress(f'模拟 {boss.name} · 核对推荐队伍')
                        if boss.full and boss.lap+1 > minimum+2:
                            continue
                        self.try_boss(boss, cp, extension, simulation_only=True)
                        if self.report['simulations']:
                            break
                if not self.report['simulations']:
                    self.report['pending'].append('未找到可模拟的首领与高级推荐队伍')
                self.report['status'] = 'complete' if self.report['simulations'] else 'partial'
                return self.report
            changed_retries = 0
            remaining_counts = None
            for _ in range(self.options['max_real_attacks']*2+3):
                self.check_deadline()
                self.report_progress(f"团队战 · 已完成 {self.report['attempts']} 次实战",
                                     self.report['attempts'], self.options['max_real_attacks']*2)
                screen = self.map()
                cp, extension = self.counts(screen)
                self.report['remaining_normal'] = cp
                self.report['remaining_extension'] = extension
                remaining_counts = (cp, extension)
                if cp == 0 and extension == 0:
                    break
                if self.report['attempts'] >= self.options['max_real_attacks']*2:
                    break
                screen, bosses = self.wait_bosses(screen)
                if not bosses:
                    self.report['pending'].append('地图未出现可识别的首领轮次，可能仍在等待行会进度刷新')
                    break
                cp, extension = self.counts(screen)
                self.report['remaining_normal'] = cp
                self.report['remaining_extension'] = extension
                remaining_counts = (cp, extension)
                if cp == 0 and extension == 0:
                    break
                if self.carry:
                    candidates = sorted((b for b in bosses if b.full),
                                        key=lambda b:(b.lane == self.carry['lane']
                                                      and b.lap == self.carry['lap']+1,
                                                      priority(b, min(v.lap for v in bosses))), reverse=True)
                    changed = False
                    for boss in candidates:
                        if extension == 0:
                            break
                        try:
                            row = self.try_boss(boss, cp, extension, self.carry['team_key'],
                                                self.carry['remaining'])
                        except BossChanged:
                            changed = True
                            break
                        if row:
                            self.report['extension_attacks'] += 1
                            self.spent.add(self.carry['team_key'])
                            self.carry = None
                            if not row['win']:
                                self.report['pending'].append('延长挑战实战未击败首领；已对账消耗，继续核对剩余普通次数')
                            break
                    if changed:
                        changed_retries += 1
                        if changed_retries > 3:
                            self.report['pending'].append('行会进度连续改变首领，已停止使用过期模拟结果')
                            break
                        continue
                    if self.carry is None:
                        continue
                    self.report['pending'].append('延长挑战未找到同队伍可安全击杀的首领')
                    break
                if extension:
                    if extension != 1:
                        self.report['pending'].append('延长挑战队伍不唯一，无法安全接续')
                        break
                    changed = False
                    selected = None
                    for boss in sorted((b for b in bosses if b.full),
                                       key=lambda b: priority(b, min(v.lap for v in bosses)), reverse=True):
                        try:
                            selected = self.try_boss(boss, cp, extension, ORPHAN_EXTENSION)
                        except BossChanged:
                            changed = True
                            break
                        if selected:
                            break
                    if changed:
                        changed_retries += 1
                        if changed_retries > 3:
                            self.report['pending'].append('行会进度连续改变首领，已停止使用过期模拟结果')
                            break
                        continue
                    if selected:
                        self.report['extension_attacks'] += 1
                        self.spent.add(selected['team_key'])
                        if not selected['win']:
                            self.report['pending'].append('延长挑战实战未击败首领；已对账消耗，继续核对剩余普通次数')
                        continue
                    self.report['pending'].append('延长挑战未找到可安全完成的首领；已参战队伍保留在游戏内')
                    break
                if cp == 0 or self.report['normal_attacks'] >= self.options['max_real_attacks']:
                    break
                minimum = min(b.lap for b in bosses)
                ordered = sorted(bosses, key=lambda b: priority(b, minimum), reverse=True)
                selected = None
                changed = False
                for boss in ordered:
                    if boss.full and boss.lap+1 > minimum+2:
                        continue
                    try:
                        selected = self.try_boss(boss, cp, extension)
                    except BossChanged:
                        changed = True
                        break
                    if selected:
                        break
                if changed:
                    changed_retries += 1
                    if changed_retries > 3:
                        self.report['pending'].append('行会进度连续改变首领，已停止使用过期模拟结果')
                        break
                    continue
                if selected is None:
                    self.report['pending'].append('当前首领均无可核验的五人高级推荐队伍或模拟战伤害未达参考目标')
                    break
                self.report['normal_attacks'] += 1
                if not selected['win']:
                    self.spent.add(selected['team_key'])
                    continue
                if selected['extension_after'] > extension and can_repeat(selected['simulation']['remaining']):
                    self.carry = selected
                else:
                    self.spent.add(selected['team_key'])
            else:
                self.report['pending'].append('团队战达到安全战斗上限')
            if remaining_counts != (0, 0) and not self.report['pending']:
                self.report['pending'].append('仍有未完成挑战次数')
            self.report['status'] = 'complete' if not self.report['pending'] else 'partial'
            return self.report
        except TaskDeadline as error:
            if self.report.get('in_flight'):
                self.report['status'] = 'error'
                self.report['pending'].append('实战结果尚未与地图次数对账：'+str(error))
                raise
            self.report['status'] = 'partial'
            self.report['pending'].append(str(error))
            return self.report
        except Exception as error:
            self.report['status'] = 'error'
            self.report['pending'].append(str(error))
            self.ui.save('team_battle_error')
            raise
        finally:
            self.save_report()
