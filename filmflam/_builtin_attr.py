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

from . import _dbg
from . import _exc
from . import _reg
from . import _ml
from . import _attr
from . import attrutils

_reg._register_builtin(attrutils.EasyAttribute(
    name = 'title',
    findable_type = _ml.FindableType.MOVIES,
    type_handler = attrutils.str_handler,
    is_array = False,
    extract_from_movie = lambda movie, mlf_movie: mlf_movie.title, # TODO: Handle unset, figure out what we do about not having type checker for this...
))

_reg._register_builtin(attrutils.EasyAttribute(
    name = 'name',
    findable_type = _ml.FindableType.PEOPLE,
    type_handler = attrutils.str_handler,
    is_array = False,
    extract_from_person = lambda person, mlf_person: mlf_person.name,
))

_reg._register_builtin(attrutils.EasyAttribute(
    name = 'characters',
    findable_type = _ml.FindableType.ROLES,
    type_handler = attrutils.str_handler,
    is_array = True,
    extract_from_role = lambda role, mlf_roles: [c for mlf_role in mlf_roles for c in mlf_role.characters],
))
