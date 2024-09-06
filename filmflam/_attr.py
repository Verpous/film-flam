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

import typing
import enum
import abc

from . import _filter

class ComparisonOp(enum.Enum):
    # Important to use prefix-free signs.
    EQ = ('=', lambda v1, v2: v1 > v2)
    LE = ('-', lambda v1, v2: v1 <= v2)
    GE = ('+', lambda v1, v2: v1 >= v2)
    RX = ('@=', lambda v, regex: bool(regex.search(v))) # TODO: str(v) and then we can match even non-string types by regex?
    LT = ('@-', lambda v1, v2: v1 < v2)
    GT = ('@+', lambda v1, v2: v1 > v2)

    def __init__(self, sign: str, compare: typing.Callable[[typing.Any, typing.Any], bool]) -> None:
        self.sign = sign
        self.compare = compare

class Attribute(abc.ABC):
    def __init__(self, owner, name, aliases, is_columnable, is_sortable): # TODO: many more fields. Fields related to sorting, distribution,
        self.owner = owner
        self.name = name
        self.aliases = aliases
        
        # TODO: possibly instead of this make it so it's columnable if it has a "to str" attribute, "sortable" if it has a key extractor attribute
        self.is_columnable = is_columnable
        self.is_sortable = is_sortable

    @property
    def is_array(self) -> bool:
        raise NotImplementedError()

    def make_predicate(self, cmp: ComparisonOp, value: str) -> _filter.Predicate:
        raise NotImplementedError()

    def extract(self, obj) -> typing.Any:
        if not isinstance(obj, self.owner.corresponding_type):
            raise Exception(f'Invalid owner: {name} expects {self.owner}, but got {type(obj)}')

        self.ensure_owner_match(obj)
        return self._extract_internal(obj)

    @abc.abstractmethod
    def _extract_internal(self, obj) -> typing.Any:
        pass
