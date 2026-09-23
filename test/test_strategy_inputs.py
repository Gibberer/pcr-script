from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock
from pcrscript.tasks.strategy_inputs import author_comment_clues,preferred_sources,source_options


def reply(rid,owner,text,**content):
    return dict(rpid=rid,member={'mid':str(owner)},content=dict(message=text,**content))


class CommentSourcesTests(TestCase):
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
