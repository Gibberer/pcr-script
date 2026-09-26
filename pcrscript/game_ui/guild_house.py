"""Collect already produced Guild House stamina through observed UI labels."""
from __future__ import annotations

from .screen import EventUI, EventUIError, normalized


def visible_stamina(screen) -> int | None:
    if not screen.find('体力', (400, 0, 650, 50), exact=True):
        return None
    label = screen.find(r'\d+/\d+', (455, 0, 700, 50), exact=True)
    return int(normalized(label.text).split('/')[0]) if label else None


def collect_produced_stamina(ui: EventUI, abyss_map) -> dict:
    """Enter from a verified deep-area map; never use a stamina refill dialog."""
    entry = abyss_map.find('公会之家', (580, 485, 725, 540), exact=True)
    if entry is None:
        raise EventUIError('深域底栏未确认公会之家入口')
    ui.click(entry)

    def house_or_notice(screen):
        return bool(screen.find('附加效果家具', (350, 0, 620, 70), exact=True)
                    or screen.find('全部收取', (820, 415, 955, 475), exact=True))

    house = ui.wait(house_or_notice, '公会之家家具领取入口')
    if house.find('附加效果家具', (350, 0, 620, 70), exact=True):
        close = house.find('关闭', (390, 445, 560, 510), exact=True)
        if close is None:
            raise EventUIError('公会之家家具提示关闭按钮未知')
        ui.click(close)
        house = ui.wait(lambda s: s.find('全部收取', (820, 415, 955, 475), exact=True),
                        '公会之家全部收取')
    before = visible_stamina(house)
    collect = house.find('全部收取', (820, 415, 955, 475), exact=True)
    if before is None or collect is None:
        raise EventUIError('公会之家体力或全部收取按钮未确认')
    ui.save('guild_house_before_collect', house)
    ui.click(collect)
    receipt = ui.wait(lambda s: s.find('全部收取', (350, 0, 610, 65), exact=True)
                      and s.find('收取了以下道具', (330, 55, 650, 115)),
                      '公会之家领取回执')
    ui.save('guild_house_collect_receipt', receipt)
    if not receipt.find(r'体力[×xX]\d+', (285, 105, 670, 445)):
        raise EventUIError('公会之家领取回执没有可确认的体力')
    close = receipt.find('关闭', (385, 445, 565, 510), exact=True)
    if close is None:
        raise EventUIError('公会之家领取回执关闭按钮未知')
    ui.click(close)
    after_screen = ui.wait(lambda s: s.find('全部收取', (820, 415, 955, 475), exact=True),
                           '公会之家领取后状态')
    after = visible_stamina(after_screen)
    ui.save('guild_house_after_collect', after_screen)
    if after is None or after <= before:
        raise EventUIError('公会之家体力未确认增加')
    return dict(before=before, after=after)
