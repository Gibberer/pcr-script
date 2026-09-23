"""Shop purchases with page and transaction checks."""
from __future__ import annotations

import re
from typing import Any

from .base import BaseTask
from .registry import register
from ..game_ui.screen import EventScreen, EventUI, EventUIError, normalized


SHOP_TABS = {
    1: "通常", 2: "地下城", 3: "竞技场", 4: "公主竞技场",
    5: "行会", 6: "大师", 7: "连结", 8: "女神的秘石", 9: "限定",
}
HEADER = (90, 50, 950, 94)
BOTTOM = (645, 413, 930, 465)


def selected_tab(screen: EventScreen, item: Any) -> bool:
    """The selected shop tab has a blue fill above its caption."""
    x, _ = item.center
    blue, green, red = map(int, screen.image[58, x])
    return blue - red > 75 and blue - green > 45


def amount(screen: EventScreen, roi: tuple[int, int, int, int]) -> int | None:
    item = screen.find(r"\d[\d,]+", roi, exact=True)
    return int(normalized(item.text).replace(",", "")) if item else None


def mana_receipt(screen: EventScreen, cost: int, balance_before: int | None) -> dict[str, int]:
    spent = screen.find(r"消耗玛那[×xX][\d,]+", (360, 60, 590, 105), exact=True)
    actual_cost = int(re.search(r"[\d,]+$", normalized(spent.text)).group().replace(",", "")) if spent else None
    receipt_before = amount(screen, (425, 345, 560, 400))
    receipt_after = amount(screen, (570, 345, 710, 400))
    if (actual_cost != cost or receipt_before is None or receipt_after is None
            or receipt_before - receipt_after != cost
            or (balance_before is not None and receipt_before != balance_before)):
        raise EventUIError("购买已提交，但玛那回执与选中金额不一致；请核对记录，勿立即重试")
    return {"balance_before": receipt_before, "balance_after": receipt_after}


def parse_rule(rule: dict) -> dict[int, list[int]]:
    if not isinstance(rule, dict):
        raise ValueError("shop_buy 规则必须是对象")
    settings: dict[int, dict] = {}
    items: dict[int, list[int]] = {}
    for key, value in rule.items():
        text = str(key)
        if text.endswith("_settings"):
            tab = int(text.removesuffix("_settings"))
            if not isinstance(value, dict):
                raise ValueError(f"商店 {tab} 的设置必须是对象")
            settings[tab] = value
        else:
            tab = int(text)
            if not isinstance(value, list) or not all(isinstance(i, int) for i in value):
                raise ValueError(f"商店 {tab} 的商品必须是整数列表")
            items[tab] = value
    for tab in set(items) | set(settings):
        if tab not in SHOP_TABS:
            raise ValueError(f"未知商店序号 {tab}")
        option = settings.get(tab, {})
        if int(option.get("time", 1)) != 1:
            raise ValueError("商店自动刷新尚未适配新版界面；请将 time 设为 1")
        positions = items.get(tab, [])
        if -1 in positions and (tab not in (1, 9) or positions != [-1]):
            raise ValueError("全选仅支持通常和限定商店，且不能与单品规则混用")
        if len(set(positions)) != len(positions):
            raise ValueError("商店商品序号不能重复")
        if any(i < 1 or i > 4 for i in positions if i != -1):
            raise ValueError("新版商店目前只支持首屏 1～4 号商品；超出范围的规则需重新核对")
    return items


@register("shop_buy", requires_home=True)
class ShopBuy(BaseTask):
    """Buy configured goods after checking the active tab and total cost."""

    def __init__(self, robot):
        super().__init__(robot)
        output = getattr(robot, "_task_output", None) or "cache/daily/shop"
        self.ui = EventUI(robot.driver, output)

    def shop(self) -> EventScreen:
        return self.ui.wait(lambda s: s.find("商店", (42, 0, 145, 55), exact=True)
                            and s.find("通常", HEADER, exact=True)
                            and s.find("限定", HEADER, exact=True), "商店页面")

    def enter(self) -> EventScreen:
        s = self.ui.wait(lambda s: s.find("商店", (625, 390, 755, 480), exact=True), "首页商店入口")
        self.ui.click(s.find("商店", (625, 390, 755, 480), exact=True))
        return self.shop()

    def choose_tab(self, tab: int) -> EventScreen:
        label = SHOP_TABS[tab]
        s = self.shop()
        item = s.find(re.escape(label), HEADER, exact=True)
        if item is None:
            raise EventUIError(f"没有识别到{label}商店标签")
        if not selected_tab(s, item):
            self.ui.click(item)
            s = self.ui.wait(lambda s: (label_item := s.find(re.escape(label), HEADER, exact=True))
                             is not None and selected_tab(s, label_item), f"切换到{label}商店")
        return s

    def clear_selection(self, s: EventScreen) -> EventScreen:
        clear = s.find("全部解除", (500, 415, 660, 460), exact=True)
        if clear:
            self.ui.click(clear)
            s = self.ui.wait(lambda s: not s.find("全部解除", (500, 415, 660, 460), exact=True), "清除旧选择")
        return s

    def select(self, tab: int, positions: list[int]) -> EventScreen | None:
        s = self.clear_selection(self.choose_tab(tab))
        if tab in (1, 9):
            all_category = s.find("全部", (610, 105, 785, 145), exact=True)
            if all_category is None:
                raise EventUIError(f"{SHOP_TABS[tab]}商店缺少全部分类")
            self.ui.click(all_category)
            s = self.shop()
        if positions == [-1]:
            select_all = s.find("全选", (790, 105, 930, 145), exact=True)
            if select_all is None:
                raise EventUIError("没有识别到商店全选按钮")
            self.ui.click(select_all)
        else:
            for pos in positions:
                self.ui.click((388 + (pos - 1) * 170, 190), delay=.3)
        s = self.shop()
        purchase = s.find(r"批量购入[\d,]+", BOTTOM)
        if purchase is None:
            if positions == [-1] and s.find("已售罄", (245, 155, 920, 390)):
                return None
            self.ui.save(f"shop_{tab}_selection_failed", s)
            raise EventUIError(f"{SHOP_TABS[tab]}商店选择后未出现批量购入；未执行购买")
        if not s.blue_button(purchase):
            raise EventUIError("商店批量购入按钮不可用")
        return s

    def buy(self, tab: int, s: EventScreen) -> dict:
        item = s.find(r"批量购入[\d,]+", BOTTOM)
        cost = int(re.search(r"[\d,]+", normalized(item.text)).group().replace(",", ""))
        if cost <= 0:
            raise EventUIError("商店购买金额无效")
        balance_before = amount(s, (780, 5, 935, 48)) if tab in (1, 9) else None
        self.ui.save(f"shop_{tab}_before_purchase", s)
        self.ui.click(item)
        s = self.ui.wait(lambda s: s.find("购买完毕|购买确认|确认购买|购买商品", (235, 15, 725, 90)), "商店购买弹窗", timeout=20)
        if not s.find("购买完毕", (235, 15, 725, 90)):
            self.ui.save(f"shop_{tab}_purchase_confirmation", s)
            body = normalized(s.text((250, 60, 710, 420))).replace(",", "")
            if str(cost) not in body:
                raise EventUIError("商店确认弹窗总价与已选商品不符，未确认购买")
            confirm = s.find("确认|购买", (365, 425, 600, 515), exact=True)
            if confirm is None or not s.blue_button(confirm):
                raise EventUIError("商店确认购买按钮无法核对")
            self.ui.click(confirm)
            s = self.ui.wait(lambda s: s.find("购买完毕", (235, 15, 725, 90)), "购买结果", timeout=20)
        self.ui.save(f"shop_{tab}_purchase_result", s)
        receipt = mana_receipt(s, cost, balance_before) if tab in (1, 9) else {}
        close = s.find("确认|关闭", (355, 435, 605, 515), exact=True)
        if close is None:
            raise EventUIError("购买结果没有可识别的关闭按钮")
        self.ui.click(close)
        self.shop()
        return {"shop": SHOP_TABS[tab], "cost": cost, **receipt}

    def run(self, rule: dict):
        parsed = parse_rule(rule)
        self.enter()
        report = {"purchased": [], "skipped": []}
        for tab, positions in parsed.items():
            if not positions:
                continue
            s = self.select(tab, positions)
            if s is None:
                report["skipped"].append(SHOP_TABS[tab])
                continue
            report["purchased"].append(self.buy(tab, s))
        return report
