from pcrscript import *
import threading
import time
import yaml
import getopt
import sys

def usage():
    print('''
    -h help
    -c 设置配置文件
    ''')

def getTaskDict(config) -> FloorDict:
    floor_dict = FloorDict()
    task = config['Task']
    for key, values in task.items():
        floor_dict[key] = values
    return floor_dict

def dostaff(robot: Robot, lock, account_list, total_size, task_dict):
    while True:
        with lock:
            if len(account_list) == 0:
                break
            account, password = account_list.pop(0)
            no = total_size - len(account_list)
        try:
            robot.changeaccount(account, password, logpath='output.log')
            robot.work(task_dict[no])
        except Exception as error:
            print(error) #发生异常跳过

def main():
    config_file = 'config.yml'
    try:
        opts, args = getopt.getopt(sys.argv[1:], 'hc:', ['help','config='])
        for name, value in opts:
            if name in ('-h','--help'):
                usage()
            elif name in ('-c','--config'):
                config_file = value
    except getopt.GetoptError as error:
        print(error)
        usage()
        return

    with open(config_file, encoding='utf-8') as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    task_dict = getTaskDict(config)
    drivers = DNSimulator2(config['Extra']['dnpath']).get_dirvers() 
    account_list = [(account['account'], account['password'])
                    for account in config['Accounts']]
    total_size = len(account_list)
    thread_list = []
    lock = threading.Lock()

    if not drivers:
        print("Device not found")
        return
    for driver in drivers:
        robot = Robot(driver)
        thread_list.append(threading.Thread(target=dostaff, args=(robot, lock, account_list,total_size, task_dict)))
    start_time = time.time()
    print("start {} thread".format(len(thread_list)))
    for thread in thread_list:
        thread.start()
    print("wait thread finish")
    for thread in thread_list:
        thread.join()
    print("consume time: {}".format(time.time() - start_time))

if __name__ =='__main__':
    main()

