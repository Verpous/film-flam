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

import os
import re
import copy
import abc
import typing
import contextlib

import filmflam.repo as repo
import filmflam.exceptions as exceptions
import filmflam._utils as utils

class ListFetcher(abc.ABC):
    @classmethod
    @abc.abstractmethod
    def fetcher_type(cls) -> str:
        pass

    def __init__(self, concrete_listdef: repo.CanonListdef, abstract_listdef: repo.CanonListdef) -> None:
        self.concrete_listdef = concrete_listdef
        self.abstract_listdef = abstract_listdef

    def id_type(self) -> str:
        # Default ID type you can override.
        return self.fetcher_type()

    @abc.abstractmethod
    def fetch_into_file(self, list_file: repo.ListFile) -> None:
        # Populates list_file with data. It may already have preexisting data if the file already existed.
        pass

    def fetch(self, ctx: repo.FlamContext, refetch_pattern: None | str = None, from_scratch: bool = False, quiet: bool = True) -> tuple[repo.ListFile, bool]:
        try:
            refetch_re = re.compile(refetch_pattern, flags=re.IGNORECASE) if refetch_pattern is not None else None
        except re.error as e:
            raise exceptions.InputError(f"Invalid PATTERN: '{refetch_pattern}': {e}")

        list_file = repo.ListFile.create() if from_scratch else ctx.load_list_file(self.abstract_listdef, must_exist=False)
        list_file_before = copy.deepcopy(list_file)
        id_type = self.id_type()
        interrupt_error = None

        if not isinstance(list_file_before.id_type, repo.UnsetType) and list_file_before.id_type != id_type:
            raise RuntimeError(f"Cannot fetch '{ctx.canon_listdef_pretty(self.abstract_listdef)}' because it's already fetched with a different ID type. "
                f"Old type: {list_file_before.id_type}, new type: {id_type}. "
                "This can happen if you changed a list's LISTDEF to a nonmatching type. You can resolve it by fetching the list from scratch.")

        if refetch_re is not None:
            list_file.movies_by_uid = {uid: movie_lf
                                        for uid, movie_lf in list_file.movies_by_uid.items()
                                        if not isinstance(movie_lf.title, repo.UnsetType) and not refetch_re.search(movie_lf.title)}
            _remove_unused_people(list_file)

        with open(os.devnull, 'w') as devnull, contextlib.redirect_stdout(devnull) if quiet else contextlib.nullcontext():
            try:
                self.fetch_into_file(list_file)
            except exceptions.FetchInterrupt as e:
                interrupt_error = e

        # Fetcher may have removed some movies from the list. Over here we remove people who are orphaned because of that.
        _remove_unused_people(list_file)

        list_file.id_type = id_type
        list_file.fetcher_type = self.abstract_listdef.fetcher_type
        list_file.address = self.abstract_listdef.address

        # Must canonicalize before comparing for equality.
        list_file.canonicalize()

        # We'll only write the new contents if they're different than before, and we'll return whether there was a diff or not.
        # This allows us to check the file mtime to know if it's dirty and dependent files need to be regenerated.
        is_changed = list_file_before != list_file

        if is_changed:
            ctx.write_list_file(list_file)

        if interrupt_error is not None:
            raise exceptions.FetchInterrupt(f"Fetching of {ctx.canon_listdef_pretty(self.abstract_listdef)} got interrupted due to error: {interrupt_error}. "
                "You may retry to pick up where it left off.")

        return list_file, is_changed

def _get_fetcher(canon_listdef: repo.CanonListdef, ctx: repo.FlamContext) -> ListFetcher:
    # Avoid cyclic dependency by importing fetchers only here. Incidentally this is also what we do for custom fetchers, but for different reasons.
    # The import may seem unused but we obtain imported classes via subclasses_recursive.
    import filmflam._imdb # pylint: disable=unused-import, cyclic-import
    
    if canon_listdef.is_abstract:
        # Assume it's a RemoteList.
        abstract_listdef = canon_listdef
        concrete_listdef = ctx.cfg.get_remote_list_by_uid(abstract_listdef.address).concrete_listdef
    else:
        abstract_listdef = concrete_listdef = canon_listdef

    for _ in range(2):
        for fetcher_cls in utils.subclasses_recursive(ListFetcher):
            fetcher_cls_safe = typing.cast(typing.Type[ListFetcher], fetcher_cls)

            if concrete_listdef.fetcher_type == fetcher_cls_safe.fetcher_type():
                return fetcher_cls_safe(concrete_listdef, abstract_listdef)

        # Failed to find it in the first iteration. It may still be a non-builtin type though.
        # Try importing a custom module named with a convention that means it should have the fetcher we seek, then seek again.
        # This way we don't import any random file named with this convention without the user explicitly asking for it, which would be a security risk.
        try:
            utils.import_from_path(f'flam_fetcher_{concrete_listdef.fetcher_type}')
        except ImportError:
            break

    raise exceptions.InputError(f"Invalid LISTDEF: '{concrete_listdef}': type is unknown.")

def parse_listdefs(listdefs: typing.Iterable[str], ctx: repo.FlamContext) -> list[ListFetcher]:
    cldefs = ctx.canonicalize_listdefs_with_all_expansion(listdefs)
    expanded = set(_expand_listdefs(cldefs, ctx))

    # Returns a list not a generator so that if one of the listdefs doesn't parse good we will raise an error now and not before fetching a few.
    return [_get_fetcher(cldef, ctx) for cldef in expanded]

def _expand_listdefs(canon_listdefs: typing.Iterable[repo.CanonListdef], ctx: repo.FlamContext) -> typing.Iterator[repo.CanonListdef]:
    for cldef in canon_listdefs:
        match cldef.fetcher_type:
            case repo.LISTDEF_DEFAULTS:
                yield from (rl.abstract_listdef for rl in ctx.cfg.remote_lists if rl.is_default_fetch)

                # Default compound lists... yeah.
                yield from (repo.CanonListdef(repo.RemoteList.FETCHER_TYPE, rl_uid)
                            for cl in ctx.cfg.compound_lists if cl.is_default_fetch
                                for rl_uid in cl.remote_list_uids)
            case repo.CompoundList.FETCHER_TYPE:
                compound_list = ctx.cfg.get_compound_list_by_uid(cldef.address)
                yield from (repo.CanonListdef(repo.RemoteList.FETCHER_TYPE, rl_uid) for rl_uid in compound_list.remote_list_uids)
            case _: # RemoteList.FETCHER_TYPE or a "concrete" type.
                yield cldef

def _get_all_used_person_uids(list_file: repo.ListFile) -> typing.Iterator[str]:
    for movie_lf in list_file.movies_by_uid.values():
        for crew in movie_lf.crew.values():
            for role in crew.roles_by_uid.values():
                yield role.person_uid

def _remove_unused_people(list_file: repo.ListFile) -> None:
    used_person_uids = set(_get_all_used_person_uids(list_file))
    list_file.people_by_uid = {uid: person for uid, person in list_file.people_by_uid.items() if uid in used_person_uids}
