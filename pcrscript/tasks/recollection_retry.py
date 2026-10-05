"""Remember settled failures without authorizing battles from cached account data."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re

from ..game_ui.screen import normalized
from ..game_ui.special_equipment import same_loadout


def known_loadout(value):
    if not isinstance(value, dict):
        return False
    slots = value.get('slots')
    if (not isinstance(slots, list) or len(slots) != 5
            or any(not isinstance(col, list) or len(col) != 3
                   or any(type(slot) is not bool for slot in col) for col in slots)):
        return False
    try:
        return same_loadout(value, value)
    except (TypeError, ValueError):
        return False


def mastery_snapshot(nodes):
    """Use complete freshly observed roles; filenames and stock are not stats."""
    from ..game_ui.role_mastery import ROLE_NODES, ROLE_TABS
    if not isinstance(nodes, list) or not nodes:
        return None
    snapshot = {}
    for row in nodes:
        if not isinstance(row, dict):
            return None
        role, node, status = row.get('role'), row.get('node'), row.get('state')
        if (role not in ROLE_NODES or type(node) is not int or not 0 <= node < 4
                or not isinstance(status, dict) or type(status.get('level')) is not int
                or status['level'] < 1):
            return None
        title = '【'+ROLE_TABS[role][0]+'】'+ROLE_NODES[role][node]+'Lv'+str(status['level'])
        if status.get('title') != title:
            return None
        raw = str(status.get('value'))
        if not re.fullmatch(r'\d+(?:\.\d+)?%?',raw):
            return None
        try:
            value = Decimal(raw.removesuffix('%'))
        except InvalidOperation:
            return None
        if not value.is_finite() or value < 0:
            return None
        snapshot.setdefault(role, {})[str(node)] = dict(level=status['level'],
            value=str(value.normalize())+('%' if raw.endswith('%') else ''))
    if any(set(role) != {'0','1','2','3'} for role in snapshot.values()):
        return None
    return snapshot


def trial_context(signature, party, details, power, *, mastery=None):
    """Only a fresh complete audit and visible formation power identify a trial."""
    if (not isinstance(signature, dict) or type(power) is not int or power <= 0
            or not signature.get('boss') or type(signature.get('level')) is not int
            or type(signature.get('maximum_hp')) is not int
            or not isinstance(signature.get('scope'), dict)
            or not signature['scope'].get('area')
            or type(signature['scope'].get('floor')) is not int):
        return None
    order = details.get('order', [])
    observed = details.get('observed', {})
    if not isinstance(observed, dict) or len(order) != 5 or len(set(order)) != 5:
        return None
    observed = {normalized(name): status for name, status in observed.items()}
    members = []
    required = {normalized(m.name): m for m in party.members}
    for name in order:
        status = observed.get(normalized(name))
        requirement = required.get(normalized(name))
        if (not isinstance(status, dict) or status.get('identity_verified') is not True
                or normalized(status.get('name') or '') != normalized(name)
                or requirement is None or type(requirement.instant) is not bool
                or any(type(status.get(k)) is not int for k in ('level','rank','stars','skill_level'))
                or any(type(status.get(k)) is not bool for k in ('unique','unique2'))):
            return None
        members.append({k: status.get(k) for k in ('name','level','rank','stars','skill_level',
            'equipment','unique','unique2','unique_level','unique2_stars')})
    special = details.get('special_equipment', {})
    # Also reject absent/malformed item observations, not just unknown slots.
    if (type(party.auto) is not bool or special.get('order') != order
            or not known_loadout(special)):
        return None
    context = dict(target={k: signature.get(k) for k in ('scope','boss','level','maximum_hp')},
                power=power, members=members, auto=party.auto,
                instant=[required[normalized(name)].instant for name in order],
                special={k: special.get(k) for k in ('order','slots','unknown','items')},
                settings_version=1)
    if mastery is not None:
        snapshot = mastery_snapshot(mastery)
        if snapshot is None:
            return None
        context['mastery'] = snapshot
    return deepcopy(context)


def same_trial(first, second):
    if not isinstance(first, dict) or not isinstance(second, dict):
        return False
    fields = ('target','power','members','auto','instant','settings_version')
    # Missing legacy observations or different coverage do not prove a change.
    # Only a shared fully observed role with changed stats permits a new trial.
    before, after = first.get('mastery', {}), second.get('mastery', {})
    mastery_same = (isinstance(before, dict) and isinstance(after, dict)
                   and all(before[role] == after[role] for role in before.keys() & after.keys()))
    return (mastery_same and all(k in first and k in second and first[k] == second[k] for k in fields)
            and known_loadout(first.get('special')) and known_loadout(second.get('special'))
            and same_loadout(first.get('special', {}), second.get('special', {})))


def same_roster(context, scope, order):
    if not isinstance(context, dict) or context.get('target', {}).get('scope') != scope:
        return False
    names = [normalized(row['name']) for row in context.get('members', [])
             if isinstance(row, dict) and isinstance(row.get('name'), str)]
    return len(names) == len(order) == 5 and sorted(names) == sorted(map(normalized, order))


def remember_failure(state, record):
    """Keep only a failure settled with counters and applied settings verified."""
    context = record.get('trial_context')
    if (not context or record.get('progressed') is not False
            or record.get('settings_verified') is not True
            or 'attempts_after' not in record or 'attempts_before' not in record
            or record.get('attempts_after') != record.get('attempts_before')
            or not (record.get('result_outcome') == 'failed'
                    or record.get('outcome') in ('failed','recovered_failed')
                    or record.get('outcome') == 'retreated'
                    and record.get('reason') == '减员超出队伍容许值，尝试下一队')):
        return
    rows = state.setdefault('failed_trials', [])
    rows[:] = [row for row in rows if not same_trial(row.get('context'), context)]
    rows.append(dict(context=deepcopy(context), evidence=record.get('after', ''),
                     settings_evidence=record.get('settings_evidence', '')))
    del rows[:-32]
