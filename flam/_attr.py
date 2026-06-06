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

# _typeshed.SupportsRichComparison exists but using it causes all kinds of problems with pylint and sphinx..
# We don't document it because it barely even belongs here, and we're happy to fool users into thinking it's from _typeshed.
class SupportsRichComparison(typing.Protocol):
    """
    :meta private:
    """
    def __lt__(self, other: typing.Any) -> bool: ...
    def __gt__(self, other: typing.Any) -> bool: ...

# Attributes may return any "primitive" type, or a list of primitive types.
# Primitives must be sortable. Other than that they are rather unconstrained, but conceptually we regard them as NOT collections.
# * str, int, datetime - good primitives
# * dict, set, list - bad primitives
# * Pedicates with a CMPTO argument like AttributePredicate expect the comparison to be to a primitive
# * If the attribute actually returns a list, they'll check if the list contains the argument
# * Otherwise they'll check if the argument is equal to the attribute value
# None has a special meaning in that we regard it as "value N/A", and consider '-' as the str representation of None.
type AttributePrimitive = None | SupportsRichComparison
"""
Type of a single element from a value returned by an attribute. Attributes may return either a primitive or a list of primitives.
``None`` is common, so always check for that. And other than that you are guaranteed that the value will be sortable.
"""

type AttributeValue = AttributePrimitive | list[AttributePrimitive]
"""
Type of a value returned by an attribute.
"""

# This enum used to not be a StrEnum and had assigned tuples of the sign and compare func. But it appears nicer in the documentation in its current form.
class ComparisonOp(enum.StrEnum):
    """
    Enumeration of possible comparison operators for comparing attributes to values. Each operator is represented with a different sign.
    """
    # IMPORTANT:
    # * Signs must be prefix-free! Hence the weird signs like '.+'
    # * Signs should avoid using characters that have special meaning in bash. Hence '+' instead of '>'
    # * Yes '~' is a special character but the alternative was '==', '=~' and that's too horrible.
    LE = '-'
    """Less or equal."""

    GE = '+'
    """Greater or equal."""

    EQ = '='
    """Exactly equal."""

    LT = '.-'
    """Strictly less than."""

    GT = '.+'
    """Strictly greater than."""

    RX = '~'
    """``str(value)`` matches a regular expression."""

    def __call__(self, primitive_lhs: AttributePrimitive, primitive_rhs: AttributePrimitive | re.Pattern) -> bool:
        """
        Compare the left hand side to the right hand side. The order matters. To illustrate:

        .. code-block:: python

            # Same as 10 < 15.
            ComparisonOp.LE(10, 15)

            # Same as re.search('the.*', 'The Big Lebowski').
            ComparisonOp.RX('The Big Lebowski', re.compile('the.*'))

        :param primitive_lhs: the left hand side value to compare.
        :param primitive_rhs: the right hand side value to compare.
        """
        return _cmp_funcs[self](primitive_lhs, primitive_rhs)

    def __repr__(self) -> str:
        return str(self)

_cmp_funcs = {
    ComparisonOp.LE: operator.le,
    ComparisonOp.GE: operator.ge,
    ComparisonOp.EQ: operator.eq,
    ComparisonOp.LT: operator.lt,
    ComparisonOp.GT: operator.gt,
    ComparisonOp.RX: (lambda v, pattern: bool(pattern.search(v))),
}

class CmpTo:
    """
    Represents comparison of some attribute's values to some constant primitive value, using a specific comparison operator.
    
    In a filter, these would be represented as a string like so: '<op><value>', where <op> is the sign of a :py:class:`ComparisonOp`, and <value> is a possible value of an attribute.
    The <op> part is optional as all attributes define a default operator. To illustrate:

    .. code-block:: python
        
        # As a string: '+90'. Checks if metascores are greater or equal to 90.
        CmpTo(ComparisonOp.GE, 90, ctx.attributes['movies-metascore'])
    
        # As a string: '~the.*'. Checks if stringified values match the regex 'the.*'.
        # This is usually the default operator for string attributes, so the '~' can usually be omitted and you can simply write 'the.*'.
        CmpTo(ComparisonOp.RX, re.compile('the.*'), ctx.attributes['movies-title'])
    """
    def __init__(self, op: ComparisonOp, const_primitive: AttributePrimitive | re.Pattern, attribute: Attribute) -> None:
        """
        :param op: the operator to use for comparisons.
        :param const_primitive: which constant value to compare other values to.
        :param attribute: which attribute the values are expected to come from.
        """
        self._attribute = attribute
        self._op = op
        self._const_primitive = const_primitive

    def __call__(self, primitive: AttributePrimitive) -> bool:
        """
        Compares ``primitive`` to the constant value. Expects ``primitive`` to come from the same attribute this object was created with.

        When comparing ``None`` to a not-``None`` value, the result is always false. That is, ``None`` is neither less, nor greater, nor equal to other values.

        :param primitive: variable value to compare with.
        """
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
                return f"{self._op}{self._const_primitive.pattern}"
            case _:
                assert not isinstance(self._const_primitive, re.Pattern)
                return f"{self._op}{self._attribute.str_of_value(self._const_primitive)}"

class Attribute(abc.ABC):
    """
    Base class for all attributes that a findable object may have. This is a key element in interfacing with flam -
    any data you may be interested in obtaining about a movie, people, or role is obtained via attributes.

    Attributes provide facilities for using them generically.
    You can extend flam by inheriting from this class and registering :ref:`your own custom attributes <Implementing a custom attribute>`.
    """

    NONE_STR = '-'
    """
    The string representation we use for ``None`` values.
    """

    def __init__(self, findable_type: _ml.FindableType, name_without_type: str, aliases_without_type: None | list[str] = None):
        """
        :param findable_type: the type of objects which have this attribute.
        :param name_without_type: the name of the attribute without the findable type.
        :param aliases_without_type: list of aliases for the attribute, also without the type.
        """
        self._findable_type = findable_type
        self._name_without_type = name_without_type
        self._qualified_name = _reg.compose_qualified_attr_or_pred_name(findable_type, name_without_type)
        self._aliases_without_type = [] if aliases_without_type is None else aliases_without_type

    @property
    def name_without_type(self) -> str:
        """
        The name of the attribute without the findable type. E.g. 'title', not 'movies-title'.
        """
        return self._name_without_type

    @property
    def aliases_without_type(self) -> typing.Iterable[str]:
        """
        Iterate over all aliases of the attribute, also without the findable type.
        """
        yield from self._aliases_without_type
    
    @property
    def findable_type(self) -> _ml.FindableType:
        """
        The type of objects which have this attribute.
        """
        return self._findable_type

    @property
    def qualified_name(self) -> str:
        """
        The qualified name of the attribute. E.g. 'movies-title', not just 'title'.
        """
        return self._qualified_name

    @property
    def qualified_aliases(self) -> typing.Iterable[str]:
        """
        Iterate over all aliases of the attribute, by their qualified name.
        """
        # No need to cache this.
        for alias_without_type in self.aliases_without_type:
            yield _reg.compose_qualified_attr_or_pred_name(self._findable_type, alias_without_type)

    @property
    @abc.abstractmethod
    def is_ascending(self) -> bool:
        """
        Suggestion for whether you should sort this attribute in ascending or descending order.
        """

    @property
    @abc.abstractmethod
    def default_op(self) -> ComparisonOp:
        """
        The default comparison operator that makes sense for this attribute.

        Typically, string attributes use regular expression matching by default, and other attributes check for equality.
        """

    @abc.abstractmethod
    def _parse_primitive_not_none(self, primitive_str: str) -> AttributePrimitive:
        """
        .. note::

            This is an internal method of attributes. Outside users shouldn't call it,
            but you need to implement it as part of :ref:`implementing a custom attribute <Implementing a custom attribute>`.
        
        Parse a string representing a single primitive into the value of this attribute. You do not need to handle ``None`` or lists in this function.

        :param primitive_str: a string representation of a single primitive value. You may assume this is not :py:attr:`NONE_STR`.

        :meta public:
        """

    @abc.abstractmethod
    def _str_of_primitive_not_none(self, primitive: AttributePrimitive, abbreviate: bool, extras: dict[str, typing.Any]) -> str:
        """
        .. note::

            This is an internal method of attributes. Outside users shouldn't call it,
            but you need to implement it as part of :ref:`implementing a custom attribute <Implementing a custom attribute>`.
        
        Return a string representation of a single primitive value of this attribute. You do not need to handle ``None`` or lists in this function.

        If ``abbreviate`` is false, then this method must be the inverse of :py:meth:`_parse_primitive_not_none`.

        :param primitive: a single primitive value. You may assume this is not ``None``.
        :param abbreviate: indicates if the string should be abbreviated. For example truncating long strings, or converting 1000000 to "1M".
        :param extras: additional optional arguments to control the string conversion.
        
        :meta public:
        """

    def sort_key(self, value: AttributeValue, is_ascending: None | bool = None) -> typing.Any:
        """
        Returns an object which may be used to safely compare values of this attribute, even if some of them are ``None``. For example:

        :param is_ascending: optionally indicate the desired sort order. This will ensure Nones are at the bottom of the sort no matter what. Defaults to :py:attr:`is_ascending`.
        
        .. code-block:: python

            attr_values = [movie.extract(attr) for attr in movie_list.find_movies()]
            attr_values.sort(key=attr.sort_key, reverse=(not attr.is_ascending))

        :param value: a value extracted using this attribute.
        """

        if is_ascending is None:
            is_ascending = self.is_ascending

        if isinstance(value, list):
            return ([self._sort_key_primitive(elem, is_ascending) for elem in value])
        
        return self._sort_key_primitive(value, is_ascending)

    def _sort_key_primitive(self, primitive: AttributePrimitive, is_ascending: bool) -> SupportsRichComparison:
        # We xor with the ascending preference so that Nones always end up at the bottom of the sort whether ascending or descending.
        return ((primitive is not None) ^ is_ascending, primitive)

    # parse_primitive and _str_of_primitive are expected to be inverses of each other, as long as the str isn't abbreviated!
    # Parsing abbreviated strs too is allowed, just not required.
    def parse_primitive(self, primitive_str: str) -> AttributePrimitive:
        """
        Parse a string representing a single primitive into the value of this attribute.

        :param primitive_str: a string representation of a single primitive value.
        """
        return None if primitive_str == self.NONE_STR else self._parse_primitive_not_none(primitive_str)

    def _str_of_primitive(self, primitive: AttributePrimitive, abbreviate: bool, extras: dict[str, typing.Any]) -> str:
        return self.NONE_STR if primitive is None else self._str_of_primitive_not_none(primitive, abbreviate, extras)

    def str_of_value(self, value: AttributeValue, abbreviate: bool = False, **extras: typing.Any) -> str:
        """
        Return a string representation of a value of this attribute. If the value is a list, its elements will be separated by commas.

        :param value: a value of this attribute.
        :param abbreviate: indicates if the string should be abbreviated. For example truncating long strings, or converting 1000000 to "1M".
        :param extras: additional optional arguments to control the string conversion.
        """
        if isinstance(value, list):
            if len(value) == 0:
                return self.NONE_STR

            return ', '.join(self._str_of_primitive(elem, abbreviate, extras) for elem in value)

        return self._str_of_primitive(value, abbreviate, extras)
