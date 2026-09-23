"""Explicit current-account trials for partially parsed boss guides."""
from __future__ import annotations

from .event_formation import EventFormation
from .event_strategy import MemberRequirement
from ..game_ui.screen import normalized
from dataclasses import asdict


class TrialFormation(EventFormation):
    use_current_build = False

    @property
    def requires_declared_build(self):
        return not self.use_current_build

    def resolve_requirement(self, requirement, actual):
        if not self.use_current_build:
            return requirement
        # Unknown live values remain unknown to readiness(); they are not
        # silently interpreted as absent weapons or a usable skill level.
        return MemberRequirement(requirement.name, max(actual.level or 1, 1),
            max(actual.rank or 1, 1), actual.stars or 1,
            actual.unique, actual.unique2, requirement.instant,
            max(actual.skill_level or 1, 1))

    def member_readiness(self, requirement, actual):
        if not self.use_current_build:
            return super().member_readiness(requirement, actual)
        reasons = []
        if not actual.identity_verified:
            reasons.append('试打角色版本未确认')
        if normalized(requirement.name) != normalized(actual.name):
            reasons.append('试打角色身份与候选不符')
        return reasons

    def select(self, party):
        self.use_current_build = party.build_basis == 'local_trial'
        ready, details = super().select(party)
        details['build_basis'] = party.build_basis
        if self.use_current_build:
            details['observed'] = {m.name: asdict(self.observed[normalized(m.name)])
                for m in party.members if normalized(m.name) in self.observed}
            details['unknown_build'] = {name: [key for key in
                ('level', 'rank', 'stars', 'unique', 'unique2', 'skill_level') if row.get(key) is None]
                for name, row in details['observed'].items()}
        return ready, details
