"""Read party members in the real game and reject unverified builds."""
from __future__ import annotations
from typing import Sequence
from .base import Screenshot, Point, Region, TaskReport
from .event_strategy import EventParty
from ..game_ui.screen import EventUI, EventScreen
from dataclasses import asdict
import json
import re
from uuid import uuid4
from pcrscript.run_session import clock as time

import cv2 as cv
import numpy as np

from .event_strategy import CharacterStatus, skill_names, readiness
from ..game_ui.screen import EventUIError, normalized
from ..game_ui.avatars import AvatarIndex, card_rectangles, search_card_rectangles, face_crop
from ..game_ui.equipment import EquipmentBadges


def count_stars(image: Screenshot) -> int | None:
    hsv = cv.cvtColor(image[103:129, 589:705], cv.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 0] >= 12) & (hsv[:, :, 0] <= 40) | (hsv[:, :, 0] >= 140)) & (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 120)
    # Adjacent star outlines touch; connected-components merge them. Sample
    # each of the six fixed slots, including the pink sixth-star variant.
    stars = sum(float(np.mean(mask[2:23, x-6:x+7])) > .18 for x in (10, 28, 46, 64, 82, 100))
    return stars if 1 <= stars <= 6 else None


def skill_title_pattern(title: str) -> str:
    # Musical decoration is sometimes omitted by OCR. Keep every actual word
    # and the evolution '+' exact; only the decorative note is optional.
    return re.escape(normalized(title)).replace('♪', '[♪♫]?')


class EventFormation:
    requires_declared_build = True
    infer_costume_from_skills = False
    slots = [(96+109*i, 452) for i in range(5)]
    slot_top = 405
    search_top = 177
    defocus = (190, 390)

    def occupied_slots(self, screen: EventScreen) -> list[Point]:
        top = self.slot_top
        return [pos for pos in self.slots if float(np.mean(cv.cvtColor(
            screen.image[top+10:top+89, pos[0]-38:pos[0]+38], cv.COLOR_BGR2HSV)[:, :, 1] > 70)) > .15]

    def search_rectangles(self, image: Screenshot) -> list[Region]:
        return search_card_rectangles(image, top=self.search_top)

    @staticmethod
    def search_identity_candidate(screen, rectangle, identity, wanted):
        if identity is None or identity == wanted:
            return True
        x, y, w, _ = rectangle
        # A stale or mistaken avatar match must not hide a card whose own
        # visible name is exact. inspect() still verifies its skills before
        # the character can join the party.
        return normalized(screen.text((x, y-4, x+w, y+26))) == wanted

    def resolve_requirement(self, requirement, actual):
        return requirement

    def member_readiness(self, requirement, actual):
        return readiness(self.resolve_requirement(requirement, actual), actual)

    def __init__(self, ui: EventUI) -> None:
        self.ui = ui
        self.observed = {}
        self.avatars = AvatarIndex()
        self.badges = EquipmentBadges()

    def inspect(self, pos: Point, full: bool = True, rectangle: Region | None = None, expected_name: str | None = None,
                verify_skills: bool = True) -> CharacterStatus:
        evidence_suffix = '_'+uuid4().hex[:8] if self.infer_costume_from_skills else ''
        before = self.ui.capture(ocr=False)
        rect = rectangle or next((r for r in card_rectangles(before.image)
                     if r[0] <= pos[0] <= r[0]+r[2] and r[1] <= pos[1] <= r[1]+r[3]), None)
        face = face_crop(before.image, rect).copy() if rect else None
        identity = self.avatars.query([face])[0] if face is not None else None
        equipment, evidence = self.badges.observe(self.ui, rect) if full and rect else (None, None)
        self.ui.swipe(pos, pos, 900)
        s = self.ui.wait(lambda s: s.find("角色详情", (300, 0, 650, 70)), "角色详情")
        if s.find('检测到手柄'):
            # Android's connection toast can temporarily cover the name and
            # level. Wait for this observed overlay; never infer hidden text.
            s = self.ui.wait(lambda frame: not frame.find('检测到手柄'), '手柄连接提示消失', timeout=8)
        names = s.all(".+", (488, 65, 750, 97))
        expected_base = normalized(expected_name or identity or '').split('(')[0]
        detected_base = normalized(''.join(i.text for i in names)).split('(')[0]
        if not names or (expected_base and detected_base != expected_base):
            # The full-frame detector can misread short names beside the blue
            # ornament. Retry the known name field at 3x; still require skills
            # to establish the costume instead of trusting the requested name.
            local = self.ui.read_region(s, (490, 65, 750, 97))
            local_names = local.all('.+', (488, 65, 750, 97))
            if local_names:
                names = local_names
        if not names:
            raise EventUIError("角色全名无法识别")
        displayed = normalized("".join(i.text for i in names))
        # Verified glyph confusion in the name field (2026-09-22). This only
        # repairs the base name; the two skill names still prove the costume.
        if displayed.split('(')[0] == '干爱瑠':
            displayed = '千爱瑠' + displayed[len('干爱瑠'):]
        if displayed.split('(')[0] == '干歌':
            displayed = '千歌' + displayed[len('干歌'):]
        candidate = normalized(expected_name or identity or displayed)
        same_base = candidate.split("(")[0] == displayed.split("(")[0]
        name = candidate if same_base else displayed
        prior = self.observed.get(normalized(name))
        reusable_skill = (prior is not None and prior.identity_verified and prior.skill_level is not None
                          and prior.observed_at is not None and 0 <= time.time()-prior.observed_at < 3600)
        actual = CharacterStatus(name=name, level=s.number((535, 100, 585, 130)),
                                 rank=s.number((775, 100, 810, 130)), stars=count_stars(s.image))
        actual.identity_verified = bool(identity == name and same_base)
        actual.observed_at = time.time()
        if full and evidence is not None:
            actual.equipment_evidence = str(self.ui.save("equipment_"+name+evidence_suffix, evidence))
        if equipment is not None:
            actual.unique, actual.unique2 = equipment
        actual.evidence = str(self.ui.save("character_"+normalized(name)+evidence_suffix, s))
        if full and (verify_skills or not actual.identity_verified
                     or (not reusable_skill and not self.infer_costume_from_skills)):
            self.ui.click(s.find("技能", (620, 132, 770, 170), exact=True))
            candidates = None
            if self.infer_costume_from_skills and expected_name is None:
                from .event_strategy import costume_skills
                candidates = costume_skills(displayed)
            wanted = skill_names(name)
            search_skills = {value for skills in candidates.values() for value in skills.values()} if candidates else set(wanted.values())
            found_names = set()
            levels = {}
            previous = None
            for page in range(8):
                s = self.ui.capture()
                self.ui.save(f"skills_{normalized(name)}{evidence_suffix}_{page}", s)
                text = normalized(s.text((485, 175, 900, 438)))
                for value in search_skills:
                    if s.find(skill_title_pattern(value), (580, 175, 800, 438), exact=True):
                        found_names.add(value)
                for label in s.all("等级", (790, 180, 840, 435)):
                    y = label.center[1]
                    value = s.number((842, y-14, 897, y+14))
                    skill = normalized(s.text((570, y-18, 785, y+18)))
                    if value is not None and skill:
                        levels[skill] = value
                if text == previous:
                    break
                previous = text
                self.ui.swipe((820, 401), (820, 210))
            actual.skill_level = min(levels.values()) if len(levels) >= 3 else None
            # The UI omits costume suffixes. The two ordinary skill names
            # independently establish the variant, even if OCR only says 怜.
            if candidates:
                matches = [candidate for candidate, skills in candidates.items() if all(
                    any(skills.get(key) in found_names for key in (f'main_skill_{i}', f'main_skill_evolution_{i}'))
                    for i in (1, 2))]
                if len(matches) == 1:
                    name = actual.name = matches[0]
                    wanted = candidates[name]
                    same_base = True
                else:
                    same_base = False
            skill_identity = all(any(wanted.get(key) in found_names for key in
                                 (f"main_skill_{i}", f"main_skill_evolution_{i}")) for i in (1, 2))
            actual.identity_verified = bool(same_base and skill_identity)
            if actual.identity_verified and face is not None:
                self.avatars.add(normalized(name), face)
        elif full and reusable_skill:
            actual.skill_level = prior.skill_level
        if full:
            self.observed[normalized(name)] = actual
            (self.ui.output / "roster.json").write_text(json.dumps(
                {k: asdict(v) for k, v in self.observed.items()}, ensure_ascii=False, indent=2), encoding="utf-8")
        self.ui.expect_click("确认", (320, 450, 650, 515), exact=True)
        close_attempts = 0
        def close_remaining_dialog(screen):
            nonlocal close_attempts
            if close_attempts >= 3 or not screen.find('角色详情', (300, 0, 650, 70), exact=True):
                return
            button = screen.find('确认', (320, 450, 650, 515), exact=True)
            if button:
                close_attempts += 1
                self.ui.click(button)
        self.ui.wait(lambda s: s.find("队伍编组", (300, 0, 650, 70)), "返回编队",
                     handle=close_remaining_dialog)
        return actual

    def inspect_current(self, full: bool = True, expected_names: Sequence[str] = (), *, verify_skills: bool = True) -> list[CharacterStatus]:
        results = []
        for pos in self.slots:
            rect = (pos[0]-48, self.slot_top, 96, 96)
            actual = self.inspect(pos, full=full, rectangle=rect, verify_skills=verify_skills)
            if not actual.identity_verified:
                for name in expected_names:
                    if normalized(name).split("(")[0] == normalized(actual.name).split("(")[0]:
                        candidate = self.inspect(pos, rectangle=rect, expected_name=name)
                        if candidate.identity_verified:
                            actual = candidate
                            break
            results.append(actual)
        return results

    def select(self, party: EventParty) -> tuple[bool, TaskReport]:
        """Use the game's hidden search bar, then one batch avatar query."""
        unspecified = [{"character": member.name, "reasons": ["攻略尚未明确专武开启状态"]}
                       for member in party.members if self.requires_declared_build
                       and (member.unique is None or member.unique2 is None)]
        if unspecified:
            return False, {"unready": unspecified}
        self.ui.wait(lambda s: s.find("队伍编组", (300, 0, 650, 70)), "队伍编组")
        self.ui.expect_click("全部", (30, 65, 115, 108), exact=True)
        for _ in range(10):
            s = self.ui.capture()
            search = s.find("用角色名搜索|角色名", (300, 105, 645, 165)) or s.find("重置", (640, 105, 755, 165), exact=True)
            if search:
                break
            self.ui.swipe((480, 170), (480, 350))
        else:
            return self._select_by_scrolling(party)
        for _ in range(10):
            s = self.ui.capture(ocr=False)
            occupied = self.occupied_slots(s)
            if not occupied:
                break
            self.ui.click(occupied[-1], delay=.3)
        else:
            raise EventUIError("当前队伍未能清空")
        failures = []
        for member in party.members:
            print(f"[剧情活动] 搜索并核对 {member.name}", flush=True)
            base = normalized(member.name).split('(')[0]
            for _ in range(3):
                self.ui.click((691, 135))  # Reset only the text-search field.
                self.ui.click((480, 136), delay=.3)
                self.ui.driver.input(base)
                time.sleep(1)  # ldconsole queues input asynchronously.
                self.ui.click(self.defocus, delay=1)
                s = self.ui.capture()
                if not s.find('队伍编组', (300, 0, 650, 70)):
                    raise EventUIError('角色搜索后未处于编队页面')
                entered = normalized(s.text((300, 110, 640, 165))).replace('干爱瑠', '千爱瑠')
                if base in entered:
                    break
            else:
                self.ui.save('search_input_unconfirmed', s)
                raise EventUIError('搜索词未确认写入，不能判断缺少角色：'+member.name)
            self.ui.save("search_"+normalized(member.name), s)
            if not s.find("队伍编组", (300, 0, 650, 70)):
                raise EventUIError("角色搜索后未处于编队页面")
            rects = self.search_rectangles(s.image)
            identities = self.avatars.query([face_crop(s.image, rect) for rect in rects])
            wanted = normalized(member.name)
            ranked = sorted(zip(rects, identities), key=lambda pair: pair[1] != wanted)
            found = False
            for rect, identity in ranked:
                if not self.search_identity_candidate(s, rect, identity, wanted):
                    continue
                x, y, w, h = rect
                pos = (x+w//2, y+h//2)
                # A matching public avatar already proves the full costume.
                # Unknown or ambiguous matches still enter the skill page.
                actual = self.inspect(pos, rectangle=rect, expected_name=member.name,
                                      verify_skills=False)
                if not actual.identity_verified or normalized(actual.name) != wanted:
                    continue
                found = True
                reasons = self.member_readiness(member, actual)
                if reasons:
                    failures.append({"character": member.name, "reasons": reasons})
                else:
                    self.ui.click(pos)
                break
            if not found:
                failures.append({"character": member.name, "reasons": ["未在搜索结果中确认该版本的角色"]})
        self.ui.click((691, 135))
        if failures:
            return False, {"unready": failures}
        actual_party = self.inspect_current(full=False, expected_names=[m.name for m in party.members])
        order = [normalized(a.name) for a in actual_party]
        if set(order) != {normalized(m.name) for m in party.members} or not all(a.identity_verified for a in actual_party):
            return False, {"errors": ["最终编队与作业不一致"], "order": order}
        return True, {"order": order}

    def _select_by_scrolling(self, party: EventParty) -> tuple[bool, TaskReport]:
        """Scan actual owned cards; inspect the full name to disambiguate variants.

        No avatar downloads, OCR guesses, upgrades, or automatic resource use.
        The selected party is verified again before starting a battle.
        """
        self.ui.wait(lambda s: s.find("队伍编组", (300, 0, 650, 70)), "队伍编组")
        # Empty only visibly occupied slots, starting from the right.
        for _ in range(10):
            s = self.ui.capture()
            occupied = self.occupied_slots(s)
            if not occupied:
                break
            self.ui.click(occupied[-1], delay=.3)
        else:
            raise EventUIError("当前队伍未能清空")
        self.ui.expect_click("全部", (30, 65, 115, 108), exact=True)
        for _ in range(10):
            self.ui.swipe((670, 145), (670, 353))
        pending = {normalized(m.name): m for m in party.members}
        scanned = set()
        previous = None
        failures = []
        for page in range(90):
            s = self.ui.capture(ocr=False)
            rectangles = card_rectangles(s.image)
            # Once the target avatars are indexed (JP assets or verified local
            # samples), scrolling needs no full-frame OCR at all.
            if any(name not in self.avatars.names for name in pending) or not rectangles:
                s = self.ui.capture()
            if page % 10 == 0:
                print(f"[剧情活动] 扫描角色第 {page+1} 页，待查：{', '.join(pending)}", flush=True)
            signature = cv.resize(s.image[115:372, 40:905], (24, 12)).tobytes()
            identities = self.avatars.query([face_crop(s.image, r) for r in rectangles])
            candidates = []
            for rect, identity in zip(rectangles, identities):
                if identity in pending:
                    x, y, w, h = rect
                    candidates.append((x+w//2, y+h//2))
            # Grid labels omit outfit names. Long press each matching base name.
            for item in s.all(".+", (45, 115, 900, 350)):
                short = normalized(item.text)
                if not any(name.startswith(short) and len(short) >= 1 for name in pending):
                    continue
                x, y = item.center
                column = max(0, min(7, round((x-86)/106)))
                pos = (108+106*column, y+39)
                if pos[1] > 350:
                    continue
                cached = next((identity for rect, identity in zip(rectangles, identities)
                               if rect[0] <= pos[0] <= rect[0]+rect[2] and rect[1] <= pos[1] <= rect[1]+rect[3]), None)
                if cached and cached not in pending:
                    continue
                if not any(abs(pos[0]-p[0]) < 15 and abs(pos[1]-p[1]) < 15 for p in candidates):
                    candidates.append(pos)
            for pos in candidates:
                x, y = pos
                column = round((x-108)/106)
                key = (signature, column, int(y//20))
                if key in scanned:
                    continue
                scanned.add(key)
                actual = self.inspect(pos, full=False)
                name = normalized(actual.name)
                if name not in pending:
                    continue
                actual = self.inspect(pos, full=True)
                reasons = readiness(pending[name], actual)
                if reasons:
                    failures.append({"character": actual.name, "reasons": reasons})
                    del pending[name]
                    continue
                self.ui.click(pos)
                del pending[name]
            if not pending or signature == previous:
                break
            previous = signature
            self.ui.swipe((660, 330), (660, 220))
        if pending or failures:
            return False, {"missing": list(pending), "unready": failures}
        actual_party = self.inspect_current()
        required = {normalized(m.name): m for m in party.members}
        errors = []
        for actual in actual_party:
            need = required.get(normalized(actual.name))
            errors.extend(readiness(need, actual) if need else [f"误选角色 {actual.name}"])
        if {normalized(a.name) for a in actual_party} != set(required):
            errors.append("编队角色不完整或重复")
        return not errors, {"errors": errors, "order": [a.name for a in actual_party]}
