import yaml
from pcrscript import *
from pcrscript.constants import Difficulty
from pcrscript.simulator import DNSimulator
from pcrscript.ocr import Ocr
from pcrscript.tasks import *
import os

if __name__ == '__main__':
    with open('daily_config.yml', encoding='utf-8') as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    drivers = DNSimulator2(config['Extra']['dnpath']).get_dirvers()
    robot = Robot(drivers[0])
    
    CommonAdventure(robot).run(estimate_combat_duration=30)
    