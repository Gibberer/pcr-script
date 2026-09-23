"""Source evidence and unknown-preserving strategy interchange, independent of UI."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .event_strategy import EventParty, MemberRequirement

VERSION = 2
BUILD_FIELDS = ('level', 'rank', 'stars', 'unique', 'unique2', 'skill_level', 'instant')


@dataclass
class Evidence:
    source: str
    cid: int | None = None
    seconds: float | None = None
    image: str = ''
    rectangle: list[int] | None = None
    method: str = ''
    text: str = ''
    confidence: float | None = None


@dataclass
class Fact:
    value: Any = None
    evidence: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)

    def add(self, value: Any, evidence: Evidence) -> None:
        if value is None:
            return
        proof = asdict(evidence)
        if self.conflicts:
            self.conflicts.append(dict(value=value, evidence=proof))
        elif self.value is not None and (type(self.value) is not type(value) or self.value != value):
            self.conflicts = [dict(value=self.value, evidence=self.evidence), dict(value=value, evidence=proof)]
            self.value = None
        else:
            self.value = value
            if proof not in self.evidence:
                self.evidence.append(proof)


def empty_member(name: str) -> dict:
    return dict(name=name, **{key: Fact() for key in BUILD_FIELDS})


def missing_fields(party: dict) -> list[str]:
    reasons = []
    members = party.get('members', [])
    if (len(members) != 5 or len({m.get('name') for m in members}) != 5
            or any(not isinstance(m.get('name'), str) or not m['name'].strip() or m['name'].startswith('unit:') for m in members)):
        reasons.append('五人身份不完整或重复')
    for member in members:
        for key in BUILD_FIELDS:
            fact = member.get(key, {})
            value = fact.get('value')
            valid = type(value) is bool if key in ('unique', 'unique2', 'instant') else type(value) is int and value > 0
            if key == 'stars':
                valid = type(value) is int and 1 <= value <= 6
            if not valid or not fact.get('evidence') or fact.get('conflicts'):
                reasons.append(f'{member.get("name", "未知角色")}.{key}未明确或冲突')
    if not party.get('scope_verified'):
        reasons.append('来源适用关卡/阶段未核验')
    if party.get('region') not in ('cn', 'jp', 'tw') or party.get('region') != party.get('target_region'):
        reasons.append('来源服区未明确或不符')
    if party.get('global_requirements'):
        reasons.append('存在尚无账号核验器的全局培养要求')
    if party.get('manual_actions'):
        reasons.append('来源包含尚不支持的手动操作/轴')
    auto = party.get('auto', {})
    if auto.get('value') is not True or not auto.get('evidence') or auto.get('conflicts'):
        reasons.append('来源未确认全程AUTO开启或存在切换；当前执行器只支持固定AUTO开启')
    return reasons


def finalize(party: dict) -> dict:
    result = dict(party)
    if isinstance(result.get('auto'), Fact):
        result['auto'] = asdict(result['auto'])
    result['members'] = [{k: asdict(v) if isinstance(v, Fact) else v for k, v in member.items()}
                         for member in party['members']]
    result['pending'] = missing_fields(result)
    result['readiness'] = 'ready' if not result['pending'] else 'incomplete'
    result['id'] = sha256(json.dumps([result['source'], result.get('scope'),
                         [m['name'] for m in result['members']]], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
    return result


def to_event_party(party: dict) -> EventParty:
    reasons = missing_fields(party)
    if reasons:
        raise ValueError('攻略未满足自动执行条件：'+'；'.join(reasons))
    return EventParty(party['id'], party['source'], [MemberRequirement(
        member['name'], **{key: member[key]['value'] for key in BUILD_FIELDS}) for member in party['members']])


def export_document(path: Path, report: dict) -> None:
    from ..game_ui.avatar_assets import atomic_json
    atomic_json(Path(path), dict(report, version=VERSION))


def abyss_candidate(party: dict) -> dict:
    """Retain full evidence in the existing candidate-facing structure."""
    scope = party['scope']
    return dict(names=[m['name'] for m in party['members']],
                instant=[m['instant']['value'] for m in party['members']],
                required_stars=[m['stars']['value'] for m in party['members']],
                source=party['source'], element=scope.get('element'), stages=[scope['stage']] if scope.get('stage') else [],
                chapters=scope.get('chapters'), excluded_stages=[],
                build_basis='source' if party['readiness'] == 'ready' else 'source_incomplete',
                document=party, notes=party.get('notes', ''), pending=party['pending'])


def dungeon_plan(report: dict, area: str):
    """Choose one source's complete, non-overlapping route; never merge guides."""
    from .dungeon_party import DungeonParty, route_conflicts
    candidates = {}
    for party in report.get('parties', []):
        scope = party.get('scope', {})
        if missing_fields(party) or scope.get('area') != area:
            continue
        floor, phase = scope.get('floor'), scope.get('phase', '')
        if type(floor) is not int or floor not in range(1, 6) or floor == 5 and not phase:
            continue
        candidates.setdefault(party['source'], []).append(
            DungeonParty(party['id'], floor, phase, to_event_party(party)))
    for route in candidates.values():
        # Multiple teams for one phase need route ordering/HP reasoning, not an
        # arbitrary choice. This first adapter supports one team per phase only.
        phases = [p.phase for p in route if p.floor == 5]
        if (area == '四彩的灵峰' and {p.floor for p in route} == set(range(1, 6))
                and len(phases) == 4 and len(set(phases)) == 4
                and all(any(season in phase for phase in phases) for season in '春夏秋冬')
                and not route_conflicts(route)):
            return route
    return []
