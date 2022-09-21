from pcrscript import *
from pcrscript.tasks import *

if __name__ == '__main__':
    # 获取当前连接的设备列表
    drivers = DNSimulator2("").get_dirvers()
    # 创建robot实例用于执行任务
    robot = Robot(drivers[0])
    # 执行清剧情任务
    ClearStory(robot).run()