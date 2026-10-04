"""Bounded event combat: inspect builds before spending an attempt."""
from __future__ import annotations
from typing import TYPE_CHECKING, Sequence
from .base import Point
from .event_strategy import EventParty, MemberRequirement
from ..game_ui.screen import EventScreen, TextBox
if TYPE_CHECKING:
    from .task_story_event import CampaignClean
from collections import defaultdict
from dataclasses import asdict, dataclass
import re
from pcrscript.run_session import clock as time

import cv2 as cv
import numpy as np

from ..game_ui.screen import EventUIError, normalized
from ..game_ui.battle_status import portrait_states
from .strategy_trial import TrialFormation
from .strategy_party_pool import boss_parties, next_boss_party
from ..templates import ImageTemplate


def quest_stars(screen: EventScreen, row: TextBox) -> int:
    y = row.center[1]+13
    patch = screen.image[max(0, y-18):y+18, 495:579]
    hsv = cv.cvtColor(patch, cv.COLOR_BGR2HSV)
    mask = cv.inRange(hsv, np.array([12, 90, 140]), np.array([40, 255, 255]))
    return sum(float(np.mean(mask[:, x-8:x+9] > 0)) > .18 for x in (16, 43, 69))


def boss_cleared(screen: EventScreen, row: TextBox) -> bool:
    return bool(screen.find("通关", (730, row.center[1]-30, 785, row.center[1]-5)))


def boss_locked(screen: EventScreen, row: TextBox) -> bool:
    """The gold padlock is anchored to the upper-left of its own boss row."""
    y = row.center[1]
    hsv = cv.cvtColor(screen.image[y-30:y, 730:760], cv.COLOR_BGR2HSV)
    gold = cv.inRange(hsv, np.array([12, 90, 140]), np.array([40, 255, 255]))
    return float(np.mean(gold > 0)) > .3


def boss_mode(screen: EventScreen) -> int | None:
    item = screen.find(r"(?:模式|MODE)\s*[123]", (0, 0, 940, 100))
    return int(re.search(r"[123]", item.text)[0]) if item else None


@dataclass
class BattleResult:
    outcome: str
    reason: str = ""


class EarlyCasualty(EventUIError):
    """A member fell before the paused battle settings could be checked."""


class EventCombat:
    # Ordered left to right, matching the order displayed in party formation.
    portraits = [(196, 400, 282, 485), (315, 400, 402, 485),
                 (438, 400, 522, 485), (557, 400, 643, 485), (678, 400, 763, 485)]

    def __init__(self, runner: CampaignClean) -> None:
        self.r = runner
        self.ui = runner.ui
        self.templates = {k: ImageTemplate(k) for k in
                          ("btn_menu_text", "btn_giveup", "btn_giveup_blue", "btn_next_step", "btn_auto")}

    def match(self, key: str, screen: EventScreen) -> Point | None:
        return self.templates[key].match(screen.image)

    def retreat(self, reason: str) -> BattleResult:
        """The battle-menu retreat only; never the boss-detail run reset."""
        # An UB animation can hide the menu for several observations. Keep
        # checking the result screen and retry the labeled battle menu when it
        # returns; never guess a coordinate while controls are hidden.
        for _ in range(45):
            s = self.ui.capture()
            if s.find('WIN|战斗胜利|战斗失败|伤害报告') or self.match('btn_next_step', s):
                return BattleResult('settled', '战斗已结束，取消撤退并核对结果')
            if (s.event_quests or s.find("BOSS详情|关卡详情|队伍编组", (0, 0, 730, 70))
                    or getattr(self.r, 'combat_return', lambda frame: False)(s)):
                self.r.log("已退出本次战斗："+reason)
                return BattleResult("retreated", reason)
            if self.r.story_dialog(s):
                continue
            button = self.match("btn_giveup_blue", s) or self.match("btn_giveup", s)
            if not button and s.find("战斗菜单|放弃这场|放弃战斗|退出战斗"):
                button = s.find("放弃|退出", (200, 150, 900, 510), exact=True)
            if button:
                self.ui.click(button)
            else:
                menu = self.match("btn_menu_text", s) or s.find('菜单', (840, 0, 960, 60), exact=True)
                if menu:
                    self.ui.click(menu)
                    continue
                time.sleep(.5)
        self.ui.save("retreat_failed")
        raise EventUIError("无法确认战斗撤退，停止后续操作")

    @staticmethod
    def paused_instant(screen: EventScreen, index: int) -> bool:
        x = round(306+87.5*index)
        hsv = cv.cvtColor(screen.image[190:217, x+23:x+49], cv.COLOR_BGR2HSV)
        return bool(np.mean((hsv[:, :, 0] > 80) & (hsv[:, :, 0] < 110) &
                            (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 160)) > .25)

    @staticmethod
    def paused_defeated(screen: EventScreen, index: int) -> bool:
        """Dead portraits have a dark face and no green HP in the pause menu."""
        x = round(306+87.5*index)
        face = screen.image[200:268, x-33:x+33]
        bar = screen.image[276:283, x-33:x+33].astype(np.int16)
        green = np.mean((bar[:, :, 1] > bar[:, :, 2]+22) &
                        (bar[:, :, 1] > bar[:, :, 0]+30))
        return bool(green < .08 and cv.cvtColor(face, cv.COLOR_BGR2HSV)[:, :, 2].mean() < 145)

    def configure_paused(self, party: EventParty, order: Sequence[str], *, screen=None) -> bool:
        """Pause during setup so animations and stage stories cannot race SET."""
        pause_deadline = time.monotonic()+120
        stable = 0
        menu_attempts = 0
        last_menu_request = 0.0
        while time.monotonic() < pause_deadline:
            self.r.check_deadline()
            # The caller has just observed the menu. Act on that observation
            # before another OCR/capture consumes the opening at 4x speed.
            s = screen if screen is not None else self.ui.capture()
            screen = None
            if s.find('进行中战斗') and s.find('主菜单'):
                # The menu is readable while still scaling/fading in. Its
                # portrait coordinates are valid only at the final position.
                ready = (s.find('主菜单', (420, 70, 540, 103), exact=True)
                         and s.find('返回', (285, 415, 385, 460), exact=True))
                stable = stable+1 if ready else 0
                if stable >= 2:
                    break
                time.sleep(.3)
                continue
            stable = 0
            if s.find('WIN|战斗胜利|战斗失败|TIMEUP|伤害报告'):
                return False
            if (s.battle_dialogue() or s.find('跳过这个剧情')) and self.r.story_dialog(s):
                # A first-entry or phase story can close an already requested
                # menu. After skipping it, obtain a fresh menu observation.
                menu_attempts = 0
                continue
            menu = s.find('菜单', (840, 0, 960, 60), exact=True) or self.match('btn_menu_text', s)
            if (menu and not s.find('返回', (285, 415, 385, 460), exact=True)
                    and menu_attempts < 3
                    and (menu_attempts == 0 or time.monotonic()-last_menu_request >= 2)):
                self.ui.click(menu, delay=.2)
                menu_attempts += 1
                last_menu_request = time.monotonic()
            elif not self.r.story_dialog(s):
                time.sleep(.3)
        else:
            raise EventUIError('无法暂停战斗核对SET，停止后续操作')
        tag = getattr(self.r, '_battle_evidence_id', '')
        suffix = '_'+tag if isinstance(tag, str) and tag else ''
        self.ui.save('battle_before_settings'+suffix, s)
        if party:
            required = {normalized(m.name): m.instant for m in party.members}
            if not order or len(order) != 5 or set(map(normalized, order)) != set(required):
                raise EventUIError('SET对应角色顺序未核验')
            defeated = [index for index in range(5) if self.paused_defeated(s, index)]
            if len(defeated) > getattr(party, 'allow_deaths', 0):
                raise EarlyCasualty(f'暂停菜单确认减员{len(defeated)}人，位置{defeated}')
            for index, name in enumerate(order):
                if index in defeated:
                    continue
                s = self.ui.capture()
                if self.paused_instant(s, index) != required[normalized(name)]:
                    self.ui.click((round(306+87.5*index), 237), delay=.8)
                    s = self.ui.capture()
                    if self.paused_instant(s, index) != required[normalized(name)]:
                        raise EventUIError('暂停菜单内SET状态核验失败，保留暂停状态')
        s = self.ui.capture()
        desired_auto = getattr(party, 'auto', True)
        expected_auto = 'AUTO开启' if desired_auto else 'AUTO关闭'
        opposite_auto = 'AUTO关闭' if desired_auto else 'AUTO开启'
        if s.find(opposite_auto, (400, 330, 550, 385)):
            self.ui.click((480, 358))
        s = self.ui.wait(lambda frame: frame.find(expected_auto, (400, 330, 550, 385)), expected_auto, timeout=5)
        evidence = self.ui.save('battle_after_settings'+suffix, s)
        confirm = getattr(self.r, 'combat_settings_confirmed', None)
        if callable(confirm):
            confirm(str(evidence))
        self.ui.expect_click('返回', (260, 405, 410, 465), exact=True)
        # The return animation can leave the old panel in the next capture.
        # Observe its closure before the main loop can request a menu again.
        self.ui.wait(lambda frame: not frame.find('主菜单', (300, 30, 660, 150), exact=True)
                     and not frame.find('进行中战斗'), '返回战斗', timeout=10)
        return True

    def run(self, party: EventParty | None = None, order: Sequence[str] | None = None, resume: bool = False) -> BattleResult:
        if not resume:
            formation = self.ui.capture()
            start = formation.find("战斗开始", (740, 390, 950, 510), exact=True)
            if not formation.blue_button(start):
                return BattleResult("blocked", "战斗开始按钮不可用，未消耗挑战次数")
            self.ui.click(start)
        deadline = time.monotonic()+self.r.options.get("battle_timeout", 220)
        started = None
        configured = False
        dead_frames = 0
        result = None
        while time.monotonic() < deadline:
            self.r.check_deadline()
            s = self.ui.capture()
            observe = getattr(self.r, 'observe_battle', None)
            if observe:
                observe(s)
            if getattr(self.r, 'combat_pre_dialog', lambda frame: False)(s):
                continue
            if (s.battle_dialogue() or s.find('跳过这个剧情')) and self.r.story_dialog(s):
                continue
            if s.find("体力回复|体力恢复|购买体力"):
                self.ui.expect_click("取消", (200, 300, 800, 510), exact=True)
                return BattleResult("blocked", "体力不足")
            if s.find('进行中战斗') and s.find('主菜单'):
                started = started or time.monotonic()
                try:
                    configured = self.configure_paused(party, order, screen=s)
                except EarlyCasualty as error:
                    return self.retreat(str(error))
                except EventUIError as error:
                    return self.retreat('SET核验中断：'+str(error))
                continue
            in_battle = self.match("btn_menu_text", s) or s.find(r"\d:\d{2}", (750, 0, 850, 55))
            if in_battle:
                started = started or time.monotonic()
                if not configured:
                    try:
                        configured = self.configure_paused(party, order, screen=s)
                    except EarlyCasualty as error:
                        return self.retreat(str(error))
                    except EventUIError as error:
                        return self.retreat('SET核验中断：'+str(error))
                    continue
                # Require repeated dark faces with empty, visible HP bars;
                # colored KO portraits and UB flashes need separate cues.
                if time.monotonic()-started > 8:
                    dark = len(portrait_states(s.image, self.portraits)['fallen'])
                    dead_frames = dead_frames+1 if (party.allow_deaths if party else 0) < dark < 5 else 0
                    if dead_frames >= 3:
                        return self.retreat("减员超出队伍容许值，尝试下一队")
            elif s.find("战斗失败|挑战失败|LOSE|DEFEAT"):
                result = BattleResult("failed", "战斗失败")
            elif s.find("伤害报告|造成的伤害|本次伤害|TIMEUP|时间到|战斗结束"):
                # A timed-out SP attempt can preserve damage. It is progress
                # only after the boss screen changes, checked by EventBattles.
                result = BattleResult("settled", "战斗结算，待核对首领状态")
            elif s.find("WIN|胜利|获得经验|获得玛那") or self.match("btn_next_step", s):
                result = result or BattleResult("settled", "战斗结算，待核对关卡状态")
            if (s.event_quests or (started and s.find("BOSS详情|关卡详情", (0, 0, 730, 70)))
                    or (started and getattr(self.r, 'combat_return', lambda frame: False)(s))):
                return result or BattleResult("settled", "已返回关卡，待核对进度")
            if result:
                button = (getattr(self.r, 'combat_result_button', lambda frame: None)(s)
                          or self.match("btn_next_step", s)
                          or s.find("下一步|确认|确定|关闭", (250, 330, 950, 525), exact=True))
                if button:
                    self.ui.click(button)
                else:
                    self.r.story_dialog(s)
            elif not in_battle and (getattr(self.r, 'combat_dialog', lambda frame: False)(s) or self.r.story_dialog(s)):
                continue
            elif s.find("战斗设定", (250, 0, 720, 100)):
                self.ui.expect_click("确认|确定", (400, 350, 900, 510), exact=True)
            time.sleep(.3)
        return self.retreat("单次战斗超时")


class EventBattles:
    def __init__(self, runner: CampaignClean) -> None:
        self.r = runner
        self.ui = runner.ui
        self.formation = TrialFormation(self.ui)
        self.combat = EventCombat(runner)
        self.source_pools = {}

    def audit_source_trial(self, party, selection, label, mode):
        """Check the live build without pretending it was specified by a guide."""
        from ..game_ui.character_equipment import inspect_unreleased_equipment
        from .task_home import ToHomePage
        members = [self.formation.observed.get(normalized(m.name)) for m in party.members]
        if any(m is None for m in members):
            raise EventUIError('本期作业队伍的实时培养观察不完整，未开战')
        unknown = [m for m in members if m.identity_verified and m.unique is None and m.unique2 is None]
        if unknown:
            getattr(self.r, 'report_progress', lambda message: None)('活动首领 · 人物页核验专武')
            self.r.home()
            for member in unknown:
                proof = inspect_unreleased_equipment(self.ui, member.name)
                if proof:
                    member.unique = member.unique2 = False
                    member.equipment_evidence = proof
                ToHomePage(self.r.robot).run(timeout=60)
            self.r.enter()
            self.r.quests(bosses=True)
            self.ui.expect_click(label, (740, 200, 930, 400), exact=True)
            detail = self.ui.wait(lambda s: s.find('BOSS详情', (0, 0, 730, 70)), '首领详情')
            if boss_mode(detail) != mode:
                raise EventUIError('专武核验后首领模式发生变化，未开战')
            self.ui.expect_click('挑战', (740, 430, 945, 515), exact=True)
            self.ui.wait(lambda s: s.find('队伍编组', (250, 0, 730, 70)), '首领编队')
            # Leaving an unstarted formation restores the previously saved
            # team. Rebuild the source party; never start that restored team.
            getattr(self.r, 'report_progress', lambda message: None)('活动首领 · 返回后重新核验来源队伍')
            ready, refreshed = self.formation.select(party)
            if not ready:
                raise EventUIError('专武核验后重新编队未通过，未开战')
            selection.update(refreshed)
            for prior in members:
                current = self.formation.observed.get(normalized(prior.name))
                if (current is None or not current.identity_verified or any(
                        getattr(current, key) != getattr(prior, key)
                        for key in ('level', 'rank', 'stars', 'skill_level'))):
                    raise EventUIError('重新编队时培养状态变化，未开战')
        confirmed = self.formation.inspect_current(full=False, expected_names=[m.name for m in party.members], verify_skills=False)
        if ([normalized(m.name) for m in confirmed] != selection.get('order')
                or not all(m.identity_verified for m in confirmed)):
            raise EventUIError('战前编队与核验队伍不一致，未开战')
        self.r.report.setdefault('source_trial_audits', []).append(dict(
            party=party.name, source=party.source, mode=mode, observed=[asdict(m) for m in members]))
        if any(not m.identity_verified or any(getattr(m, key) is None for key in
                ('level', 'rank', 'stars', 'skill_level', 'unique', 'unique2')) for m in members):
            raise EventUIError('本期作业队伍身份、培养或专武状态未确认，未开战')

    def quest_catalog(self):
        self.r.quests()
        for _ in range(6):
            self.ui.swipe((840, 180), (840, 440))
        catalog = {}
        previous = None
        for _ in range(12):
            s = self.ui.capture()
            rows = s.all(r"活动关卡[HN]-\d+", (580, 150, 850, 450))
            signature = tuple(normalized(row.text) for row in rows)
            for row in rows:
                catalog[normalized(row.text)] = quest_stars(s, row)
            if signature == previous:
                break
            previous = signature
            self.ui.swipe((840, 420), (840, 180))
        if not catalog:
            raise EventUIError("没有识别到新版活动关卡")
        return catalog

    def first_clear(self) -> None:
        from .event_first_clear import EventFirstClear
        EventFirstClear(self).run()

    def scenario_support(self):
        """Verify the game's saved fixed-support team, never assume own units."""
        from ..game_ui.avatar_assets import ensure_avatar_index
        from ..game_ui.avatars import face_crop
        index, _ = ensure_avatar_index(self.r.options.get('sources', {}).get('avatars'),
                                       check=self.r.check_deadline)
        s = self.ui.capture()
        support = s.find('支援', (540, 65, 625, 110), exact=True)
        if not s.find('队伍编组', (250, 0, 730, 70)) or not support:
            raise EventUIError('剧本模式支援标签未确认，未开战')
        self.ui.click(support)
        self.ui.wait(lambda frame: frame.find('不会消耗玛那', (600, 465, 945, 525)),
                     '剧本模式固定支援说明')
        orders = []
        for _ in range(2):
            s = self.ui.capture()
            if (not s.find('队伍编组', (250, 0, 730, 70))
                    or not s.find(r'首领战[（(]剧本模式[）)]', (600, 465, 945, 525))
                    or not s.find('不会消耗玛那', (600, 465, 945, 525))
                    or len(self.formation.occupied_slots(s)) != 5):
                raise EventUIError('剧本模式固定支援五人编队未确认，未开战')
            rects = [(pos[0]-48, self.formation.slot_top, 96, 96) for pos in self.formation.slots]
            names = index.query([face_crop(s.image, rect) for rect in rects])
            if any(not name or name.startswith('unit:') for name in names) or len(set(names)) != 5:
                raise EventUIError('剧本模式固定支援身份未确认，未开战')
            orders.append(names)
            self.ui.save('scenario_support_' + str(len(orders)), s)
            time.sleep(.5)
        if orders[0] != orders[1]:
            raise EventUIError('剧本模式固定支援多帧身份不一致')
        party = EventParty('游戏固定支援', '游戏内剧本模式固定支援',
                           [MemberRequirement(name, 1, 1, 1, None, None, True) for name in orders[0]],
                           max_attempts=1, build_basis='fixed_support')
        self.r.report['scenario_support'] = {'order': orders[0], 'basis': 'game_fixed_support', 'mana_cost': 0}
        return party, {'order': orders[0]}

    def bosses(self) -> None:
        title = self.r.home().text((0, 160, 940, 460))
        self.r.report["event"] = title
        source_area = None
        source_identity_checked = False
        unlock_attempts = 0
        for difficulty, label in (("scenario", "剧本模式"), ("special", "特别"), ("special_plus", "特别战斗\\+")):
            attempts = defaultdict(int)
            total = 0
            previous = None
            while total < self.r.options.get("max_boss_attempts", 10):
                getattr(self.r, 'check_deadline', lambda: None)()
                s = self.r.quests(bosses=True)
                unlock = s.find('解锁', (500, 390, 710, 465), exact=True)
                if unlock:
                    if unlock_attempts >= 2:
                        raise EventUIError('首领解锁后入口未变化，停止重复操作')
                    unlock_attempts += 1
                    self.ui.click(unlock)
                    dialog = self.ui.wait(lambda f: f.find('首领战解锁确认', (300, 100, 650, 185), exact=True), '首领解锁确认')
                    self.r.entry_dialog(dialog)
                    continue
                row = s.find(label, (740, 200, 930, 400), exact=True)
                if not row:
                    self.r.report["pending"].append(difficulty+" 入口未解锁/无法识别")
                    break
                if boss_cleared(s, row):
                    self.r.log(f"{row.text} 已通关，本轮跳过")
                    break
                if boss_locked(s, row):
                    self.r.report['pending'].append(difficulty+' 入口带锁，尚未解锁')
                    break
                if difficulty == 'scenario' and total:
                    self.r.report['pending'].append('剧本模式本次挑战未确认通关，停止重复开战')
                    break
                self.ui.click(row)
                detail = self.ui.wait(lambda s: s.find("BOSS详情", (0, 0, 730, 70)), "首领详情")
                if difficulty == "special_plus":
                    remaining = detail.find(r"\d+/\d+", (800, 385, 940, 450))
                    if remaining is None:
                        raise EventUIError("特别战斗＋剩余挑战次数无法确认")
                    if int(normalized(remaining.text).split("/")[0]) == 0:
                        self.r.report["pending"].append("特别战斗＋本轮次数用尽；未重置进度")
                        self.r.home()
                        break
                mode = boss_mode(detail)
                if difficulty == "scenario":
                    if not detail.find('固定支援角色'):
                        raise EventUIError('剧本模式未显示固定支援角色，不能沿用当前队伍开战')
                    mode = mode or 1
                    party = None
                else:
                    if mode is None:
                        raise EventUIError("未能确认特别战斗当前模式")
                    if not source_identity_checked:
                        source_identity_checked = True
                        try:
                            from ..news import fetch_event_news
                            current = fetch_event_news().hatsune
                            if current and normalized(current.name) in normalized(title):
                                source_area = current.name
                        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                            self.r.report.setdefault('source_errors', []).append('活动名称核验失败：'+str(error)[:160])
                    if source_area is None:
                        try:
                            source_area = self.r.event_identity()
                        except EventUIError as error:
                            self.r.report['pending'].append(str(error))
                        # Identity navigation leaves the boss detail. Reopen
                        # and re-read its state before searching or spending.
                        self.r.home()
                        if source_area is None:
                            break
                        continue
                    key = (source_area, difficulty, mode)
                    if key not in self.source_pools:
                        self.r.report_progress(f'活动首领 · 搜索{source_area} {difficulty} 模式{mode}作业')
                        found, search = boss_parties(self.r.options, kind='event', area=source_area,
                            difficulty=difficulty, mode=mode,
                            default_path='cache/game/strategies/event_teams.yml',
                            check=self.r.check_deadline)
                        self.source_pools[key] = found
                        if search:
                            self.r.report.setdefault('source_searches', []).append(search)
                            if search.get('avatar_assets'):
                                from ..game_ui.avatar_assets import ensure_avatar_index
                                self.formation.avatars, _ = ensure_avatar_index(
                                    self.r.options.get('sources', {}).get('avatars'), check=self.r.check_deadline)
                    party = next_boss_party(self.source_pools[key], attempts, mode)
                    if party is None:
                        self.r.report["pending"].append(f"{difficulty} 模式{mode} 无可用达标队伍；见来源与编队核验报告")
                        self.r.home()
                        break
                state = normalized(detail.text((40, 65, 930, 440)))
                if previous == (mode, party.name if party else None, state) and total > 0 and party:
                    attempts[(mode, party.name)] = party.max_attempts
                    previous = None
                    self.r.home()
                    continue
                self.ui.expect_click("挑战", (740, 430, 945, 515), exact=True)
                self.ui.wait(lambda s: s.find("队伍编组", (250, 0, 730, 70)), "首领编队")
                selection = {}
                if difficulty == 'scenario':
                    party, selection = self.scenario_support()
                elif party:
                    ready, selection = self.formation.select(party)
                    if not ready:
                        attempts[(mode, party.name)] = party.max_attempts
                        self.r.report["battles"].append({"boss": difficulty, "mode": mode, "party": party.name,
                            "build_basis": party.build_basis, "assumptions": party.assumptions, "unready": selection})
                        self.r.home()
                        continue
                    if party.build_basis == 'local_trial' and self.r.options.get('require_source_settings', False):
                        self.audit_source_trial(party, selection, label, mode)
                    attempts[(mode, party.name)] += 1
                self.r.report_progress(f'活动首领 · {difficulty} 模式{mode}战斗与结算')
                result = self.combat.run(party, selection.get("order"))
                total += 1
                self.r.report["battles"].append({"boss": difficulty, "mode": mode,
                    "party": party.name if party else "当前队伍/固定支援", "source": party.source if party else "游戏固定支援",
                    "build_basis": party.build_basis if party else 'fixed_support',
                    "assumptions": party.assumptions if party else [],
                    **vars(result)})
                if result.outcome in ("retreated", "failed", "blocked") and party:
                    attempts[(mode, party.name)] = party.max_attempts
                previous = (mode, party.name if party else None, state) if result.outcome == "settled" else None
                self.r.home()
            else:
                final = self.r.quests(bosses=True)
                row = final.find(label, (740, 200, 930, 400), exact=True)
                if row and boss_cleared(final, row):
                    self.r.log(f"{row.text} 已确认通关")
                else:
                    self.r.report["pending"].append(difficulty+" 达到总尝试次数上限")
        self.r.home()
