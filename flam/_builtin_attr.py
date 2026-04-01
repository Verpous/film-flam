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
import collections

from . import _reg
from . import _ml
from . import _mlf
from . import _exc
from . import attrutils
from . import utils

_STR_LEN_LONG = 45
_STR_LEN_SHORT = 30
_STR_LEN_DONTCARE = 999

# Combine common decorator chain into a single decorator.
# MUST be defined this way and not via lambda for mypy to work.
def _register_easy_attribute[T](params: attrutils.EasyAttributeParams,
        create_arrlen_attr: bool = True, create_strlen_attr: bool = True, create_numericals: bool = False) -> typing.Callable[[attrutils.Extractor[T]], None]:
    def inner(extractor: attrutils.Extractor[T]) -> None:
        attr = attrutils.easy_attribute(params)(extractor)
        _reg._register_builtin(attr)

        if create_arrlen_attr:
            _reg._register_builtin(attrutils.ArrayLengthAttribute(attr))
        
        if create_strlen_attr:
            _reg._register_builtin(attrutils.StringLengthAttribute(attr))
        
        if create_numericals:
            _reg._register_builtin(attrutils.AverageAttribute(attr))
            _reg._register_builtin(attrutils.SumAttribute(attr, params.type_handler))

            for ct in _ml.CrewType:
                _reg._register_builtin(attrutils.AverageAttribute(attr, as_crew_type=ct))
                _reg._register_builtin(attrutils.SumAttribute(attr, params.type_handler, as_crew_type=ct))

    return inner

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

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'synopsis',
    aliases_without_type = ['plot', 'summary'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.NO_TRIM, # No trimming synopses!
    default_max_len = _STR_LEN_DONTCARE,
))
def _movie_synopsis_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | str:
    return mlf_movie.synopsis

def _make_date_aliases(name: str) -> list[str]:
    aliases = []

    if name == 'birth-date':
        aliases.append('birthday')

    # Basically keeps the first letter of each part separated by '-'s.
    # Ex: 'release-date' -> 'r-d', 'watch-month-of-year' -> 'w-m-o-y'.
    aliases.append('-'.join(part[0] for part in name.split('-')))
    return aliases

# Dates come in many forms: release year, the full date, just the day of the week, etc.
# For each of those we want a watch date variant, and release date variant.
for handler in attrutils.DATE_HANDLERS:
    name_without_type = 'watch' + handler.name
    
    @_register_easy_attribute(attrutils.EasyAttributeParams(
        name_without_type = name_without_type, # pylint: disable=cell-var-from-loop
        aliases_without_type = _make_date_aliases(name_without_type), # pylint: disable=cell-var-from-loop
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
        aliases_without_type = _make_date_aliases(name_without_type), # pylint: disable=cell-var-from-loop
        findable_type = _ml.FindableType.MOVIES,
        type_handler = handler, # pylint: disable=cell-var-from-loop
        is_ascending = handler.is_ascending, # pylint: disable=cell-var-from-loop
        truncation_style = utils.TruncationStyle.NO_TRIM,
        default_max_len = _STR_LEN_DONTCARE,
    ))
    def _movie_released_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | datetime.date:
        return None if mlf_movie.release_date is None else typing.cast(attrutils.DateHandler, self._params.type_handler).strip(mlf_movie.release_date)

    name_without_type = 'listing' + handler.name

    @_register_easy_attribute(attrutils.EasyAttributeParams(
        name_without_type = name_without_type, # pylint: disable=cell-var-from-loop
        aliases_without_type = _make_date_aliases(name_without_type), # pylint: disable=cell-var-from-loop
        findable_type = _ml.FindableType.MOVIES,
        type_handler = handler, # pylint: disable=cell-var-from-loop
        is_ascending = handler.is_ascending, # pylint: disable=cell-var-from-loop
        truncation_style = utils.TruncationStyle.NO_TRIM,
        default_max_len = _STR_LEN_DONTCARE,
    ))
    def _movie_listed_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | datetime.date:
        return None if mlf_movie.listing_date is None else typing.cast(attrutils.DateHandler, self._params.type_handler).strip(mlf_movie.listing_date)

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
), create_numericals = True)
def _movie_runtime_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    return mlf_movie.runtime_minutes

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'metascore',
    aliases_without_type = ['meta-score', 'metacritic-score'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.SMALL_INT_HANDLER,
    is_ascending = False,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
), create_numericals = True)
def _movie_metascore_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    return mlf_movie.metascore

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'metascore-votes',
    aliases_without_type = ['metacritic-review-count', 'metacritic-vote-count', 'metascore-review-count', 'metascore-vote-count', 'metacritic-rating'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.SMALL_INT_HANDLER,
    is_ascending = False,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
), create_numericals = True)
def _movie_metascore_votes_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    return mlf_movie.metascore_votes

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'votes',
    aliases_without_type = ['vote-count'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.BIG_INT_HANDLER,
    is_ascending = False,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
), create_numericals = True)
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
), create_numericals = True)
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
), create_numericals = True)
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

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'languages',
    aliases_without_type = ['language'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_SHORT,
))
def _movie_languages_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[str]:
    # Assume lists are sorted at the source, because of canonicalization. So we won't sort them here.
    # However we do have to copy the list to prevent giving the user access to memory he shouldn't have.
    return list(mlf_movie.languages)

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'countries',
    aliases_without_type = ['country', 'nation', 'nations', 'nationality', 'nationalities'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_SHORT,
))
def _movie_countries_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[str]:
    # Assume lists are sorted at the source, because of canonicalization. So we won't sort them here.
    # However we do have to copy the list to prevent giving the user access to memory he shouldn't have.
    return list(mlf_movie.countries)

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
        # Use self.name_without_type instead of crew_type to avoid cell-var-from-loop error. This is important.
        ct = _ml.CrewType(self.name_without_type) if self.name_without_type != 'people' else _ml.CrewType.ANY

        # This implementation is inefficient. We could improve it by reading from the mlf_movie.crew directly,
        # but that would require sorting and will also be more complicated to support CrewType.ANY.
        # Here we rely on associated_people already guaranteeing a consistent ordering.
        return [
            person.underlying_file_people_readonly[0].name
            for person in movie.associated_people(ct, _ml.GroupMode.SEPARATE)
        ]

# TODO: uncomment and figure out exactly once we add roles' star attr.
# @_register_easy_attribute(attrutils.EasyAttributeParams(
#     name_without_type = 'stars',
#     aliases_without_type = ['star-cast', 'leads', 'lead-actors', 'lead-cast'],
#     findable_type = _ml.FindableType.MOVIES,
#     type_handler = attrutils.STR_HANDLER,
#     is_ascending = True,
#     truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
#     default_max_len = _STR_LEN_SHORT,
# ))
# def _movie_stars_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[None | str]:
#     global _people_name_attr
#     global _role_star_attr

#     # This implementation is inefficient. We could improve it by reading from the mlf_movie.crew directly,
#     # but that would require sorting and will also be more complicated to support CrewType.ANY.
#     # Here we rely on associated_people already guaranteeing a consistent ordering.
#     return [
#         typing.cast(list[None | str], role.extract(_people_name_attr))[0]
#         for role in movie.associated_roles(CrewType.CAST, _ml.GroupMode.SEPARATE)
#         if role.extract(_role_star_attr)[0] is True
#     ]

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

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'origin-uid',
    aliases_without_type = ['origin-id', 'origin-guid', 'origin-identifier'],
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_SHORT,
))
def _people_origin_uid_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> list[str]:
    # Guaranteed consistent ordering because mlf_people should already be sorted by uid.
    return [mlf_person.uid for mlf_person in mlf_people]

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
    name_without_type = 'gender',
    aliases_without_type = ['sex'],
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_SHORT,
))
def _people_gender_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> list[None | str]:
    # Guaranteed consistent ordering because mlf_people should already be sorted by uid.
    return [mlf_person.gender for mlf_person in mlf_people]

# Considered supporting a height-ft too with its own FEET_HANDLER, but fuck that.
@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'height-cm',
    aliases_without_type = ['height'],
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.FLOAT_HANDLER,
    is_ascending = False,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_SHORT,
), create_numericals = True)
def _people_height_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> list[None | float]:
    # Guaranteed consistent ordering because mlf_people should already be sorted by uid.
    return [mlf_person.height_cm for mlf_person in mlf_people]

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'countries',
    aliases_without_type = ['country', 'nation', 'nations', 'nationality', 'nationalities'],
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_SHORT,
))
def _people_countries_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> list[str]:
    # Guaranteed consistent ordering because mlf_people should already be sorted by uid.
    # Considered printing the union of all people's countries (no duplicates), or the intersection..
    # In the end I think the best is to print each person's entire nationalities joined with '-'.
    # For example if P1 is French, American and P2 is Canadian you'll get French-American, Canadian.
    return ['-'.join(mlf_person.countries) for mlf_person in mlf_people]

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'movies',
    aliases_without_type = ['titles', 'credits'],
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_LONG,
))
def _people_movies_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> list[None | str]:
    # Guaranteed ordering by associated_movies().
    return [
        movie.underlying_file_movie_readonly.title
        for movie in people.associated_movies()
    ]

for crew_type in _ml.CrewType:
    @_register_easy_attribute(attrutils.EasyAttributeParams(
        name_without_type = f'movies-as-{crew_type}', # pylint: disable=cell-var-from-loop
        aliases_without_type = [f'titles-as-{crew_type}', f'credits-as-{crew_type}'], # pylint: disable=cell-var-from-loop
        findable_type = _ml.FindableType.PEOPLE,
        type_handler = attrutils.STR_HANDLER,
        is_ascending = True,
        truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
        default_max_len = _STR_LEN_LONG,
    ))
    def _people_movies_as_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> list[None | str]:
        ct = _ml.CrewType(self.name_without_type.removeprefix('movies-as-'))

        # Find the smallest group in another crew type which has at least the same people as this one, if one exists, and return their movies.
        try:
            minimal_superset_people = people.minimal_superset_people(ct)
        except _exc.InputError:
            return []

        # Guaranteed ordering by associated_movies().
        return [
            movie.underlying_file_movie_readonly.title
            for movie in minimal_superset_people.associated_movies()
        ]

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'professions',
    aliases_without_type = ['jobs', 'expertise'],
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_SHORT,
))
def _people_professions_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> list[str]:
    professions = []
    
    # Iterate over crew types and check if this group of people also collaborated on that crew type.
    for ct in _ml.CrewType.iterate_except_any():
        # If same crew type that we group is already known to be doing together - the answer is easy.
        if ct == people.crew_type:
            professions.append(str(ct))
            continue

        # For other crew types we will check if there is a group in that crew type which is a superset of the people in this group.
        try:
            minimal_superset_people = people.minimal_superset_people(ct)
            professions.append(str(minimal_superset_people.crew_type))
        except _exc.InputError:
            pass

    return professions

# Might be nice to add top-genres-as-X someday. At that point I think I will add an infra for adding -as-X variants more easily as we have multiple use cases for it.
@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'top-genres',
    aliases_without_type = ['top-genre'],
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_SHORT,
))
def _people_top_genres_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> list[str]:
    genre_occurences: dict[str, int] = collections.defaultdict(lambda : 0)

    # Count occurences of each genre these people were in.
    for movie in people.associated_movies():
        for genre in movie.underlying_file_movie_readonly.genres:
            genre_occurences[genre] += 1

    # Sort the items() so it sorts both by the num occurences as the primary sort key, but the genre string lexicographically as a tiebreaker. This guarantees stable ordering.
    # Will take only the 3 top genres.
    return [k for k, v in sorted(genre_occurences.items())][:3]

for handler in attrutils.DATE_HANDLERS:
    name_without_type = 'birth' + handler.name
    
    @_register_easy_attribute(attrutils.EasyAttributeParams(
        name_without_type = name_without_type, # pylint: disable=cell-var-from-loop
        aliases_without_type = _make_date_aliases(name_without_type), # pylint: disable=cell-var-from-loop
        findable_type = _ml.FindableType.PEOPLE,
        type_handler = handler, # pylint: disable=cell-var-from-loop
        is_ascending = handler.is_ascending, # pylint: disable=cell-var-from-loop
        truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
        default_max_len = _STR_LEN_SHORT,
    ))
    def _people_birthday_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> list[None | datetime.date]:
        hnd = typing.cast(attrutils.DateHandler, self._params.type_handler)

        # Guaranteed consistent ordering because mlf_people should already be sorted by uid.
        return [
            None if mlf_person.birthday is None else hnd.strip(mlf_person.birthday)
            for mlf_person in mlf_people
        ]

#endregion person attributes

#region role attributes

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'uid',
    aliases_without_type = ['id', 'guid', 'identifier'],
    findable_type = _ml.FindableType.ROLES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
))
def _role_uid_extractor(self: attrutils.EasyAttribute, role: _ml.Role, mlf_roles: _ml.MLFRolesDict, mlf_movie: _mlf.MLFMovie, mlf_people: list[_mlf.MLFPerson]) -> str:
    return role.uid

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'characters',
    aliases_without_type = ['character'],
    findable_type = _ml.FindableType.ROLES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_SHORT,
))
def _role_characters_extractor(self: attrutils.EasyAttribute, role: _ml.Role, mlf_roles: _ml.MLFRolesDict, mlf_movie: _mlf.MLFMovie, mlf_people: list[_mlf.MLFPerson]) -> list[str]:
    # Guaranteed consistent ordering because:
    # * mlf_people is sorted by uids
    # * python preserves dictionary order and crew types were added to mlf_roles[mlf_people] in the same order everytime
    # * mlf_role.characters is sorted by canonicalization
    return [
        char
        for mlf_person in mlf_people
        for ct, mlf_role in mlf_roles[mlf_person.uid].items()
        for char in mlf_role.characters
    ]

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'is-star',
    aliases_without_type = ['star'],
    findable_type = _ml.FindableType.ROLES,
    type_handler = attrutils.BOOL_HANDLER,
    is_ascending = False,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_SHORT,
))
def _role_chara_extractor(self: attrutils.EasyAttribute, role: _ml.Role, mlf_roles: _ml.MLFRolesDict, mlf_movie: _mlf.MLFMovie, mlf_people: list[_mlf.MLFPerson]) -> list[None | bool]:
    # Guaranteed consistent ordering because:
    # * mlf_people is sorted by uids
    # * python preserves dictionary order and crew types were added to mlf_roles[mlf_people] in the same order everytime
    # * mlf_role.characters is sorted by canonicalization
    return [
        mlf_role.is_star
        for mlf_person in mlf_people
        for ct, mlf_role in mlf_roles[mlf_person.uid].items()
    ]

#endregion role attributes
