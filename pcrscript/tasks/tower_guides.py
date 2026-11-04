"""Public, structured tower phase guides; roster/build data stays in cache."""
from __future__ import annotations
from dataclasses import dataclass, field
from html.parser import HTMLParser
from hashlib import sha256
import json
from itertools import combinations
from pathlib import Path
import re
from urllib.parse import urlparse

import cv2 as cv
import numpy as np
import requests

from ..game_ui.avatars import face_crop, feature
from ..game_ui.screen import normalized
from ..run_session import clock as time

IDENTITY_SOURCE=('https://raw.githubusercontent.com/Expugn/priconne-diff/'
                 '508a0586957d816cd2be77f0e28f32d94b60a362/JP/json/unit_profile.json')

# Localized outfit spellings absent from the archived public JP profile table.
# These are character aliases, independent of any formation or account build.
NAME_ALIASES={'フィオ':'菲欧','ランファ(儀装束)':'兰法(礼服)',
              'チカ(儀装束)':'千歌(礼服)','マホ(ドリームパーク)':'真步(梦想乐园)',
              'アネモネ':'银莲','アオイ(パイロット)':'碧(驾驶员)',
              'ネフィネラ':'涅妃＝涅菈','エリス':'厄里斯','エリス(サマー)':'厄里斯(夏日)'}

PHASE_GOAL_VERSION=6
IDENTITY_VERSION=2


def phase_progress(before,after,phase):
    if before.get('floor')!=after.get('floor'):return False
    first,last=before.get('hp',[]),after.get('hp',[])
    if len(first)!=5 or len(last)!=5:return False
    if phase==1:
        # Normal tower carries partial shadow damage across parties too.
        return (any(first[:4]) and all(b<=a+2 for a,b in zip(first[:4],last[:4]))
                and (not any(last[:4]) or sum(first[:4])-sum(last[:4])>=10))
    return not any(first[:4]+last[:4]) and last[4]<first[4]


def with_support_trials(plans,roles,*,prefer=False):
    result=[]
    for plan in plans:
        if plan['phase']!=1:
            result.append(plan)
            continue
        front=min(plan['names'],key=lambda n:roles.get(n,{}).get('position',10**9))
        required=[n for n,m in zip(plan['names'],plan.get('members',[])) if m.get('unique_level',0)>0]
        names=required+[n for n in plan['names'] if n!=front and (roles.get(n,{}).get('role')==6
               or roles.get(n,{}).get('heal'))]+[front]
        names=list(dict.fromkeys(names))
        variants=[dict(plan,support=name) for name in names[:2]]
        result.extend(variants+[plan] if prefer else [plan]+variants)
    return result


def with_shadow_followups(plans,spent):
    """Try published full-auto parties against residual shadows, without reuse.

    The source's boss damage is not transferred to this trial. It must pass
    the current shadow goal from the account's actual starting state.
    """
    if not spent:return plans
    extra=[dict(p,phase=1,goal='shadows',source_phase=p['phase'],
                trial_reason='公开全自动队伍的残血影子免费试验')
           for p in plans if p['phase']==2 and not p.get('support')]
    phase_one=[p for p in plans if p['phase']==1]+extra
    phase_one.sort(key=lambda p:(len((set(p['names'])-{p.get('support')})&set(spent)),
                                max(m.get('rank',1000) for m in p.get('members',[{}]))))
    return phase_one+[p for p in plans if p['phase']!=1]


def prefer_untried(plans,failures):
    """An expired failure may retry, after parties not yet simulated here."""
    def failed(plan):
        return any(set(plan['names'])==set(f.get('names',[]))
                   and plan.get('support')==f.get('support')
                   and (f.get('instant') is None or plan['instant']==f['instant']) for f in failures)
    return sorted(plans,key=failed)


def prefer_proven(plans,battles):
    """Teams whose real knife lowered the boss go first; new guides only get what is left of the run."""
    best={}
    for battle in battles:
        if not isinstance(battle.get('before'),dict) or not isinstance(battle.get('after'),dict):continue
        before,after=battle['before'].get('hp',[]),battle['after'].get('hp',[])
        if (battle.get('simulate') is False and len(before)==5 and len(after)==5 and after[4]<before[4]):
            key=frozenset(battle.get('names',[]))
            best[key]=max(best.get(key,0),before[4]-after[4])
    return sorted(plans,key=lambda plan:-best.get(frozenset(plan['names']),0))


def remembered_trials(winners,phase):
    """Reuse real ordinary-floor winners as free boss trials, not win proofs."""
    if phase not in (2,3):return []
    plans=[]
    for winner in winners[:12]:
        names=winner.get('names',[]);instant=winner.get('instant',{})
        if (not isinstance(names,list) or not isinstance(instant,dict)
                or any(not isinstance(n,str) or n.startswith(('slot:','unit:')) for n in names)
                or winner.get('outcome')!='win' or winner.get('auto') is not True or len(names)!=5
                or len(set(names))!=5 or set(instant)!=set(names)
                or any(type(v) is not bool for v in instant.values())):continue
        plans.append(dict(phase=phase,goal='boss_damage',names=names,instant=instant,stars={},
            source=winner.get('source','此前普通楼层实战队伍'),
            trial_reason='此前普通楼层实战获胜队伍的本层免费试验'))
        if not all(instant.values()):
            plans.append(dict(plans[-1],instant={n:True for n in names},
                trial_reason='同五人全部即时发动的本账号免费试验'))
    return plans


def trial_key(plan,target):
    return (json.dumps(target,sort_keys=True),tuple(sorted(plan['names'])),plan.get('support'),
            tuple(sorted(plan['instant'].items())))


def with_tank_trials(plans,roles,talents):
    """Keep the four-role core; a local trial must still pass the free goal."""
    result=[]
    for plan in plans:
        result.append(plan)
        if plan['phase']!=1 or plan.get('support'):continue
        front=min(plan['names'],key=lambda n:roles.get(n,{}).get('position',10**9))
        prior=roles.get(front,{})
        if prior.get('role')!=7 or front not in talents:continue
        available=[n for n,r in roles.items() if n not in plan['names'] and r.get('role')==7
                   and talents.get(n)==talents[front] and r.get('position',10**9)<=prior['position']]
        available.sort(key=lambda n:(not roles[n].get('tank'),roles[n]['position']))
        for name in available[:2]:
            names=[name if n==front else n for n in plan['names']]
            instant={n:plan['instant'][n] for n in plan['names'] if n!=front};instant[name]=True
            result.append(dict(plan,names=names,instant=instant,
                trial_reason='同属性前排替换的本账号免费试验',outgoing=front,incoming=name))
    return result


def declared_identity(label, profiles, manifest):
    """Resolve a published outfit name by common unit ID across regions."""
    label=normalized(label)
    if alias:=NAME_ALIASES.get(label):
        names={a['name'] for a in manifest.get('assets',[]) if normalized(a['name'])==normalized(alias)}
        if len(names)==1:return next(iter(names))
    exact=[p for p in profiles if normalized(p['unit_name'])==label]
    if not exact:
        base,_,suffix=label.partition('(')
        exact=[p for p in profiles if normalized(p['unit_name']).partition('(')[0].startswith(base)
               and normalized(p['unit_name']).partition('(')[2]==suffix and len(base)>=3]
    ids={int(p['unit_id'])//100 for p in exact}
    names={a['name'] for a in manifest.get('assets',[]) if int(a['icon_id'])//100 in ids}
    return next(iter(names)) if len(names)==1 and len(ids)==1 else None


def carried_boss_hp(battles,target):
    """Use a settled real knife's final HUD only on its unchanged map."""
    if not battles:return None
    last=battles[-1]
    if last.get('after')!=target or last.get('simulate') is not False:return None
    final=[s for s in last.get('hp_samples',[]) if s['seconds']<=2 and s['hp']>=100000]
    return final[-1]['hp'] if final else None


def bar_hp(pixels):
    """Boss HP a map bar of this length stands for.

    Fitted on CN 960x540 real knives (bar 55-91px against settled HUD HP of a
    1e9 boss); the bar's fill starts about 8px in, so 50% is near 49px.
    """
    return int((pixels*11.98-92.1)*1000000)


def boss_hp_floor(target):
    """Lowest boss HP the map bar can stand for; a HUD read after a heal cannot exceed it.

    Each fitted point sits 12-20M above this bound.
    """
    hp=(target or {}).get('hp',[])
    if len(hp)!=5 or type(hp[4]) is not int or not 0<hp[4]<=91:return None
    return max(0,bar_hp(hp[4]-1)-5000000)


def top_phase(target):
    """1 while shadows live, then 2 or 3 at the boss's 50% mark read from the map bar."""
    hp=target['hp']
    if any(hp[:4]):return 1
    return 3 if bar_hp(hp[4])<500000000 else 2


class PhaseTrace:
    """Use sustained HUD readings, never temporary damage before a boss heal."""
    def __init__(self, goal, target=None, *, initial_hp=None):
        self.goal=goal
        self.initial_hp=initial_hp
        self.map_floor=boss_hp_floor(target)
        self.samples=[]
        self.shadow_samples=[]
        alive=[hp/91 for hp in (target or {}).get('hp',[91]*5)[:4] if hp>0]
        self.shadow_baselines=sorted((1-hp for hp in alive),reverse=True)
        self.shadow_missing=sum(1-hp for hp in alive)
        self.shadow_goal=sum(alive)*.25

    def shadow_gain(self,sample):
        bars=sample.get('bars',[])
        if not 0<len(bars)<=len(self.shadow_baselines):return float('-inf')
        if any(not 0<=b.get('fill',-1)<=1 for b in bars):return float('-inf')
        # Identity may be obscured. Subtract the greatest possible preexisting
        # damage for just the visible subset, not damage on hidden enemies.
        return sum(1-b['fill'] for b in bars)-sum(self.shadow_baselines[:len(bars)])

    def observe(self, screen):
        if not screen.find('菜单',(840,0,960,65),exact=True):return
        timer=screen.find(r'\d:\d{2}',(750,0,850,55),exact=True)
        if not timer or timer.score<.98:return
        minute,second=map(int,normalized(timer.text).split(':'))
        if second>=60 or minute*60+second>90:return
        if self.goal=='shadows':
            from ..game_ui.tower import shadow_bars
            bars=shadow_bars(screen)
            if bars:
                self.shadow_samples.append(dict(seconds=minute*60+second,bars=bars,
                    net_missing=self.shadow_gain(dict(bars=bars))))
        hp=screen.find(r'[\d,]+/[\d,]+',(460,30,730,70),exact=True)
        if not hp or hp.score<.98:return
        current,maximum=map(int,normalized(hp.text).replace(',','').split('/'))
        if maximum!=1000000000 or not 0<=current<=maximum:return
        # Short fragments such as "95/1000000000" can survive OCR at high
        # confidence. A genuine finishing kill is established by its WIN.
        if current<100000:return
        self.samples.append(dict(seconds=minute*60+second,hp=current))

    def passed(self, *, won=False, settled=False):
        if won:return True
        if self.goal=='shadows':
            # A quarter of total shadow HP is useful even while immunity keeps
            # the boss full. Only visible bars contribute; hidden ones add zero.
            # A clean late frame already contains independent bordered bars;
            # requiring several animation-free OCR frames rejects real damage.
            late=[s for s in self.shadow_samples if s['seconds']<=15]
            if late and self.shadow_gain(late[-1])>=self.shadow_goal>0:return True
        if not self.samples:return False
        start=self.initial_hp
        if start is None:
            # The first HUD frame may already follow a heal; the map bar bounds the real start.
            start=self.samples[0]['hp']
            if self.map_floor is not None:start=min(start,self.map_floor)
        if self.goal=='shadows':
            # The phase-one immunity cannot lose 1% to one-point chip hits.
            return sum(s['hp']<=start-10000000 for s in self.samples)>=3
        if settled and self.samples[-1]['seconds']<=2:
            return self.samples[-1]['hp']<=start-10000000
        late=[s['hp'] for s in self.samples if s['seconds']<=8]
        if len(late)>=3 and max(late[-3:])<=start-10000000:return True
        # Slow/paused OCR can yield only two readings after the final heal.
        # A completed battle's two independent final-second observations are
        # sufficient; an earlier temporary dip is still not a phase proof.
        final=[s for s in self.samples if s['seconds']<=2]
        return (len(final)>=2 and final[-1]['seconds']<=1
                and final[-2]['hp']<start and final[-1]['hp']<=final[-2]['hp']
                and final[-1]['hp']<=start-10000000)


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def text(self):
        if self.tag in ('script','style','noscript'): return ''
        return ''.join(c.text() if isinstance(c,Node) else c for c in self.children)


class Document(HTMLParser):
    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.root=Node('root');self.stack=[self.root]
        self.feed(content)

    def handle_starttag(self,tag,attrs):
        node=Node(tag,dict(attrs));self.stack[-1].children.append(node)
        if tag not in ('img','br','hr','meta','link','input','source','wbr'):self.stack.append(node)

    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag:
                del self.stack[i:];break

    def handle_data(self,value):self.stack[-1].children.append(value)


def parse_guides(content, floor):
    """Accept five explicit switches; never infer switches from a role score."""
    plans=[];scope=False;phase=None;heading='';era='';latest=None;below_half=False
    for node in Document(content).root.walk():
        text=normalized(node.text())
        if node.tag=='h2':
            scope=bool(re.search(r'頂上\('+str(floor)+r'階\).*編成例',text))
            era=text;phase=None;heading='';latest=None;below_half=False
        elif node.tag=='h3' and scope:
            found=re.search(r'(?:フェーズ([123])|([123])編成目)',text)
            phase=int(next(x for x in found.groups() if x)) if found else phase
            heading='';latest=None;below_half=False
        elif node.tag=='p' and scope and phase==2 and re.search(
                r'掲載編成はボスHP50[%％]以下からでも削り可能',text):
            below_half=True
        elif node.tag=='h4' and scope:heading=text;latest=None
        elif node.tag=='table' and scope and phase and 'フルオート' in heading:
            if '代用キャラ例' in text and latest:
                plans.extend(parse_substitutions(node,latest))
                continue
            cells=[n for n in node.walk() if n.tag=='td']
            if len(cells)!=5:continue
            members=[]
            for cell in cells:
                icons=[n for n in cell.walk() if n.tag=='img' and '/pricone-re/gacha/' in n.attrs.get('data-original','')
                       and int(re.sub(r'\D','',n.attrs.get('width','0')) or 0)>=50]
                if len(icons)!=1:break
                icon=icons[0];parts=[];segment=''
                for child in cell.children:
                    if isinstance(child,Node) and child.tag=='hr':parts.append(normalized(segment));segment=''
                    else:segment+=child.text() if isinstance(child,Node) else child
                parts.append(normalized(segment))
                on=any(p in ('SET','即発動') for p in parts)
                if not on and '-' not in parts:break
                rank=re.search(r'ランク(\d+)',cell.text())
                stars=re.search(r'星([1-6])',normalized(cell.text()))
                unique=re.search(r'専用:(\d+)',normalized(cell.text()))
                title=re.match(r'(.+?)星[1-6]',normalized(cell.text()))
                label=title[1] if title else icon.attrs.get('alt','')
                label=label.replace('(限界突破)','')
                for prefix,suffix in (('水着','サマー'),('正月','ニューイヤー')):
                    if label.startswith(prefix):label=label[len(prefix):]+'('+suffix+')'
                if not label:label=icon.attrs.get('alt','')
                members.append(dict(label=label,icon=icon.attrs['data-original'],
                                    instant=on,rank=int(rank[1]) if rank else 1000,
                                    stars=int(stars[1]) if stars else None,
                                    unique_level=int(unique[1]) if unique else 0))
            if len(members)==5 and len({m['label'] for m in members})==5:
                latest=dict(phase=phase,title=heading,era=era,members=members,
                            below_half=below_half,
                            goal='shadows' if phase==1 else 'boss_damage')
                plans.append(latest)
    plans += [dict(p,phase=3) for p in plans if p['phase']==2 and p.get('below_half')]
    return sorted(plans,key=lambda p:(max(m['rank'] for m in p['members']),p['phase']))


def parse_substitutions(table,base):
    """Only explicit one-role replacements with complete SET instructions."""
    def label(value):
        value=normalized(value).replace('(限界突破)','')
        value=re.split(r'(?:コネクト|ランク|専用):?',value,maxsplit=1)[0]
        value=re.sub(r'\(\)$','',value)
        for prefix,suffix in (('水着','サマー'),('正月','ニューイヤー')):
            if value.startswith(prefix):value=value[len(prefix):]+'('+suffix+')'
        return value
    def unique(term,members):
        term=label(term)
        found=[i for i,m in enumerate(members) if m['label']==term]
        if not found and '(' not in term:
            found=[i for i,m in enumerate(members) if m['label'].split('(')[0]==term]
        return found[0] if len(found)==1 else None
    result=[]
    for row in (n for n in table.walk() if n.tag=='tr'):
        cells=[n for n in row.children if isinstance(n,Node) and n.tag in ('th','td')]
        if len(cells)!=2:continue
        icons=[n for n in cells[0].walk() if n.tag=='img'
               and '/pricone-re/gacha/' in n.attrs.get('data-original','')]
        text=normalized(cells[1].text())
        if len(icons)!=1 or 'と代用可能' not in text or re.search(r'\d:\d{2}|手動',text):continue
        prefix=text.split('と代用可能')[0]
        targets=re.sub(r'^陣形:(?:前衛|中衛|後衛)','',prefix).split('/')
        allowed={i for t in targets if (i:=unique(t,base['members'])) is not None}
        for instruction in text.split('・')[1:]:
            match=re.match(r'(.+?)と入れ替え時[、,](.+)',instruction)
            selected=[unique(match[1],base['members'])] if match else list(allowed)
            control=match[2] if match else instruction
            excluded=re.match(r'(.+?)以外(?:SET|即発動)',control)
            if not excluded and not re.match(r'(?:全員|全て|全)(?:SET|即発動)',control):continue
            for outgoing in selected:
                if outgoing not in allowed:continue
                members=[dict(m) for m in base['members']]
                members[outgoing]=dict(label=label(cells[0].text()),icon=icons[0].attrs['data-original'],
                    rank=0,stars=None,unique_level=0,instant=True)
                off=[unique(t,members) for t in excluded[1].split('/')] if excluded else []
                if any(i is None for i in off) or len({m['label'] for m in members})!=5:continue
                for i,m in enumerate(members):m['instant']=i not in off
                result.append(dict(base,members=members,trial_reason='公开攻略明确替代队伍的免费模拟'))
    singles=list(result)
    for first,second in combinations(singles,2):
        if len(result)>=24:break
        a={i:m for i,m in enumerate(first['members']) if m['label']!=base['members'][i]['label']}
        b={i:m for i,m in enumerate(second['members']) if m['label']!=base['members'][i]['label']}
        if not a or not b or a.keys()&b.keys():continue
        if [m['instant'] for m in first['members']]!=[m['instant'] for m in second['members']]:continue
        members=[dict(m) for m in first['members']]
        for i,m in b.items():members[i]=dict(m)
        if len({m['label'] for m in members})!=5:continue
        result.append(dict(base,members=members,
            trial_reason='公开单人替代组合的本账号免费试验'))
    return result


def recognize_icon(image, avatars, manifest):
    """Geometrically verify a cropped public icon, including different frames."""
    h,w=image.shape[:2]
    scores=avatars.matrix@feature(face_crop(image,(0,0,w,h)))
    candidates=[]
    for i in np.argsort(scores)[::-1]:
        name=str(avatars.names[i])
        if name not in candidates and not name.startswith('unit:'):candidates.append(name)
        if len(candidates)==20:break
    sift=cv.SIFT_create()
    # Levels, stars and equipment badges belong to the UI, not the outfit.
    # Their coincidental matches can spoil a genuine portrait's homography.
    artwork=np.zeros((h,w),np.uint8)
    artwork[round(h*.22):round(h*.79),round(w*.05):round(w*.95)]=255
    points,descriptors=sift.detectAndCompute(cv.cvtColor(image,cv.COLOR_BGR2GRAY),artwork)
    if descriptors is None:return None
    matched=set()
    for asset in manifest.get('assets',[]):
        if asset['name'] not in candidates:continue
        path=avatars.path/'icons'/(str(asset['icon_id'])+'.webp')
        if not path.exists():continue
        raw=path.read_bytes()
        if sha256(raw).hexdigest()!=asset.get('sha256'):continue
        reference=cv.imdecode(np.frombuffer(raw,np.uint8),cv.IMREAD_COLOR)
        if reference is None:continue
        rp,rd=sift.detectAndCompute(cv.cvtColor(reference,cv.COLOR_BGR2GRAY),None)
        if rd is None or len(rd)<2:continue
        pairs=cv.BFMatcher().knnMatch(descriptors,rd,k=2)
        good=[pair[0] for pair in pairs if len(pair)==2 and pair[0].distance<.65*pair[1].distance]
        if len(good)<12:continue
        src=np.float32([rp[m.trainIdx].pt for m in good]);dst=np.float32([points[m.queryIdx].pt for m in good])
        transform,inliers=cv.findHomography(src,dst,cv.RANSAC,2)
        if transform is None or inliers is None or int(inliers.sum())<12 or float(inliers.mean())<.9:continue
        extent=np.ptp(dst[inliers[:,0].astype(bool)],axis=0)
        if float(extent[0]*extent[1])<w*h*.15:continue
        rh,rw=reference.shape[:2]
        corners=cv.perspectiveTransform(np.float32([[[0,0],[rw,0],[rw,rh],[0,rh]]]),transform)[0]
        if (not np.isfinite(corners).all() or not cv.isContourConvex(corners)
                or not .3*w*h<cv.contourArea(corners)<2*w*h):continue
        matched.add(asset['name'])
    return next(iter(matched)) if len(matched)==1 else None


def load_guides(options,floor,avatars,manifest,*,check=lambda:None,http=requests):
    urls=options.get('guide_urls', ['https://gamewith.jp/pricone-re/article/show/523902'] if floor==780 else [])
    if not isinstance(urls,list) or len(urls)>8:raise ValueError('LunaTower.guide_urls必须为最多8个来源')
    if not urls:return []
    root=Path(options.get('guide_cache','cache/game/strategies/tower_guides'));root.mkdir(parents=True,exist_ok=True)
    def fetch(url, image=False):
        host=urlparse(url).hostname
        if urlparse(url).scheme!='https' or (host not in ('gamewith.jp','img.gamewith.jp') and url!=IDENTITY_SOURCE):
            raise ValueError('露娜塔阶段攻略仅支持已识别的GameWith页面及图标域名')
        path=root/(sha256(url.encode()).hexdigest()+('.img' if image else '.html'))
        check()
        if path.exists() and 0<=time.time()-path.stat().st_mtime<86400:return path.read_bytes()
        response=http.get(url,timeout=25);response.raise_for_status()
        if len(response.content)>5*1024*1024:raise ValueError('阶段攻略响应过大')
        check();path.write_bytes(response.content);return response.content
    profiles=json.loads(fetch(IDENTITY_SOURCE)).get('unit_profile',[])
    plans=[];seen=set()
    for url in urls:
        for plan in parse_guides(fetch(url).decode('utf-8'),floor):
            names=[]
            for member in plan['members']:
                image=cv.imdecode(np.frombuffer(fetch(member['icon'],True),np.uint8),cv.IMREAD_COLOR)
                if image is None:break
                name=declared_identity(member['label'],profiles,manifest) or recognize_icon(image,avatars,manifest)
                if not name:break
                names.append(normalized(name))
            if len(names)!=5 or len(set(names))!=5:continue
            plan.update(source=url,names=names,instant={n:m['instant'] for n,m in zip(names,plan['members'])})
            plan['stars']={n:m['stars'] for n,m in zip(names,plan['members'])}
            key=(plan['phase'],plan['goal'],trial_key(plan,None))
            if key in seen:continue
            seen.add(key)
            plans.append(plan)
    return plans
