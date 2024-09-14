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

from . import _mlf
from . import _ml

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
    def __init__(self, findable_type, name, aliases, is_columnable, is_sortable): # TODO: many more fields. Fields related to sorting, distribution,
        self.findable_type = findable_type
        self.name = name
        self.aliases = aliases
        
        # TODO: possibly instead of this make it so it's columnable if it has a "to str" attribute, "sortable" if it has a key extractor attribute
        self.is_columnable = is_columnable
        self.is_sortable = is_sortable

    @property
    def is_array(self) -> bool:
        raise NotImplementedError()
    
    @property
    def default_cmp(self) -> ComparisonOp:
        raise NotImplementedError()

    # TODO: To force the right one of these to be implemented, either subclass Attribute with MovieAttribute, PersonAttribute, RoleAttribute,
    #       or some compositional approach.
    def _extract_from_movie(self, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie):
        raise NotImplementedError()

    def _extract_from_role(self, role: _ml.Role, mlf_roles: list[_mlf.MLFRole]):
        raise NotImplementedError()

    def _extract_from_person(self, person: _ml.Person, mlf_person: _mlf.MLFPerson):
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
