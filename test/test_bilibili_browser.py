"""Session persistence/security and bounded browser fallback without networking."""
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from pcrscript.extras.bilibili_browser import BilibiliBrowserSession
from pcrscript.extras.bilibili_api import BilibiliApi


class BrowserSessionTests(TestCase):
    def test_only_fresh_bilibili_cookies_with_applicable_scope(self):
        with TemporaryDirectory() as folder:
            session=BilibiliBrowserSession(folder)
            cookie=dict(name='synthetic',value='safe',domain='.bilibili.com',path='/',expires=-1)
            payload=dict(version=1,fetched_at=time.time(),user_agent='synthetic-agent',cookies=[cookie,
                dict(cookie,name='outside',domain='.example.com'),
                dict(cookie,name='hostonly',domain='search.bilibili.com'),
                dict(cookie,name='old',expires=time.time()-1),
                dict(cookie,name='newline',value='bad\r\nHeader: bad')])
            session.path.write_text(json.dumps(payload),encoding='utf-8')
            self.assertEqual(session.headers(),{'Cookie':'synthetic=safe','User-Agent':'synthetic-agent'})
            payload['fetched_at']=time.time()-90000
            session.path.write_text(json.dumps(payload),encoding='utf-8')
            self.assertEqual(session.headers(),{})

    def test_cookie_restore_does_not_touch_legacy_login_cookie(self):
        with patch('pcrscript.extras.bilibili_browser.BilibiliBrowserSession') as factory, \
             patch('pcrscript.extras.bilibili_api._cookie_path') as legacy:
            factory.return_value.headers.return_value={'Cookie':'synthetic=safe'}
            api=BilibiliApi(browser_session=True)
            self.assertEqual(api.headers['Cookie'],'synthetic=safe')
            legacy.exists.assert_not_called()

    def test_api_challenge_falls_back_at_most_twice_and_keeps_cookie_out_of_result(self):
        api=BilibiliApi()
        api.browser=Mock();api.browser.headers.return_value={'Cookie':'synthetic=private'}
        public={'code':0,'data':{'result':[]},'transport':'browser'}
        api.browser.search.return_value=public
        api._get=Mock();api._get.return_value.json.return_value={'code':0,'data':{'v_voucher':'synthetic'}}
        for _ in range(2):self.assertEqual(api.search('query'),public)
        self.assertIn('v_voucher',api.search('query')['data'])
        self.assertEqual(api.browser.search.call_count,2)
        self.assertNotIn('private',json.dumps(public))

    def test_unexpected_browser_errors_do_not_echo_secrets(self):
        api=BilibiliApi();api.browser=Mock()
        api._get=Mock();api._get.return_value.json.return_value={'code':-412}
        api.browser.search.side_effect=Exception('cookie=private')
        with self.assertRaises(RuntimeError) as caught:api.search('query')
        self.assertNotIn('private',str(caught.exception))

    def test_api_without_optin_never_launches_browser(self):
        with patch('pcrscript.extras.bilibili_browser.BilibiliBrowserSession') as browser:
            api=BilibiliApi()
            api._get=Mock();api._get.return_value.json.return_value={'code':0,'data':{'v_voucher':'synthetic'}}
            api.search('query');browser.assert_not_called()
