"""Explainable local substitutions from game-data descriptions, not guides."""
import re
import sqlite3
from ..game_ui.screen import normalized
from .abyss_history import team_key


def character_roles(database='cache/redive_cn.db'):
    result = {}
    with sqlite3.connect(database) as conn:
        roles=dict(conn.execute('SELECT unit_id,unit_role_id FROM unit_role_data'))
        rows = conn.execute('SELECT u.unit_id,u.unit_name,u.atk_type,u.search_area_width,s.union_burst,s.main_skill_1,s.main_skill_2 '
                            'FROM unit_data u JOIN unit_skill_data s ON s.unit_id=u.unit_id')
        for uid,name,kind,position,*skills in rows.fetchall():
            texts = [r[0] for sid in skills for r in conn.execute('SELECT description FROM skill_data WHERE skill_id=?',(sid,))]
            text = ''.join(texts)
            damage = sum(bool(re.search('造成.*(?:物理|魔法)伤害',t)) for t in texts)
            heal = bool(re.search('回复(?:我方|范围内我方|自身周围我方).*生命值',text))
            defense = bool(re.search('降低.*(?:物理|魔法)防御力',text))
            result[normalized(name)] = dict(kind=kind, position=position, damage=damage,
                role=roles.get(uid),
                heal=heal, defense=defense, tank='挑衅' in text, description=text,
                single=sum('一名敌人' in t or '敌方单体' in t for t in texts),
                score=damage*30+int(defense)*45+int('行动速度' in text)*15)
    return result


def alternatives(order, available, roles, failed, *, survival=False, boss=False, focus=None):
    """One-member changes keep a known core; preserve its tank and sole healer."""
    current = [roles.get(n,{}) for n in order]
    attackers = [r.get('kind') for r in current if r.get('damage',0)>0]
    kind = max(set(attackers), key=attackers.count) if attackers else None
    healers = sum(r.get('heal',False) for r in current)
    front = min(range(len(order)),key=lambda i:current[i].get('position',10**9)) if order else None
    choices=[]
    for index,old in enumerate(order):
        old_role=roles.get(old)
        if (not old_role or old_role['tank'] or (survival and index==front)
                or (old_role['heal'] and healers<=1)):
            continue
        for new in available:
            role=roles.get(new)
            if new in order or not role or role['tank'] or role['kind'] != kind:
                continue
            if survival and not role['heal']:
                continue
            if not survival and not (role['damage'] or role['defense']):
                continue
            names=order.copy();names[index]=new
            if team_key(names) in failed:
                continue
            score=role['score']-old_role['score']+int(old_role['heal'] and healers>1)*30
            if boss:score+=25*(role.get('single',0)-old_role.get('single',0))
            if survival:score+=int(role['heal'])*100
            if score<0:continue
            choices.append(dict(order=names, outgoing=old, incoming=new, score=score,
                reason=('补充治疗以改善生存' if survival else '保留坦克和至少一名治疗，调整同属性输出/破防；基于技能描述的本地试验')))
    # A fallen member is a useful clue, but a stronger support change can
    # protect that same member. Do not force the casualty out of the party.
    return sorted(choices,key=lambda c:(-c['score']-int(bool(survival and c['outgoing']==focus))*30,
                                       c['incoming'],c['outgoing']))
