"""Verify partners and assemble teams for the difficulty-one exploration."""
from dataclasses import asdict, dataclass

import cv2 as cv
import numpy as np

from .event_formation import EventFormation
from .event_strategy import EventParty, MemberRequirement, readiness
from .party_variants import character_roles
from ..game_ui.avatar_assets import ensure_avatar_index
from ..game_ui.avatars import card_rectangles, search_card_rectangles, face_crop
from ..game_ui.screen import EventUIError, normalized


@dataclass(frozen=True)
class LabyrinthBossStrategy:
    server: str
    guild: str
    difficulty: int
    boss: str
    level: int
    maximum_hp: int
    parties: tuple[EventParty, ...]
    evidence: str
    verified: bool = False


class LabyrinthFormation(EventFormation):
    requires_declared_build = False
    infer_costume_from_skills = True
    detail_close_pattern = '确认|关闭'
    formation_title_pattern = '角色选择|队伍编组'

    @staticmethod
    def require_equipment(status):
        # Rank does not prove its six ordinary items are equipped. Never turn
        # a missing badge observation or unspecified build into an allowed one.
        if (type(status.equipment) is not int or status.equipment != 6
                or type(status.unique) is not bool or type(status.unique2) is not bool
                or not status.equipment_evidence
                or (status.unique2 and not status.unique)):
            raise EventUIError(status.name+'的完整装备与专武状态尚未核验，未邀请或开战')

    @staticmethod
    def require_build(status, enemy_level=0):
        LabyrinthFormation.require_equipment(status)
        if (not status.identity_verified or status.level is None or status.level < 365 or enemy_level > 380
                or status.rank is None or status.rank < 38 or status.stars != 6
                or status.skill_level is None or status.skill_level < 365):
            raise EventUIError(f'{status.name}未满足难度1试打的培养要求（等级与技能365、Rank38、六星，普通敌人最高380级）')

    def clear_current(self):
        for _ in range(6):
            screen = self.ui.capture()
            if not screen.find('队伍编组', (300, 0, 650, 70), exact=True):
                raise EventUIError('不在迷宫编队页')
            occupied = self.occupied_slots(screen)
            if not occupied:
                break
            self.ui.click(occupied[-1])
        else:
            raise EventUIError('迷宫当前编队未能清空')
        return screen

    def select_standard(self, enemy_level):
        return self.select_members(('佩可莉姆', '可可萝', '凯露'), enemy_level)

    @staticmethod
    def require_boss_build(status):
        LabyrinthFormation.require_equipment(status)
        if (not status.identity_verified or status.level is None or status.level < 350
                or status.rank is None or status.rank < 38 or status.stars is None or status.stars < 3
                or status.skill_level is None or status.skill_level < 350):
            raise EventUIError(status.name+'未满足首领试打的培养要求（等级与技能350、Rank38、至少三星）')

    @staticmethod
    def visible_cards(screen):
        found = card_rectangles(screen.image)
        rows = sorted({r[1] for r in found})
        if not rows:
            return found
        rows = sorted(set(rows+[rows[0]-110, rows[-1]+110]))
        # Selection badges can interrupt the border. Use neighboring card
        # rows to fill occupied grid cells, then verify their actual avatars.
        for y in rows:
            if not 115 <= y <= 300:
                continue
            for rect in search_card_rectangles(screen.image, top=y):
                if not any(abs(rect[0]-r[0]) < 5 and abs(rect[1]-r[1]) < 5 for r in found):
                    found.append(rect)
        return sorted(found, key=lambda r: (r[1], r[0]))

    def select_members(self, names, enemy_level, boss=False):
        members = tuple(names)
        self.clear_current()
        party = []
        for name in members:
            screen = self.ui.capture()
            rectangles = self.visible_cards(screen)
            identities = self.avatars.query([face_crop(screen.image, r) for r in rectangles])
            rectangle = next((r for r, n in zip(rectangles, identities) if n == name), None)
            if rectangle is None and boss:
                self.scroll_to_start()
                rectangle = self.find_member(name)
            if rectangle is None:
                raise EventUIError('迷宫编队未确认伙伴身份：'+name)
            x, y, w, h = rectangle
            status = self.inspect((x+w//2, y+h//2), rectangle=rectangle,
                                  expected_name=name, verify_skills=name not in self.observed)
            if boss:
                self.require_boss_build(status)
            else:
                self.require_build(status, enemy_level)
            self.ui.click((x+w//2, y+h//2))
            party.append(asdict(status))
        screen = self.ui.capture()
        if len(self.occupied_slots(screen)) != len(members):
            raise EventUIError('迷宫编队人数无法核对')
        return party, screen

    def scroll_to_start(self):
        # Match the bounded six-page search so a member near the beginning is
        # still reachable after inspecting the end of a larger roster.
        for _ in range(6):
            self.ui.swipe((880, 205), (880, 350))
            screen = self.ui.capture()
            if not screen.find('队伍编组', (300, 0, 650, 70), exact=True):
                raise EventUIError('伙伴列表滑动后页面无法核对，未继续编组')

    def audit_boss_roster(self):
        """Discover and inspect available partners in the program, including cold runs."""
        candidates = {}
        self.scroll_to_start()
        for _ in range(6):
            screen = self.ui.capture()
            rectangles = self.visible_cards(screen)
            if not rectangles:
                raise EventUIError('首领伙伴列表无法确认')
            identities = self.avatars.query([face_crop(screen.image, r) for r in rectangles])
            unseen = [(r, n) for r, n in zip(rectangles, identities) if n and n not in candidates]
            if not unseen:
                break
            for rectangle, name in unseen:
                x, y, w, h = rectangle
                status = self.inspect((x+w//2, y+h//2), rectangle=rectangle,
                                      expected_name=name, verify_skills=True)
                candidates[name] = status
            self.ui.swipe((880, 340), (880, 205))
        self.scroll_to_start()
        roles = character_roles()
        ready = {}
        for name, status in candidates.items():
            try:
                self.require_boss_build(status)
            except EventUIError:
                continue
            if name in roles and roles[name].get('role') in range(1, 9):
                ready[name] = status
        return ready, roles

    @staticmethod
    def plan_boss_parties(ready, roles, *, strategy=None):
        """Use exact source parties; generic roles cannot authorize a battle.

        Automatic acquisition of a validated labyrinth strategy is pending.
        Production callers therefore stop here until that source is available.
        """
        if (not isinstance(strategy, LabyrinthBossStrategy) or strategy.verified is not True
                or not isinstance(strategy.evidence, str) or not strategy.evidence.strip()
                or (strategy.server, strategy.guild, strategy.difficulty, strategy.boss,
                    strategy.level, strategy.maximum_hp)
                != ('cn', '美食殿堂', 1, '暗黑滴水嘴兽', 350, 60000000)
                or type(strategy.difficulty) is not int or not isinstance(strategy.parties, tuple)
                or not 2 <= len(strategy.parties) <= 3):
            raise EventUIError('首领配队策略来源与适用条件尚未核验，已保留保存队伍，未开战')
        core = ('佩可莉姆', '可可萝', '凯露')
        groups, occupied = [], set()
        for party in strategy.parties:
            if (not isinstance(party, EventParty) or party.auto is not True
                    or party.build_basis != 'source' or party.assumptions != []
                    or not isinstance(party.source, str) or not party.source.strip()
                    or not isinstance(party.modes, (list, tuple))
                    or any(type(mode) is not int or mode not in (1, 2, 3) for mode in party.modes)
                    or 1 not in party.modes or not isinstance(party.members, list)
                    or len(party.members) != 5):
                raise EventUIError('首领攻略的自动操作或完整成员要求尚未核验，未开战')
            names = []
            for requirement in party.members:
                if (not isinstance(requirement, MemberRequirement)
                        or not isinstance(requirement.name, str) or not requirement.name.strip()
                        or any(type(getattr(requirement, key)) is not int or getattr(requirement, key) <= 0
                               for key in ('level', 'rank', 'stars', 'skill_level'))
                        or requirement.equipment != 6 or type(requirement.unique) is not bool
                        or type(requirement.unique2) is not bool or requirement.instant is not True):
                    raise EventUIError('首领攻略的培养、装备或操作要求尚未明确，未开战')
                name = normalized(requirement.name)
                if name in occupied or name not in ready:
                    raise EventUIError('首领攻略伙伴缺失或跨队重复，未开战')
                status = ready[name]
                LabyrinthFormation.require_boss_build(status)
                reasons = readiness(requirement, status)
                if reasons:
                    raise EventUIError(name+'未满足首领攻略要求：'+'；'.join(reasons))
                occupied.add(name)
                names.append(name)
            groups.append(names)
        if not set(core).issubset(groups[0]):
            raise EventUIError('首领攻略不支持当前核心伙伴，未开战')
        for name in core:
            LabyrinthFormation.require_build(ready[name])
        return groups+[[]]*(3-len(groups))

    def find_member(self, name):
        for _ in range(6):
            screen = self.ui.capture()
            rectangles = self.visible_cards(screen)
            identities = self.avatars.query([face_crop(screen.image, r) for r in rectangles])
            rectangle = next((r for r, n in zip(rectangles, identities) if n == name), None)
            if rectangle:
                return rectangle
            self.ui.swipe((880, 340), (880, 205))
        raise EventUIError('首领编队未找到已核对伙伴：'+name)

    def prepare_assets(self, check):
        self.avatars, assets = ensure_avatar_index(check=check)
        return {key: assets.get(key) for key in ('cache_hit', 'complete', 'stale')}

    def choose_reward(self, screen):
        # This is a free partner reward. It does not change the verified battle
        # team; a new partner is never silently added to a combat strategy.
        def ready(value):
            buttons = value.all('^选择$', (90, 400, 875, 510))
            return bool(len(buttons) == 3
                        and max(b.center[1] for b in buttons)-min(b.center[1] for b in buttons) <= 6)
        if not ready(screen):
            screen = self.ui.wait(ready, '伙伴奖励卡片入场', timeout=10)
        if not screen.find('还剩[1-3]次', (400, 105, 560, 145), exact=True):
            raise EventUIError('伙伴奖励的邀请次数无法核对')
        for x, center in ((143, 202), (422, 480), (701, 759)):
            labels = sorted(screen.all('.+', (center-105, 315, center+105, 392)), key=lambda item: item.center[1])
            if not labels or any(item.score < .95 for item in labels):
                continue
            displayed = normalized(''.join(item.text for item in labels))
            identity = self.avatars.query([face_crop(screen.image, (x, 183, 117, 117))])[0]
            if identity != displayed:
                continue
            choose = screen.find('选择', (center-80, 400, center+80, 480), exact=True)
            if screen.blue_button(choose):
                self.ui.click(choose)
                return displayed
        raise EventUIError('未核对伙伴奖励的完整身份，未选择')

    @staticmethod
    def invitation_cards(screen):
        found = card_rectangles(screen.image)
        rows = sorted({r[1] for r in found})
        # White hair/background can interrupt a card outline. Anchor each
        # visible row to its detected cards, then validate occupied grid slots.
        return [r for y in rows for r in search_card_rectangles(screen.image, top=y)]

    def choose_initial(self, screen):
        # A bounded beginner route uses the standard guild tank, healer and
        # area attacker. Costumes are separate identities. Lower builds must
        # obtain a verified strategy rather than enter this trial blindly.
        wanted = ('佩可莉姆', '可可萝', '凯露')
        if not screen.find('角色选择', (300, 0, 650, 70), exact=True):
            raise EventUIError('不在迷宫伙伴选择页')
        count = screen.find('[0-3]/3', (860, 60, 935, 95), exact=True)
        if not count:
            raise EventUIError('初始伙伴选择数量无法核对')
        if normalized(count.text) != '0/3':
            selected = []
            for r in self.invitation_cards(screen):
                x, y, w, h = r
                patch = cv.cvtColor(screen.image[y+5:y+37, x+w-32:x+w-8], cv.COLOR_BGR2HSV)
                white = float(np.mean((patch[:, :, 1] < 45) & (patch[:, :, 2] > 220)))
                value = self.ui.number(screen, (x+w-32, y+5, x+w-8, y+37)) if white > .7 else None
                if value in (1, 2, 3):
                    selected.append((x+w//2, y+h//2))
            if len(selected) != int(normalized(count.text)[0]):
                raise EventUIError('未核对的初始伙伴选择无法安全清空')
            for pos in selected:
                self.ui.click(pos)
            screen = self.ui.capture()
            if not screen.find('0/3', (860, 60, 935, 95), exact=True):
                raise EventUIError('未核对的初始伙伴选择未清空')
        chosen = []
        for name in wanted:
            screen = self.ui.capture()
            rectangles = self.invitation_cards(screen)
            identities = self.avatars.query([face_crop(screen.image, r) for r in rectangles])
            candidates = [(r, identity) for r, identity in zip(rectangles, identities)
                          if identity == name or (identity is None
                          and normalized(screen.text((r[0], r[1]-2, r[0]+r[2], r[1]+25))) == name)]
            candidates.sort(key=lambda pair: pair[1] != name)
            found = None
            for rect, identity in candidates:
                x, y, w, h = rect
                status = self.inspect((x+w//2, y+h//2), rectangle=rect,
                                      expected_name=name if identity else None,
                                      verify_skills=True)
                if status.identity_verified and normalized(status.name) == name:
                    found = status
                    self.require_build(status)
                    self.ui.click((x+w//2, y+h//2))
                    break
            if found is None:
                raise EventUIError('未确认初始伙伴身份：'+name)
            chosen.append(asdict(found))
        screen = self.ui.capture()
        if not screen.find('3/3', (860, 60, 935, 95), exact=True):
            raise EventUIError('初始伙伴选择数量无法核对')
        button = screen.find('去邀请', (715, 440, 930, 520), exact=True)
        if not screen.blue_button(button):
            raise EventUIError('迷宫伙伴邀请按钮未启用')
        self.ui.click(button)
        return chosen
