from cv2 import cv2 as cv
from battline_parser import *
import yaml

if __name__ == "__main__":
    parser = ExcelLikeParser()
    result = parser.parse(cv.imread("test.png"))
    with open("output.yaml", "w", encoding="utf-8") as f:
        f.write("job_list:\n")
        f.write(f"\t\"Test Output\":\n")
        for line in result:
            if line.charactor == -1:
                f.write(f"\t\t# {line.memo}\n")
            else:
                f.write(f"\t\t- {line.time} {line.charactor} # {line.memo}\n")
    