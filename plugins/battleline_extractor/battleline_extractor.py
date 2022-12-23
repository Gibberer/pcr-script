import cv2 as cv
from battleline_parser import *
import yaml

if __name__ == "__main__":
    parser = ExcelLikeParser()
    result = parser.parse(cv.imread("test.png"))
    with open("output.yaml", "w", encoding="utf-8") as f:
        f.write("job_list:\n")
        f.write(f"  \"Test Output\":\n")
        for line in result:
            if line.charactor == -1:
                f.write(f"    # {line.memo}\n")
            else:
                f.write(f"    - {line.time} {line.charactor} # {line.memo}\n")
    