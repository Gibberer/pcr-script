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

PROTOCOL = 1
LABELS = {
    'upgrade_all_characters': '强化所有角色装备和等级到上限',
    'dungeon_first_clear': '地下城 · 首次通关',
    'dungeon_sources': '地下城 · 搜索队伍来源',
    'caravan': '驾车游 · 清空骰子', 'get_gift': '礼物箱 · 领取邮件与赠礼', 'campaign_clean': '剧情活动日常',
    'revival_event_once': '复刻活动', 'tohomepage': '返回首页', 'free_gacha': '免费十连',
    'normal_gacha': '普通扭蛋', 'arena': '竞技场', 'princess_arena': '公主竞技场',
    'research': '圣迹 / 神殿调查', 'schedule': '日程表', 'shop_buy': '商店购买',
    'quick_clean': '快捷扫荡', 'adventure_daily': '冒险日常', 'common_adventure': '普通冒险',
    'clear_story': '阅读剧情', 'get_quest_reward': '首页任务 · 领取任务奖励',
    'luna_tower_clean': '露娜塔扫荡', 'luna_tower_climbing': '露娜塔登塔',
    'clear_campaign_first_time': '活动首通',
}
SPECIAL_TASKS = {'clear_story', 'dungeon_first_clear', 'dungeon_sources',
                 'upgrade_all_characters', 'common_adventure', 'caravan', 'tohomepage'}

PARAMETER_LABELS = {
    'multi': '抽取所有可用免费十连', 'exclude_stamina': '暂不领取体力',
    'hard_chapter': '扫荡活动困难关卡', 'exhaust_power': '剩余体力用于普通关卡',
    'pos': '快捷扫荡预设编号', 'rule': '商店购买规则', 'click_pos': '首页按钮坐标',
    'timeout': '超时时间（秒）', 'character_symbol': '冒险角色模板',
    'estimate_combat_duration': '预估战斗时长（秒）', 'allow_system_recommend': '允许系统推荐编队',
}
DESCRIPTIONS = {
    'upgrade_all_characters': '使用角色页一键强化，分批提升全部可强化角色至最高可用品级，并强化等级、技能和普通装备。使用现有玛那、装备与原矿；不购买资源、不改变星数或专武开关。',
    'dungeon_sources': '匿名检索地下城攻略视频，核验视频身份并保存分P、来源、时间和地区标记。无需模拟器，不直接生成战斗队伍。',
    'dungeon_first_clear': '按本地路线推进地下城首通。首领战前预检整条路线的角色占用与培养，每场保存实际伤害和配装证据；支持主力、换季、补刀与收尾队。已完成区域跳过，实际方案存于本地 cache/game/strategies/dungeon_teams.yml。',
    'caravan': '从冒险进入驾车游，消耗持有的骰子。未达标时使用单骰争取15回合内到达；已解锁时使用快速通关。不购买骰子，默认不加入每日列表。',
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
    'shop_buy': '按购买规则进入对应商店购买物品，消耗相应货币。复杂规则用 JSON 编辑，例如 {"1":[-1]} 表示普通商店全选。',
    'quick_clean': '执行游戏已保存的快捷扫荡预设（1～7）。配置列表执行时，仅困难掉落活动开放会切换到预设3；请先在游戏内确认预设内容。',
    'adventure_daily': '处理探险归来、再次出发及探险地图事件。沿用游戏内已有探险编队。',
    'common_adventure': '在当前冒险地图根据角色模板定位关卡并循环战斗。需事先进入对应地图；这是持续推进任务，需要手动停止，不适合无条件加入日常。',
    'clear_story': '处理剧情页面的可读剧情和跳过流程。任务依赖已有图片模板识别。',
    'get_quest_reward': '进入首页的任务页面领取已完成任务奖励（含体力），不领取礼物箱或活动页奖励。示例日常先领体力供扫荡使用，最后再补领新完成任务的奖励。',
    'luna_tower_clean': '在露娜塔开放且已完成对应进度时扫荡回廊。配置列表会根据活动情报筛选。',
    'luna_tower_climbing': '执行露娜塔登塔战斗，可选择是否允许系统推荐编队。会进入实际战斗，需确认队伍与当前进度。',
    'clear_campaign_first_time': '保留的活动首通兼容入口，复用剧情活动流程。是否真正推进首通仍取决于 StoryEvent.first_clear；当前默认关闭，首日连续流程仍待实测。',
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
        name, expected = requirement.split('==', 1)
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = None
        if actual != expected:
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
                           requires_device=name != 'dungeon_sources',
                           entry='执行前自动返回首页' if cls.requires_home else '需先进入目标冒险地图' if name == 'common_adventure' else '任务自行处理页面导航'))
    return result


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
    config = read_config(path if path.exists() else Path(__file__).with_name('runtime_defaults.yml'))
    return config_data(config, revision(path))


def new_config() -> dict[str, Any]:
    config = read_config(Path(__file__).with_name('runtime_defaults.yml'))
    config['Accounts'] = []
    config['Task'] = {1: []}
    config.pop('Desktop', None)
    return config_data(config, '')


def config_data(config: dict[str, Any], digest: str) -> dict[str, Any]:
    task_groups = config.get('Task', {})
    if not isinstance(task_groups, dict):
        raise ValueError('Task 必须是账号到任务列表的映射')
    selected = next(iter(task_groups), 1)
    tasks = task_groups.get(selected, [])
    saved = config.get('Desktop', {}).get('plan')
    # External YAML edits take precedence over the saved disabled-row view.
    if not isinstance(saved, list) or [[r['name'], *r['args']] for r in saved if r.get('enabled')] != tasks:
        saved = [dict(enabled=True, name=row[0], args=row[1:]) for row in tasks]
    # Remove only old, parameterless navigation separators from the GUI plan.
    # Explicit custom-coordinate/timeout tasks remain editable and executable.
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
    if not isinstance(options.get('Extra'), dict) or not isinstance(options['Extra'].get('dnpath'), str):
        raise ValueError('Extra.dnpath 必须是雷电路径字符串')
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
        config = read_config(path if path.exists() else Path(__file__).with_name('runtime_defaults.yml'))
    groups = config.setdefault('Task', {})
    selected = next(iter(groups), 1)
    config.update(options)
    groups[selected] = [[row['name'], *row['args']] for row in plan if row['enabled']]
    config.setdefault('Desktop', {})['plan'] = plan
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.with_suffix(path.suffix + '.bak').write_bytes(path.read_bytes())
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
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
    if name != 'dungeon_sources' and (not isinstance(extra, dict) or not isinstance(extra.get('dnpath'), str) or not extra['dnpath'].strip()):
        raise ValueError('请先配置雷电路径；GUI 不使用 ADB')
    with RunSession(name, run_id=run_id):
        if name == 'daily':
            from pcrscript.runtime import open_leidian_emulator, run_script
            tasks = next(iter(config.get('Task', {}).values()), [])
            validate_plan([dict(enabled=True, name=t[0], args=t[1:]) for t in tasks])
            if not tasks:
                raise ValueError('没有启用的每日任务')
            if open_leidian_emulator(config['Extra']['dnpath']) != 0:
                raise RuntimeError('雷电启动失败')
            run_script(config, False)
        else:
            args = request.get('args', [])
            validate_plan([dict(enabled=True, name=name, args=args)])
            print_report(run_task_with_config(config, name, *args))


def main() -> None:
    os.chdir(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['environment', 'catalog', 'new', 'load', 'save', 'idle', 'control', 'run'])
    parser.add_argument('--config', default='daily_config.yml')
    parser.add_argument('--run-id')
    parser.add_argument('--action', choices=['pause', 'resume', 'snapshot', 'stop'])
    args = parser.parse_args()
    try:
        if args.command == 'environment':
            result = environment_report()
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
