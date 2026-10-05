"""Read owned six-star training without opening a spending preview."""
from __future__ import annotations

import re
import cv2 as cv
import numpy as np

from .screen import normalized
from ..character_data import character


SKILL_GROUPS = (('union_burst', 'union_burst_evolution'),
                ('main_skill_1', 'main_skill_evolution_1'),
                ('main_skill_2', 'main_skill_evolution_2'),
                ('ex_skill_1', 'ex_skill_evolution_1'))


def owned_six_stars(screen):
    """The owned memory page has five gold stars and a pink sixth star.

    The five-star layout has different centers; neither an unlocked blue
    star nor an unrecognized layout proves an active six-star character.
    """
    hsv = cv.cvtColor(screen.image, cv.COLOR_BGR2HSV)
    for index, x in enumerate((152, 190, 228, 266, 304, 342)):
        patch = hsv[318:350, x-10:x+10]
        hue = patch[:, :, 0]
        color = ((hue > 140) & (hue < 175) if index == 5 else (hue > 12) & (hue < 38))
        if np.mean(color & (patch[:, :, 1] > 90) & (patch[:, :, 2] > 160)) <= .3:
            return None
    return 6


def training_skill_levels(screen, definitions):
    """Require all four current skill titles and their unambiguous Lv rows.

    Numeric upgrade costs, level caps and previews cannot stand in for a
    current level. Missing, weak or conflicting rows keep the audit unknown.
    """
    panel = [item for item in screen.items
             if 470 <= item.center[0] <= 925 and 105 <= item.center[1] <= 445]
    result = {}
    used = set()
    for keys in SKILL_GROUPS:
        titles = {normalized(definitions[key]) for key in keys if definitions.get(key)}
        if not titles:
            return None
        matches = [item for item in panel if normalized(item.text) in titles]
        if len(matches) != 1 or matches[0].score < .95:
            return None
        title = matches[0]
        levels = [item for item in panel if abs(item.center[1]-title.center[1]) <= 25
                  and item.center[0] > title.center[0]
                  and re.fullmatch(r'Lv[.]?\d+', normalized(item.text), re.I)]
        if len(levels) != 1 or levels[0].score < .95 or id(levels[0]) in used:
            return None
        level = int(re.search(r'\d+', normalized(levels[0].text))[0])
        if level < 1:
            return None
        used.add(id(levels[0]))
        result[keys[0]] = level
    return result


def inspect_owned_training(ui, name, memory_screen, *, check=lambda: None):
    """Continue an exact-costume memory audit on the visible skill tab."""
    check()
    evidence = [str(ui.save('owned_stars_'+normalized(name), memory_screen))]
    stars = owned_six_stars(memory_screen)
    result = dict(stars=stars, skill_level=None, training_evidence=evidence)
    if stars != 6:
        return result
    definitions = (character(name) or {}).get('training_skills', {})
    if any(not any(definitions.get(key) for key in keys) for keys in SKILL_GROUPS):
        return result
    ui.expect_click('技能强化', (615, 55, 700, 95), exact=True)
    screen = ui.wait(lambda s: s.find('角色强化', (40, 0, 250, 65), exact=True)
                     and s.find('技能强化', (615, 55, 700, 95), exact=True)
                     and any(normalized(item.text) in set(definitions.values())
                             for item in s.all('.+', (470, 105, 925, 445))), '自持角色技能等级')
    check()
    evidence.append(str(ui.save('owned_skills_'+normalized(name), screen)))
    levels = training_skill_levels(screen, definitions)
    if levels is not None:
        result.update(skill_level=min(levels.values()), skill_levels=levels)
    return result
