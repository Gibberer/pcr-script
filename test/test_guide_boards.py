"""Static guide boards: five-card rows and their SET notes, on synthetic frames."""
from unittest import TestCase

import cv2 as cv
import numpy as np

from pcrscript.game_ui.avatars import AvatarIndex, face_crop, feature
from pcrscript.game_ui.guide_vision import GuideText
from pcrscript.tasks.strategy_tables import board_hint, guide_board_rows

STEP = 64
SIZE = 60


def board(rows, *, seed=3):
    """White page with outlined cards; each row is (x, y, names), a None name stays blank."""
    rng = np.random.default_rng(seed)
    image = np.full((720, 1280, 3), 245, np.uint8)
    faces = {}
    for x0, y, names in rows:
        for i, name in enumerate(names):
            x = x0+i*STEP
            cv.rectangle(image, (x, y), (x+SIZE, y+SIZE), (40, 40, 180), 2)
            if name is None:
                continue
            face = faces.setdefault(name, cv.resize(rng.integers(0, 255, (8, 8, 3), dtype=np.uint8), (SIZE-4, SIZE-4)))
            image[y+2:y+SIZE-2, x+2:x+SIZE-2] = face
    index = AvatarIndex(load_existing=False)
    index.read_only = True
    index.names = []
    vectors = []
    for x0, y, names in rows:
        for i, name in enumerate(names):
            if name is not None and name not in index.names:
                index.names.append(name)
                vectors.append(feature(face_crop(image, (x0+i*STEP, y, SIZE, SIZE))))
    index.matrix = np.stack(vectors)
    return image, index


def names(prefix):
    return [prefix+str(i) for i in range(5)]


class BoardTests(TestCase):
    def test_reads_two_tables_and_each_tables_own_set(self):
        image, index = board([(100, 130, names('甲')), (700, 130, names('乙'))])
        texts = [GuideText('OOXOO', 1, (480, 300, 80, 24)), GuideText('OXOOO更好', 1, (480, 340, 90, 24)),
                 GuideText('OOOOX', 1, (1050, 300, 80, 24))]
        rows = guide_board_rows(image, texts, index)
        self.assertEqual([r['names'] for r in rows], [names('甲'), names('乙')])
        self.assertEqual(rows[0]['instant'], [True, True, False, True, True])
        self.assertEqual(rows[1]['instant'], [True, True, True, True, False])

    def test_stacked_rows_keep_their_own_notes(self):
        image, index = board([(100, 100, names('甲')), (100, 300, names('乙'))])
        texts = [GuideText('XOOOO', 1, (480, 130, 80, 24)), GuideText('开局OOOOO 自动on', 1, (480, 330, 160, 24))]
        rows = guide_board_rows(image, texts, index)
        self.assertEqual(rows[0]['instant'], [False, True, True, True, True])
        self.assertIsNone(rows[1]['instant'])  # A timed axis is not a fixed SET.

    def test_incomplete_or_blank_rows_nominate_nothing(self):
        image, index = board([(100, 130, ['甲0', '甲1', None, '甲3', '甲4'])])
        self.assertEqual(guide_board_rows(image, [], index), [])
        image, index = board([(100, 130, names('甲')[:4])])
        self.assertEqual(guide_board_rows(image, [], index), [])

    def test_unknown_faces_are_not_guessed(self):
        image, index = board([(100, 130, names('甲'))])
        other = np.random.default_rng(99).integers(0, 255, (24, 24, 3), dtype=np.uint8)
        index.matrix = np.stack([feature(other)]*len(index.names))
        self.assertEqual(guide_board_rows(image, [], index), [])

    def test_only_board_looking_frames_pay_for_the_grid_search(self):
        self.assertTrue(board_hint([GuideText('OOXOO', 1, (0, 0, 80, 20))]))
        self.assertTrue(board_hint([GuideText('RANK', 1, (0, 0, 80, 20))]))
        self.assertFalse(board_hint([GuideText('OOXOO开自动', 1, (0, 0, 80, 20)), GuideText('挑战', 1, (0, 0, 80, 20))]))


class BoardPartyTests(TestCase):
    """A board page yields boss trials through the production parser, and only those."""

    def parse(self, roster_trials, instant=[True, True, False, True, True], extra=(), rows=None):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from pcrscript.tasks.strategy_video import parse_video_source
        with TemporaryDirectory() as folder:
            path = Path(folder)/'board.avi'
            writer = cv.VideoWriter(str(path), cv.VideoWriter_fourcc(*'MJPG'), 2, (960, 540))
            for i in range(20):
                writer.write(np.full((540, 960, 3), 30+i, np.uint8))
            writer.release()
            team = names('合成')
            row = dict(names=team, instant=instant, members=[dict(name=n, score=.9, rectangle=[1, 2, 3, 4]) for n in team])
            source = dict(bvid='BV0000000000', url='https://example.com/synthetic', title='公主连结 国服光属性深渊讨伐战',
                          pages=[dict(cid=1, part='二王AUTO两刀', duration=9)], comment_complete=True, author_comments=[])
            options = dict(task_type='subjugation', region='cn', area='合成深渊', aliases=['深渊讨伐战'], category_terms=[],
                           stage='', element='light', kind='boss', difficulty='极难', boss='合成首领', boss_number=2,
                           event_id=1, period_start=0, period_end=1, roster_trials=roster_trials, parsed_dir=folder,
                           max_frames_per_page=20)
            index = SimpleNamespace(names=team, matrix=np.ones((5, 1728), np.float32))
            with patch('pcrscript.tasks.strategy_video.read_text', return_value=[GuideText('OOXOO', 1, (0, 0, 80, 20)),
                                                                                  GuideText('R38-5', 1, (0, 40, 80, 20)), *extra]), \
                 patch('pcrscript.tasks.strategy_video.combat_team', return_value=[]), \
                 patch('pcrscript.tasks.strategy_video.battle_rectangles', return_value=[]), \
                 patch('pcrscript.tasks.strategy_tables.guide_board_rows',
                       **(dict(side_effect=rows(row)) if rows else dict(return_value=[row]))):
                return parse_video_source(source, options, index, api=Mock(), ocr=Mock(),
                                          media_fetcher=lambda *a, **k: (path, dict(duration=9))), team

    def test_board_page_keeps_roster_and_fixed_set_without_requiring_the_authors_build(self):
        report, team = self.parse(True)
        party = report['parties'][0]
        self.assertEqual([m['name'] for m in party['members']], team)
        self.assertEqual([m['instant']['value'] for m in party['members']], [True, True, False, True, True])
        self.assertEqual(party['global_requirements'], [])
        self.assertEqual(party['scope'], dict(kind='boss', boss='合成首领'))

    def test_board_cells_are_dropped_but_a_stated_requirement_on_the_page_survives(self):
        from pcrscript.tasks.strategy_tables import board_reference_cell
        for cell in ('R38-5', 'Rank38-5', '属性等级', '属性技能', 'MP101', '突破'):
            self.assertTrue(board_reference_cell(cell), cell)
        for sentence in ('必须点满属性技能', '公主骑士等级需要100', 'R38-5以上才能打'):
            self.assertFalse(board_reference_cell(sentence), sentence)
        report, _ = self.parse(True, extra=[GuideText('必须点满属性技能', 1, (0, 80, 160, 20))])
        self.assertEqual([r['text'] for r in report['parties'][0]['global_requirements']], ['必须点满属性技能'])

    def test_boards_sharing_labels_and_set_text_are_each_read(self):
        def rows(first):
            other = first['names'][::-1]
            second = dict(first, names=other, members=[dict(m, name=n) for m, n in zip(first['members'], other)])
            calls = iter(range(100))
            # Same headers and SET text on every frame. The roster switches after three reads;
            # label-keyed throttling then skipped the second board's confirming read.
            return lambda *a, **k: [first if next(calls) < 3 else second]
        report, team = self.parse(True, rows=rows)
        rosters = {tuple(m['name'] for m in p['members']) for p in report['parties']}
        self.assertEqual(rosters, {tuple(team), tuple(team[::-1])})

    def test_timed_axis_leaves_set_unread(self):
        report, _ = self.parse(True, instant=None)
        self.assertEqual({m['instant']['value'] for m in report['parties'][0]['members']}, {None})

    def test_board_is_not_read_outside_roster_trials(self):
        report, _ = self.parse(False)
        self.assertEqual(report['parties'], [])
