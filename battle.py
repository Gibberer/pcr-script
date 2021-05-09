import yaml
from pcrscript import *
from autobattle.autobattle import AutoBattle
if __name__ == '__main__':
    drivers = DNSimulator2("").get_dirvers()
    auto_battle = AutoBattle(drivers[0])
    auto_battle.load("autobattle_config.yml")
    auto_battle.start()