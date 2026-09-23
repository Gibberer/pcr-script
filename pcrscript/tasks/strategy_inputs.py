"""Shared user-prioritized guide inputs; content is data, never instructions."""
from html.parser import HTMLParser
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit,urljoin
import requests


def author_comment_clues(response, owner_id, video_url):
    """Keep author identity and reply provenance; viewers are not the author."""
    if response.get('code') != 0:
        raise ValueError('评论读取未完成：'+str(response.get('code')))
    data=response.get('data') or {};queue=[];seen=set();clues=[]
    for key in ('replies','hots'):
        queue.extend(data.get(key) or [])
    queue.extend(v for v in (data.get('top') or {}).values() if isinstance(v,dict))
    for key in ('upper','admin','vote'):
        item=(data.get('top_replies') or {}).get(key) if isinstance(data.get('top_replies'),dict) else None
        if isinstance(item,dict):queue.append(item)
    if isinstance(data.get('top_replies'),list):queue.extend(data['top_replies'])
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


def preferred_sources(urls,api,*,directory='cache/game/strategies/user_sources',timeout=20,follow_comments=True):
    result=[];errors=[];root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    for priority,url in enumerate(validate_urls(urls)):
        path=root/(sha256(url.encode()).hexdigest()[:24]+'.json')
        try:
            if path.exists():
                saved=json.loads(path.read_text(encoding='utf-8'))
                if saved.get('version')==2 and saved.get('url')==url and 0<=time.time()-saved['fetched_at']<86400:
                    result.append(dict(saved,priority=priority));continue
            bvid=re.search(r'/(BV[0-9A-Za-z]{10})(?:[/?#]|$)',url)
            if urlsplit(url).hostname in ('www.bilibili.com','bilibili.com','m.bilibili.com') and bvid:
                response=api.getVideoInfo(bvid=bvid[1]);data=response.get('data',{})
                if response.get('code')!=0 or data.get('bvid')!=bvid[1]:raise ValueError('视频身份未核验')
                entry=dict(provider='bilibili',bvid=bvid[1],title=data['title'],description=data.get('desc',''),
                           published_at=data.get('pubdate'),pages=data.get('pages',[]))
                try:
                    entry['author_comments']=author_comment_clues(
                        api.getVideoComments(data['aid']),data['owner']['mid'],url)
                    entry['comment_scope']='热门第一页、置顶及已返回的楼中楼；不是全部评论'
                except (requests.RequestException,ValueError,KeyError,TypeError,AttributeError) as error:
                    entry['comment_pending']='评论未获取：'+type(error).__name__
            else:
                response=requests.get(url,timeout=timeout,headers={'User-Agent':'Mozilla/5.0'})
                response.raise_for_status()
                if len(response.content)>5_000_000:raise ValueError('攻略网页超出读取大小限制')
                parser=GuideHTML();parser.feed(response.text)
                entry=dict(provider='web',title=parser.text[0] if parser.text else '',
                           description='\n'.join(parser.text),images=[urljoin(response.url,u) for u in parser.images],
                           resolved_url=response.url)
            entry.update(version=2,url=url,fetched_at=time.time(),priority=priority,user_provided=True,
                         readiness='source_only',pending=['仍需核验任务范围和解析角色/培养要求'])
            path.write_text(json.dumps(entry,ensure_ascii=False,indent=2),encoding='utf-8')
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
                                         timeout=timeout,follow_comments=False) if references else ([],[])
        for item in linked:
            item.update(user_provided=False,discovered_via=references[item['url']],priority=len(result))
            result.append(item)
        errors.extend(failures)
    return result,errors
