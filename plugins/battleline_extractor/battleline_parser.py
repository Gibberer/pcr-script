from collections import namedtuple
from abc import ABCMeta, abstractmethod
from typing import Iterable
from numpy import ndarray
from paddleocr import PaddleOCR
import sqlite3
import json

Line = namedtuple("Line", ["time", "charactor", "memo"])
RecResult = namedtuple("RecResult", ["bounds", "content", "accuracy"])

class Parser(metaclass=ABCMeta):
    
    @abstractmethod
    def parse(self, image:ndarray)->Iterable[Line]:
        pass

class ImageRecognizer(metaclass=ABCMeta):

    @abstractmethod
    def recognize(self, image:ndarray)->Iterable[RecResult]:
        pass

class PaddleOCRImageRecognizer(ImageRecognizer):

    def __init__(self):
        self._paddle_ocr = PaddleOCR(use_angle_cls=True, lang="ch")

    def recognize(self, image:ndarray)->Iterable[RecResult]:
        ret = self._paddle_ocr.ocr(image, cls=True)
        if ret:
            result = []
            for line in ret:
                result.append(RecResult(bounds=line[0], content = line[1][0], accuracy = line[1][1]))
            return result
        else:
            return None

class PaddleOCROnlineImageRecognizer(ImageRecognizer):
    '''
    调用接口进行ocr识别
    '''

    def __init__(self, token):
        pass

    def recognize(self, image:ndarray)->Iterable[RecResult]:
        pass

class ExcelLikeParser(Parser):
    '''
    处理图似Excel格式的轴数据
    '''

    def __init__(self, imageRecognizer: ImageRecognizer = None):
        self._recognizer = imageRecognizer
        if not self._recognizer:
            self._recognizer = PaddleOCRImageRecognizer()
        self._charactor_dict = self._buildCharactorDict()

    def parse(self, image:ndarray)->Iterable[Line]:
        grouped_rec = self._ocr(image)
        pos_dict = self._get_charactor_position(grouped_rec)
        grouped_rec = self._get_valid_rect(grouped_rec)
        result = self._build_result(grouped_rec, pos_dict)
        return result

    def _ocr(self, image:ndarray):
        rec_ret = self._recognizer.recognize(image)
        # 对结果分组
        rec_ret.sort(key=lambda x : x.bounds[0][1])
        result = []
        rows = None
        cur_start = -1
        cur_end = -1
        for rec in rec_ret:
            start = rec.bounds[0][1]
            end = rec.bounds[2][1]
            if start > cur_end:
                rows = []
                result.append(rows)
                cur_start = start
            if end > cur_end:
                cur_end = end
            rows.append(rec)
        for rows in result:
            rows.sort(key=lambda x: x.bounds[0][0])
        return result
    
    def _buildCharactorDict(self):
        _dict = {}
        # 读取角色的距离数据，用于计算站位
        conn = sqlite3.connect("./data/redive_cn.db")
        cursor = conn.cursor()
        cursor.execute("select unit_name,search_area_width from unit_data")
        for name, distance in cursor.fetchall():
            _dict[name] = distance
        conn.close()
        # 读取别名数据
        with open('./data/alias.json', "r", encoding="utf-8") as f:
            alias_data = json.load(f)
            reverted_map = {}
            for key, value in alias_data.items():
                for alias in value:
                    reverted_map[alias] = key
            for key, value in reverted_map.items():
                if value in _dict:
                    _dict[key] = _dict[value]
        return _dict
    
    def _get_charactor_position(self, grouped_rec):
        defined_charactors = set()
        for row in grouped_rec:
            defined_charactors.clear()
            for rec in row:   
                if rec.content in self._charactor_dict:
                    defined_charactors.add((rec.content, self._charactor_dict[rec.content]))
            if len(defined_charactors) == 5:
                break
        if len(defined_charactors) != 5:
            # 可能没有用文字列出来，全局搜索出现的角色名
            defined_charactors.clear()
            for row in grouped_rec:
                for rec in row:
                    if rec.content in self._charactor_dict:
                        defined_charactors.add((rec.content, self._charactor_dict[rec.content]))
            if len(defined_charactors) != 5:
                raise Exception("识别出战角色失败")
        defined_charactors = sorted(defined_charactors, key=lambda x: x[1])
        _dict = {}
        for i, value in enumerate(defined_charactors):
            _dict[value[0]] = i + 1
        return _dict
    
    def _get_valid_rect(self, grouped_rec):
        start = 1
        for i, row in enumerate(grouped_rec):
            start = i + 1
            if self._is_time(row[0].content):
                break
        if start == len(grouped_rec):
            raise Exception("识别轴区域失败")
        return grouped_rec[start - 1:]
    
    def _is_time(self, content:str):
        return content.replace(".", "").replace(":", "").isdigit()

    def _build_result(self, grouped_rec, pos_dict):
        result = []
        cur_time = 90
        for row in grouped_rec:
            time, charactor, memo = self._parse_row(row, pos_dict)
            if time == None:
                time = cur_time
            else:
                cur_time = time
            result.append(Line(time=time, charactor=charactor, memo=memo))
        return result

    def _parse_row(self, row, pos_dict):
        time = None
        charactor = -1
        memo = ""
        offset = 0
        if self._is_time(row[offset].content):
            content = row[offset].content.replace(".", "").replace(":", "")
            if len(content) == 3:
                time = 60 * int(content[0]) + int(content[1:])
            elif len(content) < 3:
                time = int(content)
            else:
                raise Exception("解析轴时间失败")
            offset += 1
        if offset < len(row):
            if row[offset].content in pos_dict:
                charactor = pos_dict[row[offset].content]
                offset += 1
        if offset < len(row):
            for rec in row[offset:]:
                memo += rec.content
                memo += '    '
            memo = memo[:-1]
        return time, charactor, memo
        
        

            
