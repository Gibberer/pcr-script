"""Explicit, source-backed event parties and conservative readiness checks."""
from dataclasses import dataclass, field
from pathlib import Path
import re
import sqlite3
import yaml

from ..game_ui.screen import normalized


@dataclass
class MemberRequirement:
    name: str
    level: int
    rank: int
    stars: int
    unique: bool | None = False
    unique2: bool | None = False
    instant: bool = True
    skill_level: int = 1
    equipment: int = 0


@dataclass
class CharacterStatus:
    name: str
    level: int | None = None
    rank: int | None = None
    stars: int | None = None
    unique: bool | None = None
    unique2: bool | None = None
    skill_level: int | None = None
    equipment: int | None = None
    evidence: str = ""
    identity_verified: bool = False
    equipment_evidence: str = ""
    observed_at: float | None = None


def readiness(requirement, actual):
    """Unknown is not equivalent to ready. Unique equipment has no level gate."""
    reasons = []
    if not actual.identity_verified:
        reasons.append("角色版本尚未由头像/技能确认")
    if normalized(requirement.name) != normalized(actual.name):
        reasons.append(f"角色不符：{actual.name} != {requirement.name}")
    for key, label in (("level", "等级"), ("rank", "装备Rank"), ("stars", "星级"),
                       ("skill_level", "技能等级"), ("equipment", "装备件数")):
        need, have = getattr(requirement, key), getattr(actual, key)
        if need and (have is None or have < need):
            reasons.append(f"{label} {have if have is not None else '未知'} / 需要 {need}")
    if actual.stars is not None and (actual.stars == 6) != (requirement.stars == 6):
        reasons.append("六星开启状态与攻略不一致")
    for key, label in (("unique", "专武1"), ("unique2", "专武2")):
        need, have = getattr(requirement, key), getattr(actual, key)
        if need is None:
            reasons.append(f"攻略未明确{label}开启状态，不能据此开战")
        elif have is None:
            reasons.append(f"{label}开启状态未知（攻略要求{'开启' if need else '未开启'}）")
        elif have is not need:
            reasons.append(f"{label}开启状态不符：攻略{'开启' if need else '未开启'}，实际{'开启' if have else '未开启'}")
    return reasons


@dataclass
class EventParty:
    name: str
    source: str
    members: list[MemberRequirement]
    modes: list[int] = field(default_factory=lambda: [1, 2, 3])
    max_attempts: int = 3
    allow_deaths: int = 0


def load_parties(path, event_title, difficulty, mode):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    matches = [v for v in data.get("events", []) if
               re.search(v["match"], normalized(event_title), re.IGNORECASE)]
    if len(matches) != 1:
        return []
    result = []
    for party in matches[0].get(difficulty, []):
        if mode not in party.get("modes", [1, 2, 3]):
            continue
        members = [MemberRequirement(**m) for m in party["members"]]
        if len(members) != 5 or len({normalized(m.name) for m in members}) != 5:
            raise ValueError(f"{party['name']} 必须包含五名不同角色")
        result.append(EventParty(**{**party, "members": members}))
    return result


def skill_names(name, database="cache/redive_cn.db"):
    """Map displayed skill names to base/evolved skills in the local game DB."""
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT unit_id,unit_name FROM unit_profile").fetchall()
        unit = next((r for r in rows if normalized(r["unit_name"]) == normalized(name)), None)
        if not unit:
            return {}
        skills = conn.execute("SELECT * FROM unit_skill_data WHERE unit_id=?", (unit["unit_id"],)).fetchone()
        if not skills:
            return {}
        result = {}
        for key in ("main_skill_1", "main_skill_evolution_1", "main_skill_2", "main_skill_evolution_2"):
            if key in skills.keys() and skills[key]:
                value = conn.execute("SELECT name FROM skill_data WHERE skill_id=?", (skills[key],)).fetchone()
                if value:
                    result[key] = normalized(value[0])
        return result
