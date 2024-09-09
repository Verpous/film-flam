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

import typing
import enum
import shlex

from . import _ctx
from . import _xcept
from . import _filter

class SpecialListType(enum.StrEnum):
    ALL         = '*'           # *[=]
    DEFAULTS    = 'defaults'    # defaults[=]
    REMOTE      = 'list'        # list=<uid>
    COMPOSITE   = 'composite'   # composite=<uid>
    ANNONYMOUS  = 'annonymous'  # annonymous='<listdef1> <listdef2> ... <listdefN>' (for internal use only)

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

        # First case, DEFAULTS or ALL.
        if before_eq == SpecialListType.DEFAULTS or before_eq == SpecialListType.ALL:
            # We (reluctantly) support a trailing '=' for ALL and DEFAULTS so that this function and __str__ inverse each other. But it must be trailing.
            if after_eq != '':
                raise _xcept.InputError(f"Invalid LISTDEF: '{listdef}' must have nothing after the equal sign.")

            return cls(before_eq, after_eq)

        # For remote/composite lists we need to convert the name to a uid.
        if eq_idx != -1 and (before_eq == SpecialListType.REMOTE or before_eq == SpecialListType.COMPOSITE):
            return ctx.lists_of_type(before_eq).get_by_name(after_eq).abstract_listdef

        # The generic case where it's whatever=whatever. This includes SpecialListType.ANNONYMOUS.
        if eq_idx != -1:
            return cls(before_eq, after_eq)
        
        # If no '=' sign then we'll treat it as a remote list or composite list, and try to determine which.
        for list_type in (SpecialListType.REMOTE, SpecialListType.COMPOSITE):
            try:
                return ctx.lists_of_type(list_type).get_by_name(after_eq).abstract_listdef
            except _xcept.InputError:
                pass

        raise _xcept.InputError(f"Invalid LISTDEF: '{listdef}'.")

    @classmethod
    def parse_and_expand(cls, listdefs: typing.Iterable[str], ctx: _ctx.FlamContext, flavor: ExpandFlavor) -> typing.Iterator[CanonListdef]:
        for ldef in listdefs:
            cldef = cls.parse(ldef, ctx)
            yield from cldef.expand(ctx, flavor)

    def expand(self, ctx: _ctx.FlamContext, flavor: ExpandFlavor) -> typing.Iterator[CanonListdef]:
        match self.list_type:
            case SpecialListType.ALL:
                yield from (rl.abstract_listdef for rl in ctx.remote_lists)
            case SpecialListType.DEFAULTS:
                match flavor:
                    case ExpandFlavor.FIND:
                        yield from (rl.abstract_listdef for rl in ctx.remote_lists if rl.is_default_fetch)
                        yield from (cl.abstract_listdef for cl in ctx.composite_lists if cl.is_default_fetch)
                    case ExpandFlavor.FETCH:
                        yield from (rl.abstract_listdef for rl in ctx.remote_lists if rl.is_default_fetch)

                        # Composite lists are not atomic for fetch, so after expanding to the defaults, we must double expand them.
                        yield from (
                            dbl_expanded
                            for cl in ctx.composite_lists if cl.is_default_fetch
                                for dbl_expanded in cl.abstract_listdef.expand(ctx, flavor)
                        )
                    case _:
                        raise RuntimeError(f"Unsupported ExpandFlavor: {flavor}")
            case SpecialListType.COMPOSITE:
                match flavor:
                    case ExpandFlavor.FIND:
                        yield self
                    case ExpandFlavor.FETCH:
                        # Can't fetch composite lists, they must be expanded into remote lists.
                        composite_list = ctx.composite_lists.get_by_uid(self.address)
                        yield from (CanonListdef(SpecialListType.REMOTE, rl_uid) for rl_uid in composite_list.remote_list_uids)
                    case _:
                        raise RuntimeError(f"Unsupported ExpandFlavor: {flavor}")
            case SpecialListType.ANNONYMOUS:
                # Fully supporting annonymous lists is both unneeded and will require complicating a lot of code with recursion.
                # This list type is only meant for internal use and we'll assume that it's made up of already expanded parts.
                raise _xcept.InputError(f"Annonymous lists do not support expansion.")
            case SpecialListType.REMOTE | _:
                yield self

    @property
    def is_special(self) -> bool:
        return self.list_type in SpecialListType

    # RemoteList/CompositeList listdefs are abstract because they can't be fetched directly, only through the underlying "concrete" type.
    @property
    def is_abstract(self) -> bool:
        match self.list_type:
            case SpecialListType.REMOTE | SpecialListType.COMPOSITE | SpecialListType.ANNONYMOUS:
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
        # Annonymous lists need to separate the filter from the listdefs, and then recursively pretty the listdefs.
        if self.list_type == SpecialListType.ANNONYMOUS:
            listdefs_and_filter = shlex.split(self.address)
            listdefs, filter = _filter.split_at_filter(listdefs_and_filter)

            # Not shlex.joining them back together because it's ugly. Rather live with the "incorrectness".
            listdefs_rejoined = ' '.join(self.parse(ldef, ctx).pretty(ctx) for ldef in listdefs)
            return f"{listdefs_rejoined}{' ' if len(filter) > 0 else ''}{' '.join(filter)}"
        
        if self.is_abstract:
            # Note that we're constructing a "CanonListdef" here which technically isn't "Canon". If you were to pretty() it, it will hit an error.
            # But it's ok because we're doing it internally and not returning it.
            return str(CanonListdef(self.list_type, ctx.get_list_by_abstract_listdef(self).name))
        
        return str(self)

    def __str__(self) -> str:
        return f'{self.list_type}={self.address}'
    