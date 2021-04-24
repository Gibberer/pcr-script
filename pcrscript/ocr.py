import sys

class Ocr():
    def __init__(self):
        if 'easyocr' not in sys.modules:
            import easyocr
        self.reader = easyocr.Reader(['ch_sim','en'])
    
    def recognize(self, img, roi):
        result = self.reader.readtext(img[roi[1]:roi[3],roi[0]:roi[2]])
        if result:
            return [r[1] for r in result] 