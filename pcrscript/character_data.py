"""Shared read-only character metadata from the existing CN activity database.

Catalogue definitions never establish account ownership or installed equipment.
"""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import sqlite3

from .game_ui.screen import normalized


@lru_cache(maxsize=8)
def _catalogue(path, modified, size):
    # File identity is part of the cache key: an atomic activity DB refresh
    # invalidates both costume and equipment metadata automatically.
    with closing(sqlite3.connect(Path(path).as_uri()+'?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        profiles = conn.execute('SELECT unit_id,unit_name FROM unit_profile').fetchall()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        skills = {}
        training_skills = {}
        if {'unit_skill_data', 'skill_data'} <= tables:
            names = dict(conn.execute('SELECT skill_id,name FROM skill_data'))
            for row in conn.execute('SELECT * FROM unit_skill_data'):
                skills[row['unit_id']] = {k: normalized(names[row[k]]) for k in (
                    'main_skill_1', 'main_skill_evolution_1', 'main_skill_2', 'main_skill_evolution_2')
                    if k in row.keys() and row[k] and row[k] in names}
                training_skills[row['unit_id']] = {k: normalized(names[row[k]]) for k in (
                    'union_burst', 'union_burst_evolution', 'main_skill_1', 'main_skill_evolution_1',
                    'main_skill_2', 'main_skill_evolution_2', 'ex_skill_1', 'ex_skill_evolution_1')
                    if k in row.keys() and row[k] and row[k] in names}
        equipment = {}
        complete = {'unit_unique_equipment', 'unique_equipment_data', 'unit_skill_data', 'skill_data'} <= tables
        if complete:
            try:
                rows = conn.execute('SELECT u.unit_id,u.equip_slot,u.equip_id,d.equipment_name '
                    'FROM unit_unique_equipment u LEFT JOIN unique_equipment_data d '
                    'ON d.equipment_id=u.equip_id').fetchall()
                complete = bool(rows)
                for row in rows:
                    if row['equip_slot'] not in (1, 2) or not row['equipment_name']:
                        complete = False
                        continue
                    slots = equipment.setdefault(row['unit_id'], {})
                    if row['equip_slot'] in slots:
                        complete = False
                    slots[row['equip_slot']] = dict(id=row['equip_id'], name=normalized(row['equipment_name']))
            except sqlite3.Error:
                complete = False
        result = {}
        for row in profiles:
            name = normalized(row['unit_name'])
            if name in result:
                result[name] = None  # Ambiguous costumes cannot authorize a shortcut.
                continue
            result[name] = dict(name=name, unit_id=row['unit_id'], skills=skills.get(row['unit_id'], {}),
                training_skills=training_skills.get(row['unit_id'], {}),
                unique_slots=equipment.get(row['unit_id'], {}),
                equipment_catalogue_complete=complete and all(k in skills.get(row['unit_id'], {})
                    for k in ('main_skill_1', 'main_skill_2')))
        return result


def characters(database='cache/redive_cn.db'):
    path = Path(database).resolve()
    try:
        stamp = path.stat()
        return deepcopy(_catalogue(str(path), stamp.st_mtime_ns, stamp.st_size))
    except (OSError, sqlite3.Error):
        return {}


def character(name, database='cache/redive_cn.db'):
    return characters(database).get(normalized(name))


def equipment_requirement_issues(members, database='cache/redive_cn.db', *, verified_current=False):
    """Reject impossible source requirements early; never synthesize account flags."""
    if not verified_current:
        return []
    catalogue = characters(database)
    issues = []
    for member in members:
        info = catalogue.get(normalized(member.name))
        if not info or not info['equipment_catalogue_complete']:
            continue
        for slot, flag, numeric in ((1, 'unique', 'unique_level'), (2, 'unique2', 'unique2_stars')):
            required = getattr(member, flag) is True or getattr(member, numeric) is not None
            # A skill evolution without its equipment row suggests incomplete
            # data. Keep UI verification in that case, rather than assuming off.
            if (required and slot not in info['unique_slots']
                    and f'main_skill_evolution_{slot}' not in info['skills']):
                issues.append(dict(character=member.name, slot=slot,
                    reason=f'当前国服数据库未定义此角色的专武{slot}，无法满足来源要求'))
    return issues
