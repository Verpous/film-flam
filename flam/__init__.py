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

from ._gen_version import __version__

# Important to import _reg first, because it's the only module with a function that should be callable during the import process (the register() function).
# Counterintuitively, by importing it first, what we're actually ensuring is that it's imported *last*.
# The first modules that are fully imported are actually the ones that _reg imports, so by the time python evalutes _reg itself, its dependencies are ready.
from ._reg import *

# I don't want long lines and hate importing specific things with "from", so script names tend to be short.
# We don't import non-hidden modules 'utils', 'attrutils' here. They are for importing specifically by the user if he wants them.
from ._attr import *
from ._cfg import *
from ._ctx import *
from ._dbg import *
from ._exc import *
from ._fetch import *
from ._file import *
from ._filter import *
from ._ldef import *
from ._md import *
from ._ml import *
from ._mlf import *

logger.info(f"Imported FilmFlam! {__version__=}")
