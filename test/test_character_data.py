"""Synthetic character metadata, cache invalidation and account-state boundaries."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import os
import sqlite3

from pcrscript.character_data import character, equipment_requirement_issues
from pcrscript.tasks.event_strategy import MemberRequirement, skill_names, costume_skills
from pcrscript.tasks.party_preparation import catalogue_issues
from pcrscript.game_ui.avatar_assets import DB_SOURCE


class CharacterDataTests(TestCase):
    def database(self, root):
        path = Path(root)/'cn.db'
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript('''
                CREATE TABLE unit_profile (unit_id INTEGER, unit_name TEXT);
                CREATE TABLE unit_skill_data (unit_id INTEGER, main_skill_1 INTEGER,
                    main_skill_2 INTEGER, main_skill_evolution_1 INTEGER, main_skill_evolution_2 INTEGER);
                CREATE TABLE skill_data (skill_id INTEGER, name TEXT);
                CREATE TABLE unit_unique_equipment (unit_id INTEGER, equip_slot INTEGER, equip_id INTEGER);
                CREATE TABLE unique_equipment_data (equipment_id INTEGER, equipment_name TEXT);
                INSERT INTO unit_profile VALUES (1,'合成角色（夏日）'),(2,'合成角色（冬日）');
                INSERT INTO unit_skill_data VALUES (1,1,2,3,0),(2,4,5,0,0);
                INSERT INTO skill_data VALUES (1,'合成技能甲'),(2,'合成技能乙'),(3,'合成技能甲+'),
                    (4,'合成技能丙'),(5,'合成技能丁');
                INSERT INTO unit_unique_equipment VALUES (1,1,11);
                INSERT INTO unique_equipment_data VALUES (11,'合成专武一');
            ''')
        return path

    def test_shared_exact_costume_and_slot_data_has_no_account_fields(self):
        with TemporaryDirectory() as root:
            path = self.database(root)
            info = character('合成角色(夏日)', path)
            self.assertEqual(info['unique_slots'], {1: dict(id=11,name='合成专武一')})
            self.assertEqual(skill_names('合成角色(夏日)', path)['main_skill_evolution_1'], '合成技能甲+')
            self.assertEqual(len(costume_skills('合成角色', path)), 2)
            self.assertTrue(info['equipment_catalogue_complete'])
            self.assertTrue({'owned','unique','unique2','unique_level','unique2_stars'}.isdisjoint(info))
            self.assertIsNone(character('合成角色', path))

    def test_only_fresh_complete_metadata_rejects_impossible_source_before_ui(self):
        with TemporaryDirectory() as root:
            path = self.database(root)
            member = MemberRequirement('合成角色(夏日)', 1, 1, 1, unique=True, unique2=True)
            self.assertEqual([i['slot'] for i in equipment_requirement_issues([member], path,
                             verified_current=True)], [2])
            self.assertEqual(equipment_requirement_issues([member], path), [])
            report = dict(source=DB_SOURCE,version=1,checked_at=100,stale=False)
            formation = SimpleNamespace(database=str(path),character_database=report)
            with patch('pcrscript.tasks.party_preparation.time.time', return_value=110):
                self.assertEqual(len(catalogue_issues(formation,[member])),1)
                report['stale'] = True
                self.assertEqual(catalogue_issues(formation,[member]),[])
                report['stale'] = False
            with patch('pcrscript.tasks.party_preparation.time.time', return_value=100000):
                self.assertEqual(catalogue_issues(formation,[member]),[])

    def test_training_catalogue_includes_ub_and_ex_without_changing_identity_skills(self):
        with TemporaryDirectory() as root:
            path = self.database(root)
            before = skill_names('合成角色(夏日)',path)
            with closing(sqlite3.connect(path)) as conn:
                conn.executescript('''
                    ALTER TABLE unit_skill_data ADD COLUMN union_burst INTEGER;
                    ALTER TABLE unit_skill_data ADD COLUMN union_burst_evolution INTEGER;
                    ALTER TABLE unit_skill_data ADD COLUMN ex_skill_1 INTEGER;
                    ALTER TABLE unit_skill_data ADD COLUMN ex_skill_evolution_1 INTEGER;
                    INSERT INTO skill_data VALUES (6,'合成爆发'),(7,'合成爆发+'),
                        (8,'合成EX'),(9,'合成EX+');
                    UPDATE unit_skill_data SET union_burst=6,union_burst_evolution=7,
                        ex_skill_1=8,ex_skill_evolution_1=9 WHERE unit_id=1;
                ''')
            info = character('合成角色(夏日)',path)
            self.assertEqual(info['skills'],before)
            self.assertEqual(info['training_skills'],dict(before,union_burst='合成爆发',
                             union_burst_evolution='合成爆发+',ex_skill_1='合成EX',ex_skill_evolution_1='合成EX+'))
            self.assertNotIn('union_burst', character('合成角色(冬日)',path)['training_skills'])

    def test_updated_database_invalidates_cache_and_missing_tables_remain_unknown(self):
        with TemporaryDirectory() as root:
            path = self.database(root)
            before = path.stat().st_mtime_ns
            character('合成角色(夏日)', path)
            with closing(sqlite3.connect(path)) as conn:
                conn.execute("UPDATE skill_data SET name='更新后的技能' WHERE skill_id=1")
                conn.execute('DROP TABLE unit_unique_equipment')
                conn.commit()
            os.utime(path, ns=(before+1000000,before+1000000))
            self.assertEqual(skill_names('合成角色(夏日)',path)['main_skill_1'],'更新后的技能')
            info = character('合成角色(夏日)',path)
            self.assertFalse(info['equipment_catalogue_complete'])
            self.assertEqual(equipment_requirement_issues(
                [MemberRequirement(info['name'],1,1,1,unique2=True)],path,verified_current=True),[])

    def test_missing_database_is_not_created_and_duplicate_identity_is_unknown(self):
        with TemporaryDirectory() as root:
            missing = Path(root)/'missing.db'
            self.assertIsNone(character('合成角色', missing))
            self.assertFalse(missing.exists())
            path = self.database(root)
            with closing(sqlite3.connect(path)) as conn:
                conn.execute("INSERT INTO unit_profile VALUES (3,'合成角色（夏日）')")
                conn.commit()
            self.assertIsNone(character('合成角色(夏日)', path))
