from enum import Enum

class Difficulty(Enum):
    NORMAL = 0
    HARD = 1
    VERY_HARD = 2

BASE_WIDTH = 960
BASE_HEIGHT = 540
THRESHOLD = 0.8  # 如果使用960x540 匹配度一般在0.95以上,默认为0.8,,如果在480x270上可以调成0.65试试

TEAM_LOCATION = (
    (790, 207),
    (790, 320),
    (790, 428)
)
TEAM_GROUP_LOCATION = (
    (117,90),
    (270,90),
    (410,90),
    (550,90),
    (696,90)
)

SHOP_TAB_LOCATION = (
    (179, 69),(258, 69),(356, 69),(447, 69),(534, 69),(634, 69),(734, 69),(824, 69),(913, 69),
)

SHOP_ITEM_LOCATION = (
    (387, 149), (560, 149), (729, 149), (900, 149),
    (387, 407), (560, 407), (729, 407), (900, 407),
)

SHOP_ITEM_LOCATION_FOR_LAST_LINE = (
    (387, 197), (560, 197), (729, 197), (900, 197),
)