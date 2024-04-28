from abc import ABCMeta,abstractmethod
import numpy as np
import cv2 as cv
from .constants import THRESHOLD,BASE_WIDTH,BASE_HEIGHT

class Template(metaclass=ABCMeta):

    def __init__(self) -> None:
        self.define_width = BASE_WIDTH
        self.define_height = BASE_HEIGHT

    def set_define_size(self, width, height)->'Template':
        self.define_width = width
        self.define_height = height
        return self
    
    def __and__(self, other):
        return _AndTemplate(self, other)

    def __or__(self, other):
        return _OrTemplate(self, other)
    
    @abstractmethod
    def match(self, screenshot:np.ndarray)->None|tuple:
        '''
        返回值基于screenshot
        '''
        pass

class _AndTemplate(Template):

    def __init__(self, a:Template, b:Template) -> None:
        super().__init__()
        self._a = a
        self._b = b
    
    def match(self, screenshot: np.ndarray):
        return self._a.match(screenshot) and self._b.match(screenshot)

class _OrTemplate(Template):

    def __init__(self, a:Template, b:Template) -> None:
        super().__init__()
        self._a = a
        self._b = b
    
    def match(self, screenshot: np.ndarray):
        return self._a.match(screenshot) or self._b.match(screenshot)

class BooleanTemplate(Template):
    def __init__(self, value:bool):
        super().__init__()
        self._value = value

    def match(self, screenshot: np.ndarray):
        return self._value

class ImageTemplate(Template):

    def __init__(self, name, threshold=THRESHOLD, mode=None, ret_count=1):
        super().__init__()
        self._name = name
        self._threshold = threshold
        self._mode = mode
        self._ret_count = ret_count
    
    def _create_result(self, x, y, twidth, theight, scalex, scaley):
        return (scalex * (x + twidth/2), scaley * (y + theight/2))

    def match(self, screenshot: np.ndarray):
        source = screenshot
        template = cv.imread(f"images/{self._name}.png")
        height, width = source.shape[:2]
        theight, twidth = template.shape[:2]
        fx = width/self.define_width
        fy = height/self.define_height
        ret_scalex = 1
        ret_scaley = 1
        if fx > 1 and fy > 1: 
            ret_scalex = fx
            ret_scaley = fy
            source = cv.resize(source, None, fx=1/fx, fy=1/fy, interpolation=cv.INTER_AREA)
        elif fx < 1 and fy < 1:
            template = cv.resize(template, None, fx=fx, fy=fy, interpolation=cv.INTER_AREA)
        elif not (fx == 1 and fy == 1):
            template = cv.resize(template, None, fx=fx, fy=fy, interpolation=cv.INTER_AREA)
        theight, twidth = template.shape[:2]
        if self._mode:
            if self._mode == 'binarization':
                source = cv.cvtColor(source, cv.COLOR_BGR2GRAY)
                _, source = cv.threshold(source, 220, 255, cv.THRESH_BINARY_INV)
                template = cv.cvtColor(template, cv.COLOR_BGR2GRAY)
                _, template = cv.threshold(template, 220, 255, cv.THRESH_BINARY_INV)
            elif self._mode == 'canny':
                source = cv.Canny(source, 180, 220)
                template = cv.Canny(template, 180, 220)
        ret = cv.matchTemplate(source, template, cv.TM_CCOEFF_NORMED)
        if self._ret_count == 1:
            min_val, max_val, min_loc, max_loc = cv.minMaxLoc(ret)
            if max_val > self._threshold:
                return self._create_result(max_loc[0], max_loc[1], twidth, theight, ret_scalex, ret_scaley)
            else:
                return None
        else:
            index_array = np.where(ret > self._threshold)
            matched_points = []
            for x, y in zip(*index_array[::-1]):
                duplicate = False
                for point in matched_points:
                    if abs(point[0] - x) < 8 and abs(point[1] - y) < 8:
                        duplicate = True
                    break
                if not duplicate:
                    matched_points.append((x,y))
            if matched_points:
                matched_points = list(map(lambda point: self._create_result(point[0], point[1], twidth, theight, ret_scalex, ret_scaley), matched_points))
                if self._ret_count > 0:
                    return matched_points[:self._ret_count]
                else:
                    return matched_points
            else:
                return None