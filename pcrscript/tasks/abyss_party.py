"""Current-account trials, explicitly distinct from source-backed strategies."""
from dataclasses import asdict, replace
from pathlib import Path
import shutil
from uuid import uuid4
from .event_formation import EventFormation
from .event_strategy import EventParty, MemberRequirement, readiness
from ..game_ui.screen import normalized
from ..game_ui.avatars import card_rectangles, face_crop
from ..game_ui.abyss import AREAS
from ..game_ui.screen import EventUIError
from .party_variants import character_roles, alternatives
from .abyss_history import team_key
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


class AbyssFormation(EventFormation):
    infer_costume_from_skills = True
    requires_declared_build = False
    # The explicit "scheduled for future release" page cannot turn into an
    # equipped weapon during one uninterrupted game session. Still expire its
    # screenshot proof within the task; every battle rechecks the live card.
    unreleased_proof_seconds = 3600

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
            evidence=str(self.ui.save('abyss_quick_build',s))
            return [replace(a,equipment_evidence=evidence) for a in actual]
        return [replace(a) for a in actual]

    def inspect(self, *args, **kwargs):
        kwargs.setdefault('verify_skills', getattr(self, 'strict_source', False))
        actual=super().inspect(*args, **kwargs)
        proof=getattr(self,'unreleased',{}).get(actual.name)
        if actual.identity_verified and actual.unique is None and proof and 0<=time.time()-proof[0]<self.unreleased_proof_seconds:
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
        label=AREAS[element][1][0]
        self.ui.expect_click(label,(110,65,480,110),exact=True)
        # The middle of a card can treat a long drag as a card action and open
        # the EX-equipment panel. Scroll beside the cards instead.
        for _ in range(3): self.ui.swipe((914,200),(914,340))
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
            rects=card_rectangles(s.image)
            found.update(n for n in self.avatars.query([face_crop(s.image,r) for r in rects]) if n)
            self.ui.save(f'candidate_{element}_{page}',s)
            self.ui.swipe((914,340),(914,200))
        cache[element]=sorted(found)
        self._owned_candidates=cache
        return list(cache[element])

    def alternative_trial(self, stage, audit, failed, *, survival=False, focus=None):
        roles=character_roles()
        available=self.owned_candidates(stage.element)
        choices=alternatives(audit['order'],available,roles,failed,survival=survival,
                             boss=stage.number==10,focus=focus)
        rejected=[]
        for choice in choices:
            if hasattr(self,'check_deadline'):self.check_deadline()
            # Candidate selection checks the current account's build, never
            # infers ownership or unique equipment from downloaded metadata.
            members=[MemberRequirement(n,1,1,1,None,None,True,0) for n in choice['order']]
            candidate=EventParty('本地调整 '+stage.title,'游戏属性筛选与本地技能数据库',members)
            ready,selection=self.select(candidate)
            if not ready:
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

    def source_trial(self,stage,source,*,recover=True):
        if source.get('document'):
            from .strategy_document import to_event_party
            try:
                party = to_event_party(source['document'])
            except ValueError as error:
                return None, dict(source=source, unready=[str(error)])
            self.strict_source = True
            try:
                ready, details = self.select(party)
                details.update(source=source, build_basis='source', observed=[asdict(self.observed[n])
                    for n in source['names'] if n in self.observed])
                return (party if ready else None), details
            finally:
                self.strict_source = False
        current=self.ui.capture(ocr=False)
        identities=self.avatars.query([face_crop(current.image,(x-48,self.slot_top,96,96)) for x,_ in self.slots])
        checked=None
        if None in identities and len(self.occupied_slots(current))==5:
            checked=self.current_trial(stage)
            if len(checked[1].get('order',[]))==5:
                identities=checked[1]['order']
            else:checked=None
        if len(identities)==5 and None not in identities and set(identities)!=set(source['names']):
            missing=list(set(source['names'])-set(identities))
            incoming=list(set(identities)-set(source['names']))
            if len(missing)==len(incoming)==1:
                roles=character_roles()
                old,new=roles.get(missing[0]),roles.get(incoming[0])
                if old and new and all(old[key]==new[key] for key in ('kind','heal','tank')):
                    if checked is None:checked=self.current_trial(stage)
                    if set(checked[1].get('order',[]))==set(identities):
                        index=source['names'].index(missing[0])
                        source.setdefault('original_names',list(source['names']))
                        source['names'][index]=incoming[0]
                        source['required_stars'][index]=None
                        source.setdefault('adaptations',[]).append(dict(missing=missing[0],replacement=incoming[0],
                            reason='复用已保存的一名同属性、同攻击类型及生存职能替补，当前账号重新核验'))
        candidate=EventParty('用户攻略成员 '+stage.title,source['source'],
                             [MemberRequirement(n,1,1,1,None,None,True,0) for n in source['names']])
        if None in identities or set(identities)!=set(source['names']):
            ready,details=self.select(candidate)
            if not ready:
                unresolved=[f['character'] for f in details.get('unready',[]) if any('专武' in r for r in f.get('reasons',[]))]
                missing=[f['character'] for f in details.get('unready',[]) if any('未在搜索结果' in r for r in f.get('reasons',[]))]
                if unresolved and recover and hasattr(self,'recover_equipment'):
                    # One character-page visit can establish every unreleased
                    # weapon in this team. Auditing only the first unknown here
                    # can repeatedly rebuild and inspect the same five cards.
                    self.recover_equipment(stage,[n for n in source['names'] if n not in missing])
                    return self.source_trial(stage,source,recover=False)
                if missing and recover and not unresolved:
                    return self.adapt_source(stage,source,missing)
                # Equipment recovery is independent of a missing member.
                if missing and not unresolved:
                    return self.adapt_source(stage,source,missing)
                return None,dict(source=source,selection=details,unready=['来源阵容成员未确认'])
        party,audit=checked if checked is not None else self.current_trial(stage)
        audit['source']=source
        if party is None and recover and hasattr(self,'recover_equipment'):
            unresolved=[f['character'] for f in audit.get('unready',[]) if f.get('character')
                        and any('专武' in r for r in f.get('reasons',[]))]
            if unresolved:
                self.recover_equipment(stage,source['names'])
                return self.source_trial(stage,source,recover=False)
        if party:
            settings=dict(zip(source['names'],source['instant']))
            for member in party.members:member.instant=settings[member.name]
            observed={a['name']:a for a in audit['observed']}
            mismatches=[n for n,star in zip(source['names'],source['required_stars'])
                        if star==6 and observed[n]['stars']!=6]
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
        return self.source_trial(stage,source,recover=False)

    def current_trial(self, stage):
        screen = self.ui.capture()
        if len(self.occupied_slots(screen)) != 5:
            return None, {'unready': ['当前保存队伍不是五人，未猜测补员']}
        actual = self.inspect_current(full=True, verify_skills=False)
        archive = archive_observations(actual, self.ui.output, stage.element+'_'+stage.key)
        members = [MemberRequirement(a.name, max(a.level or 1, 1), max(a.rank or 1, 1),
                   a.stars or 1, a.unique, a.unique2, True, 0) for a in actual]
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
