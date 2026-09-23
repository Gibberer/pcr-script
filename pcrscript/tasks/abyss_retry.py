"""Conservative retry decisions from observed combat evidence."""
import re
import cv2 as cv
from ..game_ui.screen import normalized


def combat_sample(screen, portraits):
    timer=screen.find(r'\d:\d{2}',(750,0,850,55),exact=True)
    if not timer:return None
    minutes,seconds=map(int,normalized(timer.text).split(':'))
    hp=screen.find(r'[\d,]+/[\d,]+',(480,45,920,115),exact=True)
    remaining=total=None
    if hp:
        remaining,total=map(int,normalized(hp.text).replace(',','').split('/'))
        if not 0<=remaining<=total or total<=0:remaining=total=None
    dark=sum(cv.cvtColor(screen.image[y1:y2,x1:x2],cv.COLOR_BGR2GRAY).mean()<80
             and cv.cvtColor(screen.image[y1:y2,x1:x2],cv.COLOR_BGR2HSV)[:,:,1].mean()<40
             for x1,y1,x2,y2 in portraits)
    # Bright portraits are only a proxy; require repeated samples for a claim.
    return dict(seconds=minutes*60+seconds,hp=remaining,max_hp=total,dark_portraits=int(dark))


def retry_decision(samples, reason, same_team_attempts):
    valid=[s for s in samples if s.get('hp') is not None]
    tail=valid[-3:]
    shortfall=(min(s['hp']/s['max_hp'] for s in tail) if tail else None)
    elapsed=min((s['seconds'] for s in samples),default=90)
    deaths=('减员' in reason or sum(s.get('dark_portraits',0)>0 for s in samples[-4:])>=3)
    alive=(len(samples)>=3 and all(s.get('dark_portraits')==0 for s in samples[-3:]))
    if elapsed<=8 and alive and shortfall is not None and shortfall>.25:
        return dict(action='change_damage',reason='临近超时且连续无减员迹象，首领剩余生命超过25%；同队重试价值低',remaining_ratio=shortfall)
    if deaths and shortfall is not None and shortfall<=.25 and same_team_attempts<2:
        return dict(action='retry_once',reason='减员且首领剩余生命不超过25%，允许同队再试一次',remaining_ratio=shortfall)
    return dict(action='change_survival' if deaths else 'change_damage',
                reason='减员需调整生存' if deaths else '未证实同队重试有价值，优先更换输出/破防并核查培养',remaining_ratio=shortfall)
