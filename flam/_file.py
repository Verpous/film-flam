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

from . import _exc
from . import _dbg

# Parent class for all the kinds of files we have. We use msgspec for serialization, and this class adds some niceities on top.
class _FlamSerializable(msgspec.Struct, forbid_unknown_fields=True, weakref=True, order=True, kw_only=True):
    def replace(self, **changes: dict[str, typing.Any]) -> typing.Self:
        return msgspec.structs.replace(self, **changes)

    @classmethod
    def load(cls, path: str) -> typing.Self:
        with open(path, 'rb') as f:
            contents = f.read()

        # msgspec checks that the file schema (field names and their types) matches.
        try:
            obj = msgspec.json.decode(contents, type=cls)
        except msgspec.ValidationError as e:
            raise cls._validation_error(f'{e}.') from e

        obj.sanity_checks()
        _dbg.logger.info(f'Successfully loaded a {cls} of size {len(contents)}B')
        return obj

    def write(self, path: str) -> None:
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
        _dbg.logger.info(f'Canonicalizing a {type(self)}')

        # Must be depth-first for this to work.
        for node in self.depth_first_iter():
            for field in msgspec.structs.fields(node):
                value = getattr(node, field.name)

                # For now only have one field we want to exclude from sorting so we hack it.
                if isinstance(value, list) and field.name != 'filter_tokens':
                    value.sort()

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
