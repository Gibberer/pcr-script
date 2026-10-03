from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock
from pcrscript.tasks.strategy_inputs import author_comment_clues,complete_author_comments,preferred_sources,source_options
from pcrscript.run_session import RunCancelled


def reply(rid,owner,text,**content):
    return dict(rpid=rid,rcount=0,member={'mid':str(owner)},content=dict(message=text,**content))


def page(number,total,rows,*,size=1,**data):
    return dict(code=0,data=dict(page=dict(num=number,size=size,count=total),replies=rows,**data))


class CommentSourcesTests(TestCase):
    def test_complete_scan_reads_later_author_corrections_and_nested_replies(self):
        api=Mock()
        root=reply(1,9,'viewer');root.update(rcount=2,replies=[reply(11,9,'inline viewer')])
        author=reply(2,7,'Boss2 合成角色3星')
        api.getVideoComments.side_effect=[page(1,2,[root],top={'upper':author}),page(2,2,[author])]
        api.getVideoCommentReplies.side_effect=[page(1,2,[reply(11,9,'inline viewer')]),
                                              page(2,2,[reply(12,7,'Boss2需要借角色')])]
        clues,scan=complete_author_comments(api,1,7,'https://example.com/video',max_pages=4)
        self.assertEqual({c['reply_id'] for c in clues},{2,12})
        self.assertEqual(scan,dict(complete=True,pages=4,root_count=2,reply_count=2))
        self.assertEqual([c.kwargs['page'] for c in api.getVideoComments.call_args_list],[1,2])
        self.assertEqual([c.args for c in api.getVideoCommentReplies.call_args_list],[(1,1),(1,1)])

    def test_incomplete_scans_never_claim_completeness(self):
        root=reply(1,9,'viewer')
        for case in ('budget','duplicate','changed_total','missing_page','missing_children'):
            with self.subTest(case=case):
                api=Mock()
                api.getVideoComments.side_effect=[page(1,2,[root]),page(2,2,[reply(2,9,'viewer')])]
                budget=1 if case=='budget' else 4
                if case=='duplicate':api.getVideoComments.side_effect=[page(1,2,[root]),page(2,2,[root])]
                if case=='changed_total':api.getVideoComments.side_effect=[page(1,2,[root]),page(2,3,[reply(2,9,'viewer')])]
                if case=='missing_page':api.getVideoComments.side_effect=[dict(code=0,data=dict(replies=[]))]
                if case=='missing_children':
                    api.getVideoComments.side_effect=[page(1,1,[dict(root,rcount=2,replies=[])])]
                    api.getVideoCommentReplies.side_effect=[page(1,2,[reply(11,9,'viewer')]),page(2,2,[])]
                with self.assertRaises(ValueError):
                    complete_author_comments(api,1,7,'https://example.com/video',max_pages=budget)
                if case=='budget':self.assertEqual(api.getVideoComments.call_count,1)

    def test_complete_comment_scan_honors_cancellation_between_pages(self):
        api=Mock();api.getVideoComments.return_value=page(1,2,[reply(1,9,'viewer')])
        check=Mock(side_effect=[None,RunCancelled('stop')])
        with self.assertRaises(RunCancelled):
            complete_author_comments(api,1,7,'https://example.com/video',check=check)
        self.assertEqual(api.getVideoComments.call_count,1)

    def test_partial_cache_is_refreshed_for_complete_scan_and_then_reused(self):
        api=Mock()
        api.getVideoInfo.return_value=dict(code=0,data=dict(bvid='BV1234567890',aid=1,title='guide',owner={'mid':7}))
        first=page(1,2,[reply(1,9,'viewer')]);last=page(2,2,[reply(2,7,'Boss2手动')])
        api.getVideoComments.side_effect=[first,first,last]
        with TemporaryDirectory() as folder:
            url='https://www.bilibili.com/video/BV1234567890'
            partial,_=preferred_sources([url],api,directory=folder)
            self.assertFalse(partial[0]['comment_complete'])
            full,_=preferred_sources([url],api,directory=folder,require_complete_comments=True)
            self.assertTrue(full[0]['comment_complete'])
            self.assertEqual(full[0]['author_comments'][0]['text'],'Boss2手动')
            cached,_=preferred_sources([url],api,directory=folder,require_complete_comments=True)
            self.assertEqual(cached[0]['comment_scan'],full[0]['comment_scan'])
            self.assertEqual(api.getVideoComments.call_count,3)

    def test_source_urls_stay_with_concrete_task(self):
        url='https://www.bilibili.com/video/BV1234567890'
        self.assertEqual(source_options({'source_urls':[url,url]})['source_urls'],[url])
        self.assertEqual(source_options({})['source_urls'],[])

    def test_author_pinned_nested_images_and_link_provenance(self):
        parent=reply(1,9,'viewer link https://example.com/untrusted')
        author=reply(2,7,'backup https://b23.tv/BV1234567890',
                     jump_url={'native':{'url':'bilibili://video/1'}},
                     pictures=[{'img_src':'https://example.com/guide.png'}])
        parent['replies']=[author]
        response={'code':0,'data':{'replies':[parent], 'top':{'upper':author}}}
        clues=author_comment_clues(response,7,'https://example.com/video')
        self.assertEqual(len(clues),1)
        self.assertEqual(clues[0]['reply_id'],2)
        self.assertEqual(clues[0]['links'],['https://www.bilibili.com/video/BV1234567890'])
        self.assertEqual(clues[0]['images'],['https://example.com/guide.png'])

    def test_comment_failure_preserves_video_source(self):
        api=Mock()
        api.getVideoInfo.return_value={'code':0,'data':dict(bvid='BV1234567890',aid=1,title='guide',owner={'mid':7})}
        api.getVideoComments.return_value={'code':-352}
        with TemporaryDirectory() as folder:
            sources,errors=preferred_sources(['https://www.bilibili.com/video/BV1234567890'],api,directory=folder)
            self.assertFalse(errors)
            self.assertIn('comment_pending',sources[0])
            self.assertEqual(sources[0]['readiness'],'source_only')

    def test_failed_comments_are_refetched_before_reusing_the_source_cache(self):
        api=Mock()
        api.getVideoInfo.return_value={'code':0,'data':dict(bvid='BV1234567890',aid=1,title='guide',owner={'mid':7})}
        api.getVideoComments.side_effect=[{'code':-352}, {'code':0,'data':{'replies':[reply(1,7,'需要借角色')]}}]
        with TemporaryDirectory() as folder:
            url='https://www.bilibili.com/video/BV1234567890'
            first,_=preferred_sources([url],api,directory=folder)
            self.assertIn('comment_pending',first[0])
            second,_=preferred_sources([url],api,directory=folder)
            self.assertNotIn('comment_pending',second[0])
            self.assertEqual(second[0]['author_comments'][0]['text'],'需要借角色')
            third,_=preferred_sources([url],api,directory=folder)
            self.assertEqual(third[0]['author_comments'],second[0]['author_comments'])
            self.assertEqual(api.getVideoComments.call_count,2)

    def test_unknown_comment_response_is_not_an_empty_supplement(self):
        for data in (None, {}, {'unknown': []}, [], {'replies':'changed'}, {'top':[]}):
            with self.subTest(data=data),self.assertRaises(ValueError):
                author_comment_clues(dict(code=0,data=data),7,'https://example.com/video')
        self.assertEqual(author_comment_clues(dict(code=0,data={'replies':None}),7,'https://example.com/video'),[])

    def test_one_hop_does_not_crawl_recursive_recommendations(self):
        api=Mock()
        api.getVideoInfo.side_effect=lambda bvid:{'code':0,'data':dict(bvid=bvid,aid=1,title='guide',owner={'mid':7})}
        api.getVideoComments.side_effect=[
            {'code':0,'data':{'replies':[reply(1,7,'https://b23.tv/BV2234567890')]}},
            {'code':0,'data':{'replies':[reply(2,7,'https://b23.tv/BV3234567890')]}}]
        with TemporaryDirectory() as folder:
            sources,errors=preferred_sources(['https://www.bilibili.com/video/BV1234567890'],api,directory=folder)
        self.assertFalse(errors)
        self.assertEqual(len(sources),2)
        self.assertFalse(sources[1]['user_provided'])
        self.assertEqual(sources[1]['discovered_via'][0]['reply_id'],1)
