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

import abc
import typing
import re
import os
import contextlib

from . import _ldef
from . import _mlf
from . import _exc
from . import _ctx
from . import _file
from . import _dbg

class ListFetcher(abc.ABC):
    list_type: str
    uid_type: str

    # Subclasses must provide a list_type, and may optionally provide an uid_type if they have multiple fetchers that they want to be compatible.
    def __init_subclass__(cls, list_type: str, uid_type: None | str = None, **kwargs: typing.Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.list_type = list_type
        cls.uid_type = uid_type if uid_type is not None else list_type

    def __init__(self, concrete_listdef: _ldef.CanonListdef, abstract_listdef: _ldef.CanonListdef) -> None:
        self._concrete_listdef = concrete_listdef
        self._abstract_listdef = abstract_listdef

    @property
    def concrete_listdef(self) -> _ldef.CanonListdef:
        return self._concrete_listdef

    @property
    def abstract_listdef(self) -> _ldef.CanonListdef:
        return self._abstract_listdef

    def fetch(self, movie_list_file: _mlf.MovieListFile, ctx: _ctx.FlamContext, refetch_re: None | re.Pattern, quiet: bool) -> None:
        if not isinstance(movie_list_file.uid_type, _file.UnsetType) and movie_list_file.uid_type != self.uid_type:
            raise _exc.InputError(f"Cannot fetch '{self.abstract_listdef.pretty(ctx)}' because it's already fetched with a different ID type "
                f"(old: '{movie_list_file.uid_type}', new: '{self.uid_type}'). "
                "This can happen if you changed a list's LISTDEF to a nonmatching type. You can resolve it by fetching the list from scratch, or reverting the list to its old type.")

        _dbg.logger.info(f"Running fetcher {type(self)=}, abstract={self.abstract_listdef}, concrete={self.concrete_listdef}")
        interrupt_error = None

        if refetch_re is not None:
            nmovies_before = len(movie_list_file.movies_by_uid)
            npeople_before = len(movie_list_file.people_by_uid)
            
            movie_list_file.movies_by_uid = {
                uid: mlf_movie
                for uid, mlf_movie in movie_list_file.movies_by_uid.items()
                if not isinstance(mlf_movie.title, _file.UnsetType) and not refetch_re.search(mlf_movie.title)
            }

            _remove_unused_people(movie_list_file)
            _dbg.logger.info(f"Refetch pattern removed {len(movie_list_file.movies_by_uid) - nmovies_before} movies, {len(movie_list_file.people_by_uid) - npeople_before} people")

        with open(os.devnull, 'w') as devnull, contextlib.redirect_stdout(devnull) if quiet else contextlib.nullcontext():
            print(f"Fetching '{self.abstract_listdef.pretty(ctx)}'...")

            try:
                self.fetch_into_file(movie_list_file)
            except _exc.FetchInterrupt as e:
                interrupt_error = e

        # Fetcher may have removed some movies from the list. Over here we remove people who are orphaned because of that.
        _remove_unused_people(movie_list_file)

        movie_list_file.uid_type = self.uid_type
        movie_list_file.list_type = self.abstract_listdef.list_type
        movie_list_file.address = self.abstract_listdef.address

        if interrupt_error is not None:
            raise _exc.FetchInterrupt(f"Fetching of '{self.abstract_listdef.pretty(ctx)}' got interrupted due to {interrupt_error}. "
                "You may retry to pick up where it left off.")

    @abc.abstractmethod
    def fetch_into_file(self, movie_list_file: _mlf.MovieListFile) -> None:
        # Populates movie_list_file with data. It may already have preexisting data if updating an existing file.
        # Must leave no field unset. Even if it's an optional field it must explicitly be set to None.
        pass

def _remove_unused_people(movie_list_file: _mlf.MovieListFile) -> None:
    used_person_uids = set(_get_all_used_person_uids(movie_list_file))
    movie_list_file.people_by_uid = {uid: person for uid, person in movie_list_file.people_by_uid.items() if uid in used_person_uids}

def _get_all_used_person_uids(movie_list_file: _mlf.MovieListFile) -> typing.Iterator[str]:
    for mlf_movie in movie_list_file.movies_by_uid.values():
        for crew in mlf_movie.crew.values():
            for role in crew.roles_by_uid.values():
                yield role.person_uid
