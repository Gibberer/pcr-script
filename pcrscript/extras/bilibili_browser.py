"""Normal headless browsing with an isolated, local Bilibili session.

No user browser profile is read, no challenge is solved, and cookie values are
never returned in diagnostic reports. Runtime callers do not depend on Agent.
"""
from __future__ import annotations
import json
from pathlib import Path
import re
import time
from urllib.parse import quote
from uuid import uuid4


class BrowserVerificationRequired(RuntimeError):
    pass


def allowed_cookie(cookie: dict) -> bool:
    domain = str(cookie.get('domain', '')).lstrip('.')
    return domain == 'bilibili.com' or domain.endswith('.bilibili.com')


class BilibiliBrowserSession:
    def __init__(self, directory='cache/game/strategies/bilibili_browser', *, channel='msedge', timeout=20):
        self.directory = Path(directory)
        self.path = self.directory/'session.json'
        self.channel = channel
        self.timeout = min(max(timeout, 1), 60)

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if (data.get('version') == 1 and 0 <= time.time()-data['fetched_at'] < 86400
                    and isinstance(data['cookies'], list)):
                cookies = [c for c in data['cookies'] if isinstance(c, dict) and allowed_cookie(c)
                           and (c.get('expires', -1) == -1 or c.get('expires', 0) > time.time())]
                return dict(data, cookies=cookies)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
        return {}

    def headers(self) -> dict[str, str]:
        data = self.load()
        # Only cookies applicable to the API domain and root path are sent.
        cookies = [c for c in data.get('cookies', [])
                   if c.get('domain') == '.bilibili.com'
                   and c.get('path', '/') == '/'
                   and re.fullmatch(r'[A-Za-z0-9_\-]+', c.get('name', ''))
                   and not re.search(r'[\r\n;]', str(c.get('value', '')))]
        result = {}
        if cookies:
            result['Cookie'] = '; '.join(c['name']+'='+str(c['value']) for c in cookies)
            ua = data.get('user_agent', '')
            if isinstance(ua, str) and ua and not re.search(r'[\r\n]', ua):
                result['User-Agent'] = ua
        return result

    def save(self, context, page) -> None:
        state = dict(version=1, fetched_at=time.time(),
                     cookies=[c for c in context.cookies() if allowed_cookie(c)],
                     user_agent=page.evaluate('navigator.userAgent'), source='https://search.bilibili.com/')
        temporary = self.path.with_suffix('.'+uuid4().hex+'.tmp')
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        temporary.replace(self.path)

    def search(self, keyword: str) -> dict:
        from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
        self.directory.mkdir(parents=True, exist_ok=True)
        saved = self.load()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=self.channel, headless=True,
                                                 timeout=self.timeout*1000)
            try:
                context = browser.new_context(storage_state={'cookies': saved.get('cookies', []), 'origins': []})
                page = context.new_page()
                page.set_default_timeout(self.timeout*1000)
                page.goto('https://search.bilibili.com/all?keyword='+quote(keyword), wait_until='domcontentloaded')
                try:
                    page.locator('a[href*="/video/BV"]').first.wait_for(state='visible')
                except BrowserTimeout:
                    page.screenshot(path=str(self.directory/'verification_required.png'))
                    self.save(context, page)
                    raise BrowserVerificationRequired('浏览器未得到公开视频结果，可能需要人工验证；已保存现场，未自动解验证码') from None
                links = page.locator('a[href*="/video/BV"]').evaluate_all(
                    '(links) => links.map(a => ({url:a.href,title:a.innerText || a.getAttribute("title") || ""}))')
                videos = {}
                for link in links:
                    match = re.fullmatch(r'https://www\.bilibili\.com/video/(BV[0-9A-Za-z]{10})/?(?:\?.*)?', link['url'])
                    if not match:
                        continue
                    bvid = match[1]
                    title = link['title'].strip()
                    if title and (bvid not in videos or len(title) < len(videos[bvid]['title'])):
                        videos[bvid] = dict(bvid=bvid, title=title)
                if not videos:
                    raise BrowserVerificationRequired('浏览器搜索没有可核验的BV结果，未生成攻略')
                self.save(context, page)
                # Return only public search results, never the saved state.
                return {'code': 0, 'data': {'result': [{'result_type': 'video', 'data': list(videos.values())}]},
                        'transport': 'browser', 'session_saved': True}
            finally:
                browser.close()
