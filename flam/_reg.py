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
import time

from . import _exc
from . import _fetch
from . import _filter
from . import _attr
from . import _dbg

_start_import_time = time.time()

class RegistryOf[T: (type[_fetch.ListFetcher], type[_filter.Predicate], _attr.Attribute)]:
    def __init__(self, reg: Registry) -> None:
        self._registered_items: dict[str, None | T] = {}
        self._parent_reg = reg

    # as_none flag is used for a hack related to lazy creation of AttributePredicates. It's ok because this function is only ever meant to be called internally.
    def register(self, item: T, as_none: bool = False) -> None:
        register_value = item if not as_none else None

        # Register primary name.
        if item.qualified_name in self:
            raise _exc.InputError(f"Cannot register '{item}' with name '{item.qualified_name}' because an item with that name is already registered.")
        
        self._registered_items[item.qualified_name] = register_value

        # Also register aliases, with rollback support if any of them are taken.
        try:
            for alias in item.qualified_aliases:
                if alias in self:
                    raise _exc.InputError(f"Cannot register '{item}' with name '{alias}' because an item with that name is already registered.")
                
                self._registered_items[alias] = register_value
        except _exc.InputError:
            # Rollback.
            del self._registered_items[item.qualified_name]

            for alias in item.qualified_aliases:
                try:
                    del self._registered_items[alias]
                except KeyError:
                    # No reason to try the next ones if this one was where we failed to add.
                    break

            # I tested, this is safe even though we had other exceptions inside this scope.
            raise
            
        _dbg.logger.info(f"Registered {item=}, {item.qualified_name=}")

    # Important that due to lazy creation of AttributePredicates, this is the only function that may return registered items.
    def __getitem__(self, qualified_name: str) -> T:
        item = self._registered_items[qualified_name]
        assert item is not None
        return item

    def __contains__(self, qualified_name: str) -> bool:
        return qualified_name in self._registered_items

    # Support iteration only over keys and not values, because some values may be lazily allocated once you __getitem__.
    def __iter__(self) -> typing.Iterator[str]:
        return iter(self._registered_items)

# Attributes are technically also predicates, but there can be hundreds of attributes and I don't want to create an AttributePredicate for each one.
# So we do it lazy. When an attribute is registered, it's also registered as a predicate with item = None.
# When we __getitem__ that predicate, we create the actual AttributePredicate class.
class RegistryOfAttributes(RegistryOf[_attr.Attribute]):
    def register(self, item: _attr.Attribute, as_none: bool = False) -> None:
        super().register(item)

        # This completely violates type-safety but we hacky boys.
        self._parent_reg.predicates.register(item, as_none=True) # type: ignore

class RegistryOfPredicates(RegistryOf[type[_filter.Predicate]]):
    def __getitem__(self, qualified_name: str) -> type[_filter.Predicate]:
        predicate = self._registered_items[qualified_name]
        
        if predicate is None:
            attr = self._parent_reg.attributes[qualified_name]

            # Remember attributes support aliasing, so qualified_name might not be equal to attr.qualified_name.
            # We'll optimize by always caching the AttributePredicate to the primary name of the predicate,
            # and if we request the predicate by an alias, we'll return the result cached in the primary name.
            primary_predicate = self._registered_items[attr.qualified_name]

            if primary_predicate is None:
                predicate = _filter._make_attribute_predicate(attr)
                self._registered_items[attr.qualified_name] = predicate
            else:
                predicate = primary_predicate

            self._registered_items[qualified_name] = predicate

        return predicate

class Registry:
    def __init__(self) -> None:
        self._fetchers: RegistryOf[type[_fetch.ListFetcher]] = RegistryOf(self)
        self._predicates: RegistryOf[type[_filter.Predicate]] = RegistryOfPredicates(self)
        self._attributes: RegistryOf[_attr.Attribute] = RegistryOfAttributes(self)

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

def compose_qualified_attr_or_pred_name(findable_type: str, name_without_type: str) -> str:
    return f'{findable_type}-{name_without_type}'

def decompose_qualified_attr_or_pred_name(qualified_name: str) -> tuple[str, str]:
    split = qualified_name.split('-', maxsplit=1)

    if len(split) != 2:
        raise _exc.InputError(f"Invalid qualified_name: '{qualified_name}'")

    return split[0], split[1]

_dbg.logger.info(f'Module import time: {time.time() - _start_import_time}s')

# Import builtin extensions only here to avoid cyclic dependency issues.
from . import _imdb # pylint: disable=unused-import
from . import _builtin_attr # pylint: disable=unused-import
from . import _builtin_pred # pylint: disable=unused-import
