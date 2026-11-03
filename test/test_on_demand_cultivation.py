"""On-demand stars and first unique equipment, driven by synthetic screens."""
from unittest import TestCase
from unittest.mock import Mock, patch

from ui_fixtures import screen

from pcrscript.game_ui.character_equipment import install_missing_unique, unique_missing
from pcrscript.game_ui.screen import EventUIError
from pcrscript.tasks.event_strategy import MemberRequirement
from pcrscript.tasks.party_preparation import cultivate_on_demand


def equipment_page(*extra):
    return screen(('角色强化', 120, 30), ('获取方法', 590, 435), ('装备', 803, 435), *extra)


def installed_page():
    return screen(('角色强化', 120, 30), ('强化', 803, 435))


def member(name='合成角色', stars=None, unique=None):
    return MemberRequirement(name, None, None, stars, unique, None, True, None)


class InstallMissingUniqueTests(TestCase):
    def install(self, *waits, captures=()):
        ui = Mock()
        ui.wait.side_effect = list(waits)
        ui.capture.side_effect = list(captures)
        report = {}
        with patch('pcrscript.game_ui.character_equipment.open_character_memory', return_value=object()), \
             patch('pcrscript.game_ui.character_equipment.time.sleep'):
            result = install_missing_unique(ui, '合成角色', report, Mock(), Mock())
        return result, report, ui

    def test_uninstalled_layout_requires_both_page_buttons(self):
        self.assertTrue(unique_missing(equipment_page()))
        self.assertFalse(unique_missing(installed_page()))
        self.assertFalse(unique_missing(screen(('获取方法', 590, 435), ('装备', 803, 435))))

    def test_unreleased_slot_is_not_missing(self):
        self.assertFalse(unique_missing(equipment_page(('此专用装备1预定今后登场。', 695, 332))))
        result, report, ui = self.install(equipment_page(('此专用装备1预定今后登场。', 695, 332)))
        self.assertEqual(result, 'not_needed')
        self.assertNotIn('unique_installs', report)
        ui.expect_click.assert_called_once()  # only the tab that opens this page

    def test_already_installed_or_unreleased_changes_nothing(self):
        result, report, ui = self.install(installed_page())
        self.assertEqual(result, 'not_needed')
        self.assertNotIn('unique_installs', report)
        ui.click.assert_not_called()

    def test_other_missing_material_cancels_without_buying_or_orbs(self):
        panel = screen(('装备获取', 480, 42), ('素材不足。', 490, 430), ('取消', 153, 478), ('制作', 805, 478))
        with patch('pcrscript.game_ui.screen.EventScreen.blue_button', return_value=False), \
             patch('pcrscript.game_ui.character_equipment.recipe_other_material_ready', return_value=False), \
             patch('pcrscript.game_ui.character_stars.buy_from_open_shop') as buy:
            result, report, ui = self.install(equipment_page(), panel)
        self.assertEqual(result, 'insufficient_material')
        self.assertEqual(report['unique_installs'][0]['status'], 'insufficient_material')
        buy.assert_not_called()
        ui.click.assert_not_called()
        self.assertEqual(ui.expect_click.call_args_list[-1].args[0], '取消')

    def test_first_slot_buys_the_fragment_gap_then_crafts_and_installs(self):
        lacking = screen(('装备获取', 480, 42), ('素材不足。', 490, 430), ('取消', 153, 478), ('制作', 805, 478))
        shop_row = screen(('女神的秘石商店', 730, 212))
        shop = screen(('商店', 100, 30))
        ready = screen(('装备获取', 480, 42), ('取消', 153, 478), ('制作', 805, 478))
        confirm = screen(('确认', 590, 470))
        states = dict(crafted=False)
        def blue(page, item):
            if item is None:
                return False
            return states['crafted'] if item.text == '装备' else item.text == '制作' and not page.find('素材不足')
        def click(target, *a, **k):
            if getattr(target, 'text', '') == '制作':
                states['crafted'] = True
        ui = Mock()
        ui.click.side_effect = click
        ui.wait.side_effect = [equipment_page(), lacking, shop_row, shop, equipment_page(), ready]
        ui.capture.side_effect = [equipment_page(), confirm, installed_page(), installed_page()]
        report, home = {}, Mock()
        with patch('pcrscript.game_ui.character_equipment.open_character_memory', return_value=object()), \
             patch('pcrscript.game_ui.character_equipment.time.sleep'), \
             patch('pcrscript.game_ui.character_equipment.recipe_other_material_ready', return_value=True), \
             patch('pcrscript.game_ui.screen.EventScreen.blue_button', blue), \
             patch('pcrscript.game_ui.character_stars.buy_from_open_shop') as buy:
            result = install_missing_unique(ui, '合成角色', report, Mock(), home)
        self.assertEqual(result, 'installed')
        buy.assert_called_once()
        self.assertEqual(buy.call_args.kwargs['total'], 50)
        home.assert_called_once()
        self.assertEqual(report['unique_installs'][0]['status'], 'installed')

    def test_second_slot_shortage_gives_up_and_reports_to_the_user(self):
        lacking = screen(('装备获取', 480, 42), ('素材不足。', 490, 430), ('取消', 153, 478), ('制作', 805, 478))
        ui = Mock()
        ui.wait.side_effect = [installed_page(), lacking]
        ui.capture.return_value = equipment_page()
        report = {}
        with patch('pcrscript.game_ui.character_equipment.open_character_memory', return_value=object()), \
             patch('pcrscript.game_ui.character_equipment.time.sleep'), \
             patch('pcrscript.game_ui.character_equipment.second_unique_selector', return_value=(320, 110)), \
             patch('pcrscript.game_ui.character_equipment.recipe_other_material_ready', return_value=True), \
             patch('pcrscript.game_ui.screen.EventScreen.blue_button', return_value=False), \
             patch('pcrscript.game_ui.character_stars.buy_from_open_shop') as buy:
            result = install_missing_unique(ui, '合成角色', report, Mock(), Mock())
        self.assertEqual(result, 'insufficient_material')
        buy.assert_not_called()
        self.assertIn('专武2素材不足', report['needs_user'][0])

    def test_guide_forbidding_the_second_slot_leaves_it_empty(self):
        ui = Mock()
        ui.wait.side_effect = [installed_page()]
        report = {}
        with patch('pcrscript.game_ui.character_equipment.open_character_memory', return_value=object()), \
             patch('pcrscript.game_ui.character_equipment.second_unique_selector', return_value=(320, 110)) as selector:
            result = install_missing_unique(ui, '合成角色', report, Mock(), Mock(), second=False)
        self.assertEqual(result, 'not_needed')
        selector.assert_not_called()
        ui.click.assert_not_called()

    def test_lit_frame_marks_the_other_material_as_ready(self):
        from pcrscript.game_ui.character_equipment import recipe_other_material_ready
        page = screen(('装备获取', 480, 42))
        self.assertFalse(recipe_other_material_ready(page))
        page.image[304:309, 716:780] = (40, 215, 245)
        self.assertTrue(recipe_other_material_ready(page))

    def test_crafts_then_equips_and_confirms_the_final_page(self):
        panel = screen(('装备获取', 480, 42), ('取消', 153, 478), ('制作', 805, 478))
        dialog = screen(('确认', 590, 470))
        states = {'ready': False}
        def blue(page, item):
            return states['ready'] if item is not None and item.text == '装备' else item is not None
        def click(target, *a, **k):
            if getattr(target, 'text', '') == '确认':
                states['ready'] = True
        ready = equipment_page()
        with patch('pcrscript.game_ui.screen.EventScreen.blue_button', blue):
            ui = Mock()
            ui.click.side_effect = click
            ui.wait.side_effect = [equipment_page(), panel]
            ui.capture.side_effect = [dialog, ready, dialog, installed_page(), installed_page()]
            report = {}
            with patch('pcrscript.game_ui.character_equipment.open_character_memory', return_value=object()), \
                 patch('pcrscript.game_ui.character_equipment.time.sleep'):
                result = install_missing_unique(ui, '合成角色', report, Mock(), Mock())
        self.assertEqual(result, 'installed')
        self.assertEqual(report['unique_installs'][0]['status'], 'installed')
        self.assertEqual([getattr(c.args[0], 'text', '') for c in ui.click.call_args_list],
                         ['制作', '确认', '装备', '确认'])

    def test_unknown_dialog_stays_stopped_after_a_bounded_wait(self):
        panel = screen(('装备获取', 480, 42), ('取消', 153, 478), ('制作', 805, 478))
        ui = Mock()
        ui.wait.side_effect = [equipment_page(), panel]
        ui.capture.return_value = screen(('未知页面', 480, 42))
        with patch('pcrscript.game_ui.character_equipment.open_character_memory', return_value=object()), \
             patch('pcrscript.game_ui.character_equipment.time.sleep'), \
             patch('pcrscript.game_ui.screen.EventScreen.blue_button',
                   lambda page, item: item is not None and item.text == '制作'), \
             self.assertRaisesRegex(EventUIError, '回执未确认'):
            install_missing_unique(ui, '合成角色', {}, Mock(), Mock())


class CultivateOnDemandTests(TestCase):
    def run_with(self, members, stars, unique='not_needed', upgrade=None, page=None):
        report = {}
        home = Mock()
        with patch('pcrscript.game_ui.character_equipment.open_character_memory',
                   return_value=page or screen(('合成角色的记忆碎片', 570, 130))), \
             patch('pcrscript.game_ui.character_stars.unlocked_stars', return_value=stars), \
             patch('pcrscript.game_ui.character_stars.upgrade_to_five', side_effect=upgrade) as raise_stars, \
             patch('pcrscript.game_ui.character_equipment.install_missing_unique', return_value=unique) as install:
            changed = cultivate_on_demand(Mock(), members, report=report, save=Mock(), home=home)
        return changed, report, raise_stars, install

    def test_low_stars_rise_and_count_as_a_change(self):
        changed, report, raise_stars, install = self.run_with([member()], 3)
        self.assertEqual(changed, ['合成角色'])
        raise_stars.assert_called_once()
        install.assert_called_once()
        self.assertEqual(report['on_demand_cultivation'][0]['stars_after'], 5)

    def test_explicit_low_stars_and_six_stars_are_untouched(self):
        for stars, required in ((3, 3), (6, None), (5, None)):
            with self.subTest(stars=stars, required=required):
                changed, _, raise_stars, _ = self.run_with([member(stars=required)], stars)
                self.assertEqual(changed, [])
                raise_stars.assert_not_called()

    def test_bloom_page_text_overrides_a_misread_star_row(self):
        for page in (screen(('合成角色的纯净记忆碎片', 560, 130)),
                     screen(('合成角色的记忆碎片', 570, 130), ('该角色已才能开花至最高★级', 700, 330))):
            changed, report, raise_stars, _ = self.run_with([member()], 4, page=page)
            self.assertEqual(changed, [])
            raise_stars.assert_not_called()
            self.assertEqual(report['on_demand_cultivation'][0]['stars'], 'max')

    def test_guide_without_unique_keeps_it_uninstalled(self):
        _, _, _, install = self.run_with([member(unique=False)], 5)
        install.assert_not_called()

    def test_guide_unique2_limit_reaches_the_installer(self):
        _, _, _, install = self.run_with([MemberRequirement('合成角色', None, None, None, True, False, True, None)], 5)
        self.assertIs(install.call_args.kwargs['second'], False)
        _, _, _, install = self.run_with([member()], 5)
        self.assertIs(install.call_args.kwargs['second'], True)

    def test_installed_unique_counts_but_missing_material_does_not(self):
        self.assertEqual(self.run_with([member()], 5, 'installed')[0], ['合成角色'])
        self.assertEqual(self.run_with([member()], 5, 'insufficient_material')[0], [])

    def test_one_member_failure_is_recorded_and_others_continue(self):
        calls = [EventUIError('合成材料不足'), None]
        changed, report, _, _ = self.run_with([member('甲'), member('乙')], 3, upgrade=calls)
        self.assertEqual(changed, ['乙'])
        self.assertEqual(report['on_demand_cultivation'][0]['error'], '合成材料不足')
