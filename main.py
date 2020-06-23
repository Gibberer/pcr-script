from simulator import DNSimulator2
from robot import Robot
from floordict import FloorDict
import threading
import time

def getaccount():
    with open("account.txt", 'r') as f:
        return [ line.strip('\n').split(' ') for line in f.readlines()]

def getTaskDict()->FloorDict:
    floor_dict = FloorDict()
    floor_dict[1] = [
        ('get_quest_reward',),#领任务体力
        ('tohomepage',),#回首页
        ('close_ub_animation',),#关ub动画
        ('tohomepage',),#回首页
        ('advanture_1',9,9,30),#刷一章冒险
        ('tohomepage',),
        ('get_quest_reward',),#领任务
    ]
    floor_dict[2] = [
        ('get_quest_reward',),
        ('tohomepage',),
        ('buy_mana',20),
        ('saodang',1,3,40),#扫荡
        ('tohomepage',),
        ('get_quest_reward',)
    ]
    return floor_dict

task_dict = getTaskDict()
drivers = DNSimulator2("N:\dnplayer2").get_dirvers()
account_list = getaccount()
total_size = len(account_list)
thread_list = []
lock = threading.Lock()
def dostaff(robot:Robot):
    while True:
        with lock:
            if len(account_list) == 0:
                break
            account, password = account_list.pop(0)
            no = total_size - len(account_list)
        robot.changeaccount(account, password, logpath='output.log')
        robot.work(task_dict[no])
for driver in drivers:
    robot = Robot(driver)
    thread_list.append(threading.Thread(target=dostaff, args=(robot,)))
start_time = time.time()
print("start {} thread".format(len(thread_list)))
for thread in thread_list:
    thread.start()
print("wait thread finish")
for thread in thread_list:
    thread.join()
print("consume time: {}".format(time.time() - start_time))

