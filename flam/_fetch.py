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

from . import _ldef
from . import _mlf
from . import _exc
from . import _ctx
from . import _dbg

class Fetcher(abc.ABC):
    """
    Base class for all fetchers. Fetchers are in charge of actually downloading data about movie lists from some source like IMDb, Letterboxd, etc.

    You can extend flam by inheriting from this class and registering :ref:`your own custom fetchers <Implementing a custom fetcher>`.
    """
    # These are READ ONLY. We would wrap them in a propety but classmethod-properties are not supported.
    # We would UPPERCASE them to communicate that they're constants but the registry infra expects the name to be lowercased.
    qualified_name: str
    """
    The fetcher's name. This corresponds to a listdef's :py:attr:`~._ldef.CanonListdef.list_type`.
    """

    qualified_aliases: list[str]
    """
    List of aliases for the fetcher.
    """

    uid_family: str
    """
    The UID family this fetcher uses. Composite lists can only be formed from lists with the same UID family.
    
    Fetchers need to assign some unique string to each movie and person they download, but what exactly they use can vary from fetcher to fetcher.
    Usually they'll use the UIDs used by the source the data is fetched from.
    
    For example, a fetcher which sources its data from IMDb might identify a movie by the same ID IMDb identifies it with.
    But there are multiple APIs you could use to fetch data from IMDb. So you can implement multiple fetchers which all fetch from IMDb, but in different ways.
    If you make all those fetchers use the same UID family, then they will all be compatible with each other.
    """

    # Subclasses must provide a list_type, and may optionally provide an uid_family if they have multiple fetchers that they want to be compatible.
    def __init_subclass__(cls, list_type: str, qualified_aliases: None | list[str] = None, uid_family: None | str = None, **kwargs: typing.Any) -> None:
        """
        Defines parameters that subclasses can (or must) pass in as part of subclassing. Ex:

        .. code-block:: python

            class MyCustomFetcher(Fetcher, list_type='my-imdb-fetcher', uid_family='imdb'):
                # ...

        :param list_type: the name of this fetcher.
        :param qualified_aliases: list of aliases for this fetcher.
        :param uid_family: which UID family this fetcher uses. Defaults to ``list_type``, indicating this fetcher is only compatible with itself.
        """
        super().__init_subclass__(**kwargs)

        if list_type in _ldef.SpecialListType:
            raise _exc.InputError(f"List type '{list_type}' is reserved for internal use, please use a different name.")

        # I like the name list_type better, but for registration it needs to be named "qualified_name".
        cls.qualified_name = list_type
        cls.qualified_aliases = [] if qualified_aliases is None else qualified_aliases
        cls.uid_family = uid_family if uid_family is not None else list_type

    def __init__(self, concrete_listdef: _ldef.CanonListdef, abstract_listdef: _ldef.CanonListdef, fetch_params: dict[str, str], ctx: _ctx.FlamContext) -> None:
        self._concrete_listdef = concrete_listdef
        self._abstract_listdef = abstract_listdef
        self._fetch_params = fetch_params
        self._ctx = ctx

    @property
    def concrete_listdef(self) -> _ldef.CanonListdef:
        """
        The raw fetcher name and address to fetch from.
        """
        return self._concrete_listdef

    @property
    def abstract_listdef(self) -> _ldef.CanonListdef:
        """
        The simple list being fetched, if it is a simple list. Otherwise same as :py:attr:`concrete_listdef`.
        """
        return self._abstract_listdef

    def get_param(self, param_name: str) -> str:
        """
        Get the value of a fetch parameter.
        """
        try:
            return self._fetch_params[param_name]
        except KeyError as e:
            # Try case insensitive if not found easily.
            for k, v in self._fetch_params.items():
                if param_name.lower() == k.lower():
                    return v

            raise _exc.InputError(f"No such parameter: '{param_name}'.") from e

    def has_param(self, param_name: str) -> bool:
        """
        Check if fetcher has been passed this parameter.
        """
        # Try case insensitive if not found easily.
        return param_name in self._fetch_params or any(param_name.lower() == k.lower() for k in self._fetch_params)

    def _fetch(self, movie_list_file: _mlf.MovieListFile, refetch_re: None | re.Pattern, quiet: bool) -> None:
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
            _dbg.logger.info(f"Refetch pattern removed {nmovies_before - len(movie_list_file.movies_by_uid)} movies, {len(movie_list_file.people_by_uid) - npeople_before} people")

        with open(os.devnull, 'w') as devnull, contextlib.redirect_stdout(devnull) if quiet else contextlib.nullcontext():
            print(f"Fetching '{self.abstract_listdef.pretty(self._ctx)}'...")

            try:
                self._fetch_into_file(movie_list_file)
            except _exc.FetchInterrupt as e:
                # Do this part even in case of FetchInterrupt because we intend to save the partial data.
                self._postprocess_fetched_file(movie_list_file)
                raise _exc.FetchInterrupt(f"Fetching of '{self.abstract_listdef.pretty(self._ctx)}' got interrupted due to {e}. "
                    "You may retry to pick up where it left off.") from e

        self._postprocess_fetched_file(movie_list_file)

    def _postprocess_fetched_file(self, movie_list_file: _mlf.MovieListFile) -> None:
        # Fetcher may have removed some movies from the list. Over here we remove people who are orphaned because of that.
        _remove_unused_people(movie_list_file)

        # Set these in the end in case _fetch_into_file wrote some bad data there.
        movie_list_file.uid_family = self.uid_family
        movie_list_file.abstract_listdef = self.abstract_listdef

        # Scan the per_src_data of movies for correctness and also assist the users a bit with the listdef field.
        for mlf_movie in movie_list_file.movies_by_uid.values():
            if len(mlf_movie.per_src_data) != 1:
                # Not a FlamError because it shouldn't happen to users unless the developer of the fetcher wrote a bug.
                raise RuntimeError(f"Movie {mlf_movie.uid} was fetched incorrectly with {len(mlf_movie.per_src_data)} movies (should be exactly 1).")

            mlf_movie.per_src_data[0].canon_listdef = self.abstract_listdef

    @abc.abstractmethod
    def _fetch_into_file(self, movie_list_file: _mlf.MovieListFile) -> None:
        """
        .. note::

            This is an internal method of fetchers. Outside users shouldn't call it,
            but you need to implement it as part of :ref:`implementing a custom fetcher <Implementing a custom fetcher>`.
        
        Obtain data about the list identified by :py:attr:`concrete_listdef`, and populate ``movie_list_file`` with all the data fetched about movies in the list and the people in them.

        If this function raises :py:exc:`~._exc.FetchInterrupt`, everything written to the file so far will be saved to disk.

        There are a few sensitive points about the exact order that you populate this object with data:

        * Always add the people in a movie before you add the movie itself
        * Only add a movie object after it's fully populated with its data

        The above points ensure that the file is always in a good, saveable state. So if fetching gets interrupted or :py:meth:`_checkpoint` is called and the file is saved,
        it won't cause partially fetched movies to be in the file, which on the next fetch you won't know you have to re-fetch.

        :param movie_list_file: serializable object to populate with all the data we can get about the movie list.
            
            The only fields you should populate are :py:attr:`~._mlf.MovieListFile.movies_by_uid`, :py:attr:`~._mlf.MovieListFile.people_by_uid`. The rest are handled outside this fetcher.

            If the list was previously fetched, this object will contain all the data from the previous fetch.
            Use this fact to only fetch movies that weren't already fetched, which can save a lot of time.
            
            However, it's also your responsibility to remove movies from this file if they are no longer in the list.

            When removing movies that were previously fetched, you don't have to worry about also removing the people in those movies.
            That happens automatically before the file is saved.
        
        :meta public:
        """

    # Fetching can run for many hours and it's a bitch when bash crashes or something midrun. So fetchers can use this to save progress in the middle.
    def _checkpoint(self, movie_list_file: _mlf.MovieListFile) -> None:
        """
        Store the work-in-progress on this file to disk, so that if a crash happens the data fetched so far won't be lost.
        This method is meant to only be called internally from inside :py:meth:`_fetch_into_file`.
        
        You should only call this function during good save points. I.e., moments when the file doesn't contain any partially fetched movies.

        :param movie_list_file: the same object that was passed to :py:meth:`_fetch_into_file`.
        
        :meta public:
        """
        _dbg.logger.info(f"Checkpointing file for fetcher {type(self)=}, abstract={self.abstract_listdef}, concrete={self.concrete_listdef}")

        # Create a copy because we'll be modifying it a bit before we save and we don't want to modify the file the fetcher is operating on.
        # I considered sweeping errors in checkpointing under the rug but I think it's better to enforce correct use of this function.
        mlf_copy = movie_list_file.deepcopy()
        self._postprocess_fetched_file(mlf_copy)
        self._ctx._close_fetch(None, mlf_copy)

def _remove_unused_people(movie_list_file: _mlf.MovieListFile) -> None:
    used_person_uids = set(
        role.person_uid
        for mlf_movie in movie_list_file.movies_by_uid.values()
            for crew in mlf_movie.crew.values()
                for role in crew.roles_by_uid.values()
    )
    
    movie_list_file.people_by_uid = {uid: person for uid, person in movie_list_file.people_by_uid.items() if uid in used_person_uids}
