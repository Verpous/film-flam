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

import filmflam._utils as utils

# Other modules need to know about these, mainly for type checking reasons, but I don't want them to have to know about msgspec.
UnsetType = msgspec.UnsetType

class _ListFileMixin(msgspec.Struct, forbid_unknown_fields=True):
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
            
            if isinstance(value, list) and len(value) > 0 and isinstance(value[0], _ListFileMixin):
                yield from (descendant for child in value for descendant in child.depth_first_iter())
            elif isinstance(value, dict) and len(value) > 0 and isinstance(next(iter(value.values())), _ListFileMixin):
                yield from (descendant for child in value.values() for descendant in child.depth_first_iter())

        yield self

class ListFileRole(_ListFileMixin):
    person_uid:             str
    characters:             list[str]

class ListFileCrew(_ListFileMixin):
    crew_type:              str
    roles_by_uid:           dict[str, ListFileRole]

class ListFilePerson(_ListFileMixin):
    uid:                    str
    name:                   UnsetType | str

    # TODO: Would love to have these but cinemagoer doesn't seem to support them.
    # gender
    # nationality

class ListFileMovie(_ListFileMixin):
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

class ListFile(_ListFileMixin):
    fetcher_type:           UnsetType | str
    address:                UnsetType | str
    id_type:                UnsetType | str

    movies_by_uid:          dict[str, ListFileMovie]
    people_by_uid:          dict[str, ListFilePerson]

    @classmethod
    def load(cls, file: str) -> typing.Self:
        # The beauty of msgspec:
        # 1. It doesn't have shitty security vulnerabilities like jsonpickle.
        # 2. It verifies the json matches the type: if it encounters an unknown field, or a known field with the wrong type, it raises an exception.
        #    Because of this we don't have to even store the version of the file. If we change the file format, msgspec will catch it.
        #    Note: we do not wish to support what msgspec calls "schema evolution" (adding new fields without breaking the ability to decode old files)
        #    This is because if we add a new field, you may need to refetch the whole movie anyway.
        with open(file, 'rb') as f:
            list_file = msgspec.json.decode(f.read(), type=cls)

        list_file.sanity_checks()
        return list_file

    def write(self, file: str) -> None:
        self.sanity_checks()

        with open(file, 'wb') as f:
            encoded = msgspec.json.format(msgspec.json.encode(self))
            f.write(encoded)

    # A few things to make sure the file is proper. The "big" checks happen by msgspec when it encodes/decodes things.
    def sanity_checks(self) -> None:
        obj_with_unset, unset_field = self.get_first_unset()

        if obj_with_unset is not None:
            raise RuntimeError(f'Invalid ListFile: found object of type: {type(obj_with_unset)} with unset field: {unset_field}.')

        for movie in self.movies_by_uid.values():
            if len(CREW_TYPES) != len(movie.crew) or not CREW_TYPES.issuperset(movie.crew.keys()):
                raise RuntimeError(f'Invalid ListFile: found movie: {movie.uid} with bad crew types: {movie.crew.keys()}.')

class RemoteList:
    FETCHER_TYPE = 'list'
    
    def __init__(self) -> None:
        self.name = None
        self.fetcher_type = None
        self.address = None
        self.is_default_fetch = False
        self.is_default_find = False

class CompoundList:
    FETCHER_TYPE = 'compound'

    def __init__(self) -> None:
        self.name = None
        self.remote_list_names = []
        self.filters = []
        self.is_default_find = False

class Configuration:
    def __init__(self) -> None:
        self.remote_lists = []
        self.compound_lists = []

    @classmethod
    def load(cls, file: str) -> typing.Self:
        pass
    
    def write(self, file: str) -> None:
        pass

# This object represents the repository itself mainly. typing.Any creating/writing/reading files from the flam directory should go through here.
# For users who just want to work with volatile memory and not load or save anything, we support a "contextless" mode.
# All the ugly if checks for that are encapsulated in this class.
class FlamContext:
    DEFAULT_FLAM_DIR = os.getenv('FLAM_DIR', os.path.join(os.path.expanduser('~'), '.film_flam'))
    
    _LISTFILES_DIR = 'list_files'
    _CONFIGURATION_FILE = 'config.json'

    def __init__(self, flam_dir: None | str = DEFAULT_FLAM_DIR) -> None:
        self._flam_dir = flam_dir

        if self._flam_dir is None:
            self._cfg = Configuration()
        else:
            self._make_flam_dir()

            cfg_path = self._get_cfg_path()
            self._cfg = Configuration.load(cfg_path) if os.path.exists(cfg_path) else Configuration()

    def load_list_file(self, id_type: str, address: str, must_exist: bool = True) -> ListFile:
        if not must_exist and (self._flam_dir is None or not os.path.exists(self._get_list_file_path(id_type, address))):
            return ListFile.create()

        return ListFile.load(self._get_list_file_path(id_type, address))

    def write_list_file(self, list_file: ListFile) -> None:
        if self._flam_dir is not None:
            assert not isinstance(list_file.id_type, UnsetType) and not isinstance(list_file.address, UnsetType)
            list_file.write(self._get_list_file_path(list_file.id_type, list_file.address))
        
    @property
    def cfg(self) -> Configuration:
        return self._cfg

    def _make_flam_dir(self) -> None:
        assert self._flam_dir is not None

        # TODO: if this gets too annoying there's a with contextmanager to suppress specific errors.
        try:
            os.mkdir(self._flam_dir)
        except FileExistsError:
            pass

        try:
            os.mkdir(os.path.join(self._flam_dir, self._LISTFILES_DIR))
        except FileExistsError:
            pass

    def _get_list_file_path(self, id_type: str, address: str) -> str:
        assert self._flam_dir is not None
        filename = utils.slugify(f'{id_type}_{address}.json')
        return os.path.join(self._flam_dir, self._LISTFILES_DIR, filename)

    def _get_cfg_path(self) -> str:
        assert self._flam_dir is not None
        return os.path.join(self._flam_dir, self._CONFIGURATION_FILE)
        
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
