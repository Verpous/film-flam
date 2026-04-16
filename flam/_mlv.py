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

from . import _file
from . import _ldef
from . import _ml

class _MLVPeoples(_file._FlamSerializable):
    # Support any group mode since the computation is actually a little funky on GroupMode.SEPARATE when crew type isn't ANY.
    crew_type:                  _ml.CrewType
    group_mode:                 _ml.GroupMode

    # Each group is a list of MLF uids - not ML uids. The sublists should all be sorted, and groups itself should be sorted.
    groups:                     list[list[str]]

class _MLVAssocPeoples(_file._FlamSerializable):
    crew_type:                  _ml.CrewType
    group_mode:                 _ml.GroupMode

    # Each index corresponds to the movie at that index as returned by MovieList.find_movies().
    # The sublists are lists of ML people uids and should be sorted.
    assoc_peoples:               list[list[str]]

class _MLVAssocMovies(_file._FlamSerializable):
    crew_type:                  _ml.CrewType
    group_mode:                 _ml.GroupMode

    # Each index corresponds to the people at that index as returned by MovieList.find_people().
    # The sublists are lists of ML movie uids and should be sorted.
    assoc_movies:               list[list[str]]

# Only support caching minimal supersets for GroupMode.GROUP because for SEPARATE it's trivial to compute.
class _MLVMinSupersets(_file._FlamSerializable):
    self_crew_type:             _ml.CrewType
    other_crew_type:            _ml.CrewType
    group_mode:                 _ml.GroupMode

    # Each index corresponds to the people at that index as returned by MovieList.find_people().
    # The strs are ML people uids of the minimal superset people of those people, or None if there is no such people.
    minsupers:              list[None | str]

# "Vault" is being used as a synonym for "cache", but we needed a different word for it because the word "cache" is used across the codebase in other contexts.
# These files are often called "mlvs" for short, but you can also call them "mulva" ;)
class _MovieListVault(_file._FlamSerializable):
    version:                    str
    abstract_listdef:           _ldef.CanonListdef

    peoples:                    list[_MLVPeoples]
    assoc_peoples:              list[_MLVAssocPeoples]
    assoc_movies:               list[_MLVAssocMovies]
    minsupers:                  list[_MLVMinSupersets]

    def get_vaulted_computations(self) -> list[_ml._MLVComputation]:
        computations: list[_ml._MLVComputation] = []

        # The order matters - if one computation depends on another we'd want to return them topologically sorted.
        computations.extend(_ml._PeopleComputation(people.crew_type, people.group_mode) for people in self.peoples)
        computations.extend(_ml._AssocPeopleComputation(assoc.crew_type, assoc.group_mode) for assoc in self.assoc_peoples)
        computations.extend(_ml._AssocMoviesComputation(assoc.crew_type, assoc.group_mode) for assoc in self.assoc_movies)
        computations.extend(_ml._MinSupersetPeopleComputation(minsuper.self_crew_type, minsuper.other_crew_type, minsuper.group_mode) for minsuper in self.minsupers)
        
        return computations
