"""Adapt public guide members to the account and preserve verified battle builds."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from .event_strategy import readiness
from .strategy_formation import StrategyFormation, StrategyTarget
from .party_preparation import (audit_declared_build, numeric_equipment_unknown,
    read_numeric_equipment, upgrade_party_stars, prepare_character_database, catalogue_issues)
from ..game_ui import abyss_subjugation as field
from ..game_ui.avatar_assets import ensure_avatar_index
from ..game_ui.screen import EventUIError, normalized
from ..run_session import clock as time

def character_talents(database='cache/redive_cn.db'):
    try:
        with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro', uri=True)) as conn:
            rows = conn.execute('SELECT p.unit_name,t.talent_id FROM unit_profile p '
                                'JOIN unit_talent t ON p.unit_id=t.unit_id').fetchall()
    except sqlite3.Error as error:
        raise EventUIError('国服角色属性资料不可用') from error
    values = {}
    for name, talent in rows:
        values.setdefault(normalized(name), set()).add(talent)
    return {name: next(iter(talents)) if len(talents) == 1 else None for name, talents in values.items()}


def prepare_avatars(runner):
    if not getattr(runner, 'avatars_ready', False):
        runner.formation.avatars, assets = ensure_avatar_index(runner.options.get('avatars'), check=runner.check_deadline)
        runner.report['character_database'] = prepare_character_database(runner.formation,
            runner.options.get('avatars'), check=runner.check_deadline)
        runner.report['avatar_assets'] = {key: assets.get(key) for key in (
            'version', 'fetched_at', 'complete', 'database', 'source', 'features',
            'identities', 'index_sha256', 'cache_hit', 'errors')}
        runner.avatars_ready = True


def require_event_talent(runner, party):
    """Require every guide or audited member to match this event's attribute."""
    talent = runner.event.extras.get('talent_id')
    if type(talent) is not int or talent not in range(1, 6):
        raise EventUIError('活动加成属性未知')
    if not hasattr(runner, 'character_talents'):
        runner.character_talents = character_talents(runner.options.get('avatars', {}).get('database', 'cache/redive_cn.db'))
    if any(runner.character_talents.get(normalized(member.name)) != talent for member in party.members):
        raise EventUIError('完整身份核验后队伍未全部匹配本期加成属性')


class SubjugationFormation(StrategyFormation):
    """Use shared account selection; pin a simulated party before real battle."""
    def __init__(self, ui):
        super().__init__(ui)
        self.unreleased = {}
        self.pin_build = False

    def resolve_requirement(self, requirement, actual):
        return requirement if self.pin_build else super().resolve_requirement(requirement, actual)

    def select(self, party):
        self.pin_build = True
        strict = getattr(self, 'strict_source', False)
        if self.pin_build and any(m.skill_level for m in party.members):
            self.strict_source = True
        try:
            recent = self.quick_current(full=True, expected_names=[m.name for m in party.members])
            wanted = {normalized(m.name): m for m in party.members}
            if recent is not None and all(not readiness(wanted[normalized(m.name)], m) for m in recent):
                return True, dict(order=[normalized(m.name) for m in recent],
                                  reused_recent_audit=True)
            return super().select(party)
        finally:
            self.pin_build = False
            self.strict_source = strict

    def _select_source_party(self, party):
        # Source identity selection uses provisional requirements. Executable
        # parties always go through select(), which pins the audited build.
        return super().select(party)


def trial_stage(runner, title='深渊讨伐战', *, boss=False):
    from .subjugation_guides import ELEMENTS
    return StrategyTarget(element=ELEMENTS[runner.event.extras['talent_id']-1],
                          key='subjugation', title=title, is_boss=boss)


def recover_equipment(runner, names):
    from ..game_ui.character_equipment import inspect_unreleased_equipment
    from .task_home import ToHomePage
    runner.report_progress('深渊讨伐战 · 人物页核验未知专武')
    s = runner.capture()
    if field.formation(s):
        runner.click(s, '取消', (635, 415, 785, 500))
    ToHomePage(runner.robot).run(timeout=60)
    for name in names:
        prior = runner.formation.observed.get(normalized(name))
        partial = prior is not None and ((prior.unique is None) != (prior.unique2 is None))
        if partial or name in getattr(runner.formation, 'numeric_equipment_names', ()):
            read_numeric_equipment(runner.formation, name)
            ToHomePage(runner.robot).run(timeout=60)
            continue
        if prior is not None and prior.unique is not None and prior.unique2 is not None:
            continue
        runner.check_deadline()
        proof = inspect_unreleased_equipment(runner.ui, name)
        if proof:
            runner.formation.unreleased[normalized(name)] = (time.time(), proof)
        ToHomePage(runner.robot).run(timeout=60)


def guide_party(runner, seed, reopen, *, allow_substitutions=True):
    """Keep source switches, while pinning a trial's separately observed build."""
    prepare_avatars(runner)
    runner.report_progress('核验攻略队伍 · 衣装、等级、技能与专武')
    issues = catalogue_issues(runner.formation, seed.members)
    if issues:
        runner.report.setdefault('party_audits', []).append(dict(source=seed.source, unready=issues,
            character_database=runner.formation.character_database))
        raise EventUIError('攻略要求与当前国服角色资料不符：'+str(issues))
    require_event_talent(runner, seed)
    runner.formation.allow_substitutions = allow_substitutions
    numeric = numeric_equipment_unknown(seed, runner.formation.observed)
    if numeric:
        runner.formation.numeric_equipment_names = numeric
        try:
            recover_equipment(runner, numeric)
            reopen()
        finally:
            runner.formation.numeric_equipment_names = ()
    source = dict(source=seed.source, names=[normalized(m.name) for m in seed.members],
                  instant=[m.instant for m in seed.members], required_stars=[m.stars for m in seed.members])
    def recover(stage, names):
        recover_equipment(runner, names)
        reopen()
    runner.formation.recover_equipment = recover
    runner.formation.check_deadline = runner.check_deadline
    party, audit = runner.formation.source_trial(trial_stage(runner, seed.name), source)
    runner.report.setdefault('party_audits', []).append(audit)
    if party is None:
        raise EventUIError('攻略队伍未通过共享编队核验：'+str(audit))
    from .task_home import ToHomePage
    def leave():
        runner.enter()
        ToHomePage(runner.robot).run(timeout=60)
    party, audit = upgrade_party_stars(runner.formation, party, audit, options=runner.options,
        report=runner.report, save=runner.save, leave=leave, reopen=reopen,
        stage=trial_stage(runner, seed.name), declared=seed.members)
    if runner.report['party_audits'][-1] is not audit:
        runner.report['party_audits'].append(audit)
    if party is None:
        raise EventUIError('培养后队伍未通过核验：'+str(audit))
    order = audit['order']
    adaptations = source.get('adaptations', [])
    original = {normalized(m.name) for m in seed.members}
    if (set(order) != set(map(normalized, source['names'])) or not set(order)-original <= {
            normalized(a['replacement']) for a in adaptations}):
        raise EventUIError('实际五人完整衣装与共享核验的攻略或替补名单不符')
    if not audit_declared_build(runner.formation, party, audit, seed.members):
        raise EventUIError('账号培养与已明确的攻略要求不符：'+str(audit['unready']))
    party.name, party.source, party.auto = seed.name, seed.source, seed.auto
    party.build_basis, party.allow_deaths = ('local_trial' if adaptations else seed.build_basis), 0
    party.damage_reference = {} if adaptations else dict(seed.damage_reference)
    party.assumptions = list(seed.assumptions)+['按共享编队流程核验当前账号，来源缺失字段仍保留为未知']
    party.assumptions.extend('共享编队缺员替补：'+a['missing']+' → '+a['replacement'] for a in adaptations)
    if adaptations:
        party.assumptions.append('替补队伍不继承原攻略伤害；首领须免费模拟击杀后才可实战')
    require_event_talent(runner, party)
    return party, order
