"""Task-local source acquisition and bounded selection of verified boss parties."""
from __future__ import annotations

from hashlib import sha256
import sqlite3

from ..game_ui.avatars import AvatarIndex
from .event_strategy import EventParty, MemberRequirement, load_parties
from .party_variants import character_roles, alternatives
from .strategy_document import event_parties, event_trial_parties
from .strategy_video import acquire_strategies, task_source_options


def boss_parties(options: dict, *, kind: str, area: str, difficulty: str,
                 mode: int, default_path: str, check=lambda: None) -> tuple[list[EventParty], dict | None]:
    """Search by default; a legacy local plan is an explicit fallback only."""
    for key, default in (('discover_sources', True), ('use_local_teams', False),
                         ('allow_local_trials', True)):
        if type(options.get(key, default)) is not bool:
            raise ValueError(f'{key}必须为布尔值')
    report = None
    found = []
    if options.get('discover_sources', True):
        report = acquire_strategies(task_source_options(kind, options, area=area,
                                    difficulty=difficulty, mode=mode), check=check)
        found = event_parties(report, area, difficulty, mode)
        if options.get('allow_local_trials', True):
            seeds = event_trial_parties(report, area, difficulty, mode)
            found.extend(seeds)
            if seeds:
                avatar_options = options.get('sources', {}).get('avatars') or {}
                try:
                    index = AvatarIndex(avatar_options.get('directory', 'cache/game/avatars/reference'))
                    roles = character_roles(avatar_options.get('database', 'cache/redive_cn.db'))
                except (OSError, ValueError, sqlite3.Error):
                    index, roles = None, {}
            else:
                index, roles = None, {}
            if index is not None and roles:
                available = sorted({str(n) for n in index.names if not str(n).startswith('unit:')})
                seen = {tuple(m.name for m in p.members) for p in found}
                for seed in seeds:
                    order = [m.name for m in seed.members]
                    settings = {m.name: m.instant for m in seed.members}
                    for variant in alternatives(order, available, roles, set(), boss=True):
                        names = tuple(variant['order'])
                        if names in seen:
                            continue
                        seen.add(names)
                        key = sha256((seed.name+'|'.join(names)).encode()).hexdigest()[:12]
                        found.append(EventParty(seed.name+'-'+key, seed.source,
                            [MemberRequirement(name, 1, 1, 1, None, None,
                                settings.get(name, True), 1) for name in names], max_attempts=1,
                            build_basis='local_trial',
                            assumptions=seed.assumptions+[variant['reason'],
                                f"替换 {variant['outgoing']} → {variant['incoming']}；账号实时核验可用性"]))
    if options.get('use_local_teams', False):
        local = load_parties(options.get('teams', default_path), area, difficulty, mode)
        known = {party.name for party in found}
        found.extend(party for party in local if party.name not in known)
    return found, report


def next_boss_party(parties: list[EventParty], attempts: dict[tuple[int, str], int],
                    mode: int) -> EventParty | None:
    return next((party for party in parties
                 if attempts.get((mode, party.name), 0) < party.max_attempts), None)
