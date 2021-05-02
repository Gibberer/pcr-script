import sys

class Ocr():
    def __init__(self, languagelist=['ch_sim','en'], **kwargs):
        if 'easyocr' not in sys.modules:
            import easyocr
        self.reader = easyocr.Reader(languagelist, **kwargs)
    
    def recognize(self, img):
        result = self.reader.readtext(img)
        if result:
            return [r[1] for r in result] 