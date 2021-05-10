import yaml
from pcrscript import *

if __name__ == '__main__':
    with open('config.yml', encoding='utf-8') as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    drivers = DNSimulator2(config['Extra']['dnpath']).get_dirvers()
    robot = Robot(drivers[0])
    robot._dungeon_saodang(5, 1, '4', '1,2,3,4,5,6,7,8,9,10', False)