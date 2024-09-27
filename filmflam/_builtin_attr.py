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

import typing

from . import _dbg
from . import _exc
from . import _reg
from . import _ml
from . import _mlf
from . import _attr
from . import attrutils

    # def _extract_from_role(self, role: _ml.Role, mlf_roles: list[_mlf.MLFRole]) -> typing.Any:
    #     assert self._extract_from_role_lambda is not None
    #     return self._extract_from_role_lambda(role, mlf_roles)

    # def _extract_from_person(self, person: _ml.Person, mlf_person: _mlf.MLFPerson) -> typing.Any:
    #     assert self._extract_from_person_lambda is not None
    #     return self._extract_from_person_lambda(person, mlf_person)

def _instantiate_and_register(params: attrutils.EasyAttributeParams) -> typing.Callable[[type[attrutils.EasyAttribute]], None]:
    def internal(cls: type[attrutils.EasyAttribute]) -> None:
        _reg._register_builtin(cls(params))
    return internal

@_instantiate_and_register(attrutils.EasyAttributeParams(
    name = 'title',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_array = False,
))
@attrutils.easy_attribute
def _extract_from_movie(self: attrutils.EasyAttribute, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> str:
    return mlf_movie.title

@_instantiate_and_register(attrutils.EasyAttributeParams(
    name = 'name',
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.STR_HANDLER,
    is_array = False,
))
@attrutils.easy_attribute
def _extract_from_person(self: attrutils.EasyAttribute, person: _ml.Person, mlf_person: _mlf.MLFPerson) -> str:
    return mlf_person.name

@_instantiate_and_register(attrutils.EasyAttributeParams(
    name = 'characters',
    findable_type = _ml.FindableType.ROLES,
    type_handler = attrutils.STR_HANDLER,
    is_array = True,
))
@attrutils.easy_attribute
def _extract_from_role(self: attrutils.EasyAttribute, role: _ml.Role, mlf_roles: list[_mlf.MLFRole]) -> list[str]:
    return [c for mlf_role in mlf_roles for c in mlf_role.characters]
