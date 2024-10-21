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
    _simple_lists:          list[SimpleList]
    _composite_lists:       list[CompositeList]
    extensions:             list[str]

    def sanity_checks(self) -> None:
        super().sanity_checks()

        # We permit names that satisfy is_filter_token, as the ambiguity can be defeated with explicit listdefs if the user chooses to punish himself.
        # We permit names with wacky special characters, because we slugify everything when turning it into a filename.
        for sl in self._simple_lists:
            if sum(1 for rl2 in self._simple_lists if sl.name == rl2.name) > 1:
                raise self._validation_error(f"Found multiple lists named '{sl.name}'.")

            if sl.concrete_listdef.is_special:
                raise self._validation_error(f"LISTDEF '{sl.concrete_listdef}' type must not be one of: {', '.join(_ldef.SpecialListType)}.")

        for cl in self._composite_lists:
            if sum(1 for cl2 in self._composite_lists if cl.name == cl2.name) > 1:
                raise self._validation_error(f"Found multiple composite lists named '{cl.name}'.")

            if len(cl.simple_list_uids) == 0:
                raise self._validation_error(f"Composite list '{cl.name}' is made up of 0 lists.")
                
            for uid in cl.simple_list_uids:
                try:
                    # get_by_uid is not accessible from here.
                    next(sl for sl in self._simple_lists if sl.uid == uid)
                except StopIteration as e:
                    raise self._validation_error(f"Composite list '{cl.name}' references unknown simple list: '{uid}'.") from e
