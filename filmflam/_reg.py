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

from . import _exc
from . import _fetch
from . import _filter
from . import _attr
from . import _dbg

class Registry:
    def __init__(self) -> None:
        self._fetchers: dict[str, type[_fetch.ListFetcher]] = {}
        self._predicates: dict[str, type[_filter.Predicate]] = {}
        self._attributes: dict[str, _attr.Attribute] = {}

    def register(self, obj: typing.Any) -> None:
        if isinstance(obj, type) and issubclass(obj, _fetch.ListFetcher):
            if obj.list_type in self._fetchers:
                raise _exc.InputError(f"Cannot register the fetcher '{obj.list_type}' because a fetcher for that list type is already registered.")

            _dbg.logger.info(f"Registered {obj} as a fetcher with key='{obj.list_type}'")
            self._fetchers[obj.list_type] = obj
        elif isinstance(obj, type) and issubclass(obj, _filter.Predicate):
            if obj.name in self._predicates:
                raise _exc.InputError(f"Cannot register the predicate '{obj.name}' because a predicate by that name is already registered.")

            _dbg.logger.info(f"Registered {obj} as a predicate with key='{obj.name}'")
            self._predicates[obj.name] = obj
        elif isinstance(obj, _attr.Attribute):
            if obj.name in self._attributes:
                raise _exc.InputError(f"Cannot register the attribute '{obj.name}' because an attribute by that name is already registered.")

            _dbg.logger.info(f"Registered {obj} as an attribute with key='{obj.name}'")
            self._attributes[obj.name] = obj
        else:
            raise _exc.InputError(f"Invalid object for registration: {obj}.")

    def get_fetcher(self, list_type: str) -> type[_fetch.ListFetcher]:
        return self._fetchers[list_type]

    def get_predicate(self, name: str) -> type[_filter.Predicate]:
        return self._predicates[name]

    def get_attribute(self, name: str) -> _attr.Attribute:
        return self._attributes[name]

    def has_fetcher(self, list_type: str) -> bool:
        return list_type in self._fetchers

    def has_predicate(self, name: str) -> bool:
        return name in self._predicates

    def has_attribute(self, name: str) -> bool:
        return name in self._attributes

    def fetcher_keyvals(self) -> typing.ItemsView[str, type[_fetch.ListFetcher]]:
        return self._fetchers.items()

    def predicate_keyvals(self) -> typing.ItemsView[str, type[_filter.Predicate]]:
        return self._predicates.items()

    def attribute_keyvals(self) -> typing.ItemsView[str, _attr.Attribute]:
        return self._attributes.items()

_builtins = Registry()
_global_extensions = Registry()

def _register_builtin(obj: typing.Any) -> typing.Any:
    _dbg.logger.info("Registering a builtin")
    _builtins.register(obj)
    return obj

def register(obj: typing.Any) -> typing.Any:
    _dbg.logger.info("Registering a global extension")
    _global_extensions.register(obj)
    return obj

# Import builtin extensions only here to avoid cyclic dependency issues.
from . import _imdb # pylint: disable=unused-import
from . import _builtin_attr # pylint: disable=unused-import
from . import _builtin_pred # pylint: disable=unused-import
