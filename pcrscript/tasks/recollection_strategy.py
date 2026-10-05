"""Exact-floor guide selection; incomplete builds need explicit audited trials."""
from __future__ import annotations

from dataclasses import asdict

from .event_formation import EventFormation
from .event_strategy import EventParty, MemberRequirement
from .strategy_document import BUILD_FIELDS, missing_fields, to_event_party
from ..game_ui.screen import normalized
from ..run_session import clock as time


def parties_for_floor(report, area, floor, *, allow_local_trials=False):
    result = []
    seen = set()
    for raw in report.get('parties', []):
        if raw.get('scope') != dict(area=area, floor=floor) or not raw.get('scope_verified'):
            continue
        live_trial = any(e.get('method') == 'combat_matches_live_target' for e in raw.get('scope_evidence', []))
        if live_trial and not allow_local_trials:
            continue
        if not missing_fields(raw) and not live_trial:
            party = to_event_party(raw)
        elif allow_local_trials:
            members = raw.get('members', [])
            names = [m.get('name') for m in members]
            flags = [raw.get('auto', {})]+[m.get('instant', {}) for m in members]
            if (raw.get('region') != 'cn' or raw.get('global_requirements') or raw.get('manual_actions')
                    or len(names) != 5 or any(not isinstance(n, str) or not n.strip() or n.startswith('unit:') for n in names)
                    or len(set(map(normalized, names))) != 5
                    or any(type(f.get('value')) is not bool or not f.get('evidence') or f.get('conflicts') for f in flags)
                    or any(m.get(k,{}).get('conflicts') for m in members for k in BUILD_FIELDS)):
                continue
            party = EventParty(raw['id']+'-trial', raw['source'],
                [MemberRequirement(m['name'],m.get('level',{}).get('value'),
                    m.get('rank',{}).get('value'),m.get('stars',{}).get('value'),
                    m.get('unique',{}).get('value'),m.get('unique2',{}).get('value'),
                    m['instant']['value'],m.get('skill_level',{}).get('value'),
                    equipment=m.get('equipment',{}).get('value'),
                    unique_level=m.get('unique_level',{}).get('value'),
                    unique2_stars=m.get('unique2_stars',{}).get('value')) for m in members],
                max_attempts=1, build_basis='local_trial', assumptions=missing_fields(raw), auto=raw['auto']['value'])
            if live_trial:
                party.assumptions.append('来源战斗与实时目标的首领、等级和生命上限一致；按账号培养试打')
        else:
            continue
        if party.name not in seen:
            seen.add(party.name)
            result.append(party)
    return result


class RecollectionFormation(EventFormation):
    use_current_build = False
    infer_costume_from_skills = True
    require_current_skills = True

    def __init__(self, ui):
        super().__init__(ui)
        self.unreleased = {}

    def inspect(self, *args, **kwargs):
        actual = super().inspect(*args, **kwargs)
        proof = self.unreleased.get(normalized(actual.name))
        if (actual.identity_verified and actual.unique is None and actual.unique2 is None
                and proof and 0 <= time.time()-proof[0] < 3600):
            actual.unique = actual.unique2 = False
            actual.equipment_evidence = proof[1]
            if kwargs.get('full', True):
                self.observed[normalized(actual.name)] = actual
        return actual

    @property
    def requires_declared_build(self):
        return not self.use_current_build

    def member_readiness(self, requirement, actual):
        if not self.use_current_build:
            return super().member_readiness(requirement, actual)
        reasons = []
        if not actual.identity_verified or normalized(actual.name) != normalized(requirement.name):
            reasons.append('试打角色身份未核验')
        for key in ('level', 'rank', 'stars', 'skill_level', 'unique', 'unique2'):
            if getattr(actual, key) is None:
                reasons.append('账号培养或装备未明确：'+key)
        # Missing source fields may be bound to this audited account. A
        # declared Rank, star setting or equipment requirement stays binding.
        from .party_preparation import trial_requirement
        from .event_strategy import readiness
        reasons.extend(readiness(trial_requirement(requirement,actual),actual))
        return reasons

    def select(self, party):
        self.use_current_build = party.build_basis == 'local_trial'
        ready, details = super().select(party)
        details.update(build_basis=party.build_basis, assumptions=party.assumptions,
                       observed={m.name: asdict(self.observed[normalized(m.name)])
                                 for m in party.members if normalized(m.name) in self.observed})
        return ready, details
