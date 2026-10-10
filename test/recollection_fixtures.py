"""Synthetic sweep selectors shared by cross-task navigation regressions."""
from ui_fixtures import screen


def sweep_selector(confirmation=False):
    if confirmation:
        return screen(('一键扫荡确认', 480, 42), ('将消耗扫荡券，执行以下关卡。', 480, 80),
                      ('合计扫荡次数', 840, 350), ('取消', 370, 480), ('挑战', 590, 480))
    return screen(('关卡一览', 480, 42), ('1个关卡的使用券张数', 600, 385),
                  ('取消', 370, 480), ('一键扫荡', 590, 480))
