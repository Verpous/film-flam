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

# pylint: disable=unused-argument

import typing
import datetime

from . import _dbg
from . import _exc
from . import _reg
from . import _ml
from . import _mlf
from . import _file
from . import _attr
from . import attrutils

# Combine common decorator chain into a single decorator.
# MUST be defined this way and not via lambda for mypy to work.
def _register_easy_attribute[T](params: attrutils.EasyAttributeParams, create_len_attr: bool = True) -> typing.Callable[[attrutils.Extractor[T]], None]:
    def inner(extractor: attrutils.Extractor[T]) -> None:
        attr = attrutils.easy_attribute(params)(extractor)
        _reg._register_builtin(attr)

        if create_len_attr:
            _reg._register_builtin(attrutils.LenAttribute(attr))

    return inner

def mean(data: typing.Iterable) -> None | float:
    n = 0
    _mean = 0.0
 
    for x in data:
        if x is not None:
            n += 1
            _mean += (x - _mean) / n

    return _mean if n > 0 else None

#region movie attributes

# TODO: if/when we allow same name across different types, change this to just 'uid'.
@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'muid',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_big_endian = True,
    is_ascending = True,
))
def _movie_muid_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> str:
    assert not isinstance(mlf_movie.uid, _file.UnsetType)
    return mlf_movie.uid

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'title',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_big_endian = True,
    is_ascending = True,
))
def _movie_title_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | str:
    assert not isinstance(mlf_movie.title, _file.UnsetType)
    return mlf_movie.title

for handler in attrutils.DATE_HANDLERS:
    @_register_easy_attribute(attrutils.EasyAttributeParams(
        name = 'watch' + handler.name, # pylint: disable=cell-var-from-loop
        findable_type = _ml.FindableType.MOVIES,
        type_handler = handler, # pylint: disable=cell-var-from-loop
        is_big_endian = True,
        is_ascending = handler.is_ascending, # pylint: disable=cell-var-from-loop
    ))
    def _movie_watched_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | datetime.date:
        assert not isinstance(mlf_movie.watch_date, _file.UnsetType)
        return None if mlf_movie.watch_date is None else typing.cast(attrutils.DateHandler, self._params.type_handler).strip(mlf_movie.watch_date)

    @_register_easy_attribute(attrutils.EasyAttributeParams(
        name = 'release' + handler.name, # pylint: disable=cell-var-from-loop
        findable_type = _ml.FindableType.MOVIES,
        type_handler = handler, # pylint: disable=cell-var-from-loop
        is_big_endian = True,
        is_ascending = handler.is_ascending, # pylint: disable=cell-var-from-loop
    ))
    def _movie_released_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | datetime.date:
        assert not isinstance(mlf_movie.release_date, _file.UnsetType)
        return None if mlf_movie.release_date is None else typing.cast(attrutils.DateHandler, self._params.type_handler).strip(mlf_movie.release_date)

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'description',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_big_endian = True,
    is_ascending = True,
))
def _movie_description_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | str:
    assert not isinstance(mlf_movie.description, _file.UnsetType)
    return mlf_movie.description

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'index',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.INT_HANDLER,
    is_big_endian = True,
    is_ascending = True,
))
def _movie_index_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    assert not isinstance(mlf_movie.list_index, _file.UnsetType)
    return mlf_movie.list_index

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'runtime',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.MINUTES_HANDLER,
    is_big_endian = True,
    is_ascending = True,
))
def _movie_runtime_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    assert not isinstance(mlf_movie.runtime_minutes, _file.UnsetType)
    return mlf_movie.runtime_minutes

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'metascore',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.INT_HANDLER,
    is_big_endian = True,
    is_ascending = False,
))
def _movie_metascore_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    assert not isinstance(mlf_movie.metascore, _file.UnsetType)
    return mlf_movie.metascore

# TODO: human-readable str_of (i.e. add K, M, for thousands and millions)
@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'votes',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.INT_HANDLER,
    is_big_endian = True,
    is_ascending = False,
))
def _movie_votes_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    assert not isinstance(mlf_movie.votes, _file.UnsetType)
    return mlf_movie.votes

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'rating',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.FLOAT_HANDLER,
    is_big_endian = True,
    is_ascending = False,
))
def _movie_rating_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | float:
    assert not isinstance(mlf_movie.rating, _file.UnsetType)
    return mlf_movie.rating

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'myrating',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.FLOAT_HANDLER,
    is_big_endian = True,
    is_ascending = False,
))
def _movie_myrating_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | float:
    assert not isinstance(mlf_movie.myrating, _file.UnsetType)
    return mlf_movie.myrating

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'genres',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_big_endian = True,
    is_ascending = True,
))
def _movie_genres_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[str]:
    return sorted(mlf_movie.genres)

for crew_type in _ml.CrewType:
    @_register_easy_attribute(attrutils.EasyAttributeParams(
        name = crew_type, # pylint: disable=cell-var-from-loop
        findable_type = _ml.FindableType.MOVIES,
        type_handler = attrutils.STR_HANDLER,
        is_big_endian = True,
        is_ascending = True,
    ))
    def _movie_crew_type_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[str]:
        mlf = movie.movie_list.underlying_file
        
        # Use self.name instead of crew_type to avoid cell-var-from-loop error.
        return sorted(name for uid in mlf_movie.crew[self.name].roles_by_uid if isinstance(name := mlf.people_by_uid[uid].name, str))

#endregion movie attributes

#region person attributes

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'puid',
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.STR_HANDLER,
    is_big_endian = True,
    is_ascending = True,
))
def _person_puid_extractor(self: attrutils.EasyAttribute, person: _ml.Person, mlf_person: _mlf.MLFPerson) -> None | str:
    assert not isinstance(mlf_person.uid, _file.UnsetType)
    return mlf_person.uid

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'name',
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.STR_HANDLER,
    is_big_endian = True,
    is_ascending = True,
))
def _person_name_extractor(self: attrutils.EasyAttribute, person: _ml.Person, mlf_person: _mlf.MLFPerson) -> None | str:
    assert not isinstance(mlf_person.name, _file.UnsetType)
    return mlf_person.name

# TODO: Some of these things are expensive. Maybe we'll need to do some post-processing on MLFs and cache lots of expensive attributes.
@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'nmovies',
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.INT_HANDLER,
    is_big_endian = True,
    is_ascending = False,
))
def _person_nmovies_extractor(self: attrutils.EasyAttribute, person: _ml.Person, mlf_person: _mlf.MLFPerson) -> int:
    mlf = person.movie_list.underlying_file
    return sum(
        1
        for mlf_movie in mlf.movies_by_uid.values()
        if any(mlf_person.uid in mlf_movie.crew[crew_type].roles_by_uid for crew_type in _ml.CrewType)
    )

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'avg-metascore',
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.FLOAT_HANDLER,
    is_big_endian = True,
    is_ascending = False,
))
def _person_avgmetascore_extractor(self: attrutils.EasyAttribute, person: _ml.Person, mlf_person: _mlf.MLFPerson) -> None | float:
    mlf = person.movie_list.underlying_file
    return mean(
        mlf_movie.metascore
        for mlf_movie in mlf.movies_by_uid.values()
        if any(mlf_person.uid in mlf_movie.crew[crew_type].roles_by_uid for crew_type in _ml.CrewType)
    )

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'avg-rating',
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.FLOAT_HANDLER,
    is_big_endian = True,
    is_ascending = False,
))
def _person_avgrating_extractor(self: attrutils.EasyAttribute, person: _ml.Person, mlf_person: _mlf.MLFPerson) -> None | float:
    mlf = person.movie_list.underlying_file
    return mean(
        mlf_movie.rating
        for mlf_movie in mlf.movies_by_uid.values()
        if any(mlf_person.uid in mlf_movie.crew[crew_type].roles_by_uid for crew_type in _ml.CrewType)
    )

#endregion person attributes

#region role attributes

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'characters',
    findable_type = _ml.FindableType.ROLES,
    type_handler = attrutils.STR_HANDLER,
    is_big_endian = True,
    is_ascending = True,
))
def _role_characters_extractor(self: attrutils.EasyAttribute, role: _ml.Role, mlf_roles: list[_mlf.MLFRole]) -> list[str]:
    return sorted(c for mlf_role in mlf_roles for c in mlf_role.characters)

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'crew-type',
    findable_type = _ml.FindableType.ROLES,
    type_handler = attrutils.STR_HANDLER,
    is_big_endian = True,
    is_ascending = True,
))
def _role_crewtype_extractor(self: attrutils.EasyAttribute, role: _ml.Role, mlf_roles: list[_mlf.MLFRole]) -> str:
    return role.crew_type

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'group-mode',
    findable_type = _ml.FindableType.ROLES,
    type_handler = attrutils.STR_HANDLER,
    is_big_endian = True,
    is_ascending = True,
))
def _role_groupmode_extractor(self: attrutils.EasyAttribute, role: _ml.Role, mlf_roles: list[_mlf.MLFRole]) -> str:
    return role.group_mode

#endregion role attributes
