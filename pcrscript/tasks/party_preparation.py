"""Shared guide selection, cultivation gaps and verified pre-battle preparation.

Game-specific navigation stays with the caller. Plans never authorize spending;
only independently enabled, implemented executors may change the account.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path

from .event_strategy import CharacterStatus, EventParty, MemberRequirement, readiness
from ..game_ui.screen import EventUIError, normalized
from ..game_ui.special_equipment import auto_equip_special, inspect_special_equipment, same_loadout
from ..run_session import clock as time


BUILD_FIELDS = ('level', 'rank', 'stars', 'skill_level', 'equipment',
                'unique', 'unique2', 'unique_level', 'unique2_stars')


def prepare_character_database(formation, options=None, *, check=lambda: None):
    """Reuse the activity DB downloader, separately from the avatar cache age."""
    from ..game_ui.avatar_assets import ensure_database
    options = options or {}
    formation.database = str(options.get('database', 'cache/redive_cn.db'))
    try:
        report = ensure_database(Path(formation.database), max_age_hours=24, check=check)
    except (OSError, RuntimeError) as error:
        report = dict(stale=True, error=type(error).__name__)
    formation.character_database = report
    return report


def catalogue_issues(formation, members):
    from ..character_data import equipment_requirement_issues
    from ..game_ui.avatar_assets import DB_SOURCE
    report = getattr(formation, 'character_database', {})
    current = (isinstance(report, dict) and not report.get('stale', True)
        and report.get('source') == DB_SOURCE and type(report.get('version')) is int
        and report['version'] > 0 and type(report.get('checked_at')) in (int, float)
        and 0 <= time.time()-report.get('checked_at', 0) < 86400)
    return equipment_requirement_issues(members, getattr(formation, 'database', 'cache/redive_cn.db'),
                                         verified_current=current)


def numeric_equipment_unknown(party, observed):
    return [m.name for m in party.members if any(getattr(m, key) is not None
            and (normalized(m.name) not in observed or getattr(observed[normalized(m.name)], key) is None)
            for key in ('unique_level', 'unique2_stars'))]


def read_numeric_equipment(formation, name):
    from ..game_ui.character_equipment import inspect_unique_equipment
    proof = inspect_unique_equipment(formation.ui, name)
    if proof:
        formation.equipment_details[normalized(name)] = proof
        formation.observed.pop(normalized(name), None)
    return proof


def trial_requirement(declared, actual):
    """Bind only missing fields; retain every known source requirement."""
    fallback = dict(level=max(actual.level or 1, 1), rank=max(actual.rank or 1, 1),
                    stars=actual.stars or 1, skill_level=actual.skill_level or 0,
                    equipment=actual.equipment or 0, unique=actual.unique,
                    unique2=actual.unique2, unique_level=actual.unique_level,
                    unique2_stars=actual.unique2_stars)
    return replace(declared, **{key: fallback[key] for key in BUILD_FIELDS
                               if getattr(declared, key) is None})


def audit_declared_build(formation, party, audit, declared):
    """Audit retained source members; replacements never inherit their build."""
    requirements = {normalized(m.name): m for m in declared}
    actuals = {normalized(row['name']): CharacterStatus(**row) for row in audit['observed']}
    failures = []
    for member in party.members:
        name = normalized(member.name)
        required = requirements.get(name)
        if required is None:
            continue
        actual = actuals[name]
        if required.skill_level and actual.skill_level is None:
            pos = formation.slots[audit['order'].index(name)]
            actual = formation.inspect(pos, rectangle=(pos[0]-48, formation.slot_top, 96, 96),
                                       expected_name=name, verify_skills=True)
            actuals[name] = actual
        resolved = trial_requirement(required, actual)
        reasons = readiness(resolved, actual)
        if reasons:
            failures.append(dict(character=name, reasons=reasons))
        member.instant = required.instant
        for key in ('skill_level', 'unique_level', 'unique2_stars'):
            if getattr(required, key) is not None:
                setattr(member, key, getattr(actual, key))
    audit['observed'] = [asdict(actuals[n]) for n in audit['order']]
    audit['cultivation'] = cultivation_plan(replace(party, members=list(declared)), actuals.values())
    audit['unready'] = failures
    return not failures


def cultivation_plan(party, observed):
    """Explain exact gaps, including installation separately from enhancement."""
    actuals = {normalized(a.name): a for a in observed}
    rows = []
    for need in party.members:
        actual = actuals.get(normalized(need.name))
        if actual is None or not actual.identity_verified:
            rows.append(dict(character=need.name, field='identity', action='verify_identity',
                             target=need.name, current=None, executable=False))
            continue
        for key in BUILD_FIELDS:
            target, current = getattr(need, key), getattr(actual, key)
            optional = key in ('unique_level', 'unique2_stars')
            if target is None or (key in ('skill_level', 'equipment') and not target):
                # Known empty slots still deserve attention in an account trial.
                if key in ('unique', 'unique2') and current is False:
                    rows.append(dict(character=need.name, field=key, action='check_release_and_requirement',
                                     target=None, current=False, executable=False))
                continue
            exact = key in ('unique', 'unique2') or (key == 'rank' and need.exact_rank) or (key == 'stars' and need.exact_stars)
            if current is not None and (current == target if exact else current >= target):
                continue
            action = 'inspect' if current is None else 'enhance'
            if key in ('unique', 'unique2') and current is not None:
                action = 'install' if target else 'incompatible_installed_equipment'
            elif key == 'rank' and current is not None and current > target:
                action = 'incompatible_rank'
            elif key == 'stars':
                action = 'inspect' if current is None else 'change_stars' if current > target else 'raise_stars'
            row = dict(character=need.name, field=key, action=action,
                       current=current, target=target, executable=False)
            if key == 'unique2' and target and actual.unique is not True:
                row['prerequisite'] = 'unique'
            if key in ('unique', 'unique2') or optional:
                row['reason'] = '专武补装/强化须单独核实开放状态、材料预览、授权及消费回执'
            elif key == 'stars' and target == 5 and action in ('raise_stars', 'change_stars'):
                row['executor'] = 'five_star_upgrade'
            rows.append(row)
    return dict(party=party.name, source=party.source, build_basis=party.build_basis,
                gaps=rows, ready=not rows)


def party_fingerprint(party):
    """Build, switches and a verified damage goal define a distinct trial."""
    reference = party.damage_reference
    return json.dumps([party.auto, sorted((normalized(m.name), asdict(m))
                       for m in party.members), reference.get('damage'), reference.get('scope'),
                       bool(reference.get('evidence'))], ensure_ascii=False, sort_keys=True)


def rank_candidates(parties, observed, *, available=()):
    """Use account evidence for ordering only; live selection still gates combat."""
    actuals = {normalized(a.name): a for a in observed.values() if a.identity_verified}
    owned = set(map(normalized, available)) | set(actuals)
    def score(party):
        incompatible = unknown = edits = 0
        for member in party.members:
            actual = actuals.get(normalized(member.name))
            if actual is None:
                unknown += 1
                continue
            plan = cultivation_plan(EventParty('', '', [member]), [actual])
            incompatible += sum(g['action'].startswith('incompatible') for g in plan['gaps'])
            edits += sum(g['action'] in ('install', 'enhance', 'raise_stars', 'change_stars') for g in plan['gaps'])
            unknown += sum(g['action'] in ('inspect', 'verify_identity') for g in plan['gaps'])
        return (sum(normalized(m.name) not in owned for m in party.members), incompatible, edits,
                unknown, party.build_basis != 'source')
    return sorted(parties, key=score)


@dataclass
class GuideCandidate:
    party: EventParty
    allow_substitutions: bool = False


def source_candidates(fetch, observations, *, max_batches=3, available=lambda: (),
                      allow_substitutions=True):
    """Bound source batches and try all original teams before guided substitutions."""
    seen, originals = set(), []
    for batch in range(max_batches):
        fresh = []
        fetched = list(fetch(advance=batch > 0))
        for party in fetched:
            key = party_fingerprint(party)
            if key not in seen:
                seen.add(key)
                fresh.append(party)
        if fetched and not fresh:
            break
        if not fresh:
            continue
        for party in rank_candidates(fresh, observations(), available=available()):
            originals.append(party)
            yield GuideCandidate(party)
    if allow_substitutions and originals:
        for party in rank_candidates(originals, observations(), available=available()):
            yield GuideCandidate(party, allow_substitutions=True)


def prepare_special(formation, party, order, *, auto=True, expected=None):
    """Equip before a trial; paid repeats must retain the simulated loadout."""
    expected_names = {normalized(m.name) for m in party.members}
    if len(order) != 5 or len(expected_names) != 5 or set(order) != expected_names:
        raise EventUIError('特别装备准备的五人身份不完整或不符')
    result = (auto_equip_special(formation.ui, order) if auto and expected is None
              else inspect_special_equipment(formation.ui, order))
    if result['unknown']:
        raise EventUIError('特别装备槽位未知，未开战')
    # Every return from a separate panel must re-establish the live five slots.
    actual = formation.inspect_current(full=False, expected_names=order, verify_skills=False)
    if ([normalized(a.name) for a in actual] != list(order)
            or not all(a.identity_verified for a in actual)):
        raise EventUIError('特别装备返回后编队发生变化，未开战')
    if expected is not None and not same_loadout(expected, result):
        raise EventUIError('特别装备与模拟战不一致，必须重新模拟，未实战')
    return result


def upgrade_party_stars(formation, party, audit, *, options, report, save, leave, reopen, stage,
                        declared=()):
    """Shared five-star executor, preserving source constraints and battle settings."""
    if not options.get('allow_five_star_upgrade') or options.get('audit_only') or options.get('preview_only'):
        return party, audit
    constraints = {normalized(m.name): m for m in declared}
    targets = []
    for row in audit.get('observed', []):
        need = constraints.get(normalized(row['name']))
        if row.get('identity_verified') and row.get('stars') and row['stars'] < 5:
            if need is None or need.stars is None or need.stars == 5 or (not need.exact_stars and need.stars <= 5):
                targets.append(row['name'])
    if not targets:
        return party, audit
    target_names = {normalized(name) for name in targets}
    # Validate the rest of the build before spending anything on stars.
    for row in audit['observed']:
        need = constraints.get(normalized(row['name']))
        if need is not None:
            actual = CharacterStatus(**row)
            required = trial_requirement(need, actual)
            # Only waive a star gap that this executor is about to repair.
            if normalized(actual.name) in target_names:
                required = replace(required, stars=actual.stars)
            reasons = readiness(required, actual)
            if reasons:
                audit['unready'] = [dict(character=actual.name, reasons=reasons)]
                audit['cultivation'] = cultivation_plan(replace(party, members=list(declared)),
                    [CharacterStatus(**r) for r in audit['observed']])
                return None, audit
    from ..game_ui.character_stars import upgrade_to_five
    leave()
    for name in targets:
        record = {}
        report.setdefault('star_upgrades', []).append(record)
        upgrade_to_five(formation.ui, name, record, save,
                        allow_amulets=options.get('allow_divine_amulets', False))
        formation.observed.pop(normalized(name), None)
    reopen()
    # Repopulation uses observed builds; old pinned trial stars are now stale.
    probe = replace(party, members=[replace(m, stars=5) if normalized(m.name) in target_names else m
                                    for m in party.members])
    ready, selection = formation.select(probe)
    if not ready:
        return None, dict(unready=['升星后编队未恢复'], selection=selection)
    updated, fresh = formation.current_trial(stage)
    if updated is None:
        return None, fresh
    if set(fresh['order']) != {normalized(m.name) for m in party.members}:
        return None, dict(unready=['升星后队伍身份改变'])
    switches = {normalized(m.name): m.instant for m in party.members}
    for member in updated.members:
        member.instant = switches[normalized(member.name)]
    # Keep source metadata, fixed AUTO and damage reference after re-auditing.
    updated = replace(party, members=updated.members)
    for key in ('source', 'adjustment', 'set_adjustment', 'adaptations', 'assumptions'):
        if key in audit:
            fresh[key] = audit[key]
    return updated, fresh
