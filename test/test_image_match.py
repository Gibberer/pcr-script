import sys
import yaml
import cv2 as cv
import numpy as np
sys.path.insert(0,".")

from pcrscript.robot import Robot
from pcrscript.simulator import DNSimulator2
from pcrscript.ocr import Ocr

def _imgshow(template_name, screenshot, point_list):
    screenshot = screenshot.copy()
    template = cv.imread(f"images/{template_name}.png")
    theight,twidth = template.shape[:2]
    for point, val in point_list:
        x,y = point
        left_top = (int(x-twidth/2), int(y-theight/2))
        right_bottom = (int(x+twidth/2),int(y+theight/2))
        cv.rectangle(screenshot, left_top, right_bottom,(255,0,0), 3)
        cv.putText(screenshot,str(val), (int(x),int(y)), cv.FONT_HERSHEY_SIMPLEX, 0.8, (36, 255, 12), 2)
    cv.imshow("Image",screenshot)
    cv.waitKey(0)
    cv.destroyAllWindows()

def _test_and_show_image(robot:Robot, template_name, threshold=0.6, mode=None):
    screenshot = robot.driver.screenshot()
    result = robot._find_match_pos_list(screenshot, template_name,threshold=threshold, mode=mode,for_test=True)
    if result:
        if mode == 'binarization':
            binary_screen = cv.cvtColor(screenshot, cv.COLOR_BGR2GRAY)
            _, binary_screen = cv.threshold(binary_screen, 220, 255, cv.THRESH_BINARY_INV)
            # print(Ocr(languagelist=["en"]).recognize(binary_screen))
            cv.imshow("Binary mode",binary_screen)
        _imgshow(template_name, screenshot, result)
            

def test_btn_activity_match(robot:Robot):
    _test_and_show_image(robot, "btn_activity_plot")

def test_1_1_image_match(robot:Robot):
    _test_and_show_image(robot, "1-1", mode='binarization')

def test_very_hard_image_match(robot:Robot):
    _test_and_show_image(robot, "very", mode='binarization')

if __name__ == "__main__":
    with open('daily_config.yml', encoding='utf-8') as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    drivers = DNSimulator2(config['Extra']['dnpath'],useADB=False).get_dirvers()
    robot = Robot(drivers[0])
    test_1_1_image_match(robot)
