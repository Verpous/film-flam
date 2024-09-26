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

import os
import typing
import uuid
import re
import copy
import importlib
import tempfile
import weakref
import itertools

from . import _cfg
from . import _exc
from . import _filter
from . import _ldef
from . import _file
from . import _mlf
from . import _md
from . import _reg
from . import utils
from . import _fetch
from . import _ml
from . import _dbg
from . import _attr

# Data structure for using simple/composite lists generically.
class ConfigurationLists[T: (_cfg.SimpleList, _cfg.CompositeList)]:
    def __init__(self, lists: list[T], list_type: str) -> None:
        self._lists: list[T] = lists
        self._list_type = list_type

    def __iter__(self) -> typing.Iterator[T]:
        return iter(self._lists)

    def get_by_uid(self, uid: str) -> T:
        try:
            return next(l for l in self._lists if l.uid == uid)
        except StopIteration as e:
            raise _exc.InputError(f"Invalid {self._list_type} UID: '{uid}'.") from e

    def get_by_name(self, name: str) -> T:
        try:
            return next(l for l in self._lists if l.name == name)
        except StopIteration as e:
            raise _exc.InputError(f"Invalid {self._list_type} name: '{name}'.") from e

# Utility for "inverting" registries: instead of first the registration level then the item type, it's first the item type then the levels.
# Has to be implemented this way because some of the registries are contextual, some global.
class RegistriesOf[T: (type[_fetch.ListFetcher], type[_filter.Predicate], _attr.Attribute)]:
    def __init__(self, type_selector: typing.Callable[[_reg.Registry], _reg.RegistryOf[T]], ctx_registry: _reg.Registry, use_global_extensions: bool) -> None:
        self._registries_to_try = [_reg._builtins, _reg._global_extensions, ctx_registry] if use_global_extensions else [_reg._builtins, ctx_registry]
        self._type_selector: typing.Callable[[_reg.Registry], _reg.RegistryOf[T]] = type_selector

    def __getitem__(self, name: str) -> T:
        for reg in self._registries_to_try:
            try:
                return self._type_selector(reg)[name]
            except KeyError:
                pass

        raise _exc.InputError(f"No registered item with the name: '{name}'.")

    def __contains__(self, name: str) -> bool:
        return any(name in self._type_selector(reg) for reg in self._registries_to_try)

    def __iter__(self) -> typing.Iterator[T]:
        for reg in self._registries_to_try:
            yield from self._type_selector(reg)

    def register(self, item: T) -> None:
        _dbg.logger.info("Registering a context extension")

        # Last registry is the context extensions.
        self._type_selector(self._registries_to_try[-1]).register(item)

# This class is the user's entry point to basically everything that is "built in" to this API: accessing lists, filtering, configuring.
class FlamContext:
    DEFAULT_FLAM_DIR = _dbg.FlamEnv.CTX_DIR.get(os.path.join(os.path.expanduser('~'), '.film_flam'))
    _LISTFILES_DIR = 'movie_lists'
    _CONFIGURATION_FILE = 'config.json'
    _METADATA_FILE = 'metadata.json'

    def __init__(self, flam_dir: None | str = DEFAULT_FLAM_DIR, import_extensions: bool = False) -> None:
        _dbg.logger.info(f"Making a context, {flam_dir=}, {import_extensions=}")

        # Support None for users who just want to work with volatile memory and not load or save anything, we call it volatile mode.
        # Don't tell this to anyone but in "volatile" mode we actually just persist everything to a tempdir. It's so, so much easier.
        if flam_dir is None:
            tempdir = tempfile.TemporaryDirectory(prefix='.film_flam', ignore_cleanup_errors=not _dbg.is_debug()) # pylint: disable=consider-using-with
            self._flam_dir = tempdir.name

            # Deletes the tempdir when the object is garbage collected or program exits.
            weakref.finalize(self, tempdir.cleanup)
        else:
            # TODO: Acquire OS lock on the flam_dir so that you can't have multiple contexts operating on it at once?
            # I'll leave this idea for later, since I think we may need a "readonly" mode to allow multiple users on the same list...
            self._flam_dir = os.path.normpath(flam_dir)

        self._make_flam_dir()
        self._cfg = _cfg.Configuration.load_or_create(self._get_cfg_path())
        self._metadata = _md.FlamMetadata.load_or_create(self._get_metadata_path()) # TODO: Clean metadata of old lists?

        # TODO: Sort out pretty printing.
        _dbg.logger.info(f'Loaded configuration: {self._cfg=}')
        _dbg.logger.info(f'Loaded metadata: {self._metadata=}')

        self._movie_list_files_cache: dict[_ldef.CanonListdef, _mlf.MovieListFile] = {}

        # Since Configuration needs to be serializable, we can't store the lists in there in some funky data structure,
        # and we can't add fields to the object that aren't meant for serialization.
        # The solution I've got is to wrap those lists in this Context.
        self._simple_lists = ConfigurationLists(self.cfg._simple_lists, _ldef.SpecialListType.SIMPLE)
        self._composite_lists = ConfigurationLists(self.cfg._composite_lists, _ldef.SpecialListType.COMPOSITE)

        ctx_extensions = _reg.Registry()
        self._fetchers = RegistriesOf(lambda reg: reg.fetchers, ctx_extensions, import_extensions)
        self._predicates = RegistriesOf(lambda reg: reg.predicates, ctx_extensions, import_extensions)
        self._attributes = RegistriesOf(lambda reg: reg.attributes, ctx_extensions, import_extensions)

        # import_extensions does 2 things: import all configured extensions, and subscribe to any globally registered extensions.
        # It's good to make this an option with default false for security, and I prefer to keep the two options as one for simplicity.
        if import_extensions:
            for extension in self.cfg.extensions:
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

    @property
    def flam_dir(self) -> str:
        return self._flam_dir

    @property
    def cfg(self) -> _cfg.Configuration:
        return self._cfg

    @property
    def simple_lists(self) -> ConfigurationLists[_cfg.SimpleList]:
        return self._simple_lists

    @property
    def composite_lists(self) -> ConfigurationLists[_cfg.CompositeList]:
        return self._composite_lists

    @property
    def fetchers(self) -> RegistriesOf[type[_fetch.ListFetcher]]:
        return self._fetchers

    @property
    def predicates(self) -> RegistriesOf[type[_filter.Predicate]]:
        return self._predicates

    @property
    def attributes(self) -> RegistriesOf[_attr.Attribute]:
        return self._attributes

    def _make_flam_dir(self) -> None:
        # Make sure to keep it topologically sorted.
        directories = [
            self._flam_dir,
            os.path.join(self._flam_dir, self._LISTFILES_DIR),
        ]

        for d in directories:
            try:
                os.mkdir(d)
            except FileExistsError:
                pass

        # Log what the flam dir looked like at the beginning.
        _dbg.logger.info(f"Made flam dir. Structure:\n{'\n'.join(utils.tree(self._flam_dir, stats=lambda f: f" (size={os.path.getsize(f)}B, mtime={os.path.getmtime(f)})"))}")

    # List files.
    def get_movie_list(self, listdefs: str | typing.Iterable[str], filter: None | _filter.Filter = None) -> _ml.MovieList:
        listdefs_iterable = listdefs if not isinstance(listdefs, str) else (listdefs,)
        canon_listdefs = list(_ldef.CanonListdef.parse_and_expand(listdefs_iterable, self, _ldef.ExpandFlavor.FIND))

        if len(canon_listdefs) == 0:
            raise _exc.InputError(f"Can't create movie list of 0 LISTDEFs. Did you forget to set a default?")

        # Replace None with empty filter to make the rest of the code nicer.
        if filter is None:
            filter = self.compile_filter([], _ml.FindableType.MOVIES)

        if len(canon_listdefs) == 1 and filter.is_empty:
            movie_list_file = self._get_movie_list_file(canon_listdefs[0])
        else:
            movie_list_file = self._generate_composite_movie_list_file(canon_listdefs, filter, None)

        _dbg.logger.info(f"Returning movie list for: '{movie_list_file.abstract_listdef=}'")
        return _ml.MovieList(movie_list_file, self)

    def _get_movie_list_file(self, abstract_listdef: _ldef.CanonListdef) -> _mlf.MovieListFile:
        # First we check if it's a composite list that needs regeneration. In that case even if it's cached it needs to be redone.
        if abstract_listdef.list_type == _ldef.SpecialListType.COMPOSITE and self._is_composite_list_outdated(abstract_listdef.address):
            # First generate it.
            composite_list = self._composite_lists.get_by_uid(abstract_listdef.address)
            filter = self.compile_filter(composite_list.filter_tokens, _ml.FindableType.MOVIES)
            dependencies = [_ldef.CanonListdef(_ldef.SpecialListType.SIMPLE, sl_uid) for sl_uid in composite_list.simple_list_uids]
            movie_list_file = self._generate_composite_movie_list_file(dependencies, filter, abstract_listdef.address)

            # Update metadata.
            if abstract_listdef.address not in self._metadata.composite_lists_by_uid:
                self._metadata.composite_lists_by_uid[abstract_listdef.address] = _md.CompositeListMetadata.create(uid=abstract_listdef.address)

            # Assume os.path won't throw an error because it would've been caught by _is_composite_list_outdated.
            self._metadata.composite_lists_by_uid[abstract_listdef.address].dependency_mtime = {
                cldef.address: os.path.getmtime(self._get_movie_list_file_path(cldef))
                for cldef in dependencies
            }

            # Writing the mlf before the metadata I think is important.
            self._write_movie_list_file(movie_list_file)
            self._write_metadata()

            # Update cache and we can skiddadle.
            self._movie_list_files_cache[abstract_listdef] = movie_list_file

            _dbg.logger.info(f"Regenerated and returning: '{abstract_listdef}'")
            return movie_list_file

        # Now we try to get it from memory.
        if abstract_listdef in self._movie_list_files_cache:
            _dbg.logger.info(f"Returning from cache: '{abstract_listdef}'")
            return self._movie_list_files_cache[abstract_listdef]
            
        # Memory didn't work out, try to load it from disk.
        try:
            movie_list_file = _mlf.MovieListFile.load(self._get_movie_list_file_path(abstract_listdef))
        except FileNotFoundError as e:
            raise _exc.InputError(f"No fetched file for LISTDEF '{abstract_listdef.pretty(self)}'.") from e
        except _exc.FileValidationError as e:
            raise _exc.FileValidationError(f"{e} You may need to fetch '{abstract_listdef.pretty(self)}' again from scratch.") from e

        assert not isinstance(movie_list_file.address, _file.UnsetType)
        self._movie_list_files_cache[abstract_listdef] = movie_list_file
        _dbg.logger.info(f"Returning from disk: '{abstract_listdef}'")
        return movie_list_file
    
    def _is_composite_list_outdated(self, uid: str) -> bool:
        if uid not in self._metadata.composite_lists_by_uid:
            _dbg.logger.info(f"Composite list {uid=} is not in the metadata.")
            return True

        cl_config = self._composite_lists.get_by_uid(uid)
        cl_meta = self._metadata.composite_lists_by_uid[uid]

        for sl_uid in cl_config.simple_list_uids:
            if sl_uid not in cl_meta.dependency_mtime:
                _dbg.logger.info(f"Composite list {uid=} requires regeneration because of missing dependency: {sl_uid=}")
                return True

            sl_path = self._get_movie_list_file_path(_ldef.CanonListdef(_ldef.SpecialListType.SIMPLE, sl_uid))

            try:
                if sl_uid not in cl_meta.dependency_mtime or os.path.getmtime(sl_path) > cl_meta.dependency_mtime[sl_uid]:
                    _dbg.logger.info(f"Composite list {uid=} requires regeneration because of outdated dependency: {sl_uid=}")
                    return True
            except FileNotFoundError as e:
                cl_listdef = _ldef.CanonListdef(_ldef.SpecialListType.COMPOSITE, uid)
                sl_listdef = _ldef.CanonListdef(_ldef.SpecialListType.SIMPLE, sl_uid)
                raise _exc.InputError(f"List '{cl_listdef.pretty(self)}' depends on {sl_listdef} which hasn't been fetched.") from e

        return False

    def _generate_composite_movie_list_file(self, abstract_listdefs: list[_ldef.CanonListdef], filter: _filter.Filter, composite_uid: None | str) -> _mlf.MovieListFile:
        dependency_mlfs = [self._get_movie_list_file(cldef) for cldef in abstract_listdefs]

        merged_mlf = _mlf.MovieListFile.create()
        merged_mlf.uid_type = dependency_mlfs[0].uid_type

        # When building the list, we use the same objects from the dependency lists. At the end we deepcopy the result.
        # In case of duplicates we arbitrarily choose which to keep. We don't allow non-uniqueness.
        for mlf in dependency_mlfs:
            if mlf.uid_type != merged_mlf.uid_type:
                raise _exc.InputError(f"Cannot merge the lists '{' '.join(cldef.pretty(self) for cldef in abstract_listdefs)}' into a composite list "
                    f"due to an ID type mismatch: {mlf.uid_type} != {merged_mlf.uid_type}.")

            # TODO: preserve information about which list each movie/person came from? Or in how many it appeared?
            merged_mlf.movies_by_uid.update(mlf.movies_by_uid)
            merged_mlf.people_by_uid.update(mlf.people_by_uid)

        # If composite_uid is none treat it as an annonymous composite list.
        if composite_uid is None:
            # The address on annonymous lists is only present for pretty-printing purposes. It must contain all the information about how the list was built.
            merged_mlf.list_type = _ldef.SpecialListType.ANNONYMOUS
            merged_mlf.address = ' '.join(itertools.chain((cldef.pretty(self) for cldef in abstract_listdefs), filter.regurgitate()))
        else:
            merged_mlf.list_type = _ldef.SpecialListType.COMPOSITE
            merged_mlf.address = composite_uid

        if filter.is_empty:
            merged_mlf = copy.deepcopy(merged_mlf)
        else:
            merged_mlf = _ml.MovieList(merged_mlf, self).export(filter)
            
        _dbg.logger.info(f"Generated '{merged_mlf.abstract_listdef}' with nmovies={len(merged_mlf.movies_by_uid)} npeople={len(merged_mlf.people_by_uid)}")
        return merged_mlf

    def _write_movie_list_file(self, movie_list_file: _mlf.MovieListFile) -> None:
        path = self._get_movie_list_file_path(movie_list_file.abstract_listdef)
        _dbg.logger.info(f"Writing movie list file with nmovies={len(movie_list_file.movies_by_uid)} npeople={len(movie_list_file.people_by_uid)} to {path=}")
        movie_list_file.write(path)

    # After much deliberation, I decided that files for named lists should be named according to the list type and UID,
    # and unnamed lists' files should be named according to the list type and address.
    # This is mostly as opposed to storing all lists according to the concrete list_type and address.
    # The reason: this lets us change lists to a different list type with a compatible ID type.
    def _get_movie_list_file_path(self, abstract_listdef: _ldef.CanonListdef) -> str:
        filename = utils.slugify(f'{abstract_listdef.list_type}_{abstract_listdef.address}.json')
        return os.path.join(self._flam_dir, self._LISTFILES_DIR, filename)

    # Configuration.
    def lists_of_type(self, list_type: str) -> ConfigurationLists[_cfg.SimpleList] | ConfigurationLists[_cfg.CompositeList]:
        match list_type:
            case _ldef.SpecialListType.SIMPLE:
                return self._simple_lists
            case _ldef.SpecialListType.COMPOSITE:
                return self._composite_lists
            case _:
                raise _exc.InputError(f"Invalid list type '{list_type}': not any kind of stored list.")

    def get_list_by_abstract_listdef(self, abstract_listdef: _ldef.CanonListdef) -> _cfg.SimpleList | _cfg.CompositeList:
        return self.lists_of_type(abstract_listdef.list_type).get_by_uid(abstract_listdef.address)

    def add_simple_list(self, simple_list: _cfg.SimpleList) -> None:
        simple_list.uid = str(uuid.uuid4())
        self.cfg._simple_lists.append(simple_list)

        # See if the list was already fetched before it was named, and "claim" the file.
        concrete_filename = self._get_movie_list_file_path(simple_list.concrete_listdef)
        abstract_filename = self._get_movie_list_file_path(simple_list.abstract_listdef)
        
        try:
            os.rename(concrete_filename, abstract_filename)
        except FileNotFoundError:
            pass

    def delete_simple_list(self, uid: str) -> None:
        simple_list = self._simple_lists.get_by_uid(uid)

        # We don't mess with removing the list from its dependent composite lists. Let the user do that.
        dependents = [cl.name for cl in self._composite_lists if uid in cl.simple_list_uids]

        if len(dependents) > 0:
            raise _exc.InputError(f"Failed to delete list '{simple_list.name}' because it is depended on by composite lists: {', '.join(dependents)}.")

        # Deleting a list doesn't delete it from local storage, only gets it renamed to be anonymous.
        concrete_filename = self._get_movie_list_file_path(simple_list.concrete_listdef)
        abstract_filename = self._get_movie_list_file_path(simple_list.abstract_listdef)

        try:
            os.rename(abstract_filename, concrete_filename)
        except FileNotFoundError:
            pass

        self.cfg._simple_lists.remove(simple_list)

    def add_composite_list(self, composite_list: _cfg.CompositeList) -> None:
        composite_list.uid = str(uuid.uuid4())
        self.cfg._composite_lists.append(composite_list)

    def delete_composite_list(self, uid: str) -> None:
        composite_list = self._composite_lists.get_by_uid(uid)
        # TODO: delete files
        self.cfg._composite_lists.remove(composite_list)

    def write_cfg(self) -> None:
        # TODO: In all the write() functions, actually write to a .partial and mov to the true dest once complete? In case the user exits in the middle.
        _dbg.logger.info(f"Writing configuration: {self._cfg=}")
        self.cfg.write(self._get_cfg_path())
        
    def _get_cfg_path(self) -> str:
        return os.path.join(self._flam_dir, self._CONFIGURATION_FILE)

    # Metadata
    def _write_metadata(self) -> None:
        _dbg.logger.info(f"Writing metadata: {self._cfg=}")
        self._metadata.write(self._get_metadata_path())

    def _get_metadata_path(self) -> str:
        return os.path.join(self._flam_dir, self._METADATA_FILE)

    # Fetching.
    def fetch(self, listdefs: typing.Iterable[str], refetch_pattern: None | str = None, quiet: bool = True) -> None:
        _dbg.logger.info(f"Requested to fetch {listdefs=}, {refetch_pattern=}, {quiet=}")

        # Use a list not a generator so that if one of the listdefs doesn't parse good we will raise an error now and not before fetching a few.
        fetchers = [
            self._get_fetcher(cldef)
            for cldef in set(_ldef.CanonListdef.parse_and_expand(listdefs, self, _ldef.ExpandFlavor.FETCH))
        ]

        try:
            refetch_re = re.compile(refetch_pattern, flags=re.IGNORECASE) if refetch_pattern is not None else None
        except re.error as e:
            raise _exc.InputError(f"Invalid PATTERN: '{refetch_pattern}': {e}") from e

        for fetcher in fetchers:
            try:
                movie_list_file = self._get_movie_list_file(fetcher.abstract_listdef)
            # If the list were composite there'd be another case where this exception is raised, but it's not possible to reach here with a composite list.
            except _exc.InputError:
                movie_list_file = _mlf.MovieListFile.create()

            _dbg.logger.info(f"Fetching {fetcher.abstract_listdef} into file with nmovies={len(movie_list_file.movies_by_uid)} npeople={len(movie_list_file.people_by_uid)}")
                
            # We need both the old and new versions to compare at the end. But it's important that the new one is the deepcopy,
            # so that anyone currently holding on to a list handle won't have the underlying list file changed.
            new_movie_list_file = copy.deepcopy(movie_list_file)
            interrupt_error = None
            
            try:
                fetcher.fetch(new_movie_list_file, self, refetch_re, quiet)
            except _exc.FetchInterrupt as e:
                interrupt_error = e

            # Must canonicalize before comparing for equality.
            new_movie_list_file.canonicalize()

            # We'll only write the new contents if they're different than before, and we'll return whether there was a diff or not.
            # This allows us to check the file mtime to know if it's dirty and dependent files need to be regenerated.
            if movie_list_file != new_movie_list_file:
                self._write_movie_list_file(new_movie_list_file)

            # Because it's a dictionary we easily overwrite an existing outdated cached file.
            assert not isinstance(new_movie_list_file.address, _file.UnsetType)
            self._movie_list_files_cache[new_movie_list_file.abstract_listdef] = new_movie_list_file

            if interrupt_error is not None:
                _dbg.logger.info(f"Partially fetched {fetcher.abstract_listdef} due to interrupt: {interrupt_error}")
                raise interrupt_error

            _dbg.logger.info(f"Fetched {fetcher.abstract_listdef} with no interrupts")

    def _get_fetcher(self, canon_listdef: _ldef.CanonListdef) -> _fetch.ListFetcher:
        if canon_listdef.is_abstract:
            # Assume it's a SimpleList.
            abstract_listdef = canon_listdef
            concrete_listdef = self._simple_lists.get_by_uid(abstract_listdef.address).concrete_listdef
        else:
            abstract_listdef = concrete_listdef = canon_listdef

        fetcher_cls = self.fetchers[concrete_listdef.list_type]
        _dbg.logger.info(f"Created fetcher of type {fetcher_cls} for {concrete_listdef=}, {abstract_listdef=}")
        return fetcher_cls(concrete_listdef, abstract_listdef)

    # Filtering.
    def compile_filter(self, tokens: list[str], find: _ml.FindableType) -> _filter.Filter:
        _dbg.logger.info(f"Compiling {tokens=}, {find=}")
        params = _filter.EatParams(tokens=tokens, find=find, ctx=self)
        filter = _filter.Filter.eat(params)
        _dbg.logger.info(f"Compiled into: {filter}")
        return filter

