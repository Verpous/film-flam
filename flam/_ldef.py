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
import enum
import time

from . import _ctx
from . import _exc
from . import _dbg

_start_import_time = time.time()

# Listdefs are basically a spec for identifying a list. Users pass them in as a string of the form "<list_type>=<address>", where:
# * <list_type> describes where to look for the list
# * <address> describes, well, the address in the list type where you are looking
# In some cases the list_type or the address can be omitted and we automatically infer it.
#
# Internally we take listdefs through a process called "canonicalization" where we:
# * Parse them into a named tuple CanonListdef(list_type, address)
# * "Expand" them which is a process of handling special listdefs. For example '*' is a special string which we expand to a list of all configured simple lists.
#
# Some important things to know about listdefs:
# * Once they're past canonicalizaton, the list types ALL and DEFAULTS are handled and you don't have to check for them.
# * Simple/composite lists are described with the address being their name, but during canonicalization we change that to their uid
# * When printing a listdef to the user, it's best to format it pretty() because that will convert these list uids back to their names
#
# Concrete and abstract canon listdefs:
# * Canon listdefs are "concrete" when they describe the raw address from which the data was fetched. Like "imdb=0123456789".
# * Canon listdefs are "abstract" when they describe a configured list. Like "list=watched".

class SpecialListType(enum.StrEnum):
    ALL         = '*'           # *[=]                  All configured simple lists.
    DEFAULTS    = 'defaults'    # defaults[=]           All configured as default lists. We have different defaults for fetch vs find.
    SIMPLE      = 'list'        # list=<uid>            A simple list. Lists which are just a name for the raw data list from the source.
    COMPOSITE   = 'composite'   # composite=<uid>       A composite list. Lists which are a combination of other lists with a filter.
    ANONYMOUS   = 'anonymous'   # anonymous='<listdef1> <listdef2> ... <listdefN>'  For internal use only - anonymous composites. Composite lists which are not preconfigured but spun on-the-fly.
    
    def __repr__(self) -> str:
        return str(self)

class ExpandFlavor(enum.Enum):
    FIND        = enum.auto()
    FETCH       = enum.auto()

# Users input LISTDEF strings and we turn them into this more convenient representation.
class CanonListdef(typing.NamedTuple):
    list_type: str
    address: str

    @classmethod
    def parse(cls, listdef: str, ctx: _ctx.FlamContext) -> CanonListdef:
        eq_idx = listdef.find('=')
        before_eq, after_eq = (listdef[:eq_idx], listdef[eq_idx + 1:]) if eq_idx != -1 else (listdef, '')
        result: None | CanonListdef = None

        # First case, DEFAULTS or ALL.
        if before_eq == SpecialListType.DEFAULTS or before_eq == SpecialListType.ALL:
            # We (reluctantly) support a trailing '=' for ALL and DEFAULTS so that this function and __str__ inverse each other. But it must be trailing.
            if after_eq != '':
                raise _exc.InputError(f"Invalid LISTDEF: '{listdef}' must have nothing after the equal sign.")

            result = cls(before_eq, after_eq)
        # For simple/composite lists we need to convert the name to a uid.
        elif eq_idx != -1 and (before_eq == SpecialListType.SIMPLE or before_eq == SpecialListType.COMPOSITE):
            result = ctx.cfg_readonly.lists_of_type(before_eq).get_by_name(after_eq).abstract_listdef
        # The generic case where it's whatever=whatever. This includes SpecialListType.ANONYMOUS.
        elif eq_idx != -1:
            result = cls(before_eq, after_eq)
        # If no '=' sign then we'll treat it as a simple list or composite list, and try to determine which.
        else:
            for list_type in (SpecialListType.SIMPLE, SpecialListType.COMPOSITE):
                try:
                    result = ctx.cfg_readonly.lists_of_type(list_type).get_by_name(before_eq).abstract_listdef
                    break
                except _exc.InputError:
                    pass

        if result is None:
            raise _exc.InputError(f"Invalid LISTDEF: '{listdef}'.")

        _dbg.logger.info(f"Parsed {listdef=}, split into: {before_eq=}, {after_eq=}. {result=}.")
        return result

    @classmethod
    def parse_and_expand(cls, listdefs: typing.Iterable[str], ctx: _ctx.FlamContext, flavor: ExpandFlavor) -> typing.Iterable[CanonListdef]:
        for ldef in listdefs:
            cldef = cls.parse(ldef, ctx)
            
            for expanded in cldef.expand(ctx, flavor):
                _dbg.logger.info(f"Expansion of {cldef} includes {expanded}")
                yield expanded

    def expand(self, ctx: _ctx.FlamContext, flavor: ExpandFlavor) -> typing.Iterable[CanonListdef]:
        match self.list_type:
            case SpecialListType.ALL:
                yield from (sl.abstract_listdef for sl in ctx.cfg_readonly.simple_lists)
            case SpecialListType.DEFAULTS:
                match flavor:
                    case ExpandFlavor.FIND:
                        yield from (sl.abstract_listdef for sl in ctx.cfg_readonly.simple_lists if sl.is_default_find)
                        yield from (cl.abstract_listdef for cl in ctx.cfg_readonly.composite_lists if cl.is_default_find)
                    case ExpandFlavor.FETCH:
                        yield from (sl.abstract_listdef for sl in ctx.cfg_readonly.simple_lists if sl.is_default_fetch)

                        # Composite lists are not atomic for fetch, so after expanding to the defaults, we must double expand them.
                        yield from (
                            dbl_expanded
                            for cl in ctx.cfg_readonly.composite_lists if cl.is_default_fetch
                                for dbl_expanded in cl.abstract_listdef.expand(ctx, flavor)
                        )
                    case _:
                        raise RuntimeError(f"Unexpected {flavor=}")
            case SpecialListType.COMPOSITE:
                match flavor:
                    case ExpandFlavor.FIND:
                        yield self
                    case ExpandFlavor.FETCH:
                        # Can't fetch composite lists, they must be expanded into simple lists.
                        composite_list = ctx.cfg_readonly.composite_lists.get_by_uid(self.address)
                        yield from (CanonListdef(SpecialListType.SIMPLE, sl_uid) for sl_uid in composite_list.simple_list_uids)
                    case _:
                        raise RuntimeError(f"Unexpected {flavor=}")
            case SpecialListType.ANONYMOUS:
                # Fully supporting anonymous lists is both unneeded and will require complicating a lot of code with recursion.
                # This list type is only meant for internal use and we'll assume that it's made up of already expanded parts.
                raise _exc.InputError("Anonymous lists do not support expansion.")
            case SpecialListType.SIMPLE | _:
                yield self

    @property
    def is_special(self) -> bool:
        return self.list_type in SpecialListType

    # SimpleList/CompositeList listdefs are abstract because they can't be fetched directly, only through the underlying "concrete" type.
    @property
    def is_abstract(self) -> bool:
        match self.list_type:
            case SpecialListType.SIMPLE | SpecialListType.COMPOSITE | SpecialListType.ANONYMOUS:
                return True
            case _:
                return False

    # "Concrete" listdefs have a type that directly corresponds to a ListFetcher.
    @property
    def is_concrete(self) -> bool:
        return not self.is_special

    # Internally when canonicalizing listdefs it's convenient to convert list names to UIDs,
    # but it means that whenever we print the listdef we need to convert it back to have human-readable list names.
    def pretty(self, ctx: _ctx.FlamContext) -> str:
        # Printing the "anonymous=" part isn't pretty. Since anonymous lists are only ever stringified for pretty printing,
        # the lists that make it up are already pretty.
        if self.list_type == SpecialListType.ANONYMOUS:
            return self.address
        
        if self.is_abstract:
            # Note that we're constructing a "CanonListdef" here which technically isn't "Canon". If you were to pretty() it, it will hit an error.
            # But it's ok because we're doing it internally and not returning it.
            return str(CanonListdef(self.list_type, ctx.cfg_readonly.get_list_by_abstract_listdef(self).name))
        
        return str(self)

    def __str__(self) -> str:
        return f'{self.list_type}={self.address}'

_dbg.logger.info(f'Module import time: {time.time() - _start_import_time}s')
