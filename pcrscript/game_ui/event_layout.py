"""Event edition and UI layout are independent; never infer one from the other."""
import cv2 as cv
import numpy as np


def navigation_exit(screen):
    """Leave an observed story-event selector without clicking through a modal."""
    if screen.find('一?键扫荡确认|扫荡券确认|扫荡结果|获得道具|扫荡完成|扫荡券使用结果|'
                   'BOSS详情|关卡详情|队伍编组|自动推进设定'):
        return None
    quests = screen.find('活动关卡.*首领', (0, 0, 330, 65), exact=True)
    if (quests and quests.score >= .95
            and screen.find('活动关卡', (450, 55, 730, 95), exact=True)
            and screen.find('首领战', (730, 55, 950, 95), exact=True)):
        return (32, 30)
    labels = [screen.find(pattern, roi, exact=True) for pattern, roi in (
        ('关卡一览', (300, 0, 700, 70)),
        (r'活动关卡[HN]-\d+', (35, 130, 350, 375)),
        ('1个关卡的使用券张数', (480, 390, 705, 435)),
        ('取消', (460, 440, 710, 520)),
    )]
    return labels[-1] if all(item and item.score >= .95 for item in labels) else None


def map_dialogue(screen):
    """Observed map dialogue: pink nameplate above a wide white speech panel."""
    if screen.find('菜单|跳过|全文显示', (680, 0, 960, 380)):
        return False
    plate = cv.cvtColor(screen.image[394:413, 200:355], cv.COLOR_BGR2HSV)
    panel = cv.cvtColor(screen.image[450:495, 220:740], cv.COLOR_BGR2HSV)
    pink = (plate[:, :, 0] >= 140) & (plate[:, :, 0] <= 179) & (plate[:, :, 1] > 45)
    white = (panel[:, :, 1] < 35) & (panel[:, :, 2] > 180)
    return float(np.mean(pink)) > .4 and float(np.mean(white)) > .75


def event_layout(screen):
    if screen.event_quests or (screen.event_home and
            screen.find('关卡.*首领', (0, 300, 260, 460))):
        return 'list'
    if (screen.find('讨伐证交换', (700, 360, 960, 480)) and
            screen.find('普通', (700, 55, 835, 105)) and
            screen.find('困难', (835, 55, 960, 105))):
        return 'map'
    if legacy_hub(screen):
        return 'map'
    return None


def legacy_hub(screen):
    return bool(screen.find('活动关卡', (450, 150, 670, 235)) and
                screen.find('讨伐证交换', (450, 305, 705, 385)) and
                screen.find('首领挑战券', (680, 90, 950, 140)))
