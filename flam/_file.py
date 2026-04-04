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
import dataclasses
import json
import time

from . import _exc
from . import _dbg
from . import _gen_version

_start_import_time = time.time()

@dataclasses.dataclass(frozen=True)
class FieldMeta:
    order_matters: bool = False

_default_meta = FieldMeta()

_VERSION_KEY = 'version'

# Parent class for all the kinds of files we have. We use msgspec for serialization, and this class adds some niceities on top.
# Note that file fields are limited in terms of their type. They can be:
# * All kinds of primitive(ish) types: int, str, bool, datetime..
# * _FlamSerializables
# * lists or dicts of any of the above
# In other words we don't support sets, or lists of lists, or whatever else data structure. The reason is depth_first_iter. It can be expanded to support more if needed.
# File implementations also shouldn't change the order of fields because it has bearing on canonicalization.
class _FlamSerializable(msgspec.Struct,
        forbid_unknown_fields=True,     # Better to be strict and reject files which have been tampered with.
        weakref=True,                   # Support referencing file objects by weakref. We use this for configuration files.
        order=True,                     # Support order operators '<', '>=', etc. on file objects, so we can canonicalize even files with lists of serializables.
        kw_only=True):                  # Only allow kw arguments in constructors. Helps avoid bugs.
    def replace(self, **changes: dict[str, typing.Any]) -> typing.Self:
        return msgspec.structs.replace(self, **changes)

    @classmethod
    def load(cls, path: str) -> typing.Self:
        # Log at the start and end at least so we have an idea of how long it took.
        _dbg.logger.info(f'Going to load a {cls} from: {path}')
        
        with open(path, 'rb') as f:
            contents = f.read()

        # msgspec checks that the file schema (field names and their types) matches.
        try:
            obj = msgspec.json.decode(contents, type=cls)
        except msgspec.ValidationError as ve:
            # We are handed this structure in dict format, but really we want it as a sorted list.
            version_upgrades = sorted(cls._version_upgrades().items(), key=lambda vupg: vupg[0])

            try:
                # A lot of things can go wrong in this check since we did not verify a thing about this JSON.
                # If we can't even check that a version upgrade is needed we'll treat the file as failed for the reason msgspec said it is.
                # Once we verify that at least a version upgrade is needed, we'll want to raise version upgrade errors for anything that goes wrong from there.
                obj_json = json.loads(contents)
                is_version_upgrade_needed = obj_json[_VERSION_KEY] <= version_upgrades[-1][0]
            except Exception as e: # pylint: disable=broad-exception-caught
                _dbg.logger.warning(f'No version upgrade needed because of error: {e}')
                is_version_upgrade_needed = False

            if is_version_upgrade_needed:
                obj = cls._get_upgraded(obj_json, version_upgrades)
                obj.write(path)
                _dbg.logger.info(f"Successfully upgraded version of {cls}.")
            else:
                raise cls._validation_error(f'{ve}.') from ve

        _after_decode_time = time.time()

        obj.sanity_checks()
        _dbg.logger.info(f'Successfully loaded a {cls} of size {len(contents)}B')
        return obj

    @classmethod
    def _get_upgraded(cls, obj_json: dict[str, typing.Any], version_upgrades: list[tuple[str, typing.Callable[[dict[str, typing.Any]], None]]]) -> typing.Self:
        _dbg.logger.info(f"Version upgrade of {cls} needed! {obj_json[_VERSION_KEY]=}, {version_upgrades=}.")

        # Find the earliest relevant version upgrade.
        # Note that we can assume version_upgrades isn't empty, and that the highest version in the array is >= obj[_VERSION_KEY].
        first_upgrade_idx = next(i for i, (version, _) in enumerate(version_upgrades) if version >= obj_json[_VERSION_KEY])

        for _, upgrade_from_version in version_upgrades[first_upgrade_idx:]:
            try:
                upgrade_from_version(obj_json)
            except Exception as e:
                raise cls._validation_error(f"Failed to upgrade version due to error: {e}") from e

        obj_json[_VERSION_KEY] = _gen_version.__version__
        upgraded_contents = json.dumps(obj_json).encode()

        try:
            return msgspec.json.decode(upgraded_contents, type=cls)
        except msgspec.ValidationError as ve:
            raise cls._validation_error(f'{ve}.') from ve

    # Abstract function. Returns a dict[VERSION, UPGRADE_FROM_VERSION], where:
    # * VERSION is a flam version for which the immediate next version included a change in the file format.
    # * UPGRADE_FROM_VERSION is a function which takes files of version VERSION (or older as long as it had the same file format),
    #   and modifies the JSON to bring it up to the version immediately succeeding VERSION.
    # 
    # This setup may seem a little weird. It's this way because when we change the file format,
    # we don't actually know yet what will be the version number it releases under, but we know what version it will definitely be greater than.
    @classmethod
    def _version_upgrades(cls) -> dict[str, typing.Callable[[dict[str, typing.Any]], None]]:
        return {}

    def write(self, path: str) -> None:
        # Log at the start and end at least so we have an idea of how long it took.
        _dbg.logger.info(f'Going to write a {type(self)} to: {path}')

        assert hasattr(self, _VERSION_KEY)
        self.version = _gen_version.__version__ # pylint: disable=attribute-defined-outside-init

        self.sanity_checks()

        try:
            encoded = msgspec.json.encode(self)
        except msgspec.ValidationError as e:
            raise self._validation_error(f'{e}.') from e

        formatted = msgspec.json.format(encoded)
        
        with open(path, 'wb') as f:
            f.write(formatted)

        _dbg.logger.info(f'Successfully wrote a {type(self)} of size {len(formatted)}B')

    # Subclasses can override this to add file validity checks beyond what msgspec already does.
    def sanity_checks(self) -> None:
        pass

    # Sorts all lists in the file recursively so that we can compare files for equality.
    def canonicalize(self) -> None:
        # Log at the start and end at least so we have an idea of how long it took.
        _dbg.logger.info(f'Canonicalizing a {type(self)}')

        # Must be depth-first for this to work.
        for node in self.depth_first_iter():
            for field in msgspec.structs.fields(node):
                value = getattr(node, field.name)

                # For now only have one field we want to exclude from sorting so we hack it.
                if isinstance(value, list) and not self._get_meta(field).order_matters:
                    value.sort()

        _dbg.logger.info(f'Finished canonicalizing {type(self)}')

    def depth_first_iter(self) -> typing.Iterable[_FlamSerializable]:
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

    @classmethod
    def _get_meta(cls, field: msgspec.structs.FieldInfo) -> FieldMeta:
        if typing.get_origin(field.type) is typing.Annotated:
            for annot in field.type.__metadata__:
                if isinstance(annot, FieldMeta):
                    return annot

        return _default_meta

_dbg.logger.info(f'Module import time: {time.time() - _start_import_time}s')
