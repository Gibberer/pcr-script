import yaml
from pcrscript import *
from pcrscript.tasks import *

if __name__ == '__main__':
    with open('daily_config.yml', encoding='utf-8') as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    drivers = DNSimulator2(config['Extra']['dnpath'],useADB=False).get_dirvers()
    robot = Robot(drivers[0])
    ClearStory(robot).run() #清空所有未读剧情
    