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
import contextlib
import enum
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

# TODO: Don't really like these here.
class FindableType(enum.StrEnum):
    MOVIES = 'movies'
    PEOPLE = 'people'
    ROLES = 'roles'

    @property
    def corresponding_type(self) -> type:
        raise NotImplementedError()

    def is_compatible(self, find: typing.Self) -> bool:
        # Roles are compatible with everything because a role is associated with a person and a movie.
        return find == self.ROLES or self == find

class CrewType(enum.StrEnum):
    CAST = 'cast'
    STUNTCAST = 'stuntcast'
    DIRECTOR = 'director'
    WRITER = 'writer'
    PRODUCER = 'producer'
    COMPOSER = 'composer'
    CINEMATOGRAPHER = 'cinematographer'
    EDITOR = 'editor'

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

class ListHandle:
    def __init__(self, list_file): # TODO: specify how to group each crew type?
        self._list_file = list_file

    def __iter__(self):
        return self.find(FindableType.MOVIES)

    def apply_filter(self, filter: _filter.Filter):
        pass

    def find(self, what: FindableType, filter: None | _filter.Filter = None) -> typing.Iterator[typing.Any]: # TODO: not Any!
        assert filter is None or filter.findable_type == what

    def export(self, filter: _filter.Filter) -> _listfile.ListFile:
        assert filter.findable_type == FindableType.MOVIES

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
    def get_list_handle(self, listdefs: str | typing.Iterable[str], filter: None | _filter.Filter = None) -> ListHandle:
        canon_listdefs = list(self.canonicalize_listdefs_with_all_expansion(listdefs if not isinstance(listdefs, str) else (listdefs,)))
        # TODO: expand "default" and only then make into list... is it really a "list_handle" feature? We have no clear entry point find vs anything else.
        if len(canon_listdefs) == 1:
            list_file = self._get_list_file(canon_listdefs[0])
        else:
            list_file = self._generate_composite_list_file(canon_listdefs, filter)
            list_file.fetcher_type = _cfg.CompositeList.FETCHER_TYPE # TODO: different fetcher_type for annonymous lists?
            list_file.address = "ANNONYMOUS"

        return ListHandle(list_file)

    def _get_list_file(self, abstract_listdef: _ldef.CanonListdef) -> _listfile.ListFile:
        # First we check if it's a composite list that needs regeneration. In that case even if it's cached it needs to be redone.
        if abstract_listdef.fetcher_type == _cfg.CompositeList.FETCHER_TYPE and self._is_composite_list_file_outdated(abstract_listdef.address):
            # TODO: update metadata?
            composite_list = self._composite_lists.get_by_uid(abstract_listdef.address)
            filter = self.compile_filter(composite_list.filter_tokens, FindableType.MOVIES)
            dependencies = [_ldef.CanonListdef(_cfg.RemoteList.FETCHER_TYPE, rl_uid) for rl_uid in composite_list.remote_list_uids]
            list_file = self._generate_composite_list_file(dependencies, filter)
            list_file.fetcher_type = _cfg.CompositeList.FETCHER_TYPE
            list_file.address = abstract_listdef.address
            self._list_files_cache[abstract_listdef.address] = list_file
            return list_file

        # Now we try to get it from memory.
        if abstract_listdef.address in self._list_files_cache:
            return self._list_files_cache[abstract_listdef.address]
            
        # Memory didn't work out, try to load it from disk.
        try:
            list_file = _listfile.ListFile.load(self._get_list_file_path(abstract_listdef))
        except FileNotFoundError:
            raise _xcept.InputError(f"No fetched file for LISTDEF '{self.canon_listdef_pretty(abstract_listdef)}'.")
        except _xcept.FileValidationError as e:
            raise _xcept.FileValidationError(f"{e} You may need to fetch '{self.canon_listdef_pretty(abstract_listdef)}' again from scratch.") from e

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

            rl_path = self._get_list_file_path(_ldef.CanonListdef(_cfg.RemoteList.FETCHER_TYPE, rl_uid))

            try:
                if rl_uid not in cl_meta.dependency_mtime or os.path.getmtime(rl_path) > cl_meta.dependency_mtime[rl_uid]:
                    return True
            except FileNotFoundError:
                cl_listdef = _ldef.CanonListdef(_cfg.CompositeList.FETCHER_TYPE, uid)
                rl_listdef = _ldef.CanonListdef(_cfg.RemoteList.FETCHER_TYPE, rl_uid)
                raise _xcept.InputError(f"List '{self.canon_listdef_pretty(cl_listdef)}' depends on {rl_listdef} which hasn't been fetched.")

        return False

    def _generate_composite_list_file(self, abstract_listdefs: list[_ldef.CanonListdef], filter: None | _filter.Filter) -> _listfile.ListFile:
        merged_list_file = _listfile.ListFile.create()
        list_files = [self._get_list_file(cldef) for cldef in abstract_listdefs]
        # TODO: sciency shit to merge list_files into merged_list_file

        if filter is not None:
            merged_list_file = ListHandle(merged_list_file).export(filter)
            
        return merged_list_file

    def _write_list_file(self, list_file: _listfile.ListFile) -> None:
        list_file.write(self._get_list_file_path(list_file.abstract_listdef))

        # Flush the metadata when saving composite lists so we don't accidentally regenerate them.
        if list_file.fetcher_type == _cfg.CompositeList.FETCHER_TYPE:
            self._write_metadata()

    # After much deliberation, I decided that files for named lists should be named according to the list type and UID,
    # and unnamed lists' files should be named according to the fetcher type and address.
    # This is mostly as opposed to storing all lists according to the concrete fetcher_type and address.
    # The reason: this lets us change lists to a different fetcher type with a compatible ID type.
    def _get_list_file_path(self, abstract_listdef: _ldef.CanonListdef) -> str:
        filename = _utils.slugify(f'{abstract_listdef.fetcher_type}_{abstract_listdef.address}.json')
        return os.path.join(self._flam_dir, self._LISTFILES_DIR, filename)

    # Configuration.
    def lists_of_type(self, fetcher_type: str) -> ConfigurationLists[_cfg.RemoteList] | ConfigurationLists[_cfg.CompositeList]:
        match fetcher_type:
            case _cfg.RemoteList.FETCHER_TYPE:
                return self._remote_lists
            case _cfg.CompositeList.FETCHER_TYPE:
                return self._composite_lists
            case _:
                raise ValueError(f"Invalid type '{fetcher_type}': not any kind of list.")

    def get_list_by_abstract_listdef(self, abstract_listdef: _ldef.CanonListdef) -> _cfg.RemoteList | _cfg.CompositeList:
        return self.lists_of_type(abstract_listdef.fetcher_type).get_by_uid(abstract_listdef.address)

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
    def _write_metadata(self) -> str:
        self._metadata.write(self._get_metadata_path())

    def _get_metadata_path(self) -> str:
        return os.path.join(self._flam_dir, self._METADATA_FILE)

    # Listdefs.
    # TODO: I would like to move as much of this as possible to _ldef.py. Same goes for other sections here I guess.
    def canonicalize_listdef(self, listdef: str) -> _ldef.CanonListdef:
        eq_idx = listdef.find('=')
        before_eq, after_eq = (listdef[:eq_idx], listdef[eq_idx + 1:]) if eq_idx != -1 else (listdef, '')

        # First case, DEFAULTS or ALL.
        if before_eq == _ldef.LISTDEF_DEFAULTS or before_eq == _ldef.LISTDEF_ALL:
            # We (reluctantly) support a trailing '=' for ALL and DEFAULTS,
            # because this way CanonListdef.__str__ and canonicalize_listdef inverse each other. But it must be trailing.
            if after_eq != '':
                raise _xcept.InputError(f"Invalid LISTDEF: '{listdef}' must have nothing after the equal sign.")

            return _ldef.CanonListdef(before_eq, after_eq)

        # For remote/composite lists we need to convert the name to a uid.
        if eq_idx != -1 and (before_eq == _cfg.RemoteList.FETCHER_TYPE or before_eq == _cfg.CompositeList.FETCHER_TYPE):
            return self.lists_of_type(before_eq).get_by_name(after_eq).abstract_listdef
        
        # The generic case where it's whatever=whatever.
        if eq_idx != -1:
            return _ldef.CanonListdef(before_eq, after_eq)
        
        # If no '=' sign then we'll treat it as a list or composite list, and try to determine which.
        if (list_obj := self._get_implicit_list(before_eq)) is not None:
            return list_obj.abstract_listdef

        raise _xcept.InputError(f"Invalid LISTDEF: '{listdef}'.")

    # This is the most that we can canonicalize/expand listdefs generically. Other transformations are different for fetching vs finding vs whatever.
    def canonicalize_listdefs_with_all_expansion(self, listdefs: typing.Iterable[str]) -> typing.Iterator[_ldef.CanonListdef]:
        for ldef in listdefs:
            cldef = self.canonicalize_listdef(ldef)

            if cldef.fetcher_type == _ldef.LISTDEF_ALL:
                yield from (rl.abstract_listdef for rl in self._remote_lists)
            else:
                yield cldef

    # Internally when canonicalizing listdefs it's convenient to convert list names to UIDs,
    # but it means that whenever we print the listdef we need to convert it back to have human-readable list names.
    def canon_listdef_pretty(self, canon_listdef: _ldef.CanonListdef) -> str:
        return str(canon_listdef._replace(address=self.get_list_by_abstract_listdef(canon_listdef).name) if canon_listdef.is_abstract else canon_listdef)

    def _get_implicit_list(self, name: str) -> None | _cfg.RemoteList | _cfg.CompositeList:
        try:
            return self._remote_lists.get_by_name(name)
        except _xcept.InputError:
            pass

        try:
            return self._composite_lists.get_by_name(name)
        except _xcept.InputError:
            pass

        return None

    # Registration.
    def registries_to_try(self) -> typing.Iterable[_reg.Registry]:
        yield _reg._builtins

        if self._use_global_extensions:
            yield _reg._global_extensions

        yield self._extensions

    # Fetching.
    def fetch(self, listdefs: typing.Iterable[str], refetch_pattern: None | str = None, quiet: bool = True) -> None:
        fetchers = self._parse_listdefs_into_fetchers(listdefs)

        try:
            refetch_re = re.compile(refetch_pattern, flags=re.IGNORECASE) if refetch_pattern is not None else None
        except re.error as e:
            raise _xcept.InputError(f"Invalid PATTERN: '{refetch_pattern}': {e}")

        for fetcher in fetchers:
            try:
                list_file = self._get_list_file(fetcher.abstract_listdef)
            # If the list were composite there'd be another case where this exception is raised, but it's not possible to reach here with a composite list.
            except _xcept.InputError:
                list_file = _listfile.ListFile.create()
                
            if not isinstance(list_file.uid_type, _file.UnsetType) and list_file.uid_type != fetcher.uid_type:
                raise _xcept.InputError(f"Cannot fetch '{self.canon_listdef_pretty(fetcher.abstract_listdef)}' because it's already fetched with a different ID type "
                    f"(old: '{list_file.uid_type}', new: '{fetcher.uid_type}'). "
                    "This can happen if you changed a list's LISTDEF to a nonmatching type. You can resolve it by fetching the list from scratch, or reverting the list to its old type.")

            # We need both the old and new versions to compare at the end. But it's important that the new one is the deepcopy,
            # so that anyone currently holding on to a list handle won't have the underlying list file changed.
            new_list_file = copy.deepcopy(list_file)
            interrupt_error = None

            if refetch_re is not None:
                new_list_file.movies_by_uid = {
                    uid: movie_lf
                    for uid, movie_lf in new_list_file.movies_by_uid.items()
                    if not isinstance(movie_lf.title, _file.UnsetType) and not refetch_re.search(movie_lf.title)
                }

                _remove_unused_people(new_list_file)

            with open(os.devnull, 'w') as devnull, contextlib.redirect_stdout(devnull) if quiet else contextlib.nullcontext():
                print(f"Fetching {self.canon_listdef_pretty(fetcher.abstract_listdef)}...")

                try:
                    fetcher.fetch_into_file(new_list_file)
                except _xcept.FetchInterrupt as e:
                    interrupt_error = e

            # Fetcher may have removed some movies from the list. Over here we remove people who are orphaned because of that.
            _remove_unused_people(new_list_file)

            new_list_file.uid_type = fetcher.uid_type
            new_list_file.fetcher_type = fetcher.abstract_listdef.fetcher_type
            new_list_file.address = fetcher.abstract_listdef.address

            # Must canonicalize before comparing for equality.
            new_list_file.canonicalize()

            # We'll only write the new contents if they're different than before, and we'll return whether there was a diff or not.
            # This allows us to check the file mtime to know if it's dirty and dependent files need to be regenerated.
            if list_file != new_list_file:
                self._write_list_file(new_list_file)

            # Because it's a dictionary we easily overwrite an existing outdated cached file.
            self._list_files_cache[new_list_file.address] = new_list_file

            if interrupt_error is not None:
                raise _xcept.FetchInterrupt(f"Fetching of {self.canon_listdef_pretty(fetcher.abstract_listdef)} got interrupted due to error: {interrupt_error}. "
                    "You may retry to pick up where it left off.")

    def _parse_listdefs_into_fetchers(self, listdefs: typing.Iterable[str]) -> list[_fetch.ListFetcher]:
        cldefs = self.canonicalize_listdefs_with_all_expansion(listdefs)
        expanded = set(self._expand_listdefs_for_fetch(cldefs))

        # Returns a list not a generator so that if one of the listdefs doesn't parse good we will raise an error now and not before fetching a few.
        return [self._get_fetcher(cldef) for cldef in expanded]

    def _expand_listdefs_for_fetch(self, canon_listdefs: typing.Iterable[_ldef.CanonListdef]) -> typing.Iterator[_ldef.CanonListdef]:
        for cldef in canon_listdefs:
            if cldef.fetcher_type == _ldef.LISTDEF_DEFAULTS:
                yield from (rl.abstract_listdef for rl in self._remote_lists if rl.is_default_fetch)

                # Default composite lists... yeah.
                yield from (
                    _ldef.CanonListdef(_cfg.RemoteList.FETCHER_TYPE, rl_uid)
                    for cl in self._composite_lists if cl.is_default_fetch
                        for rl_uid in cl.remote_list_uids
                )
            elif cldef.fetcher_type == _cfg.CompositeList.FETCHER_TYPE:
                composite_list = self._composite_lists.get_by_uid(cldef.address)
                yield from (_ldef.CanonListdef(_cfg.RemoteList.FETCHER_TYPE, rl_uid) for rl_uid in composite_list.remote_list_uids)
            else: # RemoteList.FETCHER_TYPE or a "concrete" type.
                yield cldef

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
                fetcher_cls = registry.get_fetcher(concrete_listdef.fetcher_type)
            except KeyError:
                pass

        if fetcher_cls is None:
            raise _xcept.InputError(f"Invalid LISTDEF '{concrete_listdef}': type is unknown.")

        return fetcher_cls(concrete_listdef, abstract_listdef)

    # Filtering.
    def compile_filter(self, tokens: list[str], find: FindableType) -> _filter.Filter:
        return _filter.Filter.eat(tokens, find, self)

def _get_all_used_person_uids(list_file: _listfile.ListFile) -> typing.Iterator[str]:
    for movie_lf in list_file.movies_by_uid.values():
        for crew in movie_lf.crew.values():
            for role in crew.roles_by_uid.values():
                yield role.person_uid

def _remove_unused_people(list_file: _listfile.ListFile) -> None:
    used_person_uids = set(_get_all_used_person_uids(list_file))
    list_file.people_by_uid = {uid: person for uid, person in list_file.people_by_uid.items() if uid in used_person_uids}

# TODO: for now we put this here.
def _is_debug() -> bool:
    return 'FLAM_DEBUG' in os.environ
