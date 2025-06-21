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
import abc

from . import _exc
from . import _fetch
from . import _filter
from . import _attr
from . import _dbg

class RegistryOf[T: (type[_fetch.ListFetcher], type[_filter.Predicate], _attr.Attribute, type[_filter.Predicate] | _attr.Attribute)](abc.ABC):
    @abc.abstractmethod
    def register(self, item: T) -> None:
        pass

    @abc.abstractmethod
    def __getitem__(self, qualified_name: str) -> T:
        pass

    @abc.abstractmethod
    def __contains__(self, qualified_name: str) -> bool:
        pass

    @abc.abstractmethod
    def __iter__(self) -> typing.Iterator[T]:
        pass

class DictionaryRegistry[T: (type[_fetch.ListFetcher], type[_filter.Predicate], _attr.Attribute)](RegistryOf[T]):
    def __init__(self) -> None:
        self._registered_items: dict[str, T] = {}

    def register(self, item: T) -> None:
        if item.qualified_name in self:
            raise _exc.InputError(f"Cannot register '{item}' with name '{item.qualified_name}' because an item with that name is already registered.")

        self._registered_items[item.qualified_name] = item
        _dbg.logger.info(f"Registered {item=}, {item.qualified_name=}")

    def __getitem__(self, qualified_name: str) -> T:
        return self._registered_items[qualified_name]

    def __contains__(self, qualified_name: str) -> bool:
        return qualified_name in self._registered_items

    def __iter__(self) -> typing.Iterator[T]:
        return iter(self._registered_items.values())

# For now only used for predicates and attributes so don't bother with better type hints.
class UnionRegistry(RegistryOf[type[_filter.Predicate] | _attr.Attribute]):
    def __init__(self, registries: list[RegistryOf[type[_filter.Predicate]] | RegistryOf[_attr.Attribute]]) -> None:
        self._registries = registries

    def register(self, item: type[_filter.Predicate] | _attr.Attribute) -> None:
        raise _exc.InputError("Registering is not supported on a union registry")

    def __getitem__(self, qualified_name: str) -> type[_filter.Predicate] | _attr.Attribute:
        for reg in self._registries:
            try:
                return reg[qualified_name]
            except KeyError:
                pass

        raise KeyError(f"Item '{qualified_name}' is not in the registry")

    def __contains__(self, qualified_name: str) -> bool:
        return any(qualified_name in reg for reg in self._registries)

    def __iter__(self) -> typing.Iterator[type[_filter.Predicate] | _attr.Attribute]:
        for reg in self._registries:
            yield from reg

class Registry:
    def __init__(self) -> None:
        self._fetchers: RegistryOf[type[_fetch.ListFetcher]] = DictionaryRegistry()
        self._predicates: RegistryOf[type[_filter.Predicate]] = DictionaryRegistry()
        self._attributes: RegistryOf[_attr.Attribute] = DictionaryRegistry()

        # Ugly but helpful because attributes can function as predicates.
        # Obviously you could also just hit the predicates registry and then the attributes registry, but then you'd need special handling for things like "close match" suggestions,
        # checking "contains", iterating, the whole lot. And most importantly - we want to be able to go level by level of registries to try.
        self._predicates_and_attributes = UnionRegistry([self._predicates, self._attributes])

    @property
    def fetchers(self) -> RegistryOf[type[_fetch.ListFetcher]]:
        return self._fetchers

    @property
    def predicates(self) -> RegistryOf[type[_filter.Predicate]]:
        return self._predicates

    @property
    def attributes(self) -> RegistryOf[_attr.Attribute]:
        return self._attributes

    @property
    def predicates_and_attributes(self) -> RegistryOf[type[_filter.Predicate] | _attr.Attribute]:
        return self._predicates_and_attributes

    def register(self, obj: typing.Any) -> None:
        if isinstance(obj, type) and issubclass(obj, _fetch.ListFetcher):
            _dbg.logger.info("Registering as a fetcher")
            self.fetchers.register(obj)
        elif isinstance(obj, type) and issubclass(obj, _filter.Predicate):
            _dbg.logger.info("Registering as a predicate")
            self.predicates.register(obj)
        elif isinstance(obj, _attr.Attribute):
            _dbg.logger.info("Registering as an attribute")
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
