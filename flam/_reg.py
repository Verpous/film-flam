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

import typing

from . import _exc
from . import _fetch
from . import _filter
from . import _attr
from . import _dbg

_BUILTIN_NAME = 'builtin'
_GLOBAL_NAME = 'global'

class _RegistryOf[T: (type[_fetch.ListFetcher], type[_filter.Predicate], _attr.Attribute)]:
    def __init__(self, reg: Registry, name: str) -> None:
        self._registered_items: dict[str, None | T] = {}
        self._parent_reg = reg
        self._name = name

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
            
        # Don't log for builtins because it will cause us to log a lot during import time and make flam very expensive to import.
        # Because of this we also want this to be the ONLY log that gets logged when registering something. All the other functions in the call chain shouldn't log.
        if self._parent_reg._name != _BUILTIN_NAME:
            _dbg.logger.info(f"Registered a {self._parent_reg._name} {self._name}: {item=}, {item.qualified_name=}")

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
# In hindsight this optimization is kind of dumb and not really needed, but I'm keeping it.
class _RegistryOfAttributes(_RegistryOf[_attr.Attribute]):
    def register(self, item: _attr.Attribute, as_none: bool = False) -> None:
        super().register(item)

        # This completely violates type-safety but we hacky boys.
        self._parent_reg.predicates.register(item, as_none=True) # type: ignore

class _RegistryOfPredicates(_RegistryOf[type[_filter.Predicate]]):
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
    def __init__(self, name: str) -> None:
        self._name = name
        self._fetchers: _RegistryOf[type[_fetch.ListFetcher]] = _RegistryOf(self, 'fetcher')
        self._predicates: _RegistryOf[type[_filter.Predicate]] = _RegistryOfPredicates(self, 'predicate')
        self._attributes: _RegistryOf[_attr.Attribute] = _RegistryOfAttributes(self, 'attribute')

    @property
    def fetchers(self) -> _RegistryOf[type[_fetch.ListFetcher]]:
        return self._fetchers

    @property
    def predicates(self) -> _RegistryOf[type[_filter.Predicate]]:
        return self._predicates

    @property
    def attributes(self) -> _RegistryOf[_attr.Attribute]:
        return self._attributes

    def register(self, obj: typing.Any) -> None:
        if isinstance(obj, type) and issubclass(obj, _fetch.ListFetcher):
            self.fetchers.register(obj)
        elif isinstance(obj, type) and issubclass(obj, _filter.Predicate):
            self.predicates.register(obj)
        elif isinstance(obj, _attr.Attribute):
            self.attributes.register(obj)
        else:
            raise _exc.InputError(f"Invalid object for registration: {obj}.")

_builtins = Registry(_BUILTIN_NAME)
_global_extensions = Registry(_GLOBAL_NAME)

def _register_builtin[T](obj: T) -> T:
    _builtins.register(obj)
    return obj

def register[T](obj: T) -> T:
    _global_extensions.register(obj)
    return obj

def compose_qualified_attr_or_pred_name(findable_type: str, name_without_type: str) -> str:
    return f'{findable_type}-{name_without_type}'

def decompose_qualified_attr_or_pred_name(qualified_name: str) -> tuple[str, str]:
    split = qualified_name.split('-', maxsplit=1)

    if len(split) != 2:
        raise _exc.InputError(f"Invalid qualified_name: '{qualified_name}'")

    return split[0], split[1]

# Import builtin extensions only here to avoid cyclic dependency issues.
from . import _imdb # pylint: disable=unused-import
from . import _builtin_attr # pylint: disable=unused-import
from . import _builtin_pred # pylint: disable=unused-import

# Logging per registered builtin is very expensive and causes our import time to go way up. So instead we log them all in a big batch at the end.
_dbg.logger.info(f"Registered builtin fetchers:\n    {'\n    '.join(_builtins.fetchers)}")
_dbg.logger.info(f"Registered builtin attributes:\n    {'\n    '.join(_builtins.attributes)}")
_dbg.logger.info(f"Registered builtin predicates:\n    {'\n    '.join(_builtins.predicates)}")
