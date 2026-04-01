# Copyright (C) 2024 Aviv Edery.

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import typing
import dataclasses
import time

from . import _ctx
from . import _filter
from . import _exc
from . import _reg
from . import _attr
from . import _ml
from . import _dbg

_start_import_time = time.time()

# -true : Always true.
@_reg._register_builtin
class TruePredicate(_filter.Predicate, name_without_type='true'):
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        return cls(), at

    def excrete(self, findable: _ml.Findable, ctx: _ctx.FlamContext) -> bool:
        return True

# -false : Always false.
@_reg._register_builtin
class FalsePredicate(_filter.Predicate, name_without_type='false'):
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        return cls(), at

    def excrete(self, findable: _ml.Findable, ctx: _ctx.FlamContext) -> bool:
        return False

# -all ATTRIBUTE CMPTO : for array attributes, compare every array element according to CMPTO.
@_reg._register_builtin
class All(_filter.Predicate, name_without_type='all'):
    def __init__(self, attribute: _attr.Attribute, cmpto: _attr.CmpTo) -> None:
        self._attribute = attribute
        self._cmpto = cmpto
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        attribute = cls.eat_attribute(params, at)
        cmpto = cls.eat_cmpto(params, at + 1, attribute)
        return cls(attribute, cmpto), at + 2

    def excrete(self, findable: _ml.Findable, ctx: _ctx.FlamContext) -> bool:
        actual = findable.extract(self._attribute)

        if isinstance(actual, list):
            return all(self._cmpto(elem) for elem in actual)

        return self._cmpto(actual)

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield self._attribute.qualified_name
        yield str(self._cmpto)

# -has ATTRIBUTE : true if ATTRIBUTE isn't None
@_reg._register_builtin
class Has(_filter.Predicate, name_without_type='has'):
    def __init__(self, attribute: _attr.Attribute) -> None:
        self._attribute = attribute
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        attribute = cls.eat_attribute(params, at)
        return cls(attribute), at + 1

    def excrete(self, findable: _ml.Findable, ctx: _ctx.FlamContext) -> bool:
        actual = findable.extract(self._attribute)
        return actual is not None and (not isinstance(actual, list) or len(actual) > 0)

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield self._attribute.qualified_name

# -in-list LISTDEF : true if the findable is also in the list defined by LISTDEF.
@_reg._register_builtin
class InList(_filter.Predicate, name_without_type='in-list'):
    def __init__(self, movie_list: _ml.MovieList, filter: _filter.Filter) -> None:
        self._movie_list = movie_list
        self._filter = filter

        self._found_uids: None | set[str]
        self._found_uids_ct_gm: None | tuple[_ml.CrewType, _ml.GroupMode]

        # For optimization we cache the set of found uids.
        # But because a role filter can be reused with different modal_crew_types, we can't precompute that here, have to do it when the filter is used.
        match filter.findable_type:
            case _ml.FindableType.MOVIES | _ml.FindableType.PEOPLE:
                self._found_uids = {f.uid for f in movie_list.find(filter.findable_type, filter=self._filter)}
                self._found_uids_ct_gm = None
            case _:
                self._found_uids = None
                self._found_uids_ct_gm = None
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        movie_list, filter_idx = cls.eat_movie_list(params, at)
        filter, until = _filter.Filter.eat_single(params, filter_idx)
        return cls(movie_list, filter), until

    def excrete(self, findable: _ml.Findable, ctx: _ctx.FlamContext) -> bool:
        # TODO: this could be more efficient and simple if the API provided a quick lookup by UID.
        if self._filter.findable_type == _ml.FindableType.ROLES:
            assert isinstance(findable, _ml.Role)

            ct_gm = (findable.crew_type, findable.group_mode)

            if self._found_uids_ct_gm != ct_gm:
                self._found_uids = {f.uid for f in self._movie_list.find_roles(*ct_gm, self._filter)}
                self._found_uids_ct_gm = ct_gm

        assert self._found_uids is not None
        return findable.uid in self._found_uids

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield min(_filter.Pipeline.LPAREN)

        # We handle multiple listdefs as best we can but it's not great.
        yield from self._movie_list.abstract_listdef.pretty(self._movie_list.ctx).split(' ')

        yield min(_filter.Pipeline.RPAREN)
        yield from self._filter.regurgitate()

# -crew-contains CT_GM... SINGLE : scan the movie's crew according to CT_GMs for a group which passes the filter SINGLE.
@_reg._register_builtin
class CrewContains(_filter.Predicate, name_without_type='crew-contains', findable_type=_ml.FindableType.MOVIES):
    def __init__(self, ct_gms: list[tuple[_ml.CrewType, _ml.GroupMode]], filter: _filter.Filter) -> None:
        self._ct_gms = ct_gms
        self._filter = filter
        self._muid_attr = _reg._builtins.attributes['movies-uid']
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        ct_gms, filter_idx = cls.eat_listof(cls.eat_ct_gm, params, at, True)
        sub_params = dataclasses.replace(params, find=_ml.FindableType.ROLES)
        filter, until = _filter.Filter.eat_single(sub_params, filter_idx)
        return cls(ct_gms, filter), until

    def excrete(self, findable: _ml.Findable, ctx: _ctx.FlamContext) -> bool:
        return any(
            role.extract(self._muid_attr) == findable.uid
            for ct_gm in self._ct_gms
                for role in findable.movie_list.find_roles(*ct_gm, filter=self._filter)
        )

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield min(_filter.Pipeline.LPAREN)
        yield from (f"{ct_gm[0]}:{ct_gm[1]}" for ct_gm in self._ct_gms)
        yield min(_filter.Pipeline.RPAREN)
        yield from self._filter.regurgitate()

def _test_compile(line: str, find: _ml.FindableType = _ml.FindableType.ROLES, ctx: None | _ctx.FlamContext = None) -> None:
    import shlex
    tokens = shlex.split(line)

    if ctx is None:
        ctx = _ctx.FlamContext(flam_dir=None)

    try:
        filter = ctx.compile_filter(tokens, find)
        regurg = ' '.join(_exc.FilterSyntaxError.format_token(t) for t in filter.regurgitate())
        print(line, '->', regurg)
    except _exc.FilterSyntaxError as e:
        print(e)

# _test_compile('')
# _test_compile('-true')
# _test_compile('-true -true -false')
# _test_compile('-true -o ( -false ) )')
# _test_compile('-ftrual | -tue\\" -o ( -false )')
# _test_compile('( ( -true | -true ) ) ! -false')
# _test_compile('( -true " "')
# _test_compile('true')

_dbg.logger.info(f'Module import time: {time.time() - _start_import_time}s')
