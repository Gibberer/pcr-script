"""Synthetic Dawn Labyrinth pages shared by sweep and first-clear tests."""
import cv2 as cv

from ui_fixtures import screen


def home(passes=3):
    return screen(('黎明界迷宫', 130, 30), ('出发', 590, 302),
                  ('持有通行证', 555, 337), (f'{passes}/99', 660, 337))


def guild(*extra):
    return screen(('黎明界迷宫', 130, 30), ('请选择要同行的公会。', 480, 88),
                  ('跳过', 912, 65), ('选择', 144, 422), *extra)


def preview(before=3, after=2):
    return screen(('跳过确认', 480, 42), ('通行证持有数', 350, 330),
                  (str(before), 635, 330), ('→', 665, 330), (str(after), 695, 330),
                  ('跳过', 585, 480), ('取消', 370, 480), blue=('跳过',))


def separate_guilds(*names, disabled=(), action='跳过'):
    labels = [('黎明界迷宫', 130, 30), ('请选择要跳过的公会', 480, 88)]
    for index, name in enumerate(names):
        x = 144+269*index
        labels.extend(((name, x, 352), (action, x, 422)))
    value = screen(*labels)
    for index, name in enumerate(names):
        if name not in disabled:
            x = 144+269*index
            cv.rectangle(value.image, (x-50, 398), (x+50, 446), (230, 155, 25), -1)
    return value


def named_preview(name, before=1, after=0):
    value = preview(before, after)
    value.items.extend(screen((name, 480, 200)).items)
    return value


def result():
    return screen(('跳过结果', 480, 42), ('获得了以下报酬', 480, 130), ('确认', 480, 480))


def mission_home(passes=0, badge=True):
    value = home(passes)
    value.items.extend(screen(('任务', 874, 257)).items)
    if badge:
        cv.ellipse(value.image, (927, 226), (21, 10), 0, 0, 360, (110, 40, 245), -1)
    return value


def missions(claim=True, selected=True, title='完成合成迷宫任务'):
    value = screen(('任务', 480, 42), ('全部', 190, 88), ('普通', 480, 88), ('公会', 774, 88),
                  ('已超过持有数上限的道具将被送往礼物箱。', 480, 427),
                  ('取消', 367, 475), ('全部收取', 592, 475),
                  blue=tuple((['全部'] if selected else [])+(['全部收取'] if claim else [])))
    if title:
        row = screen((title,300,180),('1/1',650,180),('收取',840,180),
                     blue=('收取',) if claim else ())
        value.items.extend(row.items)
        value.image[140:220]=row.image[140:220]
    return value


def mission_receipt():
    return screen(('收取报酬', 480, 42), ('获得了以下报酬。', 480, 80),
                  ('合成奖励', 450, 210), ('关闭', 480, 480))


def catalogue(before=3, quantity=1, selected=True, after=None):
    after = before-quantity if selected and after is None else after
    value = screen(('可跳过的公会一览', 480, 42), ('美食殿堂', 92, 152),
                   ('黎明界迷宫', 115, 179), ('解除所有勾选', 850, 110),
                   ('通行证', 85, 430), (str(before), 250, 432),
                   (str(after) if after is not None else '-', 353, 432),
                   ('通行证使用数量', 540, 420), (str(quantity), 766, 414),
                   ('MIN', 642, 414), ('MAX', 884, 414),
                   ('取消', 584, 477), ('一键扫荡', 810, 476), blue=('一键扫荡',))
    if selected:
        cv.rectangle(value.image, (832, 148), (868, 179), (230, 155, 25), -1)
    return value


def bulk(before=3, cost=1, row_quantity=None, total=None, guild_name='美食殿堂'):
    return screen(('键扫荡确认', 480, 42),
                  ('即将消耗通行证，对以下公会及难度执行跳过操作。确定吗？', 480, 80),
                  (guild_name, 92, 119), ('黎明界迷宫', 115, 146),
                  (str(cost if row_quantity is None else row_quantity), 880, 144),
                  ('合计扫荡次数', 840, 365), ('消耗通行证', 108, 405),
                  ('通行证', 300, 405), (str(cost), 254, 405), (str(before), 465, 405),
                  (str(cost if total is None else total), 884, 398),
                  ('取消', 370, 480), ('挑战', 588, 480), blue=('挑战',))
