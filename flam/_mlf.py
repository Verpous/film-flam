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

import datetime

from . import _file
from . import _ldef
from . import _ml

# TODO: would be really interesting to add accolades.. for people and movies.

class MLFRole(_file._FlamSerializable):
    """
    Serializable object with data about a role in a movie.
    """
    person_uid:             str
    is_star:                None | bool
    characters:             list[str]
    jobs:                   list[str]
    """
    For crew type :py:attr:`~._ml.CrewType.ADDITIONAL`, this describes what the roles were.
    """

class MLFCrew(_file._FlamSerializable):
    """
    Serializable object with data about the crew of a specific type in a movie.
    """
    crew_type:              _ml.CrewType
    roles_by_uid:           dict[str, MLFRole]

class MLFPerson(_file._FlamSerializable):
    """
    Serializable object with data about a person who appeared in one or more movies from the list.
    """
    uid:                    str
    name:                   None | str
    gender:                 None | str
    """
    The exact strings representing each gender may vary based on where the data was fetched from.
    """

    height_cm:              None | float
    birthday:               None | datetime.date
    countries:              list[str]

# When building a composite list, we'll retain data from all the composite's parts if that data is expected to be different for the same movie when coming from a different list.
# In order to avoid chaos, when building a composite list on top of composite lists, each movie will not be listed as sourced from a composite list,
# but instead as sourced from the concrete or simple list it originally came from. And we'll deduplicate them.
# When fetching a list, the user is expected to create only one PerListData for each movie. And we'll take care of the listdef field in postprocess.
class MLFMoviePerSourceData(_file._FlamSerializable):
    """
    Serializable object with data about a movie which is specific to the list from which it came, not universal data about that movie.
    """
    
    canon_listdef:          _ldef.CanonListdef
    """
    The list this data belongs to. Fetchers should make this equal to the :py:attr:`MovieListFile.abstract_listdef`.
    """

    list_index:             None | int
    list_note:              None | str
    """
    This field is for notes specifically attached to the occurrence of the film in this list.

    For the user's notes about the film in general, use :py:attr:`MLFMovie.my_notes`.
    """

    listing_date:           None | datetime.date
    """
    The date this movie was added to this list.
    """

# There's some data here that arguably should be per source data - namely my_rating, is_liked, watch_dates.
# This is because there's a distinction to be made between what is "mine", and what is "the list owner's".
# To simplify things, I've decided not to allow for this distinction. You can technically fetch a list that someone else is curating,
# but it will be regarded as "your" list. If you try to composite it with other lists curated by different users, some field's behavior will be undefined.
# With this in mind, "per src data" is only data that truly belongs to the list itself. Data which belongs to the user who made the list is regarded as universal movie data.
class MLFMovie(_file._FlamSerializable):
    """
    Serializable object with data about a movie.
    """
    uid:                    str
    per_src_data:           list[MLFMoviePerSourceData]
    """
    Data about a movie which is specific to the list from which it came. Fetchers should build this list with only one element.
    """

    title:                  None | str
    tagline:                None | str
    synopsis:               None | str
    url:                    None | str
    runtime_minutes:        None | int
    metascore_votes:        None | int
    metascore:              None | int
    votes:                  None | int
    rating:                 None | float
    my_rating:              None | float
    likes:                  None | int
    is_liked:               None | bool
    release_date:           None | datetime.date
    watch_dates:            list[datetime.date]
    """
    The date(s) you watched this movie. It's a list in case you've seen it more than once and have that data.
    """

    my_notes:               list[str]
    """
    What constitutes a "note" is up to the fetcher. For instance, in Letterboxd fetcher it's the user's reviews of the film.
    """

    genres:                 list[str]
    studios:                list[str]
    languages:              list[str]
    countries:              list[str]

    # crew type -> crew object. It makes things much nicer when you can reference the crew type you want with this indirection,
    # but the downside (as opposed to having a field for each crew type), is that we have to check dynamically that no crew types were added or are missing in _sanity_checks.
    # msgspec supports TypedDict, but it has problems with initializing a default.
    crew:                   dict[_ml.CrewType, MLFCrew]

# MLFs get canonicalized so users can expect all lists in this file to be sorted.
class MovieListFile(_file._FlamSerializable):
    """
    Serializable object with all the data about a movie list.
    """
    version:                str
    
    # This field is redundant, since the user must've known it ahead-of-time to even know where to load this file. But if I'll omit it I'll regret it.
    # The name is also kind a lie - if the list is named then this will be its abstract listdef. But if you fetched a raw list it will be concrete of course.
    abstract_listdef:       _ldef.CanonListdef

    uid_family:             str
    """
    Files are "compatible" if they have a matching family. For instance, different IMDb fetchers might all rely on IMDb IDs, so they can all have the same family.
    """

    movies_by_uid:          dict[str, MLFMovie]
    """
    All the movies in the list. Note that we don't support multiple occurrences of the same movie.
    Fetchers are free to choose one occurrence to keep at random.
    """

    people_by_uid:          dict[str, MLFPerson]

    def _sanity_checks(self) -> None:
        super()._sanity_checks()

        # Check if every movie has a key for every crew type. This sounds expensive for big lists but it has a profiler stamp of approval.
        num_crew_types_except_any = sum(1 for _ in _ml.CrewType.iterate_except_any())

        for movie in self.movies_by_uid.values():
            # Efficient check if movie.crew.keys() has every crew type except ANY.
            if len(movie.crew) != num_crew_types_except_any or _ml.CrewType.ANY in movie.crew:
                raise self._validation_error(f'Found movie: {movie.uid} with bad crew types: {movie.crew.keys()}.')
