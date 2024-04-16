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
import filmflam.common as common
import filmflam._utils as utils

class ListFetcher(abc.ABC):
    def __init__(self, canon_listdef: common.CanonListdef) -> None:
        self._canon_listdef = canon_listdef

    @property
    def canon_listdef(self) -> common.CanonListdef:
        return self._canon_listdef

    @classmethod
    @abc.abstractmethod
    def fetcher_type(cls) -> str:
        pass

    def id_type(self) -> str:
        # Default ID type you can override.
        return self.fetcher_type()

    @abc.abstractmethod
    def fetch(self, list_file: repo.ListFile) -> None:
        # Populates list_file with data. It may already have preexisting data if the file already existed.
        pass

def fetch(listdefs: list[str], ctx: repo.FlamContext, refetch_pattern: None | str = None, quiet: bool = True) -> list[tuple[bool, repo.ListFile]]:
    fetchers = _parse_listdefs(common.canonicalize_listdefs(listdefs, ctx), ctx)
    refetch_re = re.compile(refetch_pattern, flags=re.IGNORECASE) if refetch_pattern is not None else None
    fetched_remote_lists = []

    for fetcher in fetchers:
        id_type = fetcher.id_type()
        list_file = ctx.load_list_file(id_type, fetcher.canon_listdef.address, must_exist=False)
        list_file_before = copy.deepcopy(list_file)

        if refetch_re is not None:
            list_file.movies_by_uid = {uid: movie_lf
                                        for uid, movie_lf in list_file.movies_by_uid.items()
                                        if not isinstance(movie_lf.title, repo.UnsetType) and not refetch_re.search(movie_lf.title)}
            _remove_unused_people(list_file)

        with open(os.devnull, 'w') as devnull, contextlib.redirect_stdout(devnull) if quiet else contextlib.nullcontext():
            print(f'Fetching {fetcher.canon_listdef.fetcher_type}={fetcher.canon_listdef.address}...')
            fetcher.fetch(list_file)

        # Fetcher may have removed some movies from the list. Over here we remove people who are orphaned because of that.
        _remove_unused_people(list_file)

        list_file.id_type = id_type
        list_file.fetcher_type = fetcher.canon_listdef.fetcher_type
        list_file.address = fetcher.canon_listdef.address

        # Must canonicalize before comparing for equality.
        list_file.canonicalize()

        # We'll only write the new contents if they're different than before, and we'll return whether there was a diff or not.
        # This allows us to check the file mtime to know if it's dirty and dependent files need to be regenerated.
        is_diff = list_file_before != list_file

        if is_diff:
            ctx.write_list_file(list_file)

        fetched_remote_lists.append((is_diff, list_file))

    return fetched_remote_lists

def _get_fetcher(canon_listdef: common.CanonListdef) -> ListFetcher:
    # Avoid cyclic dependency by importing fetchers only here. Incidentally this is also what we do for custom fetchers, but for different reasons.
    # The import may seem unused but we obtain imported classes via subclasses_recursive.
    import filmflam._imdb # pylint: disable=unused-import, cyclic-import

    for _ in range(2):
        for fetcher_cls in utils.subclasses_recursive(ListFetcher):
            fetcher_cls_safe = typing.cast(typing.Type[ListFetcher], fetcher_cls)

            if canon_listdef.fetcher_type == fetcher_cls_safe.fetcher_type():
                return fetcher_cls_safe(canon_listdef)

        # Failed to find it in the first iteration. It may still be a non-builtin type though.
        # Try importing a custom module named with a convention that means it should have the fetcher we seek, then seek again.
        # This way we don't import any random file named with this convention without the user explicitly asking for it, which would be a security risk.
        try:
            utils.import_from_path(f'flam_fetcher_{canon_listdef.fetcher_type}')
        except ImportError:
            break

    raise KeyError(f'Invalid fetcher type: {canon_listdef.fetcher_type}.')

def _expand_listdefs(canon_listdefs: typing.Iterable[common.CanonListdef], ctx: repo.FlamContext) -> typing.Iterator[common.CanonListdef]:
    for cldef in canon_listdefs:
        match cldef.fetcher_type:
            case common.LISTDEF_DEFAULTS:
                yield from (common.CanonListdef(fetcher_type=rl.FETCHER_TYPE, address=rl.name) for rl in ctx.cfg.remote_lists if rl.is_default_fetch)
            case repo.RemoteList.FETCHER_TYPE:
                remote_list = next(rl for rl in ctx.cfg.remote_lists if rl.name == cldef.address)
                yield common.CanonListdef(fetcher_type=remote_list.fetcher_type, address=remote_list.address)
            case repo.CompoundList.FETCHER_TYPE:
                compound_list = next(cl for cl in ctx.cfg.remote_lists if cl.name == cldef.address)

                for rl_name in compound_list.remote_list_names:
                    remote_list = next(rl for rl in ctx.cfg.remote_lists if rl.name == rl_name)
                    yield common.CanonListdef(fetcher_type=remote_list.fetcher_type, address=remote_list.address)
            case _:
                yield cldef

def _parse_listdefs(canon_listdefs: typing.Iterable[common.CanonListdef], ctx: repo.FlamContext) -> list[ListFetcher]:
    expanded_listdefs = set(_expand_listdefs(canon_listdefs, ctx))

    # Returns a list not a generator so that if one of the listdefs doesn't parse good we will raise an error now and not before fetching a few.
    return [_get_fetcher(cldef) for cldef in expanded_listdefs]

def _get_all_used_person_uids(list_file: repo.ListFile) -> typing.Iterator[str]:
    for movie_lf in list_file.movies_by_uid.values():
        for crew in movie_lf.crew.values():
            for role in crew.roles_by_uid.values():
                yield role.person_uid

def _remove_unused_people(list_file: repo.ListFile) -> None:
    used_person_uids = set(_get_all_used_person_uids(list_file))
    list_file.people_by_uid = {uid: person for uid, person in list_file.people_by_uid.items() if uid in used_person_uids}
