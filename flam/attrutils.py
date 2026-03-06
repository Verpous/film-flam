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
from . import _exc

# There are some facilities that we need out of every possible value attributes may extract (e.g.: parse, str_of, etc.).
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

class DateHandler(TypeHandler):
    def __init__(self, name: str, datefmt: str, is_ascending: bool, strmap: None | dict[str, str] = None) -> None:
        super().__init__()
        self._name = name
        self._datefmt = datefmt
        self._is_ascending = is_ascending
        self._strmap = strmap

    @property
    def type_(self) -> type:
        return datetime.date

    @property
    def default_op(self) -> _attr.ComparisonOp:
        return _attr.ComparisonOp.EQ

    @property
    def name(self) -> str:
        return self._name

    @property
    def datefmt(self) -> str:
        return self._datefmt

    @property
    def is_ascending(self) -> bool:
        return self._is_ascending

    def parse(self, value_str: str) -> _attr.AttributeValue:
        # First try to parse it with its datefmt. Otherwise use freeform parsing, and then drop the parts that aren't part of the format.
        try:
            return self._strptime(value_str)
        except ValueError:
            return self.strip(dateutil.parser.parse(value_str, default=datetime.datetime.min))

    def strip(self, date: datetime.date) -> datetime.date:
        # As an optimization, don't do anything for complete dates.
        return self._strptime(date.strftime(self._datefmt)) if date != "%Y-%m-%d" else date

    def str_of(self, value: _attr.AttributeValue) -> str:
        assert isinstance(value, datetime.date)
        datestr = value.strftime(self._datefmt)
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

STR_HANDLER = EasyTypeHandler(
    type_ = str,
    default_op = _attr.ComparisonOp.RX,
    parse = lambda s: s,
    str_of = lambda s: typing.cast(str, s),
)

def _parse_minutes(value_str: str) -> int:
    # We don't check for things like negative numbers, minutes exceeding 60, what base the numbers are in, etc. Because what the hell for.
    colon_idx = value_str.find(':')
    hrs_str, mins_str = (value_str[:colon_idx], value_str[colon_idx + 1:]) if colon_idx != -1 else ('0', value_str)
    hrs, mins = int(hrs_str, base=0), int(mins_str, base=0)
    return hrs * 60 + mins

MINUTES_HANDLER = EasyTypeHandler(
    type_ = int,
    default_op = _attr.ComparisonOp.EQ,
    parse = _parse_minutes,
    str_of = lambda mins: f'{str(mins // 60)}:{str(mins % 60).zfill(2)}', # type: ignore
)

DATE_HANDLERS = [
    DateHandler('',                     "%Y-%m-%d", False),
    DateHandler('-year',                "%Y",       False),
    DateHandler('-month',               "%Y-%m",    False),
    DateHandler('-week-of-year',        "%U",       True),
    DateHandler('-week-of-year-monday', "%W",       True),
    DateHandler('-day-of-year',         "%j",       True),
    DateHandler('-day-of-month',        "%d",       True),
    DateHandler('-month-of-year',       "%m",       True,
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
    DateHandler('-day-of-week',         "%w",       True,
        strmap={
            '0': 'Sunday',
            '1': 'Monday',
            '2': 'Tuesday',
            '3': 'Wednesday',
            '4': 'Thursday',
            '5': 'Friday',
            '6': 'Saturday',
        }),
    DateHandler('-day-of-week-monday',  "%u",       True,
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

# If the way this EasyAttribute business is coded looks funny to you, here is why:
# 1. I want the "_extract_from_x" functions to only be defined in the concrete classes that need them, as opposed to being inherited abstract methods.
#    That way roles can optionally define "from_person/movie" extractors that we invoke if they "hasattr" it.
# 2. Despite all these extractor methods basically returning "Any", I want mypy to still check each one for type correctness.
# 3. We're gonna be implementing a 100 attributes so boilerplate must be kept to a minimum.
# 4. Lots of little constraints to please mypy and pylint about what we're doing.
@dataclasses.dataclass
class EasyAttributeParams:
    name_without_type: str
    aliases_without_type: list[str]
    findable_type: _ml.FindableType
    type_handler: TypeHandler
    is_big_endian: bool
    is_ascending: bool

class EasyAttribute(_attr.Attribute):
    def __init__(self, params: EasyAttributeParams) -> None:
        self._params = params

    @property
    def name_without_type(self) -> str:
        return self._params.name_without_type

    @property
    def aliases_without_type(self) -> list[str]:
        return self._params.aliases_without_type

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
    def type_(self) -> type:
        return self._params.type_handler.type_

    @property
    def default_op(self) -> _attr.ComparisonOp:
        return self._params.type_handler.default_op

    def parse(self, value_str: str) -> _attr.AttributeValue:
        try:
            return self._params.type_handler.parse(value_str)
        except ValueError as e:
            raise _exc.InputError(f"Invalid {self.qualified_name}: '{value_str}'.") from e

    def _str_of_single(self, value: _attr.AttributeValue) -> str:
        return self._params.type_handler.str_of(value)

class LenAttribute(EasyAttribute):
    def __init__(self, len_of: _attr.Attribute) -> None:
        super().__init__(EasyAttributeParams(
            name_without_type = 'n' + len_of.name_without_type,
            aliases_without_type = ['n' + alias_without_type for alias_without_type in len_of.aliases_without_type],
            findable_type = len_of.findable_type,
            type_handler = INT_HANDLER,
            is_big_endian = True,
            is_ascending = False,
        ))

        self._len_of = len_of

    # Have to support all 3 extractors because if it's a person/movie attribute, it could be an array only when extracted from roles.
    def _extract_from_movie(self, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> int: # pylint: disable=unused-argument
        return self._len(movie)
    
    def _extract_from_person(self, person: _ml.Person, mlf_person: _mlf.MLFPerson) -> int: # pylint: disable=unused-argument
        return self._len(person)
    
    def _extract_from_role(self, role: _ml.Role, mlf_roles: list[_mlf.MLFRole]) -> int: # pylint: disable=unused-argument
        return self._len(role)

    def _len(self, findable: _ml.Findable) -> int:
        # TODO: Actually support len of strs too?
        actual = findable.extract(self._len_of)
        return len(actual) if isinstance(actual, list) else 1

type MovieExtractor[T] = typing.Callable[[EasyAttribute, _ml.Movie, _mlf.MLFMovie], T]
type PersonExtractor[T] = typing.Callable[[EasyAttribute, _ml.Person, _mlf.MLFPerson], T]
type RoleExtractor[T] = typing.Callable[[EasyAttribute, _ml.Role, list[_mlf.MLFRole]], T]
type Extractor[T] = MovieExtractor | PersonExtractor[T] | RoleExtractor[T]

_extractor_names = {
    _ml.FindableType.MOVIES: '_extract_from_movie',
    _ml.FindableType.PEOPLE: '_extract_from_person',
    _ml.FindableType.ROLES: '_extract_from_role',
}

def easy_attribute[ET](params: EasyAttributeParams) -> typing.Callable[[Extractor[ET]], EasyAttribute]:
    def inner(extractor: Extractor[ET]) -> EasyAttribute:
        class SpecificAttribute(EasyAttribute):
            pass

        setattr(SpecificAttribute, _extractor_names[params.findable_type], extractor)
        return SpecificAttribute(params)
    return inner
