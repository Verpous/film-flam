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

# MovieListFile-related objects go here.
class MLFRole(_file._FlamSerializable):
    person_uid:             str
    characters:             list[str]
    is_star:                None | bool

class MLFCrew(_file._FlamSerializable):
    crew_type:              _ml.CrewType
    roles_by_uid:           dict[str, MLFRole]

class MLFPerson(_file._FlamSerializable):
    uid:                    str
    name:                   None | str
    gender:                 None | str # I am not going down the rabbit hole of enum-ing the possible gender values.
    height_cm:              None | float
    birthday:               None | datetime.date
    countries:              list[str]

# When building a composite list, we'll retain data from all the composite's parts if that data is expected to be different for the same movie when coming from a different list.
# In order to avoid chaos, when building a composite list on top of composite lists, each movie will not be listed as sourced from a composite list,
# but instead as sourced from the concrete or simple list it originally came from. And we'll deduplicate them.
# When fetching a list, the user is expected to create only one PerListData for each movie. And we'll take care of the listdef field in postprocess.
class MLFMoviePerSourceData(_file._FlamSerializable):
    canon_listdef:          _ldef.CanonListdef
    list_index:             None | int
    listing_date:           None | datetime.date
    note:                   None | str

class MLFMovie(_file._FlamSerializable):
    uid:                    str
    per_src_data:           list[MLFMoviePerSourceData]

    title:                  None | str
    synopsis:               None | str
    runtime_minutes:        None | int
    metascore_votes:        None | int
    metascore:              None | int
    votes:                  None | int
    rating:                 None | float
    my_rating:              None | float
    release_date:           None | datetime.date
    watch_dates:            list[datetime.date]
    genres:                 list[str]
    languages:              list[str]
    countries:              list[str]

    # crew type -> crew object. It makes things much nicer when you can reference the crew type you want with this indirection,
    # but the downside (as opposed to having a field for each crew type), is that we have to check dynamically that no crew types were added or are missing in sanity_checks.
    # msgspec supports TypedDict, but it has problems with initializing a default.
    crew:                   dict[_ml.CrewType, MLFCrew]

# MLFs get canonicalized so users can expect all lists in this file to be sorted.
class MovieListFile(_file._FlamSerializable):
    version:                str
    
    # This field is redundant, since the user must've known it ahead-of-time to even know where to load this file. But if I'll omit it I'll regret it.
    # The name is also kind a lie - if the list is named then this will be its abstract listdef. But if you fetched a raw list it will be concrete of course.
    abstract_listdef:       _ldef.CanonListdef

    # Files are "compatible" if they have a matching uid_family. This is because I have no good way of identifying matching items between, say, IMDb and Letterboxd.
    # If a list originates from IMDb, all the uids in the file will be from IMDb, and so it will only be compatible with other IMDb-based lists.
    uid_family:             str

    movies_by_uid:          dict[str, MLFMovie]
    people_by_uid:          dict[str, MLFPerson]

    def sanity_checks(self) -> None:
        super().sanity_checks()

        # Check if every movie has a key for every crew type. This sounds expensive for big lists but it has a profiler stamp of approval.
        num_crew_types_except_any = sum(1 for _ in _ml.CrewType.iterate_except_any())

        for movie in self.movies_by_uid.values():
            # Efficient check if movie.crew.keys() has every crew type except ANY.
            if len(movie.crew) != num_crew_types_except_any or _ml.CrewType.ANY in movie.crew:
                raise self._validation_error(f'Found movie: {movie.uid} with bad crew types: {movie.crew.keys()}.')
