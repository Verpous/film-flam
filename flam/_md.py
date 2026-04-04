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

import time

from . import _file
from . import _dbg

_start_import_time = time.time()

class CompositeListMetadata(_file._FlamSerializable):
    uid:                    str
    dependency_mtime:       dict[str, float]

# The MD file doesn't get canonicalized.
class FlamMetadata(_file._FlamSerializable):
    version:                str
    composite_lists_by_uid: dict[str, CompositeListMetadata]

_dbg.logger.info(f'Module import time: {time.time() - _start_import_time}s')
