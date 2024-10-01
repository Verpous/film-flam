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
import functools

from . import _mlf
from . import _ml
from . import _exc
from . import _dbg

# For now typing.Any, but what we really want is an "intersection" of protocols value must support, which for now is sorting and stringification?
# Unfortunately python has neither an intersection type, nor a "sortable" type.
type AttributeValue = None | typing.Any

class ComparisonOp(enum.Enum):
    # Important to use prefix-free signs.
    LE = ('-', lambda v1, v2: v1 <= v2)
    GE = ('+', lambda v1, v2: v1 >= v2)
    EQ = ('=', lambda v1, v2: v1 == v2)
    LT = ('@-', lambda v1, v2: v1 < v2)
    GT = ('@+', lambda v1, v2: v1 > v2)
    RX = ('@=', lambda v, regex: bool(regex.search(v)))

    def __init__(self, sign: str, compare: typing.Callable[[AttributeValue, AttributeValue], bool]) -> None:
        self.sign = sign
        self.compare = compare

    def __call__(self, value1: AttributeValue, value2: AttributeValue) -> bool:
        return self.compare(value1, value2)

class CmpTo:
    def __init__(self, op: ComparisonOp, value: AttributeValue, attribute: Attribute) -> None:
        self._attribute = attribute
        self._op = op
        self._value = value

    def __call__(self, value: AttributeValue) -> bool:
        # Order is important.
        return self._op(value, self._value)

    def __str__(self) -> str:
        match self._op:
            case ComparisonOp.RX:
                return f"{self._op.sign}{self._value.pattern}"
            case _:
                return f"{self._op.sign}{self._attribute.str_of(self._value)}"

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

    # Of course we aren't talking about actual byte order here.
    # We're talking about generally, when stringified, does the string go from most to least significant or vice versa?
    @property
    @abc.abstractmethod
    def is_big_endian(self) -> bool:
        pass

    @property
    @abc.abstractmethod
    def is_ascending(self) -> bool:
        pass

    @property
    @abc.abstractmethod
    def type_(self) -> type:
        pass

    @property
    @abc.abstractmethod
    def default_op(self) -> ComparisonOp:
        pass

    @abc.abstractmethod
    def parse(self, value_str: str) -> AttributeValue:
        pass

    def compare(self, op: ComparisonOp, value1: AttributeValue, value2: AttributeValue) -> bool:
        if value1 is not None and value2 is not None:
            return op(value1, value2)

        assert self.is_noneable
        return value1 is None and value2 is None

    def compare_all(self, op: ComparisonOp, value1: AttributeValue, value2: AttributeValue) -> bool:
        if not self.is_array:
            return self.compare(op, value1, value2)

        assert isinstance(value1, list) and isinstance(value2, list)
        len1, len2 = len(value1), len(value2)
        
        match op:
            case ComparisonOp.LE:
                return self.compare_all(ComparisonOp.EQ, value1, value2) or self.compare_all(ComparisonOp.LT, value1, value2)
            case ComparisonOp.GE:
                return self.compare_all(ComparisonOp.EQ, value1, value2) or self.compare_all(ComparisonOp.GT, value1, value2)
            case ComparisonOp.EQ:
                return len1 == len2 and all(self.compare(op, elem1, elem2) for elem1, elem2 in zip(value1, value2))
            case ComparisonOp.LT | ComparisonOp.GT:
                # Lexicographic compare.
                for elem1, elem2 in zip(value1, value2):
                    if self.compare(op, elem1, elem2):
                        return True
                    
                    if not self.compare(ComparisonOp.EQ, value1, value2):
                        return False

                return op(len1, len2)
            case ComparisonOp.RX:
                raise _exc.InputError("Regex comparison is not supported for compare_all.")
            case _:
                raise RuntimeError(f"Unexpected {op=}")

    # The need for this function is to handle the fact that values may be None.
    # Use typing.Any because there's no typehint for sortable.
    def sort_key(self, value: AttributeValue) -> typing.Callable[[AttributeValue], typing.Any]:
        return ((value is None) ^ self.is_ascending, value)

    def verify_type(self, value: AttributeValue, allow_none: bool = True) -> AttributeValue:
        assert isinstance(value, self.type_) or (allow_none and value is None)
        return value

    def str_of(self, value: AttributeValue) -> str:
        if value is None or (isinstance(value, list) and len(value) == 0):
            return '-'

        return str(value)

    def make_cmpto(self, op: ComparisonOp, value_str: str) -> CmpTo:
        match op:
            case ComparisonOp.RX:
                try:
                    parsed = re.compile(value_str, flags=re.IGNORECASE)
                except re.error as e:
                    raise _exc.InputError(f"Failed to parse value '{value_str}' as a regular expression: {e}") from e
            case _:
                parsed = self.parse(value_str)

        return CmpTo(op, parsed, self)

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
