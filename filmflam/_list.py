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

from . import _filter
from . import _ldef
from . import _listfile
from . import _ctx

class FindableType(enum.StrEnum):
    MOVIES  = 'movies'
    PEOPLE  = 'people'
    ROLES   = 'roles'

    @property
    def corresponding_type(self) -> type:
        raise NotImplementedError()

    def is_compatible(self, find: FindableType) -> bool:
        # Roles are compatible with everything because a role is associated with a person and a movie.
        return find == self.ROLES or self == find

class CrewType(enum.StrEnum):
    CAST                = 'cast'
    STUNTCAST           = 'stuntcast'
    DIRECTOR            = 'director'
    WRITER              = 'writer'
    PRODUCER            = 'producer'
    COMPOSER            = 'composer'
    CINEMATOGRAPHER     = 'cinematographer'
    EDITOR              = 'editor'

class Findable:
    pass

class ListHandle:
    def __init__(self, list_file): # TODO: specify how to group each crew type?
        self._list_file = list_file

    def __iter__(self):
        return self.find(FindableType.MOVIES)

    def apply_filter(self, filter: _filter.Filter):
        pass

    def find(self, what: FindableType, filter: None | _filter.Filter = None) -> typing.Iterator[typing.Any]: # TODO: not Any!
        assert filter is None or filter.findable_type == what

    def export(self, filter: _filter.Filter) -> _listfile.ListFile:
        assert filter.findable_type == FindableType.MOVIES
