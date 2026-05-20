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

# TODO: if I upgrade to python 3.14 they have a change that probably makes this line no longer needed.
from __future__ import annotations

import os
import typing
import uuid
import re
import importlib
import tempfile
import weakref
import itertools
import difflib
import contextlib
import enum
import glob
import shutil
import datetime

from . import _cfg
from . import _exc
from . import _filter
from . import _ldef
from . import _mlf
from . import _mlv
from . import _ml
from . import _md
from . import _reg
from . import _fetch
from . import _dbg
from . import _attr
from . import _gen_version
from . import utils

# Without hide-value this would've shown a local path on my machine in the documentation.
DEFAULT_FLAM_DIR = _dbg.FlamEnv.CTX_DIR.get_or_default(os.path.join(os.path.expanduser('~'), '.film_flam'))
"""
The default path where flam stores all your movie lists and configuration. Equal to the environment variable **FLAM_DIR**, or ~/.film_flam if it's not defined.

:meta hide-value:
"""

class PrecachePreference(enum.IntEnum):
    """
    Preference for what you'd like to be cached. For use with :py:meth:`FlamContext.precache`.
    """
    DEFAULTS = enum.auto()
    """Generate all composite lists, and cache particularly expensive computations for all movie lists."""

    EVERYTHING = enum.auto()
    """Cache everything that can possibly be cached."""

    RESET = enum.auto()
    """Don't cache anything, instead delete existing cache files."""

# This class is the user's entry point to basically everything that is "built in" to this API: accessing lists, filtering, configuring.
# Important to have it as much at the top of the file as possible because I want this to be the first thing users see in the documentation.
class FlamContext:
    """
    Represents a user of a flam directory. All API use generally begins with creating a context, and anything you might do with flam generally goes through the context.

    Only one context is allowed per flam directory at any given time.
    """
    _MLF_DIR = 'movie_lists'
    _MLV_DIR = 'movie_list_vaults'
    _CACHE_DIR = 'cache'
    _CONFIG_FILE = 'config.json'
    _METADATA_FILE = 'metadata.json'

    def __init__(self, flam_dir: None | str = DEFAULT_FLAM_DIR, import_extensions: bool = False) -> None:
        """
        :param flam_dir: the directory where all movie lists and configuration should be stored. 
        
            If this is ``None``, flam will work in "volatile mode" - everything you fetch or configure will be lost when the context dies.
        :param import_extensions: import all configured extensions, and subscribe to globally registered extensions.
        
            .. warning::
            
                Only enable this if you trust the extensions in the configuration.
        """
        _dbg.logger.info(f"Making a context, {flam_dir=}, {import_extensions=}")

        # Support None for users who just want to work with volatile memory and not load or save anything, we call it volatile mode.
        # Don't tell this to anyone but in "volatile" mode we actually just persist everything to a tempdir. It's so, so much easier.
        if flam_dir is None:
            tempdir = tempfile.TemporaryDirectory(prefix='.film_flam.', ignore_cleanup_errors=not _dbg.is_debug()) # pylint: disable=consider-using-with
            self._flam_dir = tempdir.name

            # Deletes the tempdir when the object is garbage collected or program exits.
            weakref.finalize(self, tempdir.cleanup)
        else:
            # TODO: Acquire OS lock on the flam_dir so that you can't have multiple contexts operating on it at once?
            # I'll leave this idea for later, since I think we may need a "readonly" mode to allow multiple users on the same list...
            # and we'll need a way to "close" a context when done with it.
            self._flam_dir = os.path.abspath(flam_dir)

        self._make_flam_dir()

        try:
            self._cfg = _cfg.Configuration._load(self._cfg_path)
        except FileNotFoundError:
            _dbg.logger.info("Configuration file doesn't exist, creating a new one")
            self._cfg = _cfg.Configuration(
                version = _gen_version.__version__,
                simple_lists_raw = [],
                composite_lists_raw = [],
                extensions = [],
            )

            self._write_cfg()

        try:
            self._metadata = _md._FlamMetadata._load(self._metadata_path)
        except FileNotFoundError:
            _dbg.logger.info("Metadata file doesn't exist, creating a new one")
            self._metadata = _md._FlamMetadata(
                version = _gen_version.__version__,
                composite_lists_by_uid = {},
                movie_list_vaults = [],
            )

            self._write_metadata()

        # I wish I could print these prettier but it's not worth the hassle.
        _dbg.logger.info(f'Loaded configuration: {self._cfg=}')
        _dbg.logger.info(f'Loaded metadata: {self._metadata=}')

        # import_extensions does 2 things: import all configured extensions, and subscribe to any globally registered extensions.
        # It's good to make this an option with default false for security, and I prefer to keep the two options as one for simplicity.
        self._should_import_extensions = import_extensions

        ctx_extensions = _reg._Registry(f'context ({self.flam_dir})')
        self._fetchers = RegistriesOf(lambda reg: reg._fetchers, ctx_extensions, import_extensions)
        self._predicates = RegistriesOf(lambda reg: reg._predicates, ctx_extensions, import_extensions)
        self._attributes = RegistriesOf(lambda reg: reg._attributes, ctx_extensions, import_extensions)

        # If one of the extensions is bad it can be annoying to delete it from the configuration because flam will fail to load.
        # I don't want to sweep bad extensions under the rug though, so I think the solution of `flam --no-extensions config extension --delete` will just have to do.
        if import_extensions:
            for extension in self._cfg.extensions:
                self._import_extension(extension)
        
        # Not the prettiest cleanup job but it's good to do.
        self._delete_leaky_mlvs()

    # Tidy up the metadata and avoid potential leaks - delete MLVs and their MD entries if they're based on deleted MLFs.
    def _delete_leaky_mlvs(self) -> None:
        should_save = False

        # Iterate in reverse because we'll be deleting elements as we go.
        for i in reversed(range(len(self._metadata.movie_list_vaults))):
            mlv_meta = self._metadata.movie_list_vaults[i]

            if os.path.isfile(self._get_mlf_path(mlv_meta.abstract_listdef)):
                continue

            _dbg.logger.warning(f"Found leaky movie list vault: {mlv_meta.abstract_listdef}. Deleting it")
            del self._metadata.movie_list_vaults[i]
            
            try:
                os.remove(self._get_mlv_path(mlv_meta.abstract_listdef))
            except FileNotFoundError:
                pass     

            should_save = True

        if should_save:
            self._write_metadata()

    @property
    def flam_dir(self) -> str:
        """
        The directory where all movie lists and configuration are stored.
        """
        return self._flam_dir

    @property
    def cfg_readonly(self) -> _cfg.Configuration:
        """
        All configuration settings. This object can technically be modified, but that would lead to disaster. If you want to modify the configuration, use :py:meth:`configure`.
        """
        return self._cfg

    @property
    def fetchers(self) -> RegistriesOf[type[_fetch.Fetcher]]:
        """
        A registry object with all registered fetchers.
        """
        return self._fetchers

    @property
    def predicates(self) -> RegistriesOf[type[_filter.Predicate]]:
        """
        A registry object with all registered predicates.
        """
        return self._predicates

    @property
    def attributes(self) -> RegistriesOf[_attr.Attribute]:
        """
        A registry object with all registered attributes.
        """
        return self._attributes

    @property
    def _cfg_path(self) -> str:
        return os.path.join(self._flam_dir, self._CONFIG_FILE)

    @property
    def _metadata_path(self) -> str:
        return os.path.join(self._flam_dir, self._METADATA_FILE)

    def _make_flam_dir(self) -> None:
        # Make sure to keep it topologically sorted.
        directories = [
            self._flam_dir,
            os.path.join(self._flam_dir, self._MLF_DIR),
            os.path.join(self._flam_dir, self._CACHE_DIR),
            os.path.join(self._flam_dir, self._CACHE_DIR, self._MLF_DIR),
            os.path.join(self._flam_dir, self._CACHE_DIR, self._MLV_DIR),
        ]

        for d in directories:
            try:
                os.mkdir(d)
            except FileExistsError:
                pass

        # Log what the flam dir looked like at the beginning.
        _dbg.logger.info(f"Made flam dir. Structure:\n{'\n'.join(utils.tree(self._flam_dir, stats=lambda f: f" (size={os.path.getsize(f)}B, mtime={os.path.getmtime(f)})"))}")

    def parse_listdef(self, listdef: str) -> _ldef.CanonListdef:
        """
        Parse a string representation of a :ref:`listdef <Listdefs>` and canonicalize it.

        :param listdef: the listdef as a string. It can have a few forms:
        
            * :py:attr:`~._ldef.SpecialListType.ALL`
            * :py:attr:`~._ldef.SpecialListType.DEFAULTS`
            * '<name>' - where <name> is the name of a simple or composite list
            * '<list_type>=<address>' - where <list_type> is :py:attr:`~._ldef.SpecialListType.SIMPLE`, :py:attr:`~._ldef.SpecialListType.COMPOSITE`, or the name of a fetcher.
        """
        
        # This code really belongs in _ldef, but as an interface it's nicer for users if it's through the context.
        return _ldef.CanonListdef._parse(listdef, self)

    def register[T: (type[_fetch.Fetcher], type[_filter.Predicate], _attr.Attribute)](self, item: T) -> T:
        """
        Register a context-level extension. Context extensions are only available from the specific context to which they were registered.

        You may register an item with the same name as that of a global extension or a builtin, and it will shadow them.
        
        :param item: the item to register.
        """

        # Yes, this is a copy paste from _reg.register. I don't think it's worth the effort to avoid it.
        if isinstance(item, type) and issubclass(item, _fetch.Fetcher):
            self._fetchers._register(item)
        elif isinstance(item, type) and issubclass(item, _filter.Predicate):
            self._predicates._register(item)
        elif isinstance(item, _attr.Attribute):
            self._attributes._register(item)
        else:
            raise _exc.InputError(f"Invalid object for registration: {item}.")

        return item

    # Movie lists.
    def get_movie_list(self, listdefs: str | typing.Iterable[str], filter: None | _filter.Filter = None) -> _ml.MovieList:
        """
        Create or open a movie list.

        :param listdefs: indicates which lists to open, or which lists to composite into this movie list. They must all be already fetched.
        :param filter: a movie filter used to filter out movies from the list. If provided, the returned list will be a composite list. 
        """
        listdefs_iterable = listdefs if not isinstance(listdefs, str) else [listdefs]
        canon_listdefs = list(_ldef.CanonListdef._parse_and_expand(listdefs_iterable, self, _ldef._ExpandFlavor.FIND))
        return self._get_movie_list_from_canon_listdefs(canon_listdefs, filter)

    def _get_movie_list_from_canon_listdefs(self, canon_listdefs: list[_ldef.CanonListdef], filter: None | _filter.Filter = None) -> _ml.MovieList:
        if len(canon_listdefs) == 0:
            raise _exc.InputError("Can't create movie list of 0 LISTDEFs. Did you forget to set a default?")

        # Replace None with empty filter to make the rest of the code nicer.
        if filter is None:
            filter = self.compile_movies_filter([])

        # There is no way to express an anonymous list with a single listdef and no filter.
        # They are what happens when you put together multiple lists and/or a filter to spin a new list "on-the-fly".
        if len(canon_listdefs) == 1 and filter.is_empty:
            mlf = self._get_persistable_mlf(canon_listdefs[0])
        else:
            mlf = self._generate_composite_mlf(canon_listdefs, filter, None)

        _dbg.logger.info(f"Returning movie list for: '{mlf.abstract_listdef=}'")
        return _ml.MovieList(mlf, self)

    # This is for getting MLFs that are not anonymous - anything that is saved on disk or should be saved to disk once generated.
    def _get_persistable_mlf(self, abstract_listdef: _ldef.CanonListdef) -> _mlf.MovieListFile:
        mlf_path = self._get_mlf_path(abstract_listdef)

        # Special flow for composite lists because they are classified as cache files which should always be prepared to be regenerated.
        if abstract_listdef.list_type == _ldef.SpecialListType.COMPOSITE:
            mlf = None

            if not self._should_regenerate_composite_list(abstract_listdef.address):
                try:
                    mlf = _mlf.MovieListFile._load(mlf_path)
                except (FileNotFoundError, _exc.FileValidationError) as e:
                    # Simply regenerate if we failed to load it.
                    _dbg.logger.info(f"Composite list {abstract_listdef.address=} failed to load from disk due to error: {e}")

            regen_reason = None

            if mlf is None:
                regen_reason = 'it was not previously generated'
            elif mlf.expiration_date is not None and datetime.date.today() > mlf.expiration_date:
                regen_reason = 'the file expired'
                
            # If there is a regen reason, we must regenerate the list.
            if regen_reason is not None:
                _dbg.logger.info(f"Regenerating composite list: '{abstract_listdef}' ({regen_reason})")

                # First generate it.
                composite_list = self._cfg.composite_lists.get_by_uid(abstract_listdef.address)
                filter = self.compile_movies_filter(composite_list.filter_tokens)
                dependencies = [_ldef.CanonListdef(_ldef.SpecialListType.SIMPLE, sl_uid) for sl_uid in composite_list.simple_list_uids]
                mlf = self._generate_composite_mlf(dependencies, filter, abstract_listdef.address)

                # Update metadata. Even if the uid is already in the file just replace it with a new object, because why not.
                self._metadata.composite_lists_by_uid[abstract_listdef.address] = _md._CompositeListMetadata(
                    uid = abstract_listdef.address,

                    # Assume os.path won't throw an error because it would've been caught by _should_regenerate_composite_list.
                    dependency_mtime = {cldef.address: os.path.getmtime(self._get_mlf_path(cldef)) for cldef in dependencies},
                )

                # Writing the mlf before the metadata I think is important.
                self._write_mlf(mlf)
                self._write_metadata()
        else:
            try:
                mlf = _mlf.MovieListFile._load(mlf_path)
            except FileNotFoundError as e:
                raise _exc.InputError(f"LISTDEF '{abstract_listdef.pretty(self)}' isn't fetched.") from e

            if mlf.expiration_date is not None and datetime.date.today() > mlf.expiration_date:
                os.remove(mlf_path)
                raise _exc.InputError(f"LISTDEF '{abstract_listdef.pretty(self)}' was first fetched a long time ago and had to be deleted for legal reasons. Please refetch it.")

        _dbg.logger.info(f"Got movie list file: '{abstract_listdef}'")
        assert mlf is not None
        return mlf
    
    # Note that this function doesn't check if the composite list file exists. In normal circumstances we should never hit that case,
    # and if we hit it anyway because the user is a file-meddling bitch, _get_persistable_mlf will handle that.
    def _should_regenerate_composite_list(self, uid: str) -> bool:
        if uid not in self._metadata.composite_lists_by_uid:
            _dbg.logger.info(f"Composite list {uid=} is not in the metadata, should regenerate")
            return True

        cl_config = self._cfg.composite_lists.get_by_uid(uid)
        cl_meta = self._metadata.composite_lists_by_uid[uid]

        for sl_uid in cl_config.simple_list_uids:
            if sl_uid not in cl_meta.dependency_mtime:
                _dbg.logger.warning(f"Composite list {uid=} has a missing dependency: {sl_uid=}, should regenerate")
                return True

            sl_path = self._get_mlf_path(_ldef.CanonListdef(_ldef.SpecialListType.SIMPLE, sl_uid))

            try:
                if sl_uid not in cl_meta.dependency_mtime or os.path.getmtime(sl_path) > cl_meta.dependency_mtime[sl_uid]:
                    _dbg.logger.info(f"Composite list {uid=} has an outdated dependency: {sl_uid=}, should regenerate")
                    return True
            except FileNotFoundError as e:
                cl_listdef = _ldef.CanonListdef(_ldef.SpecialListType.COMPOSITE, uid)
                sl_listdef = _ldef.CanonListdef(_ldef.SpecialListType.SIMPLE, sl_uid)
                raise _exc.InputError(f"List '{cl_listdef.pretty(self)}' depends on {sl_listdef} which hasn't been fetched.") from e

        return False

    def _generate_composite_mlf(self, abstract_listdefs: list[_ldef.CanonListdef], filter: _filter.Filter, composite_uid: None | str) -> _mlf.MovieListFile:
        dependency_mlfs = [self._get_persistable_mlf(cldef) for cldef in abstract_listdefs]

        # If we're generating a composite list which has no uid then it is anonymous.
        if composite_uid is None:
            list_type = _ldef.SpecialListType.ANONYMOUS
            
            # The address on anonymous lists is only present for pretty-printing purposes. It must contain all the information about how the list was built.
            address = ' '.join(itertools.chain((cldef.pretty(self) for cldef in abstract_listdefs), filter.regurgitate()))
        else:
            list_type = _ldef.SpecialListType.COMPOSITE
            address = composite_uid

        # Pick the nearest of the expiration dates, for legal reasons.
        try:
            expiration_date = min(dep_mlf.expiration_date for dep_mlf in dependency_mlfs if dep_mlf.expiration_date is not None)
        except ValueError:
            expiration_date = None

        merged_mlf = _mlf.MovieListFile(
            version = _gen_version.__version__,
            uid_family = dependency_mlfs[0].uid_family,
            abstract_listdef = _ldef.CanonListdef(list_type, address),
            expiration_date = expiration_date,
            movies_by_uid = {},
            people_by_uid = {},
        )

        # When building the list, we use the same objects from the dependency lists. At the end we deepcopy the result.
        # In case of duplicates we arbitrarily choose which to keep. We don't allow non-uniqueness.
        # Canonicalization is preserved because the uid dicts are unordered anyway.
        for dep_mlf in dependency_mlfs:
            if dep_mlf.uid_family != merged_mlf.uid_family:
                raise _exc.InputError(f"Cannot merge the lists '{' '.join(cldef.pretty(self) for cldef in abstract_listdefs)}' into a composite list "
                    f"due to an ID family mismatch: {dep_mlf.uid_family} != {merged_mlf.uid_family}.")

            merged_mlf.movies_by_uid.update(dep_mlf.movies_by_uid)
            merged_mlf.people_by_uid.update(dep_mlf.people_by_uid)

        # Deepcopy because we built it using some objects from other files.
        merged_mlf = merged_mlf.deepcopy()

        # Now we're going to handle per src datas. For every movie, we want its new per_src_data to be the merging of all the per_src_datas from every dependency list the movie came from.
        # We also want to remove duplicates if the same source is listed twice. So anyway, go over each movie...
        for mlf_movie in merged_mlf.movies_by_uid.values():
            dep_src_datas = {}

            # And each dependency list..
            for dep_mlf in dependency_mlfs:
                # If the movie didn't come from this list, we can skip it.
                if mlf_movie.uid not in dep_mlf.movies_by_uid:
                    continue

                # If the movie did come from this list, we want to remember all its sources, in a data structure that will remove duplicates.
                for per_src_data in dep_mlf.movies_by_uid[mlf_movie.uid].per_src_data:
                    dep_src_datas[per_src_data.canon_listdef] = per_src_data

            # Now we can store the result into the movie. This assignment is safe to do because we did the big deepcopy above.
            # BUT that does mean that we have to deepcopy the per src datas specifically, here.
            # We sort it to preserve canonicalization faster than going through canonicalize() - this is kind of a slimy optimization.
            mlf_movie.per_src_data = sorted(per_src_data.deepcopy() for per_src_data in dep_src_datas.values())

        if not filter.is_empty:
            # For applying the filter, we'll have to wrap the MLF in a MovieList. But the MovieList can't have the listdef of the composite list we are generating, because:
            # 1. Conceptually, it would be wrong. This list is not yet the composite list we were asked to generate.
            # 2. If we did use the same listdef, then this list would try to acquire the MLV of the composite list whose MLF is not yet created so not yet on disk,
            #    and that causes a crash in _get_mlv.
            # So we will temporarily masquerade this MLF as an anonymous composite.
            original_cldef = merged_mlf.abstract_listdef
            merged_mlf.abstract_listdef = _ldef.CanonListdef(_ldef.SpecialListType.ANONYMOUS, f'temp list for exporting {original_cldef}')
            merged_mlf = _ml.MovieList(merged_mlf, self)._export(filter)
            merged_mlf.abstract_listdef = original_cldef
            
        _dbg.logger.info(f"Generated '{merged_mlf.abstract_listdef}' with {len(merged_mlf.movies_by_uid)} movies, {len(merged_mlf.people_by_uid)} people")
        return merged_mlf

    def _write_mlf(self, mlf: _mlf.MovieListFile) -> None:
        path = self._get_mlf_path(mlf.abstract_listdef)
        _dbg.logger.info(f"Writing movie list file with {len(mlf.movies_by_uid)} movies, {len(mlf.people_by_uid)} people to {path=}")
        mlf._write(path)

    def _get_mlf_path(self, abstract_listdef: _ldef.CanonListdef) -> str:
        # After much deliberation, I decided that files for named lists should be named according to the list type and UID,
        # and unnamed lists' files should be named according to the list type and address.
        # This is mostly as opposed to storing all lists according to the concrete list_type and address.
        # The reason: this lets us change lists to a different list type with the same ID family.
        filename = utils.slugify(f'{abstract_listdef.list_type}_{abstract_listdef.address}.json')

        match abstract_listdef.list_type:
            case _ldef.SpecialListType.ANONYMOUS:
                raise RuntimeError(f"Unexpected {abstract_listdef.list_type=}.")
            case _ldef.SpecialListType.COMPOSITE:
                # Everything that can be easily regenerated should go under cache so it's easy to delete them all at once.
                return os.path.join(self._flam_dir, self._CACHE_DIR, self._MLF_DIR, filename)
            case _:
                return os.path.join(self._flam_dir, self._MLF_DIR, filename)

    def _get_mlv(self, abstract_listdef: _ldef.CanonListdef) -> tuple[_mlv._MovieListVault, float]:
        if not self._should_regenerate_mlv(abstract_listdef):
            path = self._get_mlv_path(abstract_listdef)

            try:
                # If shouldn't regenerate MLV then the meta must exist.
                return _mlv._MovieListVault._load(path), self._metadata.get_mlv_meta(abstract_listdef).dependency_mtime
            except (FileNotFoundError, _exc.FileValidationError) as e:
                # Simply regenerate if we failed to load it.
                _dbg.logger.info(f"Movie list vault {abstract_listdef=} failed to load from disk due to error: {e}")

        # Create a new one, write it, return it.
        mlv = _mlv._MovieListVault(
            version = _gen_version.__version__,
            abstract_listdef = abstract_listdef,
            peoples = [],
            assoc_peoples = [],
            assoc_movies = [],
            minsupers = [],
        )

        # Assume that for non-anonymous lists this always succeeds, so after this get_mlv_meta should work.
        self._write_mlv(mlv)

        if abstract_listdef.list_type != _ldef.SpecialListType.ANONYMOUS:
            mlv_meta = self._metadata.get_mlv_meta(abstract_listdef)
            dependency_mtime = mlv_meta.dependency_mtime
        else:
            dependency_mtime = 0.0

        return mlv, dependency_mtime

    def _should_regenerate_mlv(self, abstract_listdef: _ldef.CanonListdef) -> bool:
        # Anonymous lists are not backed to disk so the MLV should always be regenerated.
        if abstract_listdef.list_type == _ldef.SpecialListType.ANONYMOUS:
            return True

        try:
            mlv_meta = self._metadata.get_mlv_meta(abstract_listdef)
        except KeyError:
            _dbg.logger.info(f"Movie list vault {abstract_listdef=} is not in the metadata, should regenerate")
            return True

        # Assume we've loaded the MLF before asking to load its MLV - so mlf_path should exist.
        mlf_path = self._get_mlf_path(abstract_listdef)

        if os.path.getmtime(mlf_path) > mlv_meta.dependency_mtime:
            _dbg.logger.info(f"Movie list vault {abstract_listdef=} is outdated, should regenerate")
            return True

        return False

    def _write_mlv(self, mlv: _mlv._MovieListVault, gen_mtime: None | float = None) -> None:
        # Anonymous lists are not backed to disk so neither is their vault.
        if mlv.abstract_listdef.list_type == _ldef.SpecialListType.ANONYMOUS:
            return

        mlf_path = self._get_mlf_path(mlv.abstract_listdef)

        try:
            mlf_mtime = os.path.getmtime(mlf_path)

            # We want to support API use cases like get_movie_list -> fetch -> get_movie_list.
            # That is, someone is holding onto a ML backed by an MLF that has since been fetched, and a new ML exists based on the more up-to-date MLF.
            # In that case what we want is to not persist the MLV old ML to disk. The ML can still use it in memory.
            # The way we do it is we remember the mtime of the MLF when the MLV was generated, and we don't persist MLVs if the MLF has since been touched.
            # 
            # Note I've also considered the case where the MLF is not touched, and you have multiple MLs based on the same MLF all competing for who gets to persist his vault.
            # I think in that case we'll let them compete. It shouldn't be a problem.
            if gen_mtime is not None and gen_mtime < mlf_mtime:
                _dbg.logger.warning(f"In-use movie list vault {mlv.abstract_listdef=} is based on outdated MLF, will not save it")
                return
        except FileNotFoundError:
            # Also support the case where the MLF was deleted but an ML based on it is still alive.
            _dbg.logger.warning(f"In-use movie list vault {mlv.abstract_listdef=} is based on deleted MLF, will not save it")
            return

        mlv_path = self._get_mlv_path(mlv.abstract_listdef)

        # Mark the MLV as up-to-date as long as the MLF still has the mtime it has now.
        try:
            self._metadata.get_mlv_meta(mlv.abstract_listdef).dependency_mtime = mlf_mtime
        except KeyError:
            _dbg.logger.info(f"Creating new MD entry for movie list vault {mlv.abstract_listdef=}")
            self._metadata.movie_list_vaults.append(_md._MLVMetadata(
                abstract_listdef = mlv.abstract_listdef,
                dependency_mtime = mlf_mtime,
            ))

        # Writing the mlv before the metadata I think is important.
        mlv._write(mlv_path)
        self._write_metadata()

    def _get_mlv_path(self, abstract_listdef: _ldef.CanonListdef) -> str:
        # Movie list vault files are named the same as the movie list but with .cache.
        filename = utils.slugify(f'{abstract_listdef.list_type}_{abstract_listdef.address}.cache.json')
        return os.path.join(self._flam_dir, self._CACHE_DIR, self._MLV_DIR, filename)

    def _import_extension(self, extension: str) -> None:
        # Try both ways.
        try:
            importlib.import_module(extension)
            _dbg.logger.info(f"Successful import using importlib: {extension=}")
        except ModuleNotFoundError:
            try:
                utils.import_file(extension)
                _dbg.logger.info(f"Successful import using utils: {extension=}")
            except ModuleNotFoundError as e:
                raise _exc.InputError(str(e)) from e

    # We embrace a weird approach to configuring. Users are to use this context manager with which they can free edit a copy of the configuration file,
    # and at the end we diff the result against the old file and find what was deleted, what was added, and check for validity of everything.
    # The reasons:
    # * Avoid boilerplate of writing a function for every possible way you can edit every field in the configuration.
    # * Allows for bundling multiple edits with a single save at the end, instead of saving after every operation.
    # * Ability to rollback the changes if something isn't valid.
    # The downsides:
    # * Users technically can access ctx.cfg_readonly so they just have to know that that copy is readonly with no enforcement.
    # * Users may shoot themselves in the foot, if you make an invalid edit you will only know it when you close the context (hopefully we catch every case).
    @contextlib.contextmanager
    def configure(self) -> typing.Iterator[_cfg.Configuration]:
        """
        Returns the configuration settings inside a context where they may be modified. When the context exits, all changes are saved.

        .. code-block:: python

            with ctx.configure() as cfg:
                cfg.extensions.append('my_extension.py')
        """
        editable_copy = self._cfg.deepcopy()
        error_occured = False

        _dbg.logger.info(f"Begin configuring of: {self._cfg=}")

        try:
            yield editable_copy
        except:
            error_occured = True
            raise
        finally:
            _dbg.logger.info(f"End configuration, {error_occured=}, {editable_copy=}")

            if not error_occured:
                self._find_changes_and_write_cfg(editable_copy)

    def _find_changes_and_write_cfg(self, editable_copy: _cfg.Configuration) -> None:
        added_sls, deleted_sls, modified_sls = self._find_added_deleted_modified(editable_copy.simple_lists, self._cfg.simple_lists)
        added_cls, deleted_cls, modified_cls = self._find_added_deleted_modified(editable_copy.composite_lists, self._cfg.composite_lists)

        _dbg.logger.info(f"Results of diff with old config:\n{added_sls=}, {deleted_sls=}, {modified_sls=}\n{added_cls=}, {deleted_cls=}, {modified_cls=}")

        # Generate UUIDs for new simple lists.
        for sl in added_sls:
            sl.uid = str(uuid.uuid4())
            _dbg.logger.info(f"Generated uid {sl.uid} for simple list named '{sl.name}'")

        # Generate UUIDs for new composite lists.
        for cl in added_cls:
            cl.uid = str(uuid.uuid4())
            _dbg.logger.info(f"Generated uid {cl.uid} for composite list named '{cl.name}'")

        # Verify deleted simple lists aren't depended on by a composite list.
        for sl in deleted_sls:
            # We don't mess with removing the list from its dependent composite lists. Let the user do that.
            dependents = [cl.name for cl in editable_copy.composite_lists if sl.uid in cl.simple_list_uids]

            if len(dependents) > 0:
                raise _exc.InputError(f"Failed to delete list '{sl.name}' because it is depended on by composite lists: {', '.join(dependents)}.")

        # "Touch" MLFs of modified simple lists so that their dependent composite lists will know to be regenerated when next we get them.
        # We should do this before saving the file because when it comes to regenerating composite lists, false positives hurt less than false negatives.
        for sl in modified_sls:
            try:
                os.utime(self._get_mlf_path(sl.abstract_listdef))
                _dbg.logger.info(f"Touched file of {sl.abstract_listdef=}")
            except FileNotFoundError:
                pass

        # For the same reason as above, delete MLFs and md of modified or deleted composite lists before even saving the file.
        for cl in itertools.chain(modified_cls, deleted_cls):
            try:
                os.remove(self._get_mlf_path(cl.abstract_listdef))
                _dbg.logger.info(f"Removed file of {cl.abstract_listdef=}")
            except FileNotFoundError:
                pass

            try:
                del self._metadata.composite_lists_by_uid[cl.uid]
            except KeyError:
                pass

        if len(modified_cls) + len(deleted_cls) > 0:
            self._write_metadata()

        # Import extensions if needed before even fully confirming the file is good.
        # Pro: catch that you have a bad extension before saving.
        # Con: if the save is aborted we've imported an extension that isn't saved (not so bad).
        if self._should_import_extensions:
            for extension in editable_copy.extensions:
                if extension not in self._cfg.extensions:
                    self._import_extension(extension)

        # At this point we're done with all the checks except sanity checks that happen while saving.
        # It's time to save and then do things we'd like to do only after we know the file is valid.
        old_cfg = self._cfg

        try:
            self._cfg = editable_copy
            self._write_cfg()
        except:
            _dbg.logger.warning("Caught exception while writing configuration change. Will rollback")
            self._cfg = old_cfg
            raise

        # For deleted simple lists, their fetch data is not deleted, just renamed to the concrete name.
        # This means the files will linger on forever. This is good because fetching can take hours and we shouldn't delete that lightly.
        for sl in deleted_sls:
            # Note: it's possible for users to add a list, then also fetch it under the concrete filename and have both files exist.
            _dbg.logger.info(f"Disowning the file of a deleted list: {sl.abstract_listdef}")
            self._change_mlf_listdef(sl.abstract_listdef, sl.concrete_listdef)

        # Check if added simple lists are already fetched under their concrete filename, and "claim" the file.
        # Note that we intentionally place this below the deleted_sls handling.
        for sl in added_sls:
            # For the record, I don't think it's actually possible to create a case the new MLF's path already exists.
            self._change_mlf_listdef(sl.concrete_listdef, sl.abstract_listdef)

    def _find_added_deleted_modified[T: (_cfg.SimpleList, _cfg.CompositeList)](self, lists: _cfg.ConfigurationLists[T], old_lists: _cfg.ConfigurationLists[T]
            ) -> tuple[list[T], list[T], list[T]]:
        added_lists = []
        deleted_lists = []
        modified_lists = []

        for cfg_list in lists:
            # Try to get matching list in the old cfg.
            try:
                old_list = old_lists.get_by_uid(cfg_list.uid)
            except _exc.InputError:
                old_list = None

            if old_list is None:
                added_lists.append(cfg_list)
            # NOTE: we can get false positives due to not canonicalizing but file first, but:
            # * File must not be canonicalized because CompositeList.filter_tokens order matters.
            # * Canonicalizing may throw errors, and we can tolerate false positives on this check.
            # * If the lists compare unequal, it does mean the list was "touched", just maybe touched with the same data in a different order.
            elif cfg_list != old_list:
                modified_lists.append(cfg_list)

        for old_sl in old_lists:
            try:
                lists.get_by_uid(old_sl.uid)
            except _exc.InputError:
                deleted_lists.append(old_sl)

        return added_lists, deleted_lists, modified_lists
        
    def _change_mlf_listdef(self, old_cldef: _ldef.CanonListdef, new_cldef: _ldef.CanonListdef) -> None:
        old_path = self._get_mlf_path(old_cldef)
        new_path = self._get_mlf_path(new_cldef)

        # If there is no MLF then there's nothing to do.
        if not os.path.isfile(old_path):
            return

        # If the new name is already taken, we have no choice but to delete. We can't raise errors to the user in this flow.
        if os.path.exists(new_path):
            _dbg.logger.info(f"Can't rename MLF from {old_cldef} -> {new_cldef}, deleting it instead")
            os.remove(old_path)
            return

        # os.rename has platform-dependent behavior w.r.t. erroring out if the destination file already exists, but we're safe because we verified it doesn't exist.
        _dbg.logger.info(f"Renaming MLF from {old_cldef} -> {new_cldef}")
        os.rename(old_path, new_path)

        # Now we must change all references to the listdef inside the file.
        try:
            mlf = _mlf.MovieListFile._load(new_path)
        except _exc.FileValidationError as e:
            # Deleting the file because it failed to load may seem a bit harsh.
            # My rationale is that if a file gets fucked up people will probably try to delete and reconfigure the list, so I think this is the result they'd expect.
            _dbg.logger.warning(f'Failed to load renamed MLF with error: {e} Will delete it.')
            os.remove(old_path)
            return

        # The listdef is referenced all over.
        mlf.abstract_listdef = new_cldef
        
        for mlf_movie in mlf.movies_by_uid.values():
            mlf_movie.per_src_data[0].canon_listdef = new_cldef

        self._write_mlf(mlf)

    def _write_cfg(self) -> None:
        _dbg.logger.info(f"Writing configuration: {self._cfg=}")
        self._cfg._write(self._cfg_path)
        
    # Metadata
    def _write_metadata(self) -> None:
        _dbg.logger.info(f"Writing metadata: {self._metadata=}")
        self._metadata._write(self._metadata_path)

    # Fetching.
    def fetch(self, listdefs: typing.Iterable[str], refetch_pattern: None | str = None, quiet: bool = True) -> None:
        """
        Fetch movie lists, i.e. download all their data from some external source and store it locally.
        Depending on the fetcher and the size of the list, this may run for a long time - even hours.

        :param listdefs: which lists to fetch. For composite lists, will actually fetch all simple lists which composite it. A few special values are also supported:

            * Supports 'defaults' to fetch all lists configured with is_default_fetch=True
            * Supports ``'*'`` to fetch all configured lists

        :param refetch_pattern: forces titles that match this regular expression (case-insensitive) to be refetched even if they are already locally stored.
            The expression only needs to match any part of the title, not the whole title. Intended for redownloading shows after a new season has come out.
        :param quiet: indicates if progress should be printed to stdout.
        """
        _dbg.logger.info(f"Requested to fetch {listdefs=}, {refetch_pattern=}, {quiet=}")

        # Get all fetchers before using any so that if one of the listdefs doesn't parse good we will raise an error now and not before fetching a few.
        # We use stable_dedup to not fetch the same thing twice but in a way which preserves the requested fetch order.
        fetchers = [
            self._get_fetcher(cldef)
            for cldef in utils.stable_dedup((_ldef.CanonListdef._parse_and_expand(listdefs, self, _ldef._ExpandFlavor.FETCH)))
        ]

        try:
            refetch_re = re.compile(refetch_pattern, flags=re.IGNORECASE) if refetch_pattern is not None else None
        except re.error as e:
            raise _exc.InputError(f"Invalid PATTERN: '{refetch_pattern}': {e}") from e

        for fetcher in fetchers:
            mlf = None

            # Use this to indicate that the file should be persisted even if the fetcher wrote nothing new, because it's the first time we're creating the file.
            # Otherwise there was a bug where fetching an empty list for the first time doesn't actually save it.
            from_scratch = False

            # Secret feature: if refetch pattern is '.*', we'll go a little extra and start the entire file from scratch.
            # This lets you overcome (im)possible cases where the file is fucked and you cannot run fetch because of it.
            if refetch_re is None or refetch_re.pattern != '.*':
                try:
                    mlf = self._get_persistable_mlf(fetcher.abstract_listdef)
                # If the list were composite there'd be another case where this exception is raised, but it's not possible to reach here with a composite list.
                except _exc.InputError:
                    pass

            # Fetch the entire list "from scratch" if we didn't read it from disk, or there's a uid family mismatch.
            # This silent handling of uid mismatch makes handling LISTDEF configuration changes much simpler,
            # and it also makes sense because uid families are mostly meant for checking composite list compatiblity, not fetch compatibility.
            if mlf is None or mlf.uid_family != fetcher.uid_family:
                from_scratch = True
                mlf = _mlf.MovieListFile(
                    version = _gen_version.__version__,
                    uid_family = fetcher.uid_family,
                    abstract_listdef = fetcher.abstract_listdef,
                    expiration_date = None,
                    movies_by_uid = {},
                    people_by_uid = {},
                )
                
            _dbg.logger.info(f"Fetching {fetcher.abstract_listdef} into file with {len(mlf.movies_by_uid)} movies, {len(mlf.people_by_uid)} people")
                
            # We need both the old and new versions to compare at the end. But it's important that the new one is the deepcopy,
            # so that anyone currently holding on to a movie list won't have the underlying MLF changed.
            new_mlf = mlf.deepcopy()
            
            try:
                fetcher._fetch(new_mlf, refetch_re, quiet)
            except _exc.FetchInterrupt:
                _dbg.logger.info(f"Partially fetched {fetcher.abstract_listdef} due to an interrupt")
                self._close_fetch(mlf if not from_scratch else None, new_mlf)
                raise

            self._close_fetch(mlf if not from_scratch else None, new_mlf)
            _dbg.logger.info(f"Fetched {fetcher.abstract_listdef} with no interrupts")

    def _close_fetch(self, old_mlf: None | _mlf.MovieListFile, new_mlf: _mlf.MovieListFile) -> None:
        # Must canonicalize before comparing for equality.
        new_mlf._canonicalize()

        # We'll only write the new contents if they're different than before, and we'll return whether there was a diff or not.
        # This allows us to check the file mtime to know if it's dirty and dependent files need to be regenerated.
        if old_mlf is None or old_mlf != new_mlf:
            self._write_mlf(new_mlf)

    def _get_fetcher(self, canon_listdef: _ldef.CanonListdef) -> _fetch.Fetcher:
        if canon_listdef.is_abstract:
            # Assume it's a SimpleList.
            abstract_listdef = canon_listdef
            concrete_listdef = self._cfg.simple_lists.get_by_uid(abstract_listdef.address).concrete_listdef
        else:
            # If fetching a totally raw list, it's easiest to lie and call the concrete listdef also "abstract".
            abstract_listdef = concrete_listdef = canon_listdef

        fetcher_cls = self.fetchers[concrete_listdef.list_type]
        _dbg.logger.info(f"Created fetcher of type {fetcher_cls} for {concrete_listdef=}, {abstract_listdef=}")
        return fetcher_cls(concrete_listdef, abstract_listdef, self)

    def precache(self, preference: PrecachePreference = PrecachePreference.DEFAULTS, quiet: bool = True) -> None:
        """
        Precompute some things and cache them to disk so that flam will work faster. This is strictly optional.
        
        :param preference: what you prefer to be cached.
        :param quiet: if False, will print about its progress to stdout.
        """
        _dbg.logger.info(f"Precaching movie list results with {preference=}")

        if preference == PrecachePreference.RESET:
            # Easiest way is to delete the entire cache dir. But then we have to recreate it empty because other functions assume it exists.
            shutil.rmtree(os.path.join(self._flam_dir, self._CACHE_DIR))
            self._make_flam_dir()
            return

        if preference == PrecachePreference.DEFAULTS:
            # Below are the default computations we always want to do. Added in topological order w.r.t. computations depending on previous computations.
            base_computations = [
                # Vault groupings for all default ctgms except any. This computation should come first because other computations depend on it.
                # Note I really only wanted to compute this for crew types which are grouped by default, but the next computations wind up vaulting this for separates anyway.
                # Only CrewType.ANY can be skipped because it's such a trivial computation it never gets vaulted anyway.
                *(_ml._PeopleComputation(ct, ct.default_group_mode) for ct in _ml.CrewType.iterate_except_any()),
                
                # Vault associated movies for all default ctgms because there is no efficient way to compute it ever.
                *(_ml._AssocMoviesComputation(ct, ct.default_group_mode) for ct in _ml.CrewType),
                
                # Vault associated people only for crew types that are grouped by default because it's efficient to compute for GroupMode.SEPARATE.
                # Important to do this after AssocMoviesComputation because this depends on that.
                *(_ml._AssocPeopleComputation(ct, ct.default_group_mode) for ct in _ml.CrewType if ct.default_group_mode == _ml.GroupMode.GROUP),
            ]
        elif preference == PrecachePreference.EVERYTHING:
            base_computations = [
                # Vault all groupings.
                *(_ml._PeopleComputation(ct, gm) for ct in _ml.CrewType for gm in _ml.GroupMode.iterate_except_default()),
                
                # Vault all associated movies.
                *(_ml._AssocMoviesComputation(ct, gm) for ct in _ml.CrewType for gm in _ml.GroupMode.iterate_except_default()),
                
                # Vault associated people for all crew types but only the GROUP case, because it's efficient to compute for GroupMode.SEPARATE.
                *(_ml._AssocPeopleComputation(ct, _ml.GroupMode.GROUP) for ct in _ml.CrewType),

                # Vault minimal superset people for all CrewType x CrewType (ct1, ct2) pairs except ones where both are the same type (ct1 == ct2) because those are trivial.
                # Also only vault for GroupMode.GROUP because otherwise it's a light computation.
                # Note that "minimal superset people" is not a bidirectional relationship - if I am your min superset, doesn't mean that you are mine.
                # So we really do have to compute both directions.
                *(_ml._MinSupersetPeopleComputation(ct1, ct2, _ml.GroupMode.GROUP) for ct1 in _ml.CrewType for ct2 in _ml.CrewType if ct1 != ct2),
            ]
        else:
            raise RuntimeError(f'Unexpected {preference=}.')

        # Handling for DEFAULTS/EVERYTHING is very similar.
        all_listdefs = self._get_all_listdefs()

        for cldef in all_listdefs:
            # Copy computations because we may add some additional ones specific to this list.
            computations = list(base_computations)

            # In DEFAULTS case we want to add any computations that were previously vaulted on this list.
            # Important to do this *before* get_movie_list because when we load the ML we will also get its MLV which will reset the file if it's stale.
            if preference == PrecachePreference.DEFAULTS:
                try:
                    # Load the MLV directly, not via _get_mlv. This is because _get_mlv will reset the file if it's gone stale, and create it if it doesn't exist.
                    # For our current purposes we don't want that - we don't care if the vaulted values are accurate, we just want to know what's vaulted.
                    mlv_path = self._get_mlv_path(cldef)
                    mulva = _mlv._MovieListVault._load(mlv_path)

                    # Add all vaulted computations but then remove duplicates in a stable way. We use the description to check "computation equality", it's a bit hacky.
                    # If we didn't remove duplicates, the infra is smart enough to not recompute things twice. But the user will see the repetition in the progress bar.
                    # And essentially every time you call this function after the first, every default will be duplicated.
                    computations.extend(mulva.get_vaulted_computations())
                    computations = list(utils.stable_dedup(computations, key=lambda c: c.description))
                except (FileNotFoundError, _exc.FileValidationError):
                    # No mulva no worries.
                    pass

            try:
                # If it's a composite list this will regenerate it - which is a part of what we want to precache.
                # We assume _get_all_listdefs returned composite lists last, so we only get to them after their dependencies were touched.
                # I'd like to make this a part of the progress bar but it's tricky and it runs so fast I don't think there's a real need.
                ml = self._get_movie_list_from_canon_listdefs([cldef])
            except _exc.InputError as e:
                # Simple list may not have been fetched, or it's a composite list whose dependencies aren't fetched.
                _dbg.logger.info(f"Failed to get movie list file {cldef} due to error: {e} Skipping it")
                continue
            
            # Compute and vault everything, save only once at the end.
            # Note that even if computations list were to contain duplicates (it doesn't), there is no risk of computing the same thing twice here.
            # This is because we use should_vault=True and _compute_or_load won't recompute something if it's vaulted.
            with open(os.devnull, 'w') as devnull, contextlib.redirect_stdout(devnull) if quiet else contextlib.nullcontext():
                with utils.ProgressBar(computations,
                        desc=cldef.pretty(self),
                        keyfunc=lambda c: c.description) as bar:
                    for computation in bar:
                        ml._compute_or_load(computation, should_vault=True, should_write=False)

            ml._write_vault()

    # Guarantees that composite lists will only show up after other kinds of lists.
    def _get_all_listdefs(self) -> list[_ldef.CanonListdef]:
        # Getting all known listdefs is a bit complicated - there are 3 kinds:
        # 1. Concrete listdefs - ones which aren't simple or composite lists. They aren't reachable except by checking what files we have fetched.
        # 2. Simple lists - they're reachable from the configuration but also stored in the same filter as concrete listdefs.
        # 3. Composite lists - they're reachable from the configuration and stored in a separate directory than the other two because they're considered cache files.

        # First get the simple lists from the configuration.
        canon_listdefs = [sl.abstract_listdef for sl in self._cfg.simple_lists]

        # Now get concrete listdefs. They can only be reached by checking which files exist.
        # Even then it's a bitch because the _get_mlf_path is not inversible so we'll have to read the entire MLF (expensive) just to get the listdef out of it.
        # This is why we handle concrete listdefs different than simple lists - performance.
        non_composite_mlfs = glob.glob(os.path.join(self._flam_dir, self._MLF_DIR, '*.json'))

        for mlf_path in non_composite_mlfs:
            # If this is a simple list we should've already added it. Note that checking mlf_path.startswith('list_') would've been faster but susceptible to false positives.
            if any(self._get_mlf_path(cldef) == mlf_path for cldef in canon_listdefs):
                continue

            # Load the MLF directly and read the listdef. It's called "abstract" but it's concrete for concrete lists.
            # Since we reached this file by globbing we have no idea what it is and we don't trust it - if it fails to load, we simply ignore it.
            try:
                mlf = _mlf.MovieListFile._load(mlf_path)
            except _exc.FileValidationError as e:
                _dbg.logger.warning(f"Failed to load movie list file {mlf_path} due to error: {e} Skipping it")
                continue

            # We're not really supposed to get special lists here except the simple lists skipped above.
            # But it's theoretically possible, if _find_changes_and_write_cfg crashes after saving the config but before _change_mlf_listdef.
            # This would be an opportunity to delete the file, but that is risky, so I'd rather just skip it.
            if mlf.abstract_listdef.is_special:
                _dbg.logger.warning(f"Found orphaned configured movie list file {mlf_path} (listdef {mlf.abstract_listdef}). Skipping it")
                continue

            canon_listdefs.append(mlf.abstract_listdef)

        # Add composite lists only after the rest.
        canon_listdefs.extend(cl.abstract_listdef for cl in self._cfg.composite_lists)
        return canon_listdefs

    # Filtering.
    def compile_filter(self, tokens: list[str], find: _ml.FindableType) -> _filter.Filter:
        """
        Compile a string into a filter object.

        :param tokens: the desired filter string split into tokens. Here is an example to illustrate how to split it:

            .. code-block:: python
                
                # As a string:
                '-title lebowski -o -release-year 1980'
                
                # Split into tokens:
                ['-title', 'lebowski', '-o', 'release-year', '1980']

        :param find: the type of objects the filter is supposed to filter. Some predicates may be specific to a certain findable type.
        """
        params = _filter.EatParams(tokens=tokens, find=find, ctx=self)
        filter = _filter.Filter._eat(params)
        _dbg.logger.info(f"Compiled {tokens=}, {find=} into: {filter}")
        return filter

    def compile_movies_filter(self, tokens: list[str]) -> _filter.Filter:
        """
        Wrapper for :py:meth:`compile_filter` when the filter is for :py:attr:`~._ml.FindableType.MOVIES`.
        """
        return self.compile_filter(tokens, _ml.FindableType.MOVIES)
        
    def compile_people_filter(self, tokens: list[str]) -> _filter.Filter:
        """
        Wrapper for :py:meth:`compile_filter` when the filter is for :py:attr:`~._ml.FindableType.PEOPLE`.
        """
        return self.compile_filter(tokens, _ml.FindableType.PEOPLE)
        
    def compile_roles_filter(self, tokens: list[str]) -> _filter.Filter:
        """
        Wrapper for :py:meth:`compile_filter` when the filter is for :py:attr:`~._ml.FindableType.ROLES`.
        """
        return self.compile_filter(tokens, _ml.FindableType.ROLES)

# Utility for "inverting" registries: instead of first the registration level then the item type, it's first the item type then the levels.
# Has to be implemented this way because some of the registries are contextual, some global.
class RegistriesOf[T: (type[_fetch.Fetcher], type[_filter.Predicate], _attr.Attribute)]:
    # Don't link the possibles values of T because it's impossible without using internal module name.
    """
    Object representing everything that is registered in a :py:class:`FlamContext` of type ``T``.
    ``T`` may be either :py:class:`~._attr.Attribute`, :py:class:`type[Predicate] <._filter.Predicate>`, or :py:class:`type[Fetcher] <._fetch.Fetcher>`.
    """
    __no_init_doc__ = True
    
    def __init__(self, type_selector: typing.Callable[[_reg._Registry], _reg._RegistryOf[T]], ctx_registry: _reg._Registry, use_global_extensions: bool) -> None:
        # Ordering lets you shadow builtins with extensions.
        self._registries_to_try = [
            ctx_registry,
            _reg._global_extensions,
            _reg._builtins
        ] if use_global_extensions else [
            ctx_registry,
            _reg._builtins
        ]

        self._type_selector: typing.Callable[[_reg._Registry], _reg._RegistryOf[T]] = type_selector
    
    def __getitem__(self, qualified_name: str) -> T:
        """
        Get a registered item.
        
        :param qualified_name: the full, qualified name of the item. Qualified names include both the name and the type. E.g., instead of 'title', it should be 'movies-title'.
        """
        return self.get(qualified_name)

    def __contains__(self, qualified_name: str) -> bool:

        """
        Check if the registry contains an item with this name.

        :param qualified_name: the full, qualified name of the item.
        """
        return any(qualified_name in self._type_selector(reg) for reg in self._registries_to_try)

    # Support iteration only over keys and not values, because some values may be lazily allocated once you __getitem__.
    def __iter__(self) -> typing.Iterator[T]:
        """
        Iterate over all unique items in the registry.
        
        To iterate over the raw registry, see :py:meth:`raw_iterate`.
        """

        for reg_idx, reg in enumerate(self._registries_to_try):
            reg_of = self._type_selector(reg)

            for item_name in reg_of:
                item = reg_of[item_name]

                if item_name != item.qualified_name:
                    continue

                is_shadowed = False

                for higher_reg in self._registries_to_try[:reg_idx]:
                    if item_name in self._type_selector(higher_reg):
                        is_shadowed = True
                        break

                if is_shadowed:
                    continue

                yield item

    def raw_iterate(self) -> typing.Iterable[str]:
        """
        Iterate over the names of all items in the registry. Beware:

            * Items support aliases so the same item may be returned multiple times, once for each name it is known by
            * Items may be shadowed if a different item with the same name is registered in a higher-level registry, so this may return the same name twice

        To iterate over items without worrying about the above, use :py:meth:`__iter__`.
        """
        
        for reg in self._registries_to_try:
            yield from self._type_selector(reg)

    def _register(self, item: T) -> None:
        # Last registry is the context extensions.
        self._type_selector(self._registries_to_try[-1]).register(item)

    # NOTE: for some reason the type hint in the documentation also shows the module name, only for this function and nothing else. Sigh...
    # NOTE: this function is a little unintuitive but I think it's ultimately helpful to avoid bugs. If we did type inference without a hint it could be a trap.
    def get(self, name: str, type_hint: None | _ml.FindableType = None) -> T:
        """
        Get a registered item, with optional support for non-qualified names.
        
        :param name: the name of the item. It must be fully qualified unless ``type_hint`` is given.
        :param type_hint: attempt to infer the type from a non-qualified name, with a preference for this hinted type.
            Multiple items can have the same name but with a different type, so this helps resolve that ambiguity.

            .. warning::

                This does NOT guarantee that the returned item will have the same type! It only guarantees to prefer that type if there's ambiguity.
        """
        for reg in self._registries_to_try:
            reg_of_type = self._type_selector(reg)
            
            # First try if it was a qualified name.
            try:
                return reg_of_type[name]
            except KeyError:
                pass

            # If got a type hint, try all types, but try the hinted type first.
            # Note that type_hint does *not* guarantee the result will be applicable to this type.
            # It only activates support for non-qualified names, and promises to resolve ambiguities by preferring the hinted type.
            if type_hint is not None:
                # Try hinted type.
                try:
                    return reg_of_type[_reg.compose_qualified_attr_or_pred_name(type_hint, name)]
                except KeyError:
                    pass

                # Try the others.
                best_match = None

                for findable_type in _ml.FindableType:
                    # Already checked the type hint.
                    if findable_type == type_hint:
                        continue

                    qualified_name = _reg.compose_qualified_attr_or_pred_name(findable_type, name)

                    try:
                        match = reg_of_type[qualified_name]
                    except KeyError:
                        continue

                    # This won't be true in case we actually found it by an alias. In that case, we'd rather see if we can find a match which isn't based on an alias.
                    # This solves the issue of movies and people both having a 'name' but for movies it's an alias to 'titles' and for people it's the primary name.
                    if match.qualified_name == qualified_name:
                        best_match = match
                        break

                    if best_match is None:
                        best_match = match
                
                if best_match is not None:
                    return best_match
        
        # Use a smaller-than-default cutoff so that it finds matches even if you tried a name without the type (e.g. 'title' should closely match 'movies-title').
        close_matches = difflib.get_close_matches(name, self.raw_iterate(), cutoff=0.45)
        suggestions = f' (did you mean: {", ".join(close_matches)}?)' if len(close_matches) > 0 else '.'
        raise _exc.CloseInputError(f"No registered item with the name: '{name}'{suggestions}", close_matches)
