# Copyright (C) 2026 Aviv Edery.

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

# pylint: disable=unused-argument

import typing
import dataclasses

from . import _ctx
from . import _filter
from . import _exc
from . import _reg
from . import _attr
from . import _ml
from . import _dbg
from . import _mlf

#region generic predicates

# -true : Always true.
@_reg._register_builtin
class TruePredicatePredicate(_filter.Predicate, name_without_type='true'):
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        return cls(), at

    def excrete(self, findable: _ml.Findable) -> bool:
        return True

# -false : Always false.
@_reg._register_builtin
class FalsePredicatePredicate(_filter.Predicate, name_without_type='false'):
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        return cls(), at

    def excrete(self, findable: _ml.Findable) -> bool:
        return False

# -every ATTRIBUTE CMPTO : for array attributes, check if every array element compares true.
@_reg._register_builtin
class EveryPredicate(_filter.Predicate, name_without_type='every'):
    def __init__(self, attribute: _attr.Attribute, cmpto: _attr.CmpTo) -> None:
        # This and all other predicates here should name their fields referencing attributes by this name '_attribute', because parse_columns expects it.
        self._attribute = attribute
        self._cmpto = cmpto
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        attribute = cls.eat_attribute(params, at)
        cmpto = cls.eat_cmpto(params, at + 1, attribute)
        return cls(attribute, cmpto), at + 2

    def excrete(self, findable: _ml.Findable) -> bool:
        value = findable.extract(self._attribute)

        if isinstance(value, list):
            return all(self._cmpto(elem) for elem in value)

        return self._cmpto(value)

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield self._attribute.qualified_name
        yield str(self._cmpto)

# -has ATTRIBUTE : true if we have some value populated for this attribute (i.e. not none or empty).
@_reg._register_builtin
class HasPredicate(_filter.Predicate, name_without_type='has'):
    def __init__(self, attribute: _attr.Attribute) -> None:
        self._attribute = attribute
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        attribute = cls.eat_attribute(params, at)
        return cls(attribute), at + 1

    def excrete(self, findable: _ml.Findable) -> bool:
        value = findable.extract(self._attribute)

        if isinstance(value, list):
            # Works even in the empty list case.
            return any(primitive is not None for primitive in value)

        return value is not None

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield self._attribute.qualified_name

# -index ATTRIBUTE INDEX CMPTO : true if the attribute compares true at the given index.
@_reg._register_builtin
class IndexPredicate(_filter.Predicate, name_without_type='index'):
    def __init__(self, attribute: _attr.Attribute, index: int, cmpto: _attr.CmpTo) -> None:
        self._attribute = attribute
        self._index = index
        self._cmpto = cmpto
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        attribute = cls.eat_attribute(params, at)
        index = cls.eat_type(params, at + 1, 'an index', int)
        cmpto = cls.eat_cmpto(params, at + 2, attribute)
        return cls(attribute, index, cmpto), at + 3

    def excrete(self, findable: _ml.Findable) -> bool:
        value = findable.extract(self._attribute)

        if isinstance(value, list):
            # We'll defer it to python to handle index errors. This means we support things python supports like -1 for the last element in the list.
            # In case of index errors, we'll return false and not raise an error. Iteration is over many arrays and user can't know exactly what each of them is like.
            try:
                return self._cmpto(value[self._index])
            except IndexError:
                return False

        # For non-lists we'll only accept index 0.
        return self._index == 0 and self._cmpto(value)

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield self._attribute.qualified_name
        yield str(self._index)
        yield str(self._cmpto)

# -has-index ATTRIBUTE INDEX : true if the attribute has a not-None value at this index.
@_reg._register_builtin
class HasIndexPredicate(_filter.Predicate, name_without_type='has-index'):
    def __init__(self, attribute: _attr.Attribute, index: int) -> None:
        self._attribute = attribute
        self._index = index
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        attribute = cls.eat_attribute(params, at)
        index = cls.eat_type(params, at + 1, 'an index', int)
        return cls(attribute, index), at + 2

    def excrete(self, findable: _ml.Findable) -> bool:
        value = findable.extract(self._attribute)

        if isinstance(value, list):
            try:
                return value[self._index] is not None
            except IndexError:
                return False

        # For non-lists we'll only accept index 0.
        return self._index == 0 and value is not None

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield self._attribute.qualified_name
        yield str(self._index)

# Examples to help understand -superset, -sameset, -subset:
# flam find movies -superset director [ coen tarantino spielberg ] - every director must be either a coen, tarantino, or spielberg.
# flam find movies -subset director [ coen tarantino spielberg ] - must be directed by coen, tarantino, and spielberg at least. Same as `-director coen -director tarantino -director spielberg`
# flam find movies -sameset director [ coen tarantino spielberg ] - must be directed by a coen, tarantino, and spielberg exactly

# -superset ATTRIBUTE CMPTO... : true if every array element in the attribute matches at least one of CMPTOs.
@_reg._register_builtin
class SupersetPredicate(_filter.Predicate, name_without_type='superset'):
    # There is no nice way to remove the code repetition that all XSetPredicate classes have the same functions except excrete.
    # * Code sharing via subclassing doesn't work because you can't pass the name_without_type yet at class init time.
    # * Code sharing via mixin class or shared classmethods is just really horrible to type hint and adds a lot of boilerplate.
    def __init__(self, attribute: _attr.Attribute, cmptos: list[_attr.CmpTo]) -> None:
        self._attribute = attribute
        self._cmptos = cmptos
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        attribute = cls.eat_attribute(params, at)
        cmptos, until = cls.eat_listof(lambda p, a: cls.eat_cmpto(p, a, attribute), params, at + 1, at_least_one=False)
        return cls(attribute, cmptos), until

    @classmethod
    def is_superset(cls, cmptos: list[_attr.CmpTo], value: _attr.AttributeValue) -> bool:
        if isinstance(value, list):
            for primitive in value:
                if all(not cmpto(primitive) for cmpto in cmptos):
                    return False

            return True

        return any(cmpto(value) for cmpto in cmptos)

    def excrete(self, findable: _ml.Findable) -> bool:
        value = findable.extract(self._attribute)
        return self.is_superset(self._cmptos, value)

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield self._attribute.qualified_name
        yield min(_filter.Pipeline.LPAREN)
        yield from (str(cmpto) for cmpto in self._cmptos)
        yield min(_filter.Pipeline.RPAREN)

# -subset ATTRIBUTE CMPTO... : true if every CMPTO matches at least one array element in the attribute.
@_reg._register_builtin
class SubsetPredicate(_filter.Predicate, name_without_type='subset'):
    def __init__(self, attribute: _attr.Attribute, cmptos: list[_attr.CmpTo]) -> None:
        self._attribute = attribute
        self._cmptos = cmptos
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        attribute = cls.eat_attribute(params, at)
        cmptos, until = cls.eat_listof(lambda p, a: cls.eat_cmpto(p, a, attribute), params, at + 1, at_least_one=False)
        return cls(attribute, cmptos), until

    @classmethod
    def is_subset(cls, cmptos: list[_attr.CmpTo], value: _attr.AttributeValue) -> bool:
        if isinstance(value, list):
            for cmpto in cmptos:
                if all(not cmpto(primitive) for primitive in value):
                    return False

            return True

        return all(cmpto(value) for cmpto in cmptos)
    
    def excrete(self, findable: _ml.Findable) -> bool:
        value = findable.extract(self._attribute)
        return self.is_subset(self._cmptos, value)

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield self._attribute.qualified_name
        yield min(_filter.Pipeline.LPAREN)
        yield from (str(cmpto) for cmpto in self._cmptos)
        yield min(_filter.Pipeline.RPAREN)

# -sameset ATTRIBUTE CMPTO... : true if every CMPTO matches at least one array element in the attribute and every array element in the attribute matches at least one CMPTO.
@_reg._register_builtin
class SamesetPredicate(_filter.Predicate, name_without_type='sameset'):
    def __init__(self, attribute: _attr.Attribute, cmptos: list[_attr.CmpTo]) -> None:
        self._attribute = attribute
        self._cmptos = cmptos
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        attribute = cls.eat_attribute(params, at)
        cmptos, until = cls.eat_listof(lambda p, a: cls.eat_cmpto(p, a, attribute), params, at + 1, at_least_one=False)
        return cls(attribute, cmptos), until

    def excrete(self, findable: _ml.Findable) -> bool:
        value = findable.extract(self._attribute)
        return SubsetPredicate.is_subset(self._cmptos, value) and SupersetPredicate.is_superset(self._cmptos, value)

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield self._attribute.qualified_name
        yield min(_filter.Pipeline.LPAREN)
        yield from (str(cmpto) for cmpto in self._cmptos)
        yield min(_filter.Pipeline.RPAREN)

# -in-list LISTDEF... : true if the findable is also in the list defined by LISTDEFs.
# NOTE: this predicate doesn't check for uid family mismatch. If there is a mismatch then it will simply not find the uid and return false.
@_reg._register_builtin
class InListPredicate(_filter.Predicate, name_without_type='in-list'):
    def __init__(self, movie_list: _ml.MovieList) -> None:
        self._movie_list = movie_list
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        movie_list, until = cls.eat_movie_list(params, at)
        return cls(movie_list), until

    # Split implementations per findable type because this is more complicated than you think.
    # For movies, it's the easiest. Just try to get a movie with that uid.
    def _excrete_from_movie(self, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> bool:
        return self._movie_list.get_movie_by_uid(movie.uid) is not None

    # For people it's complicated. We want to return true even if the same People is not exactly in the other list, but a superset People is.
    def _excrete_from_people(self, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> bool:
        return people.minimal_superset_people_in_other_list(self._movie_list) is not None

    # For roles, we could get the superset people and see if they were also in this movie. But just checking if the movie is in the other list is enough.
    # It's clearly a necessary condition. But it is also sufficient because if the movie is in this other list then necessarily that list has a superset people.
    # This is because at minimum there is always a group of the entire crew for each movie in the list.
    def _excrete_from_role(self, role: _ml.Role, mlf_roles: _ml.MLFRolesDict, mlf_movie: _mlf.MLFMovie, mlf_people: list[_mlf.MLFPerson]) -> bool:
        return self._excrete_from_movie(role.movie, mlf_movie)

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()

        # We handle multiple listdefs as best we can but it's not great.
        yield min(_filter.Pipeline.LPAREN)
        yield from self._movie_list.abstract_listdef.pretty(self._movie_list.ctx).split(' ')
        yield min(_filter.Pipeline.RPAREN)

#endregion

#region movie predicates

# -any-role CT_GM... ROLES_SINGLE : scan the movie's crew according to CT_GMs for a group which passes the filter ROLES_SINGLE.
# There's no need for -any-people because the relationship between associated people and roles is 1 to 1.
@_reg._register_builtin
class AnyRolePredicate(_filter.Predicate, name_without_type='any-role', findable_type=_ml.FindableType.MOVIES):
    # Would be really nice to not duplicate all the similar code between any-X and every-X predicates but it's not so simple. See comment on SupersetPredicate.
    def __init__(self, ct_gms: list[tuple[_ml.CrewType, _ml.GroupMode]], filter: _filter.Filter) -> None:
        self._ct_gms = ct_gms
        self._filter = filter
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        ct_gms, filter_idx = cls.eat_listof(cls.eat_ct_gm, params, at, at_least_one=False)

        # As a secret feature, if ct_gms list is empty we'll consider it to mean every crew type except any.
        if len(ct_gms) == 0:
            ct_gms = [(crew_type, _ml.GroupMode.DEFAULT) for crew_type in _ml.CrewType.iterate_except_any()]

        sub_params = dataclasses.replace(params, find=_ml.FindableType.ROLES)
        filter, until = cls.eat_single(sub_params, filter_idx)
        return cls(ct_gms, filter), until

    def _excrete_from_movie(self, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> bool:
        for ct_gm in self._ct_gms:
            for role in movie.associated_roles(*ct_gm):
                if self._filter.excrete(role):
                    return True

        return False

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield min(_filter.Pipeline.LPAREN)
        yield from (_ml.ct_gm_to_str(*ct_gm) for ct_gm in self._ct_gms)
        yield min(_filter.Pipeline.RPAREN)
        yield from self._filter.regurgitate()

    def colonoscopy(self) -> typing.Iterable[_filter.FilterMember]:
        yield self
        yield from self._filter.colonoscopy()

# -every-role CT_GM... ROLES_SINGLE : scan the movie's crew according to CT_GMs to see if every group passes the filter ROLES_SINGLE.
@_reg._register_builtin
class EveryRolePredicate(_filter.Predicate, name_without_type='every-role', findable_type=_ml.FindableType.MOVIES):
    def __init__(self, ct_gms: list[tuple[_ml.CrewType, _ml.GroupMode]], filter: _filter.Filter) -> None:
        self._ct_gms = ct_gms
        self._filter = filter
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        ct_gms, filter_idx = cls.eat_listof(cls.eat_ct_gm, params, at, at_least_one=False)

        # As a secret feature, if ct_gms list is empty we'll consider it to mean every crew type except any.
        if len(ct_gms) == 0:
            ct_gms = [(crew_type, _ml.GroupMode.DEFAULT) for crew_type in _ml.CrewType.iterate_except_any()]

        sub_params = dataclasses.replace(params, find=_ml.FindableType.ROLES)
        filter, until = cls.eat_single(sub_params, filter_idx)
        return cls(ct_gms, filter), until

    def _excrete_from_movie(self, movie: _ml.Movie, mlf_movie: _mlf.MLFMovie) -> bool:
        for ct_gm in self._ct_gms:
            for role in movie.associated_roles(*ct_gm):
                if not self._filter.excrete(role):
                    return False

        return True

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield min(_filter.Pipeline.LPAREN)
        yield from (_ml.ct_gm_to_str(*ct_gm) for ct_gm in self._ct_gms)
        yield min(_filter.Pipeline.RPAREN)
        yield from self._filter.regurgitate()

    def colonoscopy(self) -> typing.Iterable[_filter.FilterMember]:
        yield self
        yield from self._filter.colonoscopy()

#endregion

#region people predicates

# -any-movie MOVIES_SINGLE : scan the people's associated movies for one which passes the filter MOVIES_SINGLE.
# There's no need for -any-people because the relationship between associated people and roles is 1 to 1.
@_reg._register_builtin
class AnyMoviePredicate(_filter.Predicate, name_without_type='any-movie', findable_type=_ml.FindableType.PEOPLE):
    def __init__(self, filter: _filter.Filter) -> None:
        self._filter = filter
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        sub_params = dataclasses.replace(params, find=_ml.FindableType.MOVIES)
        filter, until = cls.eat_single(sub_params, at)
        return cls(filter), until

    def _excrete_from_people(self, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> bool:
        for movie in people.associated_movies():
            if self._filter.excrete(movie):
                return True

        return False

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield from self._filter.regurgitate()

    def colonoscopy(self) -> typing.Iterable[_filter.FilterMember]:
        yield self
        yield from self._filter.colonoscopy()

# -every-movie MOVIES_SINGLE : scan the people's associated movies to see if they all pass the filter MOVIES_SINGLE.
@_reg._register_builtin
class EveryMoviePredicate(_filter.Predicate, name_without_type='every-movie', findable_type=_ml.FindableType.PEOPLE):
    def __init__(self, filter: _filter.Filter) -> None:
        self._filter = filter
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        sub_params = dataclasses.replace(params, find=_ml.FindableType.MOVIES)
        filter, until = cls.eat_single(sub_params, at)
        _dbg.logger.info(f'Ate: {list(filter.regurgitate())}')
        return cls(filter), until

    def _excrete_from_people(self, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> bool:
        for movie in people.associated_movies():
            if not self._filter.excrete(movie):
                return False

        return True

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield from self._filter.regurgitate()

    def colonoscopy(self) -> typing.Iterable[_filter.FilterMember]:
        yield self
        yield from self._filter.colonoscopy()

# -as CREW_TYPE PEOPLE_SINGLE : check if the people pass the filter PEOPLE_SINGLE when they are another crew type.
@_reg._register_builtin
class AsPredicate(_filter.Predicate, name_without_type='as', findable_type=_ml.FindableType.PEOPLE):
    def __init__(self, crew_type: _ml.CrewType, filter: _filter.Filter) -> None:
        self._crew_type = crew_type
        self._filter = filter
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        crew_type = cls.eat_type(params, at, 'a crew type', _ml.CrewType)
        filter, until = cls.eat_single(params, at + 1)
        return cls(crew_type, filter), until

    def _excrete_from_people(self, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> bool:
        minsuper = people.minimal_superset_people_in_other_crew_type(self._crew_type)
        return minsuper is not None and self._filter.excrete(minsuper)

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield str(self._crew_type)
        yield from self._filter.regurgitate()

    def colonoscopy(self) -> typing.Iterable[_filter.FilterMember]:
        yield self
        yield from self._filter.colonoscopy()

# -any-person PEOPLE_SINGLE : Separate the people if they are grouped and check if any of the split people pass the filter PEOPLE_SINGLE.
@_reg._register_builtin
class AnyPersonPredicate(_filter.Predicate, name_without_type='any-person', findable_type=_ml.FindableType.PEOPLE):
    def __init__(self, filter: _filter.Filter) -> None:
        self._filter = filter
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        filter, until = cls.eat_single(params, at)
        return cls(filter), until

    def _excrete_from_people(self, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> bool:
        match people.group_mode:
            case _ml.GroupMode.SEPARATE:
                return self._filter.excrete(people)
            case _ml.GroupMode.GROUP:
                ct_gm_separate = (people.crew_type, _ml.GroupMode.SEPARATE)

                for mlf_person in people.underlying_file_people_readonly:
                    # get_by_uid should always succeed.
                    uid_as_separate = _ml.People.compose_uid([mlf_person.uid], *ct_gm_separate)
                    person = people.movie_list.get_people_by_uid(uid_as_separate, ct_gm_hint=ct_gm_separate)
                    assert person is not None
                    
                    if self._filter.excrete(person):
                        return True

                return False
            case _:
                raise RuntimeError(f"Unexpected {people.group_mode}")

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield from self._filter.regurgitate()

    def colonoscopy(self) -> typing.Iterable[_filter.FilterMember]:
        yield self
        yield from self._filter.colonoscopy()

# -every-person PEOPLE_SINGLE : Separate the people if they are grouped and check if every split person passes the filter PEOPLE_SINGLE.
@_reg._register_builtin
class EveryPersonPredicate(_filter.Predicate, name_without_type='every-person', findable_type=_ml.FindableType.PEOPLE):
    def __init__(self, filter: _filter.Filter) -> None:
        self._filter = filter
    
    @classmethod
    def eat(cls, params: _filter.EatParams, at: int) -> tuple[_filter.Predicate, int]:
        filter, until = cls.eat_single(params, at)
        return cls(filter), until

    def _excrete_from_people(self, people: _ml.People, mlf_people: list[_mlf.MLFPerson]) -> bool:
        match people.group_mode:
            case _ml.GroupMode.SEPARATE:
                return self._filter.excrete(people)
            case _ml.GroupMode.GROUP:
                ct_gm_separate = (people.crew_type, _ml.GroupMode.SEPARATE)

                for mlf_person in people.underlying_file_people_readonly:
                    # get_by_uid should always succeed.
                    uid_as_separate = _ml.People.compose_uid([mlf_person.uid], *ct_gm_separate)
                    person = people.movie_list.get_people_by_uid(uid_as_separate, ct_gm_hint=ct_gm_separate)
                    assert person is not None
                    
                    if not self._filter.excrete(person):
                        return False

                return True
            case _:
                raise RuntimeError(f"Unexpected {people.group_mode}")

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield from self._filter.regurgitate()

    def colonoscopy(self) -> typing.Iterable[_filter.FilterMember]:
        yield self
        yield from self._filter.colonoscopy()

#endregion

def _test_compile(line: str, find: _ml.FindableType = _ml.FindableType.ROLES, ctx: None | _ctx.FlamContext = None) -> None:
    import shlex
    tokens = shlex.split(line)

    if ctx is None:
        ctx = _ctx.FlamContext(flam_dir=None)

    try:
        filter = ctx.compile_filter(tokens, find)
        regurg = ' '.join(_exc.FilterSyntaxError.format_token(t) for t in filter.regurgitate())
        print(line, '->', regurg)
    except _exc.FilterSyntaxError as e:
        print(e)

# _test_compile('')
# _test_compile('-true')
# _test_compile('-true -true -false')
# _test_compile('-true -o ( -false ) )')
# _test_compile('-ftrual | -tue\\" -o ( -false )')
# _test_compile('( ( -true | -true ) ) ! -false')
# _test_compile('( -true " "')
# _test_compile('true')
