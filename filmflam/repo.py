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
import msgspec
import typing
import types
import uuid

import filmflam._utils as utils
import filmflam.exceptions as exceptions

class CanonListdef(typing.NamedTuple):
    fetcher_type: str
    address: str

    @property
    def is_special(self) -> bool:
        return self.fetcher_type in SPECIAL_FETCHER_TYPES

    @property
    def is_abstract(self) -> bool:
        return self.fetcher_type == RemoteList.FETCHER_TYPE or self.fetcher_type == CompoundList.FETCHER_TYPE

    @property
    def is_concrete(self) -> bool:
        return not self.is_special

    def __str__(self) -> str:
        return f'{self.fetcher_type}={self.address}'

# Other modules need to know about these, mainly for type checking reasons, but I don't want them to have to know about msgspec.
UnsetType = msgspec.UnsetType

class _FlamSerializable(msgspec.Struct, forbid_unknown_fields=True):
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
    def create(cls, **kwargs: typing.Any) -> typing.Self:
        field_values = dict(cls._defaults())
        field_values.update(kwargs)
        return cls(**field_values)

    @classmethod
    def load(cls, file: str) -> typing.Self:
        with open(file, 'rb') as f:
            obj = msgspec.json.decode(f.read(), type=cls)

        obj.sanity_checks()
        return obj
    
    def write(self, file: str) -> None:
        self.sanity_checks()
        encoded = msgspec.json.format(msgspec.json.encode(self))

        with open(file, 'wb') as f:
            f.write(encoded)

    def sanity_checks(self) -> None:
        pass

    # Sorts all lists recursively so that we can compare for equality.
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
    def get_first_unset(self) -> tuple[typing.Self, str] | tuple[None, None]:
        for node in self.depth_first_iter():
            for field in msgspec.structs.fields(node):
                if getattr(node, field.name) == msgspec.UNSET:
                    return self, field.name

        return None, None

    def depth_first_iter(self) -> typing.Iterator[typing.Self]:
        for field in msgspec.structs.fields(self):
            value = getattr(self, field.name)
            
            if isinstance(value, list) and len(value) > 0 and isinstance(value[0], _FlamSerializable):
                yield from (descendant for child in value for descendant in child.depth_first_iter())
            elif isinstance(value, dict) and len(value) > 0 and isinstance(next(iter(value.values())), _FlamSerializable):
                yield from (descendant for child in value.values() for descendant in child.depth_first_iter())

        yield self

class ListFileRole(_FlamSerializable):
    person_uid:             str
    characters:             list[str]

class ListFileCrew(_FlamSerializable):
    crew_type:              str
    roles_by_uid:           dict[str, ListFileRole]

class ListFilePerson(_FlamSerializable):
    uid:                    str
    name:                   UnsetType | str

    # TODO: Would love to have these but cinemagoer doesn't seem to support them.
    # gender
    # nationality

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
    crew:                   dict[str, ListFileCrew]
    # TODO: consider adding languages, countries

class ListFile(_FlamSerializable):
    fetcher_type:           UnsetType | str
    address:                UnsetType | str
    id_type:                UnsetType | str

    movies_by_uid:          dict[str, ListFileMovie]
    people_by_uid:          dict[str, ListFilePerson]

    @property
    def abstract_listdef(self) -> CanonListdef:
        assert not isinstance(self.fetcher_type, UnsetType) and not isinstance(self.address, UnsetType)
        return CanonListdef(self.fetcher_type, self.address)

    # A few things to make sure the file is proper. The "big" checks happen by msgspec when it encodes/decodes things.
    def sanity_checks(self) -> None:
        obj_with_unset, unset_field = self.get_first_unset()

        if obj_with_unset is not None:
            raise RuntimeError(f'Invalid ListFile: found object of type: {type(obj_with_unset)} with unset field: {unset_field}.')

        for movie in self.movies_by_uid.values():
            if len(CREW_TYPES) != len(movie.crew) or not CREW_TYPES.issuperset(movie.crew.keys()):
                raise RuntimeError(f'Invalid ListFile: found movie: {movie.uid} with bad crew types: {movie.crew.keys()}.')

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

class Configuration(_FlamSerializable):
    _remote_lists:          list[RemoteList]
    _compound_lists:        list[CompoundList]
    extensions:             list[str]

    def get_remote_list_by_uid(self, uid: str) -> RemoteList:
        try:
            return next(rl for rl in self._remote_lists if rl.uid == uid)
        except StopIteration as e:
            raise exceptions.InputError(f"Invalid list UID: '{uid}'") from e

    def get_compound_list_by_uid(self, uid: str) -> CompoundList:
        try:
            return next(cl for cl in self._compound_lists if cl.uid == uid)
        except StopIteration as e:
            raise exceptions.InputError(f"Invalid compound list UID: '{uid}'") from e

    def get_remote_list_by_name(self, name: str) -> RemoteList:
        try:
            return next(rl for rl in self._remote_lists if rl.name == name)
        except StopIteration as e:
            raise exceptions.InputError(f"Invalid list name: '{name}'") from e

    def get_compound_list_by_name(self, name: str) -> CompoundList:
        try:
            return next(cl for cl in self._compound_lists if cl.name == name)
        except StopIteration as e:
            raise exceptions.InputError(f"Invalid compound list name: '{name}'") from e

    def get_list_by_abstract_listdef(self, abstract_listdef: CanonListdef) -> RemoteList | CompoundList:
        match abstract_listdef.fetcher_type:
            case RemoteList.FETCHER_TYPE:
                return self.get_remote_list_by_uid(abstract_listdef.address)
            case CompoundList.FETCHER_TYPE:
                return self.get_compound_list_by_uid(abstract_listdef.address)
            case _:
                raise ValueError(f"Invalid LISTDEF: '{abstract_listdef}' type is not any kind of list.")

    @property
    def remote_lists(self) -> typing.Iterable[RemoteList]:
        return iter(self._remote_lists)

    @property
    def compound_lists(self) -> typing.Iterable[CompoundList]:
        return iter(self._compound_lists)

    def sanity_checks(self) -> None:
        obj_with_unset, unset_field = self.get_first_unset()

        if obj_with_unset is not None:
            raise exceptions.InputError(f'Invalid config: found object of type: {type(obj_with_unset)} with unset field: {unset_field}.')

        for rl in self._remote_lists:
            if sum(1 for rl2 in self._remote_lists if rl.name == rl2.name) > 1:
                raise exceptions.InputError(f"Invalid config: found multiple lists named '{rl.name}'.")

            if rl.concrete_listdef.is_special:
                raise exceptions.InputError(f"Invalid config: LISTDEF '{rl.concrete_listdef}' type must not be one of: {', '.join(SPECIAL_FETCHER_TYPES)}.")

        for cl in self._compound_lists:
            if sum(1 for cl2 in self._compound_lists if cl.name == cl2.name) > 1:
                raise exceptions.InputError(f"Invalid config: found multiple compound lists named '{cl.name}'.")

            if len(cl.remote_list_uids) == 0:
                raise exceptions.InputError(f"Invalid config: compound list '{cl.name}' is made up of 0 lists.")
                
            for uid in cl.remote_list_uids:
                try:
                    self.get_remote_list_by_uid(uid)
                except exceptions.InputError as e:
                    raise exceptions.InputError(f"Invalid config: compound list '{cl.name}' references unknown remote list: '{uid}'.") from e

# This object represents the repository itself mainly. Any creating/writing/reading files from the flam directory should go through here.
# For users who just want to work with volatile memory and not load or save anything, we support a "contextless" mode.
# All the ugly if checks for that are encapsulated in this class.
class FlamContext:
    DEFAULT_FLAM_DIR = os.getenv('FLAM_DIR', os.path.join(os.path.expanduser('~'), '.film_flam'))
    
    _LISTFILES_DIR = 'list_files'
    _CONFIGURATION_FILE = 'config.json'

    def __init__(self, flam_dir: None | str = DEFAULT_FLAM_DIR) -> None:
        # TODO: do we need to canonicalize this? what if FLAM_DIR has a different type of backslashes?
        self._flam_dir = flam_dir

        if self._flam_dir is None:
            self._cfg = Configuration.create()
        else:
            self._make_flam_dir()

            cfg_path = self._get_cfg_path()
            self._cfg = Configuration.load(cfg_path) if os.path.exists(cfg_path) else Configuration.create()

    def _make_flam_dir(self) -> None:
        assert self._flam_dir is not None

        try:
            os.mkdir(self._flam_dir)
        except FileExistsError:
            pass

        try:
            os.mkdir(os.path.join(self._flam_dir, self._LISTFILES_DIR))
        except FileExistsError:
            pass

    # List files.
    def load_list_file(self, abstract_listdef: CanonListdef, must_exist: bool = True) -> ListFile:
        if not must_exist and (self._flam_dir is None or not os.path.exists(self._get_list_file_path(abstract_listdef))):
            return ListFile.create()

        return ListFile.load(self._get_list_file_path(abstract_listdef))

    def write_list_file(self, list_file: ListFile) -> None:
        if self._flam_dir is not None:
            list_file.write(self._get_list_file_path(list_file.abstract_listdef))

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
        remote_list = self.cfg.get_remote_list_by_uid(uid)

        # We don't mess with removing the list from its dependent compound lists. Let the user do that.
        dependents = [cl.name for cl in self.cfg.compound_lists if uid in cl.remote_list_uids]

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
        compound_list = self.cfg.get_compound_list_by_uid(uid)

        if self._flam_dir is not None:
            # TODO: delete files
            pass

        self.cfg._compound_lists.remove(compound_list) # pylint: disable=protected-access

    def write_cfg(self) -> None:
        if self._flam_dir is not None:
            self.cfg.write(self._get_cfg_path())
        
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

        # For remote lists we need to convert the name to a uid.
        if eq_idx != -1 and before_eq == RemoteList.FETCHER_TYPE:
            return self.cfg.get_remote_list_by_name(after_eq).abstract_listdef
        
        # Same for compound lists.
        if eq_idx != -1 and before_eq == CompoundList.FETCHER_TYPE:
            return self.cfg.get_compound_list_by_name(after_eq).abstract_listdef
        
        # The generic case where it's whatever=whatever.
        if eq_idx != -1:
            return CanonListdef(before_eq, after_eq)
        
        # If no '=' sign then we'll treat it as a list or compound list, and try to determine which.
        if (list_obj := self._get_implicit_list(before_eq)) is not None:
            return list_obj.abstract_listdef

        raise exceptions.InputError(f"Invalid LISTDEF: '{listdef}'.")

    def canonicalize_listdefs_with_all_expansion(self, listdefs: typing.Iterable[str]) -> typing.Iterator[CanonListdef]:
        for ldef in listdefs:
            cldef = self.canonicalize_listdef(ldef)

            if cldef.fetcher_type == LISTDEF_ALL:
                yield from (rl.abstract_listdef for rl in self.cfg.remote_lists)
            else:
                yield cldef

    def canon_listdef_pretty(self, canon_listdef: CanonListdef) -> str:
        return str(canon_listdef._replace(address=self.cfg.get_list_by_abstract_listdef(canon_listdef).name) if canon_listdef.is_abstract else canon_listdef)

    def _get_implicit_list(self, name: str) -> None | RemoteList | CompoundList:
        try:
            return self.cfg.get_remote_list_by_name(name)
        except exceptions.InputError:
            pass

        try:
            return self.cfg.get_compound_list_by_name(name)
        except exceptions.InputError:
            pass

        return None

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
