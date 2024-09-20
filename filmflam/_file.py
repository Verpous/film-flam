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

import msgspec
import typing
import types

from . import _exc
from . import _dbg

# Users need to know about this type, mainly for type checking reasons, but I don't want them to have to know about msgspec.
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
        obj = cls(**field_values)
        _dbg.logger.info(f'Created serializable: {obj}')
        return obj

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
        _dbg.logger.info(f'Successfully loaded a {cls} of size {len(contents)}B')
        return obj

    @classmethod
    def load_or_create(cls, file: str, **kwargs: typing.Any) -> typing.Self:
        try:
            return cls.load(file)
        except FileNotFoundError:
            _dbg.logger.info(f"File {file} doesn't exist, creating a new instance {cls}")
            obj = cls.create(**kwargs)
            obj.write(file)
            return obj
    
    def write(self, file: str) -> None:
        self.sanity_checks()

        try:
            encoded = msgspec.json.encode(self)
        except msgspec.ValidationError as e:
            raise self._validation_error(f'{e}.') from e

        with open(file, 'wb') as f:
            formatted = msgspec.json.format(encoded)
            f.write(formatted)

        _dbg.logger.info(f'Successfully wrote a {type(self)} of size {len(formatted)}B')

    # Subclasses can override this to add file validity checks beyond what msgspec already does.
    def sanity_checks(self) -> None:
        obj_with_unset, unset_field = self.get_first_unset()

        if obj_with_unset is not None:
            raise self._validation_error(f'Found unset field: {type(obj_with_unset).__name__}.{unset_field}.')

    # Sorts all lists in the file recursively so that we can compare files for equality.
    def canonicalize(self) -> None:
        _dbg.logger.info(f'Canonicalizing a {type(self)}')

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
    def _validation_error(cls, message: str) -> _exc.FileValidationError:
        return _exc.FileValidationError(f'Invalid {cls.__name__}: {message}')
