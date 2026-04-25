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
import bisect
import collections

from . import _filter
from . import _mlf
from . import _mlv
from . import _ctx
from . import _fetch
from . import _attr
from . import _exc
from . import _dbg
from . import _ldef

class GroupMode(enum.StrEnum):
    """
    Indicates whether people who collaborate together should be grouped into a single "person".
    For example, if grouping is enabled then the Coen brothers will be presented as a single entry when finding directors.

    """
    DEFAULT             = 'default'
    """Use whichever default makes sense for the crew type."""

    GROUP               = 'group'
    """Do try to group collaborators together."""

    SEPARATE            = 'separate'
    """Don't group - keep each person as a separate entry."""

    def __repr__(self) -> str:
        return str(self)

    @classmethod
    def iterate_except_default(cls) -> typing.Iterable[GroupMode]:
        """
        Iterate over all values except :py:attr:`DEFAULT`.
        """
        yield from _group_modes_except_default

class CrewType(enum.StrEnum):
    """
    A job on a movie set.
    """

    # No need to have docstrings for each member, it's obvious what they mean. We won't document the default group mod either.
    CAST                = 'cast'
    STUNTCAST           = 'stuntcast'
    DIRECTOR            = 'director'
    WRITER              = 'writer'
    PRODUCER            = 'producer'
    COMPOSER            = 'composer'
    CINEMATOGRAPHER     = 'cinematographer'
    EDITOR              = 'editor'
    ANY                 = 'any'
    """No crew type in particular, only care about if the person was in the movie in any capacity."""

    # NOTE: throughout this file, public functions which receive a GroupMode are all expected to replace DEFAULT with whatever the default is.
    # Private functions all assume they won't receive DEFAULT and don't need to handle it.
    @property
    def default_group_mode(self) -> GroupMode:
        """
        The group mode which makes the most sense for this crew type.
        """
        # There is a way to add this as an attribute of each enum but it has... problems.
        # It's also tricky to define a ClassVar to an enum so we put it outside the class.
        return _default_group_modes[self]

    def __repr__(self) -> str:
        return str(self)

    @classmethod
    def iterate_except_any(cls) -> typing.Iterable[CrewType]:
        """
        Iterate over all values except :py:attr:`ANY`.
        """
        yield from _crew_types_except_any

def parse_ct_gm(ct_gm_str: str) -> tuple[CrewType, GroupMode]:
    """
    Parse a CTGM, short for "crew type + group mode", and returns it as a tuple.
    
    CTGMs can be just the crew type or also the group mode with a colon delimiter. Ex: 'director:group', 'cast:separate', 'writer:default' or just 'writer'.

    :param ct_gm_str: the CTGM as a string.
    """
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
    """
    Inverse of :py:meth:`parse_ct_gm`.

    :param crew_type: the crew type.
    :param group_mode: the group mode.
    """
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
_group_modes_except_default = [gm for gm in GroupMode if gm != GroupMode.DEFAULT]

# We want to guarantee a consistent ordering on find(), and associated_X() functions because it spares attribute implementations from worrying about ordering on their end.
# Python dictionaries guarantee to preserve the order keys were added so we can have both efficient lookups and ordering in one data structure if we build it right.
# NOTE: cProfile thinks this function is very expensive but it's only because it uses an iterable so it counts the time of the generator that's yielding us all this stuff.
def _build_findables_dict[T: Findable](findables: typing.Iterable[T], assume_sorted: bool = False) -> dict[str, T]:
    return {f.uid: f for f in (findables if assume_sorted else sorted(findables, key=lambda fi: fi.uid))}

# Hate this function but we just have a lot of list comprehensions which can either use this, or an ugly cast, or ugly generators.
def _assert_not_none[T](value: None | T) -> T:
    assert value is not None
    return value

# Some terminology: a computation can be loaded, and it can be vaulted. These are not mutually exclusive!
# * Loaded means it's computed and cached in a volatile way in the MovieList or Movie/People/Role objects, ex: Movie._associated_people_cache.
# * Vaulted means it's computed and stored in the MovieListVault, so that if the user wants it in memory he can load it instead of compute it
# 
# Not all loaded computations are vaulted - we may not have vaulted it yet, or it may be a trivial result we'd rather just recompute next run.
# Not all vaulted computations are loaded - it may be vaulted from a previous run, and we have not found a need to load it in this run.
# There is no generic way to check if a computation is loaded, but there is a way to check if it's vaulted.
# The reason there is no generic way to check that is because it's not possible to do in a performant enough way.
# Each computation is expected to implement its own ad hoc way to check if it's loaded.
class _MLVComputation(abc.ABC):
    # This description is presented to users in the progressbar but it is also used to check if two computations are equal so it must be unique!
    @property
    @abc.abstractmethod
    def description(self) -> str:
        pass

    # Unconditionally does the math and assigns the results to ML objects, so in the end the computation is *loaded*.
    @abc.abstractmethod
    def compute(self, movie_list: MovieList) -> None:
        pass

    # Attempts to copy the results from vault to the ML objects, so in the end the computation is also *loaded*.
    # Returns false if the computation wasn't vaulted.
    @abc.abstractmethod
    def load_if_vaulted(self, movie_list: MovieList, vault: _mlv._MovieListVault) -> bool:
        pass

    # Assumes the computation is *loaded* and *not vaulted*, and copies the loaded results to the MLV, so in the end the computation is also *vaulted*.
    # For the record, I am fully aware that we could've ditched this function if we changed compute to store the result in the vault and not the ML objects.
    # However that would make us lose the ability to have computations that we exclude from vaulting, and will make it very hard if we ever want to disable vaulting.
    @abc.abstractmethod
    def vault(self, movie_list: MovieList, vault: _mlv._MovieListVault) -> None:
        pass

class _PeopleComputation(_MLVComputation):
    def __init__(self, crew_type: CrewType, group_mode: GroupMode):
        self._crew_type = crew_type
        self._group_mode = group_mode

    @property
    def description(self) -> str:
        return f'people - {ct_gm_to_str(self._crew_type, self._group_mode)}'

    def compute(self, movie_list: MovieList) -> None:
        ct_gm = (self._crew_type, self._group_mode)
        movie_list._peoples[ct_gm] = _build_findables_dict(self._generate_peoples_no_cache(movie_list))
        _dbg.logger.info(f"Computed people list for {ct_gm=}, {len(movie_list._peoples[ct_gm])=}")

    def load_if_vaulted(self, movie_list: MovieList, vault: _mlv._MovieListVault) -> bool:
        ct_gm = (self._crew_type, self._group_mode)

        for mlv_people in vault.peoples:
            if ct_gm != (mlv_people.crew_type, mlv_people.group_mode):
                continue
            
            mlf = movie_list._movie_list_file
            movie_list._peoples[ct_gm] = _build_findables_dict(
                (
                    People(
                        movie_list,
                        (mlf.people_by_uid[uid] for uid in group),
                        *ct_gm
                    )
                    for group in mlv_people.groups
                ),
                assume_sorted=True
            )

            _dbg.logger.info(f"Loaded people list from vault for {ct_gm=}, {len(movie_list._peoples[ct_gm])=}")
            return True

        return False

    def vault(self, movie_list: MovieList, vault: _mlv._MovieListVault) -> None:
        ct_gm = (self._crew_type, self._group_mode)

        groups = [
            [mlf_person.uid for mlf_person in people._mlf_people]
            for people in movie_list._peoples[ct_gm].values()
        ]

        mlv_people = _mlv._MLVPeoples(
            crew_type = self._crew_type,
            group_mode = self._group_mode,
            groups = groups,
        )

        vault.peoples.append(mlv_people)
        _dbg.logger.info(f"Vaulted people list for {ct_gm=}, {len(movie_list._peoples[ct_gm])=}")

    def _generate_peoples_no_cache(self, movie_list: MovieList) -> typing.Iterable[People]:
        ct_gm = (self._crew_type, self._group_mode)
        mlf = movie_list._movie_list_file

        match ct_gm:
            case (CrewType.ANY, GroupMode.SEPARATE):
                for mlf_person in mlf.people_by_uid.values():
                    yield People(movie_list, [mlf_person], *ct_gm)
            case (_, GroupMode.SEPARATE):
                # Could be optimized if we cached associated movies of a person by crew type and ran "for mlf_person for associated_movies",
                # however that posits a problem - for _AssocMoviesComputation is dependent on this computation.
                # We tried instead to implement this as "for mlf_person for movie if person did crew type in movie", but the profiler *really* didn't like that.
                # The way it's currently written will yield the same People multiple times if he is in multiple movies. That is deduplicated by _build_findables_dict.
                for mlf_movie in mlf.movies_by_uid.values():
                    for mlf_person_uid in mlf_movie.crew[self._crew_type].roles_by_uid:
                        yield People(movie_list, [mlf.people_by_uid[mlf_person_uid]], *ct_gm)
            case (_, GroupMode.GROUP):
                yield from self._group_people(movie_list)
            case _:
                raise RuntimeError(f"Unexpected {ct_gm=}")

    def _group_people(self, movie_list: MovieList) -> typing.Iterable[People]:
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

        mlf = movie_list._movie_list_file

        # groups will in the end include all relevant people groups, each as a frozenset. We know that at minimum, it should have every crew that any movie has.
        # This set also allows us to only iterate over every unique movie crew pair, instead of every movie pair.
        # We use frozenset because regular sets aren't hashable.
        if self._crew_type == CrewType.ANY:
            # If covering all crew types, we need to union the people who worked on the movie in any capacity.
            groups = {
                frozenset(uid for mlf_crew in mlf_movie.crew.values() for uid in mlf_crew.roles_by_uid)
                for mlf_movie in mlf.movies_by_uid.values()
            }
        else:
            groups = {
                frozenset(mlf_movie.crew[self._crew_type].roles_by_uid)
                for mlf_movie in mlf.movies_by_uid.values()
                if len(mlf_movie.crew[self._crew_type].roles_by_uid) > 0
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
                movie_list,
                (mlf.people_by_uid[uid] for uid in group),
                self._crew_type, GroupMode.GROUP,
            )

# We don't do small computations of like, a single movie's associated_people. This will compute every movie's associated_people. This is because:
# 1. There may be more efficient algorithms we can use if we compute for all movies at once.
# 2. After each computation we want to vault & write to disk. Doing a 1000 small computations and writing to disk after each one would be horrible.
class _AssocPeopleComputation(_MLVComputation):
    def __init__(self, crew_type: CrewType, group_mode: GroupMode):
        self._crew_type = crew_type
        self._group_mode = group_mode

    @property
    def description(self) -> str:
        # Short descriptions so they fit in the progress bar, even if it means they'll be a bit cryptic to users I think it's ok.
        return f'assoc people - {ct_gm_to_str(self._crew_type, self._group_mode)}'

    def compute(self, movie_list: MovieList) -> None:
        ct_gm = (self._crew_type, self._group_mode)

        for movie in movie_list.find_movies():
            # Must guarantee consistent ordering.
            movie._associated_people_cache[ct_gm] = sorted(self._associated_people_no_cache(movie), key=lambda people: people.uid)

        _dbg.logger.info(f"Computed associated people for {ct_gm=}")

    def load_if_vaulted(self, movie_list: MovieList, vault: _mlv._MovieListVault) -> bool:
        ct_gm = (self._crew_type, self._group_mode)

        for mlv_assoc_people in vault.assoc_peoples:
            if ct_gm != (mlv_assoc_people.crew_type, mlv_assoc_people.group_mode):
                continue
            
            # find_movies guarantees a consistent ordering, and it's important that we vault mlv_assoc_people.assoc_peoples with the same order.
            # assoc_people_uids should also be sorted, which is also important.
            for movie, assoc_people_uids in zip(movie_list.find_movies(), mlv_assoc_people.assoc_peoples, strict=True):
                movie._associated_people_cache[ct_gm] = [
                    _assert_not_none(movie_list.get_people_by_uid(uid, ct_gm_hint=ct_gm)) for uid in assoc_people_uids
                ]

            _dbg.logger.info(f"Loaded associated people from vault for {ct_gm=}")
            return True

        return False

    def vault(self, movie_list: MovieList, vault: _mlv._MovieListVault) -> None:
        ct_gm = (self._crew_type, self._group_mode)

        # The order of the movies and the order of the people for each movie is very important.
        assoc_peoples = [
            [people.uid for people in movie._associated_people_cache[ct_gm]]
            for movie in movie_list.find_movies()
        ]

        mlv_assoc_people = _mlv._MLVAssocPeoples(
            crew_type = self._crew_type,
            group_mode = self._group_mode,
            assoc_peoples = assoc_peoples,
        )

        vault.assoc_peoples.append(mlv_assoc_people)
        _dbg.logger.info(f"Vaulted associated people for {ct_gm=}")

    def _associated_people_no_cache(self, movie: Movie) -> typing.Iterable[People]:
        ct_gm = (self._crew_type, self._group_mode)
        ml = movie.movie_list

        match ct_gm:
            case (CrewType.ANY, GroupMode.SEPARATE):
                # Put all the uids in a set to deduplicate them.
                crew_uids_any = set(uid for mlf_crew in movie._mlf_movie.crew.values() for uid in mlf_crew.roles_by_uid)

                for mlf_person_uid in crew_uids_any:
                    people = ml.get_people_by_uid(People.compose_uid([mlf_person_uid], *ct_gm), ct_gm_hint=ct_gm)
                    assert people is not None
                    yield people
            case (_, GroupMode.SEPARATE):
                for mlf_role in movie._mlf_movie.crew[self._crew_type].roles_by_uid.values():
                    people = ml.get_people_by_uid(People.compose_uid([mlf_role.person_uid], *ct_gm), ct_gm_hint=ct_gm)
                    assert people is not None
                    yield people
            case (_, GroupMode.GROUP):
                # It's not optimal to go over all people just to find the ones in this movie but we have no better way right now.
                # We did our best to speed it up by optimizing are_in_movie. As a consequence, this whole computation is dependent on AssocMoviesComputation.
                for people in ml.find_people(*ct_gm):
                    if people.are_in_movie(movie):
                        yield people
            case _:
                raise RuntimeError(f"Unexpected {ct_gm=}")

class _AssocMoviesComputation(_MLVComputation):
    def __init__(self, crew_type: CrewType, group_mode: GroupMode):
        self._crew_type = crew_type
        self._group_mode = group_mode

    @property
    def description(self) -> str:
        return f'assoc movies - {ct_gm_to_str(self._crew_type, self._group_mode)}'

    def compute(self, movie_list: MovieList) -> None:
        ct_gm = (self._crew_type, self._group_mode)

        # First we'll build this dictionary where for each MLF person uid, you have a set of all the MLF movie uids that person was in.
        # In the past we had a different algorithm, to run foreach people foreach movie and ask "are these people in this movie". It was *significantly* slower.
        # With this algorithm, it runs so fast we've even made it a dependency of AssocPeopleComputation, and we use this result to speed that other computation up.
        assoc_movies = collections.defaultdict(set)

        if self._crew_type == CrewType.ANY:
            relevant_crew_types = list(CrewType.iterate_except_any())
        else:
            relevant_crew_types = [self._crew_type]

        for mlf_movie in movie_list.underlying_file_readonly.movies_by_uid.values():
            for ct in relevant_crew_types:
                for mlf_person_uid in mlf_movie.crew[ct].roles_by_uid:
                    assoc_movies[mlf_person_uid].add(mlf_movie.uid)

        # Now we have assoc_movies built we'll go over each People object and set its associated movies using this helper data structure we built.
        for people in movie_list.find_people(*ct_gm):
            mlf_people = people.underlying_file_people_readonly

            # The GroupMode.SEPARATE case (or in GROUP case when the group has only 1 dude) is easy since the associated movies is exactly what we built in assoc_movies.
            if len(mlf_people) == 1:
                assoc_movies_all_group = assoc_movies[people.underlying_file_people_readonly[0].uid]
            else:
                # In the GROUP case we need to actually intersect the associated movies of all the people in the group. For that we need to start with a copy of the set.
                assoc_movies_all_group = set(assoc_movies[people.underlying_file_people_readonly[0].uid])
                
                for mlf_person in people.underlying_file_people_readonly[1:]:
                    assoc_movies_all_group.intersection_update(assoc_movies[mlf_person.uid])

            # This line is kind of a hack, we rely on the trick that for movies the MLF uid is the same as the ML uid.
            people._associated_movies_cache = _build_findables_dict(
                _assert_not_none(movie_list.get_movie_by_uid(movie_uid)) for movie_uid in assoc_movies_all_group
            )

        _dbg.logger.info(f"Computed associated movies for {ct_gm=}")

    def load_if_vaulted(self, movie_list: MovieList, vault: _mlv._MovieListVault) -> bool:
        ct_gm = (self._crew_type, self._group_mode)

        for mlv_assoc_movie in vault.assoc_movies:
            if ct_gm != (mlv_assoc_movie.crew_type, mlv_assoc_movie.group_mode):
                continue
            
            # find_people guarantees a consistent ordering, and it's important that we vault mlv_assoc_movie.assoc_movies with the same order.
            # assoc_movie_uids should also be sorted, which is also important.
            for people, assoc_movie_uids in zip(movie_list.find_people(*ct_gm), mlv_assoc_movie.assoc_movies, strict=True):
                people._associated_movies_cache = _build_findables_dict(
                    (_assert_not_none(movie_list.get_movie_by_uid(uid)) for uid in assoc_movie_uids),
                    assume_sorted=True
                )

            _dbg.logger.info(f"Loaded associated movies from vault for {ct_gm=}")
            return True

        return False

    def vault(self, movie_list: MovieList, vault: _mlv._MovieListVault) -> None:
        ct_gm = (self._crew_type, self._group_mode)

        # The order of the people and the order of the movies for each people is very important.
        assoc_movies = [
            list(_assert_not_none(people._associated_movies_cache).keys())
            for people in movie_list.find_people(*ct_gm)
        ]

        mlv_assoc_movie = _mlv._MLVAssocMovies(
            crew_type = self._crew_type,
            group_mode = self._group_mode,
            assoc_movies = assoc_movies,
        )

        vault.assoc_movies.append(mlv_assoc_movie)
        _dbg.logger.info(f"Vaulted associated movies for {ct_gm=}")

class _MinSupersetPeopleComputation(_MLVComputation):
    def __init__(self, self_crew_type: CrewType, other_crew_type: CrewType, group_mode: GroupMode):
        self._self_crew_type = self_crew_type
        self._other_crew_type = other_crew_type
        self._group_mode = group_mode

    @property
    def description(self) -> str:
        # Despite the short description it's still too long sometimes, but it's good enough..
        return f'minsupers - {ct_gm_to_str(self._self_crew_type, self._group_mode)}->{self._other_crew_type}'

    def compute(self, movie_list: MovieList) -> None:
        self_ct_gm = (self._self_crew_type, self._group_mode)

        for people in movie_list.find_people(*self_ct_gm):
            people._minimal_superset_people_cache[self._other_crew_type] = people._minimal_superset_people_internal(movie_list, self._other_crew_type)

        _dbg.logger.info(f"Computed minimal superset people for {self_ct_gm=}, {self._other_crew_type=}")

    def load_if_vaulted(self, movie_list: MovieList, vault: _mlv._MovieListVault) -> bool:
        self_ct_gm = (self._self_crew_type, self._group_mode)
        other_ct_gm = (self._other_crew_type, self._group_mode)

        for mlv_minsuper in vault.minsupers:
            if self_ct_gm != (mlv_minsuper.self_crew_type, mlv_minsuper.group_mode) or self._other_crew_type != mlv_minsuper.other_crew_type:
                continue
            
            # find_people guarantees a consistent ordering, and it's important that we vault mlv_minsuper.minsupers with the same order.
            for people, minsuper_uid in zip(movie_list.find_people(*self_ct_gm), mlv_minsuper.minsupers, strict=True):
                other_people = movie_list.get_people_by_uid(minsuper_uid, ct_gm_hint=other_ct_gm) if minsuper_uid is not None else None
                people._minimal_superset_people_cache[self._other_crew_type] = other_people

            _dbg.logger.info(f"Loaded minimal superset people from vault for {self_ct_gm=}, {self._other_crew_type=}")
            return True

        return False

    def vault(self, movie_list: MovieList, vault: _mlv._MovieListVault) -> None:
        self_ct_gm = (self._self_crew_type, self._group_mode)

        # The order of the people is very important.
        minsupers = []

        for people in movie_list.find_people(*self_ct_gm):
            minsuper = people._minimal_superset_people_cache[self._other_crew_type]
            minsupers.append(minsuper.uid if minsuper is not None else None)

        mlv_minsuper = _mlv._MLVMinSupersets(
            self_crew_type = self._self_crew_type,
            other_crew_type = self._other_crew_type,
            group_mode = self._group_mode,
            minsupers = minsupers,
        )

        vault.minsupers.append(mlv_minsuper)
        _dbg.logger.info(f"Vaulted minimal superset people for {self_ct_gm=}, {self._other_crew_type=}")

class FindableType(enum.StrEnum):
    """
    The type of an object which can be found in a movie list.
    """
    MOVIES              = 'movies'
    """Each object represents a single movie from the list."""

    PEOPLE              = 'people'
    """Each object may represent more than one person from the list, if grouping is enabled. They can also be limited to a specific crew type and group mode."""

    ROLES               = 'roles'
    """Each object represents an appearance of a person (or several grouped people) in a specific film in some specific capacity.
    Think "Cristoph Waltz as a castmember in Inglorious Basterds".
    
    So when searching for roles, you will see an entry per person per movie."""

    def is_applicable_to(self, find: FindableType) -> bool:
        """
        True if attributes of this findable type can be extracted from objects of type ``find``.

        Movie objects only support movie attributes.
        
        People objects only support people attributes.
        
        Roles are a combination of a movie and a people, so they support all attribute types.
        
        :param find: the type of the object you would try to extract an attribute from.
        """
        # Roles are compatible with everything because a role is associated with people and a movie.
        # DECISION: I considered allowing total cross applicability, by say applying movie attributes to a person
        # by returning the array of results for every movie the person is in. But that's ridiculous and confusing and we're not doing it.
        return find == self.ROLES or self == find

    def __repr__(self) -> str:
        return str(self)

class Findable(abc.ABC):
    """
    Base class for "findables"; objects which can be found in a movie list.
    """
    __no_init_doc__ = True
    
    def __init__(self, movie_list: MovieList) -> None:
        self._movie_list = movie_list

    @property
    def movie_list(self) -> MovieList:
        """
        The list this object came from.
        """
        return self._movie_list

    @property
    @abc.abstractmethod
    def type_(self) -> FindableType:
        """
        The type of this object.
        """

    @property
    @abc.abstractmethod
    def uid(self) -> str:
        """
        A unique string identifying this object. It's unique only per movie list.
        """

    @abc.abstractmethod
    def _extract_internal(self, attribute: _attr.Attribute) -> _attr.AttributeValue:
        pass
        
    @abc.abstractmethod
    def _excrete(self, predicate: _filter.Predicate) -> bool:
        pass

    def extract(self, attribute: _attr.Attribute) -> _attr.AttributeValue:
        """
        Get the value of an attribute which is applicable to this object. See :py:meth:`FindableType.is_applicable_to`.

        :param attribute: the attribute whose value you are interested in.
        """
        if not attribute.findable_type.is_applicable_to(self.type_):
            raise _exc.InputError(f"Attribute '{attribute.qualified_name}' is a {attribute.findable_type} attribute, so it is not found on {self.type_}.")

        return self._extract_internal(attribute)

    # __getitem__ for also encapsulating the attribute lookup, the ultimate quick & dirty way. extract() for more efficient and clean code.
    def __getitem__(self, attribute_name: str) -> _attr.AttributeValue:
        """
        Same as :py:meth:`extract`, but resolves the attribute from its name.

        :param attribute_name: the name of the attribute. It does not have to be a qualified name.
        """
        attr = self._movie_list.ctx.attributes.get(attribute_name, type_hint=self.type_)
        return self.extract(attr)

class Movie(Findable):
    """
    Represents a movie from the list.
    """
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
        """
        Serializable object we use to store all the movie's data to disk. It can technically be modified, but you shouldn't do that.

        NOTE: this is mostly an internal API; you might need it when implementing a custom extension.
        For typical use cases, you should use attributes to read the movie's data instead.
        """
        return self._mlf_movie

    def _extract_internal(self, attribute: _attr.Attribute) -> _attr.AttributeValue:
        return attribute._extract_from_movie(self, self._mlf_movie) # type: ignore

    def _excrete(self, predicate: _filter.Predicate) -> bool:
        return predicate._excrete_from_movie(self, self._mlf_movie) # type: ignore

    def associated_people(self, crew_type: CrewType, group_mode: GroupMode) -> typing.Iterable[People]:
        """
        Iterate over all people who were in this movie in a specific capacity. The order of iteration is guaranteed to be consistent.

        :param crew_type: only find people who performed this specific job on the movie
        :param group_mode: indicates if collaborators should be grouped together
        """
        if group_mode == GroupMode.DEFAULT:
            group_mode = crew_type.default_group_mode

        ct_gm = (crew_type, group_mode)
        
        if ct_gm not in self._associated_people_cache:
            # NOTE: we encounter the need to compute this from a specific Movie instance, but the computation will actually compute it *for every* Movie with this CTGM.
            # Only vault in case of GROUP because otherwise it's cheap to recompute.
            computation = _AssocPeopleComputation(crew_type, group_mode)
            self.movie_list._compute_or_load(computation, should_vault=(group_mode == GroupMode.GROUP))
            assert ct_gm in self._associated_people_cache
        
        yield from self._associated_people_cache[ct_gm]

    def associated_roles(self, crew_type: CrewType, group_mode: GroupMode) -> typing.Iterable[Role]:
        """
        Same as :py:meth:`associated_people`, but returns them as :py:class:`Role` objects where the movie is this movie.
        """
        ml = self.movie_list

        if group_mode == GroupMode.DEFAULT:
            group_mode = crew_type.default_group_mode

        # Since associated people are all guaranteed to be in the movie, they should each correspond to a Role object.
        # Guaranteed consisted ordering because associated_people() has consistent ordering.
        for people in self.associated_people(crew_type, group_mode):
            role_uid = Role.compose_uid(self, people)
            role = ml.get_role_by_uid(role_uid, ct_gm_hint=(people.crew_type, people.group_mode))
            assert role is not None
            yield role

class PeopleUidParts(typing.NamedTuple):
    """
    The parts which make up a People UID. Returned by :py:meth:`People.decompose_uid`.
    """
    mlf_people_uids: typing.Iterable[str]
    """"""
    crew_type: CrewType
    """"""
    group_mode: GroupMode
    """"""

class People(Findable):
    """
    Represents a person in their capacity as a specific crew type, or several collaborating people if grouping is enabled.
    """
    def __init__(self, movie_list: MovieList, mlf_people: typing.Iterable[_mlf.MLFPerson], crew_type: CrewType, group_mode: GroupMode) -> None:
        super().__init__(movie_list)

        # Keep people sorted by uid.
        self._mlf_people = sorted(mlf_people, key=lambda mlf_person: mlf_person.uid)
        self._crew_type = crew_type
        self._group_mode = group_mode
        self._uid = self.compose_uid((mlf_person.uid for mlf_person in self._mlf_people), crew_type, group_mode)
        self._associated_movies_cache: None | dict[str, Movie] = None
        self._minimal_superset_people_cache: dict[CrewType, None | People] = {}

    @property
    def type_(self) -> FindableType:
        return FindableType.PEOPLE

    @property
    def uid(self) -> str:
        return self._uid

    @property
    def crew_type(self) -> CrewType:
        """
        The job these people perform in movies.
        """
        return self._crew_type

    @property
    def group_mode(self) -> GroupMode:
        """
        Whether these people were searched with grouping enabled.
        """
        return self._group_mode

    @property
    def underlying_file_people_readonly(self) -> list[_mlf.MLFPerson]:
        """
        List of serializable objects we use to store each person's data to disk, sorted in a consistent order. It can technically be modified, but you shouldn't do that.

        NOTE: this is mostly an internal API; you might need it when implementing a custom extension.
        For typical use cases, you should use attributes to read the people's data instead.
        """
        return self._mlf_people
    
    def _extract_internal(self, attribute: _attr.Attribute) -> _attr.AttributeValue:
        return attribute._extract_from_people(self, self._mlf_people) # type: ignore

    def _excrete(self, predicate: _filter.Predicate) -> bool:
        return predicate._excrete_from_people(self, self._mlf_people) # type: ignore

    def associated_movies(self) -> typing.Iterable[Movie]:
        """
        Iterate over movies these people were in as this crew type. The order of iteration is guaranteed to be consistent.

        Note that in the case of several grouped people, only movies that they **were all in together** will be returned.
        """
        # Guaranteed consisted ordering because find() has consistent ordering.
        if self._associated_movies_cache is None:
            # NOTE: we encounter the need to compute this from a specific People instance, but the computation will actually compute it *for every* People with this CTGM.
            computation = _AssocMoviesComputation(self.crew_type, self.group_mode)
            self.movie_list._compute_or_load(computation)
            assert self._associated_movies_cache is not None

        yield from self._associated_movies_cache.values()

    def associated_roles(self) -> typing.Iterable[Role]:
        """
        Same as :py:meth:`associated_movies`, but returns them as :py:class:`Role` objects where the people are these people.
        """
        ml = self.movie_list

        # Since associated people are all guaranteed to be in the movie, they should each correspond to a Role object.
        # Guaranteed consisted ordering because associated_movies() has consistent ordering.
        for movie in self.associated_movies():
            role_uid = Role.compose_uid(movie, self)
            role = ml.get_role_by_uid(role_uid, ct_gm_hint=(self.crew_type, self.group_mode))
            assert role is not None
            yield role

    # I think by nature of our grouping algorithm, there is guaranteed to be either no min superset, or exactly 1 unique min superset like this.
    # Assume our group is P1,P2 and in another crew type there's the groups P1,P2,P3 and P1,P2,P4. So then the grouping algorithm would've created P1,P2 as well.
    def minimal_superset_people_in_other_crew_type(self, crew_type: CrewType) -> None | People:
        """
        Returns the smallest group of people in another crew type who contain every person in this group, or ``None`` if there is no such group.

        :param crew_type: which crew type to search for these people in.
        """
        # Optimization - same crew type, same people.
        if crew_type == self.crew_type:
            return self

        if crew_type not in self._minimal_superset_people_cache:
            # Only vault in case of GROUP because otherwise it's cheap to recompute.
            computation = _MinSupersetPeopleComputation(self.crew_type, crew_type, self.group_mode)
            self.movie_list._compute_or_load(computation, should_vault=(self.group_mode == GroupMode.GROUP))
            assert crew_type in self._minimal_superset_people_cache

        return self._minimal_superset_people_cache[crew_type]

    def minimal_superset_people_in_other_list(self, other_list: MovieList, crew_type: None | CrewType = None) -> None | People:
        """
        Returns the smallest group of people in another movie list and optionally different crew type who contain every person in this group, or ``None`` if there is no such group.

        :param other_list: which movie list to search for these people in.
        :param crew_type: which crew type to search for these people in. By default searches in the same crew type as these people.
        """
        if crew_type is None:
            crew_type = self.crew_type

        # No vaulting for the in_other_list case because that's just crazy.
        return self._minimal_superset_people_internal(other_list, crew_type)

    # Returns None when it fails instead of raising an exception because this can happen a lot and raising a log each time is expensive.
    def _minimal_superset_people_internal(self, movie_list: MovieList, crew_type: CrewType) -> None | People:
        ct_gm = (crew_type, self.group_mode)

        # SEPARATE group mode, so it's much easier to check if this person is in another crew type.
        if self.group_mode == GroupMode.SEPARATE:
            # If it's the same crew type too then we really don't have to compose a uid, we already know it.
            uid = self.compose_uid([self._mlf_people[0].uid], crew_type, self.group_mode) if crew_type != self.crew_type else self.uid
            return movie_list.get_people_by_uid(uid, ct_gm_hint=ct_gm)

        # We'll try our luck at searching if this group appears exactly the same in another crew type.
        # If it's the same crew type too then we really don't have to compose a uid, we already know it.
        uid = self.compose_uid((mlf_person.uid for mlf_person in self._mlf_people), crew_type, self.group_mode) if crew_type != self.crew_type else self.uid
        minsuper = movie_list.get_people_by_uid(uid, ct_gm_hint=ct_gm)

        if minsuper is not None:
            return minsuper

        # Now in the general case we must see if there's a strict superset in this other crew type.
        for people in movie_list.find_people(crew_type, self.group_mode):
            # We know we're searching for a group that has strictly more people than self.
            if len(people._mlf_people) <= len(self._mlf_people):
                continue

            # We also know we're searching for a group that has fewer people than the current smallest one we've found.
            if minsuper is not None and len(minsuper._mlf_people) <= len(people._mlf_people):
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
            
            # If we broke out of the above loop having reached the end of self._mlf_people then we found a match for each person there and people is a superset.
            if i_self == len(self._mlf_people):
                # Optimization: we know that there is no exactly equal set, only a strict superset.
                # So if a superset of just 1 additional person exists, it must be the minimal superset and we can return it.
                if len(people._mlf_people) <= len(self._mlf_people) + 1:
                    return people

                # The general case where we want to remember the minimum so far and keep searching for more minimal supersets.
                minsuper = people

        return minsuper

    def are_in_movie(self, movie: Movie) -> bool:
        """
        Check if these people were in a movie as their crew type.

        :param movie: the movie to check.
        """
        # Naively checking if these people are in the movie by inspecting the MLF sounds like a fast algorithm,
        # but we call this function so many times it was actually a major slowdown. So we've made _associated_movies_cache a dict and use it instead.
        if self._associated_movies_cache is None:
            computation = _AssocMoviesComputation(self.crew_type, self.group_mode)
            self.movie_list._compute_or_load(computation)
            assert self._associated_movies_cache is not None

        return movie.uid in self._associated_movies_cache

    @classmethod
    def compose_uid(cls, mlf_people_uids: typing.Iterable[str], crew_type: CrewType, group_mode: GroupMode) -> str:
        """
        Compose a people UID which can be used to :py:meth:`MovieList.get_people_by_uid`.

        :param mlf_people_uids: the UID of each person in the source that the movie list was fetched from.
        :param crew_type: the people's crew type.
        :param group_mode: the people's group mode.
        """
        if group_mode == GroupMode.DEFAULT:
            group_mode = crew_type.default_group_mode
            
        # I'll just assume that no MLF uid will have '::' in it.
        sorted_uids = sorted(mlf_people_uids)
        return f'{crew_type}::{group_mode}::{"::".join(sorted_uids)}'

    @classmethod
    def decompose_uid(cls, uid: str) -> PeopleUidParts:
        """
        Inverse of :py:meth:`compose_uid`.
        """
        try:
            split = uid.split('::')
            crew_type = CrewType(split[0])
            group_mode = GroupMode(split[1])
            return PeopleUidParts(mlf_people_uids=split[2:], crew_type=crew_type, group_mode=group_mode)
        except Exception as e:
            raise _exc.InputError(f"Invalid People uid: '{uid}'") from e

class RoleUidParts(typing.NamedTuple):
    """
    The parts which make up a Role UID. Returned by :py:meth:`Role.decompose_uid`.
    """

    # Empty docs because they aren't needed but if it wasn't empty it would be inherited from NamedTuple.
    movie_uid: str
    """"""
    people_uid: str
    """"""

type MLFRolesDict = dict[str, dict[CrewType, _mlf.MLFRole]]
"""
Return type of :py:meth:`Role.underlying_file_roles_readonly`.
"""

class Role(Findable):
    """
    Represents an appearance of a person (or several grouped people) in a specific film in some specific capacity. Think "Cristoph Waltz as a castmember in Inglorious Basterds".
    """
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
        """
        The movie this role was in.
        """
        return self._movie

    @property
    def people(self) -> People:
        """
        The people who performed this role.
        """
        return self._people

    @property
    def crew_type(self) -> CrewType:
        """
        The job these people performed in this movie.
        """
        return self._people.crew_type

    @property
    def group_mode(self) -> GroupMode:
        """
        Whether these people were grouped by collaborators.
        """
        return self._people.group_mode

    @property
    def underlying_file_roles_readonly(self) -> MLFRolesDict:
        """
        Dictionary of serializable objects we use to store each role's data to disk. It can technically be modified, but you shouldn't do that.

        The data structure maps the "MLF" UID of people in the group (i.e., the UID of a person in the fetch source) and the crew type to the object with the role data.

        If :py:attr:`crew_type` isn't :py:attr:`CrewType.ANY`, then that'll be the only crew type in the dictionary.
        Otherwise, the dictionary will have every crew type the person occupied.

        .. code-block:: python
            
            # mlf_person is a person's underlying file object, and crew_type is the crew type he was in in this role.
            mlf_role = roles_dict[mlf_person.uid][crew_type]
            print(mlf_role.characters)

        NOTE: this is mostly an internal API; you might need it when implementing a custom extension. For typical use cases, you should use attributes to read the role's data instead.
        """
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
        """
        Compose a role UID which can be used to :py:meth:`MovieList.get_role_by_uid`.

        :param movie: the movie the role was in.
        :param people: the people in the role.
        """
        return f'{movie.uid}::{people.uid}'

    @classmethod
    def decompose_uid(cls, uid: str) -> RoleUidParts:
        """
        Inverse of :py:meth:`compose_uid`.
        """
        try:
            split = uid.split('::', maxsplit=1)
            return RoleUidParts(movie_uid=split[0], people_uid=split[1])
        except Exception as e:
            raise _exc.InputError(f"Invalid Role uid: '{uid}'") from e

class MovieList:
    """
    Represents a movie list with functions to inspect the objects in the list.
    """
    __no_init_doc__ = True

    def __init__(self, movie_list_file: _mlf.MovieListFile, ctx: _ctx.FlamContext) -> None:
        _dbg.logger.info(f"Creating movie list for '{movie_list_file.abstract_listdef}', "
            f"which has {len(movie_list_file.movies_by_uid)} movies, {len(movie_list_file.people_by_uid)} people")

        self._ctx = ctx
        self._movie_list_file = movie_list_file

        # Important to get the MLV only after the MLF is loaded.
        vault, gen_mtime = ctx._get_mlv(self._movie_list_file.abstract_listdef)
        self._vault = vault
        self._vault_gen_mtime = gen_mtime

        self._movies: None | dict[str, Movie] = None
        self._peoples: dict[tuple[CrewType, GroupMode], dict[str, People]] = {}
        self._roles: dict[tuple[CrewType, GroupMode], dict[str, Role]] = {}

    # I permit access to this and entrust users to only read from it because some attributes need it,
    # and I don't believe in going so crazy about the API being "clean" and bulletproof that I sacrifice its efficiency.
    # If you're implementing an attribute you should be allowed to peek "under the hood" more than a typical user anyway.
    @property
    def underlying_file_readonly(self) -> _mlf.MovieListFile:
        """
        Serializable object we use to store all the list's data to disk. It can technically be modified, but you shouldn't do that.

        NOTE: this is mostly an internal API; you might need it when implementing a custom extension.
        For typical use cases, you should use :py:meth:`find` to read the list's data instead.
        """
        return self._movie_list_file

    @property
    def ctx(self) -> _ctx.FlamContext:
        """
        The context used to load this list.
        """
        return self._ctx

    @property
    def abstract_listdef(self) -> _ldef.CanonListdef:
        """
        Listdef which describes how to get this list.
        """
        return self._movie_list_file.abstract_listdef

    @property
    def uid_family(self) -> str:
        """
        The UID family used to fetch this list or all lists compositing it.
        I.e., if you have multiple ways to fetch data from IMDb, they would all have the same family and be compatible with one another for compositing.
        """
        return self._movie_list_file.uid_family

    # Don't default to CrewType.ANY, I would rather users be explicit.
    # I want to log when this function is called but that could flood the logs too much.
    def find(self, what: FindableType, crew_type: None | CrewType = None, group_mode: GroupMode = GroupMode.DEFAULT,
            filter: None | _filter.Filter = None) -> typing.Iterable[Findable]:
        """
        Iterate over objects in the list. They're guaranteed to be returned in a consistent order every time.

        :param what: which objects to find.
        :param crew_type: limit the search to a crew type. This has no meaning when finding :py:attr:`FindableType.MOVIES`, but is required for :py:attr:`FindableType.PEOPLE` or :py:attr:`FindableType.ROLES`.
        :param group_mode: specify whether to group collaborators. This has no meaning when finding :py:attr:`FindableType.MOVIES`, and is optional for the rest.
        :param filter: skip objects which don't pass this filter. It must have the same findable type as ``what``.
        """
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
        """
        Wrapper for :py:meth:`find` when searching for :py:attr:`FindableType.MOVIES`.
        """
        # The infrastructure we will need to write these functions without ignoring types is too much to bother.
        return typing.cast(typing.Iterable[Movie], self.find(FindableType.MOVIES, filter=filter))

    def find_people(self, crew_type: CrewType, group_mode: GroupMode = GroupMode.DEFAULT, filter: None | _filter.Filter = None) -> typing.Iterable[People]:
        """
        Wrapper for :py:meth:`find` when searching for :py:attr:`FindableType.PEOPLE`.
        """
        return typing.cast(typing.Iterable[People], self.find(FindableType.PEOPLE, crew_type=crew_type, group_mode=group_mode, filter=filter))

    def find_roles(self, crew_type: CrewType, group_mode: GroupMode = GroupMode.DEFAULT, filter: None | _filter.Filter = None) -> typing.Iterable[Role]:
        """
        Wrapper for :py:meth:`find` when searching for :py:attr:`FindableType.ROLES`.
        """
        return typing.cast(typing.Iterable[Role], self.find(FindableType.ROLES, crew_type=crew_type, group_mode=group_mode, filter=filter))

    def _export(self, filter: _filter.Filter) -> _mlf.MovieListFile:
        _dbg.logger.info(f"Exporting '{self._movie_list_file.abstract_listdef}' with {filter=!s}")
        filtered_file = self._movie_list_file.deepcopy()

        # Canonicalization is preserved because we haven't messed with anything that was sorted.
        filtered_file.movies_by_uid = {movie._mlf_movie.uid: movie._mlf_movie for movie in self.find_movies(filter)}
        _fetch._remove_unused_people(filtered_file)
        
        _dbg.logger.info(f"Resulting file has {len(filtered_file.movies_by_uid)} movies, {len(filtered_file.people_by_uid)} people")
        return filtered_file

    def get_by_uid(self, findable_type: FindableType, uid: str) -> None | Findable:
        """
        Get an object by its UID, or ``None`` if it doesn't exist.

        :param findable_type: the type of object to get.
        :param uid: the object's UID.
        """
        match findable_type:
            case FindableType.MOVIES:
                return self.get_movie_by_uid(uid)
            case FindableType.PEOPLE:
                return self.get_people_by_uid(uid)
            case FindableType.ROLES:
                return self.get_role_by_uid(uid)
            case _:
                raise RuntimeError(f"Unexpected {findable_type=}")

    def get_movie_by_uid(self, uid: str) -> None | Movie:
        """
        Wrapper for :py:meth:`get_by_uid` when searching for :py:attr:`FindableType.MOVIES`.
        """
        # These getters return None instead of raising an exception because FlamErrors create a log,
        # and it's too expensive for the amount of times we expect this to be called and fail.
        movies = self._generate_movies()
        return movies.get(uid, None)

    # The ct_gm can be deduced from the uid but from profiling we know it's a little expensive.
    # The caller almost always knows the ct_gm beforehand so we can ask them to help us be efficient. On large workloads this optimization is significant.
    def get_people_by_uid(self, uid: str, ct_gm_hint: None | tuple[CrewType, GroupMode] = None) -> None | People:
        """
        Wrapper for :py:meth:`get_by_uid` when searching for :py:attr:`FindableType.PEOPLE`.

        :param ct_gm_hint: the people's crew type and group mode. This is optional because it can be deduced from ``uid``, but it helps performance.
        """
        if ct_gm_hint is None:
            # Break down the uid to determine the ct_gm and know which list to search in.
            breakdown = People.decompose_uid(uid)
            ct_gm = (breakdown.crew_type, breakdown.group_mode)
        else:
            ct_gm = ct_gm_hint if ct_gm_hint[1] != GroupMode.DEFAULT else (ct_gm_hint[0], ct_gm_hint[0].default_group_mode)

        peoples = self._generate_peoples(*ct_gm)
        return peoples.get(uid, None)

    def get_role_by_uid(self, uid: str, ct_gm_hint: None | tuple[CrewType, GroupMode] = None) -> None | Role:
        """
        Wrapper for :py:meth:`get_by_uid` when searching for :py:attr:`FindableType.ROLES`.

        :param ct_gm_hint: the role's crew type and group mode. This is optional because it can be deduced from ``uid``, but it helps performance.
        """
        if ct_gm_hint is None:
            # Break down the uid to determine the ct_gm and know which list to search in.
            role_breakdown = Role.decompose_uid(uid)
            people_breakdown = People.decompose_uid(role_breakdown.people_uid)
            ct_gm = (people_breakdown.crew_type, people_breakdown.group_mode)
        else:
            ct_gm = ct_gm_hint if ct_gm_hint[1] != GroupMode.DEFAULT else (ct_gm_hint[0], ct_gm_hint[0].default_group_mode)
            
        roles = self._generate_roles(*ct_gm)
        return roles.get(uid, None)

    def _compute_or_load(self, computation: _MLVComputation, should_vault: bool = True, should_write: bool = True) -> None:
        if computation.load_if_vaulted(self, self._vault):
            return

        computation.compute(self)
        
        # Some computations should not be vaulted even if computed - usually because they're trivial and fast to recompute.
        if should_vault:
            computation.vault(self, self._vault)

            if should_write:
                self._write_vault()

    def _write_vault(self) -> None:
        self._ctx._write_mlv(self._vault, self._vault_gen_mtime)

    def _generate_movies(self) -> dict[str, Movie]:
        if self._movies is None:
            self._movies = _build_findables_dict(Movie(self, mlf_movie) for mlf_movie in self._movie_list_file.movies_by_uid.values())
            _dbg.logger.info(f"Generated movie list, {len(self._movies)=}")

        return self._movies

    def _generate_peoples(self, crew_type: CrewType, group_mode: GroupMode) -> dict[str, People]:
        ct_gm = (crew_type, group_mode)

        if ct_gm not in self._peoples:
            # Don't vault if any:separate because it's efficient to compute on the fly.
            computation = _PeopleComputation(*ct_gm)
            self._compute_or_load(computation, should_vault=(ct_gm != (CrewType.ANY, GroupMode.SEPARATE)))
            assert ct_gm in self._peoples

        return self._peoples[ct_gm]

    def _generate_roles(self, crew_type: CrewType, group_mode: GroupMode) -> dict[str, Role]:
        ct_gm = (crew_type, group_mode)

        if ct_gm not in self._roles:
            self._roles[ct_gm] = _build_findables_dict(self._generate_roles_no_cache(crew_type, group_mode))
            _dbg.logger.info(f"Generated roles list, {ct_gm=}, {len(self._roles[ct_gm])=}")

        return self._roles[ct_gm]

    def _generate_roles_no_cache(self, crew_type: CrewType, group_mode: GroupMode) -> typing.Iterable[Role]:
        peoples = self._generate_peoples(crew_type, group_mode)

        for people in peoples.values():
            for movie in people.associated_movies():
                yield Role(self, movie, people)
