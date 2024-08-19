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

# Really tricky to type hint _FlamSerializable without this.
from __future__ import annotations

import os
import msgspec
import typing
import types
import uuid
import shutil

import filmflam._utils as utils
import filmflam.exceptions as exceptions

# Users input LISTDEF strings and we turn them into this more convenient representation.
class CanonListdef(typing.NamedTuple):
    fetcher_type: str
    address: str

    @property
    def is_special(self) -> bool:
        return self.fetcher_type in SPECIAL_FETCHER_TYPES

    # RemoteList/CompoundList listdefs are abstract because they can't be fetched directly, only through the underlying "concrete" type.
    @property
    def is_abstract(self) -> bool:
        return self.fetcher_type == RemoteList.FETCHER_TYPE or self.fetcher_type == CompoundList.FETCHER_TYPE

    # "Concrete" listdefs have a type that directly corresponds to a ListFetcher.
    @property
    def is_concrete(self) -> bool:
        return not self.is_special

    def __str__(self) -> str:
        return f'{self.fetcher_type}={self.address}'

# Other modules need to know about these, mainly for type checking reasons, but I don't want them to have to know about msgspec.
UnsetType = msgspec.UnsetType

# Parent class for all the kinds of files we have. We use msgspec for serialization, and this class adds some niceities on top.
class _FlamSerializable(msgspec.Struct, forbid_unknown_fields=True):
    # msgspec creates files through their __init__ and checks that all fields exist and things like that.
    # If a field has a default, it will silently handle it when the field doesn't exist.
    # We want fields to have defaults, but only so that users can initialize them after creation. We do NOT want files to be encoded/decoded with default values.
    # So objects MUST be created through this function which initializes default values without interfering with msgspec.
    @classmethod
    def create(cls, **kwargs: typing.Any) -> typing.Self:
        field_values = dict(cls._defaults())
        field_values.update(kwargs)
        return cls(**field_values)

    @classmethod
    def _defaults(cls) -> typing.Iterator[tuple[str, typing.Any]]:
        for field in msgspec.structs.fields(cls):
            origin = typing.get_origin(field.type)
            args = typing.get_args(field.type)

            # If the field supports unset, default to unset.
            if origin is types.UnionType and UnsetType in args:
                yield field.name, msgspec.UNSET
            # If the field is a collection, default to empty.
            elif origin is list:
                yield field.name, []
            elif origin is dict:
                yield field.name, {}
            # Other types are mandatory and have no defaults.

    @classmethod
    def load(cls, file: str) -> typing.Self:
        with open(file, 'rb') as f:
            contents = f.read()

        # msgspec checks that the file schema (field names and their types) matches.
        try:
            obj = msgspec.json.decode(contents, type=cls)
        except msgspec.ValidationError as e:
            raise cls._validation_error(f'{e}.') from e

        obj.sanity_checks()
        return obj
    
    def write(self, file: str) -> None:
        self.sanity_checks()

        try:
            encoded = msgspec.json.encode(self)
        except msgspec.ValidationError as e:
            raise self._validation_error(f'{e}.') from e

        with open(file, 'wb') as f:
            f.write(msgspec.json.format(encoded))

    # Subclasses can override this to add file validity checks beyond what msgspec already does.
    def sanity_checks(self) -> None:
        obj_with_unset, unset_field = self.get_first_unset()

        if obj_with_unset is not None:
            raise self._validation_error(f'Found unset field: {type(obj_with_unset).__name__}.{unset_field}.')

    # Sorts all lists in the file recursively so that we can compare files for equality.
    def canonicalize(self) -> None:
        # Must be depth-first for this to work.
        for node in self.depth_first_iter():
            for field in msgspec.structs.fields(node):
                value = getattr(node, field.name)

                if isinstance(value, list):
                    value.sort()

    # Finds the first field it can which is UNSET, recursively.
    # We do a bit of a hack, UNSET is intended to mark fields which are allowed to be missing from the JSON when decoded.
    # Instead, we will check if any fields are unset before encoding and after decoding, and raise an exception.
    # The reason: to force the user to initialize all fields even if only to initialize them as None,
    # while allowing them to be initialized one by one and not at the constructor.
    def get_first_unset(self) -> tuple[_FlamSerializable, str] | tuple[None, None]:
        for node in self.depth_first_iter():
            for field in msgspec.structs.fields(node):
                if getattr(node, field.name) == msgspec.UNSET:
                    return self, field.name

        return None, None

    def depth_first_iter(self) -> typing.Iterator[_FlamSerializable]:
        for field in msgspec.structs.fields(self):
            value = getattr(self, field.name)

            # If a data structure isn't here we don't support it.
            if isinstance(value, _FlamSerializable):
                yield from value.depth_first_iter()
            elif isinstance(value, list) and len(value) > 0 and isinstance(value[0], _FlamSerializable):
                yield from (descendant for child in value for descendant in child.depth_first_iter())
            elif isinstance(value, dict) and len(value) > 0 and isinstance(next(iter(value.values())), _FlamSerializable):
                yield from (descendant for child in value.values() for descendant in child.depth_first_iter())

        yield self

    @classmethod
    def _validation_error(cls, message: str) -> exceptions.FileValidationError:
        return exceptions.FileValidationError(f'Invalid {cls.__name__}: {message}')

# TODO: Don't like the name "list", could too easily be confused with too many things. Maybe I should just invent a word and call it a "Flist"?
# ListFile-related objects go here.
class ListFileRole(_FlamSerializable):
    person_uid:             str
    characters:             list[str]

class ListFileCrew(_FlamSerializable):
    crew_type:              str
    roles_by_uid:           dict[str, ListFileRole]

class ListFilePerson(_FlamSerializable):
    uid:                    str
    name:                   UnsetType | str
    # Would love to add gender, nationality but cinemagoer doesn't have them.

class ListFileMovie(_FlamSerializable):
    uid:                    str
    title:                  UnsetType | str
    watch_date:             UnsetType | None | str
    release_date:           UnsetType | None | str
    description:            UnsetType | None | str
    list_index:             UnsetType | None | int
    runtime_minutes:        UnsetType | None | int
    metascore:              UnsetType | None | int
    votes:                  UnsetType | None | int
    rating:                 UnsetType | None | float
    myrating:               UnsetType | None | float
    genres:                 list[str]
    # TODO: consider adding languages, countries

    # crew type -> crew object. It makes things much nicer when you can reference the crew type you want with this indirection,
    # but the downside (as opposed to having a field for each crew type), is that we have to check dynamically that no crew types were added or are missing.
    # msgspec supports TypedDict, but it has problems with initializing a default.
    crew:                   dict[str, ListFileCrew]

class ListFile(_FlamSerializable):
    # These two fields are redundant, they are essentially the filename so the user must already know them to reach them. but if I'll omit them I'll regret it.
    fetcher_type:           UnsetType | str
    address:                UnsetType | str

    # Files are "compatible" if they have a matching uid_type. This is because I have no good way of identifying matching items between, say, IMDb and Letterboxd.
    # If a list originates from IMDb, all the uids in the file will be from IMDb, and so it will only be compatible with other IMDb-based lists.
    uid_type:               UnsetType | str

    movies_by_uid:          dict[str, ListFileMovie]
    people_by_uid:          dict[str, ListFilePerson]

    @property
    def abstract_listdef(self) -> CanonListdef:
        assert not isinstance(self.fetcher_type, UnsetType) and not isinstance(self.address, UnsetType)
        return CanonListdef(self.fetcher_type, self.address)

    def sanity_checks(self) -> None:
        super().sanity_checks()

        for movie in self.movies_by_uid.values():
            if len(CREW_TYPES) != len(movie.crew) or not CREW_TYPES.issuperset(movie.crew.keys()):
                raise self._validation_error(f'Found movie: {movie.uid} with bad crew types: {movie.crew.keys()}.')

# This is where Configuration objects begin.
class RemoteList(_FlamSerializable):
    FETCHER_TYPE: typing.ClassVar[str] = 'list'
    
    uid:                    UnsetType | str
    name:                   str
    fetcher_type:           str
    address:                str
    is_default_fetch:       bool
    is_default_find:        bool

    @property
    def abstract_listdef(self) -> CanonListdef:
        assert not isinstance(self.uid, UnsetType)
        return CanonListdef(self.FETCHER_TYPE, self.uid)

    @property
    def concrete_listdef(self) -> CanonListdef:
        return CanonListdef(self.fetcher_type, self.address)

class CompoundList(_FlamSerializable):
    FETCHER_TYPE: typing.ClassVar[str] = 'compound'

    uid:                    UnsetType | str
    name:                   str
    remote_list_uids:       list[str]
    filter_tokens:          list[str]
    is_default_fetch:       bool
    is_default_find:        bool

    @property
    def abstract_listdef(self) -> CanonListdef:
        assert not isinstance(self.uid, UnsetType)
        return CanonListdef(self.FETCHER_TYPE, self.uid)

# TODO: Maybe the configuration should use "schema evolution".
class Configuration(_FlamSerializable):
    _remote_lists:          list[RemoteList]
    _compound_lists:        list[CompoundList]
    extensions:             list[str]

    # TODO: Forbid special characters in list names that might be confused for a filter token.
    def sanity_checks(self) -> None:
        super().sanity_checks()

        for rl in self._remote_lists:
            if sum(1 for rl2 in self._remote_lists if rl.name == rl2.name) > 1:
                raise self._validation_error(f"Found multiple lists named '{rl.name}'.")

            if rl.concrete_listdef.is_special:
                raise self._validation_error(f"LISTDEF '{rl.concrete_listdef}' type must not be one of: {', '.join(SPECIAL_FETCHER_TYPES)}.")

        for cl in self._compound_lists:
            if sum(1 for cl2 in self._compound_lists if cl.name == cl2.name) > 1:
                raise self._validation_error(f"Found multiple compound lists named '{cl.name}'.")

            if len(cl.remote_list_uids) == 0:
                raise self._validation_error(f"Compound list '{cl.name}' is made up of 0 lists.")
                
            for uid in cl.remote_list_uids:
                try:
                    # Unfortunately the get_by_uid method is not accessible from here, see comment in FlamContext.
                    next(rl for rl in self._remote_lists if rl.uid == uid)
                except StopIteration as e:
                    raise self._validation_error(f"Compound list '{cl.name}' references unknown remote list: '{uid}'.") from e

# Data structure for using remote/compound lists generically.
LT = typing.TypeVar('LT', RemoteList, CompoundList)

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
            raise exceptions.InputError(f"Invalid {self._type_name} UID: '{uid}'") from e

    # Had a bitch of a time trying to make this an overload of get_by_uid.
    def get_by_uid_or_none(self, uid: str) -> None | LT:
        return next((l for l in self._lists if l.uid == uid), None)

    def get_by_name(self, name: str) -> LT:
        try:
            return next(l for l in self._lists if l.name == name)
        except StopIteration as e:
            raise exceptions.InputError(f"Invalid {self._type_name} name: '{name}'") from e

    def get_by_name_or_none(self, name: str) -> None | LT:
        return next((l for l in self._lists if l.name == name), None)

# TODO: Register extension attributes, predicates, fetchers, etc. to the context. API goes something like: init context, register extensions, then use context.
# Have a default global context that everything gets registered to if you don't create your own context to isolate it.
# Problem: how to make this compatible with default-imported extensions, we want them to be a feature of flam the API not flam the CLI tool,
# which means we need a way to register them to the specific context.
# Maybe not such a problem, extensions will register to the global context, if you initialize your own context then that's like saying you want to isolate from the global stuff.

# This object represents the repository itself mainly. Any creating/writing/reading files from the flam directory should go through here.
# For users who just want to work with volatile memory and not load or save anything, we support a "contextless" mode.
# All the ugly if checks for that are encapsulated in this class.
class FlamContext:
    DEFAULT_FLAM_DIR = os.getenv('FLAM_DIR', os.path.join(os.path.expanduser('~'), '.film_flam'))
    _LISTFILES_DIR = 'list_files'
    _CONFIGURATION_FILE = 'config.json'

    # TODO: Acquire OS lock on the flam_dir so that you can't have multiple contexts operating on it at once?
    def __init__(self, flam_dir: None | str = DEFAULT_FLAM_DIR) -> None:
        self._flam_dir = flam_dir

        if self._flam_dir is None:
            self._cfg = Configuration.create()
        else:
            self._flam_dir = os.path.normpath(self._flam_dir)
            self._make_flam_dir()

            cfg_path = self._get_cfg_path()
            self._cfg = Configuration.load(cfg_path) if os.path.exists(cfg_path) else Configuration.create()

        # Since Configuration needs to be serializable, we can't store the lists in there in some funky data structure,
        # and we can't add fields to the object that aren't meant for serialization.
        # The solution I've got is to wrap those lists in this Context.
        self.remote_lists = ConfigurationLists(self.cfg._remote_lists, 'list')
        self.compound_lists = ConfigurationLists(self.cfg._compound_lists, 'compound list')

        # Registered extensions.
        self.fetchers = []
        self.predicates = []
        self.attributes = []

    def _make_flam_dir(self) -> None:
        assert self._flam_dir is not None

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
    def load_list_file(self, abstract_listdef: CanonListdef, must_exist: bool = True) -> ListFile:
        if self._flam_dir is not None:
            try:
                return ListFile.load(self._get_list_file_path(abstract_listdef))
            except FileNotFoundError:
                if must_exist:
                    raise
            except exceptions.FileValidationError as e:
                raise exceptions.FileValidationError(f"{e} You may need to fetch '{self.canon_listdef_pretty(abstract_listdef)}' again from scratch.") from e

        if must_exist:
            raise FileNotFoundError(f"No existing file for LISTDEF '{self.canon_listdef_pretty(abstract_listdef)}' because we're in contextless mode.")

        return ListFile.create()

    def write_list_file(self, list_file: ListFile) -> None:
        # We use devnull in contextless mode, so that we still go through the file validity checks even if we don't write it anywhere.
        if self._flam_dir is None:
            list_file.write(os.devnull)
            return

        file = self._get_list_file_path(list_file.abstract_listdef)
        
        try:
            shutil.copyfile(file, f'{file}.bak')
        except FileNotFoundError:
            pass
        finally:
            # No backup error is worth not writing what we've got.
            list_file.write(file)

    def restore_list_file_to_previous(self, abstract_listdef: CanonListdef) -> None:
        if self._flam_dir is not None:
            file = self._get_list_file_path(abstract_listdef)
            shutil.copyfile(f'{file}.bak', file)
            # TODO: Mark categories dirty.

    # After much deliberation, I decided that files for named lists should be named according to the list type and UID,
    # and unnamed lists' files should be named according to the fetcher type and address.
    # This is mostly as opposed to storing all lists according to the concrete fetcher_type and address.
    # The reason: this lets us change lists to a different fetcher type with a compatible ID type.
    def _get_list_file_path(self, abstract_listdef: CanonListdef) -> str:
        assert self._flam_dir is not None
        filename = utils.slugify(f'{abstract_listdef.fetcher_type}_{abstract_listdef.address}.json')
        return os.path.join(self._flam_dir, self._LISTFILES_DIR, filename)

    # Configuration.
    @property
    def cfg(self) -> Configuration:
        return self._cfg

    def lists_of_type(self, fetcher_type: str) -> ConfigurationLists[RemoteList] | ConfigurationLists[CompoundList]:
        match fetcher_type:
            case RemoteList.FETCHER_TYPE:
                return self.remote_lists
            case CompoundList.FETCHER_TYPE:
                return self.compound_lists
            case _:
                raise ValueError(f"Invalid type '{fetcher_type}': not any kind of list.")

    def get_list_by_abstract_listdef(self, abstract_listdef: CanonListdef) -> RemoteList | CompoundList:
        return self.lists_of_type(abstract_listdef.fetcher_type).get_by_uid(abstract_listdef.address)

    def get_list_by_abstract_listdef_or_none(self, abstract_listdef: CanonListdef) -> None | RemoteList | CompoundList:
        return self.lists_of_type(abstract_listdef.fetcher_type).get_by_uid_or_none(abstract_listdef.address)

    def add_remote_list(self, remote_list: RemoteList) -> None:
        remote_list.uid = str(uuid.uuid4())
        self.cfg._remote_lists.append(remote_list) # pylint: disable=protected-access

        # See if the list was already fetched before it was named, and "claim" the file.
        if self._flam_dir is not None:
            concrete_filename = self._get_list_file_path(remote_list.concrete_listdef)
            abstract_filename = self._get_list_file_path(remote_list.abstract_listdef)
            
            try:
                os.rename(concrete_filename, abstract_filename)
            except FileNotFoundError:
                pass

    def delete_remote_list(self, uid: str) -> None:
        remote_list = self.remote_lists.get_by_uid(uid)

        # We don't mess with removing the list from its dependent compound lists. Let the user do that.
        dependents = [cl.name for cl in self.compound_lists if uid in cl.remote_list_uids]

        if len(dependents) > 0:
            raise exceptions.InputError(f"Failed to delete list '{remote_list.name}' because it is depended on by compound lists: {', '.join(dependents)}")

        if self._flam_dir is not None:
            # Deleting a list doesn't delete it from local storage, only gets it renamed to be anonymous.
            concrete_filename = self._get_list_file_path(remote_list.concrete_listdef)
            abstract_filename = self._get_list_file_path(remote_list.abstract_listdef)

            try:
                os.rename(abstract_filename, concrete_filename)
            except FileNotFoundError:
                pass

        self.cfg._remote_lists.remove(remote_list) # pylint: disable=protected-access

    def add_compound_list(self, compound_list: CompoundList) -> None:
        compound_list.uid = str(uuid.uuid4())
        self.cfg._compound_lists.append(compound_list) # pylint: disable=protected-access

    def delete_compound_list(self, uid: str) -> None:
        compound_list = self.compound_lists.get_by_uid(uid)

        if self._flam_dir is not None:
            # TODO: delete files
            pass

        self.cfg._compound_lists.remove(compound_list) # pylint: disable=protected-access

    def write_cfg(self) -> None:
        # We use devnull in contextless mode, so that we still go through the file validity checks even if we don't write it anywhere.
        file = self._get_cfg_path() if self._flam_dir is not None else os.devnull
        self.cfg.write(file)
        
    def _get_cfg_path(self) -> str:
        assert self._flam_dir is not None
        return os.path.join(self._flam_dir, self._CONFIGURATION_FILE)

    # Listdefs.
    def canonicalize_listdef(self, listdef: str) -> CanonListdef:
        eq_idx = listdef.find('=')
        before_eq, after_eq = (listdef[:eq_idx], listdef[eq_idx + 1:]) if eq_idx != -1 else (listdef, '')

        # First case, DEFAULTS or ALL.
        if before_eq == LISTDEF_DEFAULTS or before_eq == LISTDEF_ALL:
            # We (reluctantly) support a trailing '=' for ALL and DEFAULTS,
            # because this way CanonListdef.__str__ and canonicalize_listdef inverse each other. But it must be trailing.
            if after_eq != '':
                raise exceptions.InputError(f"Invalid LISTDEF: '{listdef}' must have nothing after the equal sign.")

            return CanonListdef(before_eq, after_eq)

        # For remote/compound lists we need to convert the name to a uid.
        if eq_idx != -1 and (before_eq == RemoteList.FETCHER_TYPE or before_eq == CompoundList.FETCHER_TYPE):
            return self.lists_of_type(before_eq).get_by_name(after_eq).abstract_listdef
        
        # The generic case where it's whatever=whatever.
        if eq_idx != -1:
            return CanonListdef(before_eq, after_eq)
        
        # If no '=' sign then we'll treat it as a list or compound list, and try to determine which.
        if (list_obj := self._get_implicit_list(before_eq)) is not None:
            return list_obj.abstract_listdef

        raise exceptions.InputError(f"Invalid LISTDEF: '{listdef}'.")

    # This is the most that we can canonicalize/expand listdefs generically. Other transformations are different for fetching vs finding vs whatever.
    def canonicalize_listdefs_with_all_expansion(self, listdefs: typing.Iterable[str]) -> typing.Iterator[CanonListdef]:
        for ldef in listdefs:
            cldef = self.canonicalize_listdef(ldef)

            if cldef.fetcher_type == LISTDEF_ALL:
                yield from (rl.abstract_listdef for rl in self.remote_lists)
            else:
                yield cldef

    # Internally when canonicalizing listdefs it's convenient to convert list names to UIDs,
    # but it means that whenever we print the listdef we need to convert it back to have human-readable list names.
    def canon_listdef_pretty(self, canon_listdef: CanonListdef) -> str:
        return str(canon_listdef._replace(address=self.get_list_by_abstract_listdef(canon_listdef).name) if canon_listdef.is_abstract else canon_listdef)

    def _get_implicit_list(self, name: str) -> None | RemoteList | CompoundList:
        try:
            return self.remote_lists.get_by_name(name)
        except exceptions.InputError:
            pass

        try:
            return self.compound_lists.get_by_name(name)
        except exceptions.InputError:
            pass

        return None

    # Registration.
    # TODO: avoid duplicates, better data structures, whatever? Also get functions and everything, and maybe make the lists private.
    def register_fetcher(self, fetcher: fetching.ListFetcher) -> None:
        self.fetchers.append(fetcher)

    def register_predicate(self, predicate: filtering.Predicate) -> None:
        self.predicates.append(predicate)

    def register_attribute(self, attribute: attributes.Attribute) -> None:
        self.attributes.append(attribute)

CREW_TYPES = {
    'cast',
    'director',
    'writer',
    'producer',
    'composer',
    'cinematographer',
    'editor',
    'stunt performer',
}

LISTDEF_ALL = '*'
LISTDEF_DEFAULTS = 'defaults'
SPECIAL_FETCHER_TYPES = {LISTDEF_DEFAULTS, LISTDEF_ALL, RemoteList.FETCHER_TYPE, CompoundList.FETCHER_TYPE}
