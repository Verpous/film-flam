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

class _CompositeListMetadata(_file._FlamSerializable):
    uid:                    str
    dependency_mtime:       dict[str, float]

class _MLVMetadata(_file._FlamSerializable):
    abstract_listdef:       _ldef.CanonListdef
    dependency_mtime:       float

# The MD file doesn't get canonicalized.
class _FlamMetadata(_file._FlamSerializable):
    version:                str
    composite_lists_by_uid: dict[str, _CompositeListMetadata]
    movie_list_vaults:      list[_MLVMetadata]

    def get_mlv_meta(self, abstract_listdef: _ldef.CanonListdef) -> _MLVMetadata:
        for mlv_meta in self.movie_list_vaults:
            if mlv_meta.abstract_listdef == abstract_listdef:
                return mlv_meta

        raise KeyError(f"No vault metadata for movie list '{abstract_listdef}'.")
