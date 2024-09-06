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

import abc
import typing

from . import _ldef
from . import _listfile

class ListFetcher(abc.ABC):
    fetcher_type: str
    uid_type: str

    # Subclasses must provide a fetcher_type, and may optionally provide an uid_type if they have multiple fetchers that they want to be compatible.
    def __init_subclass__(cls, fetcher_type: str, uid_type: None | str = None, **kwargs: typing.Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.fetcher_type = fetcher_type
        cls.uid_type = uid_type if uid_type is not None else fetcher_type

    def __init__(self, concrete_listdef: _ldef.CanonListdef, abstract_listdef: _ldef.CanonListdef) -> None:
        self._concrete_listdef = concrete_listdef
        self._abstract_listdef = abstract_listdef

    @property
    def concrete_listdef(self) -> _ldef.CanonListdef:
        return self._concrete_listdef

    @property
    def abstract_listdef(self) -> _ldef.CanonListdef:
        return self._abstract_listdef

    @abc.abstractmethod
    def fetch_into_file(self, list_file: _listfile.ListFile) -> None:
        # Populates list_file with data. It may already have preexisting data if updating an existing file.
        # Must leave no field unset. Even if it's an optional field it must explicitly be set to None.
        pass
