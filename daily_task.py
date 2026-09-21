import yaml
import os
from pcrscript.run_session import clock as time
from pcrscript import DNSimulator, Robot, GeneralSimulator
from pcrscript.runtime import open_leidian_emulator, modify_task_list, run_script

def main():
    with open("daily_config.yml", encoding="utf-8") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    dnpath = config["Extra"]["dnpath"]
    if dnpath:
        return_code = open_leidian_emulator(dnpath)
        if return_code < 0:
            print("open leidian emulator failed")
        else:
            print("leidian emulator install path is configured, use leidian console.")
            run_script(config, False)
    else:
        print("leidian emulator install path not found, use ADB command.")
        os.system(
                f'adb -s {GeneralSimulator().get_devices()[0]} shell monkey -p com.bilibili.priconne 1'
            )
        time.sleep(30)
        run_script(config, True)
        


if __name__ == "__main__":
    from pcrscript.run_session import RunSession
    with RunSession("daily"):
        main()
