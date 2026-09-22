"""Read-only registered guide search, also available without an emulator."""
from .base import BaseTask
from .registry import register
from .dungeon_sources import discover_sources

@register('dungeon_sources')
class DungeonSources(BaseTask):
    config_section = 'DungeonSources'

    @classmethod
    def prepare(cls, config, *args, **kwargs):
        if args or kwargs:
            raise ValueError('dungeon_sources使用DungeonSources配置，不接受位置参数')
        return (), {}, discover_sources(dict(config.get(cls.config_section,{})))

    def run(self):
        return discover_sources(self.task_options())
