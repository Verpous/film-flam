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
import copy
import bisect

from . import _filter
from . import _mlf
from . import _ctx
from . import _fetch
from . import _attr
from . import _exc
from . import _dbg
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
    ANY                 = 'any'

    # NOTE: throughout this file, public functions which receive a GroupMode are all expected to replace DEFAULT with whatever the default is.
    # Private functions all assume they won't receive DEFAULT and don't need to handle it.
    @property
    def default_group_mode(self) -> GroupMode:
        # There is a way to add this as an attribute of each enum but it has... problems.
        # It's also tricky to define a ClassVar to an enum so we put it outside the class.
        return _default_group_modes[self]

    def __repr__(self) -> str:
        return str(self)

    @classmethod
    def iterate_except_any(cls) -> typing.Iterable[CrewType]:
        yield from _crew_types_except_any

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

def ct_gm_to_str(crew_type: CrewType, group_mode: GroupMode) -> str:
    return f'{crew_type}:{group_mode}'

_default_group_modes = {
    CrewType.CAST:              GroupMode.SEPARATE,
    CrewType.STUNTCAST:         GroupMode.SEPARATE,
    CrewType.DIRECTOR:          GroupMode.GROUP,
    CrewType.WRITER:            GroupMode.GROUP,
    CrewType.PRODUCER:          GroupMode.SEPARATE,
    CrewType.COMPOSER:          GroupMode.GROUP,
    CrewType.CINEMATOGRAPHER:   GroupMode.GROUP,
    CrewType.EDITOR:            GroupMode.GROUP,
    CrewType.ANY:               GroupMode.SEPARATE,
}

_crew_types_except_any = [ct for ct in CrewType if ct != CrewType.ANY]

class FindableType(enum.StrEnum):
    MOVIES              = 'movies'
    PEOPLE              = 'people'
    ROLES               = 'roles'

    def is_applicable_to(self, find: FindableType) -> bool:
        # Roles are compatible with everything because a role is associated with people and a movie.
        # DECISION: I considered allowing total cross applicability, by say applying movie attributes to a person
        # by returning the array of results for every movie the person is in. But that's ridiculous and confusing and we're not doing it.
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
    def _extract_internal(self, attribute: _attr.Attribute) -> _attr.AttributeValue:
        pass
        
    @abc.abstractmethod
    def _excrete(self, predicate: _filter.Predicate) -> bool:
        pass

    def extract(self, attribute: _attr.Attribute) -> _attr.AttributeValue:
        if not attribute.findable_type.is_applicable_to(self.type_):
            raise _exc.InputError(f"Attribute '{attribute.qualified_name}' is a {attribute.findable_type} attribute, so it is not found on {self.type_}.")

        return self._extract_internal(attribute)

    # __getitem__ for also encapsulating the attribute lookup, the ultimate quick & dirty way. extract() for more efficient and clean code.
    def __getitem__(self, attribute_name: str) -> _attr.AttributeValue:
        attr = self._movie_list.ctx.attributes.get(attribute_name, type_hint=self.type_)
        return self.extract(attr)

class Movie(Findable):
    def __init__(self, movie_list: MovieList, mlf_movie: _mlf.MLFMovie) -> None:
        super().__init__(movie_list)
        self._mlf_movie = mlf_movie
        self._associated_people_cache: dict[tuple[CrewType, GroupMode], list[People]] = {}

    @property
    def type_(self) -> FindableType:
        return FindableType.MOVIES

    @property
    def uid(self) -> str:
        return self._mlf_movie.uid

    @property
    def underlying_file_movie_readonly(self) -> _mlf.MLFMovie:
        return self._mlf_movie

    def _extract_internal(self, attribute: _attr.Attribute) -> _attr.AttributeValue:
        return attribute._extract_from_movie(self, self._mlf_movie) # type: ignore

    def _excrete(self, predicate: _filter.Predicate) -> bool:
        return predicate._excrete_from_movie(self, self._mlf_movie) # type: ignore

    def associated_people(self, crew_type: CrewType, group_mode: GroupMode) -> typing.Iterable[People]:
        if group_mode == GroupMode.DEFAULT:
            group_mode = crew_type.default_group_mode

        ct_gm = (crew_type, group_mode)
        
        if ct_gm not in self._associated_people_cache:
            # Must guarantee consistent ordering.
            self._associated_people_cache[ct_gm] = sorted(self._associated_people_no_cache(crew_type, group_mode), key=lambda people: people.uid)
        
        yield from self._associated_people_cache[ct_gm]

    def _associated_people_no_cache(self, crew_type: CrewType, group_mode: GroupMode) -> typing.Iterable[People]:
        ct_gm = (crew_type, group_mode)
        ml = self.movie_list

        match ct_gm:
            case (CrewType.ANY, GroupMode.SEPARATE):
                # Put all the uids in a set to deduplicate them.
                crew_uids_any = set(uid for mlf_crew in self._mlf_movie.crew.values() for uid in mlf_crew.roles_by_uid)

                for mlf_person_uid in crew_uids_any:
                    yield ml.get_people_by_uid(People.compose_uid([mlf_person_uid], crew_type, group_mode))
            case (_, GroupMode.SEPARATE):
                for mlf_role in self._mlf_movie.crew[crew_type].roles_by_uid.values():
                    yield ml.get_people_by_uid(People.compose_uid([mlf_role.person_uid], crew_type, group_mode))
            case (_, GroupMode.GROUP):
                # It's not optimal to go over all people just to find the ones in this movie but we have no better way right now.
                for people in ml.find_people(crew_type, group_mode):
                    if people.are_in_movie(self):
                        yield people
            case _:
                raise RuntimeError(f"Unexpected {ct_gm=}")

    def associated_roles(self, crew_type: CrewType, group_mode: GroupMode) -> typing.Iterable[Role]:
        ml = self.movie_list

        if group_mode == GroupMode.DEFAULT:
            group_mode = crew_type.default_group_mode

        # Since associated people are all guaranteed to be in the movie, they should each correspond to a Role object.
        # Guaranteed consisted ordering because associated_people() has consistent ordering.
        for people in self.associated_people(crew_type, group_mode):
            role_uid = Role.compose_uid(self, people)
            yield ml.get_role_by_uid(role_uid)

class PeopleUidParts(typing.NamedTuple):
    mlf_people_uids: typing.Iterable[str]
    crew_type: CrewType
    group_mode: GroupMode

class People(Findable):
    def __init__(self, movie_list: MovieList, mlf_people: typing.Iterable[_mlf.MLFPerson], crew_type: CrewType, group_mode: GroupMode) -> None:
        super().__init__(movie_list)

        # Keep people sorted by uid.
        self._mlf_people = sorted(mlf_people, key=lambda mlf_person: mlf_person.uid)
        self._crew_type = crew_type
        self._group_mode = group_mode
        self._uid = self.compose_uid((mlf_person.uid for mlf_person in self._mlf_people), crew_type, group_mode)
        self._associated_movies_cache: None | list[Movie] = None

    @property
    def type_(self) -> FindableType:
        return FindableType.PEOPLE

    @property
    def uid(self) -> str:
        return self._uid

    @property
    def crew_type(self) -> CrewType:
        return self._crew_type

    @property
    def group_mode(self) -> GroupMode:
        return self._group_mode

    @property
    def underlying_file_people_readonly(self) -> list[_mlf.MLFPerson]:
        return self._mlf_people
    
    def _extract_internal(self, attribute: _attr.Attribute) -> _attr.AttributeValue:
        return attribute._extract_from_people(self, self._mlf_people) # type: ignore

    def _excrete(self, predicate: _filter.Predicate) -> bool:
        return predicate._excrete_from_people(self, self._mlf_people) # type: ignore

    def associated_movies(self) -> typing.Iterable[Movie]:
        # Guaranteed consisted ordering because find() has consistent ordering.
        if self._associated_movies_cache is None:
            self._associated_movies_cache = [
                movie
                for movie in self.movie_list.find_movies()
                if self.are_in_movie(movie)
            ]

        yield from self._associated_movies_cache

    def associated_roles(self) -> typing.Iterable[Role]:
        ml = self.movie_list

        # Since associated people are all guaranteed to be in the movie, they should each correspond to a Role object.
        # Guaranteed consisted ordering because associated_movies() has consistent ordering.
        for movie in self.associated_movies():
            role_uid = Role.compose_uid(movie, self)
            yield ml.get_role_by_uid(role_uid)

    # Find the smallest group of people in another crew type who contain every person in this group.
    # I think by nature of our grouping algorithm, there is guaranteed to be either no such group, or exactly 1 unique group like this.
    # Assume our group is P1,P2 and in another crew type there's the groups P1,P2,P3 and P1,P2,P4. So then the grouping algorithm would've created P1,P2 as well.
    def minimal_superset_people_in_other_crew_type(self, crew_type: CrewType) -> People:
        # Optimization - same crew type, same people.
        if crew_type == self.crew_type:
            return self

        return self._minimal_superset_people_internal(self.movie_list, crew_type)

    # Find the smallest group of people in another movie list and optionally different crew type who contain every person in this group.
    def minimal_superset_people_in_other_list(self, other_list: MovieList, crew_type: None | CrewType = None) -> People:
        if crew_type is None:
            crew_type = self.crew_type

        return self._minimal_superset_people_internal(other_list, crew_type)

    def _minimal_superset_people_internal(self, movie_list: MovieList, crew_type: CrewType) -> People:
        # SEPARATE group mode, so it's much easier to check if this person is in another crew type.
        if self.group_mode == GroupMode.SEPARATE:
            uid = self.compose_uid([self._mlf_people[0].uid], crew_type, self.group_mode)
            return movie_list.get_people_by_uid(uid)

        # We'll try our luck at searching if this group appears exactly the same in another crew type.
        uid = self.compose_uid((mlf_person.uid for mlf_person in self._mlf_people), crew_type, self.group_mode)

        try:
            return movie_list.get_people_by_uid(uid)
        except _exc.InputError:
            pass

        # Now in the general case we must see if there's a strict superset in this other crew type.
        min_superset = None
        
        for people in movie_list.find_people(crew_type, self.group_mode):
            # We know we're searching for a group that has strictly more people than self.
            if len(people._mlf_people) <= len(self._mlf_people):
                continue

            # We also know we're searching for a group that has fewer people than the current smallest one we've found.
            if min_superset is not None and len(min_superset._mlf_people) <= len(people._mlf_people):
                continue

            # Efficient subset check assuming both are sorted by uid.
            i_self = 0
            i_other = 0
            
            while i_self < len(self._mlf_people) and i_other < len(people._mlf_people):
                # Seek ahead until you find the person in this other group.
                while i_other < len(people._mlf_people) and self._mlf_people[i_self] != people._mlf_people[i_other]:
                    i_other += 1

                # If found a match, move on to the next.
                if i_other < len(people._mlf_people):
                    i_other += 1
                    i_self += 1
            
            if i_self == len(self._mlf_people):
                return people

        if movie_list is self.movie_list:
            raise _exc.InputError(f'The People {self.uid} did not collaborate as the crew type {crew_type}.')

        raise _exc.InputError(f'The People {self.uid} did not collaborate as the crew type {crew_type} in the list {movie_list.abstract_listdef.pretty(movie_list.ctx)}.')

    def are_in_movie(self, movie: Movie) -> bool:
        # The hell with python one-liners using `any`, `all`, etc. This is more optimal and readable and modifiable.
        if self._crew_type == CrewType.ANY:
            for mlf_person in self._mlf_people:
                found = False

                for crew in movie._mlf_movie.crew.values():
                    if mlf_person.uid in crew.roles_by_uid:
                        found = True
                        break

                if not found:
                    return False
        else:
            for mlf_person in self._mlf_people:
                if not mlf_person.uid in movie._mlf_movie.crew[self._crew_type].roles_by_uid:
                    return False

        return True

    @classmethod
    def compose_uid(cls, mlf_people_uids: typing.Iterable[str], crew_type: CrewType, group_mode: GroupMode) -> str:
        if group_mode == GroupMode.DEFAULT:
            group_mode = crew_type.default_group_mode
            
        # I'll just assume that no MLF uid will have '::' in it.
        sorted_uids = sorted(mlf_people_uids)
        return f'{crew_type}::{group_mode}::{"::".join(sorted_uids)}'

    @classmethod
    def decompose_uid(cls, uid: str) -> PeopleUidParts:
        try:
            split = uid.split('::')
            crew_type = CrewType(split[0])
            group_mode = GroupMode(split[1])
            return PeopleUidParts(mlf_people_uids=split[2:], crew_type=crew_type, group_mode=group_mode)
        except Exception as e:
            raise _exc.InputError(f"Invalid People uid: '{uid}'") from e

class RoleUidParts(typing.NamedTuple):
    movie_uid: str
    people_uid: str

type MLFRolesDict = dict[str, dict[CrewType, _mlf.MLFRole]]

class Role(Findable):
    def __init__(self, movie_list: MovieList, movie: Movie, people: People) -> None:
        super().__init__(movie_list)
        self._movie = movie
        self._people = people
        self._uid = self.compose_uid(movie, people)

        # Get associated MLFRole objects based on the movie and people.
        crew_type = people.crew_type

        self._mlf_roles: MLFRolesDict

        if crew_type == CrewType.ANY:
            self._mlf_roles = {
                mlf_person.uid: {
                    ct: movie._mlf_movie.crew[ct].roles_by_uid[mlf_person.uid]
                    for ct in CrewType.iterate_except_any()
                    if mlf_person.uid in movie._mlf_movie.crew[ct].roles_by_uid
                }
                for mlf_person in people._mlf_people
            }
        else:
            self._mlf_roles = {
                mlf_person.uid: {crew_type: movie._mlf_movie.crew[crew_type].roles_by_uid[mlf_person.uid]}
                for mlf_person in people._mlf_people
            }

    @property
    def type_(self) -> FindableType:
        return FindableType.ROLES

    @property
    def uid(self) -> str:
        return self._uid

    @property
    def movie(self) -> Movie:
        return self._movie

    @property
    def people(self) -> People:
        return self._people

    @property
    def crew_type(self) -> CrewType:
        return self._people.crew_type

    @property
    def group_mode(self) -> GroupMode:
        return self._people.group_mode

    @property
    def underlying_file_roles_readonly(self) -> MLFRolesDict:
        return self._mlf_roles

    def _extract_internal(self, attribute: _attr.Attribute) -> _attr.AttributeValue:
        # Support optionally implementing _extract_from_role on any type of attribute, for custom behavior on how to extract them from roles.
        # It's best not to abuse this power but we will allow it.
        if attribute.findable_type == FindableType.ROLES or hasattr(attribute, '_extract_from_role'):
            return attribute._extract_from_role(self, self._mlf_roles, self._movie._mlf_movie, self._people._mlf_people) # type: ignore
        
        if attribute.findable_type == FindableType.MOVIES:
            return self.movie._extract_internal(attribute)
        
        if attribute.findable_type == FindableType.PEOPLE:
            return self.people._extract_internal(attribute)
        
        raise RuntimeError(f"Unexpected {attribute.findable_type=}")

    def _excrete(self, predicate: _filter.Predicate) -> bool:
        # Support optionally implementing _excrete_from_role on any type of predicate, for custom behavior on how to extract them from roles.
        # It's best not to abuse this power but we will allow it.
        if predicate.findable_type == FindableType.ROLES or hasattr(predicate, '_excrete_from_role'):
            return predicate._excrete_from_role(self, self._mlf_roles, self._movie._mlf_movie, self._people._mlf_people) # type: ignore
        
        if predicate.findable_type == FindableType.MOVIES:
            return self.movie._excrete(predicate)
        
        if predicate.findable_type == FindableType.PEOPLE:
            return self.people._excrete(predicate)
        
        raise RuntimeError(f"Unexpected {predicate.findable_type=}")

    @classmethod
    def compose_uid(cls, movie: Movie, people: People) -> str:
        return f'{movie.uid}::{people.uid}'

    @classmethod
    def decompose_uid(cls, uid: str) -> RoleUidParts:
        try:
            split = uid.split('::', maxsplit=1)
            return RoleUidParts(movie_uid=split[0], people_uid=split[1])
        except Exception as e:
            raise _exc.InputError(f"Invalid Role uid: '{uid}'") from e

class MovieList:
    def __init__(self, movie_list_file: _mlf.MovieListFile, ctx: _ctx.FlamContext) -> None:
        _dbg.logger.info(f"Creating movie list for '{movie_list_file.abstract_listdef}', "
            f"which has {len(movie_list_file.movies_by_uid)} movies, {len(movie_list_file.people_by_uid)} people")

        self._ctx = ctx
        self._movie_list_file = movie_list_file

        self._movies: None | dict[str, Movie] = None
        self._peoples: dict[tuple[CrewType, GroupMode], dict[str, People]] = {}
        self._roles: dict[tuple[CrewType, GroupMode], dict[str, Role]] = {}

    # I permit access to this and entrust users to only read from it because some attributes need it,
    # and I don't believe in going so crazy about the API being "clean" and bulletproof that I sacrifice its efficiency.
    # If you're implementing an attribute you should be allowed to peek "under the hood" more than a typical user anyway.
    @property
    def underlying_file_readonly(self) -> _mlf.MovieListFile:
        return self._movie_list_file

    @property
    def ctx(self) -> _ctx.FlamContext:
        return self._ctx

    @property
    def abstract_listdef(self) -> _ldef.CanonListdef:
        return self._movie_list_file.abstract_listdef

    @property
    def uid_family(self) -> str:
        return self._movie_list_file.uid_family

    # Don't default to CrewType.ANY, I would rather users be explicit.
    # I want to log when this function is called but that could flood the logs too much.
    def find(self, what: FindableType, crew_type: None | CrewType = None, group_mode: GroupMode = GroupMode.DEFAULT,
            filter: None | _filter.Filter = None) -> typing.Iterable[Findable]:
        if filter is not None and filter.findable_type != what:
            raise _exc.InputError(f"Requested to find {what} but filter is of type {filter.findable_type}.")

        # Typing is covariant and dict is not.
        # We assume findables is a dict with elements inserted in sorted by uid order.
        findables: typing.Mapping[str, Findable]
        
        match what:
            case FindableType.MOVIES:
                findables = self._generate_movies()
            case FindableType.PEOPLE:
                if crew_type is None:
                    raise _exc.InputError(f"Cannot find {what} without specifying the crew type.")
                
                if group_mode == GroupMode.DEFAULT:
                    group_mode = crew_type.default_group_mode

                findables = self._generate_peoples(crew_type, group_mode)
            case FindableType.ROLES:
                if crew_type is None:
                    raise _exc.InputError(f"Cannot find {what} without specifying the crew type.")

                if group_mode == GroupMode.DEFAULT:
                    group_mode = crew_type.default_group_mode

                findables = self._generate_roles(crew_type, group_mode)
            case _:
                raise RuntimeError(f"Unexpected {what=}")

        if filter is None or filter.is_empty:
            yield from findables.values()
        else:
            for f in findables.values():
                if filter.excrete(f):
                    yield f

    def find_movies(self, filter: None | _filter.Filter = None) -> typing.Iterable[Movie]:
        # The infrastructure we will need to write these functions without ignoring types is too much to bother.
        return typing.cast(typing.Iterable[Movie], self.find(FindableType.MOVIES, filter=filter))

    def find_people(self, crew_type: CrewType, group_mode: GroupMode = GroupMode.DEFAULT, filter: None | _filter.Filter = None) -> typing.Iterable[People]:
        return typing.cast(typing.Iterable[People], self.find(FindableType.PEOPLE, crew_type=crew_type, group_mode=group_mode, filter=filter))

    def find_roles(self, crew_type: CrewType, group_mode: GroupMode = GroupMode.DEFAULT, filter: None | _filter.Filter = None) -> typing.Iterable[Role]:
        return typing.cast(typing.Iterable[Role], self.find(FindableType.ROLES, crew_type=crew_type, group_mode=group_mode, filter=filter))

    def export(self, filter: _filter.Filter) -> _mlf.MovieListFile:
        _dbg.logger.info(f"Exporting '{self._movie_list_file.abstract_listdef}' with {filter=!s}")
        filtered_file = copy.deepcopy(self._movie_list_file)

        # Canonicalization is preserved because we haven't messed with anything that was sorted.
        filtered_file.movies_by_uid = {movie._mlf_movie.uid: movie._mlf_movie for movie in self.find_movies(filter)}
        _fetch._remove_unused_people(filtered_file)
        
        _dbg.logger.info(f"Resulting file has {len(filtered_file.movies_by_uid)} movies, {len(filtered_file.people_by_uid)} people")
        return filtered_file

    def get_movie_by_uid(self, uid: str) -> Movie:
        movies = self._generate_movies()
        
        try:
            return movies[uid]
        except KeyError as e:
            raise _exc.InputError(f"No movie with the uid: '{uid}'") from e

    def get_people_by_uid(self, uid: str) -> People:
        # Break down the uid to determine the ct_gm and know which list to search in.
        breakdown = People.decompose_uid(uid)
        peoples = self._generate_peoples(breakdown.crew_type, breakdown.group_mode)

        try:
            return peoples[uid]
        except KeyError as e:
            raise _exc.InputError(f"No people with the uid: '{uid}'") from e

    def get_role_by_uid(self, uid: str) -> Role:
        # Break down the uid to determine the ct_gm and know which list to search in.
        role_breakdown = Role.decompose_uid(uid)
        people_breakdown = People.decompose_uid(role_breakdown.people_uid)
        roles = self._generate_roles(people_breakdown.crew_type, people_breakdown.group_mode)

        try:
            return roles[uid]
        except KeyError as e:
            raise _exc.InputError(f"No role with the uid: '{uid}'") from e

    def get_by_uid(self, findable_type: FindableType, uid: str) -> Findable:
        match findable_type:
            case FindableType.MOVIES:
                return self.get_movie_by_uid(uid)
            case FindableType.PEOPLE:
                return self.get_people_by_uid(uid)
            case FindableType.ROLES:
                return self.get_role_by_uid(uid)
            case _:
                raise RuntimeError(f"Unexpected {findable_type=}")

    def _generate_movies(self) -> dict[str, Movie]:
        if self._movies is None:
            self._movies = self._findables_to_sorted_dict(Movie(self, mlf_movie) for mlf_movie in self._movie_list_file.movies_by_uid.values())
            _dbg.logger.info(f"Generated movie list, {len(self._movies)=}")

        return self._movies

    def _generate_peoples(self, crew_type: CrewType, group_mode: GroupMode) -> dict[str, People]:
        ct_gm = (crew_type, group_mode)

        if ct_gm not in self._peoples:
            self._peoples[ct_gm] = self._findables_to_sorted_dict(self._generate_peoples_no_cache(crew_type, group_mode))
            _dbg.logger.info(f"Generated people list, {ct_gm=}, {len(self._peoples[ct_gm])=}")

        return self._peoples[ct_gm]

    def _generate_peoples_no_cache(self, crew_type: CrewType, group_mode: GroupMode) -> typing.Iterable[People]:
        ct_gm = (crew_type, group_mode)

        match ct_gm:
            case (CrewType.ANY, GroupMode.SEPARATE):
                for mlf_person in self._movie_list_file.people_by_uid.values():
                    yield People(self, [mlf_person], crew_type, group_mode)
            case (_, GroupMode.SEPARATE):
                # Could be optimized if we cached associated movies of a person by crew type.
                # The way it's currently written will yield the same people multiple times if they are in multiple movies. That is deduplicated by _findables_to_sorted_dict.
                # For reasons I can't explain the profiler finds this implementation monumentally faster than iterating "for person for movie".
                for mlf_movie in self._movie_list_file.movies_by_uid.values():
                    for mlf_person_uid in mlf_movie.crew[crew_type].roles_by_uid:
                        yield People(self, [self._movie_list_file.people_by_uid[mlf_person_uid]], crew_type, group_mode)
            case (_, GroupMode.GROUP):
                yield from self._group_people(crew_type)
            case _:
                raise RuntimeError(f"Unexpected {ct_gm=}")

    def _group_people(self, crew_type: CrewType) -> typing.Iterable[People]:
        # High level, the algorithm is as follows:
        #
        # foreach movie:
        #     intersect movie's crew set with every other movie's
        #     if the intersection with a movie (including self) is not empty, add that intersection to a set of sets
        #
        # Later for constructing Role objects where you need to know the credits of each collaborating group:
        # 
        # foreach crew set in the set of sets we built:
        #     find all movies whose crew is a superset of this set
        #
        # In the end you have for every relevant person set, all movies that are accredited to it.
        # In reality the algorithm barely resembles this because of various optimizations.

        mlf = self._movie_list_file

        # groups will in the end include all relevant people groups, each as a frozenset. We know that at minimum, it should have every crew that any movie has.
        # This set also allows us to only iterate over every unique movie crew pair, instead of every movie pair.
        # We use frozenset because regular sets aren't hashable.
        if crew_type == CrewType.ANY:
            # If covering all crew types, we need to union the people who worked on the movie in any capacity.
            groups = {
                frozenset(uid for mlf_crew in mlf_movie.crew.values() for uid in mlf_crew.roles_by_uid)
                for mlf_movie in mlf.movies_by_uid.values()
            }
        else:
            groups = {
                frozenset(mlf_movie.crew[crew_type].roles_by_uid)
                for mlf_movie in mlf.movies_by_uid.values()
                if len(mlf_movie.crew[crew_type].roles_by_uid) > 0
            }

        # Some crews may have been empty. In that case they should all be equal to this empty set and we can easily remove it.
        groups.discard(frozenset())

        # Optimization: we only need to only iterate over each *unordered* crew pair once. For that we need groups to be ordered.
        ordered_base_groups = list(groups)

        # Optimization: 1-man crews are not interesting. Any intersection they have is either empty or equal to themselves.
        # So we will sort by crew length, and get the first index where crews have a greater length than 1.
        ordered_base_groups.sort(key=len)

        # If no elements in the list with len > 1, it returns len(ordered_base_groups), which is exactly what we want.
        start_multiple = bisect.bisect_right(ordered_base_groups, 1, key=len)

        # Now we iterate over every unordered pair of crews that both have len > 1.
        # NOTE: in the past I had it as part of this algorithm to remember each group's credits. I thought that when merging two groups, we can merge their credits too.
        # But in the end that proved to be incorrect. I can't entirely explain it but I think it's better to just not complicate things with that anymore.
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

        for group in groups:
            yield People(
                self,
                (mlf.people_by_uid[uid] for uid in group),
                crew_type, GroupMode.GROUP,
            )

    def _generate_roles(self, crew_type: CrewType, group_mode: GroupMode) -> dict[str, Role]:
        ct_gm = (crew_type, group_mode)

        if ct_gm not in self._roles:
            self._roles[ct_gm] = self._findables_to_sorted_dict(self._generate_roles_no_cache(crew_type, group_mode))
            _dbg.logger.info(f"Generated roles list, {ct_gm=}, {len(self._roles[ct_gm])=}")

        return self._roles[ct_gm]

    def _generate_roles_no_cache(self, crew_type: CrewType, group_mode: GroupMode) -> typing.Iterable[Role]:
        peoples = self._generate_peoples(crew_type, group_mode)

        for people in peoples.values():
            for movie in people.associated_movies():
                yield Role(self, movie, people)

    # We want to guarantee a consistent ordering on find(), and associated_X() functions because it spares attribute implementations from worrying about ordering on their end.
    # Python dictionaries guarantee to preserve the order keys were added so we can have both efficient lookups and ordering in one data structure if we build it right.
    @classmethod
    def _findables_to_sorted_dict[T: Findable](cls, findables: typing.Iterable[T]) -> dict[str, T]:
        return {f.uid: f for f in sorted(findables, key=lambda fi: fi.uid)}
