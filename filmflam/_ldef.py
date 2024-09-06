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

# Not even worth bothering trying to type hint this file without this.
from __future__ import annotations

import typing

from . import _cfg

# Users input LISTDEF strings and we turn them into this more convenient representation.
class CanonListdef(typing.NamedTuple):
    fetcher_type: str
    address: str

    @property
    def is_special(self) -> bool:
        return self.fetcher_type in SPECIAL_FETCHER_TYPES

    # RemoteList/CompositeList listdefs are abstract because they can't be fetched directly, only through the underlying "concrete" type.
    @property
    def is_abstract(self) -> bool:
        return self.fetcher_type == _cfg.RemoteList.FETCHER_TYPE or self.fetcher_type == _cfg.CompositeList.FETCHER_TYPE

    # "Concrete" listdefs have a type that directly corresponds to a ListFetcher.
    @property
    def is_concrete(self) -> bool:
        return not self.is_special

    def __str__(self) -> str:
        return f'{self.fetcher_type}={self.address}'

LISTDEF_ALL = '*'
LISTDEF_DEFAULTS = 'defaults'
SPECIAL_FETCHER_TYPES = {LISTDEF_DEFAULTS, LISTDEF_ALL, _cfg.RemoteList.FETCHER_TYPE, _cfg.CompositeList.FETCHER_TYPE}
