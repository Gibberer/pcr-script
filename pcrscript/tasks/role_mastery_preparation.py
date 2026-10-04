"""Explicit, bounded role-node preparation for an existing first-clear task."""
from ..game_ui import role_mastery as mastery
from ..game_ui.screen import EventUIError


def validate_mastery_preparation(options):
    if not isinstance(options, dict):
        raise ValueError('mastery_preparation必须为配置对象')
    value = dict(options)
    if set(value)-{'roles','max_tickets','max_actions','strengthen_target_level','node_order','claim_earned_rewards'}:
        raise ValueError('mastery_preparation包含未知选项')
    roles = value.setdefault('roles', {})
    if (not isinstance(roles,dict) or any(role not in mastery.ROLE_NODES
            or type(level) is not int or level != 3 for role,level in roles.items())):
        raise ValueError('精通准备仅支持已核验的attack/break/buff/speed/defense职能及目标Lv3')
    order = value.setdefault('node_order', {})
    if (not isinstance(order,dict) or set(order)-set(roles)
            or any(not isinstance(nodes,list) or len(nodes)!=4
                   or any(type(node) is not int for node in nodes)
                   or set(nodes)!={0,1,2,3} for nodes in order.values())):
        raise ValueError('node_order必须按已指定职能列出0至3四个节点的完整无重复顺序')
    for key, default, maximum in (('max_tickets',0,100000),('max_actions',150,300)):
        number = value.setdefault(key,default)
        if type(number) is not int or not 0 <= number <= maximum:
            raise ValueError('精通准备'+key+'必须是范围内的整数')
    flag = value.setdefault('strengthen_target_level',False)
    if type(flag) is not bool:
        raise ValueError('strengthen_target_level必须为布尔值')
    if type(value.setdefault('claim_earned_rewards',False)) is not bool:
        raise ValueError('claim_earned_rewards必须为布尔值')
    return value


def enter_role_mastery(task, screen=None):
    """Reuse the ordinary, non-consuming route before preparation or recovery."""
    ui = task.ui
    screen = task.capture() if screen is None else screen
    if mastery.quest_page(screen) or mastery.gacha_home(screen):
        ui.click((30,30))
    elif mastery.gacha_result(screen):
        button = mastery.result_exit(screen)
        if button is None:
            raise EventUIError('精通结果退出按钮未知')
        ui.click(button)
        ui.wait(mastery.gacha_home,'精通抽取首页')
        ui.click((30,30))
    elif not mastery.role_page(screen):
        if screen.find('强化确认|收取报酬'):
            raise EventUIError('精通待核对弹窗无法安全离开，保留记录')
        from .task_home import ToHomePage
        ToHomePage(task.robot).run(timeout=60)
        # Confirm the known neighbours of the illustrated strength tab.
        ui.wait(lambda s:s.find('角色',(145,475,260,540),exact=True)
                and s.find('剧情',(375,475,470,540),exact=True)
                and s.find('冒险',(475,475,595,540),exact=True), '强化入口导航栏')
        ui.click((306,505))
        ui.wait(lambda s:s.find('公主骑士强化',(30,0,280,70),exact=True),'公主骑士强化')
        ui.expect_click('职能精通',(760,45,930,100),exact=True)
    return ui.wait(mastery.role_page,'职能精通')


def restore_pending_mastery_page(task, pending):
    """Restore the ledger's observation context, never a spending control."""
    kind = pending.get('kind')
    if kind not in ('mastery_gacha','mastery_claim','mastery_node'):
        raise EventUIError('未知精通待核对记录')
    if kind == 'mastery_node':
        role, node = pending.get('role'), pending.get('node')
        if (role not in mastery.ROLE_NODES or type(node) is not int or not 0 <= node < 4
                or not isinstance(pending.get('before'),dict)):
            raise EventUIError('精通待核对职能或节点无效，未导航')
    ui = task.ui
    screen = task.capture()
    if kind == 'mastery_gacha' and (mastery.gacha_home(screen) or mastery.gacha_result(screen)):
        return screen
    if kind == 'mastery_claim' and (mastery.quest_page(screen) or mastery.quest_receipt(screen)):
        return screen
    if kind == 'mastery_node' and screen.find('强化确认',(300,15,660,70),exact=True):
        # Preserve the existing confirmation for the submission-aware handler.
        return screen
    enter_role_mastery(task, screen)
    if kind == 'mastery_gacha':
        ui.expect_click('精通扭蛋',(70,150,225,225),exact=True)
        return ui.wait(mastery.gacha_home,'恢复精通抽取余额页')
    if kind == 'mastery_claim':
        ui.expect_click('任务',(760,15,835,75),exact=True)
        return ui.wait(mastery.quest_page,'恢复强化任务奖励列表')
    ui.click((mastery.ROLE_TABS[role][1],130))
    ui.wait(lambda s:mastery.role_page(s,role),'恢复待核对精通职能')
    ui.click(mastery.NODE_POINTS[node])
    expected = '【'+mastery.ROLE_TABS[role][0]+'】'+mastery.ROLE_NODES[role][node]+r'Lv\d+'
    return ui.wait(lambda s:mastery.role_page(s,role) and s.find(
        expected,(580,145,945,190),exact=True),'恢复待核对精通节点')


def prepare_role_mastery(task, options):
    """Use only held materials/tickets; pending operations prevent replay."""
    ui = task.ui
    report = task.report.setdefault('mastery_preparation',dict(history=[],nodes=[],tickets_spent=0))
    def begin(record):
        if task.state.get('pending_mastery'):
            raise EventUIError('存在未核对精通消费，未重复提交')
        task.state['pending_mastery'] = dict(record, submitted=False)
        task.save()
    def submitted(record):
        task.state['pending_mastery'] = dict(record,submitted=True)
        task.save()
    def settled(record):
        if not task.state.get('pending_mastery'):
            raise EventUIError('精通核账缺少对应待核对记录')
        report['history'].append(record)
        if record['kind']=='mastery_gacha':
            report['tickets_spent'] += record['cost']
        task.state.pop('pending_mastery')
        task.save()
    if pending := task.state.get('pending_mastery'):
        task.report_progress('核对上次精通消费')
        screen = restore_pending_mastery_page(task,pending)
        if pending['kind']=='mastery_gacha':
            mastery.reconcile_mastery_batch(ui,pending,settled=settled)
        elif pending['kind']=='mastery_claim':
            mastery.reconcile_mastery_rewards(ui,pending,observed=submitted,settled=settled)
        elif pending['kind']=='mastery_node':
            if screen.find('强化确认',(300,15,660,70),exact=True):
                # A persisted submission must never be sent twice. Preserve
                # an uncertain dialog rather than guessing whether it arrived.
                if pending.get('submitted'):
                    raise EventUIError('上次精通确认是否提交未知，保留记录，未重复确认')
                ui.expect_click('取消',(265,440,480,520),exact=True)
                screen = ui.wait(lambda s:mastery.role_page(s,pending['role']),'取消精通预览')
                if mastery.node_state(screen,pending['role'],ui=ui) != pending['before']:
                    raise EventUIError('取消精通预览后节点状态不一致')
                task.state.pop('pending_mastery')
                report['history'].append(dict(pending,outcome='cancelled_preview'))
                task.save()
            elif (pending.get('submitted') is False
                    and mastery.node_state(screen,pending['role'],ui=ui) == pending['before']):
                # The first journal write can precede opening the preview.
                # An unchanged selected node with no submission is cancellable.
                task.state.pop('pending_mastery')
                report['history'].append(dict(pending,outcome='cancelled_preview'))
                task.save()
            else:
                mastery.reconcile_mastery_node(ui,pending,settled=settled)
        else:
            raise EventUIError('未知精通待核对记录')
    if not options['roles']:
        return report

    enter_role_mastery(task)
    if options['claim_earned_rewards']:
        mastery.collect_mastery_rewards(ui,begin=begin,observed=submitted,settled=settled)
    actions = 0
    plan = [(role,level,optional)
            for optional in (False,True) if not optional or options['strengthen_target_level']
            for role,level in options['roles'].items()]
    for role,level,optional in plan:
        if optional and task.report['pending']:
            break
        if optional and role == next(iter(options['roles'])) and options['claim_earned_rewards']:
            mastery.collect_mastery_rewards(ui,begin=begin,observed=submitted,settled=settled)
        ui.click((mastery.ROLE_TABS[role][1],130))
        ui.wait(lambda s:mastery.role_page(s,role),'选择精通职能')
        for node in options['node_order'].get(role,range(4)):
            name = mastery.ROLE_NODES[role][node]
            task.report_progress('核对精通 · '+mastery.ROLE_TABS[role][0]+' · '+name)
            while True:
                task.check_deadline()
                ui.click(mastery.NODE_POINTS[node])
                expected = '【'+mastery.ROLE_TABS[role][0]+'】'+name+r'Lv\d+'
                screen = ui.wait(lambda s:mastery.role_page(s,role) and s.find(
                    expected,(580,145,945,190),exact=True),'选择精通节点')
                observed = mastery.node_observation(screen,role,ui=ui)
                if observed is None:
                    raise EventUIError('精通节点身份、等级或当前属性未知，未强化')
                if observed['level'] >= level and not optional:
                    state = observed
                    break
                state = mastery.node_state(screen,role,ui=ui)
                if state is None:
                    if optional:
                        state = dict(observed,optional_unreadable=True)
                        break
                    raise EventUIError('精通节点属性、材料或下次消耗未知，未强化')
                if state['level'] > level or optional and state['action']=='升级':
                    break
                if state['level'] < 2:
                    raise EventUIError('精通Lv1升级流程尚未核验，未消费')
                if not state['enabled'] or state['held'] < state['cost']:
                    # Optional strengthening stops at available held materials;
                    # it does not draw more after the required level is reached.
                    if optional:
                        break
                    remaining = options['max_tickets']-report['tickets_spent']
                    if remaining < 1 or actions >= options['max_actions']:
                        task.report['pending'].append(mastery.ROLE_TABS[role][0]+name+'材料不足，未达到Lv3')
                        break
                    ui.expect_click('精通扭蛋',(70,150,225,225),exact=True)
                    ui.wait(mastery.gacha_home,'精通材料抽取')
                    mastery.draw_mastery_batch(ui,remaining_budget=remaining,begin=begin,settled=settled)
                    actions += 1
                    ui.click((30,30));ui.wait(mastery.role_page,'抽取后返回精通')
                    ui.click((mastery.ROLE_TABS[role][1],130))
                    ui.wait(lambda s:mastery.role_page(s,role),'恢复目标职能')
                    continue
                if actions >= options['max_actions']:
                    raise EventUIError('精通准备达到本次动作上限，未追加消费')
                task.report_progress('强化精通 · '+mastery.ROLE_TABS[role][0]+' · '+name,
                                     actions,options['max_actions'])
                mastery.reinforce_mastery_node(ui,role,node,begin=begin,submitted=submitted,settled=settled)
                actions += 1
            report['nodes'].append(dict(role=role,node=node,state=state,optional=optional,
                evidence=str(ui.save('mastery_final_'+role+'_'+str(node)+'_'+str(optional),screen))))
            task.save()
    if not options['strengthen_target_level'] and options['claim_earned_rewards'] and not task.report['pending']:
        mastery.collect_mastery_rewards(ui,begin=begin,observed=submitted,settled=settled)
    return report
