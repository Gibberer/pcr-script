from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock,patch
import json
import requests
from pcrscript.tasks.dungeon_sources import discover_sources,relevant
from pcrscript.runtime import run_task_with_config

BV='BV1234567890'
def fake_api():
 a=Mock()
 a.search.return_value={'code':0,'data':{'result':[{'result_type':'video','data':[{'bvid':BV,'title':'测试区域 攻略','pubdate':1}]}]}}
 a.getVideoInfo.return_value={'code':0,'data':{'bvid':BV,'title':'公主连结 国服 测试区域 攻略','owner':{'name':'synthetic'},'pages':[{'cid':1,'page':1,'part':'测试阶段'}]}}
 return a

class SourceTests(TestCase):
 def options(self,folder):return dict(area='测试区域',aliases=[],cache_dir=folder)
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
 def test_exact_ascii_difficulty_and_changed_scope(self):
  self.assertFalse(relevant('攻略 EX70',['EX7']))
  self.assertTrue(relevant('地下城EX7攻略',['EX7']))
  with TemporaryDirectory() as folder:
   api=fake_api();one=discover_sources(self.options(folder),api=api)
   two=discover_sources(dict(self.options(folder),aliases=['TEST7']),api=api)
   self.assertNotEqual(one['catalog'],two['catalog'])
 def test_registered_entry_never_connects_emulator(self):
  with TemporaryDirectory() as folder,patch('pcrscript.tasks.dungeon_sources.BilibiliApi',return_value=fake_api()),patch('pcrscript.runtime.robot_from_config',side_effect=AssertionError('no device')):
   r=run_task_with_config({'DungeonSources':self.options(folder)},'dungeon_sources')
   self.assertEqual(r['status'],'complete')

 def test_other_game_and_wrong_region_are_excluded(self):
  for title in ['其他游戏 测试区域','公主连结 日服 测试区域']:
   with TemporaryDirectory() as folder:
    api=fake_api();api.getVideoInfo.return_value['data']['title']=title
    r=discover_sources(self.options(folder),api=api)
    self.assertFalse(r['candidates']);self.assertEqual(len(r['excluded']),1)

 def test_missing_plan_invokes_formal_search_without_creating_executable_parties(self):
  from types import SimpleNamespace
  from pcrscript.tasks.task_dungeon import DungeonFirstClear
  with TemporaryDirectory() as folder,patch('pcrscript.tasks.dungeon_sources.discover_sources',return_value={'status':'complete','candidates':[{'readiness':'source_only'}]}) as search:
   task=object.__new__(DungeonFirstClear);task.plan=None;task.area='测试区域'
   task.options={'teams':str(Path(folder)/'absent.yml')};task.robot=SimpleNamespace(task_config={});task.report={'pending':[]}
   self.assertEqual(task.ensure_plan(),[]);self.assertEqual(task.ensure_plan(),[])
   search.assert_called_once();self.assertTrue(task.report['pending'])
