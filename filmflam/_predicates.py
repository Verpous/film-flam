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

import filmflam.infra as ff
import filmflam._utils as utils
import filmflam.exceptions as exceptions

@ff._register_builtin
class TruePredicate(ff.Predicate, name='true'):
    @classmethod
    def eat(cls, tokens: list[str], at: int, ctx: ff.FlamContext) -> tuple[ff.Predicate, int]:
        return cls(), at

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        return True

@ff._register_builtin
class FalsePredicate(ff.Predicate, name='false'):
    @classmethod
    def eat(cls, tokens: list[str], at: int, ctx: ff.FlamContext) -> tuple[ff.Predicate, int]:
        return cls(), at

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        return False

# class MoviePredicate(Predicate):
#     pass
        
# class PersonPredicate(Predicate):
#     pass

# class RolePredicate(Predicate):
#     pass

# TODO: Predicate ideas:
# Generic predicates:
# * -<attribute-name> [=|+|-|++|--]<value> (obviously. = for eq and is default, +/- for ge/le, ++/-- for strictly gt/lt. Not all attributes support anything other than =.
#                                           Worth noting that if you want to compare equality to a negative number, you can avoid ambiguity by specifying the "=".
#                                           If attribute is array type, compare against first element I think, and false if no first element.
#                                           The names in a group are an array attribute that we don't have to treat special.)
# * -contains <array attribute name> [=|+|-|++|--]<value>
# * -all <array attribute name> [=|+|-|++|--]<value>
# * -size <array attribute name> [=|+|-|++|--]<value> (array len check)
# 
# Person predicates:
# * -appeared-in <pipeline with movie predicates> (searches all crew types)
# * -<crew-type>-in <pipeline with movie predicates> (ex: cast-in, director-in, etc. IDEA: "-cast-in -true" as a way to check if a person is an actor at all)
#
# Movie predicates:
# * -crew-contains <crew-type> <pipeline with person predicates>
# * -crews-contain <pipeline with person predicates> (searches all crew types, beware of people who appear in multiple crew types!)
#
# Role predicates:
# * -crew <crew-type>

def _test_compile(line: str, ctx: None | ff.FlamContext = None) -> None:
    import shlex
    tokens = shlex.split(line)

    if ctx is None:
        ctx = ff.FlamContext(flam_dir=None)

    try:
        filtr = ctx.compile(tokens)
        regurg = ' '.join(ff.exceptions.FilterSyntaxError.format_token(t) for t in filtr.regurgitate())
        print(line, '->', regurg)
    except ff.exceptions.FilterSyntaxError as e:
        print(e)

# _test_compile('')
# _test_compile('-true')
# _test_compile('-true -true -false')
# _test_compile('-true -o ( -false ) )')
# _test_compile('-ftrual | -tue\\" -o ( -false )')
# _test_compile('( ( -true | -true ) ) ! -false')
# _test_compile('( -true " "')
# _test_compile('true')
