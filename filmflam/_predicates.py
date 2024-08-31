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
    def eat(cls, tokens: list[str], at: int, find: ff.FindableType, ctx: ff.FlamContext) -> tuple[ff.Predicate, int]:
        return cls(), at

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        return True

@ff._register_builtin
class FalsePredicate(ff.Predicate, name='false'):
    @classmethod
    def eat(cls, tokens: list[str], at: int, find: ff.FindableType, ctx: ff.FlamContext) -> tuple[ff.Predicate, int]:
        return cls(), at

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        return False

@ff._register_builtin
class All(ff.Predicate, name='all'):
    def __init__(self, attribute: ff.Attribute, cmp: ff.ComparisonOp, value: typing.Any) -> None: # TODO: better annotation for value, in many places.
        self._attribute = attribute
        self._cmp = cmp
        self._value = value
    
    @classmethod
    def eat(cls, tokens: list[str], at: int, find: ff.FindableType, ctx: ff.FlamContext) -> tuple[ff.Predicate, int]:
        attribute = cls.eat_attribute(tokens, at, find, ctx, is_array=True)
        cmp, value_str = cls.eat_cmp_value(tokens, at + 1)
        value = None # TODO: use attribute to parse value_str into the attribute's type. Possibly also check if attribute supports the comparator?
        return cls(attribute, cmp, value), at + 2

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        # TODO: If array type, extract first element only.
        actual = self._attribute.extract(None) # TODO: not None of course.
        return all(self._cmp.compare(elem, self._value) for elem in actual)

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield self._attribute.name
        yield self._cmp.sign + str(self._value)

@ff._register_builtin
class Contains(ff.Predicate, name='contains'):
    def __init__(self, attribute: ff.Attribute, cmp: ff.ComparisonOp, value: typing.Any) -> None:
        self._attribute = attribute
        self._cmp = cmp
        self._value = value
    
    @classmethod
    def eat(cls, tokens: list[str], at: int, find: ff.FindableType, ctx: ff.FlamContext) -> tuple[ff.Predicate, int]:
        attribute = cls.eat_attribute(tokens, at, find, ctx, is_array=True)
        cmp, value_str = cls.eat_cmp_value(tokens, at + 1)
        value = None # TODO: use attribute to parse value_str into the attribute's type. Possibly also check if attribute supports the comparator?
        return cls(attribute, cmp, value), at + 2

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        # TODO: If array type, extract first element only.
        actual = self._attribute.extract(None) # TODO: not None of course.
        return any(self._cmp.compare(elem, self._value) for elem in actual)

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield self._attribute.name
        yield self._cmp.sign + str(self._value)

@ff._register_builtin
class Size(ff.Predicate, name='size'):
    def __init__(self, attribute: ff.Attribute, cmp: ff.ComparisonOp, value: typing.Any) -> None:
        self._attribute = attribute
        self._cmp = cmp
        self._value = value
    
    @classmethod
    def eat(cls, tokens: list[str], at: int, find: ff.FindableType, ctx: ff.FlamContext) -> tuple[ff.Predicate, int]:
        attribute = cls.eat_attribute(tokens, at, find, ctx, is_array=True)
        cmp, value_str = cls.eat_cmp_value(tokens, at + 1)
        
        try:
            value = int(value_str)
        except ValueError:
            raise ff.exceptions.FilterSyntaxError(f"Expected value to be an int, but got: '{value_str}'.", tokens=tokens, error_indices=at + 1)

        return cls(attribute, cmp, value), at + 2

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        # TODO: If array type, extract first element only.
        actual = self._attribute.extract(None) # TODO: not None of course.
        return self._cmp.compare(len(actual), self._value)

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield self._attribute.name
        yield self._cmp.sign + str(self._value)

# TODO: Predicate ideas:
# Don't forget for string predicates we should support regex with "anywhere in the string" matching by default!
# Generic predicates:
# * -<attribute-name> [=|+|-|++|--]<value> (obviously. = for eq and is default, +/- for ge/le, ++/-- for strictly gt/lt. Not all attributes support anything other than =.
#                                           Worth noting that if you want to compare equality to a negative number, you can avoid ambiguity by specifying the "=".
#                                           If attribute is array type, compare against first element I think, and false if no first element.
#                                           The names in a group are an array attribute that we don't have to treat special.)
# * -contains <array attribute name> [=|+|-|++|--]<value>
# * -all <array attribute name> [=|+|-|++|--]<value>
# * -size <array attribute name> [=|+|-|++|--]<value> (array len check)
# * -also-in <listdef> (searches for the same uid in another list by the same pivot/crew-type. I think this is only a person/movie predicate, not a role predicate)
# 
# Person predicates:
# * -appeared-in <single with movie predicates> (searches all crew types)
# * -<crew-type>-in <single with movie predicates> (ex: cast-in, director-in, etc. IDEA: "-cast-in -true" as a way to check if a person is an actor at all)
#
# Movie predicates:
# * -crew-contains <crew-type> <single with role predicates>
# * -crews-contain <single with role predicates> (searches all crew types, beware of people who appear in multiple crew types!)
#
# Role predicates:
# * -crew <crew-type>

def _test_compile(line: str, find: ff.FindableType = ff.FindableType.ROLES, ctx: None | ff.FlamContext = None) -> None:
    import shlex
    tokens = shlex.split(line)

    if ctx is None:
        ctx = ff.FlamContext(flam_dir=None)

    try:
        filter = ctx.compile_filter(tokens, find)
        regurg = ' '.join(ff.exceptions.FilterSyntaxError.format_token(t) for t in filter.regurgitate())
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
