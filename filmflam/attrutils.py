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
import abc

from . import _attr
from . import _mlf
from . import _ml

# There are some facilities that we need out of every possible value attributes may extract (e.g.: ability stringify, etc.).
# I don't want to wrap every such value in a "Value" class to provide those facitilites because that would mean making lots of small objects.
# Solution: Flyweight pattern. Subclasses of TypeHandler provide all the facilities we need, with the underlying value externalized.
# Downside: Casting/type assertion everywhere, or in many places just assuming the types are fine and not checking.
class TypeHandler(abc.ABC):
    @property
    @abc.abstractmethod
    def type_(self) -> type:
        pass

    @property
    @abc.abstractmethod
    def default_op(self) -> _attr.ComparisonOp:
        pass

    @abc.abstractmethod
    def parse(self, value_str: str) -> _attr.AttributeValue:
        pass

    # Assumes value is not None.
    def str_of(self, value: _attr.AttributeValue) -> str:
        return str(value)

class EasyTypeHandler(TypeHandler):
    def __init__(
            self,
            type_: type,
            default_op: _attr.ComparisonOp,
            parse: typing.Callable[[str], _attr.AttributeValue],
            str_of: typing.Callable[[_attr.AttributeValue], str]) -> None:
        super().__init__()
        self._type = type_
        self._default_op = default_op
        self._parse = parse
        self._str_of = str_of

    @property
    def type_(self) -> type:
        return self._type

    @property
    def default_op(self) -> _attr.ComparisonOp:
        return self._default_op

    def parse(self, value_str: str) -> _attr.AttributeValue:
        return self._parse(value_str)

    def str_of(self, value: _attr.AttributeValue) -> str:
        return self._str_of(value)

INT_HANDLER = EasyTypeHandler(
    type_ = int,
    default_op = _attr.ComparisonOp.EQ,
    parse = lambda s: int(s, base=0), # 0 means deduce the base from the str.
    str_of = str,
)

FLOAT_HANDLER = EasyTypeHandler(
    type_ = float,
    default_op = _attr.ComparisonOp.EQ,
    parse = float,
    str_of = str,
)

# TODO: I think we want this to compare EQ case-insensitively.
STR_HANDLER = EasyTypeHandler(
    type_ = str,
    default_op = _attr.ComparisonOp.RX,
    parse = lambda s: s,
    str_of = lambda s: s,
)

# TODO: If an attribute is like "release year+month (without day)", you wouldn't want to compare by the whole date, would you?
DATE_HANDLER = EasyTypeHandler(
    type_ = datetime.date,
    default_op = _attr.ComparisonOp.EQ,
    parse = lambda s: dateutil.parser.parse(s, default=datetime.datetime.min).date(),
    str_of = lambda d: d.strftime("%Y-%m-%d"),
)

# If the way this EasyAttribute business is coded looks funny to you, here is why:
# 1. I want the "_extract_from_x" functions to only be defined in the concrete classes that need them, as opposed to being inherited abstract methods.
#    That way roles can optionally define "from_person/movie" extractors that we invoke if they "hasattr" it.
# 2. Despite all these extractor methods basically returning "Any", I want mypy to still check each one for type correctness.
# 3. We're gonna be implementing a 100 attributes so boilerplate must be kept to a minimum.
# 4. Lots of little constraints to please mypy and pylint about what we're doing.
@dataclasses.dataclass
class EasyAttributeParams:
    # TODO: many more fields. Fields related to sorting, distribution, etc..
    name: str
    findable_type: _ml.FindableType
    type_handler: TypeHandler
    is_array: bool
    is_big_endian: bool
    is_ascending: bool

class EasyAttribute(_attr.Attribute):
    def __init__(self, params: EasyAttributeParams) -> None: 
        self._params = params

    @property
    def name(self) -> str:
        return self._params.name
    
    @property
    def findable_type(self) -> _ml.FindableType:
        return self._params.findable_type

    @property
    def is_big_endian(self) -> bool:
        return self._params.is_big_endian

    @property
    def is_ascending(self) -> bool:
        return self._params.is_big_endian

    @property
    def is_array(self) -> bool:
        return self._params.is_array

    @property
    def type_(self) -> type:
        return self._params.type_handler.type_

    @property
    def default_op(self) -> _attr.ComparisonOp:
        return self._params.type_handler.default_op

    def parse(self, value_str: str) -> _attr.AttributeValue:
        return self._params.type_handler.parse(value_str)

    def _str_of_single(self, value: AttributeValue) -> str:
        return self._params.type_handler.str_of(value)

type MovieExtractor[T] = typing.Callable[[EasyAttribute, _ml.Movie, _mlf.MLFMovie], T]
type PersonExtractor[T] = typing.Callable[[EasyAttribute, _ml.Person, _mlf.MLFPerson], T]
type RoleExtractor[T] = typing.Callable[[EasyAttribute, _ml.Role, list[_mlf.MLFRole]], T]
type Extractor[T] = MovieExtractor | PersonExtractor[T] | RoleExtractor[T]

_extractor_names = {
    _ml.FindableType.MOVIES: '_extract_from_movie',
    _ml.FindableType.PEOPLE: '_extract_from_person',
    _ml.FindableType.ROLES: '_extract_from_role',
}

def easy_attribute[T](params: EasyAttributeParams) -> typing.Callable[[Extractor[T]], EasyAttribute]:
    def inner(extractor: Extractor[T]) -> EasyAttribute:
        class SpecificAttribute(EasyAttribute):
            pass

        setattr(SpecificAttribute, _extractor_names[params.findable_type], extractor)
        return SpecificAttribute(params)
    return inner

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
