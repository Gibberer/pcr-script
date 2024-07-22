from flet import colors

_color_set = [
    colors.RED, 
    colors.PINK, 
    colors.PURPLE, 
    colors.DEEP_PURPLE_500,
    colors.INDIGO, 
    colors.BLUE, 
    colors.ORANGE,
    colors.BLUE_GREY,
    colors.YELLOW,
    colors.CYAN,
    colors.TEAL,
    colors.BROWN,
    colors.DEEP_ORANGE,
    colors.LIME,
    colors.GREY
]

def text2color(text:str):
    size = len(_color_set)
    index = 0
    for b in text.encode():
        index = (index + b + 47) % size
    return _color_set[index]
    