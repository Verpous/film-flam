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

import typing
from collections import namedtuple

import filmflam.repo as repo
import filmflam._utils as utils

CanonListdef = namedtuple('CanonListdef', ['fetcher_type', 'address'])
LISTDEF_ALL = 'all'
LISTDEF_DEFAULTS = 'defaults'

def _get_implicit_list(name: str, ctx: repo.FlamContext) -> None | repo.RemoteList | repo.CompoundList:
    remote_list = next((rl for rl in ctx.cfg.remote_lists if rl.name == name), None)

    if remote_list is not None:
        return remote_list

    return next((cl for cl in ctx.cfg.compound_lists if cl.name == name), None)

def canonicalize_listdefs(listdefs: typing.Iterable[str], ctx: repo.FlamContext) -> typing.Iterator[CanonListdef]:
    for ldef in listdefs:
        if ldef == LISTDEF_DEFAULTS:
            yield CanonListdef(fetcher_type='defaults', address='')
        elif ldef == LISTDEF_ALL:
            yield from (CanonListdef(fetcher_type=rl.FETCHER_TYPE, address=rl.name) for rl in ctx.cfg.remote_lists)
        elif (eq_idx := ldef.find('=')) != -1:
            yield CanonListdef(fetcher_type=ldef[:eq_idx], address=ldef[eq_idx + 1:])
        elif (list_obj := _get_implicit_list(ldef, ctx)) is not None:
            yield CanonListdef(fetcher_type=type(list_obj).FETCHER_TYPE, address=list_obj.name)
        else:
            raise ValueError(f"Invalid LISTDEF: '{ldef}'.")
