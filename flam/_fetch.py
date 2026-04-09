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

import abc
import typing
import re
import os
import contextlib
import copy

from . import _ldef
from . import _mlf
from . import _exc
from . import _ctx
from . import _dbg

class ListFetcher(abc.ABC):
    # These are READ ONLY. We would wrap them in a propety but classmethod-properties are not supported.
    # We would UPPERCASE them to communicate that they're constants but the registry infra expects the name to be lowercased.
    qualified_name: str
    qualified_aliases: list[str]
    uid_family: str

    # Subclasses must provide a list_type, and may optionally provide an uid_family if they have multiple fetchers that they want to be compatible.
    def __init_subclass__(cls, list_type: str, qualified_aliases: None | list[str] = None, uid_family: None | str = None, **kwargs: typing.Any) -> None:
        super().__init_subclass__(**kwargs)

        # I like the name list_type better, but for registration it needs to be named "qualified_name".
        cls.qualified_name = list_type
        cls.qualified_aliases = [] if qualified_aliases is None else qualified_aliases
        cls.uid_family = uid_family if uid_family is not None else list_type

    def __init__(self, concrete_listdef: _ldef.CanonListdef, abstract_listdef: _ldef.CanonListdef, ctx: _ctx.FlamContext) -> None:
        self._concrete_listdef = concrete_listdef
        self._abstract_listdef = abstract_listdef
        self._ctx = ctx

    @property
    def concrete_listdef(self) -> _ldef.CanonListdef:
        return self._concrete_listdef

    @property
    def abstract_listdef(self) -> _ldef.CanonListdef:
        return self._abstract_listdef

    def fetch(self, movie_list_file: _mlf.MovieListFile, refetch_re: None | re.Pattern, quiet: bool) -> None:
        _dbg.logger.info(f"Running fetcher {type(self)=}, abstract={self.abstract_listdef}, concrete={self.concrete_listdef}")

        if refetch_re is not None:
            nmovies_before = len(movie_list_file.movies_by_uid)
            npeople_before = len(movie_list_file.people_by_uid)
            
            movie_list_file.movies_by_uid = {
                uid: mlf_movie
                for uid, mlf_movie in movie_list_file.movies_by_uid.items()
                if not refetch_re.search(mlf_movie.title)
            }

            _remove_unused_people(movie_list_file)
            _dbg.logger.info(f"Refetch pattern removed {len(movie_list_file.movies_by_uid) - nmovies_before} movies, {len(movie_list_file.people_by_uid) - npeople_before} people")

        with open(os.devnull, 'w') as devnull, contextlib.redirect_stdout(devnull) if quiet else contextlib.nullcontext():
            print(f"Fetching '{self.abstract_listdef.pretty(self._ctx)}'...")

            try:
                self.fetch_into_file(movie_list_file)
            except _exc.FetchInterrupt as e:
                # Do this part even in case of FetchInterrupt because we intend to save the partial data.
                self._postprocess_fetched_file(movie_list_file)
                raise _exc.FetchInterrupt(f"Fetching of '{self.abstract_listdef.pretty(self._ctx)}' got interrupted due to {e}. "
                    "You may retry to pick up where it left off.") from e

        self._postprocess_fetched_file(movie_list_file)

    def _postprocess_fetched_file(self, movie_list_file: _mlf.MovieListFile) -> None:
        # Fetcher may have removed some movies from the list. Over here we remove people who are orphaned because of that.
        _remove_unused_people(movie_list_file)

        # Set these in the end in case fetch_into_file wrote some bad data there.
        movie_list_file.uid_family = self.uid_family
        movie_list_file.abstract_listdef = self.abstract_listdef

        # Scan the per_src_data of movies for correctness and also assist the users a bit with the listdef field.
        for mlf_movie in movie_list_file.movies_by_uid.values():
            if len(mlf_movie.per_src_data) != 1:
                # Not a FlamError because it shouldn't happen to users unless the developer of the fetcher wrote a bug.
                raise RuntimeError(f"Movie {mlf_movie.uid} was fetched incorrectly with {len(mlf_movie.per_src_data)} movies (should be exactly 1).")

            mlf_movie.per_src_data[0].canon_listdef = self.abstract_listdef

    # Fetching can run for many hours and it's a bitch when bash crashes or something midrun. So fetchers can use this to save progress in the middle.
    def checkpoint(self, movie_list_file: _mlf.MovieListFile) -> None:
        _dbg.logger.info(f"Checkpointing file for fetcher {type(self)=}, abstract={self.abstract_listdef}, concrete={self.concrete_listdef}")

        # Create a copy because we'll be modifying it a bit before we save and we don't want to modify the file the fetcher is operating on.
        # I considered sweeping errors in checkpointing under the rug but I think it's better to enforce correct use of this function.
        mlf_copy = copy.deepcopy(movie_list_file)
        self._postprocess_fetched_file(mlf_copy)
        self._ctx._close_fetch(None, mlf_copy)

    @abc.abstractmethod
    def fetch_into_file(self, movie_list_file: _mlf.MovieListFile) -> None:
        # Populates movie_list_file with data. It may already have preexisting data if updating an existing file.
        pass

def _remove_unused_people(movie_list_file: _mlf.MovieListFile) -> None:
    used_person_uids = set(
        role.person_uid
        for mlf_movie in movie_list_file.movies_by_uid.values()
            for crew in mlf_movie.crew.values()
                for role in crew.roles_by_uid.values()
    )
    
    movie_list_file.people_by_uid = {uid: person for uid, person in movie_list_file.people_by_uid.items() if uid in used_person_uids}
