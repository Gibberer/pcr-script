"""Synthetic phase guides and cumulative-boss acceptance."""
from unittest import TestCase
from tempfile import TemporaryDirectory
from pathlib import Path
from hashlib import sha256
import numpy as np
import cv2 as cv
from pcrscript.game_ui.avatars import AvatarIndex,face_crop
from pcrscript.tasks.tower_guides import (parse_guides, PhaseTrace, boss_hp_floor, declared_identity, phase_progress,
    with_support_trials,with_tank_trials,with_shadow_followups,prefer_untried,remembered_trials,trial_key,recognize_icon,carried_boss_hp)
from ui_fixtures import screen


class PhaseGuideTests(TestCase):
    def test_carried_real_hp_counts_damage_before_first_simulation_capture(self):
        target=dict(floor=30,hp=[0,0,0,0,70])
        battle=dict(simulate=False,after=target,hp_samples=[dict(seconds=1,hp=700000000)]*2)
        initial=carried_boss_hp([battle],target)
        self.assertEqual(initial,700000000)
        self.assertEqual(carried_boss_hp([dict(battle,hp_samples=battle['hp_samples'][-1:])],target),initial)
        trace=PhaseTrace('boss_damage',target,initial_hp=initial)
        trace.samples=[dict(seconds=t,hp=h) for t,h in [(80,690000000),(2,695000000),(1,685000000)]]
        self.assertTrue(trace.passed())
        self.assertIsNone(carried_boss_hp([dict(battle,simulate=True)],target))
        self.assertIsNone(carried_boss_hp([battle],dict(target,hp=[0,0,0,0,69])))

    def test_published_replacement_requires_unambiguous_target_and_complete_switches(self):
        cells=''.join('<td><img data-original="https://img.gamewith.jp/article_tools/pricone-re/gacha/'+str(i)+
            '_i.png" width="50px" alt="unit'+str(i)+'">ランク38<hr>即発動<hr>専用：360</td>' for i in range(5))
        base='<h2>頂上(123階)ボスの攻略編成例</h2><h3>フェーズ2</h3><h4>フルオート</h4><table>'+cells+'</table>'
        replacement=('<table><tr><th>代用キャラ例</th></tr><tr><th>'
            '<img data-original="https://img.gamewith.jp/article_tools/pricone-re/gacha/999_i.png" width="50px">代用甲</th>'
            '<td>陣形:中衛unit0と代用可能・unit0と入れ替え時、unit2以外SETで約1億</td></tr></table>')
        original,variant=parse_guides(base+replacement,123)
        self.assertEqual([m['instant'] for m in variant['members']],[True,True,False,True,True])
        self.assertEqual(variant['members'][0]['label'],'代用甲')
        annotated=replacement.replace('代用甲</th>','代用甲<br>コネクト：6</th>')
        self.assertEqual(parse_guides(base+annotated,123)[1]['members'][0]['label'],'代用甲')
        empty_outfit=replacement.replace('unit0と','unit0()と')
        self.assertEqual(len(parse_guides(base+empty_outfit,123)),2)
        self.assertEqual(variant['members'][0]['unique_level'],0)
        self.assertIsNone(variant['members'][0]['stars'])
        self.assertTrue(all(m['instant'] for m in original['members']))
        both=base.replace('<h4>',
            '<p>掲載編成はボスHP50%以下からでも削り可能です。</p><h4>')
        self.assertEqual([p['phase'] for p in parse_guides(both,123)],[2,3])
        self.assertEqual([p['phase'] for p in parse_guides(base,123)],[2])
        for altered in (replacement.replace('unit2以外','unknown以外'),
                        replacement.replace('約1億','手動0:39'),
                        replacement.replace('unit0と代用可能','unit1と代用可能')):
            self.assertEqual(len(parse_guides(base+altered,123)),1)
        other=replacement.replace('代用甲','代用乙').replace('unit0','unit1').replace('999_i','998_i')
        joined=replacement.replace('</table>',other.replace('<table>',''))
        combined=parse_guides(base+joined,123)
        self.assertEqual(len(combined),4)
        self.assertEqual([m['label'] for m in combined[-1]['members']][:2],['代用甲','代用乙'])
        conflict=joined.replace('unit1と入れ替え時、unit2以外','unit1と入れ替え時、unit3以外')
        self.assertEqual(len(parse_guides(base+conflict,123)),3)

    def test_previous_real_win_becomes_free_trial_not_current_win_proof(self):
        winner=dict(names=['甲','乙','丙','丁','戊'],instant={n:True for n in '甲乙丙丁戊'},
                    auto=True,outcome='win',floor=10)
        plan,=remembered_trials([winner],2)
        self.assertEqual(plan['goal'],'boss_damage')
        self.assertEqual(plan['instant'],winner['instant'])
        self.assertNotIn('passed',plan)
        self.assertEqual(remembered_trials([dict(winner,outcome='failed')],2),[])
        self.assertEqual(remembered_trials([winner],1),[])
        original,changed=remembered_trials([dict(winner,instant={n:False for n in winner['names']})],2)
        target=dict(floor=20,hp=[0,0,0,0,60])
        self.assertNotEqual(trial_key(original,target),trial_key(changed,target))
        reordered=dict(original,names=list(reversed(original['names'])))
        self.assertEqual(trial_key(original,target),trial_key(reordered,target))
        self.assertEqual(original['names'],changed['names'])
    def test_old_failure_is_demoted_without_blocking_changed_switches(self):
        first=dict(names=['甲','乙'],instant=dict(甲=True,乙=False))
        changed=dict(first,instant=dict(甲=True,乙=True))
        other=dict(names=['丙','丁'],instant=dict(丙=True,丁=True))
        ordered=prefer_untried([first,changed,other],[dict(first)])
        self.assertEqual(ordered,[changed,other,first])
    def test_residual_shadow_trials_prioritize_unused_public_parties(self):
        first=dict(phase=1,names=['甲','乙','丙','丁','戊'],instant=dict(甲=False),members=[dict(rank=38)])
        other=dict(phase=2,names=['己','庚','辛','壬','癸'],instant=dict(己=False),members=[dict(rank=38)])
        trial,*_=with_shadow_followups([first,other],{'甲','乙','丙','丁','戊'})
        self.assertEqual(trial['names'],other['names'])
        self.assertEqual(trial['instant'],other['instant'])
        self.assertEqual((trial['phase'],trial['goal'],trial['source_phase']),(1,'shadows',2))
        self.assertEqual(other['phase'],2)

    def test_declared_weapon_dependencies_prioritize_support_without_live_audits(self):
        names=['合成甲','合成乙','合成丙','合成丁','合成戊']
        plan=dict(phase=1,names=names,members=[dict(unique_level=360 if i in (1,3) else 0) for i in range(5)])
        roles={n:dict(position=800-i*100,role=6 if i==0 else 3) for i,n in enumerate(names)}
        first,second,_=with_support_trials([plan],roles,prefer=True)
        self.assertEqual([first['support'],second['support']],[names[1],names[3]])

    def test_geometric_identity_rejects_corrupt_or_ambiguous_references(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);(root/'icons').mkdir()
            icon=np.random.default_rng(9).integers(0,256,(96,96,3),dtype=np.uint8)
            icon=cv.GaussianBlur(icon,(3,3),.7)
            raw=cv.imencode('.webp',icon,[cv.IMWRITE_WEBP_QUALITY,101])[1].tobytes()
            (root/'icons'/'100111.webp').write_bytes(raw)
            index=AvatarIndex(root,load_existing=False)
            index.add('合成甲',face_crop(icon,(0,0,96,96)),persist=False)
            asset=dict(name='合成甲',icon_id=100111,sha256='corrupt')
            self.assertIsNone(recognize_icon(icon,index,dict(assets=[asset])))
            asset['sha256']=sha256(raw).hexdigest()
            self.assertEqual(recognize_icon(icon,index,dict(assets=[asset])),'合成甲')
            overlaid=icon.copy()
            overlaid[:20]=np.random.default_rng(11).integers(0,256,overlaid[:20].shape,dtype=np.uint8)
            overlaid[79:]=np.random.default_rng(12).integers(0,256,overlaid[79:].shape,dtype=np.uint8)
            self.assertEqual(recognize_icon(overlaid,index,dict(assets=[asset])),'合成甲')
            different=icon.copy()
            different[20:79,4:92]=np.random.default_rng(13).integers(0,256,different[20:79,4:92].shape,dtype=np.uint8)
            self.assertIsNone(recognize_icon(different,index,dict(assets=[asset])))
            (root/'icons'/'100211.webp').write_bytes(raw)
            index.add('合成乙',face_crop(icon,(0,0,96,96)),persist=False)
            other=dict(asset,name='合成乙',icon_id=100211)
            self.assertIsNone(recognize_icon(icon,index,dict(assets=[asset,other])))

    def test_survival_variants_keep_core_and_element_without_changing_source_switches(self):
        names=['合成甲','合成乙','合成丙','合成丁','合成戊']
        plan=dict(phase=1,names=names,instant={n:i!=1 for i,n in enumerate(names)})
        roles={n:dict(position=800-i*100,role=7 if i==4 else 3) for i,n in enumerate(names)}
        roles.update(替补甲=dict(position=100,role=7,tank=True),替补乙=dict(position=90,role=7,tank=True))
        talents={n:5 for n in names};talents.update(替补甲=5,替补乙=4)
        original,variant=with_tank_trials([plan],roles,talents)
        self.assertEqual(original,plan)
        self.assertEqual(variant['names'],names[:4]+['替补甲'])
        self.assertFalse(variant['instant']['合成乙'])
        self.assertTrue(variant['instant']['替补甲'])
        self.assertIn('本账号免费试验',variant['trial_reason'])

    def test_healing_role_is_used_when_skill_text_heuristic_misses_healing(self):
        plan=dict(phase=1,names=['合成甲','合成乙','合成丙','合成丁','合成戊'])
        roles={n:dict(position=800-i*100,role=6 if i==0 else 7 if i==4 else 3,heal=False)
               for i,n in enumerate(plan['names'])}
        first,second,last=with_support_trials([plan],roles,prefer=True)
        self.assertEqual(first['support'],'合成甲')
        self.assertEqual(second['support'],'合成戊')
        self.assertEqual(last,plan)

    def test_only_net_enemy_progress_counts_after_real_settlement(self):
        before=dict(floor=20,hp=[91]*5)
        self.assertTrue(phase_progress(before,dict(floor=20,hp=[0,0,0,0,91]),1))
        self.assertTrue(phase_progress(before,dict(floor=20,hp=[0,0,91,0,91]),1))
        self.assertFalse(phase_progress(before,dict(floor=20,hp=[90,90,91,91,91]),1))
        self.assertFalse(phase_progress(dict(floor=20,hp=[30,30,91,91,91]),
                                        dict(floor=20,hp=[60,0,91,91,91]),1))
        boss=dict(floor=20,hp=[0,0,0,0,60])
        self.assertFalse(phase_progress(boss,dict(floor=20,hp=[0,0,0,0,70]),2))
        self.assertFalse(phase_progress(boss,dict(floor=20,hp=[0,0,0,0,60]),2))
        self.assertTrue(phase_progress(boss,dict(floor=20,hp=[0,0,0,0,50]),2))

    def test_cross_region_names_require_unique_unit_and_outfit(self):
        profiles=[dict(unit_id=100101,unit_name='Synthetic'),dict(unit_id=100201,unit_name='Synthetic(Other)')]
        manifest=dict(assets=[dict(icon_id=100111,name='合成甲'),dict(icon_id=100131,name='合成甲'),
                              dict(icon_id=100211,name='合成乙')])
        self.assertEqual(declared_identity('Synthetic',profiles,manifest),'合成甲')
        self.assertEqual(declared_identity('Synthetic(Other)',profiles,manifest),'合成乙')
        self.assertIsNone(declared_identity('Synthetic(Unknown)',profiles,manifest))
        profiles.append(dict(unit_id=100301,unit_name='Synthetic'))
        self.assertIsNone(declared_identity('Synthetic',profiles,manifest))

    def test_only_explicit_five_switches_in_matching_floor(self):
        cells=''.join('<td><img data-original="https://img.gamewith.jp/article_tools/pricone-re/gacha/'+str(i)+
            '_i.png" width="50px" alt="unit'+str(i)+'">ランク38<hr>'+('即発動' if i else '-')+
            '<hr>専用：-</td>' for i in range(5))
        html='<h2>頂上(123階)ボスの攻略編成例</h2><h3>フェーズ1</h3><h4>フルオート</h4><table>'+cells+'</table>'
        self.assertEqual(parse_guides(html,124),[])
        plan,=parse_guides(html,123)
        self.assertEqual([m['instant'] for m in plan['members']],[False,True,True,True,True])
        self.assertEqual(plan['goal'],'shadows')
        self.assertEqual(parse_guides(html.replace('<hr>-<hr>','<hr>不明<hr>'),123),[])

    def test_temporary_damage_before_healing_is_not_phase_progress(self):
        trace=PhaseTrace('boss_damage')
        for seconds,hp in [(80,900000000),(40,500000000),(8,900000000),(6,900000000),(4,900000000)]:
            trace.samples.append(dict(seconds=seconds,hp=hp))
        self.assertFalse(trace.passed())
        for s in trace.samples[-3:]:s['hp']=800000000
        self.assertTrue(trace.passed())

    def test_first_hud_reading_after_heal_is_bounded_by_map_bar(self):
        healed=PhaseTrace('boss_damage',dict(floor=30,hp=[0,0,0,0,44]))
        healed.samples=[dict(seconds=t,hp=h) for t,h in [(85,600000000),(2,545000000),(1,540000000)]]
        self.assertFalse(healed.passed(settled=True))
        self.assertFalse(healed.passed())
        # A real settled knife from an 80px bar (HUD 865.6M -> 755.1M) still counts.
        real=PhaseTrace('boss_damage',dict(floor=30,hp=[0,0,0,0,80]))
        real.samples=[dict(seconds=t,hp=h) for t,h in [(88,865557900),(2,756000000),(1,755099843)]]
        self.assertTrue(real.passed(settled=True))
        for bar,hp in [(80,865557900),(70,748973103),(71,754763682),(62,647127763),(55,570577470),(91,1000000000)]:
            self.assertLess(boss_hp_floor(dict(hp=[0,0,0,0,bar])),hp)
        self.assertIsNone(boss_hp_floor(dict(hp=[0,0,0,0,0])))

    def test_top_phase_three_starts_at_the_bosss_half_hp(self):
        from pcrscript.tasks.tower_guides import top_phase, bar_hp
        self.assertEqual(top_phase(dict(hp=[16,23,13,34,91])),1)
        # 55px is ~567M; 46-49px (~459-495M) is already below half.
        self.assertEqual([top_phase(dict(hp=[0,0,0,0,b])) for b in (91,55,50,49,47,46,30)],[2,2,2,3,3,3,3])
        for bar,hp in [(80,865557900),(62,647127763),(55,570577470),(91,1000000000)]:
            self.assertLess(abs(bar_hp(bar)-hp),20000000)

    def test_final_two_readings_accept_partial_damage_after_full_battle(self):
        trace=PhaseTrace('boss_damage')
        trace.samples=[dict(seconds=t,hp=hp) for t,hp in
                       [(90,700000000),(3,698000000),(1,695000000),(1,680000000)]]
        self.assertTrue(trace.passed())
        trace.samples[-1]['hp']=710000000
        self.assertFalse(trace.passed())

    def test_completed_simulation_needs_no_repeated_final_second_frame(self):
        trace=PhaseTrace('boss_damage',initial_hp=700000000)
        trace.samples=[dict(seconds=t,hp=h) for t,h in [(80,695000000),(7,705000000),(1,680000000)]]
        self.assertFalse(trace.passed())
        self.assertTrue(trace.passed(settled=True))
        trace.samples=[dict(seconds=1,hp=680000000)]
        self.assertTrue(trace.passed(settled=True))
        trace.samples[-1]['hp']=710000000
        self.assertFalse(trace.passed(settled=True))
        trace.samples=trace.samples[:-1]
        self.assertFalse(trace.passed())

    def test_shadow_phase_does_not_require_full_boss_kill(self):
        trace=PhaseTrace('shadows')
        trace.samples=[dict(seconds=90,hp=1000000000)]+[dict(seconds=t,hp=970000000) for t in (30,25,20)]
        self.assertTrue(trace.passed())
        trace.samples[1:]=[dict(seconds=t,hp=999999000) for t in (30,25,20)]
        self.assertFalse(trace.passed())

    def test_partial_shadow_goal_requires_late_net_damage(self):
        trace=PhaseTrace('shadows',dict(hp=[91]*5))
        trace.samples=[dict(seconds=t,hp=1000000000) for t in (20,12,7)]
        trace.shadow_samples=[dict(seconds=t,bars=[dict(fill=.4)]*2) for t in (20,12,7)]
        self.assertTrue(trace.passed())
        trace.shadow_samples=[dict(seconds=t,bars=[dict(fill=.4)]*2) for t in (20,18,17)]
        self.assertFalse(trace.passed())
        trace.shadow_samples=[dict(seconds=7,bars=[dict(fill=.95)]*2)]
        self.assertFalse(trace.passed())
        damaged=PhaseTrace('shadows',dict(hp=[0,0,91,91,91]))
        self.assertEqual(damaged.shadow_missing,0)
        self.assertEqual(damaged.shadow_goal,.5)
        damaged=PhaseTrace('shadows',dict(hp=[16,23,13,34,91]))
        sample=dict(seconds=11,bars=[dict(fill=.01),dict(fill=.04)])
        self.assertGreater(damaged.shadow_gain(sample),damaged.shadow_goal)
        # The same observed subset with no new damage cannot pass.
        self.assertLess(damaged.shadow_gain(dict(bars=[dict(fill=13/91),dict(fill=16/91)])),1e-8)
        self.assertTrue(phase_progress(dict(floor=20,hp=[0,0,0,3,91]),
                                       dict(floor=20,hp=[0,0,0,0,91]),1))

    def test_shadow_bars_require_borders_and_continuous_orange_fill(self):
        from pcrscript.game_ui.tower import shadow_bars
        frame=screen(background=0)
        for x,y in ((400,240),(600,300)):
            frame.image[y:y+8,x:x+62]=0
            frame.image[y,x:x+62]=255
            frame.image[y+7,x:x+62]=255
            frame.image[y+2:y+6,x:x+25]=(30,140,230)
        bars=shadow_bars(frame)
        self.assertEqual(len(bars),2)
        self.assertAlmostEqual(bars[0]['fill'],25/62)
        frame.image[307,600:662]=0
        self.assertEqual(len(shadow_bars(frame)),1)

    def test_only_high_confidence_battle_hud_is_sampled(self):
        trace=PhaseTrace('shadows')
        frame=screen(('菜单',900,25),('1:10',800,25),('990000000/1000000000',600,49))
        trace.observe(frame)
        self.assertEqual(trace.samples,[dict(seconds=70,hp=990000000)])
        frame=screen(('1:10',800,25),('990000000/1000000000',600,49))
        trace.observe(frame)
        self.assertEqual(len(trace.samples),1)
        for value in ('.999999998/1000000000','999999998/1000000000X','95/1000000000'):
            trace.observe(screen(('菜单',900,25),('1:10',800,25),(value,600,49)))
        self.assertEqual(len(trace.samples),1)
