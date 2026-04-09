# Copyright (C) 2026 Aviv Edery.

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
import operator

from . import _ml
from . import _reg

if typing.TYPE_CHECKING:
    import _typeshed

# Attributes may return any "primitive" type, or a list of primitive types.
# Primitives must be sortable. Other than that they are rather unconstrained, but conceptually we regard them as NOT collections.
# * str, int, datetime - good primitives
# * dict, set, list - bad primitives
# * Pedicates with a CMPTO argument like AttributePredicate expect the comparison to be to a primitive
# * If the attribute actually returns a list, they'll check if the list contains the argument
# * Otherwise they'll check if the argument is equal to the attribute value
# None has a special meaning in that we regard it as "value N/A", and consider '-' as the str representation of None.
type AttributePrimitive = None | _typeshed.SupportsRichComparison # pylint: disable=used-before-assignment
type AttributeValue = AttributePrimitive | list[AttributePrimitive]

class ComparisonOp(enum.Enum):
    # IMPORTANT:
    # * Signs must be prefix-free! Hence the weird signs like '.+'
    # * Signs should avoid using characters that have special meaning in bash. Hence '+' instead of '>'
    # * Yes '~' is a special character but the alternative was '==', '=~' and that's too horrible.
    LE = ('-', operator.le)
    GE = ('+', operator.ge)
    EQ = ('=', operator.eq)
    LT = ('.-', operator.lt)
    GT = ('.+', operator.gt)
    RX = ('~', lambda v, pattern: bool(pattern.search(v)))

    def __init__(self, sign: str, compare: typing.Callable[[AttributePrimitive, AttributePrimitive | re.Pattern], bool]) -> None:
        self.sign = sign
        self.compare = compare

    def __call__(self, primitive_lhs: AttributePrimitive, primitive_rhs: AttributePrimitive | re.Pattern) -> bool:
        return self.compare(primitive_lhs, primitive_rhs)

# CmpTo's are objects which encapsulate comparison by some operator of attribute primitives X to some constant value V.
# Think of it like: =V(X) - is X equal to V, +V(X) - is X greater than V.
# Concrete example: "=~coen" parses to a CmpTo which checks if strings match the regex /coen/.
class CmpTo:
    def __init__(self, op: ComparisonOp, const_primitive: AttributePrimitive | re.Pattern, attribute: Attribute) -> None:
        self._attribute = attribute
        self._op = op
        self._const_primitive = const_primitive

    def __call__(self, primitive: AttributePrimitive) -> bool:
        # This is really bizarre but if you just use self._op directly mypy complains it isn't callable.
        op = self._op

        match self._op:
            case ComparisonOp.RX:
                # No threat of Nones for regexes. And order is important.
                return op(self._attribute.str_of_value(primitive), self._const_primitive)
            case _:
                # If one but not both are None then they are incomparable - return false.
                if (primitive is None) ^ (self._const_primitive is None):
                    return False

                return op(primitive, self._const_primitive)

    def __str__(self) -> str:
        match self._op:
            case ComparisonOp.RX:
                assert isinstance(self._const_primitive, re.Pattern)
                return f"{self._op.sign}{self._const_primitive.pattern}"
            case _:
                assert not isinstance(self._const_primitive, re.Pattern)
                return f"{self._op.sign}{self._attribute.str_of_value(self._const_primitive)}"

class Attribute(abc.ABC):
    NONE_STR = '-'

    def __init__(self, findable_type: _ml.FindableType, name_without_type: str, aliases_without_type: None | list[str] = None):
        self._findable_type = findable_type
        self._name_without_type = name_without_type
        self._qualified_name = _reg.compose_qualified_attr_or_pred_name(findable_type, name_without_type)
        self._aliases_without_type = [] if aliases_without_type is None else aliases_without_type

    @property
    def name_without_type(self) -> str:
        return self._name_without_type

    @property
    def aliases_without_type(self) -> typing.Iterable[str]:
        yield from self._aliases_without_type
    
    @property
    def findable_type(self) -> _ml.FindableType:
        return self._findable_type

    @property
    def qualified_name(self) -> str:
        return self._qualified_name

    @property
    def qualified_aliases(self) -> typing.Iterable[str]:
        # No need to cache this.
        for alias_without_type in self.aliases_without_type:
            yield _reg.compose_qualified_attr_or_pred_name(self._findable_type, alias_without_type)

    @property
    @abc.abstractmethod
    def is_ascending(self) -> bool:
        pass

    @property
    @abc.abstractmethod
    def default_op(self) -> ComparisonOp:
        pass

    @abc.abstractmethod
    def _parse_primitive_not_none(self, primitive_str: str) -> AttributePrimitive:
        pass

    @abc.abstractmethod
    def _str_of_primitive_not_none(self, primitive: AttributePrimitive, abbreviate: bool, extras: dict[str, typing.Any]) -> str:
        pass

    # The need for this function is to handle the fact that values may be None, and Nones can't compare with the not-Nones.
    def sort_key(self, value: AttributeValue) -> typing.Any:
        if isinstance(value, list):
            return ([self._sort_key_primitive(elem) for elem in value])
        
        return self._sort_key_primitive(value)

    def _sort_key_primitive(self, primitive: AttributePrimitive) -> _typeshed.SupportsRichComparison:
        # We xor with the ascending preference so that Nones always end up at the bottom of the sort whether ascending or descending.
        return ((primitive is not None) ^ self.is_ascending, primitive)

    # parse_primitive and _str_of_primitive are expected to be inverses of each other, as long as the str isn't abbreviated!
    # Parsing abbreviated strs too is allowed, just not required.
    def parse_primitive(self, primitive_str: str) -> AttributePrimitive:
        return None if primitive_str == self.NONE_STR else self._parse_primitive_not_none(primitive_str)

    def _str_of_primitive(self, primitive: AttributePrimitive, abbreviate: bool, extras: dict[str, typing.Any]) -> str:
        return self.NONE_STR if primitive is None else self._str_of_primitive_not_none(primitive, abbreviate, extras)

    def str_of_value(self, value: AttributeValue, abbreviate: bool = False, **extras: typing.Any) -> str:
        if isinstance(value, list):
            if len(value) == 0:
                return self.NONE_STR

            return ', '.join(self._str_of_primitive(elem, abbreviate, extras) for elem in value)

        return self._str_of_primitive(value, abbreviate, extras)
