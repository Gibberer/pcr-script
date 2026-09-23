import argparse
from pathlib import Path
import subprocess
from pcrscript.run_session import clock as time
from pcrscript.runtime import load_config, modify_task_list, open_leidian_emulator, run_script, select_driver

def main():
    parser = argparse.ArgumentParser(description="运行当前配置中的完整日常")
    parser.add_argument("--config", default="daily_config.yml" if Path("daily_config.yml").exists() else "runtime_defaults.yml")
    args = parser.parse_args()
    config = load_config(args.config)
    if not any(config.get("Task", {}).values()):
        raise ValueError(f"配置 {args.config} 未启用日常任务；请先编辑 Task 或指定其他配置")
    dnpath = str(config.get("Extra", {}).get("dnpath") or "").strip()
    if dnpath:
        return_code = open_leidian_emulator(dnpath)
        if return_code < 0:
            raise RuntimeError("雷电启动失败")
        else:
            print("leidian emulator install path is configured, use leidian console.")
            run_script(config)
    else:
        driver = select_driver(config)
        print(f"使用 ADB 设备 {driver.device_name}")
        subprocess.run([driver.adb_path, "-s", driver.device_name, "shell", "monkey", "-p", "com.bilibili.priconne", "1"], check=True)
        time.sleep(30)
        run_script(config)
        


if __name__ == "__main__":
    from pcrscript.run_session import RunSession
    with RunSession("daily"):
        main()
