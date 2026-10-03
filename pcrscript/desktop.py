"""Versioned JSON interface for the desktop client; uses the production task stack."""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def runtime_defaults_path() -> Path:
    """Shared default configuration for GUI and command-line entry points."""
    return ROOT / 'runtime_defaults.yml'

PROTOCOL = 1
LABELS = {
    'abyss_push': '深域关卡 · 尽力推进',
    'abyss_subjugation': '深渊讨伐战 · 每日首通与扫荡',
    'upgrade_all_characters': '强化所有角色装备和等级到上限',
    'max_character_bonds': '角色好感度与剧情解锁',
    'dungeon_first_clear': '地下城 · 首次通关',
    'caravan': '驾车游 · 清空骰子', 'get_gift': '礼物箱 · 领取邮件与赠礼', 'campaign_clean': '剧情活动日常',
    'dawn_labyrinth': '黎明界迷宫 · 扫荡通行证',
    'dawn_labyrinth_first_clear': '黎明界迷宫 · 难度1首通',
    'recollection': '追忆战场 · 日常领奖与扫荡',
    'recollection_first_clear': '追忆战场 · 首次通关',
    'revival_event_once': '复刻活动', 'tohomepage': '返回首页', 'free_gacha': '免费十连',
    'normal_gacha': '普通扭蛋', 'arena': '竞技场', 'princess_arena': '公主竞技场',
    'research': '圣迹 / 神殿调查', 'schedule': '日程表', 'shop_buy': '商店购买',
    'quick_clean': '快捷扫荡', 'adventure_daily': '冒险日常', 'common_adventure': '普通冒险',
    'clear_story': '阅读剧情', 'get_quest_reward': '首页任务 · 领取任务奖励',
    'luna_tower_clean': '露娜塔扫荡',
    'team_battle': '团队战',
    'clear_campaign_first_time': '活动首通',
}
SPECIAL_TASKS = {'clear_story', 'dungeon_first_clear', 'abyss_push',
                 'upgrade_all_characters', 'max_character_bonds', 'common_adventure', 'caravan', 'tohomepage',
                 'dawn_labyrinth_first_clear', 'recollection_first_clear'}

PARAMETER_LABELS = {
    'multi': '抽取所有可用免费十连', 'exclude_stamina': '暂不领取体力',
    'hard_chapter': '扫荡活动困难关卡', 'exhaust_power': '剩余体力用于普通关卡',
    'pos': '快捷扫荡预设编号', 'rule': '商店购买规则', 'click_pos': '首页按钮坐标',
    'timeout': '超时时间（秒）', 'character_symbol': '冒险角色模板',
    'estimate_combat_duration': '预估战斗时长（秒）',
}
DESCRIPTIONS = {
    'abyss_subjugation': '活动开放期间，优先取得本期国服攻略并核验五人身份、培养及 SET/AUTO，同队首通前哨各难度并扫荡剩余次数；首领模拟核验后消耗讨伐委托证推进未通关首领。全部首通后扫荡一个高难首领，核对次数与券余额。可领取公会之家现有体力，不购买体力、回复次数或重置首领进度。',
    'abyss_push': '按五种属性推进深域NEXT关卡。按来源优先选队并核验当前培养，开战前自动装备特别装备；结合伤害、减员和历史失败记录调整阵容与重试次数。可选升5星并用女神秘石兑换所需碎片，默认关闭；不购买体力或重置次数。攻略搜索结果仅为候选来源，尚不能自动解析完整培养要求。',
    'upgrade_all_characters': '使用角色页一键强化，分批提升全部可强化角色至最高可用品级，并强化等级、技能和普通装备。使用现有玛那、装备与原矿；不购买资源、不改变星数或专武开关。',
    'max_character_bonds': '按好感度从低到高检查持有角色，使用现有礼物尽量提升至当前上限，逐篇跳过新开放的角色剧情并核对首读及属性奖励。记录每位角色的礼物消耗与未完成原因；不购买礼物。',
    'dungeon_first_clear': '按本地路线推进地下城首通。首领战前预检整条路线的角色占用与培养，每场保存实际伤害和配装证据；支持主力、换季、补刀与收尾队。已完成区域跳过，实际方案存于本地 cache/game/strategies/dungeon_teams.yml。',
    'caravan': '从冒险进入驾车游，消耗持有的骰子。未达标时使用单骰争取15回合内到达；已解锁时使用快速通关。不购买骰子，默认不加入每日列表。',
    'dawn_labyrinth': '从冒险进入黎明界迷宫，沿用游戏已选难度，通过已解锁的跳过消耗现有通行证。核对消费预览、跳过结果和余额后继续，结束时领取迷宫任务奖励；零票也检查奖励。未解锁时提示先运行首通任务，可设置本次通行证上限。',
    'dawn_labyrinth_first_clear': '从冒险进入黎明界迷宫，尝试美食殿堂难度1首通；每次至多出发一次。伙伴须核验身份、培养、完整装备与专武，装备信息不全时停止。已有探索须证明难度与同行公会，无法证明时保留进度；不购买资源或培养角色。首通或已通关复查完成后领取迷宫任务奖励。',
    'recollection': '领取普通追忆战的累计报酬，按本次上限扫荡追忆战·霸各领域已通关的最高层；核对扫荡券与挑战次数，不挑战未通关层。日程表能领取普通报酬，但不支持追忆战·霸扫荡。',
    'recollection_first_clear': '尽力推进记忆领域和追忆战·霸已解锁领域。程序获取对应层攻略、核对五人身份与培养后有限挑战；已完成层跳过，次数耗尽或来源、装备未知时保留进度。可选分配现有特别装备；不购买资源、重置次数或培养角色。',
    'get_gift': '从首页礼物箱领取邮件与赠礼，不是任务页面的成就/每日任务领奖。可选择暂不领取体力。特别装备满仓时按配置使用游戏已有自动分解规则释放空间；其他持有上限会停止并报告。',
    'campaign_clean': '处理剧情活动重复日：困难扫荡、按标记检查剧情与任务、兑换奖励。首通和首领是否执行由活动配置控制，默认关闭。',
    'revival_event_once': '检查当期复刻活动并按完成回执跳过已完成内容。未完成时根据布局和配置处理关卡、首领与奖励；开战依赖有效队伍方案及培养核验。',
    'tohomepage': '手动返回游戏首页。普通任务已自动处理首页前置条件，无需在配置中穿插此项。可调整首页按钮坐标和等待超时。',
    'free_gacha': '进行活动免费十连，可选择抽取所有累积次数。按配置执行时会根据活动情报筛选；单独执行前需确认活动可用。',
    'normal_gacha': '进入普通扭蛋并执行领取流程。需要有可用的免费抽取次数。',
    'arena': '进入竞技场进行一次挑战，使用游戏中已有编队。会消耗可用挑战次数。',
    'princess_arena': '进入公主竞技场进行一次挑战，使用游戏中已有编队。会消耗可用挑战次数。',
    'research': '执行圣迹与神殿调查的日常扫荡，使用可用次数和体力。',
    'schedule': '执行游戏内日程表，按游戏已保存的日程设置领取和安排任务。',
    'shop_buy': '按购买规则进入对应商店购买物品，消耗相应货币。{"1":[-1]} 表示通常商店“全部”分类全选；目前不支持自动刷新及首屏外的单品。',
    'quick_clean': '执行游戏已保存的快捷扫荡预设（1～7）。配置列表执行时，仅困难掉落活动开放会切换到预设3；请先在游戏内确认预设内容。',
    'adventure_daily': '处理探险归来、再次出发及探险地图事件。沿用游戏内已有探险编队。',
    'common_adventure': '在当前冒险地图根据角色模板定位关卡并循环战斗。需事先进入对应地图；这是持续推进任务，需要手动停止，不适合无条件加入日常。',
    'clear_story': '处理剧情页面的可读剧情和跳过流程。任务依赖已有图片模板识别。',
    'get_quest_reward': '依次检查首页任务页面的每日、普通、称号标签并领取已完成任务奖励（含体力）。示例日常先领体力供扫荡使用，最后再补领新完成任务的奖励。',
    'luna_tower_clean': '在露娜塔开放且已完成对应进度时扫荡回廊。配置列表会根据活动情报筛选。',
    'team_battle': '团队战开放期间，在扫荡后使用现有挑战次数。优先选择满血且可连续击杀的首领；高级推荐队伍必须五人齐全并装备特别装备，每次实战前先通过模拟战。不会购买体力或重置次数。',
    'clear_campaign_first_time': '核对保存队伍并按 StoryEvent.max_first_clear_stamina 上限自动推进普通、困难关卡，随后扫荡和领奖。需允许 allow_local_trials；首领由 bosses 独立控制。',
}


def environment_report() -> dict[str, Any]:
    """Standard-library-only check, usable before installing runtime dependencies."""
    import importlib.metadata
    import struct
    missing: list[str] = []
    for requirement in (ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines():
        requirement = requirement.strip()
        if not requirement or requirement.startswith('#'):
            continue
        name = requirement.split('==', 1)[0]
        try:
            importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(requirement)
    compatible = sys.version_info >= (3, 12) and struct.calcsize('P') == 8
    return dict(protocol=PROTOCOL, compatible=compatible, ready=compatible and not missing,
                python=sys.executable, version=sys.version.split()[0], missing=missing)


def catalog() -> list[dict[str, Any]]:
    from pcrscript.tasks import find_taskclass
    from pcrscript.tasks.registry import registered_tasks
    result = []
    for name in registered_tasks():
        cls = find_taskclass(name)
        parameters = []
        for key, p in inspect.signature(cls.run).parameters.items():
            if key == 'self' or key in ('event',) or p.kind == p.KEYWORD_ONLY:
                continue
            default = None if p.default is inspect.Parameter.empty else p.default
            kind = 'boolean' if isinstance(default, bool) else 'number' if isinstance(default, (int, float)) else 'string' if isinstance(default, str) else 'json'
            parameters.append(dict(name=key, label=PARAMETER_LABELS.get(key, key), type=kind, default=default,
                                   required=p.default is inspect.Parameter.empty))
        result.append(dict(name=name, label=LABELS.get(name, name), description=DESCRIPTIONS.get(name, inspect.getdoc(cls) or '暂无任务说明'), parameters=parameters,
                           config_section=cls.config_section,
                           category='special' if name in SPECIAL_TASKS else 'daily',
                           category_label='按需专项' if name in SPECIAL_TASKS else '每日日常',
                           requires_device=True,
                           entry='执行前自动返回首页' if cls.requires_home else '需先进入目标冒险地图' if name == 'common_adventure' else '任务自行处理页面导航'))
    return result


def device_report(options: dict[str, Any]) -> dict[str, Any]:
    """Connection check only; reuse production discovery, never capture/start a game."""
    from pcrscript.simulator import DNSimulator, GeneralSimulator
    ensure_idle()
    emulator = str(options.get('dnpath') or '').strip()
    if emulator:
        if not (Path(emulator) / 'ldconsole.exe').is_file():
            raise ValueError('此目录没有 ldconsole.exe，请选择雷电模拟器安装目录，而非桌面快捷方式。')
        simulator = DNSimulator(emulator, useADB=False)
        devices = simulator.get_devices() or []
        message = ('雷电模拟器连接正常，在线实例：' + '、'.join(devices) + '。请登录游戏首页，并确认分辨率为 960×540。') if devices else (
            simulator.discovery_error())
        return dict(protocol=PROTOCOL, ready=bool(devices), devices=[], message=message,
                    discovery=simulator.last_discovery)
    states = GeneralSimulator(str(options.get('adb_path') or 'adb')).get_device_states()
    devices = [serial for serial, state in states.items() if state == 'device']
    serial = str(options.get('adb_serial') or '').strip()
    ready = serial in devices if serial else len(devices) == 1
    if ready:
        message = 'ADB 连接正常：' + (serial or devices[0]) + '。请登录游戏；手机布局尚需实机验证。'
    elif serial and serial not in states:
        message = '未找到指定序列号，请从列表重新选择目标设备。'
    elif states.get(serial) == 'unauthorized' or (not serial and 'unauthorized' in states.values()):
        message = '手机尚未授权：解锁手机，勾选并允许此电脑进行 USB 调试，然后重新检查。'
    elif states.get(serial) == 'offline' or (not serial and not devices and 'offline' in states.values()):
        message = '设备离线：请重新连接数据线，确认 USB 调试已开启后重试。'
    elif len(devices) > 1:
        message = '发现多个已授权设备，请在 ADB 设备序列号下拉框选择本次使用的设备。'
    else:
        message = '未发现可用设备：检查 USB 调试、数据线和手机厂商 USB 驱动；手机需要处于正常 Android 系统。'
    return dict(protocol=PROTOCOL, ready=ready, devices=devices, message=message)


def read_config(path: Path) -> dict[str, Any]:
    import yaml
    value = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('配置必须是 YAML 对象')
    return value


def revision(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ''


def ensure_idle() -> None:
    """Use the same OS lock as RunSession, including unresponsive processes."""
    import msvcrt
    folder = ROOT / 'cache/daily/runs'
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'daily.lock').open('a+b') as handle:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise ValueError('有任务仍在运行，暂不能修改配置或更新环境') from error
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def config_view(path: Path) -> dict[str, Any]:
    config = read_config(path if path.exists() else runtime_defaults_path())
    return config_data(config, revision(path), path if path.exists() else None)


def new_config() -> dict[str, Any]:
    config = read_config(runtime_defaults_path())
    config['Accounts'] = []
    config['Task'] = {1: []}
    config.pop('Desktop', None)
    return config_data(config, '')


def task_signature(tasks: list) -> str:
    import yaml
    data = yaml.safe_dump(tasks, allow_unicode=True, sort_keys=False)
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def desktop_state_dir() -> Path:
    local = os.environ.get('LOCALAPPDATA')
    return (Path(local) if local else Path.home() / '.local' / 'share') / 'PcrDesktop'


def plan_state_path(path: Path) -> Path:
    key = hashlib.sha256(str(path.resolve()).casefold().encode('utf-8')).hexdigest()
    return desktop_state_dir() / 'plans' / f'{key}.json'


def task_plan(tasks: list, path: Path | None = None) -> list[dict[str, Any]]:
    active = [dict(enabled=True, name=row[0], args=row[1:]) for row in tasks]
    if path is None:
        return active
    try:
        state = json.loads(plan_state_path(path).read_text(encoding='utf-8'))
    except (FileNotFoundError, OSError, ValueError):
        return active
    if not isinstance(state, dict) or state.get('task_hash') != task_signature(tasks):
        return active
    disabled = state.get('disabled')
    if not isinstance(disabled, list):
        return active
    if not all(isinstance(row, dict) and type(row.get('index')) is int
               and isinstance(row.get('name'), str) and isinstance(row.get('args'), list)
               for row in disabled):
        return active
    plan = active[:]
    for entry in sorted(disabled, key=lambda row: row['index']):
        if not 0 <= entry['index'] <= len(plan):
            return active
        plan.insert(entry['index'], dict(enabled=False, name=entry['name'], args=entry['args']))
    return plan


def config_data(config: dict[str, Any], digest: str, path: Path | None = None) -> dict[str, Any]:
    task_groups = config.get('Task', {})
    if not isinstance(task_groups, dict):
        raise ValueError('Task 必须是账号到任务列表的映射')
    selected = next(iter(task_groups), 1)
    tasks = task_groups.get(selected, [])
    saved = task_plan(tasks, path)
    saved = [r for r in saved if r['name'] != 'tohomepage' or r['args']]
    options = {k: v for k, v in config.items() if k not in ('Accounts', 'Task', 'Desktop')}
    return dict(protocol=PROTOCOL, revision=digest, plan=saved, options=options,
                account_group=str(selected), catalog=catalog())


def validate_plan(plan: Any) -> list[dict[str, Any]]:
    from pcrscript.tasks import find_taskclass
    if not isinstance(plan, list):
        raise ValueError('任务列表格式错误')
    for row in plan:
        if not isinstance(row, dict) or not isinstance(row.get('enabled'), bool) or not isinstance(row.get('args'), list):
            raise ValueError('每项任务需要 enabled、name、args')
        cls = find_taskclass(row.get('name', ''))
        if cls is None:
            if row.get('name') == 'campaign_reward_exchange':
                raise ValueError('活动领奖已并入 campaign_clean，请从配置移除旧 campaign_reward_exchange；活动日常会自动领奖和兑换')
            raise ValueError(f"未知任务：{row.get('name')}")
        inspect.signature(cls.run).bind(None, *row['args'])
        if row['name'] == 'shop_buy':
            if not row['args'] or not isinstance(row['args'][0], dict):
                raise ValueError('shop_buy.rule 必须是购买规则对象')
            # JSON object keys are strings; the legacy task distinguishes integer
            # tab IDs from string keys such as "1_time". Restore only numeric IDs.
            row['args'][0] = {int(k) if isinstance(k, str) and k.isdecimal() else k: v
                              for k, v in row['args'][0].items()}
        params = list(inspect.signature(cls.run).parameters.values())[1:]
        for value, param in zip(row['args'], params):
            default = param.default
            if isinstance(default, bool) and not isinstance(value, bool):
                raise ValueError(f'{row["name"]}.{param.name} 必须为布尔值')
            if isinstance(default, (int, float)) and not isinstance(default, bool) and (not isinstance(value, (int, float)) or isinstance(value, bool)):
                raise ValueError(f'{row["name"]}.{param.name} 必须为数字')
    return plan


def save_config(path: Path, request: dict[str, Any]) -> dict[str, Any]:
    import yaml
    ensure_idle()
    if revision(path) != request.get('revision'):
        raise ValueError('配置已被其他程序修改，请重新加载后保存')
    plan = validate_plan(request['plan'])
    options = request['options']
    if not isinstance(options, dict) or any(k in options for k in ('Accounts', 'Task', 'Desktop')):
        raise ValueError('公共配置必须是对象，不可覆盖账号和任务列表')
    if not isinstance(options.get('Extra'), dict) or not isinstance(options['Extra'].get('dnpath', ''), str):
        raise ValueError('Extra.dnpath 必须是字符串')
    for key in ('adb_path', 'adb_serial'):
        if not isinstance(options['Extra'].get(key, ''), str):
            raise ValueError(f'Extra.{key} 必须是字符串')
    source = request.get('source')
    if source is not None:
        if path.exists():
            raise ValueError('另存为的目标已存在，请选择新文件')
        source_path = Path(source)
        if revision(source_path) != request.get('source_revision'):
            raise ValueError('源配置已被修改，请重新加载后另存为')
        config = read_config(source_path)
    elif request.get('new'):
        if path.exists():
            raise ValueError('新配置目标已存在，请选择新文件')
        config = {'Accounts': [], 'Task': {1: []}}
    else:
        config = read_config(path if path.exists() else runtime_defaults_path())
    groups = config.setdefault('Task', {})
    selected = next(iter(groups), 1)
    config.update(options)
    groups[selected] = [[row['name'], *row['args']] for row in plan if row['enabled']]
    config.pop('Desktop', None)
    disabled = [dict(index=index, name=row['name'], args=row['args'])
                for index, row in enumerate(plan) if not row['enabled']]
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.with_suffix(path.suffix + '.bak').write_bytes(path.read_bytes())
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    state_path = plan_state_path(path)
    if disabled:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_temp = state_path.with_name(state_path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            state_temp.write_text(json.dumps(dict(task_hash=task_signature(groups[selected]), disabled=disabled),
                                             ensure_ascii=False), encoding='utf-8')
            os.replace(state_temp, state_path)
        finally:
            state_temp.unlink(missing_ok=True)
    else:
        state_path.unlink(missing_ok=True)
    return config_view(path)


def run_folder(run_id: str) -> Path:
    # Never accept an arbitrary path from the client for control operations.
    return ROOT / 'cache/daily/runs' / str(uuid.UUID(run_id))


def control(run_id: str, action: str) -> dict[str, Any]:
    from pcrscript.run_session import atomic_json
    folder = run_folder(run_id)
    state = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
    if state['state'] not in ('running', 'paused') or time.time() - state['heartbeat'] > 10:
        raise ValueError('运行已结束或心跳失联，不能发送控制命令')
    command = dict(id=uuid.uuid4().hex, action=action, requested_at=time.time())
    destination = folder / ('snapshot-request.json' if action == 'snapshot' else 'control.json')
    if destination.exists() and action != 'stop':
        previous = json.loads(destination.read_text(encoding='utf-8'))
        ack = state.get('snapshot_id' if action == 'snapshot' else 'command_id')
        if previous.get('id') != ack:
            raise ValueError('上一个控制请求尚未确认')
    atomic_json(destination, command)
    return dict(protocol=PROTOCOL, requested=True, command_id=command['id'])


def execute(path: Path, request: dict[str, Any], run_id: str) -> None:
    from pcrscript.run_session import RunSession
    from pcrscript.runtime import run_task_with_config, print_report
    name = request.get('task', 'daily')
    config = read_config(path) if name == 'daily' else request.get('options')
    if not isinstance(config, dict):
        raise ValueError('单任务请提供 GUI 运行选项，无需配置文件')
    extra = config.get('Extra')
    section = {'abyss_push': 'Abyss', 'dungeon_first_clear': 'Dungeon'}.get(name)
    prepare_only = bool(section and isinstance(config.get(section), dict) and config[section].get('prepare_only') is True)
    if not prepare_only and not isinstance(extra, dict):
        raise ValueError('请先配置 Extra 运行环境')
    with RunSession(name, run_id=run_id):
        if name == 'daily':
            from pcrscript.runtime import open_leidian_emulator, run_script, select_driver
            from pcrscript.run_session import emit
            tasks = next(iter(config.get('Task', {}).values()), [])
            validate_plan([dict(enabled=True, name=t[0], args=t[1:]) for t in tasks])
            if not tasks:
                raise ValueError('没有启用的每日任务')
            emit('progress', scope='action', label='启动游戏与连接设备', unit='task')
            dnpath = str(config['Extra'].get('dnpath') or '').strip()
            if dnpath:
                if open_leidian_emulator(dnpath) != 0:
                    raise RuntimeError('雷电模拟器启动失败')
            else:
                import subprocess
                from pcrscript.run_session import clock
                driver = select_driver(config)
                subprocess.run([driver.adb_path, '-s', driver.device_name, 'shell', 'monkey', '-p', 'com.bilibili.priconne', '1'], check=True)
                clock.sleep(30)
            run_script(config)
        else:
            args = request.get('args', [])
            validate_plan([dict(enabled=True, name=name, args=args)])
            print_report(run_task_with_config(config, name, *args))


def main() -> None:
    os.chdir(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['environment', 'devices', 'catalog', 'new', 'load', 'save', 'idle', 'control', 'run'])
    parser.add_argument('--config', default='daily_config.yml')
    parser.add_argument('--run-id')
    parser.add_argument('--action', choices=['pause', 'resume', 'snapshot', 'stop'])
    args = parser.parse_args()
    try:
        if args.command == 'environment':
            result = environment_report()
        elif args.command == 'devices':
            result = device_report(json.load(sys.stdin))
        elif args.command == 'catalog':
            result = dict(protocol=PROTOCOL, catalog=catalog())
        elif args.command == 'new':
            result = new_config()
        elif args.command == 'load':
            result = config_view(Path(args.config))
        elif args.command == 'save':
            result = save_config(Path(args.config), json.load(sys.stdin))
        elif args.command == 'idle':
            ensure_idle()
            result = dict(protocol=PROTOCOL, idle=True)
        elif args.command == 'control':
            result = control(args.run_id, args.action)
        else:
            execute(Path(args.config), json.load(sys.stdin), args.run_id)
            return
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        print(json.dumps(dict(protocol=PROTOCOL, error=str(error)), ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
