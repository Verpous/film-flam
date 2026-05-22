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
import enum

from . import _ctx
from . import _exc
from . import _dbg

class CanonListdef(typing.NamedTuple):
    """
    Represents a spec for identifying a list. Listdefs as a strings have the form "<list_type>=<address>", or sometimes just "<address>",
    and internally we "canonicalize" them into this object. This process involves:

    * Inferring the list type if it's missing - we're only able to infer the types for configured simple or composite lists
    * Handling some special values. See :py:class:`SpecialListType`.

    Some important things to know about listdefs:
    
    * Once they're past canonicalization, the special list types :py:attr:`SpecialListType.ALL` and :py:attr:`SpecialListType.DEFAULTS` are handled and you don't have to check for them
    * Simple/composite lists are described with the address being their name, but during canonicalization we change that to their UID
    * When printing a listdef to the user, it's best to format it :py:meth:`pretty` because that will convert these list uids back to their names
    
    Concrete and abstract canon listdefs:

    * Canon listdefs are "concrete" when they describe the raw address from which the data was fetched. E.g., "imdb-listid=083886771"
    * Canon listdefs are "abstract" when they describe a configured list. E.g., "list=watched"
    """

    list_type: str
    """
    The fetcher used to download information about this list. Also supports a few special values, see :py:class:`SpecialListType`.
    """

    address: str
    """
    An address pointing to an exact list. This could be different based on the list type - it could be a path, a URL, a name, or anything else.
    """

    @classmethod
    def _parse(cls, listdef: str, ctx: _ctx.FlamContext) -> CanonListdef:
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

        _dbg.logger.info(f"Parsed {listdef=}, split into: {before_eq=}, {after_eq=}. {result=}")
        return result

    @classmethod
    def _parse_and_expand(cls, listdefs: typing.Iterable[str], ctx: _ctx.FlamContext, flavor: _ExpandFlavor) -> typing.Iterable[CanonListdef]:
        for ldef in listdefs:
            cldef = cls._parse(ldef, ctx)
            
            for expanded in cldef._expand(ctx, flavor):
                _dbg.logger.info(f"Expansion of {cldef} includes {expanded}")
                yield expanded

    def _expand(self, ctx: _ctx.FlamContext, flavor: _ExpandFlavor) -> typing.Iterable[CanonListdef]:
        match self.list_type:
            case SpecialListType.ALL:
                yield from (sl.abstract_listdef for sl in ctx.cfg_readonly.simple_lists)
            case SpecialListType.DEFAULTS:
                match flavor:
                    case _ExpandFlavor.FIND:
                        yield from (sl.abstract_listdef for sl in ctx.cfg_readonly.simple_lists if sl.is_default_find)
                        yield from (cl.abstract_listdef for cl in ctx.cfg_readonly.composite_lists if cl.is_default_find)
                    case _ExpandFlavor.FETCH:
                        # Only simple lists support default_fetch because it makes no sense for composites.
                        yield from (sl.abstract_listdef for sl in ctx.cfg_readonly.simple_lists if sl.is_default_fetch)
                    case _:
                        raise RuntimeError(f"Unexpected {flavor=}.")
            case SpecialListType.COMPOSITE:
                match flavor:
                    case _ExpandFlavor.FIND:
                        yield self
                    case _ExpandFlavor.FETCH:
                        # Can't fetch composite lists, they must be expanded into simple lists.
                        composite_list = ctx.cfg_readonly.composite_lists.get_by_uid(self.address)
                        yield from (CanonListdef(SpecialListType.SIMPLE, sl_uid) for sl_uid in composite_list.simple_list_uids)
                    case _:
                        raise RuntimeError(f"Unexpected {flavor=}.")
            case SpecialListType.ANONYMOUS:
                # Fully supporting anonymous lists is both unneeded and will require complicating a lot of code with recursion.
                # This list type is only meant for internal use and we'll assume that it's made up of already expanded parts.
                raise _exc.InputError("Anonymous lists do not support expansion.")
            case SpecialListType.SIMPLE | _:
                yield self

    @property
    def is_special(self) -> bool:
        """
        Whether this listdef has a special type.
        """
        return self.list_type in SpecialListType

    # SimpleList/CompositeList listdefs are abstract because they can't be fetched directly, only through the underlying "concrete" type.
    @property
    def is_abstract(self) -> bool:
        """
        Whether this listdef is "abstract", meaning it describes a configured list. E.g., "list=watched".
        """
        match self.list_type:
            case SpecialListType.SIMPLE | SpecialListType.COMPOSITE | SpecialListType.ANONYMOUS:
                return True
            case _:
                return False

    # "Concrete" listdefs have a type that directly corresponds to a Fetcher.
    @property
    def is_concrete(self) -> bool:
        """
        Whether this listdef is "concrete", meaning it describes a raw address from which the data was fetched. E.g., "imdb-listid=083886771".
        """
        return not self.is_special

    # Internally when canonicalizing listdefs it's convenient to convert list names to UIDs,
    # but it means that whenever we print the listdef we need to convert it back to have human-readable list names.
    def pretty(self, ctx: _ctx.FlamContext) -> str:
        """
        Returns a pretty string representation of this listdef. Use this so configured lists will be printed with their name instead of a long ugly UID.

        :param ctx: the context containing list configurations we need to know.
        """
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

class SpecialListType(enum.StrEnum):
    """
    An enumeration of special listdef types.
    """
    ALL         = '*'
    """All configured simple lists."""
    
    DEFAULTS    = 'defaults'
    """All configured as default lists. We have different defaults for fetch vs find."""
    
    SIMPLE      = 'list'
    """A simple list. Lists which are just a name for the raw data list from the source. Outwardly uses the name as the address, but internally uses a uid."""
    
    COMPOSITE   = 'composite'
    """A composite list. Lists which are a combination of other lists with a filter. Outwardly uses the name as the address, but internally uses a uid."""
    
    # Has the string form 'anonymous=<listdef1> <listdef2> ... <listdefN>'
    ANONYMOUS   = 'anonymous'
    """FOR INTERNAL USE ONLY - anonymous composites. Composite lists which are not preconfigured but spun on-the-fly."""
    
    def __repr__(self) -> str:
        return str(self)

class _ExpandFlavor(enum.Enum):
    FIND        = enum.auto()
    FETCH       = enum.auto()
