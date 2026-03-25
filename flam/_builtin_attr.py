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

from . import _reg
from . import _ml
from . import _mlf
from . import attrutils
from . import utils

_STR_LEN_LONG = 45
_STR_LEN_SHORT = 30
_STR_LEN_DONTCARE = 999

# Combine common decorator chain into a single decorator.
# MUST be defined this way and not via lambda for mypy to work.
def _register_easy_attribute[T](params: attrutils.EasyAttributeParams,
        create_arrlen_attr: bool = True, create_strlen_attr: bool = True) -> typing.Callable[[attrutils.Extractor[T]], None]:
    def inner(extractor: attrutils.Extractor[T]) -> None:
        attr = attrutils.easy_attribute(params)(extractor)
        _reg._register_builtin(attr)

        if create_arrlen_attr:
            _reg._register_builtin(attrutils.ArrayLengthAttribute(attr))
        
        if create_strlen_attr:
            _reg._register_builtin(attrutils.StringLengthAttribute(attr))

    return inner

# Not really a generic utils function because its handling of Nones is pretty ad hoc.
def _mean_except_nones(data: typing.Iterable[None | typing.SupportsFloat]) -> None | float:
    n = 0
    mean = 0.0
 
    for x in data:
        if x is not None:
            n += 1
            mean += (float(x) - mean) / n

    return mean if n > 0 else None

#region movie attributes

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'uid',
    aliases_without_type = ['id', 'guid', 'identifier'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
))
def _movie_uid_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> str:
    return movie.uid

# For movies specifically the ML uid and the MLF uid are the same, but still implement them separately.
@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'origin-uid',
    aliases_without_type = ['origin-id', 'origin-guid', 'origin-identifier'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
))
def _movie_origin_uid_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> str:
    return mlf_movie.uid

# Primary name should be 'title' because People have an attribute named 'name'.
@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'title',
    aliases_without_type = ['name', 'movie'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_END,
    default_max_len = _STR_LEN_LONG,
))
def _movie_title_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | str:
    return mlf_movie.title

def _make_date_aliases(name_without_type: str) -> list[str]:
    # Basically keeps the first letter of each part separated by '-'s.
    # Ex: 'release-date' -> 'r-d', 'watch-month-of-year' -> 'w-m-o-y'.
    return ['-'.join(part[0] for part in name_without_type.split('-'))]

# Dates come in many forms: release year, the full date, just the day of the week, etc.
# For each of those we want a watch date variant, and release date variant.
for handler in attrutils.DATE_HANDLERS:
    name_without_type = 'watch' + handler.name
    
    @_register_easy_attribute(attrutils.EasyAttributeParams(
        name_without_type = name_without_type, # pylint: disable=cell-var-from-loop
        aliases_without_type = _make_date_aliases(name_without_type),
        findable_type = _ml.FindableType.MOVIES,
        type_handler = handler, # pylint: disable=cell-var-from-loop
        is_ascending = handler.is_ascending, # pylint: disable=cell-var-from-loop
        truncation_style = utils.TruncationStyle.NO_TRIM,
        default_max_len = _STR_LEN_DONTCARE,
    ))
    def _movie_watched_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | datetime.date:
        return None if mlf_movie.watch_date is None else typing.cast(attrutils.DateHandler, self._params.type_handler).strip(mlf_movie.watch_date)

    name_without_type = 'release' + handler.name

    @_register_easy_attribute(attrutils.EasyAttributeParams(
        name_without_type = name_without_type, # pylint: disable=cell-var-from-loop
        aliases_without_type = _make_date_aliases(name_without_type),
        findable_type = _ml.FindableType.MOVIES,
        type_handler = handler, # pylint: disable=cell-var-from-loop
        is_ascending = handler.is_ascending, # pylint: disable=cell-var-from-loop
        truncation_style = utils.TruncationStyle.NO_TRIM,
        default_max_len = _STR_LEN_DONTCARE,
    ))
    def _movie_released_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | datetime.date:
        return None if mlf_movie.release_date is None else typing.cast(attrutils.DateHandler, self._params.type_handler).strip(mlf_movie.release_date)

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'description',
    aliases_without_type = ['desc', 'comment'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_LONG,
))
def _movie_description_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | str:
    return mlf_movie.description

# 'index' only as an alias because there's a predicate by the same name.
@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'list-index',
    aliases_without_type = ['index'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.SMALL_INT_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
))
def _movie_index_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    return mlf_movie.list_index

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'runtime',
    aliases_without_type = ['runtime-minutes', 'length', 'minutes', 'run-length', 'run-time'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.MINUTES_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
))
def _movie_runtime_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    return mlf_movie.runtime_minutes

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'metascore',
    aliases_without_type = ['meta-score'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.SMALL_INT_HANDLER,
    is_ascending = False,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
))
def _movie_metascore_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    return mlf_movie.metascore

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'votes',
    aliases_without_type = ['vote-count'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.BIG_INT_HANDLER,
    is_ascending = False,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
))
def _movie_votes_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    return mlf_movie.votes

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'rating',
    aliases_without_type = ['user-rating', 'user-score', 'ratings'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.FLOAT_HANDLER,
    is_ascending = False,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
))
def _movie_rating_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | float:
    return mlf_movie.rating

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'my-rating',
    aliases_without_type = ['my-score', 'my-ratings', 'myrating'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.FLOAT_HANDLER,
    is_ascending = False,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
))
def _movie_my_rating_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | float:
    return mlf_movie.my_rating

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'genres',
    aliases_without_type = ['genre', 'category', 'categories'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_LONG,
))
def _movie_genres_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[str]:
    # Assume lists are sorted at the source, because of canonicalization. So we won't sort them here.
    # However we do have to copy the list to prevent giving the user access to memory he shouldn't have.
    return list(mlf_movie.genres)

# Returns the names of all people in a certain crew type. Supports CrewType.ANY, but an attribute named 'any' will be very unclear, so we name that one 'people' instead.
# There are many aliases to consider supporting here: 'crew' instead of 'people', 'directors' instead of 'director', 'actors' instead of 'cast'...
# But crew types show up in many places and it will be confusing to support them here but not in other places.
for crew_type in _ml.CrewType:
    @_register_easy_attribute(attrutils.EasyAttributeParams(
        name_without_type = crew_type if crew_type != _ml.CrewType.ANY else 'people', # pylint: disable=cell-var-from-loop
        aliases_without_type = [],
        findable_type = _ml.FindableType.MOVIES,
        type_handler = attrutils.STR_HANDLER,
        is_ascending = True,
        truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
        default_max_len = _STR_LEN_SHORT,
    ))
    def _movie_crew_type_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[None | str]:
        global _people_name_attr
        
        # Use self.name_without_type instead of crew_type to avoid cell-var-from-loop error. This is important.
        ct = _ml.CrewType(self.name_without_type) if self.name_without_type != 'people' else _ml.CrewType.ANY

        # This implementation is inefficient. We could improve it by reading from the mlf_movie.crew directly,
        # but that would require sorting and will also be more complicated to support CrewType.ANY.
        # Here we rely on associated_people already guaranteeing a consistent ordering.
        return [
            typing.cast(list[None | str], person.extract(_people_name_attr))[0]
            for person in movie.associated_people(ct, _ml.GroupMode.SEPARATE)
        ]

#endregion movie attributes

#region person attributes

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'uid',
    aliases_without_type = ['id', 'guid', 'identifier'],
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
))
def _people_uid_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> str:
    return people.uid

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'name',
    aliases_without_type = ['names', 'person', 'people'],
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_LONG,
))
def _people_name_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> list[None | str]:
    # Guaranteed consistent ordering because mlf_people should already be sorted by uid.
    return [mlf_person.name for mlf_person in mlf_people]

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'crew-type',
    aliases_without_type = [],
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
))
def _people_crew_type_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> str:
    return people.crew_type

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'group-mode',
    aliases_without_type = [],
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
))
def _people_group_mode_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> str:
    return people.group_mode

# TODO: Some of these things are expensive. Maybe we'll need to do some post-processing on MLFs and cache lots of expensive attributes.
# @_register_easy_attribute(attrutils.EasyAttributeParams(
#     name_without_type = 'nmovies',
#     aliases_without_type = [],
#     findable_type = _ml.FindableType.PEOPLE,
#     type_handler = attrutils.SMALL_INT_HANDLER,
#     is_ascending = False,
#     truncation_style = utils.TruncationStyle.NO_TRIM,
#     default_max_len = _STR_LEN_DONTCARE,
# ))
# def _people_nmovies_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> int:
#     mlf = person.movie_list.underlying_file
#     return sum(
#         1
#         for mlf_movie in mlf.movies_by_uid.values()
#         if any(mlf_person.uid in mlf_movie.crew[crew_type].roles_by_uid for crew_type in _ml.CrewType.iterate_except_any())
#     )

# @_register_easy_attribute(attrutils.EasyAttributeParams(
#     name_without_type = 'avg-metascore',
#     aliases_without_type = [],
#     findable_type = _ml.FindableType.PEOPLE,
#     type_handler = attrutils.FLOAT_HANDLER,
#     is_ascending = False,
#     truncation_style = utils.TruncationStyle.NO_TRIM,
#     default_max_len = _STR_LEN_DONTCARE,
# ))
# def _people_avg_metascore_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> None | float:
#     mlf = person.movie_list.underlying_file
#     return _mean_except_nones(
#         mlf_movie.metascore
#         for mlf_movie in mlf.movies_by_uid.values()
#         if any(mlf_person.uid in mlf_movie.crew[crew_type].roles_by_uid for crew_type in _ml.CrewType.iterate_except_any())
#     )

# @_register_easy_attribute(attrutils.EasyAttributeParams(
#     name_without_type = 'avg-rating',
#     aliases_without_type = [],
#     findable_type = _ml.FindableType.PEOPLE,
#     type_handler = attrutils.FLOAT_HANDLER,
#     is_ascending = False,
#     truncation_style = utils.TruncationStyle.NO_TRIM,
#     default_max_len = _STR_LEN_DONTCARE,
# ))
# def _people_avg_rating_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> None | float:
#     mlf = person.movie_list.underlying_file
#     return _mean_except_nones(
#         mlf_movie.rating
#         for mlf_movie in mlf.movies_by_uid.values()
#         if any(mlf_person.uid in mlf_movie.crew[crew_type].roles_by_uid for crew_type in _ml.CrewType.iterate_except_any())
#     )

#endregion person attributes

#region role attributes

# @_register_easy_attribute(attrutils.EasyAttributeParams(
#     name_without_type = 'characters',
#     aliases_without_type = [],
#     findable_type = _ml.FindableType.ROLES,
#     type_handler = attrutils.STR_HANDLER,
#     is_ascending = True,
#     truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
#     default_max_len = _STR_LEN_SHORT,
# ))
# def _role_characters_extractor(self: attrutils.EasyAttribute, role: _ml.Role, mlf_roles: _ml.MLFRolesDict, mlf_movie: _mlf.MLFMovie, mlf_people: list[_mlf.MLFPerson]) -> list[str]:
#     return sorted(c for mlf_role in mlf_roles for c in mlf_role.characters)

#endregion role attributes

# Cache some attributes for efficiency. Do it at the end of the file after everything's been added.
_people_name_attr = _reg._builtins.attributes['people-name']
