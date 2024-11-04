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

from . import _file
from . import _ldef
from . import _exc

import typing
import weakref

class SimpleList(_file._FlamSerializable):
    uid:                    _file.UnsetType | str
    name:                   str
    list_type:              str
    address:                str
    is_default_fetch:       bool
    is_default_find:        bool

    @property
    def abstract_listdef(self) -> _ldef.CanonListdef:
        assert not isinstance(self.uid, _file.UnsetType)
        return _ldef.CanonListdef(_ldef.SpecialListType.SIMPLE, self.uid)

    @property
    def concrete_listdef(self) -> _ldef.CanonListdef:
        return _ldef.CanonListdef(self.list_type, self.address)

class CompositeList(_file._FlamSerializable):
    uid:                    _file.UnsetType | str
    name:                   str
    simple_list_uids:       list[str]
    filter_tokens:          list[str]
    is_default_fetch:       bool
    is_default_find:        bool

    @property
    def abstract_listdef(self) -> _ldef.CanonListdef:
        assert not isinstance(self.uid, _file.UnsetType)
        return _ldef.CanonListdef(_ldef.SpecialListType.COMPOSITE, self.uid)

# TODO: Maybe the configuration should use "schema evolution".
class Configuration(_file._FlamSerializable):
    simple_lists_raw:       list[SimpleList]
    composite_lists_raw:    list[CompositeList]
    extensions:             list[str]

    @property
    def simple_lists(self) -> ConfigurationLists[SimpleList]:
        return _ConfigurationExtras.of(self).simple_lists

    @property
    def composite_lists(self) -> ConfigurationLists[CompositeList]:
        return _ConfigurationExtras.of(self).composite_lists

    def lists_of_type(self, list_type: str) -> ConfigurationLists[SimpleList] | ConfigurationLists[CompositeList]:
        match list_type:
            case _ldef.SpecialListType.SIMPLE:
                return self.simple_lists
            case _ldef.SpecialListType.COMPOSITE:
                return self.composite_lists
            case _:
                raise _exc.InputError(f"Invalid list type: '{list_type}': must be '{_ldef.SpecialListType.SIMPLE}' or '{_ldef.SpecialListType.COMPOSITE}'.")

    def get_list_by_abstract_listdef(self, abstract_listdef: _ldef.CanonListdef) -> SimpleList | CompositeList:
        return self.lists_of_type(abstract_listdef.list_type).get_by_uid(abstract_listdef.address)
        
    def sanity_checks(self) -> None:
        super().sanity_checks()

        # We permit names that satisfy is_filter_token, as the ambiguity can be defeated with explicit listdefs if the user chooses to punish himself.
        # We permit names with wacky special characters, because we slugify everything when turning it into a filename.
        for sl in self.simple_lists_raw:
            if sum(1 for rl2 in self.simple_lists_raw if sl.name == rl2.name) > 1:
                raise self._validation_error(f"Found multiple lists named '{sl.name}'.")

            if sl.concrete_listdef.is_special:
                raise self._validation_error(f"LISTDEF '{sl.concrete_listdef}' type must not be one of: {', '.join(_ldef.SpecialListType)}.")

        for cl in self.composite_lists_raw:
            if sum(1 for cl2 in self.composite_lists_raw if cl.name == cl2.name) > 1:
                raise self._validation_error(f"Found multiple composite lists named '{cl.name}'.")

            if len(cl.simple_list_uids) == 0:
                raise self._validation_error(f"Composite list '{cl.name}' is made up of 0 lists.")
                
            for uid in cl.simple_list_uids:
                if not any(sl.uid == uid for sl in self.simple_lists_raw):
                    raise self._validation_error(f"Composite list '{cl.name}' references unknown list: '{uid}'.")

# We can't add fields to the Configuration class that we don't want serialized. So extra fields are added through this mechanism.
# The only thing to be cautious about, is that all extras should only reference the cfg object by weakref.
class _ConfigurationExtras:
    _all_extras: dict[int, _ConfigurationExtras] = {}

    def __init__(self, cfg_weak: weakref.ref[Configuration]) -> None:
        self.simple_lists = ConfigurationLists(cfg_weak, SimpleList)
        self.composite_lists = ConfigurationLists(cfg_weak, CompositeList)

    @classmethod
    def of(cls, cfg: Configuration) -> _ConfigurationExtras:
        id_ = id(cfg)

        try:
            return cls._all_extras[id_]
        except KeyError:
            # Add to dict and register to have it removed when the cfg gets gc'd.
            cfg_weak = weakref.ref(cfg, lambda w: _ConfigurationExtras._all_extras.pop(id_))
            extras = cls(cfg_weak)
            cls._all_extras[id_] = extras
            return extras

# Data structure for generically using simple or composite lists.
class ConfigurationLists[T: (SimpleList, CompositeList)]:
    def __init__(self, cfg_weak: weakref.ref[Configuration], list_type: type[T]) -> None:
        self._cfg_weak = cfg_weak
        self._lists: typing.Callable[[], list[T]]

        if list_type == SimpleList:
            # Use a lambda to get lists with indirection so that if someone assigns a new list to it we automatically adapt.
            self._lists = lambda: self._cfg_weak().simple_lists_raw # type: ignore
            self._list_type = _ldef.SpecialListType.SIMPLE
        elif list_type == CompositeList:
            self._lists = lambda: self._cfg_weak().composite_lists_raw # type: ignore
            self._list_type = _ldef.SpecialListType.COMPOSITE
        else:
            raise RuntimeError(f"Unexpected {list_type=}")

    def __iter__(self) -> typing.Iterator[T]:
        return iter(self._lists())

    def get_idx_by_uid(self, uid: str) -> int:
        try:
            return next(i for i, l in enumerate(self) if l.uid == uid)
        except StopIteration as e:
            raise _exc.InputError(f"Invalid {self._list_type} UID: '{uid}'.") from e

    def get_idx_by_name(self, name: str) -> int:
        try:
            return next(i for i, l in enumerate(self) if l.name == name)
        except StopIteration as e:
            raise _exc.InputError(f"Invalid {self._list_type} name: '{name}'.") from e

    def get_by_uid(self, uid: str) -> T:
        return self._lists()[self.get_idx_by_uid(uid)]

    def get_by_name(self, name: str) -> T:
        return self._lists()[self.get_idx_by_name(name)]
