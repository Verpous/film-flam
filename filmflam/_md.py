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

import typing

from . import _file

class CompositeListMetadata(_file._FlamSerializable):
    uid:                    str
    dependency_mtime:       dict[str, float]

class FlamMetadata(_file._FlamSerializable):
    composite_lists_by_uid:  dict[str, CompositeListMetadata]
