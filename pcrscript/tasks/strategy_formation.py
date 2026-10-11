"""Current-account trials, explicitly distinct from source-backed strategies."""
from dataclasses import asdict, dataclass, replace
from pathlib import Path
import shutil
from uuid import uuid4
from .event_formation import EventFormation
from .event_strategy import EventParty, MemberRequirement, readiness, team_key
from ..game_ui.screen import normalized
from ..game_ui.avatars import candidate_card_rectangles, face_crop
from ..game_ui.screen import EventUIError
from .party_variants import character_roles, alternatives
from ..run_session import clock as time


def archive_observations(actual, output: Path, label: str) -> Path:
    """A later audit must not overwrite evidence referenced by old battles."""
    directory = output/'audits'/(label+'_'+uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=True)
    for status in actual:
        for field in ('evidence', 'equipment_evidence'):
            original = Path(getattr(status, field))
            if not original.is_file():
                continue
            target = directory/original.name
            shutil.copyfile(original, target)
            sidecar = original.with_suffix('.json')
            if sidecar.exists():
                shutil.copyfile(sidecar, target.with_suffix('.json'))
            setattr(status, field, str(target))
    return directory


@dataclass(frozen=True)
class StrategyTarget:
    element: str
    key: str
    title: str
    is_boss: bool = False


class StrategyFormation(EventFormation):
    infer_costume_from_skills = True
    requires_declared_build = False
    # The explicit "scheduled for future release" page cannot turn into an
    # equipped weapon during one uninterrupted game session. Still expire its
    # screenshot proof within the task; every battle rechecks the live card.
    unreleased_proof_seconds = 3600
    allow_substitutions = True

    def inspect_current(self,*args,**kwargs):
        kwargs.setdefault('verify_skills',False)
        full=kwargs.get('full',args[0] if args else True)
        expected=kwargs.get('expected_names',args[1] if len(args)>1 else ())
        if not kwargs['verify_skills']:
            cached=self.quick_current(full=full,expected_names=expected)
            if cached is not None:
                return cached
        return super().inspect_current(*args,**kwargs)

    def quick_current(self,*,full,expected_names):
        """Reuse recent detail audits after verifying the live five-card roster."""
        s=self.ui.capture(ocr=False)
        if len(self.occupied_slots(s))!=5:return None
        rects=[(x-48,self.slot_top,96,96) for x,_ in self.slots]
        names=self.avatars.query([face_crop(s.image,r) for r in rects])
        if None in names or len(set(names))!=5:return None
        if expected_names and set(names)!=set(expected_names):return None
        actual=[self.observed.get(n) for n in names]
        if any(a is None or not a.identity_verified or a.observed_at is None
               or not 0<=time.time()-a.observed_at<self.unreleased_proof_seconds for a in actual):return None
        if full:
            confirmed=[None]*5;repeats=[0]*5
            for _ in range(12):
                s=self.ui.capture(ocr=False)
                for i,rect in enumerate(rects):
                    result=self.badges.read(s.image,rect)
                    repeats[i]=repeats[i]+1 if result is not None and result==confirmed[i] else int(result is not None)
                    if result is not None:confirmed[i]=result
                if all(count>=2 or (confirmed[i] is None and names[i] in getattr(self,'unreleased',{}))
                       for i,count in enumerate(repeats)):
                    break
                time.sleep(.45)
            for i,a in enumerate(actual):
                badge=confirmed[i] if repeats[i]>=2 else None
                if badge is None:
                    proof=getattr(self,'unreleased',{}).get(names[i])
                    if not proof or not 0<=time.time()-proof[0]<self.unreleased_proof_seconds:
                        return None
                    badge=(False,False)
                if badge!=(a.unique,a.unique2):return None
            evidence=str(self.ui.save('strategy_quick_build',s))
            return [replace(a,equipment_evidence=evidence) for a in actual]
        return [replace(a) for a in actual]

    def inspect(self, *args, **kwargs):
        kwargs.setdefault('verify_skills', getattr(self, 'strict_source', False))
        actual=super().inspect(*args, **kwargs)
        proof=getattr(self,'unreleased',{}).get(actual.name)
        if actual.identity_verified and actual.unique is None and actual.unique2 is None and proof and 0<=time.time()-proof[0]<self.unreleased_proof_seconds:
            actual.unique=actual.unique2=False;actual.equipment_evidence=proof[1]
        return actual

    def resolve_requirement(self, requirement, actual):
        if getattr(self, 'strict_source', False):
            return requirement
        return MemberRequirement(requirement.name, max(actual.level or 1,1), max(actual.rank or 1,1),
                                 actual.stars or 1, actual.unique, actual.unique2, True, 0)

    def owned_candidates(self, element):
        """Read only cards actually visible under the game's attribute filter."""
        # This task never acquires characters. Reuse the same attribute's
        # owned roster after a loss instead of scrolling every page again.
        cache=getattr(self,'_owned_candidates',{})
        if element in cache:
            return list(cache[element])
        label={'fire':'火','water':'水','wind':'风','light':'光','dark':'暗'}[element]
        self.ui.expect_click(label,(110,65,480,110),exact=True)
        # Drag the verified thumb toward the start, then toward the end.
        # Content swipe directions are reversed when applied to a scrollbar.
        scrollbar = (912, 124, 923, 361)
        for _ in range(6):
            s = self.ui.capture()
            if not s.find('队伍编组',(300,0,650,70),exact=True):
                raise EventUIError('候选扫描不在编队，未滑动未知页面')
            if not self.ui.scrollbar(s, scrollbar, -1):
                break
        found=set(); previous=None
        import cv2 as cv
        recovered_panel=False
        for page in range(12):
            s=self.ui.capture()
            if s.find('特别装备设定',(320,15,650,65),exact=True) and not recovered_panel:
                recovered_panel=True
                self.ui.expect_click('取消',(35,445,265,520),exact=True)
                s=self.ui.wait(lambda frame:frame.find('队伍编组',(300,0,650,70),exact=True),'候选扫描返回编队')
            if not s.find('队伍编组',(300,0,650,70),exact=True):
                raise EventUIError('候选扫描离开编队，未将异常页面当作无候选')
            signature=cv.resize(s.image[115:372,40:905],(48,24)).tobytes()
            if signature==previous:break
            previous=signature
            rects=candidate_card_rectangles(s.image)
            found.update(n for n in self.avatars.query([face_crop(s.image,r) for r in rects]) if n)
            self.ui.save(f'candidate_{element}_{page}',s)
            if not self.ui.scrollbar(s, scrollbar, 1):
                break
        cache[element]=sorted(found)
        self._owned_candidates=cache
        return list(cache[element])

    def alternative_trial(self, stage, audit, failed, *, survival=False, focus=None):
        roles=character_roles()
        available=self.owned_candidates(stage.element)
        choices=alternatives(audit['order'],available,roles,failed,survival=survival,
                             boss=getattr(stage, 'is_boss', getattr(stage, 'number', None)==10),focus=focus)
        rejected=[]
        blocked_incoming={}
        for choice in choices:
            if hasattr(self,'check_deadline'):self.check_deadline()
            prior=blocked_incoming.get(choice['incoming'])
            if prior is not None:
                rejected.append(dict(choice=choice,selection=prior,
                                     reason='同一替补已在本轮核验失败'))
                continue
            # Candidate selection checks the current account's build, never
            # infers ownership or unique equipment from downloaded metadata.
            members=[MemberRequirement(n,1,1,1,None,None,True,0) for n in choice['order']]
            candidate=EventParty('本地调整 '+stage.title,'游戏属性筛选与本地技能数据库',members)
            ready,selection=self.select(candidate)
            if not ready:
                unready=selection.get('unready',[])
                if (unready and not selection.get('errors')
                        and all(isinstance(row,dict)
                                and row.get('character')==choice['incoming'] for row in unready)):
                    blocked_incoming[choice['incoming']]=selection
                rejected.append(dict(choice=choice,selection=selection));continue
            party,current=self.current_trial(stage)
            if party is None:
                rejected.append(dict(choice=choice,audit=current));continue
            before=audit.get('observed',[])
            trained=[a for a in before if a.get('level') and a.get('rank')]
            replacement=next(a for a in current['observed'] if a['name']==choice['incoming'])
            if trained and (replacement['level']<min(a['level'] for a in trained)-10
                            or replacement['rank']<min(a['rank'] for a in trained)-2):
                rejected.append(dict(choice=choice,reason='替补培养明显低于原队，未为凑次数试打',observed=replacement));continue
            if team_key(current['order']) in failed:
                raise EventUIError('换队后仍为失败过的阵容，未开战')
            current.update(adjustment=choice,rejected=rejected,available=available)
            return party,current
        return None,dict(unready=['没有可确认且未试过的同属性替代阵容'],
                         available=available,rejected=rejected,proposals=choices)

    def select_source_members(self, party, *, known_missing=()):
        """Select source identities before their separately declared build is audited."""
        missing = set(map(normalized, known_missing)) & {normalized(m.name) for m in party.members}
        if not missing:
            return self._select_source_party(party)
        # A read-only equipment visit cannot acquire the already missing
        # versions. Refresh the held members without repeating those searches;
        # this partial selection can never authorize combat.
        _, details = self._select_source_party(replace(party, members=[m for m in party.members
                                     if normalized(m.name) not in missing]))
        details['unready'] = list(details.get('unready', [])) + [
            dict(character=m.name, reasons=['未在搜索结果中确认该版本的角色'])
            for m in party.members if normalized(m.name) in missing]
        return False, details

    def _select_source_party(self, party):
        return self.select(party)

    def recover_source_equipment(self, stage, source, names):
        recovered = set(source.get('_equipment_recovered', ()))
        observed = getattr(self, 'observed', {})
        pending = [name for name in names if name not in recovered and (
            observed.get(normalized(name)) is None
            or observed[normalized(name)].unique is None
            or observed[normalized(name)].unique2 is None)]
        if not pending:
            return False
        # A later selection may reveal another unknown. Bound recovery per
        # character instead of exhausting the whole team's chance at once.
        source['_equipment_recovered'] = sorted(recovered | set(pending))
        self.recover_equipment(stage, pending)
        return True

    def source_trial(self,stage,source,*,recover=True):
        if source.get('document'):
            from .party_preparation import audit_declared_build, numeric_equipment_unknown, catalogue_issues
            from .strategy_document import BUILD_FIELDS, to_event_party
            document = source['document']
            if any(member.get(key, {}).get('conflicts') for member in document['members'] for key in BUILD_FIELDS):
                return None, dict(source=source, unready=['来源培养要求存在冲突'])
            declared = [MemberRequirement(m['name'], **{key: m.get(key, {}).get('value')
                        for key in BUILD_FIELDS}) for m in document['members']]
            issues = catalogue_issues(self, declared)
            if issues:
                return None, dict(source=source, unready=issues,
                                  character_database=self.character_database)
            if document.get('readiness') == 'ready':
                try:
                    to_event_party(document)
                except ValueError as error:
                    return None, dict(source=source, unready=[str(error)])
            needs = numeric_equipment_unknown(EventParty('', '', declared), self.observed)
            if needs and recover and hasattr(self, 'recover_equipment'):
                self.numeric_equipment_names = needs
                try:
                    self.recover_equipment(stage, needs)
                finally:
                    self.numeric_equipment_names = ()
            trial = dict(source)
            trial.pop('document')
            trial['instant'] = [flag if type(flag) is bool else True for flag in source['instant']]
            complete = document.get('readiness') == 'ready'
            substitutions = self.allow_substitutions
            if complete:
                self.allow_substitutions = False
            try:
                party, audit = self.source_trial(stage, trial, recover=recover)
            finally:
                self.allow_substitutions = substitutions
            audit.update(source=source, build_basis='source' if complete else 'local_trial_source_roster',
                         assumptions=list(document.get('pending', [])) +
                         [name+'.SET未知，试打暂按开启' for name, flag in
                          zip(source['names'], source['instant']) if type(flag) is not bool])
            if trial.get('adaptations'):
                audit['adaptations'] = trial['adaptations']
            if party and hasattr(self, 'prepare_build'):
                party, audit = self.prepare_build(stage, party, audit)
            if party and not audit_declared_build(self, party, audit, declared):
                return None, audit
            if party:
                party.auto = document.get('auto', {}).get('value', True)
                party.build_basis = 'source' if complete and not trial.get('adaptations') else 'local_trial'
            return party, audit
        current=self.ui.capture(ocr=False)
        identities=self.avatars.query([face_crop(current.image,(x-48,self.slot_top,96,96)) for x,_ in self.slots])
        checked=None
        known = {n for n in identities if n is not None}
        if (None in identities and len(self.occupied_slots(current))==5
                and len(known)==4 and known <= set(source['names'])):
            # Only a four-member source match can justify inspecting the
            # ambiguous fifth saved card. An unrelated saved team will be
            # replaced and must not consume a full five-character audit.
            checked=self.current_trial(stage)
            if len(checked[1].get('order',[]))==5:
                identities=checked[1]['order']
            else:checked=None
        # Returning from equipment inspection can restore an older saved team.
        # Select the intended members; only a confirmed missing identity may
        # trigger adapt_source(), never a mismatch with that saved team.
        candidate=EventParty('用户攻略成员 '+stage.title,source['source'],
                             [MemberRequirement(n,1,1,1,None,None,True,0) for n in source['names']])
        if None in identities or set(identities)!=set(source['names']):
            known_missing = source.get('_known_missing', ())
            ready,details=(self.select_source_members(candidate, known_missing=known_missing)
                           if known_missing else self.select_source_members(candidate))
            if not ready:
                unresolved=[f['character'] for f in details.get('unready',[]) if any('专武' in r for r in f.get('reasons',[]))]
                missing=[f['character'] for f in details.get('unready',[]) if any('未在搜索结果' in r for r in f.get('reasons',[]))]
                if missing and not self.allow_substitutions:
                    return None,dict(source=source,selection=details,unready=['来源阵容缺员，继续其他原阵容候选'])
                if unresolved and recover and hasattr(self,'recover_equipment'):
                    source['_known_missing'] = sorted(set(known_missing) | set(missing))
                    if self.recover_source_equipment(stage,source,[n for n in source['names'] if n not in missing]):
                        return self.source_trial(stage,source)
                # Equipment recovery is independent of a missing member.
                if self.allow_substitutions and missing and not unresolved:
                    return self.adapt_source(stage,source,missing)
                return None,dict(source=source,selection=details,unready=['来源阵容成员未确认'])
            # The preliminary audit described the saved team before select().
            # Never reuse it after the five cards have been replaced.
            checked=None
        party,audit=checked if checked is not None else self.current_trial(stage)
        audit['source']=source
        if party is None and recover and hasattr(self,'recover_equipment'):
            unresolved=[f['character'] for f in audit.get('unready',[]) if f.get('character')
                        and any('专武' in r for r in f.get('reasons',[]))]
            if unresolved and self.recover_source_equipment(stage,source,source['names']):
                return self.source_trial(stage,source)
        if party:
            settings=dict(zip((normalized(name) for name in source['names']),source['instant']))
            if {normalized(member.name) for member in party.members} != set(settings):
                audit['unready']=['选队后的五人身份与来源不一致，未开战']
                return None,audit
            for member in party.members:member.instant=settings[normalized(member.name)]
            observed={normalized(a['name']):a for a in audit['observed']}
            mismatches=[n for n,star in zip(source['names'],source['required_stars'])
                        if star==6 and observed[normalized(n)]['stars']!=6]
            if mismatches:
                audit['unready']=[{'characters':mismatches,'reasons':['来源明确六星，但账号当前状态不一致']}]
                return None,audit
        return party,audit

    def adapt_source(self,stage,source,missing):
        if hasattr(self,'check_deadline'):self.check_deadline()
        roles=character_roles();available=self.owned_candidates(stage.element)
        rejected=set(source.get('unavailable_names',[]))|set(missing)
        adapted=dict(source,names=list(source['names']),required_stars=list(source['required_stars']),
                     original_names=source.get('original_names',source['names']),
                     unavailable_names=sorted(rejected),adaptations=list(source.get('adaptations',[])))
        for name in missing:
            target=roles.get(name)
            if target is None:return None,dict(unready=['缺员且数据库没有替补职能依据'],missing=missing)
            options=[]
            for replacement in available:
                role=roles.get(replacement)
                if replacement in rejected or replacement in adapted['names'] or role is None or role['kind']!=target['kind']:continue
                similarity=100*int(target.get('role') is not None and role.get('role')==target['role'])+40*int(role['heal']==target['heal'])+30*int(role['tank']==target['tank'])
                similarity-=20*abs(role['damage']-target['damage'])
                options.append((similarity,replacement))
            if not options:return None,dict(unready=['缺员且没有同属性同职能替补'],missing=missing,available=available)
            replacement=max(options)[1];i=adapted['names'].index(name);adapted['names'][i]=replacement;adapted['required_stars'][i]=None
            adapted['adaptations'].append(dict(missing=name,replacement=replacement,reason='同属性同攻击类型，按职能/治疗/坦克/输出技能相似度选本地替补'))
        source.update(adapted)
        # New members receive their own bounded equipment recovery.
        return self.source_trial(stage,source)

    def current_trial(self, stage):
        screen = self.ui.capture()
        if len(self.occupied_slots(screen)) != 5:
            return None, {'unready': ['当前保存队伍不是五人，未猜测补员']}
        actual = self.inspect_current(full=True, verify_skills=False)
        archive = archive_observations(actual, self.ui.output, stage.element+'_'+stage.key)
        members = [MemberRequirement(a.name, max(a.level or 1, 1), max(a.rank or 1, 1),
                   a.stars or 1, a.unique, a.unique2, True, 0,
                   unique_level=a.unique_level, unique2_stars=a.unique2_stars) for a in actual]
        failures = [{'character': a.name, 'reasons': readiness(m, a)} for m, a in zip(members, actual)]
        failures = [f for f in failures if f['reasons']]
        order = [normalized(a.name) for a in actual]
        if len(set(order)) != 5:
            failures.append({'reasons': ['成员身份未唯一确认']})
        details = {'build_basis': 'local_trial_current_account', 'stage': stage.title,
                   'observed': [asdict(a) for a in actual], 'order': order, 'unready': failures,
                   'evidence_directory': str(archive)}
        if failures:
            return None, details
        # Actual observations are the trial requirements, never source claims.
        evidence = str(self.ui.save('trial_'+archive.name))
        return EventParty('本地试验 '+stage.title, evidence, members, max_attempts=3), details
