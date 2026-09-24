from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock,patch
import json
import requests
from pcrscript.tasks.strategy_sources import discover_sources,relevant
from pcrscript.tasks import find_taskclass

BV='BV1234567890'
def fake_api():
 a=Mock()
 a.search.return_value={'code':0,'data':{'result':[{'result_type':'video','data':[{'bvid':BV,'title':'测试区域 攻略','pubdate':1}]}]}}
 a.getVideoInfo.return_value={'code':0,'data':{'bvid':BV,'title':'公主连结 国服 测试区域 攻略','owner':{'name':'synthetic'},'pages':[{'cid':1,'page':1,'part':'测试阶段'}]}}
 return a

class SourceTests(TestCase):
 def options(self,folder):return dict(task_type='dungeon',area='测试区域',aliases=[],cache_dir=folder)
 def test_empty_cache_fetch_then_reuse_and_expiry(self):
  with TemporaryDirectory() as folder:
   api=fake_api();o=self.options(folder)
   first=discover_sources(o,api=api);self.assertEqual(first['status'],'complete')
   self.assertEqual(first['candidates'][0]['readiness'],'source_only')
   self.assertEqual(first['candidates'][0]['region'],'cn')
   cached=discover_sources(o,api=api);self.assertTrue(cached['cache_hit']);self.assertEqual(api.search.call_count,1)
   discover_sources(dict(o,max_age_hours=0),api=api);self.assertEqual(api.search.call_count,2)
 def test_wrong_metadata_identity_is_rejected(self):
  with TemporaryDirectory() as folder:
   api=fake_api();api.getVideoInfo.return_value['data']['bvid']='BV0000000000'
   r=discover_sources(self.options(folder),api=api)
   self.assertEqual(r['status'],'blocked');self.assertEqual(r['candidates'],[])
 def test_recent_candidate_survives_search_reorder_after_parser_update(self):
  with TemporaryDirectory() as folder:
   api=fake_api();o=self.options(folder)
   first=discover_sources(o,api=api)
   path=Path(first['catalog']);saved=json.loads(path.read_text(encoding='utf-8'))
   saved['parser_version']-=1
   path.write_text(json.dumps(saved),encoding='utf-8')
   api.search.return_value={'code':0,'data':{'result':[]}}
   refreshed=discover_sources(o,api=api)
   self.assertEqual([c['bvid'] for c in refreshed['candidates']],[BV])
   self.assertFalse(refreshed['cache_hit'])
   self.assertEqual(api.getVideoInfo.call_count,2)
 def test_refresh_failure_preserves_last_good_but_is_not_success(self):
  with TemporaryDirectory() as folder:
   api=fake_api();o=self.options(folder);discover_sources(o,api=api)
   api.search.side_effect=requests.ConnectionError('offline')
   r=discover_sources(dict(o,max_age_hours=0),api=api)
   self.assertEqual(r['status'],'blocked');self.assertTrue(Path(r['previous_catalog']).exists())
 def test_duplicate_queries_do_not_repeat_video_requests(self):
  with TemporaryDirectory() as folder:
   api=fake_api();o=self.options(folder);o['aliases']=['TEST7']
   r=discover_sources(o,api=api);self.assertEqual(len(r['candidates']),1);api.getVideoInfo.assert_called_once()
 def test_automatic_abyss_uses_candidate_after_manual_and_long_parts(self):
  with TemporaryDirectory() as folder:
   api=fake_api()
   ids=['BV0000000001','BV0000000002','BV0000000003']
   api.search.return_value={'code':0,'data':{'result':[{'result_type':'video','data':[
    {'bvid':bvid,'title':'公主连结 测试区域 深域 2-10'} for bvid in ids]}]}}
   parts=['2-10（半自动）','深域2-1至2-10合集','2-10']
   durations=[120,1183,100]
   def info(*,bvid):
    i=ids.index(bvid)
    return {'code':0,'data':{'bvid':bvid,'title':'公主连结 国服 测试区域 深域 2-10',
     'owner':{'name':'synthetic'},'pages':[{'cid':i+1,'page':1,'part':parts[i],
                                           'duration':durations[i]}]}}
   api.getVideoInfo.side_effect=info
   result=discover_sources(dict(task_type='abyss',area='测试区域',stage='2-10',
    category_terms=['深域'],max_videos=1,max_video_seconds=240,skip_manual_media=True,
    skip_long_media=True,cache_dir=folder),api=api)
   self.assertEqual([c['bvid'] for c in result['candidates']],[ids[2]])
   self.assertEqual([e['bvid'] for e in result['excluded']],ids[:2])
   self.assertEqual(api.getVideoInfo.call_count,3)
 def test_automatic_abyss_checks_element_before_other_stage_parts(self):
  with TemporaryDirectory() as folder:
   api=fake_api()
   api.search.return_value['data']['result'][0]['data'][0]['title']='公主连结 深域 风2-10'
   api.getVideoInfo.return_value['data'].update(title='公主连结 国服 深域 全属性合集',
    pages=[{'cid':1,'page':1,'part':'风2-10（简易1押）','duration':145},
           {'cid':2,'page':2,'part':'暗2-10（全SET）','duration':98}])
   result=discover_sources(dict(task_type='abyss',area='深域',aliases=['风'],element='wind',
    stage='2-10',category_terms=['深域'],max_videos=1,max_video_seconds=240,
    skip_manual_media=True,skip_long_media=True,cache_dir=folder),api=api)
   self.assertEqual(result['candidates'],[])
   self.assertIn('手动操作',result['excluded'][0]['reason'])
 def test_automatic_abyss_excludes_tp_requirement_in_description(self):
  with TemporaryDirectory() as folder:
   api=fake_api()
   api.search.return_value['data']['result'][0]['data'][0]['title']='公主连结 深域 风2-10'
   api.getVideoInfo.return_value['data'].update(title='公主连结 国服 深域 风2-10',
    desc='风2-10刚需TP+2大师点',pages=[{'cid':1,'page':1,'part':'风2-10','duration':120}])
   result=discover_sources(dict(task_type='abyss',area='深域',aliases=['风'],element='wind',
    stage='2-10',category_terms=['深域'],max_videos=1,max_video_seconds=240,
    skip_manual_media=True,skip_long_media=True,cache_dir=folder),api=api)
   self.assertEqual(result['candidates'],[])
   self.assertIn('TP+2',result['excluded'][0]['reason'])
 def test_exact_ascii_difficulty_and_changed_scope(self):
  self.assertFalse(relevant('攻略 EX70',['EX7']))
  self.assertTrue(relevant('地下城EX7攻略',['EX7']))
  with TemporaryDirectory() as folder:
   api=fake_api();one=discover_sources(self.options(folder),api=api)
   two=discover_sources(dict(self.options(folder),aliases=['TEST7']),api=api)
   self.assertNotEqual(one['catalog'],two['catalog'])
 def test_search_is_internal_to_dungeon_task(self):
  self.assertIsNone(find_taskclass('dungeon_sources'))

 def test_other_game_and_wrong_region_are_excluded(self):
  for title in ['其他游戏 测试区域','公主连结 日服 测试区域','公主连结 台服 测试区域']:
   with TemporaryDirectory() as folder:
    api=fake_api();api.getVideoInfo.return_value['data']['title']=title
    r=discover_sources(self.options(folder),api=api)
    self.assertFalse(r['candidates']);self.assertEqual(len(r['excluded']),1)

 def test_missing_plan_invokes_formal_search_without_creating_executable_parties(self):
  from types import SimpleNamespace
  from pcrscript.tasks.task_dungeon import DungeonFirstClear
  with TemporaryDirectory() as folder,patch('pcrscript.tasks.strategy_video.acquire_strategies',return_value={'status':'partial','parties':[],'pending':['来源培养未明确']}) as search:
   task=object.__new__(DungeonFirstClear);task.plan=None;task.area='测试区域'
   task.options={'teams':str(Path(folder)/'absent.yml')};task.robot=SimpleNamespace(task_config={});task.report={'pending':[]}
   self.assertEqual(task.ensure_plan(),[]);self.assertEqual(task.ensure_plan(),[])
   search.assert_called_once();self.assertTrue(task.report['pending'])
