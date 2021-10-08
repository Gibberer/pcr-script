import sys


class Ocr():
    def __init__(self, languagelist=['ch_sim', 'en'], **kwargs):
        if 'easyocr' not in sys.modules:
            import easyocr
        self.reader = easyocr.Reader(languagelist, **kwargs)

    def recognize(self, img):
        result = self.reader.readtext(img)
        if result:
            return [r[1] for r in result]

    def find_match_text_pos(self, img, text):
        result = self.reader.readtext(img)
        for r in result:
            if r[1] == text:
                return ((r[0][2][0] - r[0][0][0])/2, (r[0][3][1] - r[0][1][1])/2)
        return None
