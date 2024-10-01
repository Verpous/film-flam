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
def _register_easy_attribute[T](params: attrutils.EasyAttributeParams) -> typing.Callable[[attrutils.Extractor[T]], None]:
    def inner(extractor: attrutils.Extractor[T]) -> None:
        _reg._register_builtin(attrutils.easy_attribute(params)(extractor))
    return inner

#region movie attributes

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'title',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_array = False,
    is_big_endian = True,
    is_ascending = True,
))
def _movie_title_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | str:
    assert not isinstance(mlf_movie.title, _file.UnsetType)
    return mlf_movie.title

# TODO: Format output hrs:minutes
@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'runtime',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.INT_HANDLER,
    is_array = False,
    is_big_endian = True,
    is_ascending = True,
))
def _movie_runtime_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    assert not isinstance(mlf_movie.runtime_minutes, _file.UnsetType)
    return mlf_movie.runtime_minutes

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'released',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.DATE_HANDLER,
    is_array = False,
    is_big_endian = True,
    is_ascending = False,
))
def _movie_released_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | datetime.date:
    assert not isinstance(mlf_movie.release_date, _file.UnsetType)
    return mlf_movie.release_date

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'rating',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.FLOAT_HANDLER,
    is_array = False,
    is_big_endian = True,
    is_ascending = False,
))
def _movie_rating_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | float:
    assert not isinstance(mlf_movie.rating, _file.UnsetType)
    return mlf_movie.rating

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'metascore',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.INT_HANDLER,
    is_array = False,
    is_big_endian = True,
    is_ascending = False,
))
def _movie_metascore_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    assert not isinstance(mlf_movie.metascore, _file.UnsetType)
    return mlf_movie.metascore

# TODO: Do we want this to just be the name or should we extract a list of roles?
@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'director',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_array = True,
    is_big_endian = True,
    is_ascending = True,
))
def _movie_director_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[str]:
    mlf = movie.movie_list.underlying_file
    return sorted(mlf.people_by_uid[uid].name for uid in mlf_movie.crew[_ml.CrewType.DIRECTOR].roles_by_uid)

#endregion movie attributes

#region person attributes

@_reg._register_builtin
@attrutils.easy_attribute(attrutils.EasyAttributeParams(
    name = 'name',
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.STR_HANDLER,
    is_array = False,
    is_big_endian = True,
    is_ascending = True,
))
def _person_name_extractor(self: attrutils.EasyAttribute, person: _ml.Person, mlf_person: _mlf.MLFPerson) -> None | str:
    assert not isinstance(mlf_person.name, _file.UnsetType)
    return mlf_person.name

#endregion person attributes

#region role attributes

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name = 'characters',
    findable_type = _ml.FindableType.ROLES,
    type_handler = attrutils.STR_HANDLER,
    is_array = True,
    is_big_endian = True,
    is_ascending = True,
))
def _role_characters_extractor(self: attrutils.EasyAttribute, role: _ml.Role, mlf_roles: list[_mlf.MLFRole]) -> list[str]:
    return sorted(c for mlf_role in mlf_roles for c in mlf_role.characters)

#endregion role attributes
