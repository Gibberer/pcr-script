"""Explicit, source-backed event parties and conservative readiness checks."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import re
import yaml

from ..game_ui.screen import normalized


def team_key(names):
    return '|'.join(sorted(map(normalized, names)))


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
    exact_rank: bool = True
    exact_stars: bool = True
    unique_level: int | None = None
    unique2_stars: int | None = None


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
    unique_level: int | None = None
    unique2_stars: int | None = None


def readiness(requirement: MemberRequirement, actual: CharacterStatus) -> list[str]:
    """Check every declared threshold; unknown live equipment is never ready."""
    reasons = []
    if not actual.identity_verified:
        reasons.append("角色版本尚未由头像/技能确认")
    if normalized(requirement.name) != normalized(actual.name):
        reasons.append(f"角色不符：{actual.name} != {requirement.name}")
    for key, label in (("level", "等级"), ("rank", "装备Rank"), ("stars", "星级"),
                       ("skill_level", "技能等级"), ("equipment", "装备件数")):
        need, have = getattr(requirement, key), getattr(actual, key)
        exact = (key == "rank" and requirement.exact_rank) or (key == "stars" and requirement.exact_stars)
        if need and (have is None or (have != need if exact else have < need)):
            relation = '必须为' if exact else '至少'
            reasons.append(f"{label} {have if have is not None else '未知'} / {relation} {need}")
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
    for key, equipped, label in (("unique_level", "unique", "专武1等级"),
                                 ("unique2_stars", "unique2", "专武2强化阶段")):
        need, have = getattr(requirement, key), getattr(actual, key)
        if need is not None:
            if type(need) is not int or (not 0 <= need <= 5 if key == 'unique2_stars' else need <= 0):
                reasons.append(f"攻略{label}数值无效")
            elif getattr(requirement, equipped) is not True:
                reasons.append(f"攻略{label}与装备开启状态冲突")
            elif getattr(actual, equipped) is not True or have is None or have < need:
                reasons.append(f"{label} {have if have is not None else '未知'} / 至少 {need}")
    return reasons


@dataclass
class EventParty:
    name: str
    source: str
    members: list[MemberRequirement]
    modes: list[int] = field(default_factory=lambda: [1, 2, 3])
    max_attempts: int = 3
    allow_deaths: int = 0
    build_basis: str = 'source'
    assumptions: list[str] = field(default_factory=list)
    auto: bool = True
    damage_reference: dict = field(default_factory=dict)


def load_parties(path: str | Path, event_title: str, difficulty: str, mode: int) -> list[EventParty]:
    # Local runtime data; automatic acquisition upstream is still pending.
    # Absence must block combat rather than require a shipped real-event file.
    if not Path(path).exists():
        return []
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


def skill_names(name: str, database: str | Path = "cache/redive_cn.db") -> dict[str, str]:
    """Reuse the CN character catalogue; a DB definition is not an account state."""
    from ..character_data import character
    return (character(name, database) or {}).get('skills', {})


def costume_skills(base: str, database: str | Path = 'cache/redive_cn.db') -> dict[str, dict[str, str]]:
    from ..character_data import characters
    base = normalized(base).split('(')[0]
    return {name: info['skills'] for name, info in characters(database).items()
            if info and name.split('(')[0] == base}
