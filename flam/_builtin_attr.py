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

# pylint: disable=unused-argument

import typing
import datetime
import collections

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
    """the movie's UID in flam."""
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
    """the movie's UID in the source from which the data is fetched."""
    return mlf_movie.uid

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'media-type',
    aliases_without_type = ['type', 'title-type'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
))
def _movie_media_type_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | str:
    """whether this "movie" is actually a movie, or a TV series, etc."""
    return mlf_movie.media_type

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
    """the movie's title."""
    return mlf_movie.title

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'original-title',
    aliases_without_type = ['original-name', 'native-title', 'native-name'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_END,
    default_max_len = _STR_LEN_LONG,
))
def _movie_original_title_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | str:
    """the movie's original title in its native language."""
    return mlf_movie.original_title

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'source',
    aliases_without_type = ['sources', 'origin', 'origins', 'src', 'list', 'lists'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_SHORT,
))
def _movie_source_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[str]:
    """for composite lists - which lists this movie came from."""
    sources = []

    # Guaranteed consistent ordering by canonicalization of per_src_data.
    for per_src_data in mlf_movie.per_src_data:
        # The only kind of abstract listdef we expect to get here is simple lists. For them we will print return just the name without the type.
        if per_src_data.canon_listdef.is_abstract:
            sources.append(movie.movie_list.ctx.cfg_readonly.get_list_by_abstract_listdef(per_src_data.canon_listdef).name)
        # For other kinds return type=address.
        else:
            sources.append(str(per_src_data.canon_listdef))

    return sources

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'tagline',
    aliases_without_type = ['slogan'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.NO_TRIM, # No trimming taglines.
    default_max_len = _STR_LEN_DONTCARE,
))
def _movie_tagline_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | str:
    """the movie's tagline."""
    return mlf_movie.tagline

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'synopsis',
    aliases_without_type = ['plot', 'summary', 'description', 'desc', 'overview'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.NO_TRIM, # No trimming synopses!
    default_max_len = _STR_LEN_DONTCARE,
))
def _movie_synopsis_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | str:
    """the movie's synopsis."""
    return mlf_movie.synopsis

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'url',
    aliases_without_type = ['link', 'page'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.NO_TRIM, # Trimmed urls are worthless.
    default_max_len = _STR_LEN_DONTCARE,
))
def _movie_url_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | str:
    """link to the movie's page on the website it was fetched from."""
    return mlf_movie.url

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
        truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
        default_max_len = _STR_LEN_SHORT,
    ))
    def _movie_watch_date_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[datetime.date]:
        """list of dates that you watched the film in this date format."""
        return [typing.cast(attrutils.DateHandler, self._params.type_handler).strip(watch_date) for watch_date in mlf_movie.watch_dates]

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
    def _movie_release_date_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | datetime.date:
        """the movie's release date in this date format."""
        return None if mlf_movie.release_date is None else typing.cast(attrutils.DateHandler, self._params.type_handler).strip(mlf_movie.release_date)

    name_without_type = 'end' + handler.name

    @_register_easy_attribute(attrutils.EasyAttributeParams(
        name_without_type = name_without_type, # pylint: disable=cell-var-from-loop
        aliases_without_type = _make_date_aliases(name_without_type), # pylint: disable=cell-var-from-loop
        findable_type = _ml.FindableType.MOVIES,
        type_handler = handler, # pylint: disable=cell-var-from-loop
        is_ascending = handler.is_ascending, # pylint: disable=cell-var-from-loop
        truncation_style = utils.TruncationStyle.NO_TRIM,
        default_max_len = _STR_LEN_DONTCARE,
    ))
    def _movie_end_date_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | datetime.date:
        """the TV show's final air date in this date format."""
        return None if mlf_movie.end_date is None else typing.cast(attrutils.DateHandler, self._params.type_handler).strip(mlf_movie.end_date)

    name_without_type = 'listing' + handler.name

    @_register_easy_attribute(attrutils.EasyAttributeParams(
        name_without_type = name_without_type, # pylint: disable=cell-var-from-loop
        aliases_without_type = _make_date_aliases(name_without_type), # pylint: disable=cell-var-from-loop
        findable_type = _ml.FindableType.MOVIES,
        type_handler = handler, # pylint: disable=cell-var-from-loop
        is_ascending = handler.is_ascending, # pylint: disable=cell-var-from-loop
        truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
        default_max_len = _STR_LEN_SHORT,
    ))
    def _movie_listing_date_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[None | datetime.date]:
        """list of when you added this movie to this list or all lists compositing this list, in this date format."""
        return [
            None if per_src_data.listing_date is None else typing.cast(attrutils.DateHandler, self._params.type_handler).strip(per_src_data.listing_date)
            for per_src_data in mlf_movie.per_src_data
        ]

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'list-note',
    aliases_without_type = ['list-comment', 'list-notes', 'list-comments'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_LONG,
))
def _movie_list_note_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[None | str]:
    """list of notes left on this movie in this list."""
    return [per_src_data.list_note for per_src_data in mlf_movie.per_src_data]

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'my-notes',
    aliases_without_type = ['my-note', 'my-comment', 'my-comments'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_LONG,
))
def _movie_my_notes_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[str]:
    """list of notes left on this movie by you in general."""
    return list(mlf_movie.my_notes)

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'episodes-num',
    aliases_without_type = ['episodes'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.SMALL_INT_HANDLER,
    is_ascending = False,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
), create_numericals = True)
def _movie_episodes_num_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    """the number of episodes in this TV show."""
    return mlf_movie.episodes_num

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'seasons-num',
    aliases_without_type = ['seasons'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.SMALL_INT_HANDLER,
    is_ascending = False,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
), create_numericals = True)
def _movie_seasons_num_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    """the number of seasons in this TV show."""
    return mlf_movie.seasons_num

# 'index' only as an alias because there's a predicate by the same name.
@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'list-index',
    aliases_without_type = ['index', 'list-indices', 'indices', 'list-indexes', 'indexes'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.SMALL_INT_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_SHORT,
))
def _movie_index_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[None | int]:
    """list of the movie's indexes in the lists it came from."""
    return [per_src_data.list_index for per_src_data in mlf_movie.per_src_data]

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
    """the movie's runtime in minutes."""
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
    """the movie's metascore."""
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
    """how many critic's reviews went into this movie's metascore."""
    return mlf_movie.metascore_votes

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
    """the movie's rating."""
    return mlf_movie.rating

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
    """how many people voted on this movie's rating."""
    return mlf_movie.votes

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
    """the rating you gave to this movie."""
    return mlf_movie.my_rating

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'likes',
    aliases_without_type = ['like-count'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.BIG_INT_HANDLER,
    is_ascending = False,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
), create_numericals = True)
def _movie_likes_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    """how many people liked the film."""
    return mlf_movie.likes

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'is-liked',
    aliases_without_type = ['liked', 'my-like'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.BOOL_HANDLER,
    is_ascending = False,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
))
def _movie_is_liked_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | bool:
    """whether you gave the film a like."""
    return mlf_movie.is_liked

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'budget-usd',
    aliases_without_type = ['budget'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.BIG_INT_HANDLER,
    is_ascending = False,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
), create_numericals = True)
def _movie_budget_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    """the movie's budget in US dollars."""
    return mlf_movie.budget_usd

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'revenue-usd',
    aliases_without_type = ['revenue'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.BIG_INT_HANDLER,
    is_ascending = False,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
), create_numericals = True)
def _movie_revenue_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    """the movie's revenue in US dollars."""
    return mlf_movie.revenue_usd

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'profit-usd',
    aliases_without_type = ['profit'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.BIG_INT_HANDLER,
    is_ascending = False,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
), create_numericals = True)
def _movie_profit_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | int:
    """the movie's profit in US dollars."""
    if mlf_movie.revenue_usd is None or mlf_movie.budget_usd is None:
        return None
        
    return mlf_movie.revenue_usd - mlf_movie.budget_usd

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'content-rating',
    aliases_without_type = [],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_SHORT,
))
def _movie_content_rating_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> None | str:
    """the movie's content rating."""
    return mlf_movie.content_rating

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
    """list of the movie's genres."""
    # Assume lists are sorted at the source, because of canonicalization. So we won't sort them here.
    # However we do have to copy the list to prevent giving the user access to memory he shouldn't have.
    return list(mlf_movie.genres)

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'studios',
    aliases_without_type = ['studio'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_LONG,
))
def _movie_studios_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[str]:
    """list of the movie's producing studios."""
    return list(mlf_movie.studios)

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
    """list of the movie's languages."""
    return list(mlf_movie.languages)

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'countries',
    aliases_without_type = ['country', 'nation', 'nations', 'nationality', 'nationalities'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_LONG,
))
def _movie_countries_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[str]:
    """list of the movie's producing countries."""
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
        """list of names of the movie's crewmembers in this crew type."""
        # Use self.name_without_type instead of crew_type to avoid cell-var-from-loop error. This is important.
        ct = _ml.CrewType(self.name_without_type) if self.name_without_type != 'people' else _ml.CrewType.ANY

        # This implementation is inefficient. We could improve it by reading from the mlf_movie.crew directly,
        # but that would require sorting and will also be more complicated to support CrewType.ANY.
        # Here we rely on associated_people already guaranteeing a consistent ordering.
        return [
            person.underlying_file_people_readonly[0].name
            for person in movie.associated_people(ct, _ml.GroupMode.SEPARATE)
        ]

# Dictionary equivalent of l[0] when you know the list has only one element.
def _get_only_value[TKey, TVal](d: dict[TKey, TVal]) -> TVal:
    for k in d:
        return d[k] # Donkey-Kong!

    raise RuntimeError('Unexpected non-empty dictionary.')

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'stars',
    aliases_without_type = ['star-cast', 'leads', 'lead-actors', 'lead-cast'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_LONG,
))
def _movie_stars_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[None | str]:
    """list names of the movie's starring actors."""
    # Consistent ordering guaranteed by associated_roles.
    return [
        role.people.underlying_file_people_readonly[0].name
        for role in movie.associated_roles(_ml.CrewType.CAST, _ml.GroupMode.SEPARATE)
        if _get_only_value(role.underlying_file_roles_readonly)[_ml.CrewType.CAST].is_star
    ]

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'oscar-noms',
    aliases_without_type = ['oscar-nominations', 'noms', 'nominations'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_LONG,
))
def _movie_oscar_noms_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[str]:
    """list of Oscar nominations received by this movie."""
    # The same oscar can appear under many crew members so we have to find unique oscars.
    return sorted(set(
        oscar
        for crew in mlf_movie.crew.values()
            for mlf_role in crew.roles_by_uid.values()
                for oscar in mlf_role.oscar_noms
    ))

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'oscar-wins',
    aliases_without_type = ['oscars', 'awards'],
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_LONG,
))
def _movie_oscar_wins_extractor(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> list[str]:
    """list of Oscars won by this movie."""
    return sorted(set(
        oscar
        for crew in mlf_movie.crew.values()
            for mlf_role in crew.roles_by_uid.values()
                for oscar in mlf_role.oscar_wins
    ))

#endregion movie attributes

#region people attributes

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
    """the people's UID in flam."""
    return people.uid

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
    """list of every person's UID in the source from which the data is fetched."""
    # Guaranteed consistent ordering because mlf_people should already be sorted by uid.
    return [mlf_person.uid for mlf_person in mlf_people]

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
    """the people's crew type."""
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
    """the people's group mode."""
    return people.group_mode

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
    """list of every person's name."""
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
    """list of every person's gender (the exact strings representing each gender may vary based on where the data was fetched from)."""
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
    """list of every person's height in centimeters."""
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
    """list of every person's countries."""
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
    """list of movie titles these people were in."""
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
        """list of movie titles these people were in as this crew type."""
        ct = _ml.CrewType(self.name_without_type.removeprefix('movies-as-'))

        # Find the smallest group in another crew type which has at least the same people as this one, if one exists, and return their movies.
        minsuper = people.minimal_superset_people_in_other_crew_type(ct)

        if minsuper is None:
            return []

        # Guaranteed ordering by associated_movies().
        return [
            movie.underlying_file_movie_readonly.title
            for movie in minsuper.associated_movies()
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
    """list of crew types occupied by these people."""
    professions = []
    
    # Iterate over crew types and check if this group of people also collaborated on that crew type.
    for ct in _ml.CrewType.iterate_except_any():
        # Check if there is a group in that crew type which is a superset of the people in this group.
        # This is efficient when ct == people.crew_type.
        minsuper = people.minimal_superset_people_in_other_crew_type(ct)

        if minsuper is not None:
            professions.append(str(minsuper.crew_type))

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
    """list of up to 3 genres these people appear in the most."""
    genre_occurrences: dict[str, int] = collections.defaultdict(lambda : 0)

    # Count occurrences of each genre these people were in.
    for movie in people.associated_movies():
        for genre in movie.underlying_file_movie_readonly.genres:
            genre_occurrences[genre] += 1

    # Sort the items() so it sorts both by the num occurrences as the primary sort key, but the genre string lexicographically as a tiebreaker. This guarantees stable ordering.
    # Will take only the 3 top genres.
    return [k for k, v in sorted(genre_occurrences.items())][:3]

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
        """list of every person's birthday in this date format."""
        hnd = typing.cast(attrutils.DateHandler, self._params.type_handler)

        # Guaranteed consistent ordering because mlf_people should already be sorted by uid.
        return [
            None if mlf_person.birthday is None else hnd.strip(mlf_person.birthday)
            for mlf_person in mlf_people
        ]

    name_without_type = 'death' + handler.name
    
    @_register_easy_attribute(attrutils.EasyAttributeParams(
        name_without_type = name_without_type, # pylint: disable=cell-var-from-loop
        aliases_without_type = _make_date_aliases(name_without_type), # pylint: disable=cell-var-from-loop
        findable_type = _ml.FindableType.PEOPLE,
        type_handler = handler, # pylint: disable=cell-var-from-loop
        is_ascending = handler.is_ascending, # pylint: disable=cell-var-from-loop
        truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
        default_max_len = _STR_LEN_SHORT,
    ))
    def _people_deathday_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> list[None | datetime.date]:
        """list of every person's death date in this date format."""
        hnd = typing.cast(attrutils.DateHandler, self._params.type_handler)

        # Guaranteed consistent ordering because mlf_people should already be sorted by uid.
        return [
            None if mlf_person.deathday is None else hnd.strip(mlf_person.deathday)
            for mlf_person in mlf_people
        ]

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'death-reason',
    aliases_without_type = [],
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_LONG,
))
def _people_death_reason_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> list[None | str]:
    """list of every person's death reason."""
    return [mlf_person.death_reason for mlf_person in mlf_people]

def _get_shared_oscars(people: _ml.People, get_oscars: typing.Callable[[_mlf.MLFRole], list[str]]) -> list[str]:
    # This is a little complicated. A role is usually only one crew type, except in the ANY case.
    # Our fetcher doesn't even try to sort out awards by crew type. It hands it to the person in every crew type.
    # So there are 3 levels of oscars to compute:
    # * Oscars won jointly by this group in a specific movie (intersection of oscar sets).
    # * Oscars won by this group across all movies (list of oscars, allows duplicates).
    oscars: list[str] = []

    for role in people.associated_roles():
        role_oscars: None | set[str] = None
        mlf_roles = role.underlying_file_roles_readonly

        for mlf_person in people.underlying_file_people_readonly:
            person_oscars_in_movie = (
                oscar
                for ct, mlf_role in mlf_roles[mlf_person.uid].items()
                    for oscar in get_oscars(mlf_role)
            )

            if role_oscars is None:
                role_oscars = set(person_oscars_in_movie)
            else:
                role_oscars.intersection_update(person_oscars_in_movie)

        assert role_oscars is not None
        oscars.extend(role_oscars)

    oscars.sort()
    return oscars

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'oscar-noms',
    aliases_without_type = ['oscar-nominations', 'noms', 'nominations'],
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_LONG,
))
def _people_oscar_noms_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> list[str]:
    """list of Oscar nominations received by these people."""
    return _get_shared_oscars(people, lambda r: r.oscar_noms)

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'oscar-wins',
    aliases_without_type = ['oscars', 'awards'],
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_LONG,
))
def _people_oscar_wins_extractor(self: attrutils.EasyAttribute, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> list[str]:
    """list of Oscars won by these people."""
    return _get_shared_oscars(people, lambda r: r.oscar_wins)

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
    """the role's UID in flam."""
    return role.uid

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'episodes-num',
    aliases_without_type = ['episodes'],
    findable_type = _ml.FindableType.ROLES,
    type_handler = attrutils.SMALL_INT_HANDLER,
    is_ascending = False,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = _STR_LEN_DONTCARE,
))
def _role_episodes_num_extractor(self: attrutils.EasyAttribute, role: _ml.Role, mlf_roles: _ml.MLFRolesDict, mlf_movie: _mlf.MLFMovie, mlf_people: list[_mlf.MLFPerson]) -> list[None | int]:
    """the number of episodes this role appeared in."""
    return [
        mlf_role.episodes_num
        for mlf_person in mlf_people
        for ct, mlf_role in mlf_roles[mlf_person.uid].items()
    ]

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'oscar-noms',
    aliases_without_type = ['oscar-nominations', 'noms', 'nominations'],
    findable_type = _ml.FindableType.ROLES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_LONG,
))
def _role_oscar_noms_extractor(self: attrutils.EasyAttribute, role: _ml.Role, mlf_roles: _ml.MLFRolesDict, mlf_movie: _mlf.MLFMovie, mlf_people: list[_mlf.MLFPerson]) -> list[str]:
    """list of Oscar nominations received by this role."""
    return [
        oscar
        for mlf_person in mlf_people
            for ct, mlf_role in mlf_roles[mlf_person.uid].items()
                for oscar in mlf_role.oscar_noms
    ]

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'oscar-wins',
    aliases_without_type = ['oscars', 'awards'],
    findable_type = _ml.FindableType.ROLES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_LONG,
))
def _role_oscar_wins_extractor(self: attrutils.EasyAttribute, role: _ml.Role, mlf_roles: _ml.MLFRolesDict, mlf_movie: _mlf.MLFMovie, mlf_people: list[_mlf.MLFPerson]) -> list[str]:
    """list of Oscar nominations received by this role."""
    return [
        oscar
        for mlf_person in mlf_people
            for ct, mlf_role in mlf_roles[mlf_person.uid].items()
                for oscar in mlf_role.oscar_wins
    ]

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
    """list of characters played by this role (mainly for actors)."""
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
def _role_star_extractor(self: attrutils.EasyAttribute, role: _ml.Role, mlf_roles: _ml.MLFRolesDict, mlf_movie: _mlf.MLFMovie, mlf_people: list[_mlf.MLFPerson]) -> list[None | bool]:
    """list of every person's star status in this movie - i.e. true or false based on if that person is starring."""
    # Guaranteed consistent ordering because:
    # * mlf_people is sorted by uids
    # * python preserves dictionary order and crew types were added to mlf_roles[mlf_people] in the same order everytime
    # * mlf_role.characters is sorted by canonicalization
    return [
        mlf_role.is_star
        for mlf_person in mlf_people
            for ct, mlf_role in mlf_roles[mlf_person.uid].items()
    ]

@_register_easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'jobs',
    aliases_without_type = ['job'],
    findable_type = _ml.FindableType.ROLES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.TRIM_MIDDLE,
    default_max_len = _STR_LEN_SHORT,
))
def _role_jobs_extractor(self: attrutils.EasyAttribute, role: _ml.Role, mlf_roles: _ml.MLFRolesDict, mlf_movie: _mlf.MLFMovie, mlf_people: list[_mlf.MLFPerson]) -> list[str]:
    """list of jobs performed by this role (for crew type :py:attr:`~._ml.CrewType.ADDITIONAL`)."""
    # Guaranteed consistent ordering because:
    # * mlf_people is sorted by uids
    # * python preserves dictionary order and crew types were added to mlf_roles[mlf_people] in the same order everytime
    # * mlf_role.jobs is sorted by canonicalization
    return [
        job
        for mlf_person in mlf_people
            for ct, mlf_role in mlf_roles[mlf_person.uid].items()
                for job in mlf_role.jobs
    ]

#endregion role attributes
