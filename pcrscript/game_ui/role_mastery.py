"""Observed CN role mastery and held-ticket gacha screens at 960x540."""
from __future__ import annotations

import re
from hashlib import sha256
from uuid import uuid4

from .screen import EventUIError, normalized, claimable_task_snapshot
from ..run_session import clock as time


ROLE_TABS = {
    'attack': ('攻击型', 338), 'break': ('破防型', 416),
    'buff': ('增益型', 494), 'debuff': ('减益型', 572),
    'speed': ('强化型', 650), 'heal': ('治疗型', 728),
    'defense': ('坦克型', 806), 'interference': ('干扰型', 884),
}
ROLE_NODES = {
    'attack': ('攻击力提升','暴击提升','造成伤害提升','普通攻击强化'),
    'break': ('攻击力提升','暴击提升','暴击伤害提升','普通攻击强化'),
    'buff': ('生命值提升','物理防御力提升','魔法防御力提升','增益强化'),
    'speed': ('生命值提升','物理防御力提升','魔法防御力提升','技能值充能'),
    'defense': ('生命值提升','物理防御力提升','魔法防御力提升','异常状态抵抗'),
}
NODE_POINTS = ((383, 250), (489, 250), (383, 350), (489, 350))


def integer_text(text):
    value = normalized(text)
    # The comma in this UI can be recognized as a dot. Only full thousands
    # groups are accepted; a decimal or truncated number remains unknown.
    if not re.fullmatch(r'(?:\d+|\d{1,3}(?:[,.]\d{3})+)', value):
        return None
    return int(value.replace(',', '').replace('.', ''))


def integer_region(screen, roi):
    items = [item for item in screen.all(r'[\d,.]+', roi)
             if item.score >= .95 and integer_text(item.text) is not None]
    return integer_text(items[0].text) if len(items) == 1 else None


def gacha_home(screen):
    return bool(screen.find('精通扭蛋', (35, 0, 205, 65), exact=True)
                and screen.find('持有的券', (485,420,615,465), exact=True)
                and screen.find('批量抽取', (700,325,910,390), exact=True))


def gacha_result(screen):
    return bool(screen.find('扭蛋结果', (35,0,205,65), exact=True)
                and screen.find('获得精通一览', (370,0,590,60), exact=True)
                and screen.find('持有精通券', (525,350,690,402), exact=True))


def ticket_balance(screen):
    roi = ((670,420,790,465) if gacha_home(screen) else
           (750,350,850,402) if gacha_result(screen) else None)
    return integer_region(screen, roi) if roi else None


def _complete_balance(ui, screen):
    value = ticket_balance(screen)
    if value is not None:
        return value
    roi = ((670,420,790,465) if gacha_home(screen) else
           (750,350,850,402) if gacha_result(screen) else None)
    if roi is None:
        return None
    value = integer_region(ui.read_region(screen, roi, classify=False), roi)
    if value is None:
        # The isolated zero disappears from detection; the shared numeric
        # reader also performs recognition without a detected text box.
        candidate = ui.number(screen,roi)
        if type(candidate) is int and candidate >= 0:
            value = candidate
    return value


def result_exit(screen):
    if not gacha_result(screen):
        return None
    button = screen.find('取消',(265,395,480,470),exact=True)
    if button and button.score >= .95:
        return button
    button = screen.find('确认',(360,395,605,460),exact=True)
    if (button and button.score >= .95
            and not screen.find('再次抽取',(480,395,710,470),exact=True)):
        return button
    return None


def reconcile_mastery_batch(ui, record, *, settled, observed=None, recover_unsubmitted=False):
    """Resolve a durable pending draw without ever submitting another draw."""
    if (not callable(settled) or observed is not None and not callable(observed)
            or record.get('kind') != 'mastery_gacha'
            or type(record.get('before')) is not int or record['before'] < 1
            or type(record.get('cost')) is not int or record['cost'] != min(record['before'],500)
            or record.get('expected_after') != record['before']-record['cost']):
        raise ValueError('精通待核对消费记录无效')
    can_recover_unchanged = (record.get('submission_tracked') is True
        and (record.get('submitted') is False
             or recover_unsubmitted and record.get('submitted') is True))
    def unchanged_home(screen):
        controls = [screen.find(pattern,roi,exact=True) for pattern,roi in (
            ('精通扭蛋',(35,0,205,65)),('持有的券',(485,420,615,465)),
            ('批量抽取',(700,325,910,390)))]
        return (not record.get('result_evidence')
            and all(item and item.score >= .95 for item in controls)
            and screen.blue_button(controls[-1])
            and not screen.find('正在进行数据连接|连接中|加载中')
            and _complete_balance(ui,screen) == record['before'])
    def complete(screen):
        if screen.find('正在进行数据连接|连接中|加载中'):
            return False
        if not (gacha_home(screen) or gacha_result(screen)):
            return False
        if gacha_result(screen) and not record.get('result_evidence'):
            # Seeing results forbids unchanged-balance cancellation on later
            # restarts as well. Persist this proof before exiting the result.
            record['result_evidence'] = str(ui.save('mastery_gacha_result_'+uuid4().hex[:8],screen))
            if observed is not None:
                observed(record)
        value = _complete_balance(ui, screen)
        if value is None:
            # Leaving results is non-consuming and exposes a second, larger
            # balance field. A pending draw remains durable across this exit.
            return bool(result_exit(screen))
        if (gacha_home(screen) and value == record['before']
                and can_recover_unchanged and unchanged_home(screen)):
            return True
        if value != record['expected_after']:
            raise EventUIError('精通抽取结果余额不一致，保留待核对记录，未追加抽取')
        return True
    screen = ui.wait(complete, '精通抽取余额核对', timeout=45)
    if gacha_home(screen) and _complete_balance(ui,screen) == record['before']:
        for _ in range(2):
            time.sleep(.5)
            screen = ui.capture()
            if not unchanged_home(screen):
                raise EventUIError('未提交精通抽取的页面或余额变化，保留待核对记录')
        resolved = dict(record,after=record['before'],outcome='cancelled_unsubmitted',
            home_evidence=str(ui.save('mastery_gacha_unsubmitted_'+uuid4().hex[:8],screen)))
        settled(resolved)
        return resolved
    evidence = record.get('result_evidence') or str(ui.save('mastery_gacha_result_'+uuid4().hex[:8], screen))
    if gacha_result(screen):
        button = result_exit(screen)
        if button is None:
            raise EventUIError('精通结果退出按钮未知，保留待核对记录')
        roi = (265,395,480,470) if normalized(button.text)=='取消' else (360,395,605,460)
        ui.expect_click(normalized(button.text),roi,exact=True)
    home = ui.wait(lambda s: gacha_home(s) and complete(s)
                   and _complete_balance(ui,s) == record['expected_after'],
                   '精通结果返回首页', timeout=30)
    resolved = dict(record, after=_complete_balance(ui, home), result_evidence=evidence,
                    home_evidence=str(ui.save('mastery_gacha_home_'+uuid4().hex[:8], home)))
    settled(resolved)
    return resolved


def role_page(screen, key=None):
    if (not screen.find('公主骑士强化', (30,0,280,70), exact=True)
            or not screen.find('批量强化', (325,395,570,470), exact=True)):
        return False
    if key is None:
        return True
    item = screen.find(ROLE_TABS[key][0], (370,164,550,205), exact=True)
    return bool(item and item.score >= .95)


def quest_page(screen):
    button = screen.find('全部收取',(730,405,950,468),exact=True)
    return bool(screen.find('强化任务',(30,0,220,70),exact=True)
                and button and button.score >= .95)


def quest_receipt(screen):
    return bool(screen.find('收取报酬',(300,15,660,70),exact=True)
                and screen.find('收取了以下道具。',(270,65,690,120),exact=True)
                and screen.find('关闭',(350,440,610,520),exact=True))


def quest_claim_snapshot(screen):
    if (not quest_page(screen) or quest_receipt(screen)
            or not screen.blue_button(screen.find('全部收取',(730,405,950,468),exact=True))):
        return None
    return claimable_task_snapshot(screen,(310,65,920,350))


def reconcile_mastery_rewards(ui, record, *, observed, settled, recover_unsubmitted=False):
    """A reward receipt resolves a pending claim; never submit another claim."""
    if record.get('kind') != 'mastery_claim' or not all(callable(x) for x in (observed,settled)):
        raise ValueError('精通任务奖励待核对记录无效')
    screen = ui.capture()
    if quest_page(screen) and record.get('receipt_evidence') and isinstance(record.get('rewards'),str):
        settled(record)
        return record
    if recover_unsubmitted and quest_page(screen) and record.get('quest_view'):
        snapshot = record['quest_view']
        if quest_claim_snapshot(screen) == snapshot:
            for _ in range(2):
                time.sleep(.5)
                screen = ui.capture()
                if quest_claim_snapshot(screen) != snapshot:
                    raise EventUIError('强化任务领奖恢复时内容或状态变化，保留待核对记录')
            row = dict(record,outcome='cancelled_unclaimed',
                recovery_evidence=str(ui.save('mastery_claim_unclaimed_'+uuid4().hex[:8],screen)))
            settled(row)
            return row
    screen = ui.wait(quest_receipt,'核对强化任务奖励回执',timeout=30)
    row = dict(record,receipt_evidence=str(ui.save('mastery_claim_receipt_'+uuid4().hex[:8],screen)),
               rewards=screen.text((250,100,720,440)))
    observed(row)
    ui.expect_click('关闭',(350,440,610,520),exact=True)
    ui.wait(quest_page,'奖励领取后返回强化任务')
    settled(row)
    return row


def collect_mastery_rewards(ui, *, begin, observed, settled):
    """Collect already earned rewards, then return to role mastery."""
    if not all(callable(x) for x in (begin,observed,settled)):
        raise ValueError('精通任务领奖需要持久化回调')
    screen = ui.capture()
    if not quest_page(screen):
        if not role_page(screen):
            raise EventUIError('强化任务入口上下文未知，未领奖')
        ui.expect_click('任务',(760,15,835,75),exact=True)
        screen = ui.wait(quest_page,'强化任务奖励列表')
    claimed = []
    for _ in range(3):
        button = screen.find('全部收取',(730,405,950,468),exact=True)
        if not screen.blue_button(button):
            ui.save('mastery_claim_empty_'+uuid4().hex[:8],screen)
            break
        snapshot = quest_claim_snapshot(screen)
        if snapshot is None:
            raise EventUIError('强化任务内容或可领取状态不完整，未保存领奖记录或领取')
        row = dict(kind='mastery_claim',quest_view=snapshot,submitted=False,before_evidence=str(
            ui.save('mastery_claim_before_'+uuid4().hex[:8],screen)))
        begin(row)
        row['submitted'] = True
        observed(row)
        # Immediate, free claim. The durable pending record prevents replay.
        ui.click(button)
        claimed.append(reconcile_mastery_rewards(ui,row,observed=observed,settled=settled))
        screen = ui.capture()
        if not quest_page(screen):
            raise EventUIError('强化任务领奖后的列表未知，未继续')
        if not screen.blue_button(screen.find('全部收取',(730,405,950,468),exact=True)):
            break
    else:
        raise EventUIError('强化任务领奖达到批次上限，未继续')
    ui.click((30,30))
    ui.wait(role_page,'领奖后返回职能精通')
    return claimed


def node_observation(screen, role, *, ui=None):
    """Observe achieved identity, level and property independently of next cost."""
    if role not in ROLE_TABS or not role_page(screen, role):
        return None
    title = screen.find(r'【'+ROLE_TABS[role][0]+r'】.+Lv\d+',
                        (580,145,945,190), exact=True)
    current = screen.all(r'^\d+(?:\.\d+)?%?$', (700,270,800,325))
    current = [x for x in current if x.score >= .95]
    if ui is not None and len(current) != 1:
        current = [x for x in ui.read_region(screen,(700,270,800,310),classify=False).all(
            r'^\d+(?:\.\d+)?%?$',(700,270,800,310)) if x.score >= .95]
    if not title or title.score < .95 or len(current) != 1:
        return None
    return dict(title=normalized(title.text), level=int(re.search(r'Lv(\d+)',title.text)[1]),
                value=normalized(current[0].text))


def node_state(screen, role, *, ui=None):
    """Read achieved property plus the next action's cost and target."""
    observed = node_observation(screen,role,ui=ui)
    if observed is None:
        return None
    held_pattern = r'\d+(?:\(其中可转换的数量\d+\))?'
    held = screen.find(held_pattern, (700,375,935,408), exact=True)
    if ui is not None and (not held or held.score < .95):
        held = ui.read_region(screen,(700,375,935,408),classify=False).find(
            held_pattern,(700,375,935,408),exact=True)
    target = [x for x in screen.all(r'^\d+(?:\.\d+)?%?\(\+\d+(?:\.\d+)?%?\)$',
                                    (800,270,935,325)) if x.score >= .95]
    if ui is not None and len(target) != 1:
        target = [x for x in ui.read_region(screen,(810,270,935,310),classify=False).all(
            r'^\d+(?:\.\d+)?%?\(\+\d+(?:\.\d+)?%?\)$',(810,270,935,310)) if x.score >= .95]
    cost = integer_region(screen, (860,350,935,375))
    action = screen.find('升级|强化', (650,395,855,470), exact=True)
    if (not held or held.score < .95 or len(target) != 1 or cost is None
            or not action or action.score < .95):
        return None
    return dict(observed, target=normalized(target[0].text).split('(')[0],
                cost=cost, held=int(re.match(r'\d+',normalized(held.text))[0]),
                action=normalized(action.text), enabled=screen.blue_button(action))


def node_confirmation_snapshot(screen):
    """Identify the original material preview, including quantities missed by OCR."""
    if screen.find('正在进行数据连接|连接中|加载中'):
        return None
    controls = [screen.find(pattern,roi,exact=True) for pattern,roi in (
        ('强化确认',(300,15,660,70)),
        ('要消耗以下道具进行强化吗[?？]',(300,70,680,110)),
        ('取消',(265,440,480,520)),('确认',(480,440,700,520)))]
    materials = screen.all('.+',(255,115,705,435))
    if (any(not item or item.score < .95 for item in controls)
            or not screen.blue_button(controls[-1]) or not materials
            or any(item.score < .95 for item in materials)
            or not any(normalized(item.text) == '消耗道具' for item in materials)
            or not any(re.fullmatch(r'Lv[1-9]\d*',normalized(item.text)) for item in materials)):
        return None
    # Icons and their consumption counts are part of the proof even when OCR
    # sees only a material's level. Keep their exact pixels in a local digest.
    digest = sha256(screen.image[115:435,255:705].tobytes()).hexdigest()
    rows = [[normalized(item.text),*map(int,item.center)] for item in materials]
    return dict(version=1,materials_digest=digest,rows=sorted(rows,key=lambda row:(row[2],row[1],row[0])))


def reconcile_cancelled_mastery_node(ui, record, screen, *, settled, recover_unchanged=False):
    """Observe an unchanged node after an interrupted or delivered cancellation."""
    view = record.get('confirmation_view')
    lost_confirmation = (recover_unchanged and record.get('submitted') is True
        and isinstance(view,dict) and view.get('version') == 1
        and isinstance(view.get('materials_digest'),str)
        and re.fullmatch(r'[0-9a-f]{64}',view['materials_digest'])
        and isinstance(view.get('rows'),list) and bool(view['rows']))
    if (not lost_confirmation and record.get('submitted') is not False
            and (record.get('cancellation_requested') is not True
                 or not isinstance(record.get('confirmation_view'),dict))):
        raise EventUIError('精通取消恢复缺少原预览与取消记录，保留待核对消费')
    for check in range(3):
        if (screen.find('强化确认|确认|取消|正在进行数据连接|连接中|加载中')
                or node_state(screen,record['role'],ui=ui) != record['before']):
            raise EventUIError('取消精通预览后节点或材料不一致，保留待核对记录')
        if check < 2:
            time.sleep(.5)
            screen = ui.capture()
    resolved = dict(record,outcome='cancelled_preview',
        recovery_evidence=str(ui.save('mastery_node_cancelled_'+uuid4().hex[:8],screen)))
    settled(resolved)
    return resolved


def cancel_mastery_confirmation(ui, record, screen, *, observed, settled):
    """Cancel a proven unchanged preview, then prove the node and stock unchanged."""
    snapshot = node_confirmation_snapshot(screen)
    saved = record.get('confirmation_view')
    if snapshot is None or (record.get('submitted') is not False and saved != snapshot):
        raise EventUIError('上次精通确认缺少原消耗预览或状态未知，保留记录，未重复确认')
    if saved and saved != snapshot:
        raise EventUIError('精通确认的消耗预览与原记录不一致，保留记录')
    for _ in range(2):
        time.sleep(.5)
        if node_confirmation_snapshot(ui.capture()) != snapshot:
            raise EventUIError('精通确认弹窗或消耗预览变化，保留记录，未取消或重放')
    record = dict(record,confirmation_view=snapshot,cancellation_requested=True)
    # Cancellation is also an input boundary. A restart after its delivery
    # must be able to reconcile an unchanged node without waiting for a spend.
    observed(record)
    ui.expect_click('取消',(265,440,480,520),exact=True)
    screen = ui.wait(lambda s:role_page(s,record['role'])
        and not s.find('强化确认|正在进行数据连接|连接中|加载中'),'取消精通预览')
    return reconcile_cancelled_mastery_node(ui,record,screen,settled=settled)


def reinforce_mastery_node(ui, role, node, *, begin, submitted, settled):
    """Apply one audited node increment, journaling before both input steps."""
    if role not in ROLE_TABS or type(node) is not int or not 0 <= node < 4:
        raise ValueError('精通职能或节点无效')
    if not all(callable(x) for x in (begin, submitted, settled)):
        raise ValueError('精通强化需要持久化消费回调')
    screen = ui.capture()
    state = node_state(screen, role, ui=ui)
    if not state or not state['enabled'] or state['cost'] <= 0 or state['held'] < state['cost']:
        raise EventUIError('精通节点、属性增量或材料无法核对，未强化')
    if (role not in ROLE_NODES or not re.fullmatch(
            '【'+ROLE_TABS[role][0]+'】'+ROLE_NODES[role][node]+r'Lv\d+',state['title'])):
        raise EventUIError('当前精通节点与指定槽位不一致，未强化')
    tag = uuid4().hex[:8]
    record = dict(kind='mastery_node', role=role, node=node, before=state,
                  expected_level=state['level']+int(state['action']=='升级'),
                  expected_value=state['target'], before_evidence=str(ui.save('mastery_node_before_'+tag,screen)))
    begin(record)
    ui.expect_click(state['action'], (650,395,855,470), exact=True)
    confirmation = ui.wait(lambda s:s.find('强化确认', (300,15,660,70),exact=True)
                           and s.find('要消耗以下道具进行强化吗[?？]', (300,70,680,110),exact=True),
                           '精通强化确认', timeout=30)
    button = confirmation.find('确认', (480,440,700,520), exact=True)
    if not button or button.score < .95 or not confirmation.blue_button(button):
        raise EventUIError('精通强化确认按钮未知，保留待核对记录')
    snapshot = node_confirmation_snapshot(confirmation)
    if snapshot is None:
        raise EventUIError('精通强化消耗预览不完整，保留待核对记录，未确认')
    record['confirmation_view'] = snapshot
    record['confirmation_evidence'] = str(ui.save('mastery_node_confirmation_'+tag,confirmation))
    record['submitted'] = True
    submitted(record)
    ui.click(button)
    return reconcile_mastery_node(ui,record,settled=settled)


def reconcile_mastery_node(ui, record, *, settled):
    """Only observe a pending node's expected property; never replay input."""
    if (record.get('kind') != 'mastery_node' or record.get('role') not in ROLE_TABS
            or not isinstance(record.get('before'),dict) or not callable(settled)):
        raise ValueError('精通节点待核对记录无效')
    observed = {}
    def complete(screen):
        if screen.find('正在进行数据连接'):
            return False
        state = node_observation(screen,record['role'],ui=ui)
        if not state:
            return False
        old = record['before']
        expected_title = re.sub(r'Lv\d+$','Lv'+str(record['expected_level']),old['title'])
        if state['title'] != expected_title:
            if state['title'] == old['title'] and state['value'] == old['value']:
                return False
            raise EventUIError('精通强化后的节点或等级不一致，未重复提交')
        if state['value'] != record['expected_value']:
            return False
        observed.update(state)
        return True
    screen = ui.wait(complete,'精通强化结果核对',timeout=30)
    resolved = dict(record, after=dict(observed), after_evidence=str(ui.save('mastery_node_after_'+uuid4().hex[:8],screen)))
    settled(resolved)
    return resolved


def draw_mastery_batch(ui, *, remaining_budget, begin, submitted, settled):
    """Draw the displayed batch with durable preparation and submission states."""
    if type(remaining_budget) is not int or remaining_budget < 1:
        raise ValueError('精通批量抽取的剩余授权必须为正整数')
    if not all(callable(x) for x in (begin,submitted,settled)):
        raise ValueError('精通抽取需要持久化消费回调')
    screen = ui.capture()
    before = _complete_balance(ui,screen)
    cost = screen.find(r'消耗\d+张', (700,370,910,415), exact=True)
    amount = int(re.search(r'\d+',normalized(cost.text))[0]) if cost and cost.score >= .95 else None
    button = screen.find('批量抽取', (700,325,910,390), exact=True)
    if (not gacha_home(screen) or before is None or before < 1
            or amount != min(before,500) or amount > remaining_budget
            or not button or button.score < .95
            or not screen.blue_button(button)):
        raise EventUIError('精通券余额、批量消耗、剩余上限或按钮无法核对，未抽取')
    tag = uuid4().hex[:8]
    record = dict(kind='mastery_gacha', before=before, expected_after=before-amount, cost=amount,
                  submitted=False,submission_tracked=True,
                  before_evidence=str(ui.save('mastery_gacha_before_'+tag, screen)))
    begin(record)
    record['submitted'] = True
    submitted(record)
    # This button submits immediately; never replay it while awaiting a result.
    ui.click(button)
    ui.wait(gacha_result, '精通批量抽取结果', timeout=45)
    return reconcile_mastery_batch(ui, record, settled=settled, observed=submitted)
