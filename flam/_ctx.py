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

# TODO: if I upgrade to python 3.14 they have a change that probably makes this line no longer needed.
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
import difflib
import contextlib
import time

from . import _cfg
from . import _exc
from . import _filter
from . import _ldef
from . import _mlf
from . import _md
from . import _reg
from . import _fetch
from . import _ml
from . import _dbg
from . import _attr
from . import _gen_version
from . import utils

_start_import_time = time.time()
DEFAULT_FLAM_DIR = _dbg.FlamEnv.CTX_DIR.get_or_default(os.path.join(os.path.expanduser('~'), '.film_flam'))

# Utility for "inverting" registries: instead of first the registration level then the item type, it's first the item type then the levels.
# Has to be implemented this way because some of the registries are contextual, some global.
class RegistriesOf[T: (type[_fetch.ListFetcher], type[_filter.Predicate], _attr.Attribute)]:
    def __init__(self, type_selector: typing.Callable[[_reg.Registry], _reg.RegistryOf[T]], ctx_registry: _reg.Registry, use_global_extensions: bool) -> None:
        # Ordering lets you shadow builtins with extensions.
        self._registries_to_try = [
            ctx_registry,
            _reg._global_extensions,
            _reg._builtins
        ] if use_global_extensions else [
            ctx_registry,
            _reg._builtins
        ]

        self._type_selector: typing.Callable[[_reg.Registry], _reg.RegistryOf[T]] = type_selector
    
    def __getitem__(self, qualified_name: str) -> T:
        return self.get(qualified_name)

    def __contains__(self, qualified_name: str) -> bool:
        return any(qualified_name in self._type_selector(reg) for reg in self._registries_to_try)

    # Support iteration only over keys and not values, because some values may be lazily allocated once you __getitem__.
    def __iter__(self) -> typing.Iterator[str]:
        for reg in self._registries_to_try:
            yield from self._type_selector(reg)

    def register(self, item: T) -> None:
        _dbg.logger.info("Registering a context extension")

        # Last registry is the context extensions.
        self._type_selector(self._registries_to_try[-1]).register(item)

    # __getitem__ expects a qualified name. This function supports inferring the full name from a partial one.
    def get(self, name: str, type_hint: None | _ml.FindableType = None) -> T:
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
        close_matches = difflib.get_close_matches(name, self, cutoff=0.45)
        suggestions = f' (did you mean: {", ".join(close_matches)}?)' if len(close_matches) > 0 else '.'
        raise _exc.CloseInputError(f"No registered item with the name: '{name}'{suggestions}", close_matches)

# This class is the user's entry point to basically everything that is "built in" to this API: accessing lists, filtering, configuring.
class FlamContext:
    _LISTFILES_DIR = 'movie_lists'
    _CACHE_DIR = 'cache'
    _CONFIGURATION_FILE = 'config.json'
    _METADATA_FILE = 'metadata.json'

    def __init__(self, flam_dir: None | str = DEFAULT_FLAM_DIR, import_extensions: bool = False) -> None:
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
            self._cfg = _cfg.Configuration.load(self._cfg_path)
        except FileNotFoundError:
            self._cfg = _cfg.Configuration(
                version = _gen_version.__version__,
                simple_lists_raw = [],
                composite_lists_raw = [],
                extensions = [],
            )

            _dbg.logger.info("Configuration file doesn't exist, creating a new one.")
            self._write_cfg()

        try:
            self._metadata = _md.FlamMetadata.load(self._metadata_path)
        except FileNotFoundError:
            self._metadata = _md.FlamMetadata(
                version = _gen_version.__version__,
                composite_lists_by_uid = {},
            )

            _dbg.logger.info("Metadata file doesn't exist, creating a new one.")
            self._write_metadata()

        # I wish I could print these prettier but it's not worth the hassle.
        _dbg.logger.info(f'Loaded configuration: {self._cfg=}')
        _dbg.logger.info(f'Loaded metadata: {self._metadata=}')

        self._should_import_extensions = import_extensions

        ctx_extensions = _reg.Registry()
        self._fetchers = RegistriesOf(lambda reg: reg.fetchers, ctx_extensions, import_extensions)
        self._predicates = RegistriesOf(lambda reg: reg.predicates, ctx_extensions, import_extensions)
        self._attributes = RegistriesOf(lambda reg: reg.attributes, ctx_extensions, import_extensions)

        # import_extensions does 2 things: import all configured extensions, and subscribe to any globally registered extensions.
        # It's good to make this an option with default false for security, and I prefer to keep the two options as one for simplicity.
        if import_extensions:
            for extension in self._cfg.extensions:
                self._import_extension(extension)

    @property
    def flam_dir(self) -> str:
        return self._flam_dir

    @property
    def cfg_readonly(self) -> _cfg.Configuration:
        return self._cfg

    @property
    def fetchers(self) -> RegistriesOf[type[_fetch.ListFetcher]]:
        return self._fetchers

    @property
    def predicates(self) -> RegistriesOf[type[_filter.Predicate]]:
        return self._predicates

    @property
    def attributes(self) -> RegistriesOf[_attr.Attribute]:
        return self._attributes

    @property
    def _cfg_path(self) -> str:
        return os.path.join(self._flam_dir, self._CONFIGURATION_FILE)

    @property
    def _metadata_path(self) -> str:
        return os.path.join(self._flam_dir, self._METADATA_FILE)

    def _make_flam_dir(self) -> None:
        # Make sure to keep it topologically sorted.
        directories = [
            self._flam_dir,
            os.path.join(self._flam_dir, self._LISTFILES_DIR),
            os.path.join(self._flam_dir, self._CACHE_DIR),
            os.path.join(self._flam_dir, self._CACHE_DIR, self._LISTFILES_DIR),
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
            raise _exc.InputError("Can't create movie list of 0 LISTDEFs. Did you forget to set a default?")

        # Replace None with empty filter to make the rest of the code nicer.
        if filter is None:
            filter = self.compile_filter([], _ml.FindableType.MOVIES)

        # There is no way to express an anonymous list with a single listdef and no filter.
        # They are what happens when you put together multiple lists and filters to spin a new list "on-the-fly".
        if len(canon_listdefs) == 1 and filter.is_empty:
            mlf = self._get_persistable_mlf(canon_listdefs[0])
        else:
            mlf = self._generate_composite_mlf(canon_listdefs, filter, None)

        _dbg.logger.info(f"Returning movie list for: '{mlf.abstract_listdef=}'")
        return _ml.MovieList(mlf, self)

    # This is for getting MLFs that are not anonymous - anything that is saved on disk or should be saved to disk once generated.
    def _get_persistable_mlf(self, abstract_listdef: _ldef.CanonListdef) -> _mlf.MovieListFile:
        # Special flow for composite lists because they are classified as cache files which should always be prepared to be regenerated.
        if abstract_listdef.list_type == _ldef.SpecialListType.COMPOSITE:
            mlf = None

            if not self._should_regenerate_composite_list(abstract_listdef.address):
                try:
                    mlf = _mlf.MovieListFile.load(self._get_mlf_path(abstract_listdef))
                except (FileNotFoundError, _exc.FileValidationError) as e:
                    # Simply regenerate if we failed to load it.
                    _dbg.logger.info(f"Composite list {abstract_listdef.address=} failed to load from disk due to error: {e}")

            if mlf is None:
                _dbg.logger.info(f"Regenerating composite list: '{abstract_listdef}'")

                # First generate it.
                composite_list = self._cfg.composite_lists.get_by_uid(abstract_listdef.address)
                filter = self.compile_filter(composite_list.filter_tokens, _ml.FindableType.MOVIES)
                dependencies = [_ldef.CanonListdef(_ldef.SpecialListType.SIMPLE, sl_uid) for sl_uid in composite_list.simple_list_uids]
                mlf = self._generate_composite_mlf(dependencies, filter, abstract_listdef.address)

                # Update metadata. Even if the uid is already in the file just replace it with a new object, because why not.
                self._metadata.composite_lists_by_uid[abstract_listdef.address] = _md.CompositeListMetadata(
                    uid = abstract_listdef.address,

                    # Assume os.path won't throw an error because it would've been caught by _should_regenerate_composite_list.
                    dependency_mtime = {cldef.address: os.path.getmtime(self._get_mlf_path(cldef)) for cldef in dependencies},
                )

                # Writing the mlf before the metadata I think is important.
                self._write_mlf(mlf)
                self._write_metadata()
        else:
            try:
                mlf = _mlf.MovieListFile.load(self._get_mlf_path(abstract_listdef))
            except FileNotFoundError as e:
                raise _exc.InputError(f"LISTDEF '{abstract_listdef.pretty(self)}' isn't fetched.") from e

        _dbg.logger.info(f"Got movie list file: '{abstract_listdef}'")
        return mlf
    
    # Note that this function doesn't check if the composite list file exists. In normal circumstances we should never hit that case,
    # and if we hit it anyway because the user is a file-meddling bitch, _get_persistable_mlf will handle that.
    def _should_regenerate_composite_list(self, uid: str) -> bool:
        if uid not in self._metadata.composite_lists_by_uid:
            _dbg.logger.info(f"Composite list {uid=} is not in the metadata.")
            return True

        cl_config = self._cfg.composite_lists.get_by_uid(uid)
        cl_meta = self._metadata.composite_lists_by_uid[uid]

        for sl_uid in cl_config.simple_list_uids:
            if sl_uid not in cl_meta.dependency_mtime:
                _dbg.logger.info(f"Composite list {uid=} has a missing dependency: {sl_uid=}")
                return True

            sl_path = self._get_mlf_path(_ldef.CanonListdef(_ldef.SpecialListType.SIMPLE, sl_uid))

            try:
                if sl_uid not in cl_meta.dependency_mtime or os.path.getmtime(sl_path) > cl_meta.dependency_mtime[sl_uid]:
                    _dbg.logger.info(f"Composite list {uid=} has an outdated dependency: {sl_uid=}")
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

        merged_mlf = _mlf.MovieListFile(
            version = _gen_version.__version__,
            uid_family = dependency_mlfs[0].uid_family,
            list_type = list_type,
            address = address,
            movies_by_uid = {},
            people_by_uid = {},
        )

        # When building the list, we use the same objects from the dependency lists. At the end we deepcopy the result.
        # In case of duplicates we arbitrarily choose which to keep. We don't allow non-uniqueness.
        # Canonicalization is preserved because the uid dicts are unordered anyway.
        for mlf in dependency_mlfs:
            if mlf.uid_family != merged_mlf.uid_family:
                raise _exc.InputError(f"Cannot merge the lists '{' '.join(cldef.pretty(self) for cldef in abstract_listdefs)}' into a composite list "
                    f"due to an ID family mismatch: {mlf.uid_family} != {merged_mlf.uid_family}.")

            # TODO: preserve information about which list each movie/person came from? Or in how many it appeared?
            merged_mlf.movies_by_uid.update(mlf.movies_by_uid)
            merged_mlf.people_by_uid.update(mlf.people_by_uid)

        if filter.is_empty:
            # Deepcopy because we built it using some objects from other files.
            merged_mlf = copy.deepcopy(merged_mlf)
        else:
            merged_mlf = _ml.MovieList(merged_mlf, self).export(filter)
            
        _dbg.logger.info(f"Generated '{merged_mlf.abstract_listdef}' with {len(merged_mlf.movies_by_uid)} movies, {len(merged_mlf.people_by_uid)} people")
        return merged_mlf

    def _write_mlf(self, mlf: _mlf.MovieListFile) -> None:
        path = self._get_mlf_path(mlf.abstract_listdef)
        _dbg.logger.info(f"Writing movie list file with {len(mlf.movies_by_uid)} movies, {len(mlf.people_by_uid)} people to {path=}")
        mlf.write(path)

    def _get_mlf_path(self, abstract_listdef: _ldef.CanonListdef) -> str:
        # After much deliberation, I decided that files for named lists should be named according to the list type and UID,
        # and unnamed lists' files should be named according to the list type and address.
        # This is mostly as opposed to storing all lists according to the concrete list_type and address.
        # The reason: this lets us change lists to a different list type with the same ID family.
        filename = utils.slugify(f'{abstract_listdef.list_type}_{abstract_listdef.address}.json')

        match abstract_listdef.list_type:
            case _ldef.SpecialListType.ANONYMOUS:
                raise RuntimeError(f"Unexpected {abstract_listdef.list_type=}")
            case _ldef.SpecialListType.COMPOSITE:
                # Everything that can be easily regenerated should go under cache so it's easy to delete them all at once.
                return os.path.join(self._flam_dir, self._CACHE_DIR, self._LISTFILES_DIR, filename)
            case _:
                return os.path.join(self._flam_dir, self._LISTFILES_DIR, filename)

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
        editable_copy = copy.deepcopy(self._cfg)
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
            _dbg.logger.info("Caught exception while writing configuration change. Will rollback.")
            self._cfg = old_cfg
            raise

        # For deleted simple lists, their fetch data is not deleted, just renamed to the concrete name.
        # This means the files will linger on forever. I considered cleaning them up, but I think there's no need.
        for sl in deleted_sls:
            concrete_filename = self._get_mlf_path(sl.concrete_listdef)
            abstract_filename = self._get_mlf_path(sl.abstract_listdef)

            # os.rename has platform-dependent behavior w.r.t. erroring out if the destination file already exists, so we must check ourselves.
            # Note: it's possible for users to add a list, then also fetch it under the concrete filename and have both files exist.
            if os.path.isfile(abstract_filename) and not os.path.exists(concrete_filename):
                _dbg.logger.info(f"Disowning the file of a deleted list: {abstract_filename=}, {concrete_filename=}")
                os.rename(abstract_filename, concrete_filename)

        # Check if added simple lists are already fetched under their concrete filename, and "claim" the file.
        # Note that we intentionally place this below the deleted_sls handling.
        for sl in added_sls:
            concrete_filename = self._get_mlf_path(sl.concrete_listdef)
            abstract_filename = self._get_mlf_path(sl.abstract_listdef)
            
            # For the record, I don't think it's actually possible to create a case where both files exist.
            if os.path.isfile(concrete_filename) and not os.path.exists(abstract_filename):
                _dbg.logger.info(f"Claiming an existing file for a new list: {abstract_filename=}, {concrete_filename=}")
                os.rename(concrete_filename, abstract_filename)

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
            # Note: would be better if we first canonicalized the file, but that may throw errors, and we can tolerate false positives on this check.
            # Anyway if the lists compare unequal, it does mean the list was "touched", just maybe touched with the same data in a different order.
            elif cfg_list != old_list:
                modified_lists.append(cfg_list)

        for old_sl in old_lists:
            try:
                lists.get_by_uid(old_sl.uid)
            except _exc.InputError:
                deleted_lists.append(old_sl)

        return added_lists, deleted_lists, modified_lists
        
    def _write_cfg(self) -> None:
        _dbg.logger.info(f"Writing configuration: {self._cfg=}")
        self._cfg.canonicalize()
        self._cfg.write(self._cfg_path)
        
    # Metadata
    def _write_metadata(self) -> None:
        _dbg.logger.info(f"Writing metadata: {self._metadata=}")
        self._metadata.write(self._metadata_path)

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
            mlf = None

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
                mlf = _mlf.MovieListFile(
                    version = _gen_version.__version__,
                    uid_family = fetcher.uid_family,
                    list_type = fetcher.abstract_listdef.list_type,
                    address = fetcher.abstract_listdef.address,
                    movies_by_uid = {},
                    people_by_uid = {},
                )
                
            _dbg.logger.info(f"Fetching {fetcher.abstract_listdef} into file with {len(mlf.movies_by_uid)} movies, {len(mlf.people_by_uid)} people")
                
            # We need both the old and new versions to compare at the end. But it's important that the new one is the deepcopy,
            # so that anyone currently holding on to a list handle won't have the underlying list file changed.
            new_mlf = copy.deepcopy(mlf)
            
            try:
                fetcher.fetch(new_mlf, self, refetch_re, quiet)
            except _exc.FetchInterrupt:
                _dbg.logger.info(f"Partially fetched {fetcher.abstract_listdef} due to an interrupt.")
                self._close_fetch(mlf, new_mlf)
                raise

            self._close_fetch(mlf, new_mlf)
            _dbg.logger.info(f"Fetched {fetcher.abstract_listdef} with no interrupts")

    def _close_fetch(self, mlf: _mlf.MovieListFile, new_mlf: _mlf.MovieListFile) -> None:
        # Must canonicalize before comparing for equality.
        new_mlf.canonicalize()

        # We'll only write the new contents if they're different than before, and we'll return whether there was a diff or not.
        # This allows us to check the file mtime to know if it's dirty and dependent files need to be regenerated.
        if mlf != new_mlf:
            self._write_mlf(new_mlf)

    def _get_fetcher(self, canon_listdef: _ldef.CanonListdef) -> _fetch.ListFetcher:
        if canon_listdef.is_abstract:
            # Assume it's a SimpleList.
            abstract_listdef = canon_listdef
            concrete_listdef = self._cfg.simple_lists.get_by_uid(abstract_listdef.address).concrete_listdef
        else:
            abstract_listdef = concrete_listdef = canon_listdef

        fetcher_cls = self.fetchers[concrete_listdef.list_type]
        _dbg.logger.info(f"Created fetcher of type {fetcher_cls} for {concrete_listdef=}, {abstract_listdef=}")
        return fetcher_cls(concrete_listdef, abstract_listdef)

    # Filtering.
    def compile_filter(self, tokens: list[str], find: _ml.FindableType) -> _filter.Filter:
        params = _filter.EatParams(tokens=tokens, find=find, ctx=self)
        filter = _filter.Filter.eat(params)
        _dbg.logger.info(f"Compiled {tokens=}, {find=} into: {filter}")
        return filter

_dbg.logger.info(f'Module import time: {time.time() - _start_import_time}s')
