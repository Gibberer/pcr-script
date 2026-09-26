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
from .strategy_inputs import preferred_sources,validate_urls

PARSER_VERSION = 19

MANUAL_PART = re.compile(r'半自动|手动|目押|卡轴|(?:\d+|[一二三四五六七八九十])押|改星|调星|切星|降星|星级变更|TP\s*\+\s*2|大师点', re.I)
UNVERIFIED_SETTING = re.compile(r'TP\s*\+\s*2|大师点', re.I)
ABYSS_ELEMENT_LABELS = {'fire': '火', 'water': '水', 'wind': '风', 'light': '光', 'dark': '暗'}


def abyss_chapter_collection(text: str, stage: str) -> bool:
    """Metadata can nominate a chapter collection for frame-level review."""
    if not re.fullmatch(r'\d+-\d+', stage):
        return False
    chapter = int(stage.split('-')[0])
    return any(int(a) <= chapter <= int(b) for a, b in
               re.findall(r'(?<!\d)(\d+)\s*[-－~～至]\s*(\d+)\s*图', text))


def source_queries(terms: list[str], stage: str, effort: str, *, kind: str,
                   element: str | None = None) -> list[str]:
    queries = ['公主连结 '+term+' '+stage+' 攻略' for term in terms[:3]]
    if stage:
        queries.append('公主连结 '+terms[min(1, len(terms)-1)]+' 攻略')
    if kind == 'abyss' and stage and effort == 'high':
        short = ABYSS_ELEMENT_LABELS.get(element, terms[-1].replace('属性', ''))
        queries.extend([
            f'公主连结 深域 {short} {stage}',
            f'{short}{stage} 全set',
            f'公主连结 {short}深域{stage} 自动 作业',
            f'公主连结 {short}深域{stage} 队伍',
            f'公主连结 深域 {short} {stage} 配队',
            f'公主连结 {terms[0]} 一图流',
            f'公主连结 {short}深域 通关阵容',
            f'公主连结 国服 {short}深域{stage} 最新 自动',
        ])
    return list(dict.fromkeys(queries))


def publication_time(candidate: dict) -> float:
    published = candidate.get('published_at', candidate.get('pubdate'))
    return float(published) if type(published) in (int, float) and published > 0 else 0.0


def abyss_candidate_priority(candidate: dict, stage: str, element: str | None) -> tuple:
    """Prefer exact target scope and recent character pools, then AUTO hints."""
    target = re.compile(r'(?<!\d)'+re.escape(stage)+r'(?!\d)')
    label = ABYSS_ELEMENT_LABELS.get(element)
    targets = [page for page in candidate.get('pages', []) if target.search(page['title'])]
    matched = [page for page in targets if label and label in page['title']]
    unlabeled = [page for page in targets if not any(
        other in page['title'] for other in ABYSS_ELEMENT_LABELS.values())]
    pages = matched or unlabeled
    title = candidate.get('title', '')
    title_scope = bool(target.search(title)) and (bool(label and label in title) or not any(
        other in title for other in ABYSS_ELEMENT_LABELS.values()))
    scoped = bool(pages) or (not targets and title_scope)
    text = candidate.get('title', '')+' '+' '.join(page['title'] for page in pages)
    automatic = bool(re.search(r'全自动|自动|AUTO', text, re.I))
    lengths = [float(page['duration']) for page in pages
               if isinstance(page.get('duration'), (int, float)) and page['duration'] > 0]
    return (not scoped, -publication_time(candidate), not automatic,
            min(lengths, default=float('inf')))


def unusable_abyss_media(pages: list[dict], stage: str, options: dict) -> str | None:
    """Reject a source only when metadata proves every target part unusable."""
    if not pages or not (options.get('skip_manual_media') or options.get('skip_long_media')):
        return None
    target = re.compile(r'(?<!\d)'+re.escape(stage)+r'(?!\d)')
    exact = [page for page in pages if target.search(page['title'])]
    element = options.get('element')
    if exact and element in ABYSS_ELEMENT_LABELS:
        matched = [page for page in exact if ABYSS_ELEMENT_LABELS[element] in page['title']]
        unlabeled = [page for page in exact if not any(
            label in page['title'] for label in ABYSS_ELEMENT_LABELS.values())]
        if not matched and not unlabeled:
            return '视频分P只有其他属性的目标关卡'
        selected = matched or unlabeled
    else:
        selected = exact or pages
    limit = float(options.get('max_video_seconds', 180))
    for page in selected:
        if options.get('skip_manual_media') and MANUAL_PART.search(page['title']):
            continue
        duration = page.get('duration')
        if options.get('skip_long_media') and duration is not None and float(duration) > limit:
            continue
        return None
    return '目标分P均明确要求手动操作或超出自动解析时长上限'

def clean(value: Any) -> str:
    return html.unescape(re.sub(r'<[^>]*>', '', str(value or ''))).strip()

def relevant(text: str, terms: list[str]) -> bool:
    return any(re.search(r'(?<![a-z0-9])'+re.escape(term)+r'(?![a-z0-9])', text, re.I)
               if term.isascii() else term.casefold() in text.casefold() for term in terms)

def discover_sources(options: dict, *, api=None) -> dict:
    area = options.get('area', '')
    if not isinstance(area, str):
        raise ValueError('area必须为明确的目标名称')
    area = area.strip()
    kind = options.get('task_type', '')
    stage = options.get('stage', '')
    categories = options.get('category_terms', [])
    if not isinstance(kind, str) or not kind.strip() or not isinstance(stage, str):
        raise ValueError('来源查询必须明确task_type，stage必须为字符串')
    if not isinstance(categories, list) or any(not isinstance(t, str) or not t.strip() for t in categories):
        raise ValueError('category_terms必须为非空名称列表')
    aliases = options.get('aliases', [])
    if not area or not isinstance(aliases, list) or any(not isinstance(a,str) or not a.strip() for a in aliases):
        raise ValueError('area和aliases必须是明确的目标名称/别名')
    terms = list(dict.fromkeys([area]+aliases))
    urls=validate_urls(options.get('source_urls',[]))
    region = options.get('region', 'cn')
    if region not in ('cn', 'jp', 'tw'):
        raise ValueError('region应为cn、jp或tw')
    limit = options.get('max_videos', 8)
    effort = options.get('search_effort', 'normal')
    if effort not in ('normal', 'high'):
        raise ValueError('search_effort必须为normal或high')
    ttl = options.get('max_age_hours', 24)
    timeout = options.get('request_timeout', 12)
    if type(timeout) not in (int, float) or not 1 <= timeout <= 60:
        raise ValueError('request_timeout应为1–60秒')
    if type(limit) is not int or not 1 <= limit <= 30 or type(ttl) not in (int,float) or not 0 <= ttl <= 720:
        raise ValueError('max_videos应为1–30，max_age_hours应为0–720')
    queries = source_queries(terms, stage, effort, kind=kind, element=options.get('element'))
    scope = dict(task_type=kind,area=area,stage=stage,category_terms=categories,
                 terms=terms,region=region,max_videos=limit,queries=queries,source_urls=urls,
                 element=options.get('element'),search_effort=effort,
                 skip_manual_media=bool(options.get('skip_manual_media')),
                 skip_long_media=bool(options.get('skip_long_media')),
                 max_video_seconds=options.get('max_video_seconds', 180))
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
    browser_enabled = options.get('browser_session', True)
    if type(browser_enabled) is not bool:
        raise ValueError('browser_session必须为布尔值')
    api = api or BilibiliApi(timeout=timeout, browser_session=browser_enabled,
                           browser_cache_dir=options.get('browser_cache_dir', 'cache/game/strategies/bilibili_browser'),
                           browser_channel=options.get('browser_channel', 'msedge'))
    found = {}
    # A parser update or a reordered public search must not discard a recent
    # candidate that was already identified for this exact scope. Re-fetch its
    # metadata below and apply the current filters before using it again.
    if (isinstance(cached, dict) and cached.get('scope') == scope
            and type(cached.get('fetched_at')) in (int, float)
            and 0 <= now-cached['fetched_at'] < ttl*3600):
        prior = cached.get('candidates', [])
        if isinstance(prior, list):
            for rank, item in enumerate(prior):
                bvid = item.get('bvid') if isinstance(item, dict) else None
                if isinstance(bvid, str) and re.fullmatch(r'BV[0-9A-Za-z]{10}', bvid):
                    found[bvid] = dict(bvid=bvid, queries=['recent_verified_catalog'],
                                       search_rank=rank-len(prior))
    errors = []
    preferred,preferred_errors=preferred_sources(urls,api,timeout=timeout)
    errors.extend(dict(stage='preferred_source',**e) for e in preferred_errors)
    for query in queries:
        try:
            result = api.search(query)
            if result.get('code') != 0:
                raise ValueError('搜索接口code='+str(result.get('code')))
            if result.get('data', {}).get('v_voucher'):
                raise ValueError('公开搜索要求站点验证，本次不继续该查询')
            groups = result.get('data',{}).get('result')
            if not isinstance(groups,list):
                raise ValueError('搜索结构变化')
            for group in groups:
                if group.get('result_type') != 'video': continue
                for rank, item in enumerate(group.get('data',[])):
                    bvid = item.get('bvid','')
                    text = clean(item.get('title'))+' '+clean(item.get('description'))+' '+clean(item.get('tag'))
                    if not re.fullmatch(r'BV[0-9A-Za-z]{10}',bvid) or not relevant(text,terms+categories): continue
                    if bvid not in found: found[bvid] = dict(item,queries=[],search_rank=rank)
                    found[bvid]['search_rank'] = min(rank, found[bvid]['search_rank'])
                    found[bvid]['queries'].append(query)
        except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as error:
            # Public responses/errors only; no login credential is accessed.
            errors.append(dict(stage='search',query=query,error=type(error).__name__+': '+str(error)[:240]))
    candidates = []
    excluded = []
    high_abyss = kind == 'abyss' and effort == 'high'
    if high_abyss:
        target = re.compile(r'(?<!\d)'+re.escape(stage)+r'(?!\d)')
        # Search ranks restart for each query. Inspect exact-stage teasers first
        # and favor recent uploads within that group before the metadata cap.
        items = sorted(found.items(), key=lambda pair: (
            pair[1]['search_rank'] >= 0,
            not bool(target.search(clean(pair[1].get('title')))),
            -publication_time(pair[1]), pair[1]['search_rank']))
    else:
        items = sorted(found.items(), key=lambda pair: pair[1]['search_rank'])
    metadata_limit = max(72, limit*8) if high_abyss else max(24, limit*4)
    for bvid,item in items[:metadata_limit]:
        if not high_abyss and len(candidates) >= limit: break
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
            detail_text = title+' '+description+' '+' '.join(p['title'] for p in pages)
            if not relevant(detail_text,terms) or (categories and not relevant(detail_text,categories)):
                excluded.append(dict(bvid=bvid,reason='视频详情与目标玩法/区域不匹配'))
                continue
            if stage and not re.search(r'(?<!\d)'+re.escape(stage)+r'(?!\d)', detail_text):
                if not (kind == 'abyss' and effort == 'high'
                        and abyss_chapter_collection(detail_text, stage)):
                    excluded.append(dict(bvid=bvid,reason='视频详情未明确目标关卡或所在章节合集'))
                    continue
            if kind == 'abyss' and stage:
                reason = unusable_abyss_media(pages, stage, options)
                if reason:
                    excluded.append(dict(bvid=bvid, reason=reason))
                    continue
            declared = [code for code, pattern in [('cn', '国服|國服'), ('jp', '日服'), ('tw', '台服|臺服')]
                        if re.search(pattern, title+' '+description)]
            actual_region = declared[0] if len(declared) == 1 else 'unknown'
            if actual_region not in (region,'unknown'):
                excluded.append(dict(bvid=bvid,reason='视频明确服区与目标不符',region=actual_region))
                continue
            if kind == 'abyss' and options.get('skip_manual_media') and UNVERIFIED_SETTING.search(title+' '+description):
                excluded.append(dict(bvid=bvid,reason='视频标题或简介含未核实的TP+2大师点条件'))
                continue
            candidates.append(dict(bvid=bvid,url=f'https://www.bilibili.com/video/{bvid}/',title=title,
                description=description,author=clean(data.get('owner',{}).get('name')),published_at=data.get('pubdate'),
                pages=pages,matched_queries=item['queries'],verified_at=time.time(),identity_verified=True,
                region=actual_region,
                readiness='source_only',pending=(['视频服区未明确，需核验'] if actual_region == 'unknown' else [])+['需解析逐队衣装、培养开关、SET和阶段，再核验账号与跨队占用']))
        except (requests.RequestException, ValueError, KeyError, TypeError, RuntimeError, AttributeError) as error:
            errors.append(dict(stage='metadata',bvid=bvid,error=type(error).__name__+': '+str(error)[:240]))
    deferred = []
    if high_abyss:
        candidates.sort(key=lambda item: abyss_candidate_priority(item, stage, options.get('element')))
        deferred = [dict(bvid=item['bvid'], title=item['title']) for item in candidates[limit:]]
        candidates = candidates[:limit]
    report = dict(status='complete' if candidates and not errors else 'partial' if candidates else 'blocked',
                  parser_version=PARSER_VERSION,scope=scope,fetched_at=now,cache_hit=False,catalog=str(path),
                  candidates=candidates,deferred_candidates=deferred,preferred_sources=preferred,
                  excluded=excluded,errors=errors,pending=[])
    if not candidates: report['pending'].append('没有获得经视频详情核验的目标攻略来源；未生成战斗队伍')
    if errors: report['pending'].append('部分来源请求或详情核验失败，见errors；未把失败当作没有攻略')
    path.parent.mkdir(parents=True,exist_ok=True)
    if isinstance(cached,dict) and cached.get('status') == 'complete' and report['status'] != 'complete':
        backup=path.with_suffix('.last-good.json')
        backup.write_text(json.dumps(cached,ensure_ascii=False,indent=2),encoding='utf-8')
        report['previous_catalog']=str(backup)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
    return report
