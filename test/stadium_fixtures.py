"""Synthetic stadium pages; no account images or real strategies."""
import cv2 as cv

from ui_fixtures import screen


def home(*, stars=0, unlocked=1, total=18, first=1, round_stars=(0, 0, 0)):
    labels = [('斗技场', 100, 30), ('进度', 450, 32), (str(unlocked), 560, 32),
              (f'/{total}解锁', 603, 32), (str(stars), 677, 32),
              (f'/{total*3}获得', 720, 32), ('报酬', 901, 450),
              ('举办时间:10/0912:00~10/1323:59', 220, 70)]
    for i in range(min(3, total-first+1)):
        labels.append((f'回合{first+i}', 195+i*282, 340))
    s = screen(*labels)
    for i in range(min(3, total-first+1)):
        if round_stars[i] is None:
            continue
        for j in range(3):
            x = 198+i*282+(j-1)*28
            color = (20, 195, 245) if j < round_stars[i] else (200, 155, 100)
            cv.rectangle(s.image, (x-9, 295), (x+9, 315), color, -1)
    return s


def reward_page(targets=(3, 6, 9), *, received=False, claimable=False):
    labels = [('★获得任务', 480, 42), ('取消', 360, 475), ('全部收取', 590, 475)]
    for i, target in enumerate(targets):
        labels += [(f'斗技场累计获得{target}个★吧', 330, 94+i*128)]
        labels += ([('已完成', 84, 126+i*128), (f'{target}/{target}', 280, 126+i*128)] if received
                   else [('收取', 842, 150+i*128)])
    return screen(*labels, blue=('全部收取', '收取') if claimable else ())


def reward_receipt():
    return screen(('收取报酬', 480, 42), ('收取了以下道具。', 480, 135), ('确认', 480, 480))


def detail():
    return screen(('编组详情', 90, 50), ('回合1', 200, 50), ('挑战目标', 130, 322),
                  ('战斗效果', 680, 335), ('剩余时间1:00以上获胜', 235, 348),
                  ('我方总生命值80%以上获胜', 235, 375),
                    ('我方总生命值60%以上获胜', 235, 399),
                  ('取消', 650, 450), ('挑战', 830, 450), blue=('挑战',))


def formation():
    return screen(('队伍编组', 480, 42), ('对战对手的队伍', 485, 88),
                  ('战斗效果', 140, 88), ('取消', 650, 450),
                  ('战斗开始', 850, 455), blue=('战斗开始',))


def battle_result():
    return screen(('WIN', 480, 180), ('前往斗技场', 830, 480), blue=('前往斗技场',))
