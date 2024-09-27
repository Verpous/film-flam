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
import dataclasses

from . import _attr
from . import _mlf
from . import _ml

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

# TODO: I think we want this to compare EQ case-insensitively.
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

# If the way this EasyAttribute business is coded looks funny to you, here is why:
# 1. I want the "_extract_from_x" functions to only be defined in the concrete classes that need them, as opposed to being inherited abstract methods.
#    That way roles can optionally define "from_person/movie" extractors that we invoke if they "hasattr" it.
# 2. Despite all these extractor methods basically returning "Any", I want mypy to still check each one for type correctness.
# 3. We're gonna be implementing a 100 attributes so boilerplate must be kept to a minimum.
@dataclasses.dataclass
class EasyAttributeParams:
    name: str
    findable_type: _ml.FindableType
    type_handler: _attr.TypeHandler
    is_array: bool

class EasyAttribute(_attr.Attribute):
    # TODO: many more fields. Fields related to sorting, distribution, etc..
    def __init__(self, params: EasyAttributeParams) -> None: 
        self._params = params

    @property
    def name(self) -> str:
        return self._params.name
    
    @property
    def findable_type(self) -> _ml.FindableType:
        return self._params.findable_type

    @property
    def type_handler(self) -> _attr.TypeHandler:
        return self._params.type_handler

    @property
    def is_array(self) -> bool:
        return self._params.is_array

def easy_attribute[T](extractor:
        typing.Callable[[EasyAttribute, _ml.Movie, _mlf.MLFMovie], T] |
        typing.Callable[[EasyAttribute, _ml.Person, _mlf.MLFPerson], T] |
        typing.Callable[[EasyAttribute, _ml.Role, list[_mlf.MLFRole]], T]) -> type[EasyAttribute]:
    class SpecificAttribute(EasyAttribute):
        pass

    setattr(SpecificAttribute, extractor.__name__, extractor)
    return SpecificAttribute

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
