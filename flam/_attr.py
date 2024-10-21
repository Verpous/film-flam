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

# For now typing.Any, but what we really want is an "intersection" of protocols value must support, which for now is sorting and stringification?
# Unfortunately python has neither an intersection type, nor a "sortable" type.
type AttributeValue = None | typing.Any

class ComparisonOp(enum.Enum):
    # IMPORTANT: use prefix-free signs.
    LE = ('-', lambda v1, v2: v1 <= v2)
    GE = ('+', lambda v1, v2: v1 >= v2)
    EQ = ('==', lambda v1, v2: v1 == v2)
    LT = ('.-', lambda v1, v2: v1 < v2)
    GT = ('.+', lambda v1, v2: v1 > v2)
    RX = ('=~', lambda v, pattern: bool(pattern.search(v)))

    def __init__(self, sign: str, compare: typing.Callable[[AttributeValue, AttributeValue | re.Pattern], bool]) -> None:
        self.sign = sign
        self.compare = compare

    def __call__(self, value1: AttributeValue, value2: AttributeValue | re.Pattern) -> bool:
        return self.compare(value1, value2)

class CmpTo:
    def __init__(self, op: ComparisonOp, value: AttributeValue | re.Pattern, attribute: Attribute) -> None:
        self._attribute = attribute
        self._op = op
        self._value = value

    def __call__(self, value: AttributeValue) -> bool:
        # This is really bizarre but if you just use self._op directly mypy complains it isn't callable.
        op = self._op

        match self._op:
            case ComparisonOp.RX:
                # Order is important.
                return op(self._attribute.str_of(value), self._value)
            case _:
                return value is not None and op(value, self._value)

    def __str__(self) -> str:
        match self._op:
            case ComparisonOp.RX:
                assert isinstance(self._value, re.Pattern)
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

    @abc.abstractmethod
    def _str_of_single(self, value: AttributeValue) -> str:
        pass

    # The need for this function is to handle the fact that values may be None.
    # Use typing.Any because there's no typehint for sortable.
    def sort_key(self, value: AttributeValue) -> tuple[bool, AttributeValue]:
        return ((value is None) ^ self.is_ascending, value)

    def verify_type(self, value: AttributeValue, allow_none: bool = True) -> AttributeValue:
        assert isinstance(value, self.type_) or (allow_none and value is None)
        return value

    def str_of(self, value: AttributeValue) -> str:
        if value is None or (isinstance(value, list) and len(value) == 0):
            return '-'

        if isinstance(value, list):
            if len(value) == 0:
                return '-'
            
            return ', '.join(self._str_of_single(elem) for elem in value)

        return self._str_of_single(value)

    def make_cmpto(self, op: ComparisonOp, value_str: str) -> CmpTo:
        parsed: AttributeValue | re.Pattern

        match op:
            case ComparisonOp.RX:
                try:
                    parsed = re.compile(value_str, flags=re.IGNORECASE)
                except re.error as e:
                    raise _exc.InputError(f"Failed to parse value '{value_str}' as a regular expression: {e}") from e
            case _:
                parsed = self.parse(value_str)

        return CmpTo(op, parsed, self)

def iter_value(value: AttributeValue) -> typing.Iterable[AttributeValue]:
    if isinstance(value, list):
        yield from value
    else:
        yield value

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
