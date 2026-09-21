"""Recognition for the caravan board, in 960 x 540 coordinates."""
import re
import cv2 as cv
import numpy as np
from .screen import normalized, EventScreen


def board(screen: EventScreen) -> bool:
    return bool(screen.find('驾车游', (45, 0, 180, 65))
                and screen.find('经过回合', (0, 140, 245, 230))
                and (screen.find('投骰子', (805, 385, 945, 435))
                     or (screen.find('同时掷3个', (760, 425, 945, 465))
                         and screen.find('食用料理', (700, 390, 800, 425)))))


def triple_mode(screen: EventScreen) -> bool | None:
    """Blue = enabled; white = disabled. Unknown must never authorize a roll."""
    hsv = cv.cvtColor(screen.image[429:455, 818:903], cv.COLOR_BGR2HSV)
    blue = np.mean((hsv[:, :, 0] > 85) & (hsv[:, :, 0] < 125)
                   & (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 150))
    white = np.mean((hsv[:, :, 1] < 45) & (hsv[:, :, 2] > 190))
    if blue > .25:
        return True
    if white > .45:
        return False
    return None


def disabled_roll(screen: EventScreen) -> bool:
    """The white die is darkened independently of the still-bright food UI.

    This permits a tooltip query only; it is not proof of a zero balance.
    """
    value = cv.cvtColor(screen.image, cv.COLOR_BGR2HSV)[:, :, 2]
    return bool(np.mean(value[334:382, 890:925] > 180) < .15
            and np.mean(value[402:422, 711:780] > 180) > .6)


def progress(screen: EventScreen) -> tuple[int | None, int | None]:
    text = normalized(screen.text((0, 140, 245, 295)))
    turn = re.search(r'(\d+)回合', text)
    distance = re.search(r'还剩(\d+)格', text)
    return (int(turn[1]) if turn else None, int(distance[1]) if distance else None)


def fastest_turn(screen: EventScreen) -> int | None:
    label = screen.find('赛季最快到达纪录', (0, 300, 245, 400), exact=True)
    if label is None:
        return None
    y = int(label.center[1])
    match = re.search(r'(\d+)回合', normalized(screen.text((135, y, 245, y+45))))
    return int(match[1]) if match else None


def helpful_food(text: str) -> bool:
    text = normalized(text)
    return bool(re.search('跳过下个回合的计数', text)
                or re.search('移动时可跳过里程格子', text)
                or re.search('可跳过料理格子移动', text)
                or re.search('下次投掷骰子时[，,]?会多走[1-9]个格子', text)
                or re.search('点数必定为[“"「]?[56]', text))


def surplus_food(text: str) -> bool:
    text = normalized(text)
    return not helpful_food(text) and bool(re.search(
        '开启品级[123]的里程商店|能够当场获得3个珍贵的未鉴定|将所有.*里程格子.*变为品级3', text))
