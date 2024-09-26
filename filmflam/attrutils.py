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

from __future__ import annotations

import typing
import datetime
import dateutil.parser

from . import _attr
from . import _mlf
from . import _ml

# TODO: Pull this same shtick for attributes?
class EasyTypeHandler(_attr.TypeHandler):
    def __init__(self, type_: type, default_cmp: _attr.ComparisonOp, parse: typing.Callable[[str], typing.Any]) -> None:
        super().__init__()
        self._type = type_
        self._default_cmp = default_cmp
        self._parse = parse

    @property
    def type_(self) -> type:
        return self._type

    @property
    def default_cmp(self) -> _attr.ComparisonOp:
        return self._default_cmp

    def parse(self, value_str: str) -> typing.Any:
        return self._parse(value_str)

INT_HANDLER = EasyTypeHandler(
    type_ = int,
    default_cmp = _attr.ComparisonOp.EQ,
    parse = lambda s: int(s, base=0), # 0 means deduce the base from the str.
)

STR_HANDLER = EasyTypeHandler(
    type_ = str,
    default_cmp = _attr.ComparisonOp.RX,
    parse = lambda s: s,
)

# TODO: If an attribute is like "release year+month (without day)", you wouldn't want to compare by the whole date, would you?
DATE_HANDLER = EasyTypeHandler(
    type_ = datetime.date,
    default_cmp = _attr.ComparisonOp.EQ,
    parse = lambda s: dateutil.parser.parse(s, default=datetime.datetime.min).date(),
)

class EasyAttribute(_attr.Attribute):
    # TODO: many more fields. Fields related to sorting, distribution, etc..
    def __init__(
                self,
                name: str,
                findable_type: _ml.FindableType,
                type_handler: _attr.TypeHandler,
                is_array: bool,
                extract_from_role: None | typing.Callable[[_ml.Role, list[_mlf.MLFRole]], typing.Any] = None,
                extract_from_movie: None | typing.Callable[[_ml.Movie, _mlf.MLFMovie], typing.Any] = None,
                extract_from_person: None | typing.Callable[[_ml.Person, _mlf.MLFPerson], typing.Any] = None,
            ) -> None: 
        self._name = name
        self._findable_type = findable_type
        self._type_handler = type_handler
        self._is_array = is_array

        assert findable_type != _ml.FindableType.ROLES or extract_from_role is not None
        assert findable_type != _ml.FindableType.MOVIES or extract_from_movie is not None
        assert findable_type != _ml.FindableType.PEOPLE or extract_from_person is not None

        self._extract_from_role_lambda = extract_from_role
        self._extract_from_movie_lambda = extract_from_movie
        self._extract_from_person_lambda = extract_from_person

    @property
    def name(self) -> str:
        return self._name
    
    @property
    def findable_type(self) -> _ml.FindableType:
        return self._findable_type

    @property
    def type_handler(self) -> _attr.TypeHandler:
        return self._type_handler

    @property
    def is_array(self) -> bool:
        return self._is_array

    # TODO: Don't like the assert on every extract, don't like the inability to define these optionally so we can hasattr them...
    def _extract_from_movie(self, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> typing.Any:
        assert self._extract_from_movie_lambda is not None
        return self._extract_from_movie_lambda(movie, mlf_movie)

    def _extract_from_role(self, role: _ml.Role, mlf_roles: list[_mlf.MLFRole]) -> typing.Any:
        assert self._extract_from_role_lambda is not None
        return self._extract_from_role_lambda(role, mlf_roles)

    def _extract_from_person(self, person: _ml.Person, mlf_person: _mlf.MLFPerson) -> typing.Any:
        assert self._extract_from_person_lambda is not None
        return self._extract_from_person_lambda(person, mlf_person)

# TODO: attribute ideas:
# Generic:
# * for every array type predicate have a length attribute
# * every field in list files should have a corresponding attribute
# 
# Person:
# * nmovies appeared in
# * n<crew-type>, like ndirector for num of movies directed
# * average rating (per crew type?)
# 
# Movie:
# * days until it leaves, this should be a personal extension of mine
# * release/watch date in many formats? day of week, month of year, etc.
# 
# Crew:
# * which crew type
# * npeople in the group
# * ncrewed (or some different name), adaptive version of n<crew-type>
