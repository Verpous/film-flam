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
from . import _mlf
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
    #                      name                 is_grouped_by_default
    CAST                = ('cast',              False)
    STUNTCAST           = ('stuntcast',         False)
    DIRECTOR            = ('director',          True)
    WRITER              = ('writer',            True)
    PRODUCER            = ('producer',          False)
    COMPOSER            = ('composer',          True)
    CINEMATOGRAPHER     = ('cinematographer',   True)
    EDITOR              = ('editor',            True)

    # This is how you add attributes to the enum without ruining it being primarily a StrEnum.
    def __new__(cls, name: str, is_grouped_by_default: bool) -> CrewType:
        obj = str.__new__(cls, name)
        obj.is_grouped_by_default = is_grouped_by_default
        return obj

    # This init only exists to convince mypy that this enum really has these fields.
    def __init__(self, name: str, is_grouped_by_default: bool) -> None:
        self.is_grouped_by_default = is_grouped_by_default

class Findable:
    def __init__(self, movie_list) -> None:
        self._movie_list = movie_list

class Movie(Findable):
    def __init__(self, movie_list, movie):
        super().__init__(movie_list)
        self._movie = movie

class Role(Findable):
    pass

# TODO: Actually represents a group? But still call it Person?
# Actuallyyy, the idea was that "Person" is detached from any crew type, whereas a group... isn't? So a Group actually is more like a Role than a Person??
class Person(Findable):
    pass

# TODO: So it looks like all lists are "movie lists" and you can "find" non-movie things from them as an option.
# First consider if this is really efficient enough, and then if so maybe we should rename the "List" in MovieListFile, MovieList to "MovieList".
# This will solve the problem of naming variables "lists", we'll name them "mlists" instead.
class MovieList:
    def __init__(self, movie_list_file): # TODO: specify how to group each crew type?
        self._movie_list_file = movie_list_file

    def __iter__(self):
        return self.find(FindableType.MOVIES)

    def find(self, what: FindableType, filter: None | _filter.Filter = None) -> typing.Iterator[typing.Any]: # TODO: not Any!
        assert filter is None or filter.findable_type == what

    def export(self, filter: _filter.Filter) -> _mlf.MovieListFile:
        assert filter.findable_type == FindableType.MOVIES

    # I permit access to this and entrust users to only read from it because some attributes need it,
    # and I don't believe in going so crazy about the API being "clean" and bulletproof that I sacrifice its efficiency.
    # If you're implementing an attribute you should be allowed to peek "under the hood" more than a typical user anyway.
    @property
    def underlying_movie_list_file(self) -> _mlf.MovieListFile:
        return self._movie_list_file
