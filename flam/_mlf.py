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

import datetime

from . import _file
from . import _ldef
from . import _ml

# MovieListFile-related objects go here.
class MLFRole(_file._FlamSerializable):
    person_uid:             str
    characters:             list[str]

class MLFCrew(_file._FlamSerializable):
    crew_type:              str
    roles_by_uid:           dict[str, MLFRole]

class MLFPerson(_file._FlamSerializable):
    uid:                    str
    name:                   None | str
    # TODO: Check if can support birthday?
    # Would love to add gender, nationality but cinemagoer doesn't have them.

# TODO: Separate properties of the movie from properties of its prescence in a list?
# I.e., 'watch_date', 'description', 'list_index' are not the same as the rest, and when merging lists, we should keep them all.
class MLFMovie(_file._FlamSerializable):
    uid:                    str
    title:                  None | str
    watch_date:             None | datetime.date
    release_date:           None | datetime.date
    description:            None | str
    list_index:             None | int
    runtime_minutes:        None | int
    metascore:              None | int
    votes:                  None | int
    rating:                 None | float
    myrating:               None | float
    genres:                 list[str]
    # TODO: consider adding languages, countries

    # crew type -> crew object. It makes things much nicer when you can reference the crew type you want with this indirection,
    # but the downside (as opposed to having a field for each crew type), is that we have to check dynamically that no crew types were added or are missing.
    # msgspec supports TypedDict, but it has problems with initializing a default.
    crew:                   dict[str, MLFCrew]

class MovieListFile(_file._FlamSerializable):
    # These two fields are redundant, they are essentially the filename so the user must already know them to reach them. but if I'll omit them I'll regret it.
    list_type:              str
    address:                str

    # Files are "compatible" if they have a matching uid_family. This is because I have no good way of identifying matching items between, say, IMDb and Letterboxd.
    # If a list originates from IMDb, all the uids in the file will be from IMDb, and so it will only be compatible with other IMDb-based lists.
    uid_family:             str

    movies_by_uid:          dict[str, MLFMovie]
    people_by_uid:          dict[str, MLFPerson]

    @property
    def abstract_listdef(self) -> _ldef.CanonListdef:
        return _ldef.CanonListdef(self.list_type, self.address)

    def sanity_checks(self) -> None:
        super().sanity_checks()
        crew_types_set = set(ct.value for ct in _ml.CrewType)

        for movie in self.movies_by_uid.values():
            # I verified this check works.
            if crew_types_set != movie.crew.keys():
                raise self._validation_error(f'Found movie: {movie.uid} with bad crew types: {movie.crew.keys()}.')
