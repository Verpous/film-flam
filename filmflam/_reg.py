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

class RegistryOf[T: (type[_fetch.ListFetcher], type[_filter.Predicate], _attr.Attribute)]:
    def __init__(self) -> None:
        self._registered_items: dict[str, T] = {}

    def register(self, item: T) -> None:
        if item.name in self:
            raise _exc.InputError(f"Cannot register '{item}' because an item with that name is already registered.")

        self._registered_items[item.name] = item
        _dbg.logger.info(f"Registered {item=}, {item.name=}")

    def __getitem__(self, name: str) -> T:
        return self._registered_items[name]

    def __contains__(self, name: str) -> bool:
        return name in self._registered_items

    def __iter__(self) -> typing.Iterator[T]:
        return iter(self._registered_items.values())

class Registry:
    def __init__(self) -> None:
        self._fetchers: RegistryOf[type[_fetch.ListFetcher]] = RegistryOf()
        self._predicates: RegistryOf[type[_filter.Predicate]] = RegistryOf()
        self._attributes: RegistryOf[_attr.Attribute] = RegistryOf()

    @property
    def fetchers(self) -> RegistryOf[type[_fetch.ListFetcher]]:
        return self._fetchers

    @property
    def predicates(self) -> RegistryOf[type[_filter.Predicate]]:
        return self._predicates

    @property
    def attributes(self) -> RegistryOf[_attr.Attribute]:
        return self._attributes

    def register(self, obj: typing.Any) -> None:
        if isinstance(obj, type) and issubclass(obj, _fetch.ListFetcher):
            _dbg.logger.info(f"Registering as a fetcher")
            self.fetchers.register(obj)
        elif isinstance(obj, type) and issubclass(obj, _filter.Predicate):
            _dbg.logger.info(f"Registering as a predicate")
            self.predicates.register(obj)
        elif isinstance(obj, _attr.Attribute):
            _dbg.logger.info(f"Registering as an attribute")
            self.attributes.register(obj)
        else:
            raise _exc.InputError(f"Invalid object for registration: {obj}.")

_builtins = Registry()
_global_extensions = Registry()

def _register_builtin[T](obj: T) -> T:
    _dbg.logger.info("Registering a builtin")
    _builtins.register(obj)
    return obj

def register[T](obj: T) -> T:
    _dbg.logger.info("Registering a global extension")
    _global_extensions.register(obj)
    return obj

# Import builtin extensions only here to avoid cyclic dependency issues.
from . import _imdb # pylint: disable=unused-import
from . import _builtin_attr # pylint: disable=unused-import
from . import _builtin_pred # pylint: disable=unused-import
