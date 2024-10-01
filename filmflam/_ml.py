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
import copy

from . import _filter
from . import _mlf
from . import _ctx
from . import _fetch
from . import _attr
from . import _exc
from . import _dbg

class GroupMode(enum.StrEnum):
    DEFAULT             = 'default'
    GROUP               = 'group'
    SEPARATE            = 'separate'
    
    def __repr__(self) -> str:
        return str(self)

class CrewType(enum.StrEnum):
    CAST                = 'cast'
    STUNTCAST           = 'stuntcast'
    DIRECTOR            = 'director'
    WRITER              = 'writer'
    PRODUCER            = 'producer'
    COMPOSER            = 'composer'
    CINEMATOGRAPHER     = 'cinematographer'
    EDITOR              = 'editor'

    @property
    def default_group_mode(self) -> GroupMode:
        # There is a way to add this as an attribute of each enum but it has... problems.
        # It's also tricky to define a ClassVar to an enum so we put it outside the class.
        return _default_group_modes[self]
        
    def __repr__(self) -> str:
        return str(self)

_default_group_modes = {
    CrewType.CAST: GroupMode.SEPARATE,
    CrewType.STUNTCAST: GroupMode.SEPARATE,
    CrewType.DIRECTOR: GroupMode.GROUP,
    CrewType.WRITER: GroupMode.GROUP,
    CrewType.PRODUCER: GroupMode.SEPARATE,
    CrewType.COMPOSER: GroupMode.GROUP,
    CrewType.CINEMATOGRAPHER: GroupMode.GROUP,
    CrewType.EDITOR: GroupMode.GROUP,
}

class FindableType(enum.StrEnum):
    MOVIES              = 'movies'
    PEOPLE              = 'people'
    ROLES               = 'roles'

    def is_compatible(self, find: FindableType) -> bool:
        # Roles are compatible with everything because a role is associated with people and a movie.
        return find == self.ROLES or self == find
        
    def __repr__(self) -> str:
        return str(self)

class Findable(abc.ABC):
    def __init__(self, movie_list: MovieList) -> None:
        self._movie_list = movie_list
        self._cache: dict[typing.Hashable, typing.Any] = {}

    @property
    def movie_list(self) -> MovieList:
        return self._movie_list

    @abc.abstractmethod
    def extract(self, attribute: _attr.Attribute) -> _attr.AttributeValue:
        pass

    # TODO: some attributes may want to cache partial results, but we could have a special case for attributes that want to cache the entire result of extract(),
    # where extract simply returns the cached value without asking 
    def cache(self, key: typing.Hashable, value: typing.Any) -> None:
        self._cache[key] = value

    def get(self, key: typing.Hashable) -> typing.Any:
        return self._cache[key]

    def is_cached(self, key: typing.Hashable) -> bool:
        return key in self._cache

class Movie(Findable):
    def __init__(self, movie_list: MovieList, mlf_movie: _mlf.MLFMovie) -> None:
        super().__init__(movie_list)
        self._mlf_movie = mlf_movie

    def extract(self, attribute: _attr.Attribute) -> _attr.AttributeValue:
        return attribute._extract_from_movie(self, self._mlf_movie) # type: ignore

class Person(Findable):
    def __init__(self, movie_list: MovieList, mlf_person: _mlf.MLFPerson):
        super().__init__(movie_list)
        self._mlf_person = mlf_person

    def extract(self, attribute: _attr.Attribute) -> _attr.AttributeValue:
        return attribute._extract_from_person(self, self._mlf_person) # type: ignore

class Role(Findable):
    def __init__(self, movie_list: MovieList, mlf_roles: list[_mlf.MLFRole], mlf_movie: _mlf.MLFMovie, crew_type: CrewType, group_mode: GroupMode):
        super().__init__(movie_list)
        self._mlf_roles = mlf_roles
        self._mlf_movie = mlf_movie
        self._crew_type = crew_type
        self._group_mode = group_mode

    @property
    def crew_type(self) -> CrewType:
        return self._crew_type

    @property
    def group_mode(self) -> GroupMode:
        return self._group_mode

    def extract(self, attribute: _attr.Attribute) -> _attr.AttributeValue:
        # TODO: Optimize by caching Person/Movie objects, maybe even on the ML so that if someone iterates over movies/people later
        # they will be there and include things already computed on them.
        match attribute.findable_type:
            case FindableType.ROLES:
                return attribute._extract_from_role(self, self._mlf_roles) # type: ignore
            case FindableType.MOVIES:
                # Role attributes can define custom extractors from movie/people if the default behavior doesn't suit them.
                if hasattr(attribute, '_extract_from_movie'):
                    return attribute._extract_from_movie(self, self._mlf_movie)

                return Movie(self.movie_list, self._mlf_movie).extract(attribute)
            case FindableType.PEOPLE:
                mlf = self.movie_list.underlying_file
                mlf_people = (mlf.people_by_uid[mlf_role.person_uid] for mlf_role in self._mlf_roles)

                if hasattr(attribute, '_extract_from_person'):
                    return attribute._extract_from_person(self, list(mlf_people))

                # TODO: if attribute is array type already, flatten it?
                return [Person(self.movie_list, mlf_person).extract(attribute) for mlf_person in mlf_people]

class MovieList:
    def __init__(self, movie_list_file: _mlf.MovieListFile, ctx: _ctx.FlamContext):
        _dbg.logger.info(f"Creating movie list for '{movie_list_file.abstract_listdef}', "
            f"which has {len(movie_list_file.movies_by_uid)} movies, {len(movie_list_file.people_by_uid)} people")

        self._ctx = ctx
        self._movie_list_file = movie_list_file

        self._movies: None | list[Movie] = None
        self._people: None | list[Person] = None
        self._roles: None | dict[tuple[GroupMode, CrewType], list[Role]] = None

    def __iter__(self) -> typing.Iterator[Findable]:
        return iter(self.find(FindableType.MOVIES))

    def find(self, what: FindableType, crew_type: None | CrewType = None, group_mode: GroupMode = GroupMode.DEFAULT,
            filter: None | _filter.Filter = None) -> typing.Iterator[Findable]:
        _dbg.logger.info(f"Going to find {what} in '{self._movie_list_file.abstract_listdef}' with {filter=!s}")

        if filter is None:
            filter = self._ctx.compile_filter([], what)

        if filter.findable_type != what:
            raise _exc.InputError(f"Requested to find {what} but filter is of type {filter.findable_type}.")

        findables: list[Movie] | list[Person] | list[Role]
        
        match what:
            case FindableType.MOVIES:
                findables = self._generate_movies()
            case FindableType.PEOPLE:
                findables = self._generate_people()
            case FindableType.ROLES:
                if crew_type is None:
                    raise _exc.InputError(f"Cannot find {what} without specifying the crew type.")

                findables = self._generate_roles(crew_type, group_mode)

        if filter.is_empty:
            yield from findables
        else:
            yield from (f for f in findables if filter.excrete(f, self._ctx))

    def find_movies(self, filter: None | _filter.Filter = None) -> typing.Iterator[Movie]:
        # Yes, casting, ugly... But the infrastracture we will need to build to eliminate this cast is, at this time, not worth it.
        return typing.cast(typing.Iterator[Movie], self.find(FindableType.MOVIES, filter=filter))

    def find_people(self, filter: None | _filter.Filter = None) -> typing.Iterator[Person]:
        return typing.cast(typing.Iterator[Person], self.find(FindableType.PEOPLE, filter=filter))

    def find_roles(self, crew_type: None | CrewType = None, group_mode: GroupMode = GroupMode.DEFAULT, filter: None | _filter.Filter = None) -> typing.Iterator[Role]:
        return typing.cast(typing.Iterator[Role], self.find(FindableType.ROLES, crew_type=crew_type, group_mode=group_mode, filter=filter))

    def export(self, filter: _filter.Filter) -> _mlf.MovieListFile:
        _dbg.logger.info(f"Exporting '{self._movie_list_file.abstract_listdef}' with {filter=!s}")
        filtered_file = copy.deepcopy(self._movie_list_file)
        filtered_file.movies_by_uid = {movie._mlf_movie.uid: movie._mlf_movie for movie in self.find_movies(filter)}
        _fetch._remove_unused_people(filtered_file)
        _dbg.logger.info(f"Resulting file has {len(filtered_file.movies_by_uid)} movies, {len(filtered_file.people_by_uid)} people")
        return filtered_file

    # I permit access to this and entrust users to only read from it because some attributes need it,
    # and I don't believe in going so crazy about the API being "clean" and bulletproof that I sacrifice its efficiency.
    # If you're implementing an attribute you should be allowed to peek "under the hood" more than a typical user anyway.
    @property
    def underlying_file(self) -> _mlf.MovieListFile:
        return self._movie_list_file

    def _generate_movies(self) -> list[Movie]:
        if self._movies is None:
            self._movies = [Movie(self, mlf_movie) for mlf_movie in self._movie_list_file.movies_by_uid.values()]

        _dbg.logger.info(f"Generated movie list, {len(self._movies)=}")
        return self._movies

    def _generate_people(self) -> list[Person]:
        if self._people is None:
            self._people = [Person(self, mlf_person) for mlf_person in self._movie_list_file.people_by_uid.values()]

        _dbg.logger.info(f"Generated people list, {len(self._people)=}")
        return self._people

    def _generate_roles(self, crew_type: CrewType, group_mode: GroupMode) -> list[Role]:
        if self._roles is None:
            self._roles = {}

        modal_crew_type = (group_mode, crew_type)

        if modal_crew_type not in self._roles:
            # TODO: implement grouping. For now assume not grouped.
            self._roles[modal_crew_type] = [
                Role(self, [mlf_role], mlf_movie, crew_type, group_mode)
                for mlf_movie in self._movie_list_file.movies_by_uid.values()
                    for mlf_role in mlf_movie.crew[crew_type].roles_by_uid.values()
            ]

        _dbg.logger.info(f"Generated roles list, {modal_crew_type=}, {len(self._roles[modal_crew_type])=}")
        return self._roles[modal_crew_type]

# Crew type, grouping, roles, people brainstorming:
# I think we pass on allowing to group across crew types. Grouping is for a specific crew type
# Browsing by people means browsing all the movie's crew and has no grouping
# Browsing by "role" is actually browsing by a specific crew type, and it may be grouped
# the CLI will support searching in multiple crew types, which actually is just searching by each of them in a for loop
# a la: flam find cast,director -name tarantino     OR shorthand for all crew types:     flam find crew(or role?) -name tarantino
# Searching by crew type is searching by role
# There are no attributes or predicates specific to a crew type. They're are either for "roles" (meaning for any crew type), or for person or movie
# When searching by crew type you can also probe attributes of the movie or the people in the group
# The way we generalize it I suppose is: when searching by grouped roles, predicates of a person return true if they are true for any person in the group
# But really though? The "-appeared-in" person predicate, when applied to a group, should search if that exact group appeared elsewhere no?
# flam director -name coen

# Questions:
# * When grouping cast, do we just merge their characters into one?
# * What about tabulation, what if you want to print a person's attribute when finding by group? I guess print comma-delimited the attribute of each person
# * What about if I want to search something like "both directors are coen".
# * Hmm.. we've been saying that AttributePredicate should be "contains" by default for arrays.
#   In a group, every person attribute is an array attribute and has similar "contains" behavior
#   Maybe the "-all" predicate should work here too, like: find director -ngroup +2 -all -name coen (to find all groups of directors > 2 where all match coen)
#   Would this confuse people if targeting an array attribute of a person? Like you'd expect -all to seek in each array element and instead it looks at just 1 array element from each person
#   Also, when searching by ungrouped crew, we don't need any of this, should we do it anyway for consistency?
#   I guess maybe so because we want people to be able to search by many crew types at once with the same filter
# * does FindableType stay as it is or have just 3 possible values?
# * How to pass in whether to group when searching by crew type
