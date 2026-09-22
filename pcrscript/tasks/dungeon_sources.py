"""Anonymous guide discovery. Candidate sources are never executable parties."""
from __future__ import annotations
import hashlib
import html
import json
import re
import requests
from pathlib import Path
from typing import Any
from ..extras.bilibili_api import BilibiliApi
from ..run_session import clock as time

PARSER_VERSION = 2

def clean(value: Any) -> str:
    return html.unescape(re.sub(r'<[^>]*>', '', str(value or ''))).strip()

def relevant(text: str, terms: list[str]) -> bool:
    return any(re.search(r'(?<![a-z0-9])'+re.escape(term)+r'(?![a-z0-9])', text, re.I)
               if term.isascii() else term.casefold() in text.casefold() for term in terms)

def discover_sources(options: dict, *, api=None) -> dict:
    area = str(options.get('area', '四彩的灵峰')).strip()
    aliases = options.get('aliases', ['极难7', 'EX7'] if area == '四彩的灵峰' else [])
    if not area or not isinstance(aliases, list) or any(not isinstance(a,str) or not a.strip() for a in aliases):
        raise ValueError('area和aliases必须是明确的地下城名称/别名')
    terms = list(dict.fromkeys([area]+aliases))
    region = options.get('region', 'cn')
    if region not in ('cn', 'jp'):
        raise ValueError('region应为cn或jp')
    limit = options.get('max_videos', 8)
    ttl = options.get('max_age_hours', 24)
    if type(limit) is not int or not 1 <= limit <= 30 or not isinstance(ttl,(int,float)) or not 0 <= ttl <= 720:
        raise ValueError('max_videos应为1–30，max_age_hours应为0–720')
    queries = ['公主连结 '+t+' 攻略' for t in terms[:3]]
    scope = dict(area=area,terms=terms,region=region,max_videos=limit,queries=queries)
    key = hashlib.sha256(json.dumps(scope,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    path = Path(options.get('cache_dir','cache/game/strategies/sources'))/(key+'.json')
    now = time.time()
    cached = None
    try:
        cached = json.loads(path.read_text(encoding='utf-8'))
        if (isinstance(cached,dict) and cached.get('parser_version') == PARSER_VERSION and cached.get('scope') == scope
                and cached.get('status') == 'complete' and cached.get('candidates')
                and 0 <= now-cached.get('fetched_at',0) < ttl*3600):
            return dict(cached,cache_hit=True,catalog=str(path))
    except (OSError,ValueError,TypeError):
        pass
    api = api or BilibiliApi(timeout=options.get('request_timeout',12))
    found = {}
    errors = []
    for query in queries:
        try:
            result = api.search(query)
            if result.get('code') != 0:
                raise ValueError('搜索接口code='+str(result.get('code')))
            groups = result.get('data',{}).get('result')
            if not isinstance(groups,list):
                raise ValueError('搜索结构变化')
            for group in groups:
                if group.get('result_type') != 'video': continue
                for item in group.get('data',[]):
                    bvid = item.get('bvid','')
                    text = clean(item.get('title'))+' '+clean(item.get('description'))+' '+clean(item.get('tag'))
                    if not re.fullmatch(r'BV[0-9A-Za-z]{10}',bvid) or not relevant(text,terms): continue
                    if bvid not in found: found[bvid] = dict(item,queries=[])
                    found[bvid]['queries'].append(query)
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            # Public responses/errors only; no login credential is accessed.
            errors.append(dict(stage='search',query=query,error=type(error).__name__+': '+str(error)[:240]))
    candidates = []
    excluded = []
    # Newer guides first, but date/popularity never proves build compatibility.
    items = sorted(found.items(),key=lambda pair:int(str(pair[1].get('pubdate') or 0)) if str(pair[1].get('pubdate') or 0).isdigit() else 0,reverse=True)
    for bvid,item in items[:limit*2]:
        if len(candidates) >= limit: break
        try:
            response = api.getVideoInfo(bvid=bvid)
            data = response.get('data',{})
            if response.get('code') != 0 or data.get('bvid') != bvid:
                raise ValueError('公开视频身份核验失败')
            title,description = clean(data.get('title')),clean(data.get('desc'))
            if not re.search(r'公主连[结接]|公主連[結接]|プリコネ|princess\s*connect|\bpcr\b', title+' '+description, re.I):
                excluded.append(dict(bvid=bvid,reason='视频详情没有确认公主连结游戏身份'))
                continue
            pages = [dict(cid=p.get('cid'),page=p.get('page'),title=clean(p.get('part')),duration=p.get('duration'))
                     for p in data.get('pages',[]) if isinstance(p,dict)]
            if not relevant(title+' '+description+' '+' '.join(p['title'] for p in pages),terms):
                raise ValueError('视频详情与目标地下城不匹配')
            explicit_cn = '国服' in title+' '+description
            explicit_jp = '日服' in title+' '+description
            actual_region = 'cn' if explicit_cn and not explicit_jp else 'jp' if explicit_jp and not explicit_cn else 'unknown'
            if actual_region not in (region,'unknown'):
                excluded.append(dict(bvid=bvid,reason='视频明确服区与目标不符',region=actual_region))
                continue
            candidates.append(dict(bvid=bvid,url=f'https://www.bilibili.com/video/{bvid}/',title=title,
                description=description,author=clean(data.get('owner',{}).get('name')),published_at=data.get('pubdate'),
                pages=pages,matched_queries=item['queries'],verified_at=time.time(),identity_verified=True,
                region=actual_region,
                readiness='source_only',pending=(['视频服区未明确，需核验'] if actual_region == 'unknown' else [])+['需解析逐队衣装、培养开关、SET和阶段，再核验账号与跨队占用']))
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            errors.append(dict(stage='metadata',bvid=bvid,error=type(error).__name__+': '+str(error)[:240]))
    report = dict(status='complete' if candidates and not errors else 'partial' if candidates else 'blocked',
                  parser_version=PARSER_VERSION,scope=scope,fetched_at=now,cache_hit=False,catalog=str(path),
                  candidates=candidates,excluded=excluded,errors=errors,pending=[])
    if not candidates: report['pending'].append('没有获得经视频详情核验的目标攻略来源；未生成战斗队伍')
    if errors: report['pending'].append('部分来源请求或详情核验失败，见errors；未把失败当作没有攻略')
    path.parent.mkdir(parents=True,exist_ok=True)
    if isinstance(cached,dict) and cached.get('status') == 'complete' and report['status'] != 'complete':
        backup=path.with_suffix('.last-good.json')
        backup.write_text(json.dumps(cached,ensure_ascii=False,indent=2),encoding='utf-8')
        report['previous_catalog']=str(backup)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
    return report
