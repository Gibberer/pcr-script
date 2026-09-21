"""Task API and registration; concrete implementations live in feature modules."""
from .base import BaseTask, TimeLimitTask, Event, EventNews
from .image import ImageTask
from .registry import register, find_taskclass
from .task_home import ToHomePage
from .task_gacha import FreeGacha, NormalGacha
from .task_adventure import CommonAdventure, QuickClean, AdventureDaily
from .task_shop import ShopBuy
from .task_story import ClearStory, GetQuestReward
from .task_routines import Arena, PrincessArena, Research, Schedule
from .task_combat import TeamFormation, TeamFormationEx, Combat
from .task_tower import LunaTowerClean, LunaTowerClimbing
from .task_gifts import GetGift
from .task_story_event import CampaignClean, CampaignRewardExchange, ClearCampaignFirstTime
from .task_revival_event import RevivalEventOnce
from .task_caravan import Caravan
