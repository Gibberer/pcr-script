from simulator import DNSimulator2
from robot import Robot
from floordict import FloorDict
import threading
import time
import yaml

with open('config.yml', encoding='utf-8') as f:
    config = yaml.load(f, Loader=yaml.FullLoader)

def getTaskDict() -> FloorDict:
    floor_dict = FloorDict()
    task = config['Task']
    for key, values in task.items():
        floor_dict[key] = values
    return floor_dict

task_dict = getTaskDict()
drivers = DNSimulator2("N:\dnplayer2").get_dirvers()
account_list = [(account['account'], account['password'])
                for account in config['Accounts']]
total_size = len(account_list)
thread_list = []
lock = threading.Lock()

def dostaff(robot: Robot):
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
