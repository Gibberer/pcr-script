"""Select a source roster by exact search portraits, without detail pages.

Shared by tasks whose failed battle costs nothing, so the live result rather
than per-member detail reads judges an undeclared build. Any unclear step
returns None and leaves the caller's full audit in charge.
"""
from ..game_ui.avatars import face_crop
from ..game_ui.character_search import search_character_candidates as search_character
from ..game_ui.screen import EventUIError, normalized


PORTRAIT_ASSUMPTION = '攻略未声明培养要求；头像确认成员后以实战结果判断，未读账号培养'


def declares_build(party):
    """Any source build field (default empty equipment aside) needs the full audit."""
    from .party_preparation import BUILD_FIELDS
    declared = getattr(party, 'declared_build', None)
    if isinstance(declared, dict) and declared:
        # Account-trial seeds fill member fields with placeholder 1s and keep
        # only evidenced source values here, keyed per member.
        return any(bool(values) for values in declared.values())
    return any(getattr(member, key, None) is not None and (key != 'equipment' or getattr(member, key))
               for member in party.members for key in BUILD_FIELDS)


def portrait_trial(formation, party, *, failed=()):
    """Select an undeclared roster by portraits; None leaves the full audit in charge.

    `failed` lists member-name collections that already lost at this target.
    Those take the full audit, which records the build a retry is judged by."""
    names = [normalized(m.name) for m in party.members]
    lost = {frozenset(map(normalized, roster)) for roster in failed}
    if (declares_build(party) or set(names) & set(getattr(formation, 'unowned', ()))
            or frozenset(names) in lost):
        return None
    order = formation.select_by_portrait(names)
    if order is None:
        return None
    return dict(order=order, build_basis='portrait_trial',
                assumptions=list(getattr(party, 'assumptions', []) or [])+[PORTRAIT_ASSUMPTION])


class PortraitSelection:
    def portrait_order(self, expected=(), *, use_picks=True):
        """Read the occupied slots by portrait; None when any slot stays unclear.

        use_picks lets members this selection just picked settle a near tie or
        a single gap. A roster restored after leaving the page must not."""
        wanted = set(map(normalized, expected))
        size = len(wanted) if wanted else 5
        s = self.ui.capture(ocr=False)
        occupied = self.occupied_slots(s)
        if len(occupied) != size:
            return None
        crops = [face_crop(s.image, (x-48, self.slot_top, 96, 96)) for x, _ in occupied]
        names = [normalized(n) if n is not None else None for n in self.avatars.query(crops)]
        # A near-tie may only settle a member this selection picked from its
        # search card; a pre-existing slot could hold a look-alike.
        picked = wanted & set(getattr(self, 'portrait_selected', ())) if use_picks else set()
        for i, name in enumerate(names):
            if name is None and picked:
                found = self.avatars.expected_identity(crops[i], picked)
                names[i] = normalized(found) if found is not None else None
        # Slot crops can miss a portrait the search card matched exactly. One
        # gap is settled by elimination, only for a member picked that way.
        missing = wanted-set(names) if use_picks else set()
        if (names.count(None) == 1 and len(missing) == 1
                and missing <= getattr(self, 'portrait_selected', set())
                and set(names)-{None} <= wanted):
            names[names.index(None)] = missing.pop()
        elif (use_picks and names.count(None) == len(missing) > 1
                and missing <= getattr(self, 'portrait_selected', set())
                and set(names)-{None} <= wanted):
            # Several gaps are all picked members, so only their order is open.
            gaps = [i for i, name in enumerate(names) if name is None]
            found = self.avatars.assign_expected([crops[i] for i in gaps], sorted(missing))
            if found:
                for i, name in zip(gaps, found):
                    names[i] = name
        if None in names or len(set(names)) != size:
            self.ui.save('portrait_order_unconfirmed', s)
            return None
        return names

    def note_unowned(self, names):
        """These tasks never acquire characters, so one failed search holds for the whole run."""
        self.unowned = set(getattr(self, 'unowned', ())) | set(map(normalized, names))

    def select_by_portrait(self, names):
        """Pick exact portrait matches without detail pages; None leaves the full audit in charge."""
        wanted = [normalized(n) for n in names]
        if (not getattr(self.ui.driver, 'supports_unicode_input', True)
                or not 1 <= len(wanted) <= 5 or len(set(wanted)) != len(wanted)):
            return None
        # Picks from an earlier selection do not vouch for the formation found now.
        self.portrait_selected = set()
        current = self.portrait_order(wanted)
        if current is None or set(current) != set(wanted):
            if not self.prepare_search():
                return None
            self.portrait_selected = set()
            for name in wanted:
                print(f'[编队] 搜索并按头像选入 {name}', flush=True)
                try:
                    s = search_character(self.ui, name, defocus=self.defocus, field_area=self.search_field_area,
                                         reset=self.search_reset, field=self.search_field)
                except EventUIError as error:
                    if not str(error).startswith(('后台角色搜索输入失败', '搜索词未确认写入')):
                        raise
                    self._reset_search_for_scan()
                    return None
                rects = self.search_rectangles(s.image)
                crops = [face_crop(s.image, r) for r in rects]
                # The typed name already excludes unrelated faces; only costumes compete here.
                hits = [r for r, c in zip(rects, crops) if self.avatars.expected_identity(c, [name])]
                rect = hits[0] if len(hits) == 1 else None
                if rect is None:
                    identities = self.avatars.query(crops)
                    # One unclear portrait only costs that member's detail page.
                    for r, i, c in zip(rects, identities, crops):
                        # Only a separated read of another costume (query() keeps a
                        # margin over every other name) may skip the detail page;
                        # a near tie between costumes still needs it.
                        closest = normalized(i) if i is not None else None
                        if (not hits and closest is not None and closest != name
                                and closest.split('(')[0] == name.split('(')[0]):
                            continue
                        if self.search_identity_candidate(s, r, i, name):
                            actual = self.inspect((r[0]+r[2]//2, r[1]+r[3]//2), rectangle=r,
                                                  expected_name=name, verify_skills=False)
                            if actual.identity_verified and normalized(actual.name) == name:
                                rect = r
                                break
                if rect is None:
                    self.ui.click(self.search_reset)
                    self.note_unowned([name])
                    return None
                x, y, w, h = rect
                self.select_card((x+w//2, y+h//2))
                self.portrait_selected.add(name)
            self.ui.click(self.search_reset)
            current = self.portrait_order(wanted)
        if current is None or set(current) != set(wanted):
            return None
        self.portrait_roster = set(current)
        return current
