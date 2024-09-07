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
import atexit

from . import _cfg
from . import _xcept
from . import _attr
from . import _filter
from . import _ldef
from . import _file
from . import _listfile
from . import _md
from . import _reg
from . import _utils
from . import _fetch
from . import _list

# Data structure for using remote/composite lists generically.
LT = typing.TypeVar('LT', _cfg.RemoteList, _cfg.CompositeList)

class ConfigurationLists(typing.Generic[LT]):
    def __init__(self, lists: list[LT], type_name: str) -> None:
        self._lists: list[LT] = lists
        self._type_name = type_name

    def __iter__(self) -> typing.Iterator[LT]:
        return iter(self._lists)

    def get_by_uid(self, uid: str) -> LT:
        try:
            return next(l for l in self._lists if l.uid == uid)
        except StopIteration as e:
            raise _xcept.InputError(f"Invalid {self._type_name} UID: '{uid}'") from e

    def get_by_name(self, name: str) -> LT:
        try:
            return next(l for l in self._lists if l.name == name)
        except StopIteration as e:
            raise _xcept.InputError(f"Invalid {self._type_name} name: '{name}'") from e

# This class is the user's entry point to basically everything that is "built in" to this API: accessing lists, filtering, configuring.
class FlamContext:
    DEFAULT_FLAM_DIR = os.environ.get('FLAM_DIR', os.path.join(os.path.expanduser('~'), '.film_flam'))
    _LISTFILES_DIR = 'list_files'
    _CONFIGURATION_FILE = 'config.json'
    _METADATA_FILE = 'metadata.json'

    def __init__(self, flam_dir: None | str = DEFAULT_FLAM_DIR, import_extensions: bool = False) -> None:
        # Support None for users who just want to work with volatile memory and not load or save anything, we call it volatile mode.
        # Don't tell this to anyone but in "volatile" mode we actually just persist everything to a tempdir. It's so, so much easier.
        if flam_dir is None:
            tempdir = tempfile.TemporaryDirectory(prefix='.film_flam', ignore_cleanup_errors=not _is_debug()) # pylint: disable=consider-using-with
            atexit.register(tempdir.cleanup) # TODO: cleanup at object's __del__ it if happens before atexit?
            self._flam_dir = tempdir.name
        else:
            # TODO: Acquire OS lock on the flam_dir so that you can't have multiple contexts operating on it at once?
            self._flam_dir = os.path.normpath(flam_dir)

        self._make_flam_dir()
        self._cfg = _cfg.Configuration.load_or_create(self._get_cfg_path())
        self._metadata = _md.FlamMetadata.load_or_create(self._get_metadata_path()) # TODO: Initialize/verify metadata? Or just fix up the file as we use it?

        self._list_files_cache: dict[str, _listfile.ListFile] = {}

        # Since Configuration needs to be serializable, we can't store the lists in there in some funky data structure,
        # and we can't add fields to the object that aren't meant for serialization.
        # The solution I've got is to wrap those lists in this Context.
        self._remote_lists = ConfigurationLists(self.cfg._remote_lists, 'list')
        self._composite_lists = ConfigurationLists(self.cfg._composite_lists, 'composite list')

        self._extensions = _reg.Registry()

        # import_extensions does 2 things: import all configured extensions, and subscribe to any globally registered extensions.
        # It's good to make this an option with default false for security, and I prefer to keep the two options as one for simplicity.
        self._use_global_extensions = import_extensions

        if import_extensions:
            for extension in self.cfg.extensions:
                # Try both ways.
                # TODO: Raise InputError?
                try:
                    importlib.import_module(extension)
                except ModuleNotFoundError:
                    _utils.import_file(extension)

    @property
    def flam_dir(self) -> str:
        return self._flam_dir

    @property
    def cfg(self) -> _cfg.Configuration:
        return self._cfg

    @property
    def extensions(self) -> _reg.Registry:
        return self._extensions

    @property
    def remote_lists(self) -> ConfigurationLists[_cfg.RemoteList]:
        return self._remote_lists

    @property
    def composite_lists(self) -> ConfigurationLists[_cfg.CompositeList]:
        return self._composite_lists

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

    # List files.
    def get_list_handle(self, listdefs: str | typing.Iterable[str], filter: None | _filter.Filter = None) -> _list.ListHandle:
        listdefs_list = listdefs if not isinstance(listdefs, str) else (listdefs,)
        canon_listdefs = list(_ldef.CanonListdef.parse_and_expand(listdefs_list, self, _ldef.ExpandFlavor.FIND))

        if len(canon_listdefs) == 1 and filter is None:
            list_file = self._get_list_file(canon_listdefs[0])
        else:
            list_file = self._generate_composite_list_file(canon_listdefs, filter)
            list_file.list_type = _ldef.SpecialListType.ANNONYMOUS
            list_file.address = ' '.join(str(cldef) for cldef in canon_listdefs)

        return _list.ListHandle(list_file)

    def _get_list_file(self, abstract_listdef: _ldef.CanonListdef) -> _listfile.ListFile:
        # First we check if it's a composite list that needs regeneration. In that case even if it's cached it needs to be redone.
        if abstract_listdef.list_type == _ldef.SpecialListType.COMPOSITE and self._is_composite_list_file_outdated(abstract_listdef.address):
            # TODO: update metadata?
            composite_list = self._composite_lists.get_by_uid(abstract_listdef.address)
            filter = self.compile_filter(composite_list.filter_tokens, _list.FindableType.MOVIES)
            dependencies = [_ldef.CanonListdef(_ldef.SpecialListType.REMOTE, rl_uid) for rl_uid in composite_list.remote_list_uids]
            list_file = self._generate_composite_list_file(dependencies, filter)
            list_file.list_type = _ldef.SpecialListType.COMPOSITE
            list_file.address = abstract_listdef.address
            self._list_files_cache[abstract_listdef.address] = list_file
            return list_file

        # Now we try to get it from memory.
        if abstract_listdef.address in self._list_files_cache:
            return self._list_files_cache[abstract_listdef.address]
            
        # Memory didn't work out, try to load it from disk.
        try:
            list_file = _listfile.ListFile.load(self._get_list_file_path(abstract_listdef))
        except FileNotFoundError as e:
            raise _xcept.InputError(f"No fetched file for LISTDEF '{abstract_listdef.pretty(self)}'.") from e
        except _xcept.FileValidationError as e:
            raise _xcept.FileValidationError(f"{e} You may need to fetch '{abstract_listdef.pretty(self)}' again from scratch.") from e

        assert not isinstance(list_file.address, _file.UnsetType)
        self._list_files_cache[list_file.address] = list_file
        return list_file
    
    def _is_composite_list_file_outdated(self, uid: str) -> bool:
        if uid not in self._metadata.composite_lists_by_uid:
            return True

        cl_config = self._composite_lists.get_by_uid(uid)
        cl_meta = self._metadata.composite_lists_by_uid[uid]

        for rl_uid in cl_config.remote_list_uids:
            if rl_uid not in cl_meta.dependency_mtime:
                return True

            rl_path = self._get_list_file_path(_ldef.CanonListdef(_ldef.SpecialListType.REMOTE, rl_uid))

            try:
                if rl_uid not in cl_meta.dependency_mtime or os.path.getmtime(rl_path) > cl_meta.dependency_mtime[rl_uid]:
                    return True
            except FileNotFoundError as e:
                cl_listdef = _ldef.CanonListdef(_ldef.SpecialListType.COMPOSITE, uid)
                rl_listdef = _ldef.CanonListdef(_ldef.SpecialListType.REMOTE, rl_uid)
                raise _xcept.InputError(f"List '{cl_listdef.pretty(self)}' depends on {rl_listdef} which hasn't been fetched.") from e

        return False

    def _generate_composite_list_file(self, abstract_listdefs: list[_ldef.CanonListdef], filter: None | _filter.Filter) -> _listfile.ListFile:
        merged_list_file = _listfile.ListFile.create()
        list_files = [self._get_list_file(cldef) for cldef in abstract_listdefs]
        # TODO: sciency shit to merge list_files into merged_list_file

        if filter is not None:
            merged_list_file = _list.ListHandle(merged_list_file).export(filter)
            
        return merged_list_file

    def _write_list_file(self, list_file: _listfile.ListFile) -> None:
        list_file.write(self._get_list_file_path(list_file.abstract_listdef))

        # Flush the metadata when saving composite lists so we don't accidentally regenerate them.
        if list_file.list_type == _ldef.SpecialListType.COMPOSITE:
            self._write_metadata()

    # After much deliberation, I decided that files for named lists should be named according to the list type and UID,
    # and unnamed lists' files should be named according to the list type and address.
    # This is mostly as opposed to storing all lists according to the concrete list_type and address.
    # The reason: this lets us change lists to a different list type with a compatible ID type.
    def _get_list_file_path(self, abstract_listdef: _ldef.CanonListdef) -> str:
        filename = _utils.slugify(f'{abstract_listdef.list_type}_{abstract_listdef.address}.json')
        return os.path.join(self._flam_dir, self._LISTFILES_DIR, filename)

    # Configuration.
    def lists_of_type(self, list_type: str) -> ConfigurationLists[_cfg.RemoteList] | ConfigurationLists[_cfg.CompositeList]:
        match list_type:
            case _ldef.SpecialListType.REMOTE:
                return self._remote_lists
            case _ldef.SpecialListType.COMPOSITE:
                return self._composite_lists
            case _:
                raise _xcept.InputError(f"Invalid list type '{list_type}': not any kind of stored list.")

    def get_list_by_abstract_listdef(self, abstract_listdef: _ldef.CanonListdef) -> _cfg.RemoteList | _cfg.CompositeList:
        return self.lists_of_type(abstract_listdef.list_type).get_by_uid(abstract_listdef.address)

    def add_remote_list(self, remote_list: _cfg.RemoteList) -> None:
        remote_list.uid = str(uuid.uuid4())
        self.cfg._remote_lists.append(remote_list) # pylint: disable=protected-access

        # See if the list was already fetched before it was named, and "claim" the file.
        concrete_filename = self._get_list_file_path(remote_list.concrete_listdef)
        abstract_filename = self._get_list_file_path(remote_list.abstract_listdef)
        
        try:
            os.rename(concrete_filename, abstract_filename)
        except FileNotFoundError:
            pass

    def delete_remote_list(self, uid: str) -> None:
        remote_list = self._remote_lists.get_by_uid(uid)

        # We don't mess with removing the list from its dependent composite lists. Let the user do that.
        dependents = [cl.name for cl in self._composite_lists if uid in cl.remote_list_uids]

        if len(dependents) > 0:
            raise _xcept.InputError(f"Failed to delete list '{remote_list.name}' because it is depended on by composite lists: {', '.join(dependents)}")

        # Deleting a list doesn't delete it from local storage, only gets it renamed to be anonymous.
        concrete_filename = self._get_list_file_path(remote_list.concrete_listdef)
        abstract_filename = self._get_list_file_path(remote_list.abstract_listdef)

        try:
            os.rename(abstract_filename, concrete_filename)
        except FileNotFoundError:
            pass

        self.cfg._remote_lists.remove(remote_list) # pylint: disable=protected-access

    def add_composite_list(self, composite_list: _cfg.CompositeList) -> None:
        composite_list.uid = str(uuid.uuid4())
        self.cfg._composite_lists.append(composite_list) # pylint: disable=protected-access

    def delete_composite_list(self, uid: str) -> None:
        composite_list = self._composite_lists.get_by_uid(uid)
        # TODO: delete files
        self.cfg._composite_lists.remove(composite_list) # pylint: disable=protected-access

    def write_cfg(self) -> None:
        self.cfg.write(self._get_cfg_path())
        
    def _get_cfg_path(self) -> str:
        return os.path.join(self._flam_dir, self._CONFIGURATION_FILE)

    # Metadata
    def _write_metadata(self) -> None:
        self._metadata.write(self._get_metadata_path())

    def _get_metadata_path(self) -> str:
        return os.path.join(self._flam_dir, self._METADATA_FILE)

    # Registration.
    def registries_to_try(self) -> typing.Iterable[_reg.Registry]:
        yield _reg._builtins

        if self._use_global_extensions:
            yield _reg._global_extensions

        yield self._extensions

    # Fetching.
    def fetch(self, listdefs: typing.Iterable[str], refetch_pattern: None | str = None, quiet: bool = True) -> None:
        # Use a list not a generator so that if one of the listdefs doesn't parse good we will raise an error now and not before fetching a few.
        fetchers = [
            self._get_fetcher(cldef)
            for cldef in set(_ldef.CanonListdef.parse_and_expand(listdefs, self, _ldef.ExpandFlavor.FETCH))
        ]

        try:
            refetch_re = re.compile(refetch_pattern, flags=re.IGNORECASE) if refetch_pattern is not None else None
        except re.error as e:
            raise _xcept.InputError(f"Invalid PATTERN: '{refetch_pattern}': {e}") from e

        for fetcher in fetchers:
            try:
                list_file = self._get_list_file(fetcher.abstract_listdef)
            # If the list were composite there'd be another case where this exception is raised, but it's not possible to reach here with a composite list.
            except _xcept.InputError:
                list_file = _listfile.ListFile.create()
                
            # We need both the old and new versions to compare at the end. But it's important that the new one is the deepcopy,
            # so that anyone currently holding on to a list handle won't have the underlying list file changed.
            new_list_file = copy.deepcopy(list_file)
            interrupt_error = None
            
            try:
                fetcher.fetch(new_list_file, self, refetch_re, quiet)
            except _xcept.FetchInterrupt as e:
                interrupt_error = e

            # Must canonicalize before comparing for equality.
            new_list_file.canonicalize()

            # We'll only write the new contents if they're different than before, and we'll return whether there was a diff or not.
            # This allows us to check the file mtime to know if it's dirty and dependent files need to be regenerated.
            if list_file != new_list_file:
                self._write_list_file(new_list_file)

            # Because it's a dictionary we easily overwrite an existing outdated cached file.
            assert not isinstance(new_list_file.address, _file.UnsetType)
            self._list_files_cache[new_list_file.address] = new_list_file

            if interrupt_error is not None:
                raise interrupt_error

    def _get_fetcher(self, canon_listdef: _ldef.CanonListdef) -> _fetch.ListFetcher:        
        if canon_listdef.is_abstract:
            # Assume it's a RemoteList.
            abstract_listdef = canon_listdef
            concrete_listdef = self._remote_lists.get_by_uid(abstract_listdef.address).concrete_listdef
        else:
            abstract_listdef = concrete_listdef = canon_listdef

        fetcher_cls = None

        for registry in self.registries_to_try():
            try:
                fetcher_cls = registry.get_fetcher(concrete_listdef.list_type)
            except KeyError:
                pass

        if fetcher_cls is None:
            raise _xcept.InputError(f"Invalid LISTDEF '{concrete_listdef}': type is unknown.")

        return fetcher_cls(concrete_listdef, abstract_listdef)

    # Filtering.
    def compile_filter(self, tokens: list[str], find: _list.FindableType) -> _filter.Filter:
        return _filter.Filter.eat(tokens, find, self)

# TODO: for now we put this here.
def _is_debug() -> bool:
    return 'FLAM_DEBUG' in os.environ
