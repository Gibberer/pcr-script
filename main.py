from simulator import Simulator
from driver import Driver
from robot import Robot
import threading

def getaccount():
    with open("account.txt", 'r') as f:
        return [ line.strip('\n').split(' ') for line in f.readlines()]

drivers = Simulator().get_dirvers()
account_list = getaccount()
thread_list = []
lock = threading.Lock()
def dostaff(robot:Robot):
    while True:
        with lock:
            if len(account_list) == 0:
                break
            account, password = account_list.pop(0)
        robot.changeaccount(account, password)
        robot.work()
for driver in drivers:
    robot = Robot(driver)
    thread_list.append(threading.Thread(target=dostaff, args=(robot,)))
print("start {} thread".format(len(thread_list)))
for thread in thread_list:
    thread.start()
print("wait thread finish")
for thread in thread_list:
    thread.join()

