"""Shared user-prioritized guide inputs; content is data, never instructions."""
from html.parser import HTMLParser
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit,urljoin
import requests
from ..run_session import atomic_json

SOURCE_CACHE_VERSION = 5


def video_metadata(data):
    """The same public metadata schema for supplied links and search results."""
    return dict(provider='bilibili', bvid=data['bvid'],
                url=f'https://www.bilibili.com/video/{data["bvid"]}/',
                title=data['title'], description=data.get('desc', ''),
                published_at=data.get('pubdate'), pages=data.get('pages', []))


def source_statements(source):
    """One metadata view for applicability, requirements and their provenance."""
    return [(source.get('title', ''), 'source_title'),
            (source.get('description', source.get('desc', '')), 'source_description')]+[
        (row.get('text', ''), 'author_comment:'+str(row.get('reply_id')))
        for row in source.get('author_comments', [])]


def advisory_requirement(text):
    """Reference builds and the author's own stats do not impose a minimum."""
    reference = (re.search(r'参考练度|练度参考|参考配置|配置参考|建议|推荐|可选', text)
                 or re.search(r'^(?:我|本人|作者)[^\n；。]*(?:练度|属性|MP\d+|大师点)', text, re.I))
    return bool(reference) and not re.search(
        r'必须|必备|需要|要求|至少|最低|不低于|不可低于|才能|否则|务必|一定要|不能少|不可缺', text)


def fixed_set_statement(text):
    """An explicit five-slot initial setting, with no timed actions or extra instructions."""
    compact = re.sub(r'\s+', '', text)
    match = re.fullmatch(
        r'(?:不想操作的)?(?:[【\[]?(?:Boss[1-3]|[1-3]王|首领[1-3])[】\]]?)?'
        r'(?:开局)?(?:SET)?(?P<flags>[OX]{5}|全SET)'
        r'(?:开自动|(?:AUTO|自动)(?:ON|开启))?(?:同样)?(?:[1-9]\d*|[一二两三四五六七八九十])?刀?',
        compact, re.I)
    if match is None:
        return None
    flags = match['flags'].upper()
    return (True,)*5 if flags == '全SET' else tuple(flag == 'O' for flag in flags)


def declared_region(text: str) -> str:
    # Guild recruitment does not declare the recorded battle's server.
    text = re.sub(r'(?:国服|國服|日服|台服|臺服)\s*(?:公会|公會|行会|行會)', '', text)
    values = {code for code, pattern in [('cn', '国服|國服'), ('jp', '日服'), ('tw', '台服|臺服')]
              if re.search(pattern, text)}
    return next(iter(values)) if len(values) == 1 else 'conflict' if values else 'unknown'


def author_comment_clues(response, owner_id, video_url):
    """Keep author identity and reply provenance; viewers are not the author."""
    if response.get('code') != 0:
        raise ValueError('评论读取未完成：'+str(response.get('code')))
    data=response.get('data')
    if not isinstance(data,dict) or not any(k in data for k in ('replies','hots','top','top_replies')):
        raise ValueError('评论结构未知，不能确认作者补充已读取')
    for key,kind in (('replies',list),('hots',list),('top',dict),('top_replies',(dict,list))):
        if data.get(key) is not None and not isinstance(data[key],kind):
            raise ValueError('评论列表结构未知：'+key)
    queue=comment_roots(data);seen=set();clues=[]
    while queue:
        item=queue.pop(0)
        if not isinstance(item,dict) or item.get('rpid') in seen:continue
        seen.add(item.get('rpid'));queue.extend(item.get('replies') or [])
        if str(item.get('member',{}).get('mid'))!=str(owner_id):continue
        content=item.get('content') or {};message=content.get('message','')
        links=re.findall(r'https?://[^\s<>]+',message)
        for value in (content.get('jump_url') or {}).values():
            if isinstance(value,dict) and value.get('url'):links.append(value['url'])
        normalized_links=[]
        for link in links:
            parsed=urlsplit(link)
            if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
                continue
            bv=re.fullmatch(r'https?://b23\.tv/(BV[0-9A-Za-z]{10})/?',link)
            normalized_links.append('https://www.bilibili.com/video/'+bv[1] if bv else link)
        clues.append(dict(reply_id=item.get('rpid'),owner_id=str(owner_id),text=message,
                          source=video_url,created_at=item.get('ctime'),
                          images=[p['img_src'] for p in content.get('pictures',[]) if p.get('img_src')],
                          links=list(dict.fromkeys(normalized_links))))
    return clues


def comment_roots(data):
    queue=[]
    for key in ('replies','hots'):
        queue.extend(data.get(key) or [])
    queue.extend(v for v in (data.get('top') or {}).values() if isinstance(v,dict))
    for key in ('upper','admin','vote'):
        item=(data.get('top_replies') or {}).get(key) if isinstance(data.get('top_replies'),dict) else None
        if isinstance(item,dict):queue.append(item)
    if isinstance(data.get('top_replies'),list):queue.extend(data['top_replies'])
    return queue


def complete_author_comments(api, avid, owner_id, video_url, *, max_pages=10, check=lambda: None):
    """Read all counted root/child replies within one bounded request budget."""
    if type(max_pages) is not int or not 1 <= max_pages <= 100:
        raise ValueError('max_comment_pages必须为1到100')
    requests_used=0;clues={}
    def read_pages(fetch, *, expected_count=None):
        nonlocal requests_used
        rows={};page=1;total=expected_count
        while True:
            check()
            if requests_used >= max_pages:
                raise ValueError(f'作者评论未读完：达到 max_comment_pages={max_pages}')
            requests_used+=1
            response=fetch(page)
            for clue in author_comment_clues(response,owner_id,video_url):
                clues[(clue['reply_id'],clue['text'])]=clue
            data=response['data'];pagination=data.get('page') or {}
            count,size=pagination.get('count'),pagination.get('size')
            if (type(count) is not int or count < 0 or type(size) is not int or not 1 <= size <= 100
                    or pagination.get('num') != page or total is not None and count != total):
                raise ValueError('作者评论分页总量未知或读取期间变化')
            total=count
            for row in comment_roots(data):
                if not isinstance(row,dict) or type(row.get('rpid')) not in (int,str) or not str(row['rpid']).isdigit():
                    raise ValueError('作者评论身份未知')
                rows[str(row['rpid'])]=row
            if page*size >= total:
                break
            page+=1
        if len(rows) != total:
            raise ValueError('作者评论数量与分页总量不符，未确认完整读取')
        return rows
    cursor_reader = getattr(type(api), 'getVideoCommentsCursor', None)
    if callable(cursor_reader):
        roots = {}; cursor = 0; cursors = set(); total = None
        while True:
            check()
            if requests_used >= max_pages:
                raise ValueError(f'作者评论未读完：达到 max_comment_pages={max_pages}')
            if cursor in cursors:
                raise ValueError('作者评论游标重复，未确认完整读取')
            cursors.add(cursor); requests_used += 1
            response = api.getVideoCommentsCursor(avid, next_cursor=cursor)
            for clue in author_comment_clues(response, owner_id, video_url):
                clues[(clue['reply_id'], clue['text'])] = clue
            data = response['data']; pagination = data.get('cursor') or {}
            count = pagination.get('all_count')
            # An empty cursor omits all_count. Confirm zero through the
            # independent numbered endpoint instead of assuming absence.
            if (count is None and cursor == 0 and pagination.get('is_end') is True
                    and not comment_roots(data)):
                legacy = read_pages(lambda page: api.getVideoComments(avid, page=page))
                if legacy:
                    raise ValueError('作者评论空游标与分页结果不一致')
                count = 0
            if (type(count) is not int or count < 0 or pagination.get('mode') != 2
                    or type(pagination.get('is_end')) is not bool
                    or total is not None and count != total):
                raise ValueError('作者评论游标总量未知或读取期间变化')
            total = count
            for row in comment_roots(data):
                if (not isinstance(row, dict) or type(row.get('rpid')) not in (int, str)
                        or not str(row['rpid']).isdigit()
                        or type(row.get('rcount')) is not int or row['rcount'] < 0):
                    raise ValueError('作者评论身份或楼中楼数量未知')
                roots[str(row['rpid'])] = row
            if pagination['is_end']:
                break
            cursor = pagination.get('next')
            if type(cursor) is not int or cursor <= 0:
                raise ValueError('作者评论下一页游标未知')
        # all_count includes root comments and their children, unlike the
        # legacy synthetic page contract. Pinned roots are deduplicated.
        if len(roots)+sum(row['rcount'] for row in roots.values()) != total:
            raise ValueError('作者评论数量与游标总量不符，未确认完整读取')
    else:
        roots=read_pages(lambda page: api.getVideoComments(avid,page=page))
    child_count=0
    for root in roots.values():
        count=root.get('rcount');inline=root.get('replies') or []
        if type(count) is not int or count < 0 or not isinstance(inline,list):
            raise ValueError('楼中楼数量未知')
        ids={str(row['rpid']) for row in inline if isinstance(row,dict) and row.get('rpid') is not None}
        if len(ids) > count or len(ids) != len(inline):
            raise ValueError('楼中楼预览数量不符')
        if len(ids) < count:
            read_pages(lambda page: api.getVideoCommentReplies(avid,root['rpid'],page=page), expected_count=count)
        child_count+=count
    return list(clues.values()),dict(complete=True,pages=requests_used,root_count=len(roots),reply_count=child_count)


def source_options(local):
    """Normalize links supplied by the concrete task only."""
    result=dict(local)
    result['source_urls']=list(dict.fromkeys(validate_urls(result.get('source_urls',[]))))
    return result


def validate_urls(urls):
    if not isinstance(urls,list) or any(not isinstance(u,str) for u in urls):
        raise ValueError('source_urls必须是攻略链接列表')
    for url in urls:
        p=urlsplit(url)
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:
            raise ValueError('攻略链接必须是无账号密码的HTTP(S)地址')
    return urls


class GuideHTML(HTMLParser):
    def __init__(self):
        super().__init__();self.skip=0;self.text=[];self.images=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.skip+=1
        if tag=='img':
            data=dict(attrs);url=data.get('data-src') or data.get('src')
            if url:self.images.append(url)
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if not self.skip and data.strip():self.text.append(data.strip())


def preferred_sources(urls,api,*,directory='cache/game/strategies/user_sources',timeout=20,follow_comments=True,
                      require_complete_comments=False,max_comment_pages=10,check=lambda: None):
    result=[];errors=[];root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    for priority,url in enumerate(validate_urls(urls)):
        check()
        path=root/(sha256(url.encode()).hexdigest()[:24]+'.json')
        try:
            if path.exists():
                saved=json.loads(path.read_text(encoding='utf-8'))
                if (saved.get('version')==SOURCE_CACHE_VERSION and not saved.get('comment_pending')
                        and (not require_complete_comments or saved.get('comment_complete') is True)
                        and saved.get('url')==url and 0<=time.time()-saved['fetched_at']<86400):
                    result.append(dict(saved,priority=priority));continue
            bvid=re.search(r'/(BV[0-9A-Za-z]{10})(?:[/?#]|$)',url)
            if urlsplit(url).hostname in ('www.bilibili.com','bilibili.com','m.bilibili.com') and bvid:
                response=api.getVideoInfo(bvid=bvid[1]);data=response.get('data',{})
                if response.get('code')!=0 or data.get('bvid')!=bvid[1]:raise ValueError('视频身份未核验')
                entry=video_metadata(data)
                try:
                    entry['comment_complete']=False
                    if require_complete_comments:
                        entry['author_comments'],entry['comment_scan']=complete_author_comments(
                            api,data['aid'],data['owner']['mid'],url,max_pages=max_comment_pages,check=check)
                        entry['comment_complete']=True
                        entry['comment_scope']='按分页总量核对全部可见主评论及楼中楼'
                    else:
                        entry['author_comments']=author_comment_clues(
                            api.getVideoComments(data['aid']),data['owner']['mid'],url)
                        entry['comment_scope']='热门第一页、置顶及已返回的楼中楼；不是全部评论'
                except (requests.RequestException,ValueError,KeyError,TypeError,AttributeError) as error:
                    entry['comment_pending']='评论未获取：'+type(error).__name__+': '+str(error)[:180]
            else:
                response=requests.get(url,timeout=timeout,headers={'User-Agent':'Mozilla/5.0'})
                response.raise_for_status()
                if len(response.content)>5_000_000:raise ValueError('攻略网页超出读取大小限制')
                parser=GuideHTML();parser.feed(response.text)
                entry=dict(provider='web',title=parser.text[0] if parser.text else '',
                           description='\n'.join(parser.text),images=[urljoin(response.url,u) for u in parser.images],
                           resolved_url=response.url)
            entry.update(version=SOURCE_CACHE_VERSION,url=url,fetched_at=time.time(),priority=priority,user_provided=True,
                         readiness='source_only',pending=['仍需核验任务范围和解析角色/培养要求'])
            atomic_json(path, entry)
            result.append(entry)
        except (requests.RequestException,ValueError,KeyError,TypeError,OSError) as error:
            errors.append(dict(url=url,error=type(error).__name__+': '+str(error)[:180]))
    if follow_comments:
        explicit=set(urls);references={}
        for source in result:
            for comment in source.get('author_comments',[]):
                for link in comment['links']:
                    if link not in explicit:
                        references.setdefault(link,[]).append(dict(source=source['url'],reply_id=comment['reply_id']))
        # One hop only: links are evidence, never an unbounded crawler.
        linked,failures=preferred_sources(list(references)[:8],api,directory=directory,
            timeout=timeout,follow_comments=False,require_complete_comments=require_complete_comments,
            max_comment_pages=max_comment_pages,check=check) if references else ([],[])
        for item in linked:
            item.update(user_provided=False,discovered_via=references[item['url']],priority=len(result))
            result.append(item)
        errors.extend(failures)
    return result,errors
