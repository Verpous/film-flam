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
from . import _file
from . import _ldef

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

def parse_ct_gm(ct_gm_str: str) -> tuple[CrewType, GroupMode]:
    colon_idx = ct_gm_str.find(':')
    crew_type_str, group_mode_str = (ct_gm_str[:colon_idx], ct_gm_str[colon_idx + 1:]) if colon_idx != -1 else (ct_gm_str, GroupMode.DEFAULT)

    try:
        crew_type = CrewType(crew_type_str)
    except ValueError as e:
        raise _exc.InputError(f"Invalid crew type: '{crew_type_str}'") from e

    try:
        group_mode = GroupMode(group_mode_str)
    except ValueError as e:
        raise _exc.InputError(f"Invalid group mode: '{group_mode_str}'") from e

    return crew_type, group_mode

_default_group_modes = {
    CrewType.CAST:              GroupMode.SEPARATE,
    CrewType.STUNTCAST:         GroupMode.SEPARATE,
    CrewType.DIRECTOR:          GroupMode.GROUP,
    CrewType.WRITER:            GroupMode.GROUP,
    CrewType.PRODUCER:          GroupMode.SEPARATE,
    CrewType.COMPOSER:          GroupMode.GROUP,
    CrewType.CINEMATOGRAPHER:   GroupMode.GROUP,
    CrewType.EDITOR:            GroupMode.GROUP,
}

class FindableType(enum.StrEnum):
    MOVIES              = 'movies'
    PEOPLE              = 'people'
    ROLES               = 'roles'

    def is_applicable_to(self, find: FindableType) -> bool:
        # Roles are compatible with everything because a role is associated with people and a movie.
        return find == self.ROLES or self == find
        
    def __repr__(self) -> str:
        return str(self)

class Findable(abc.ABC):
    def __init__(self, movie_list: MovieList) -> None:
        self._movie_list = movie_list

    @property
    def movie_list(self) -> MovieList:
        return self._movie_list

    @property
    @abc.abstractmethod
    def type_(self) -> FindableType:
        pass

    @property
    @abc.abstractmethod
    def uid(self) -> str:
        pass

    @abc.abstractmethod
    def extract(self, attribute: _attr.Attribute) -> _attr.AttributeValue:
        pass

    # TODO: So much awful about how these are implemented from an optimization perspective. Maybe they should return the MLF objects, maybe they should cache things,
    # maybe they should share the Movie/Person objects with the entire list.
    @abc.abstractmethod
    def associated_movies(self) -> typing.Iterable[Movie]:
        pass

    @abc.abstractmethod
    def associated_people(self) -> typing.Iterable[Person]:
        pass

class Movie(Findable):
    def __init__(self, movie_list: MovieList, mlf_movie: _mlf.MLFMovie) -> None:
        super().__init__(movie_list)
        self._mlf_movie = mlf_movie

    @property
    def type_(self) -> FindableType:
        return FindableType.MOVIES

    @property
    def uid(self) -> str:
        return self._mlf_movie.uid

    def extract(self, attribute: _attr.Attribute) -> _attr.AttributeValue:
        return attribute._extract_from_movie(self, self._mlf_movie) # type: ignore

    def associated_movies(self) -> typing.Iterable[Movie]:
        yield self

    def associated_people(self) -> typing.Iterable[Person]:
        for mlf_person in self.movie_list.underlying_file.people_by_uid.values():
            yield Person(self.movie_list, mlf_person)

class Person(Findable):
    def __init__(self, movie_list: MovieList, mlf_person: _mlf.MLFPerson):
        super().__init__(movie_list)
        self._mlf_person = mlf_person

    @property
    def type_(self) -> FindableType:
        return FindableType.PEOPLE

    @property
    def uid(self) -> str:
        return self._mlf_person.uid

    def extract(self, attribute: _attr.Attribute) -> _attr.AttributeValue:
        return attribute._extract_from_person(self, self._mlf_person) # type: ignore

    def associated_movies(self) -> typing.Iterable[Movie]:
        for mlf_movie in self.movie_list.underlying_file.movies_by_uid.values():
            if any(self._mlf_person.uid in mlf_movie.crew[crew_type].roles_by_uid for crew_type in CrewType):
                yield Movie(self.movie_list, mlf_movie)

    def associated_people(self) -> typing.Iterable[Person]:
        yield self

class Role(Findable):
    def __init__(self, movie_list: MovieList, mlf_roles: list[_mlf.MLFRole], mlf_movie: _mlf.MLFMovie, crew_type: CrewType, group_mode: GroupMode):
        super().__init__(movie_list)
        self._mlf_roles = mlf_roles
        self._mlf_movie = mlf_movie
        self._crew_type = crew_type
        self._group_mode = group_mode

        # TODO: A bit misleading to call it a UID if it isn't based on the movie and the ct:gm.
        self._uid = ','.join(mlf_role.person_uid for mlf_role in mlf_roles)

    @property
    def type_(self) -> FindableType:
        return FindableType.ROLES

    @property
    def uid(self) -> str:
        return self._uid

    @property
    def crew_type(self) -> CrewType:
        return self._crew_type

    @property
    def group_mode(self) -> GroupMode:
        return self._group_mode

    def extract(self, attribute: _attr.Attribute) -> _attr.AttributeValue:
        # Support optionally implementing _extract_from_role on any type of attribute, for custom behavior on how to extract them from roles.
        if attribute.findable_type == FindableType.ROLES or hasattr(attribute, '_extract_from_role'):
            return attribute._extract_from_role(self, self._mlf_roles) # type: ignore
        
        # TODO: Optimize by caching Person/Movie objects, maybe even on the ML so that if someone iterates over movies/people later
        # they will be there and include things already computed on them.
        if attribute.findable_type == FindableType.MOVIES:
            return Movie(self.movie_list, self._mlf_movie).extract(attribute)
        
        if attribute.findable_type == FindableType.PEOPLE:
            mlf = self.movie_list.underlying_file
            mlf_people = (mlf.people_by_uid[mlf_role.person_uid] for mlf_role in self._mlf_roles)

            # We should not re-sort this. It should be ordered the same self._mlf_roles, which should be sorted by the person names.
            return list(self._flatten(value for mlf_person in mlf_people if (value := Person(self.movie_list, mlf_person).extract(attribute)) is not None))
        
        raise RuntimeError(f"Unexpected {attribute.findable_type=}")

    def _flatten(self, iterable: typing.Iterable[_attr.AttributeValue]) -> typing.Iterable[_attr.AttributeValue]:
        for elem in iterable:
            yield from _attr.iter_value(elem)

    def associated_movies(self) -> typing.Iterable[Movie]:
        yield Movie(self.movie_list, self._mlf_movie)

    def associated_people(self) -> typing.Iterable[Person]:
        people_by_uid = self.movie_list.underlying_file.people_by_uid
        yield from (Person(self.movie_list, people_by_uid[mlf_role.person_uid]) for mlf_role in self._mlf_roles)

class MovieList:
    def __init__(self, movie_list_file: _mlf.MovieListFile, ctx: _ctx.FlamContext):
        _dbg.logger.info(f"Creating movie list for '{movie_list_file.abstract_listdef}', "
            f"which has {len(movie_list_file.movies_by_uid)} movies, {len(movie_list_file.people_by_uid)} people")

        self._ctx = ctx
        self._movie_list_file = movie_list_file

        self._movies: None | list[Movie] = None
        self._people: None | list[Person] = None
        self._roles: None | dict[tuple[CrewType, GroupMode], list[Role]] = None

    # I permit access to this and entrust users to only read from it because some attributes need it,
    # and I don't believe in going so crazy about the API being "clean" and bulletproof that I sacrifice its efficiency.
    # If you're implementing an attribute you should be allowed to peek "under the hood" more than a typical user anyway.
    @property
    def underlying_file(self) -> _mlf.MovieListFile:
        return self._movie_list_file

    @property
    def ctx(self) -> _ctx.FlamContext:
        return self._ctx

    @property
    def abstract_listdef(self) -> _ldef.CanonListdef:
        return self._movie_list_file.abstract_listdef

    @property
    def list_type(self) -> str:
        assert not isinstance(self._movie_list_file.list_type, _file.UnsetType)
        return self._movie_list_file.list_type

    @property
    def address(self) -> str:
        assert not isinstance(self._movie_list_file.address, _file.UnsetType)
        return self._movie_list_file.address

    @property
    def uid_type(self) -> str:
        assert not isinstance(self._movie_list_file.uid_type, _file.UnsetType)
        return self._movie_list_file.uid_type

    def __iter__(self) -> typing.Iterator[Movie]:
        return iter(self.find_movies())

    def find(self, what: FindableType, crew_type: None | CrewType = None, group_mode: GroupMode = GroupMode.DEFAULT,
            filter: None | _filter.Filter = None) -> typing.Iterable[Findable]:
        _dbg.logger.info(f"Going to find {what} with {crew_type=}, {group_mode=} in '{self._movie_list_file.abstract_listdef}' with {filter=!s}")

        if filter is None:
            filter = self._ctx.compile_filter(None, what)

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

    def find_movies(self, filter: None | _filter.Filter = None) -> typing.Iterable[Movie]:
        # The infrastructure we will need to write these functions without ignoring types is too much to bother.
        return typing.cast(typing.Iterable[Movie], self.find(FindableType.MOVIES, filter=filter))

    def find_people(self, filter: None | _filter.Filter = None) -> typing.Iterable[Person]:
        return typing.cast(typing.Iterable[Person], self.find(FindableType.PEOPLE, filter=filter))

    def find_roles(self, crew_type: None | CrewType = None, group_mode: GroupMode = GroupMode.DEFAULT, filter: None | _filter.Filter = None) -> typing.Iterable[Role]:
        return typing.cast(typing.Iterable[Role], self.find(FindableType.ROLES, crew_type=crew_type, group_mode=group_mode, filter=filter))

    def export(self, filter: _filter.Filter) -> _mlf.MovieListFile:
        _dbg.logger.info(f"Exporting '{self._movie_list_file.abstract_listdef}' with {filter=!s}")
        filtered_file = copy.deepcopy(self._movie_list_file)
        filtered_file.movies_by_uid = {movie._mlf_movie.uid: movie._mlf_movie for movie in self.find_movies(filter)}
        _fetch._remove_unused_people(filtered_file)
        _dbg.logger.info(f"Resulting file has {len(filtered_file.movies_by_uid)} movies, {len(filtered_file.people_by_uid)} people")
        return filtered_file

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

        if group_mode == GroupMode.DEFAULT:
            group_mode = crew_type.default_group_mode

        ct_gm = (crew_type, group_mode)

        if ct_gm not in self._roles:
            match group_mode:
                case GroupMode.SEPARATE:
                    self._roles[ct_gm] = [
                        Role(self, [mlf_role], mlf_movie, crew_type, group_mode)
                        for mlf_movie in self._movie_list_file.movies_by_uid.values()
                            for mlf_role in mlf_movie.crew[crew_type].roles_by_uid.values()
                    ]
                case GroupMode.GROUP:
                    # High level, the algorithm is as follows:
                    #
                    # foreach movie:
                    #     intersect movie's crew set with every other movie's
                    #     if the intersection with a movie (including self) is not empty, add that intersection to a set of sets
                    #
                    # foreach crew set in the set of sets we built:
                    #     find all movies whose crew is a superset of this set
                    #
                    # In the end you have for every relevant person set, all movies that are accredited to it.
                    # In reality the algorithm barely resembles this because of various optimizations.

                    mlf = self._movie_list_file

                    # groups will in the end include all relevant crew sets. We know that at minimum, it should have every crew that any movie has.
                    # This set also allows us to only iterate over every unique movie crew pair, instead of every movie pair.
                    groups = {
                        frozenset(mlf_movie.crew[crew_type].roles_by_uid)
                        for mlf_movie in mlf.movies_by_uid.values()
                        if len(mlf_movie.crew[crew_type].roles_by_uid) > 0
                    }

                    # Optimization: we only need to only iterate over each *unordered* crew pair once. For that we need groups to be ordered.
                    ordered_base_groups = list(groups)

                    # Optimization: 1-man crews are not interesting. Any intersection they have is either empty or equal to themselves.
                    # So we will sort by crew length, and get the first index where crews have a greater length than 1.
                    ordered_base_groups.sort(key=len)
                    start_multiple = next((i for i, group in enumerate(ordered_base_groups) if len(group) > 1), len(ordered_base_groups))

                    # Now we iterate over every unordered pair of crews that both have len > 1.
                    for i, g1 in enumerate(ordered_base_groups[start_multiple:]):

                        # We skip the pair of any crew with itself because we started off groups with all of those.
                        for g2 in ordered_base_groups[i + 1:]:
                            intersection = g1 & g2
                            len_intersection = len(intersection)

                            # Empty intersections are skipped.
                            # If the intersection is equal to g1 or g2, it's already in groups so we will not re-add it.
                            # If we did re-add it the set will block it anyway but doing it this way is more optimal.
                            # For extra optimization juice, we don't even compare the sets, comparing lengths is enough.
                            if len_intersection != 0 and len_intersection != len(g1) and len_intersection != len(g2):
                                groups.add(intersection)

                    # This is step 2 of the algorithm: finding each group's credits.
                    self._roles[ct_gm] = [
                        Role(
                            self,
                            sorted(
                                (mlf_movie.crew[crew_type].roles_by_uid[uid] for uid in group),
                                key=lambda role: ((name := mlf.people_by_uid[role.person_uid].name) is not None, name)
                            ),
                            mlf_movie, crew_type, group_mode
                        )
                        for mlf_movie in mlf.movies_by_uid.values()
                            for group in groups if group.issubset(mlf_movie.crew[crew_type].roles_by_uid)
                    ]

                case _:
                    raise RuntimeError(f"Unexpected {group_mode=}")

            _dbg.logger.info(f"Generated roles list, {ct_gm=}, {len(self._roles[ct_gm])=}")

        return self._roles[ct_gm]

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
