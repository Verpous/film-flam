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

# Not even worth bothering trying to type hint this file without this.
from __future__ import annotations

import os
import abc
import msgspec
import typing
import types
import uuid
import re
import copy
import contextlib
import difflib
import enum
import importlib
import tempfile
import atexit

import filmflam._utils as utils
import filmflam.exceptions as exceptions

#region serialization

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
        return cls(**field_values)

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
        return obj

    @classmethod
    def load_or_create(cls, file: str, **kwargs: typing.Any) -> typing.Self:
        try:
            return cls.load(file)
        except FileNotFoundError:
            return cls.create(**kwargs)
    
    def write(self, file: str) -> None:
        self.sanity_checks()

        try:
            encoded = msgspec.json.encode(self)
        except msgspec.ValidationError as e:
            raise self._validation_error(f'{e}.') from e

        with open(file, 'wb') as f:
            f.write(msgspec.json.format(encoded))

    # Subclasses can override this to add file validity checks beyond what msgspec already does.
    def sanity_checks(self) -> None:
        obj_with_unset, unset_field = self.get_first_unset()

        if obj_with_unset is not None:
            raise self._validation_error(f'Found unset field: {type(obj_with_unset).__name__}.{unset_field}.')

    # Sorts all lists in the file recursively so that we can compare files for equality.
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
    def _validation_error(cls, message: str) -> exceptions.FileValidationError:
        return exceptions.FileValidationError(f'Invalid {cls.__name__}: {message}')

# TODO: Don't like the name "list", could too easily be confused with too many things. Maybe I should just invent a word and call it a "Flist"?
# ListFile-related objects go here.
class ListFileRole(_FlamSerializable):
    person_uid:             str
    characters:             list[str]

class ListFileCrew(_FlamSerializable):
    crew_type:              str
    roles_by_uid:           dict[str, ListFileRole]

class ListFilePerson(_FlamSerializable):
    uid:                    str
    name:                   UnsetType | str
    # Would love to add gender, nationality but cinemagoer doesn't have them.

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
    # TODO: consider adding languages, countries

    # crew type -> crew object. It makes things much nicer when you can reference the crew type you want with this indirection,
    # but the downside (as opposed to having a field for each crew type), is that we have to check dynamically that no crew types were added or are missing.
    # msgspec supports TypedDict, but it has problems with initializing a default.
    crew:                   dict[str, ListFileCrew]

class ListFile(_FlamSerializable):
    # These two fields are redundant, they are essentially the filename so the user must already know them to reach them. but if I'll omit them I'll regret it.
    fetcher_type:           UnsetType | str
    address:                UnsetType | str

    # Files are "compatible" if they have a matching uid_type. This is because I have no good way of identifying matching items between, say, IMDb and Letterboxd.
    # If a list originates from IMDb, all the uids in the file will be from IMDb, and so it will only be compatible with other IMDb-based lists.
    uid_type:               UnsetType | str

    movies_by_uid:          dict[str, ListFileMovie]
    people_by_uid:          dict[str, ListFilePerson]

    @property
    def abstract_listdef(self) -> CanonListdef:
        assert not isinstance(self.fetcher_type, UnsetType) and not isinstance(self.address, UnsetType)
        return CanonListdef(self.fetcher_type, self.address)

    def sanity_checks(self) -> None:
        super().sanity_checks()
        crew_types_set = set(ct.value for ct in CrewType)

        for movie in self.movies_by_uid.values():
            # I verified this check works.
            if crew_types_set != movie.crew.keys():
                raise self._validation_error(f'Found movie: {movie.uid} with bad crew types: {movie.crew.keys()}.')

# This is where Configuration objects begin.
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

# TODO: rename to CompositeList!
class CompositeList(_FlamSerializable):
    FETCHER_TYPE: typing.ClassVar[str] = 'composite'

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

# TODO: Maybe the configuration should use "schema evolution".
class Configuration(_FlamSerializable):
    _remote_lists:          list[RemoteList]
    _composite_lists:        list[CompositeList]
    extensions:             list[str]

    # TODO: Forbid special characters in list names that might be confused for a filter token.
    def sanity_checks(self) -> None:
        super().sanity_checks()

        for rl in self._remote_lists:
            if sum(1 for rl2 in self._remote_lists if rl.name == rl2.name) > 1:
                raise self._validation_error(f"Found multiple lists named '{rl.name}'.")

            if rl.concrete_listdef.is_special:
                raise self._validation_error(f"LISTDEF '{rl.concrete_listdef}' type must not be one of: {', '.join(_SPECIAL_FETCHER_TYPES)}.")

        for cl in self._composite_lists:
            if sum(1 for cl2 in self._composite_lists if cl.name == cl2.name) > 1:
                raise self._validation_error(f"Found multiple composite lists named '{cl.name}'.")

            if len(cl.remote_list_uids) == 0:
                raise self._validation_error(f"Composite list '{cl.name}' is made up of 0 lists.")
                
            for uid in cl.remote_list_uids:
                try:
                    # Unfortunately the get_by_uid method is not accessible from here, see comment in FlamContext.
                    next(rl for rl in self._remote_lists if rl.uid == uid)
                except StopIteration as e:
                    raise self._validation_error(f"Composite list '{cl.name}' references unknown remote list: '{uid}'.") from e

class _CompositeListMetadata(_FlamSerializable):
    uid:                    str
    dependency_mtime:       dict[str, float]

class _FlamMetadata(_FlamSerializable):
    composite_lists_by_uid:  dict[str, _CompositeListMetadata]

#endregion serialization

#region fetching

class ListFetcher(abc.ABC):
    fetcher_type: str
    uid_type: str

    # Subclasses must provide a fetcher_type, and may optionally provide an uid_type if they have multiple fetchers that they want to be compatible.
    def __init_subclass__(cls, fetcher_type: str, uid_type: None | str = None, **kwargs: typing.Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.fetcher_type = fetcher_type
        cls.uid_type = uid_type if uid_type is not None else fetcher_type

    def __init__(self, concrete_listdef: CanonListdef, abstract_listdef: CanonListdef) -> None:
        self._concrete_listdef = concrete_listdef
        self._abstract_listdef = abstract_listdef

    @property
    def concrete_listdef(self) -> CanonListdef:
        return self._concrete_listdef

    @property
    def abstract_listdef(self) -> CanonListdef:
        return self._abstract_listdef

    @abc.abstractmethod
    def fetch_into_file(self, list_file: ListFile) -> None:
        # Populates list_file with data. It may already have preexisting data if updating an existing file.
        # Must leave no field unset. Even if it's an optional field it must explicitly be set to None.
        pass

def _get_all_used_person_uids(list_file: ListFile) -> typing.Iterator[str]:
    for movie_lf in list_file.movies_by_uid.values():
        for crew in movie_lf.crew.values():
            for role in crew.roles_by_uid.values():
                yield role.person_uid

def _remove_unused_people(list_file: ListFile) -> None:
    used_person_uids = set(_get_all_used_person_uids(list_file))
    list_file.people_by_uid = {uid: person for uid, person in list_file.people_by_uid.items() if uid in used_person_uids}

#endregion fetching

#region filters

# FILTER    := PIPELINE | <epsilon>
# PIPELINE  := SINGLE JOINABLE*
# SINGLE    := NEGATIVE | POSITIVE
# POSITIVE  := PREDICATE | ( PIPELINE )
# NEGATIVE  := NOT POSITIVE
# JOINABLE  := CONJOINED | DISJOINED | SINGLE
# CONJOINED := AND SINGLE
# DISJOINED := OR SINGLE
# PREDICATE := -<name> <arg1> <arg2>...

# OR        := -o | -or  | `|`
# AND       := -a | -and | &
# NOT       := -n | -not | !
# (         := (  | [    | -lparen
# )         := )  | ]    | -rparen

# This one's for you, mayer.
_EinGafrurError = exceptions.FilterSyntaxError

# We represent filters as an AST of FilterMembers.
class FilterMember(abc.ABC):
    # TODO: annotate this better once I know how.
    # Takes in a found item (movie, person, or role) and returns true if it passes the filter.
    @abc.abstractmethod
    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        pass

    # Decompiles the filter into a list of tokens.
    @abc.abstractmethod
    def regurgitate(self) -> typing.Iterable[str]:
        pass

    # Helper methods for parsing below.
    @classmethod
    def eat_str(cls, tokens: list[str], at: int, description: str, error_indices: int | typing.Iterable[int] = -1, is_terminal: bool = False) -> str:
        if at >= len(tokens):
            raise _EinGafrurError(f"Expected {description}, but reached the end of input.", tokens=tokens, is_terminal=is_terminal, error_indices=error_indices)

        return tokens[at]

    @classmethod
    def eat_one_of(cls, tokens: list[str], at: int, description: str, options: set[str], is_terminal: bool = False) -> str:
        s = cls.eat_str(tokens, at, description, is_terminal)
        
        if s not in options:
            raise _EinGafrurError(f"Expected {description}, but got: '{s}'.", tokens=tokens, is_terminal=is_terminal, error_indices=at)

        return s

    # TODO: Also receive the attribute owner?
    @classmethod
    def eat_attribute(cls, tokens: list[str], at: int, find: FindableType, ctx: FlamContext, is_array: bool = False) -> Attribute:
        description = 'a valid attribute name'
        attribute_name = cls.eat_str(tokens, at, description)
        attribute = next((registry.get_attribute(attribute_name) for registry in ctx.registries_to_try() if registry.has_attribute(attribute_name)), None)

        if attribute is None:
            raise _EinGafrurError(f"Expected {description}, but got: '{attribute_name}'.", tokens=tokens, error_indices=at)

        if not attribute.owner.is_compatible(find):
            raise _EinGafrurError(f"Expected attribute of {find}, but got: '{attribute_name}' which belongs to {attribute.owner}.", tokens=tokens, error_indices=at)

        if is_array and not attribute.is_array:
            # TODO: "which is of type X"? Or nah?
            raise _EinGafrurError(f"Expected attribute to be an array type, but got: '{attribute_name}'.", tokens=tokens, error_indices=at)

        return attribute

    @classmethod
    def eat_cmp_value(cls, tokens: list[str], at: int) -> tuple[ComparisonOp, str]:
        cmp_value = cls.eat_str(tokens, at, 'a value')
        # TODO: Cast value into correct type?
        return cls.split_cmp_value(cmp_value)

    @classmethod
    def split_cmp_value(cls, cmp_value: str) -> tuple[ComparisonOp, str]:
        # TODO: Could be sped up with a dictionary.
        for cmp in ComparisonOp:
            if cmp_value.startswith(cmp.sign):
                return cmp, cmp_value.removeprefix(cmp.sign)

        return ComparisonOp.EQ, cmp_value

class Filter(FilterMember):
    def __init__(self, pipeline: None | Pipeline, find: FindableType) -> None:
        self._pipeline = pipeline
        self._find = find

    @property
    def findable_type(self) -> FindableType:
        return self._find

    # We compile by defining "eat" classmethods for all the FilterMembers (and some classes which aren't FilterMembers).
    # Generally, eat receives the *full* tokenized expression, and the index where "uneaten" tokens begin.
    # It "eats" tokens starting from that point and returns the FilterMember object created from them, and the index where it stopped eating.
    # Filter is the root object so it's a little different, it expects to eat everything to it doesn't need start or end indices.
    @classmethod
    def eat(cls, tokens: list[str], find: FindableType, ctx: FlamContext) -> Filter:
        if len(tokens) == 0:
            return cls(None, find)

        pipeline, _ = Pipeline.eat(tokens, 0, find, ctx, expect_eat_everything=True)
        return cls(pipeline, find)

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        return self._pipeline is None or self._pipeline.excrete(item, general)

    def regurgitate(self) -> typing.Iterable[str]:
        if self._pipeline is not None:
            # Parentheses around the whole filter are useless, and they make it so if you repeatedly compile(regurgitate(compile(regurgitate...))),
            # each iteration wraps the expression in an additional parentheses.
            yield from self._pipeline.regurgitate(parenthesize=False)

class Pipeline(FilterMember):
    # Yes the type annotations are a little ugly, but there's no way to alias them due to their recursive nature.
    def __init__(self, single: Predicate | Negative | Pipeline, joinables: list[Disjoined | Predicate | Negative | Pipeline]) -> None:
        self._single = single
        self._joinables = joinables
        
    @classmethod
    def eat(cls, tokens: list[str], at: int, find: FindableType, ctx: FlamContext, expect_eat_everything: bool = False) -> tuple[Pipeline, int]:
        single, until = Single.eat(tokens, at, find, ctx)
        joinables = []

        while until < len(tokens):
            try:
                swallow, until = Joinable.eat(tokens, until, find, ctx)
            except _EinGafrurError:
                # Doing it this way "breaks" the model (by giving Pipeline a unique eat signature),
                # but it lets us raise a meaningful error instead of some cryptic "some tokens weren't eaten".
                if expect_eat_everything:
                    raise
                    
                break

            joinables.append(swallow)

        return cls(single, joinables), until

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        accept = self._single.excrete(item, general)
        
        for joinable in self._joinables:
            # Conjunction is the default, so only disjunction must be specified.
            if isinstance(joinable, Negative | Predicate | Pipeline):
                accept = accept and joinable.excrete(item, general)
            elif isinstance(joinable, Disjoined):
                accept = accept or joinable.excrete(item, general)
            else:
                raise RuntimeError("this shouldn't happen")

        return accept

    def regurgitate(self, parenthesize: bool = True) -> typing.Iterable[str]:
        if parenthesize:
            # We use min because these are sets so next(iter(...)) returns different things every time.
            yield min(Positive.LPAREN)

        yield from self._single.regurgitate()
        yield from (tok for jable in self._joinables for tok in jable.regurgitate())

        if parenthesize:
            yield min(Positive.RPAREN)

# Some "FilterMembers" (as defined in the BNF) don't need to be instantiated. Eating a "Single" directly returns what its "child" would be.
class Single:
    @classmethod
    def eat(cls, tokens: list[str], at: int, find: FindableType, ctx: FlamContext) -> tuple[Predicate | Negative | Pipeline, int]:
        # The order is important for raising the most meaningful exception.
        try:
            return Negative.eat(tokens, at, find, ctx)
        except _EinGafrurError as e:
            # If the exception was that there isn't a 'not' symbol, we want to try parsing this as a Positive.
            # Otherwise, there's no point to even try, and the most meaningful exception we can raise is this one.
            if e.is_terminal:
                raise

        return Positive.eat(tokens, at, find, ctx)

class Positive:
    LPAREN = {'(', '[', '-lparen'}
    RPAREN = {')', ']', '-rparen'}
    _RPAREN_DESC = 'matching right parenthesis'

    @classmethod
    def eat(cls, tokens: list[str], at: int, find: FindableType, ctx: FlamContext) -> tuple[Predicate | Pipeline, int]:
        # Only raise parenthesis errors if we have reason to believe this was meant to be a parenthesis expression.
        if at < len(tokens) and tokens[at] in cls.LPAREN:
            pipeline, until = Pipeline.eat(tokens, at + 1, find, ctx)
            
            # Doesn't use eat_one_of because different error_indices.
            rparen = FilterMember.eat_str(tokens, until, cls._RPAREN_DESC, error_indices=at)

            if rparen not in cls.RPAREN:
                raise _EinGafrurError(f"Expected {cls._RPAREN_DESC}, but got: '{rparen}'.", tokens=tokens, error_indices=[at, until])

            return pipeline, until + 1

        return Predicate.eat(tokens, at, find, ctx)

class Negative(FilterMember):
    NEGATE = {'!', '-n', '-not'}
    _DESC = "'not' symbol"

    def __init__(self, positive: Predicate | Pipeline) -> None:
        self._positive = positive

    @classmethod
    def eat(cls, tokens: list[str], at: int, find: FindableType, ctx: FlamContext) -> tuple[Negative, int]:
        cls.eat_one_of(tokens, at, cls._DESC, cls.NEGATE, is_terminal=False)
        positive, until = Positive.eat(tokens, at + 1, find, ctx)
        return cls(positive), until

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        return not self._positive.excrete(item, general)

    def regurgitate(self) -> typing.Iterable[str]:
        yield min(self.NEGATE)
        yield from self._positive.regurgitate()

class Joinable(FilterMember):
    @classmethod
    def eat(cls, tokens: list[str], at: int, find: FindableType, ctx: FlamContext) -> tuple[Disjoined | Predicate | Negative | Pipeline, int]:
        # Ordered this way so we raise the most meaningful exception possible.
        try:
            return Disjoined.eat(tokens, at, find, ctx)
        except _EinGafrurError as e:
            if e.is_terminal:
                raise

        try:
            return Conjoined.eat(tokens, at, find, ctx)
        except _EinGafrurError as e:
            if e.is_terminal:
                raise

        return Single.eat(tokens, at, find, ctx)

class Conjoined:
    CONJOIN = {'&', '-a', '-and'}
    _DESC = "'and' symbol"

    @classmethod
    def eat(cls, tokens: list[str], at: int, find: FindableType, ctx: FlamContext) -> tuple[Predicate | Negative | Pipeline, int]:
        FilterMember.eat_one_of(tokens, at, cls._DESC, cls.CONJOIN, is_terminal=False)

        # There is no need to return a Coinjoined object because conjoining is the default behavior when boolean operators are omitted.
        return Single.eat(tokens, at + 1, find, ctx)

class Disjoined(FilterMember):
    DISJOIN = {'|', '-o', '-or'}
    _DESC = "'or' symbol"

    def __init__(self, single: Predicate | Negative | Pipeline) -> None:
        self._single = single

    @classmethod
    def eat(cls, tokens: list[str], at: int, find: FindableType, ctx: FlamContext) -> tuple[Disjoined, int]:
        cls.eat_one_of(tokens, at, cls._DESC, cls.DISJOIN, is_terminal=False)
        single, until = Single.eat(tokens, at + 1, find, ctx)
        return cls(single), until

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        return self._single.excrete(item, general)

    def regurgitate(self) -> typing.Iterable[str]:
        yield min(self.DISJOIN)
        yield from self._single.regurgitate()

class Predicate(FilterMember):
    PREFIX = '-'
    name: str
    
    def __init_subclass__(cls, name: str, **kwargs: typing.Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.name = name

    @classmethod
    def eat(cls, tokens: list[str], at: int, find: FindableType, ctx: FlamContext) -> tuple[Predicate, int]:
        prefixed_name = cls.eat_str(tokens, at, 'a predicate name')
        name = prefixed_name.removeprefix(Predicate.PREFIX)

        if name != prefixed_name:
            # Instead of going predicate by predicate and checking for _EinGafrurError,
            # it's more optimal to pick the only possibly right predicate from a dictionary,
            # and eat the name token right here and let the predicate eat its arguments alone.
            for registry in ctx.registries_to_try():
                if registry.has_predicate(name):
                    # Throughout this file we annotate return types with the class name and not typing.Self.
                    # I don't like this, but it's the best way to get mypy to shut up about this line.
                    return registry.get_predicate(name).eat(tokens, at + 1, find, ctx)
                
                # Special treatment for AttributePredicate because it's not wise to make a predicate for each attribute.
                # TODO: Check if attribute owner matches what we're filtering?
                if registry.has_attribute(name):
                    return AttributePredicate.eat_shit(tokens, at + 1, registry.get_attribute(name))

        if prefixed_name in Positive.RPAREN:
            raise _EinGafrurError('Right parenthesis has no matching left parenthesis.', tokens=tokens, error_indices=at)
            
        all_pred_names = (
            Predicate.PREFIX + k
            for registry in ctx.registries_to_try()
                for keyvals in (registry.predicate_keyvals(), registry.attribute_keyvals())
                    for k, _ in keyvals
        )

        close_matches = difflib.get_close_matches(prefixed_name, all_pred_names)
        suggestions = f' (did you mean: {", ".join(close_matches)}?)' if len(close_matches) > 0 else '.'
        raise _EinGafrurError(f"Expected valid predicate name, but got: '{prefixed_name}'{suggestions}", tokens=tokens, error_indices=at)

    def regurgitate(self) -> typing.Iterable[str]:
        yield self.PREFIX + self.name

# This should be the only concrete predicate that is in this file, because it's special.
class AttributePredicate(Predicate, name='attribute'):
    def __init__(self, attribute: Attribute, cmp: ComparisonOp, value: typing.Any) -> None: # TODO: "Any" should be the same T that the attribute is.
        self._attribute = attribute
        self._cmp = cmp
        self._value = value

        # Shadow the name with that of the attribute. Python lets you shadow class variables with instance variables like this.
        self.name = attribute.name

    # Part of being a special predicate means its "eat" has a different signature so we have to give it a different name.
    @classmethod
    def eat_shit(cls, tokens: list[str], at: int, attribute: Attribute) -> tuple[Predicate, int]:
        cmp, value_str = cls.eat_cmp_value(tokens, at)
        value = None # TODO: use attribute to parse value_str into the attribute's type. Possibly also check if attribute supports the comparator?
        return cls(attribute, cmp, value), at + 1

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        # TODO: If array type, extract first element only.
        actual = self._attribute.extract(None) # TODO: not None of course.
        return self._cmp.compare(actual, self._value)

    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield self._cmp.sign + str(self._value)

# Doesn't guarantee that token is valid, only indicates that it looks like it should be.
def is_filter_token(token: str) -> bool:
    return (token.startswith(Predicate.PREFIX)
            or token in Negative.NEGATE
            or token in Disjoined.DISJOIN
            or token in Conjoined.CONJOIN
            or token in Positive.LPAREN
            or token in Positive.RPAREN)

#endregion filters

#region attributes

class ComparisonOp(enum.Enum):
    EQ = ('=', lambda v1, v2: v1 == v2)
    LE = ('-', lambda v1, v2: v1 <= v2)
    GE = ('+', lambda v1, v2: v1 >= v2)
    LT = ('--', lambda v1, v2: v1 < v2)
    GT = ('++', lambda v1, v2: v1 > v2)

    def __init__(self, sign: str, compare: typing.Callable[[typing.Any, typing.Any], bool]) -> None:
        self.sign = sign
        self.compare = compare

class Attribute(abc.ABC):
    def __init__(self, owner, name, aliases, is_columnable, is_sortable): # TODO: many more fields. Fields related to sorting, distribution,
        self.owner = owner
        self.name = name
        self.aliases = aliases
        
        # TODO: possibly instead of this make it so it's columnable if it has a "to str" attribute, "sortable" if it has a key extractor attribute
        self.is_columnable = is_columnable
        self.is_sortable = is_sortable

    @property
    def is_array(self) -> bool:
        raise NotImplementedError()

    def make_predicate(self, cmp: ComparisonOp, value: str) -> Predicate:
        raise NotImplementedError()

    def extract(self, obj) -> typing.Any:
        if not isinstance(obj, self.owner.corresponding_type):
            raise Exception(f'Invalid owner: {name} expects {self.owner}, but got {type(obj)}')

        self.ensure_owner_match(obj)
        return self._extract_internal(obj)

    @abc.abstractmethod
    def _extract_internal(self, obj) -> typing.Any:
        pass

#endregion

#region context

# Data structure for using remote/composite lists generically.
LT = typing.TypeVar('LT', RemoteList, CompositeList)

class ConfigurationLists(typing.Generic[LT]):
    def __init__(self, lists: list[LT], type_name: str) -> None:
        self._lists: list[LT] = lists
        self._type_name = type_name

    def __iter__(self) -> typing.Iterator[LT]:
        return iter(self._lists)

    def get_by_uid(self, uid: str) -> LT:
        try:
            return next(l for l in self._lists if l.uid == uid)
        except StopIteration as e:
            raise exceptions.InputError(f"Invalid {self._type_name} UID: '{uid}'") from e

    def get_by_name(self, name: str) -> LT:
        try:
            return next(l for l in self._lists if l.name == name)
        except StopIteration as e:
            raise exceptions.InputError(f"Invalid {self._type_name} name: '{name}'") from e

class ListHandle:
    def __init__(self, list_file): # TODO: specify how to group each crew type?
        self._list_file = list_file

    def __iter__(self):
        return self.find(FindableType.MOVIES)

    def apply_filter(self, filter: Filter):
        pass

    def find(self, what: FindableType, filter: None | Filter = None) -> typing.Iterator[typing.Any]: # TODO: not Any!
        assert filter is None or filter.findable_type == what

    def export(self, filter: Filter) -> ListFile:
        assert filter.findable_type == FindableType.MOVIES

# This class is the user's entry point to basically everything that is "built in" to this API: accessing lists, filtering, configuring.
class FlamContext:
    DEFAULT_FLAM_DIR = os.environ.get('FLAM_DIR', os.path.join(os.path.expanduser('~'), '.film_flam'))
    _LISTFILES_DIR = 'list_files'
    _CONFIGURATION_FILE = 'config.json'
    _METADATA_FILE = 'metadata.json'

    def __init__(self, flam_dir: None | str = DEFAULT_FLAM_DIR, import_extensions: bool = False) -> None:
        # Support None for users who just want to work with volatile memory and not load or save anything, we call it volatile mode.
        # Don't tell this to anyone but in "volatile" mode we actually just persist everything to a tempdir. It's so, so much easier.
        if flam_dir is None:
            tempdir = tempfile.TemporaryDirectory(prefix='.film_flam', ignore_cleanup_errors=not _is_debug()) # pylint: disable=consider-using-with
            atexit.register(tempdir.cleanup) # TODO: cleanup at object's __del__ it if happens before atexit?
            self._flam_dir = tempdir.name
        else:
            # TODO: Acquire OS lock on the flam_dir so that you can't have multiple contexts operating on it at once?
            self._flam_dir = os.path.normpath(flam_dir)

        self._make_flam_dir()
        self._cfg = Configuration.load_or_create(self._get_cfg_path())
        self._metadata = _FlamMetadata.load_or_create(self._get_metadata_path()) # TODO: Initialize/verify metadata? Or just fix up the file as we use it?

        self._list_files_cache: dict[str, ListFile] = {}

        # Since Configuration needs to be serializable, we can't store the lists in there in some funky data structure,
        # and we can't add fields to the object that aren't meant for serialization.
        # The solution I've got is to wrap those lists in this Context.
        self._remote_lists = ConfigurationLists(self.cfg._remote_lists, 'list')
        self._composite_lists = ConfigurationLists(self.cfg._composite_lists, 'composite list')

        self._extensions = Registry()

        # import_extensions does 2 things: import all configured extensions, and subscribe to any globally registered extensions.
        # It's good to make this an option with default false for security, and I prefer to keep the two options as one for simplicity.
        self._use_global_extensions = import_extensions

        if import_extensions:
            for extension in self.cfg.extensions:
                # Try both ways.
                # TODO: Raise InputError?
                try:
                    importlib.import_module(extension)
                except ModuleNotFoundError:
                    utils.import_file(extension)

    @property
    def flam_dir(self) -> str:
        return self._flam_dir

    @property
    def cfg(self) -> Configuration:
        return self._cfg

    @property
    def extensions(self) -> Registry:
        return self._extensions

    @property
    def remote_lists(self) -> ConfigurationLists[RemoteList]:
        return self._remote_lists

    @property
    def composite_lists(self) -> ConfigurationLists[CompositeList]:
        return self._composite_lists

    def _make_flam_dir(self) -> None:
        # Make sure to keep it topologically sorted.
        directories = [
            self._flam_dir,
            os.path.join(self._flam_dir, self._LISTFILES_DIR),
        ]

        for d in directories:
            try:
                os.mkdir(d)
            except FileExistsError:
                pass

    # List files.
    def get_list_handle(self, listdefs: str | typing.Iterable[str], filter: None | Filter = None) -> ListHandle:
        canon_listdefs = list(self.canonicalize_listdefs_with_all_expansion(listdefs if not isinstance(listdefs, str) else (listdefs,)))
        # TODO: expand "default" and only then make into list... is it really a "list_handle" feature? We have no clear entry point find vs anything else.
        if len(canon_listdefs) == 1:
            list_file = self._get_list_file(canon_listdefs[0])
        else:
            list_file = self._generate_composite_list_file(canon_listdefs, filter)
            list_file.fetcher_type = CompositeList.FETCHER_TYPE # TODO: different fetcher_type for annonymous lists?
            list_file.address = "ANNONYMOUS"

        return ListHandle(list_file)

    def _get_list_file(self, abstract_listdef: CanonListdef) -> ListFile:
        # First we check if it's a composite list that needs regeneration. In that case even if it's cached it needs to be redone.
        if abstract_listdef.fetcher_type == CompositeList.FETCHER_TYPE and self._is_composite_list_file_outdated(abstract_listdef.address):
            # TODO: update metadata?
            composite_list = self._composite_lists.get_by_uid(abstract_listdef.address)
            filter = self.compile_filter(composite_list.filter_tokens, FindableType.MOVIES)
            dependencies = [CanonListdef(RemoteList.FETCHER_TYPE, rl_uid) for rl_uid in composite_list.remote_list_uids]
            list_file = self._generate_composite_list_file(dependencies, filter)
            list_file.fetcher_type = CompositeList.FETCHER_TYPE
            list_file.address = abstract_listdef.address
            self._list_files_cache[abstract_listdef.address] = list_file
            return list_file

        # Now we try to get it from memory.
        if abstract_listdef.address in self._list_files_cache:
            return self._list_files_cache[abstract_listdef.address]
            
        # Memory didn't work out, try to load it from disk.
        try:
            list_file = ListFile.load(self._get_list_file_path(abstract_listdef))
        except FileNotFoundError:
            raise exceptions.InputError(f"No fetched file for LISTDEF '{self.canon_listdef_pretty(abstract_listdef)}'.")
        except exceptions.FileValidationError as e:
            raise exceptions.FileValidationError(f"{e} You may need to fetch '{self.canon_listdef_pretty(abstract_listdef)}' again from scratch.") from e

        assert not isinstance(list_file.address, UnsetType)
        self._list_files_cache[list_file.address] = list_file
        return list_file
    
    def _is_composite_list_file_outdated(self, uid: str) -> bool:
        if uid not in self._metadata.composite_lists_by_uid:
            return True

        cl_config = self._composite_lists.get_by_uid(uid)
        cl_meta = self._metadata.composite_lists_by_uid[uid]

        for rl_uid in cl_config.remote_list_uids:
            if rl_uid not in cl_meta.dependency_mtime:
                return True

            rl_path = self._get_list_file_path(CanonListdef(RemoteList.FETCHER_TYPE, rl_uid))

            try:
                if rl_uid not in cl_meta.dependency_mtime or os.path.getmtime(rl_path) > cl_meta.dependency_mtime[rl_uid]:
                    return True
            except FileNotFoundError:
                cl_listdef = CanonListdef(CompositeList.FETCHER_TYPE, uid)
                rl_listdef = CanonListdef(RemoteList.FETCHER_TYPE, rl_uid)
                raise exceptions.InputError(f"List '{self.canon_listdef_pretty(cl_listdef)}' depends on {rl_listdef} which hasn't been fetched.")

        return False

    def _generate_composite_list_file(self, abstract_listdefs: list[CanonListdef], filter: None | Filter) -> ListFile:
        merged_list_file = ListFile.create()
        list_files = [self._get_list_file(cldef) for cldef in abstract_listdefs]
        # TODO: sciency shit to merge list_files into merged_list_file

        if filter is not None:
            merged_list_file = ListHandle(merged_list_file).export(filter)
            
        return merged_list_file

    def _write_list_file(self, list_file: ListFile) -> None:
        list_file.write(self._get_list_file_path(list_file.abstract_listdef))

        # Flush the metadata when saving composite lists so we don't accidentally regenerate them.
        if list_file.fetcher_type == CompositeList.FETCHER_TYPE:
            self._write_metadata()

    # After much deliberation, I decided that files for named lists should be named according to the list type and UID,
    # and unnamed lists' files should be named according to the fetcher type and address.
    # This is mostly as opposed to storing all lists according to the concrete fetcher_type and address.
    # The reason: this lets us change lists to a different fetcher type with a compatible ID type.
    def _get_list_file_path(self, abstract_listdef: CanonListdef) -> str:
        filename = utils.slugify(f'{abstract_listdef.fetcher_type}_{abstract_listdef.address}.json')
        return os.path.join(self._flam_dir, self._LISTFILES_DIR, filename)

    # Configuration.
    def lists_of_type(self, fetcher_type: str) -> ConfigurationLists[RemoteList] | ConfigurationLists[CompositeList]:
        match fetcher_type:
            case RemoteList.FETCHER_TYPE:
                return self._remote_lists
            case CompositeList.FETCHER_TYPE:
                return self._composite_lists
            case _:
                raise ValueError(f"Invalid type '{fetcher_type}': not any kind of list.")

    def get_list_by_abstract_listdef(self, abstract_listdef: CanonListdef) -> RemoteList | CompositeList:
        return self.lists_of_type(abstract_listdef.fetcher_type).get_by_uid(abstract_listdef.address)

    def add_remote_list(self, remote_list: RemoteList) -> None:
        remote_list.uid = str(uuid.uuid4())
        self.cfg._remote_lists.append(remote_list) # pylint: disable=protected-access

        # See if the list was already fetched before it was named, and "claim" the file.
        concrete_filename = self._get_list_file_path(remote_list.concrete_listdef)
        abstract_filename = self._get_list_file_path(remote_list.abstract_listdef)
        
        try:
            os.rename(concrete_filename, abstract_filename)
        except FileNotFoundError:
            pass

    def delete_remote_list(self, uid: str) -> None:
        remote_list = self._remote_lists.get_by_uid(uid)

        # We don't mess with removing the list from its dependent composite lists. Let the user do that.
        dependents = [cl.name for cl in self._composite_lists if uid in cl.remote_list_uids]

        if len(dependents) > 0:
            raise exceptions.InputError(f"Failed to delete list '{remote_list.name}' because it is depended on by composite lists: {', '.join(dependents)}")

        # Deleting a list doesn't delete it from local storage, only gets it renamed to be anonymous.
        concrete_filename = self._get_list_file_path(remote_list.concrete_listdef)
        abstract_filename = self._get_list_file_path(remote_list.abstract_listdef)

        try:
            os.rename(abstract_filename, concrete_filename)
        except FileNotFoundError:
            pass

        self.cfg._remote_lists.remove(remote_list) # pylint: disable=protected-access

    def add_composite_list(self, composite_list: CompositeList) -> None:
        composite_list.uid = str(uuid.uuid4())
        self.cfg._composite_lists.append(composite_list) # pylint: disable=protected-access

    def delete_composite_list(self, uid: str) -> None:
        composite_list = self._composite_lists.get_by_uid(uid)
        # TODO: delete files
        self.cfg._composite_lists.remove(composite_list) # pylint: disable=protected-access

    def write_cfg(self) -> None:
        self.cfg.write(self._get_cfg_path())
        
    def _get_cfg_path(self) -> str:
        return os.path.join(self._flam_dir, self._CONFIGURATION_FILE)

    # Metadata
    def _write_metadata(self) -> str:
        self._metadata.write(self._get_metadata_path())

    def _get_metadata_path(self) -> str:
        return os.path.join(self._flam_dir, self._METADATA_FILE)

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

        # For remote/composite lists we need to convert the name to a uid.
        if eq_idx != -1 and (before_eq == RemoteList.FETCHER_TYPE or before_eq == CompositeList.FETCHER_TYPE):
            return self.lists_of_type(before_eq).get_by_name(after_eq).abstract_listdef
        
        # The generic case where it's whatever=whatever.
        if eq_idx != -1:
            return CanonListdef(before_eq, after_eq)
        
        # If no '=' sign then we'll treat it as a list or composite list, and try to determine which.
        if (list_obj := self._get_implicit_list(before_eq)) is not None:
            return list_obj.abstract_listdef

        raise exceptions.InputError(f"Invalid LISTDEF: '{listdef}'.")

    # This is the most that we can canonicalize/expand listdefs generically. Other transformations are different for fetching vs finding vs whatever.
    def canonicalize_listdefs_with_all_expansion(self, listdefs: typing.Iterable[str]) -> typing.Iterator[CanonListdef]:
        for ldef in listdefs:
            cldef = self.canonicalize_listdef(ldef)

            if cldef.fetcher_type == LISTDEF_ALL:
                yield from (rl.abstract_listdef for rl in self._remote_lists)
            else:
                yield cldef

    # Internally when canonicalizing listdefs it's convenient to convert list names to UIDs,
    # but it means that whenever we print the listdef we need to convert it back to have human-readable list names.
    def canon_listdef_pretty(self, canon_listdef: CanonListdef) -> str:
        return str(canon_listdef._replace(address=self.get_list_by_abstract_listdef(canon_listdef).name) if canon_listdef.is_abstract else canon_listdef)

    def _get_implicit_list(self, name: str) -> None | RemoteList | CompositeList:
        try:
            return self._remote_lists.get_by_name(name)
        except exceptions.InputError:
            pass

        try:
            return self._composite_lists.get_by_name(name)
        except exceptions.InputError:
            pass

        return None

    # Registration.
    def registries_to_try(self) -> typing.Iterable[Registry]:
        yield _builtins

        if self._use_global_extensions:
            yield _global_extensions

        yield self._extensions

    # Fetching.
    def fetch(self, listdefs: typing.Iterable[str], refetch_pattern: None | str = None, quiet: bool = True) -> None:
        fetchers = self._parse_listdefs_into_fetchers(listdefs)

        try:
            refetch_re = re.compile(refetch_pattern, flags=re.IGNORECASE) if refetch_pattern is not None else None
        except re.error as e:
            raise exceptions.InputError(f"Invalid PATTERN: '{refetch_pattern}': {e}")

        for fetcher in fetchers:
            try:
                list_file = self._get_list_file(fetcher.abstract_listdef)
            # If the list were composite there'd be another case where this exception is raised, but it's not possible to reach here with a composite list.
            except exceptions.InputError:
                list_file = ListFile.create()
                
            if not isinstance(list_file.uid_type, UnsetType) and list_file.uid_type != fetcher.uid_type:
                raise exceptions.InputError(f"Cannot fetch '{self.canon_listdef_pretty(fetcher.abstract_listdef)}' because it's already fetched with a different ID type "
                    f"(old: '{list_file.uid_type}', new: '{fetcher.uid_type}'). "
                    "This can happen if you changed a list's LISTDEF to a nonmatching type. You can resolve it by fetching the list from scratch, or reverting the list to its old type.")

            # We need both the old and new versions to compare at the end. But it's important that the new one is the deepcopy,
            # so that anyone currently holding on to a list handle won't have the underlying list file changed.
            new_list_file = copy.deepcopy(list_file)
            interrupt_error = None

            if refetch_re is not None:
                new_list_file.movies_by_uid = {
                    uid: movie_lf
                    for uid, movie_lf in new_list_file.movies_by_uid.items()
                    if not isinstance(movie_lf.title, UnsetType) and not refetch_re.search(movie_lf.title)
                }

                _remove_unused_people(new_list_file)

            with open(os.devnull, 'w') as devnull, contextlib.redirect_stdout(devnull) if quiet else contextlib.nullcontext():
                print(f"Fetching {self.canon_listdef_pretty(fetcher.abstract_listdef)}...")

                try:
                    fetcher.fetch_into_file(new_list_file)
                except exceptions.FetchInterrupt as e:
                    interrupt_error = e

            # Fetcher may have removed some movies from the list. Over here we remove people who are orphaned because of that.
            _remove_unused_people(new_list_file)

            new_list_file.uid_type = fetcher.uid_type
            new_list_file.fetcher_type = fetcher.abstract_listdef.fetcher_type
            new_list_file.address = fetcher.abstract_listdef.address

            # Must canonicalize before comparing for equality.
            new_list_file.canonicalize()

            # We'll only write the new contents if they're different than before, and we'll return whether there was a diff or not.
            # This allows us to check the file mtime to know if it's dirty and dependent files need to be regenerated.
            if list_file != new_list_file:
                self._write_list_file(new_list_file)

            # Because it's a dictionary we easily overwrite an existing outdated cached file.
            self._list_files_cache[new_list_file.address] = new_list_file

            if interrupt_error is not None:
                raise exceptions.FetchInterrupt(f"Fetching of {self.canon_listdef_pretty(fetcher.abstract_listdef)} got interrupted due to error: {interrupt_error}. "
                    "You may retry to pick up where it left off.")

    def _parse_listdefs_into_fetchers(self, listdefs: typing.Iterable[str]) -> list[ListFetcher]:
        cldefs = self.canonicalize_listdefs_with_all_expansion(listdefs)
        expanded = set(self._expand_listdefs_for_fetch(cldefs))

        # Returns a list not a generator so that if one of the listdefs doesn't parse good we will raise an error now and not before fetching a few.
        return [self._get_fetcher(cldef) for cldef in expanded]

    def _expand_listdefs_for_fetch(self, canon_listdefs: typing.Iterable[CanonListdef]) -> typing.Iterator[CanonListdef]:
        for cldef in canon_listdefs:
            if cldef.fetcher_type == LISTDEF_DEFAULTS:
                yield from (rl.abstract_listdef for rl in self._remote_lists if rl.is_default_fetch)

                # Default composite lists... yeah.
                yield from (
                    CanonListdef(RemoteList.FETCHER_TYPE, rl_uid)
                    for cl in self._composite_lists if cl.is_default_fetch
                        for rl_uid in cl.remote_list_uids
                )
            elif cldef.fetcher_type == CompositeList.FETCHER_TYPE:
                composite_list = self._composite_lists.get_by_uid(cldef.address)
                yield from (CanonListdef(RemoteList.FETCHER_TYPE, rl_uid) for rl_uid in composite_list.remote_list_uids)
            else: # RemoteList.FETCHER_TYPE or a "concrete" type.
                yield cldef

    def _get_fetcher(self, canon_listdef: CanonListdef) -> ListFetcher:        
        if canon_listdef.is_abstract:
            # Assume it's a RemoteList.
            abstract_listdef = canon_listdef
            concrete_listdef = self._remote_lists.get_by_uid(abstract_listdef.address).concrete_listdef
        else:
            abstract_listdef = concrete_listdef = canon_listdef

        fetcher_cls = None

        for registry in self.registries_to_try():
            try:
                fetcher_cls = registry.get_fetcher(concrete_listdef.fetcher_type)
            except KeyError:
                pass

        if fetcher_cls is None:
            raise exceptions.InputError(f"Invalid LISTDEF '{concrete_listdef}': type is unknown.")

        return fetcher_cls(concrete_listdef, abstract_listdef)

    # Filtering.
    def compile_filter(self, tokens: list[str], find: FindableType) -> Filter:
        return Filter.eat(tokens, find, self)

#endregion context

#region general

# Users input LISTDEF strings and we turn them into this more convenient representation.
class CanonListdef(typing.NamedTuple):
    fetcher_type: str
    address: str

    @property
    def is_special(self) -> bool:
        return self.fetcher_type in _SPECIAL_FETCHER_TYPES

    # RemoteList/CompositeList listdefs are abstract because they can't be fetched directly, only through the underlying "concrete" type.
    @property
    def is_abstract(self) -> bool:
        return self.fetcher_type == RemoteList.FETCHER_TYPE or self.fetcher_type == CompositeList.FETCHER_TYPE

    # "Concrete" listdefs have a type that directly corresponds to a ListFetcher.
    @property
    def is_concrete(self) -> bool:
        return not self.is_special

    def __str__(self) -> str:
        return f'{self.fetcher_type}={self.address}'

class FindableType(enum.StrEnum):
    MOVIES = 'movies'
    PEOPLE = 'people'
    ROLES = 'roles'

    @property
    def corresponding_type(self) -> type:
        raise NotImplementedError()

    def is_compatible(self, find: typing.Self) -> bool:
        # Roles are compatible with everything because a role is associated with a person and a movie.
        return find == self.ROLES or self == find

class CrewType(enum.StrEnum):
    CAST = 'cast'
    STUNTCAST = 'stuntcast'
    DIRECTOR = 'director'
    WRITER = 'writer'
    PRODUCER = 'producer'
    COMPOSER = 'composer'
    CINEMATOGRAPHER = 'cinematographer'
    EDITOR = 'editor'

def _is_debug() -> bool:
    return 'FLAM_DEBUG' in os.environ

LISTDEF_ALL = '*'
LISTDEF_DEFAULTS = 'defaults'
_SPECIAL_FETCHER_TYPES = {LISTDEF_DEFAULTS, LISTDEF_ALL, RemoteList.FETCHER_TYPE, CompositeList.FETCHER_TYPE}

#endregion general

#region registration

# TODO: concerns:
# * Might want to lock any further extensions once a context is in use
# * Might want to prevent registering something that is already registered
class Registry:
    def __init__(self) -> None:
        self._fetchers: dict[str, type[ListFetcher]] = {}
        self._predicates: dict[str, type[Predicate]] = {}
        self._attributes: dict[str, Attribute] = {}

    def register(self, obj: typing.Any) -> None:
        if isinstance(obj, type) and issubclass(obj, ListFetcher):
            self._fetchers[obj.fetcher_type] = obj
        elif isinstance(obj, type) and issubclass(obj, Predicate):
            self._predicates[obj.name] = obj
        elif isinstance(obj, Attribute):
            self._attributes[obj.name] = obj
        else:
            raise exceptions.InputError(f"Invalid object for registration: {obj}.")

    def get_fetcher(self, fetcher_type: str) -> type[ListFetcher]:
        return self._fetchers[fetcher_type]

    def get_predicate(self, name: str) -> type[Predicate]:
        return self._predicates[name]

    def get_attribute(self, name: str) -> Attribute:
        return self._attributes[name]

    def has_fetcher(self, fetcher_type: str) -> bool:
        return fetcher_type in self._fetchers

    def has_predicate(self, name: str) -> bool:
        return name in self._predicates

    def has_attribute(self, name: str) -> bool:
        return name in self._attributes

    def fetcher_keyvals(self) -> typing.ItemsView[str, type[ListFetcher]]:
        return self._fetchers.items()

    def predicate_keyvals(self) -> typing.ItemsView[str, type[Predicate]]:
        return self._predicates.items()

    def attribute_keyvals(self) -> typing.ItemsView[str, Attribute]:
        return self._attributes.items()

_builtins = Registry()
_global_extensions = Registry()

def _register_builtin(obj: typing.Any) -> typing.Any:
    _builtins.register(obj)
    return obj

def register(obj: typing.Any) -> typing.Any:
    _global_extensions.register(obj)
    return obj

# Import builtin extensions only here to avoid cyclic dependency issues.
import filmflam._imdb # pylint: disable=unused-import, cyclic-import
import filmflam._predicates # pylint: disable=unused-import, cyclic-import
import filmflam._attributes # pylint: disable=unused-import, cyclic-import

#endregion registration
