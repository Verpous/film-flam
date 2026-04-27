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
import datetime
import dateutil.parser
import dataclasses
import abc

from . import _attr
from . import _mlf
from . import _ml
from . import _exc
from . import utils

# If the way this EasyAttribute business is coded looks funny to you, here is why:
# 1. I want the "_extract_from_x" functions to only be defined in the concrete classes that need them, as opposed to being inherited abstract methods.
#    That way roles can optionally define "from_person/movie" extractors that we invoke if they "hasattr" it.
# 2. Despite all these extractor methods basically returning "Any", I want mypy to still check each one for type correctness.
# 3. We're gonna be implementing a 100 attributes so boilerplate must be kept to a minimum.
# 4. Lots of little constraints to please mypy and pylint about what we're doing.
@dataclasses.dataclass
class EasyAttributeParams:
    """
    Parameters used to create an :py:class:`EasyAttribute`.
    """
    name_without_type: str
    aliases_without_type: list[str]
    findable_type: _ml.FindableType
    type_handler: TypeHandler
    is_ascending: bool
    truncation_style: utils.TruncationStyle
    """
    Indicates how this attribute's values should be truncated if their string representation is too long.
    """
    
    default_max_len: int
    """
    The maximum length beyond which attribute values as strings get truncated.
    """

class EasyAttribute(_attr.Attribute):
    """
    Utility for easily implementing an attribute. You always have the option of inheriting directly from :py:class:`~._attr.Attribute`,
    but if you inherit from this instead you will have to do a lot less work. You only need to implement an extractor function for getting the attribute value:

    .. code-block:: python

        class MovieTitleAttribute(EasyAttribute):
            def _extract_from_movie(self, movie: Movie, mlf_movie: MLFMovie) -> None | str:
                return mlf_movie.title

        register(MovieTitleAttribute(EasyAttributeParams(
            name_without_type = 'title',
            aliases_without_type = ['name', 'movie'],
            findable_type = FindableType.MOVIES,
            type_handler = STR_HANDLER,
            is_ascending = True,
            truncation_style = TruncationStyle.TRIM_END,
            default_max_len = 45,
        )))
    """
    def __init__(self, params: EasyAttributeParams) -> None:
        """
        :param params: dataclass with all this attribute's parameters.
        """
        super().__init__(params.findable_type, params.name_without_type, params.aliases_without_type)
        self._params = params

    @property
    def is_ascending(self) -> bool:
        """
        :meta private:
        """
        return self._params.is_ascending

    @property
    def default_op(self) -> _attr.ComparisonOp:
        """
        :meta private:
        """
        return self._params.type_handler.default_op

    def str_of_value(self, value: _attr.AttributeValue, abbreviate: bool = False, **extras: typing.Any) -> str:
        """
        See :py:class:`Attribute.str_of_value <flam._attr.Attribute.str_of_value>`. EasyAttributes support two optional ``extras``:

        * max_len - the maximum length beyond which the string will be truncated down to this length.
        * ellipsis - short string to use to indicate a truncated part of the string.
        """
        value_str = super().str_of_value(value, abbreviate, **extras)

        if not abbreviate:
            return value_str
            
        max_len = extras.get('max_len', self._params.default_max_len)
        ellipsis = extras.get('ellipsis', '...')

        if not isinstance(max_len, int):
            raise _exc.InputError(f"Invalid max_len type: '{type(max_len)}': must be int.")

        if not isinstance(ellipsis, str):
            raise _exc.InputError(f"Invalid ellipsis type: '{type(ellipsis)}': must be str.")

        return utils.truncate(value_str, max_len, ellipsis=ellipsis, truncation_style=self._params.truncation_style)

    def _parse_primitive_not_none(self, primitive_str: str) -> _attr.AttributePrimitive:
        """
        :meta private:
        """
        try:
            return self._params.type_handler.parse(primitive_str)
        except ValueError as e:
            raise _exc.InputError(f"Invalid {self.qualified_name}: '{primitive_str}'.") from e

    def _str_of_primitive_not_none(self, primitive: _attr.AttributePrimitive, abbreviate: bool, extras: dict[str, typing.Any]) -> str:
        """
        :meta private:
        """
        return self._params.type_handler.str_of(primitive, abbreviate, extras)

type MovieExtractor[T] = typing.Callable[[EasyAttribute, _ml.Movie, _mlf.MLFMovie], T]
"""
Type signature for ``_extract_from_movie``.
"""

type PeopleExtractor[T] = typing.Callable[[EasyAttribute, _ml.People, list[_mlf.MLFPerson]], T]
"""
Type signature for ``_extract_from_people``.
"""

type RoleExtractor[T] = typing.Callable[[EasyAttribute, _ml.Role, _ml.MLFRolesDict, _mlf.MLFMovie, list[_mlf.MLFPerson]], T]
"""
Type signature for ``_extract_from_role``.
"""

type Extractor[T] = MovieExtractor | PeopleExtractor[T] | RoleExtractor[T]
"""
Type signature for any extractor method.
"""

_extractor_names = {
    _ml.FindableType.MOVIES: '_extract_from_movie',
    _ml.FindableType.PEOPLE: '_extract_from_people',
    _ml.FindableType.ROLES: '_extract_from_role',
}

# This function has TRet's syndrome.
def easy_attribute[TRet](params: EasyAttributeParams) -> typing.Callable[[Extractor[TRet]], EasyAttribute]:
    """
    Decorator you can apply to an extractor function to create an :py:class:`EasyAttribute` from it and return an instance of that class.
    This is an extra layer of convenience so you don't even have to explicitly inherit from EasyAttribute or instantiate it. For example:

    .. code-block:: python

        @register
        @easy_attribute(EasyAttributeParams(
            name_without_type = 'title',
            aliases_without_type = ['name', 'movie'],
            findable_type = FindableType.MOVIES,
            type_handler = STR_HANDLER,
            is_ascending = True,
            truncation_style = TruncationStyle.TRIM_END,
            default_max_len = 45,
        ))
        def _movie_title_extractor(self, movie: Movie, mlf_movie: MLFMovie) -> None | str:
            return mlf_movie.title

    :param params: dataclass with all the attribute's parameters.
    """
    def inner(extractor: Extractor[TRet]) -> EasyAttribute:
        class SpecificAttribute(EasyAttribute):
            pass

        setattr(SpecificAttribute, _extractor_names[params.findable_type], extractor)
        SpecificAttribute.__doc__ = extractor.__doc__
        return SpecificAttribute(params)
    return inner

# There are some facilities that we need out of every possible value attributes may extract (e.g.: parse, str_of, etc.).
# I don't want to wrap every such value in a "Value" class to provide those facitilites because that would mean making lots of small objects.
# Solution: Flyweight pattern. Subclasses of TypeHandler provide all the facilities we need, with the underlying value externalized.
# Downside: Casting/type assertion everywhere, or in many places just assuming the types are fine and not checking.
class TypeHandler(abc.ABC):
    """
    Utility for operations pertaining to the type of an attribute's values, so you don't have to repeat the same code for each attribute of that type.

    Note that all attributes are assumed to also possibly return ``None`` or a list of values.
    So even if your attribute returns ``list[None | float]``, it may still use :py:data:`FLOAT_HANDLER`, for example.
    """
    @property
    @abc.abstractmethod
    def default_op(self) -> _attr.ComparisonOp:
        """
        The default comparison operator that makes sense for this type.
        """

    @abc.abstractmethod
    def parse(self, primitive_str: str) -> _attr.AttributePrimitive:
        """
        Parse a string representing a single primitive of this handler's type. You do not need to handle ``None`` or lists in this function.

        :param primitive_str: a string representation of a single primitive value.
        """

    @abc.abstractmethod
    def str_of(self, primitive: _attr.AttributePrimitive, abbreviate: bool, extras: dict[str, typing.Any]) -> str:
        """
        Return a string representation of a single primitive value of this handler's type. You do not need to handle ``None`` or lists in this function.

        If ``abbreviate`` is false, then this method must be the inverse of :py:meth:`parse`.

        :param primitive: a single primitive value. You may assume this is not ``None``.
        :param abbreviate: indicates if the string should be abbreviated. Abbreviation can mean different things for different types. It's allowed to be lossy.
        :param extras: additional optional arguments to control the string conversion.
        """

class IntHandler(TypeHandler):
    """
    Type handler for integers with support for pretty strings.
    """
    __no_init_doc__ = True

    def __init__(self, abbreviable: bool) -> None:
        super().__init__()
        self._abbreviable = abbreviable

    @property
    def default_op(self) -> _attr.ComparisonOp:
        """
        :meta private:
        """
        return _attr.ComparisonOp.EQ

    def parse(self, primitive_str: str) -> int:
        """
        :meta private:
        """
        return utils.parse_num_pretty(primitive_str)

    def str_of(self, primitive: _attr.AttributePrimitive, abbreviate: bool, extras: dict[str, typing.Any]) -> str:
        """
        :meta private:
        """
        assert isinstance(primitive, int)
        
        if abbreviate and self._abbreviable:
            return utils.num_pretty(primitive)

        return str(primitive)

class FloatHandler(TypeHandler):
    """
    Type handler for floats with support for rounding off small decimal digits.
    """
    @property
    def default_op(self) -> _attr.ComparisonOp:
        """
        :meta private:
        """
        return _attr.ComparisonOp.EQ

    def parse(self, primitive_str: str) -> float:
        """
        :meta private:
        """
        return float(primitive_str)

    def str_of(self, primitive: _attr.AttributePrimitive, abbreviate: bool, extras: dict[str, typing.Any]) -> str:
        """
        :meta private:
        """
        if abbreviate:
            return f'{primitive:.1f}'
        
        # Python will abbreviate to scientific notation which is lossless(ish?) so it's fine.
        return str(primitive)

class BoolHandler(TypeHandler):
    """
    Type handler for booleans with support for various, case-insensitive ways you might describe a boolean (e.g., 'true', 'yes', 'no', 'n', etc.).
    """
    _str_reps = {
        'true':     True,
        't':        True,
        'yes':      True,
        'y':        True,
        'false':    False,
        'f':        False,
        'no':       False,
        'n':        False,
    }

    @property
    def default_op(self) -> _attr.ComparisonOp:
        """
        :meta private:
        """
        return _attr.ComparisonOp.EQ

    def parse(self, primitive_str: str) -> bool:
        """
        :meta private:
        """
        try:
            return self._str_reps[primitive_str.lower()]
        except KeyError as e:
            raise ValueError(f"Invalid boolean string: '{primitive_str}'") from e

    def str_of(self, primitive: _attr.AttributePrimitive, abbreviate: bool, extras: dict[str, typing.Any]) -> str:
        """
        :meta private:
        """
        return str(primitive)

class StrHandler(TypeHandler):
    """
    Type handler for strings.
    """
    @property
    def default_op(self) -> _attr.ComparisonOp:
        """
        :meta private:
        """
        return _attr.ComparisonOp.RX

    def parse(self, primitive_str: str) -> str:
        """
        :meta private:
        """
        return primitive_str

    def str_of(self, primitive: _attr.AttributePrimitive, abbreviate: bool, extras: dict[str, typing.Any]) -> str:
        """
        :meta private:
        """
        return typing.cast(str, primitive)

class MinutesHandler(TypeHandler):
    """
    Type handler for minutes with support for pretty formatting of hours:minutes.
    """
    @property
    def default_op(self) -> _attr.ComparisonOp:
        """
        :meta private:
        """
        return _attr.ComparisonOp.EQ

    def parse(self, primitive_str: str) -> int:
        """
        :meta private:
        """
        # We don't check for things like negative numbers, minutes exceeding 60, etc. because what the hell for.
        colon_idx = primitive_str.find(':')
        hrs_str, mins_str = (primitive_str[:colon_idx], primitive_str[colon_idx + 1:]) if colon_idx != -1 else ('0', primitive_str)
        
        # Support only base 10 because A: it makes sense, and B: base=0 doesn't support leading zeroes like '07'.
        hrs, mins = int(hrs_str), int(mins_str)
        return hrs * 60 + mins

    def str_of(self, primitive: _attr.AttributePrimitive, abbreviate: bool, extras: dict[str, typing.Any]) -> str:
        """
        :meta private:
        """
        assert isinstance(primitive, int)

        if abbreviate:
            return f'{str(primitive // 60)}:{str(primitive % 60).zfill(2)}'

        return str(primitive)

class DateHandler(TypeHandler):
    """
    Type handler for dates in many possible formats.
    """
    __no_init_doc__ = True

    def __init__(self, name: str, datefmt: str, is_ascending: bool, strmap: None | dict[str, str] = None) -> None:
        super().__init__()
        self._name = name
        self._datefmt = datefmt
        self._is_ascending = is_ascending
        self._strmap = strmap

    @property
    def default_op(self) -> _attr.ComparisonOp:
        """
        :meta private:
        """
        return _attr.ComparisonOp.EQ

    @property
    def name(self) -> str:
        """
        Name of the date format which can be appended to an attribute name to create a name for that attribute with that date format. Ex: '-year', '-day-of-month'.
        """
        return self._name

    @property
    def datefmt(self) -> str:
        """
        Format string for this date handler. See ``datetime.strftime`` in the python docs for format syntax.
        """
        return self._datefmt

    @property
    def is_ascending(self) -> bool:
        """
        Suggestion for whether you should sort this attribute in ascending or descending order.
        """
        return self._is_ascending

    def parse(self, primitive_str: str) -> datetime.date:
        """
        :meta private:
        """
        # First try to parse it with its datefmt. Otherwise use freeform parsing, and then drop the parts that aren't part of the format.
        try:
            return self._strptime(primitive_str)
        except ValueError:
            return self.strip(dateutil.parser.parse(primitive_str, default=datetime.datetime.min).date())

    def strip(self, date: datetime.date) -> datetime.date:
        """
        Takes a date and "zeroes out" the parts of the date which are irrelevant to this handler's :py:attr:`datefmt`.
        
        For instance, a handler which returns the year only doesn't care about the day and month.
        So by stripping those out, dates which have the same year but different days and months can be considered equal.

        :param date:
        """
        # As an optimization, don't do anything for complete dates.
        return self._strptime(date.strftime(self._datefmt)) if self._datefmt != "%Y-%m-%d" else date

    def str_of(self, primitive: _attr.AttributePrimitive, abbreviate: bool, extras: dict[str, typing.Any]) -> str:
        """
        :meta private:
        """
        assert isinstance(primitive, datetime.date)
        datestr = primitive.strftime(self._datefmt)
        return datestr if self._strmap is None else self._strmap[datestr]

    # This function is a hack because strptime won't work correctly with certain formats unless additional information is supplied.
    def _strptime(self, date_str: str) -> datetime.date:
        match self._datefmt:
            # Week of year requires specifying the day of week and the year.
            case "%U" | "%W":
                return datetime.datetime.strptime(date_str + " 0 1900", self._datefmt + " %w %Y").date()
            # Day of week requires specifying the week of year.
            case "%u" | "%w":
                return datetime.datetime.strptime(date_str + " 0", self._datefmt + " %W").date()
            case _:
                return datetime.datetime.strptime(date_str, self._datefmt).date()

SMALL_INT_HANDLER               = IntHandler(abbreviable=False)
"""
Handler object you can use for attributes which return small integers that do not need to be abbreviated.
"""

BIG_INT_HANDLER                 = IntHandler(abbreviable=True)
"""
Handler object you can use for attributes which return big integers that sometimes need to be abbreviated.
"""

FLOAT_HANDLER                   = FloatHandler()
"""
Handler object you can use for attributes which return floats.
"""

BOOL_HANDLER                    = BoolHandler()
"""
Handler object you can use for attributes which return booleans.
"""

STR_HANDLER                     = StrHandler()
"""
Handler object you can use for attributes which return strings.
"""

MINUTES_HANDLER                 = MinutesHandler()
"""
Handler object you can use for attributes which return a minutes duration.
"""

DATE_HANDLERS = [
    #           name                    datefmt     is_ascending
    DateHandler('-date',                '%Y-%m-%d', False),
    DateHandler('-year',                '%Y',       False),
    DateHandler('-month',               '%Y-%m',    False),
    DateHandler('-week-of-year',        '%U',       True),
    DateHandler('-week-of-year-monday', '%W',       True),
    DateHandler('-day-of-year',         '%j',       True),
    DateHandler('-day-of-month',        '%d',       True),
    DateHandler('-month-of-year',       '%m',       True,
        strmap={
            '01': 'January',
            '02': 'February',
            '03': 'March',
            '04': 'April',
            '05': 'May',
            '06': 'June',
            '07': 'July',
            '08': 'August',
            '09': 'September',
            '10': 'October',
            '11': 'November',
            '12': 'December',
        }),
    DateHandler('-day-of-week',         '%w',       True,
        strmap={
            '0': 'Sunday',
            '1': 'Monday',
            '2': 'Tuesday',
            '3': 'Wednesday',
            '4': 'Thursday',
            '5': 'Friday',
            '6': 'Saturday',
        }),
    DateHandler('-day-of-week-monday',  '%u',       True,
        strmap={
            '1': 'Monday',
            '2': 'Tuesday',
            '3': 'Wednesday',
            '4': 'Thursday',
            '5': 'Friday',
            '6': 'Saturday',
            '7': 'Sunday',
        }),
]
"""
List of date handlers in many date formats available to use.

:meta hide-value:
"""

class ArrayLengthAttribute(EasyAttribute):
    """
    Attribute which returns the number of elements in another attribute's return value. For attributes which don't return a list, the length is 1:

    .. code-block:: python

        register(ArrayLengthAttribute(my_attr))
    """
    def __init__(self, wrapped_attr: _attr.Attribute) -> None:
        """
        Initializes this attribute with the name 'num-<wrapped_attr.name_without_type>'.

        :param wrapped_attr: the attribute whose num of elements will be returned.
        """
        super().__init__(EasyAttributeParams(
            name_without_type = 'num-' + wrapped_attr.name_without_type,
            aliases_without_type = ['num-' + alias_without_type for alias_without_type in wrapped_attr.aliases_without_type],
            findable_type = wrapped_attr.findable_type,
            type_handler = SMALL_INT_HANDLER,
            is_ascending = False,
            truncation_style = utils.TruncationStyle.NO_TRIM,
            default_max_len = 999, # Don't care.
        ))

        self._wrapped_attr = wrapped_attr

    # Have to support all 3 extractors because if it's a person/movie attribute, it could be an array only when extracted from roles.
    def _extract_from_movie(self, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> int: # pylint: disable=unused-argument
        return self._len(movie)
    
    def _extract_from_people(self, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> int: # pylint: disable=unused-argument
        return self._len(people)
    
    def _extract_from_role(self, role: _ml.Role, mlf_roles: _ml.MLFRolesDict, mlf_movie: _mlf.MLFMovie, mlf_people: list[_mlf.MLFPerson]) -> int: # pylint: disable=unused-argument
        return self._len(role)

    def _len(self, findable: _ml.Findable) -> int:
        value = findable.extract(self._wrapped_attr)
        return len(value) if isinstance(value, list) else 1

class StringLengthAttribute(EasyAttribute):
    """
    Attribute which returns length of another attribute's return value as a string.
    """
    def __init__(self, wrapped_attr: _attr.Attribute) -> None:
        """
        Initializes this attribute with the name 'len-<wrapped_attr.name_without_type>'.

        :param wrapped_attr: the attribute whose string length will be returned.
        """
        super().__init__(EasyAttributeParams(
            name_without_type = 'len-' + wrapped_attr.name_without_type,
            aliases_without_type = ['len-' + alias_without_type for alias_without_type in wrapped_attr.aliases_without_type],
            findable_type = wrapped_attr.findable_type,
            type_handler = SMALL_INT_HANDLER,
            is_ascending = False,
            truncation_style = utils.TruncationStyle.NO_TRIM,
            default_max_len = 999, # Don't care.
        ))

        self._wrapped_attr = wrapped_attr

    # Have to support all 3 extractors because if it's a person/movie attribute, it could be an array only when extracted from roles.
    def _extract_from_movie(self, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> int: # pylint: disable=unused-argument
        return self._len(movie)
    
    def _extract_from_people(self, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> int: # pylint: disable=unused-argument
        return self._len(people)
    
    def _extract_from_role(self, role: _ml.Role, mlf_roles: _ml.MLFRolesDict, mlf_movie: _mlf.MLFMovie, mlf_people: list[_mlf.MLFPerson]) -> int: # pylint: disable=unused-argument
        return self._len(role)

    def _len(self, findable: _ml.Findable) -> int:
        value = findable.extract(self._wrapped_attr)
        return len(self._wrapped_attr.str_of_value(value))

class AverageAttribute(EasyAttribute):
    """
    Attribute which returns the average of another attribute's value.

    For movie attributes, this will be a people attribute with the average across all movies those people were in.

    For people attributes, this will be a movie attribute with the average across all people in the movie with the same crew type.

    Example usage:

    .. code-block:: python

        register(AverageAttribute(my_attr))

        for ct in CrewType:
            register(AverageAttribute(my_attr, as_crew_type=ct))
    """
    def __init__(self, wrapped_attr: _attr.Attribute, as_crew_type: None | _ml.CrewType = None) -> None:
        """
        Initializes this attribute with the name 'avg-<wrapped_attr.name_without_type>'.

        :param wrapped_attr: the attribute whose average will be returned.
        :param as_crew_type: optional modifier for this attribute. If provided, the attribute's name will be 'avg-<wrapped_attr.name_without_type>-as-<crew_type>':

            For movie attributes, this will be a people attribute with the average across all movies those people were in as this crew type.

            For people attributes, this will be a movie attribute with the average across all people in the movie with this crew type.
        """
        as_suffix = '' if as_crew_type is None else f'-as-{as_crew_type}'

        super().__init__(EasyAttributeParams(
            name_without_type = f'avg-{wrapped_attr.name_without_type}{as_suffix}',
            aliases_without_type = [f'avg-{alias_without_type}{as_suffix}' for alias_without_type in wrapped_attr.aliases_without_type],
            findable_type = self._flip_findable_type(wrapped_attr.findable_type),
            type_handler = FLOAT_HANDLER,
            is_ascending = wrapped_attr.is_ascending,
            truncation_style = utils.TruncationStyle.NO_TRIM,
            default_max_len = 999, # Don't care.
        ))

        self._wrapped_attr = wrapped_attr
        self._as_crew_type = as_crew_type

    def _extract_from_movie(self, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | float: # pylint: disable=unused-argument
        # For movie attributes, -as-X means the average over all the people in that movie in a specific crew type, default ANY.
        ct = _ml.CrewType.ANY if self._as_crew_type is None else self._as_crew_type
        return self._compute_average(people.extract(self._wrapped_attr)[0] for people in movie.associated_people(ct, _ml.GroupMode.SEPARATE)) # type: ignore
    
    def _extract_from_people(self, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> None | float: # pylint: disable=unused-argument
        # For people attributes, -as-X means the average over all the movies those people did while wearing the hat of X, default to their current crew type.
        people_as = people if self._as_crew_type is None else people.minimal_superset_people_in_other_crew_type(self._as_crew_type)

        if people_as is None:
            return None

        return self._compute_average(movie.extract(self._wrapped_attr) for movie in people_as.associated_movies()) # type: ignore
    
    # Not really a generic utils function because its handling of Nones is pretty ad hoc.
    @classmethod
    def _compute_average(cls, data: typing.Iterable[None | typing.SupportsFloat]) -> None | float:
        n = 0
        mean = 0.0
    
        for x in data:
            if x is not None:
                n += 1
                mean += (float(x) - mean) / n

        return mean if n > 0 else None

    # When wrapping movie attributes, the average is a property of people because it's the average over those people's associated movies.
    # When wrapping people attributes, the average is a property of movies because it's the average over that movie's associated people.
    # Roles don't support this attribute because there's no list of associated_X to iterate over.
    @classmethod
    def _flip_findable_type(cls, findable_type: _ml.FindableType) -> _ml.FindableType:
        match findable_type:
            case _ml.FindableType.PEOPLE:
                return _ml.FindableType.MOVIES
            case _ml.FindableType.MOVIES:
                return _ml.FindableType.PEOPLE
            case _:
                raise RuntimeError(f'Unexpected {findable_type=}')

class SumAttribute(EasyAttribute):
    """
    Attribute which returns the sum of another attribute's value.

    For movie attributes, this will be a people attribute with the sum across all movies those people were in.

    For people attributes, this will be a movie attribute with the sum across all people in the movie with the same crew type.
    """
    def __init__(self, wrapped_attr: _attr.Attribute, type_handler: TypeHandler, as_crew_type: None | _ml.CrewType = None) -> None:
        """
        Initializes this attribute with the name 'sum-<wrapped_attr.name_without_type>'.

        :param wrapped_attr: the attribute whose sum will be returned.
        :param as_crew_type: optional modifier for this attribute. If provided, the attribute's name will be 'sum-<wrapped_attr.name_without_type>-as-<crew_type>':

            For movie attributes, this will be a people attribute with the sum across all movies those people were in as this crew type.

            For people attributes, this will be a movie attribute with the sum across all people in the movie with this crew type.
        """
        # Works the same as AverageAttribute in many ways but for summing up instead.
        # One difference is we have to accept a TypeHandler. Averaging turns everything to floats but summation preserves types.
        # Valid type handlers are not just INT or FLOAT, but MINUTES too for example.
        as_suffix = '' if as_crew_type is None else f'-as-{as_crew_type}'

        super().__init__(EasyAttributeParams(
            name_without_type = f'sum-{wrapped_attr.name_without_type}{as_suffix}',
            aliases_without_type = [f'sum-{alias_without_type}{as_suffix}' for alias_without_type in wrapped_attr.aliases_without_type],
            findable_type = AverageAttribute._flip_findable_type(wrapped_attr.findable_type),
            type_handler = type_handler,
            is_ascending = wrapped_attr.is_ascending,
            truncation_style = utils.TruncationStyle.NO_TRIM,
            default_max_len = 999, # Don't care.
        ))

        self._wrapped_attr = wrapped_attr
        self._as_crew_type = as_crew_type

    def _extract_from_movie[TAttr: (int, float)](self, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | TAttr: # pylint: disable=unused-argument
        # For movie attributes, -as-X means the average over all the people in that movie in a specific crew type, default ANY.
        ct = _ml.CrewType.ANY if self._as_crew_type is None else self._as_crew_type
        return self._compute_sum(people.extract(self._wrapped_attr)[0] for people in movie.associated_people(ct, _ml.GroupMode.SEPARATE)) # type: ignore
    
    def _extract_from_people[TAttr: (int, float)](self, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> None | TAttr: # pylint: disable=unused-argument
        # For people attributes, -as-X means the average over all the movies those people did while wearing the hat of X, default to their current crew type.
        people_as = people if self._as_crew_type is None else people.minimal_superset_people_in_other_crew_type(self._as_crew_type)

        if people_as is None:
            return None

        return self._compute_sum(movie.extract(self._wrapped_attr) for movie in people_as.associated_movies()) # type: ignore
    
    # Not really a generic utils function because its handling of Nones is pretty ad hoc.
    @classmethod
    def _compute_sum[TAttr: (int, float)](cls, data: typing.Iterable[None | TAttr]) -> None | TAttr:
        # Written in such a way that it preserves the input type. I.e. we don't covert ints to floats.
        total = None
    
        for x in data:
            if x is None:
                continue

            if total is None:
                total = x
            else:
                total += x

        return total
