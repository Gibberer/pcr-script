from .floordict import FloorDict
from enum import Enum

class Difficulty(Enum):
    NORMAL = 0
    HARD = 1
    VERY_HARD = 2

BASE_WIDTH = 960
BASE_HEIGHT = 540
THRESHOLD = 0.8  # 如果使用960x540 匹配度一般在0.95以上,默认为0.8,,如果在480x270上可以调成0.65试试
HARD_CHAPTER_POS = (
    (237, 339), (469, 263), (697, 321),
    (279, 265), (475, 358), (730, 337),
    (253, 259), (478, 342), (729, 269),
    (248, 258), (483, 223), (768, 249),
    (244, 319), (455, 245), (698, 261),
    (266, 298), (499, 304), (718, 248),
    (275, 239), (481, 328), (759, 277),
    (213, 390), (477, 355), (718, 286),
    (221, 267), (484, 338), (768, 282),
    (218, 350), (486, 246), (765, 326),
    (220, 359), (482, 239), (771, 317),
    (217, 252), (488, 346), (764, 238),
    (217, 244), (485, 355), (781, 337),
    (220, 343), (484, 245), (776, 332),
    (213, 227), (488, 353), (774, 271),
    (226, 351), (490, 258), (766, 283),
    (215, 291), (490, 342), (766, 264),
    (226, 270), (490, 350), (766, 283),
    (226, 330), (490, 270), (766, 320),
    (226, 280), (490, 320), (766, 264),
    (226, 266), (490, 320), (766, 260),
    (217, 330), (483, 269), (769, 321),
    (218, 274), (490, 328), (769, 258),
    (218, 280), (490, 356), (769, 251),
    (218, 290), (490, 350), (769, 240),
    (218, 290), (490, 241), (769, 333),
    (218, 290), (490, 360), (769, 300),
    (250, 231), (490, 350), (770, 280),
)

VH_CHAPTER_POS = (
    (216, 266), (483, 363), (780, 293),
    (218, 336), (483, 255), (780, 290)
)

GUILD_BOSS_POS = ((115, 291), (277, 290), (460, 168), (617, 234), (833, 248))
CHAPTER_NONE = ((0, 0),)

CHAPTER_1 = ((106, 281), (227, 237), (314, 331), (379, 235), (479, 294),
             (545, 376), (611, 305), (622, 204), (749, 245), (821, 353))
CHAPTER_2 = ((120, 410), (253, 410), (382, 378), (324, 274), (235, 216), (349, 162), (457, 229),
             (500, 319), (600, 375), (722, 370), (834, 348), (816, 227))
CHAPTER_2_ZOOM = ((48, 410), (180, 412), (302, 381), (256, 276), (157, 210), (275, 170), (377, 230),
                  (426, 321), (526, 377), (648, 377), (755, 341), (742, 226))
CHAPTER_3 = ((135, 185), (192, 309), (284, 229), (414, 230), (379, 343), (488, 411), (532, 289),
             (615, 194), (691, 272), (675, 390), (821, 339), (835, 211))
CHAPTER_4 = (
    (168, 239), (259, 312), (367, 267),
    (487, 340), (483, 371), (605, 345),
)
CHAPTER_4_ZOOM = (
    (44, 200), (136, 317), (246, 266),
    (361, 242), (349, 375), (483, 345),
)
CHAPTER_15 = (
    (0, 0), (0, 0), (0, 0), (0, 0), (0, 0), (0, 0), (0, 0), (0, 0), (0, 0),
    (352, 361), (498, 401), (651, 397), (753, 302), (597, 255)
)
CHAPTERS = (
    FloorDict({0: CHAPTER_1}),
    FloorDict({0: CHAPTER_2, 8: CHAPTER_2_ZOOM}),
    FloorDict({0: CHAPTER_3}),
    FloorDict({0: CHAPTER_4, 5: CHAPTER_4_ZOOM}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_15}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE}),
)
CHAPTER_SYMBOLS = (
    'chapter1', 'chapter2', 'chapter3', 'chapter4', 'chapter5', 'chapter6', 'chapter7', 'chapter8',
    'chapter9', 'chapter10', 'chapter11', 'chapter12', 'chapter13', 'chapter14', 'chapter15', 'chapter16',
    'chapter17', 'chapter18', 'chapter19', 'chapter20','chapter21','chapter22', 'chapter23','chapter24',
    'chapter25', 'chapter26','chapter27','chapter28'
)

VH_CHAPTERS = (
    FloorDict({0: CHAPTER_NONE}),
    FloorDict({0: CHAPTER_NONE})
)

VH_CHAPTER_SYMBOLS = (
    'chapter18','chapter19'
)

ACTIVITY_YLY = ((168, 322), (261, 247), (334, 356), (415, 231), (488, 317),
                (601, 348), (651, 239), (733, 338), (832, 301), (925, 246))
ACTIVITY_YLY_1 = ((57, 328), (149, 250), (229, 351), (310, 225), (378, 316),
                  (479, 347), (546, 237), (623, 343), (712, 296), (820, 243), (879, 337))

ACTIVITIES = (
    FloorDict({0: ACTIVITY_YLY, 4: ACTIVITY_YLY_1}),
)

ACTIVITY_SYMBOLS = ('activity_symbol',)

TEAM_LOCATION = (
    (790, 170),
    (790, 290),
    (790, 409)
)
TEAM_GROUP_LOCATION = (
    (117,90),
    (270,90),
    (410,90),
    (550,90),
    (696,90)
)
DUNGEON_LOCATION = ((136, 251), (361, 241), (627, 242), (780, 238))
DUNGEON_LEVEL_POS = (
    [(669, 279), (475, 256), (301, 269),
     (542, 287), (417, 275), (597, 275), (454, 255)],
    [],
    [],
    [(669, 279), (622, 280), (327, 277),
     (679, 290), (300, 185)],
    [(471, 245), (643, 267), (495, 286),
     (424, 249), (500, 266)],
)

SHOP_TAB_LOCATION = (
    (279, 69),(358, 69),(456, 69),(547, 69),(634, 69),(734, 69),(824, 69),(913, 69),
)

SHOP_ITEM_LOCATION = (
    (387, 149), (560, 149), (729, 149), (900, 149),
    (387, 407), (560, 407), (729, 407), (900, 407),
)
