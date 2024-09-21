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
import enum
import abc
import re

from . import _mlf
from . import _ml
from . import _exc
from . import _dbg

class ComparisonOp(enum.Enum):
    # Important to use prefix-free signs.
    LE = ('-', lambda v1, v2: v1 <= v2)
    GE = ('+', lambda v1, v2: v1 >= v2)
    EQ = ('=', lambda v1, v2: v1 == v2)
    LT = ('@-', lambda v1, v2: v1 < v2)
    GT = ('@+', lambda v1, v2: v1 > v2)
    RX = ('@=', lambda v, regex: bool(regex.search(v)))

    def __init__(self, sign: str, compare: typing.Callable[[typing.Any, typing.Any], bool]) -> None:
        self.sign = sign
        self.compare = compare

# TODO: Everything about this class is ugly, but I don't know how to do it better at this time.
class CmpValue:
    def __init__(self, compare_func: typing.Callable[[typing.Any], bool], str_func: typing.Callable[[], str]) -> None:
        self._compare_func = compare_func
        self._str_func = str_func

    def compare(self, value: typing.Any) -> bool:
        return self._compare_func(value)

    def __str__(self) -> str:
        return self._str_func()

# There are some facilities that we need out of every possible value attributes may extract.
# I don't want to wrap every such value in a "Value" class to provide those facitilites because that would mean making lots of small objects.
# Solution: Flyweight pattern. Subclasses of TypeHandler provide all the facilities we need, with the underlying value externalized.
# Downside: Casting/type assertion everywhere.
class TypeHandler(abc.ABC):
    @property
    @abc.abstractmethod
    def type_(self) -> type:
        pass

    @property
    @abc.abstractmethod
    def default_cmp(self) -> ComparisonOp:
        pass

    @abc.abstractmethod
    def parse(self, value_str: str) -> typing.Any:
        pass

    def assert_type(self, value: typing.Any) -> typing.Any:
        assert isinstance(value, self.type_)
        return value

    def stringify(self, value: typing.Any) -> str:
        return str(self.assert_type(value))

    def make_cmp_value(self, cmp: ComparisonOp, value_str: str) -> CmpValue:
        match cmp:
            case ComparisonOp.RX:
                try:
                    # TODO: Support case sensitivity on the cmpvalue level, or globally with an env var, or not at all?
                    compiled = re.compile(value_str, flags=re.IGNORECASE)
                except re.error as e:
                    raise _exc.InputError(f"Failed to parse value '{value_str}' as a regular expression: {e}") from e

                return CmpValue(
                    compare_func=lambda value: cmp.compare(self.stringify(value), compiled),
                    str_func=lambda: compiled.pattern)
            case _:
                parsed = self.parse(value_str)
                return CmpValue(
                    compare_func=lambda value: cmp.compare(self.assert_type(value), parsed),
                    str_func=lambda: f"{cmp.sign}{self.stringify(parsed)}")

# TODO: Thoughts on supporting aliases: will need to register the attribute with each alias name, separate the registry by findable type,
# prevent collisions (but allow them across types), and support '<findable-type>-<attr name>' (e.g. movies-name, person-age) to prevent ambiguity when there is any
class Attribute(abc.ABC):
    @property
    @abc.abstractmethod
    def name(self) -> str:
        pass
    
    @property
    @abc.abstractmethod
    def findable_type(self) -> _ml.FindableType:
        pass

    @property
    @abc.abstractmethod
    def is_array(self) -> bool:
        pass

    # TODO: Not sure if all type_handler functions should actually be in attribute, and type_handler should only be an implementation detail used by EasyAttribute.
    @property
    @abc.abstractmethod
    def type_handler(self) -> TypeHandler:
        pass

    def _extract_from_movie(self, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> typing.Any:
        raise NotImplementedError()

    def _extract_from_role(self, role: _ml.Role, mlf_roles: list[_mlf.MLFRole]) -> typing.Any:
        raise NotImplementedError()

    def _extract_from_person(self, person: _ml.Person, mlf_person: _mlf.MLFPerson) -> typing.Any:
        raise NotImplementedError()

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
