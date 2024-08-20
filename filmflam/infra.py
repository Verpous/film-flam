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
import shutil
import re
import copy
import contextlib
import difflib
import enum

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

        for movie in self.movies_by_uid.values():
            if len(CREW_TYPES) != len(movie.crew) or not CREW_TYPES.issuperset(movie.crew.keys()):
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

class CompoundList(_FlamSerializable):
    FETCHER_TYPE: typing.ClassVar[str] = 'compound'

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
    _compound_lists:        list[CompoundList]
    extensions:             list[str]

    # TODO: Forbid special characters in list names that might be confused for a filter token.
    def sanity_checks(self) -> None:
        super().sanity_checks()

        for rl in self._remote_lists:
            if sum(1 for rl2 in self._remote_lists if rl.name == rl2.name) > 1:
                raise self._validation_error(f"Found multiple lists named '{rl.name}'.")

            if rl.concrete_listdef.is_special:
                raise self._validation_error(f"LISTDEF '{rl.concrete_listdef}' type must not be one of: {', '.join(SPECIAL_FETCHER_TYPES)}.")

        for cl in self._compound_lists:
            if sum(1 for cl2 in self._compound_lists if cl.name == cl2.name) > 1:
                raise self._validation_error(f"Found multiple compound lists named '{cl.name}'.")

            if len(cl.remote_list_uids) == 0:
                raise self._validation_error(f"Compound list '{cl.name}' is made up of 0 lists.")
                
            for uid in cl.remote_list_uids:
                try:
                    # Unfortunately the get_by_uid method is not accessible from here, see comment in FlamContext.
                    next(rl for rl in self._remote_lists if rl.uid == uid)
                except StopIteration as e:
                    raise self._validation_error(f"Compound list '{cl.name}' references unknown remote list: '{uid}'.") from e

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

    # TODO: Not a big fan of "from scratch". Maybe callers should just clean up the file before calling fetch.
    def fetch(self, ctx: FlamContext, refetch_pattern: None | str = None, from_scratch: bool = False, quiet: bool = True) -> tuple[ListFile, bool]:
        try:
            refetch_re = re.compile(refetch_pattern, flags=re.IGNORECASE) if refetch_pattern is not None else None
        except re.error as e:
            raise exceptions.InputError(f"Invalid PATTERN: '{refetch_pattern}': {e}")

        list_file = ListFile.create() if from_scratch else ctx.load_list_file(self.abstract_listdef, must_exist=False)
        list_file_before = copy.deepcopy(list_file)
        interrupt_error = None

        if not isinstance(list_file_before.uid_type, UnsetType) and list_file_before.uid_type != self.uid_type:
            raise exceptions.InputError(f"Cannot fetch '{ctx.canon_listdef_pretty(self.abstract_listdef)}' because it's already fetched with a different ID type "
                f"(old: '{list_file_before.uid_type}', new: '{self.uid_type}'). "
                "This can happen if you changed a list's LISTDEF to a nonmatching type. You can resolve it by fetching the list from scratch, or reverting the list to its old type.")

        if refetch_re is not None:
            list_file.movies_by_uid = {
                uid: movie_lf
                for uid, movie_lf in list_file.movies_by_uid.items()
                if not isinstance(movie_lf.title, UnsetType) and not refetch_re.search(movie_lf.title)
            }
            _remove_unused_people(list_file)

        with open(os.devnull, 'w') as devnull, contextlib.redirect_stdout(devnull) if quiet else contextlib.nullcontext():
            try:
                self.fetch_into_file(list_file)
            except exceptions.FetchInterrupt as e:
                interrupt_error = e

        # Fetcher may have removed some movies from the list. Over here we remove people who are orphaned because of that.
        _remove_unused_people(list_file)

        list_file.uid_type = self.uid_type
        list_file.fetcher_type = self.abstract_listdef.fetcher_type
        list_file.address = self.abstract_listdef.address

        # Must canonicalize before comparing for equality.
        list_file.canonicalize()

        # We'll only write the new contents if they're different than before, and we'll return whether there was a diff or not.
        # This allows us to check the file mtime to know if it's dirty and dependent files need to be regenerated.
        is_changed = list_file_before != list_file

        if is_changed:
            ctx.write_list_file(list_file)

        if interrupt_error is not None:
            raise exceptions.FetchInterrupt(f"Fetching of {ctx.canon_listdef_pretty(self.abstract_listdef)} got interrupted due to error: {interrupt_error}. "
                "You may retry to pick up where it left off.")

        return list_file, is_changed

def _get_fetcher(canon_listdef: CanonListdef, ctx: FlamContext) -> ListFetcher:
    # Avoid cyclic dependency by importing fetchers only here. Incidentally this is also what we do for custom fetchers, but for different reasons.
    # The import may seem unused but we obtain imported classes via subclasses_recursive.
    import filmflam._imdb # pylint: disable=unused-import, cyclic-import
    
    if canon_listdef.is_abstract:
        # Assume it's a RemoteList.
        abstract_listdef = canon_listdef
        concrete_listdef = ctx.remote_lists.get_by_uid(abstract_listdef.address).concrete_listdef
    else:
        abstract_listdef = concrete_listdef = canon_listdef

    for _ in range(2):
        # Lookup a fetcher with a matching type.
        for fetcher_cls in utils.subclasses_recursive(ListFetcher):
            fetcher_cls_safe = typing.cast(type[ListFetcher], fetcher_cls)

            if concrete_listdef.fetcher_type == fetcher_cls_safe.fetcher_type:
                return fetcher_cls_safe(concrete_listdef, abstract_listdef)

        # Failed to find it in the first iteration. It may still be a non-builtin type though.
        # Try importing a custom module named with a convention that means it should have the fetcher we seek, then seek again.
        # This way we don't import any random file named with this convention without the user explicitly asking for it, which would be a security risk.
        # TODO: unified extensions method based on decorators to register fetchers, attributes, etc.?
        # No more voodo detecting subclasses, just auto import scripts which register extensions. Screw security, maybe it's not so bad.
        try:
            utils.import_from_path(f'flam_fetcher_{concrete_listdef.fetcher_type}')
        except ImportError:
            break

    raise exceptions.InputError(f"Invalid LISTDEF '{concrete_listdef}': type is unknown.")

def parse_listdefs(listdefs: typing.Iterable[str], ctx: FlamContext) -> list[ListFetcher]:
    cldefs = ctx.canonicalize_listdefs_with_all_expansion(listdefs)
    expanded = set(_expand_listdefs(cldefs, ctx))

    # Returns a list not a generator so that if one of the listdefs doesn't parse good we will raise an error now and not before fetching a few.
    return [_get_fetcher(cldef, ctx) for cldef in expanded]

def _expand_listdefs(canon_listdefs: typing.Iterable[CanonListdef], ctx: FlamContext) -> typing.Iterator[CanonListdef]:
    for cldef in canon_listdefs:
        if cldef.fetcher_type == LISTDEF_DEFAULTS:
            yield from (rl.abstract_listdef for rl in ctx.remote_lists if rl.is_default_fetch)

            # Default compound lists... yeah.
            yield from (
                CanonListdef(RemoteList.FETCHER_TYPE, rl_uid)
                for cl in ctx.compound_lists if cl.is_default_fetch
                    for rl_uid in cl.remote_list_uids
            )
        elif cldef.fetcher_type == CompoundList.FETCHER_TYPE:
            compound_list = ctx.compound_lists.get_by_uid(cldef.address)
            yield from (CanonListdef(RemoteList.FETCHER_TYPE, rl_uid) for rl_uid in compound_list.remote_list_uids)
        else: # RemoteList.FETCHER_TYPE or a "concrete" type.
            yield cldef

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
# PIPELINE  := VALUE JOINABLE*
# VALUE     := NEGATIVE | POSITIVE
# POSITIVE  := PREDICATE | ( PIPELINE )
# NEGATIVE  := NOT POSITIVE
# JOINABLE  := CONJOINED | DISJOINED | VALUE
# CONJOINED := AND VALUE
# DISJOINED := OR VALUE
# PREDICATE := -<name> <arg1> <arg2>...

# OR        := -o | -or  | `|`
# AND       := -a | -and | &
# NOT       := -n | -not | !
# (         := (  | [    | -lparen
# )         := )  | ]    | -rparen

# This one's for you, mayer.
EinGafrurError = exceptions.FilterSyntaxError

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

class Filter(FilterMember):
    def __init__(self, pipeline: None | Pipeline) -> None:
        self.pipeline = pipeline

    # We compile by defining "eat" classmethods for all the FilterMembers (and some classes which aren't FilterMembers).
    # Generally, eat receives the *full* tokenized expression, and the index where "uneaten" tokens begin.
    # It "eats" tokens starting from that point and returns the FilterMember object created from them, and the index where it stopped eating.
    # Filter is the root object so it's a little different, it expects to eat everything to it doesn't need start or end indices.
    @classmethod
    def eat(cls, tokens: list[str]) -> Filter:
        if len(tokens) == 0:
            return cls(None)

        pipeline, _ = Pipeline.eat(tokens, 0, expect_eat_everything=True)
        return cls(pipeline)

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        return True if self.pipeline is None else self.pipeline.excrete(item, general)

    def regurgitate(self) -> typing.Iterable[str]:
        if self.pipeline is not None:
            # Parentheses around the whole filter are useless, and they make it so if you repeatedly compile(regurgitate(compile(regurgitate...))),
            # each iteration wraps the expression in an additional parentheses.
            yield from self.pipeline.regurgitate(parenthesize=False)

class Pipeline(FilterMember):
    # Yes the type annotations are a little ugly, but there's no way to alias them due to their recursive nature.
    def __init__(self, value: Predicate | Negative | Pipeline, joinables: list[Disjoined | Predicate | Negative | Pipeline]) -> None:
        self.value = value
        self.joinables = joinables
        
    @classmethod
    def eat(cls, tokens: list[str], at: int, expect_eat_everything: bool = False) -> tuple[Pipeline, int]:
        value, until = Value.eat(tokens, at)
        joinables = []

        while until < len(tokens):
            try:
                swallow, until = Joinable.eat(tokens, until)
            except EinGafrurError:
                # Doing it this way "breaks" the model (by giving Pipeline a unique eat signature),
                # but it lets us raise a meaningful error instead of some cryptic "some tokens weren't eaten".
                if expect_eat_everything:
                    raise
                    
                break

            joinables.append(swallow)

        return cls(value, joinables), until

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        accept = self.value.excrete(item, general)
        
        for joinable in self.joinables:
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

        yield from self.value.regurgitate()
        yield from (tok for jable in self.joinables for tok in jable.regurgitate())

        if parenthesize:
            yield min(Positive.RPAREN)

# Some "FilterMembers" (as defined in the BNF) don't need to be instantiated. Eating a "Value" directly returns what its "child" would be.
class Value:
    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[Predicate | Negative | Pipeline, int]:
        # The order is important for raising the most meaningful exception.
        try:
            return Negative.eat(tokens, at)
        except EinGafrurError as e:
            # If the exception was that there isn't a 'not' symbol, we want to try parsing this as a Positive.
            # Otherwise, there's no point to even try, and the most meaningful exception we can raise is this one.
            if e.is_terminal:
                raise

        return Positive.eat(tokens, at)

class Positive:
    LPAREN = {'(', '[', '-lparen'}
    RPAREN = {')', ']', '-rparen'}

    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[Predicate | Pipeline, int]:
        # Only raise parenthesis errors if we have reason to believe this was meant to be a parenthesis expression.
        if at < len(tokens) and tokens[at] in cls.LPAREN:
            pipeline, until = Pipeline.eat(tokens, at + 1)
            
            if until >= len(tokens):
                raise EinGafrurError('Expected matching right parenthesis, but reached the end of input.', tokens=tokens, error_indices=at)

            if tokens[until] not in cls.RPAREN:
                raise EinGafrurError(f"Expected matching right parenthesis, but got: '{tokens[until]}'.", tokens=tokens, error_indices=[at, until])

            return pipeline, until + 1

        return Predicate.eat(tokens, at)

class Negative(FilterMember):
    NEGATE = {'!', '-n', '-not'}

    def __init__(self, positive: Predicate | Pipeline) -> None:
        self.positive = positive

    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[Negative, int]:
        if at >= len(tokens):
            raise EinGafrurError("Expected 'not' symbol, but reached the end of input.", is_terminal=False, tokens=tokens)

        if tokens[at] not in cls.NEGATE:
            raise EinGafrurError(f"Expected 'not' symbol, but got: '{tokens[at]}'.", is_terminal=False, tokens=tokens, error_indices=at)

        positive, until = Positive.eat(tokens, at + 1)
        return cls(positive), until

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        return not self.positive.excrete(item, general)

    def regurgitate(self) -> typing.Iterable[str]:
        yield min(self.NEGATE)
        yield from self.positive.regurgitate()

class Joinable(FilterMember):
    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[Disjoined | Predicate | Negative | Pipeline, int]:
        # Ordered this way so we raise the most meaningful exception possible.
        try:
            return Disjoined.eat(tokens, at)
        except EinGafrurError as e:
            if e.is_terminal:
                raise

        try:
            return Conjoined.eat(tokens, at)
        except EinGafrurError as e:
            if e.is_terminal:
                raise

        return Value.eat(tokens, at)

class Conjoined:
    CONJOIN = {'&', '-a', '-and'}

    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[Predicate | Negative | Pipeline, int]:
        if at >= len(tokens):
            raise EinGafrurError("Expected 'and' symbol, but reached the end of input.", is_terminal=False, tokens=tokens)

        if tokens[at] not in cls.CONJOIN:
            raise EinGafrurError(f"Expected 'and' symbol, but got: '{tokens[at]}'.", is_terminal=False, tokens=tokens, error_indices=at)

        # There is no need to return a Coinjoined object because conjoining is the default behavior when boolean operators are omitted.
        return Value.eat(tokens, at + 1)

class Disjoined(FilterMember):
    DISJOIN = {'|', '-o', '-or'}

    def __init__(self, value: Predicate | Negative | Pipeline) -> None:
        self.value = value

    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[Disjoined, int]:
        if at >= len(tokens):
            raise EinGafrurError("Expected 'or' symbol, but reached the end of input.", is_terminal=False, tokens=tokens)

        if tokens[at] not in cls.DISJOIN:
            raise EinGafrurError(f"Expected 'or' symbol, but got: '{tokens[at]}'.", is_terminal=False, tokens=tokens, error_indices=at)

        value, until = Value.eat(tokens, at + 1)
        return cls(value), until

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        return self.value.excrete(item, general)

    def regurgitate(self) -> typing.Iterable[str]:
        yield min(self.DISJOIN)
        yield from self.value.regurgitate()

class Predicate(FilterMember):
    PREFIX = '-'
    name: str
    
    def __init_subclass__(cls, name: str, **kwargs: typing.Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.name = name

    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[Predicate, int]:
        if at >= len(tokens):
            raise EinGafrurError('Expected a predicate name, but reached the end of input.', tokens=tokens)

        prefixed_name = tokens[at]
        name = prefixed_name.removeprefix(Predicate.PREFIX)

        # Instead of going predicate by predicate and checking for EinGafrurError,
        # it's more optimal to pick the only possibly right predicate from a dictionary,
        # and eat the name token right here and let the predicate eat its arguments alone.
        if name == prefixed_name or name not in PREDICATES:
            if prefixed_name in Positive.RPAREN:
                raise EinGafrurError('Right parenthesis has no matching left parenthesis.', tokens=tokens, error_indices=at)
                
            close_matches = difflib.get_close_matches(prefixed_name, (Predicate.PREFIX + k for k in PREDICATES.keys()))
            suggestions = f' (did you mean: {", ".join(close_matches)}?)' if len(close_matches) > 0 else '.'
            raise EinGafrurError(f"Expected valid predicate name, but got: '{prefixed_name}'{suggestions}", tokens=tokens, error_indices=at)

        # Throughout this file we annotate return types with the class name and not typing.Self.
        # I don't like this, but it's the best way to get mypy to shut up about this line.
        return PREDICATES[name].eat(tokens, at + 1)

    def regurgitate(self) -> typing.Iterable[str]:
        yield self.PREFIX + self.name

# TODO: Predicates except the base Predicate class might be possible to push into a different file.
class TruePredicate(Predicate, name='true'):
    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[Predicate, int]:
        return cls(), at

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        return True

class FalsePredicate(Predicate, name='false'):
    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[Predicate, int]:
        return cls(), at

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        return False

# class MoviePredicate(Predicate):
#     pass
        
# class PersonPredicate(Predicate):
#     pass

# class RolePredicate(Predicate):
#     pass

# TODO: think about how to make this support custom extensions.
PREDICATES = {cls.name: cls for cls in [TruePredicate, FalsePredicate]}

def compile(tokens: list[str]) -> Filter:
    return Filter.eat(tokens)

def decompile(filter: Filter) -> list[str]:
    return list(filter.regurgitate())

def test_compile(line: str) -> None:
    import shlex
    tokens = shlex.split(line)

    try:
        filtr = compile(tokens)
        regurg = ' '.join(EinGafrurError.format_token(t) for t in filtr.regurgitate())
        print(line, '->', regurg)
    except EinGafrurError as e:
        print(e)

# Doesn't guarantee that token is valid, only indicates that it looks like it should be.
def is_filter_token(token: str) -> bool:
    return (token.startswith(Predicate.PREFIX)
            or token in Negative.NEGATE
            or token in Disjoined.DISJOIN
            or token in Conjoined.CONJOIN
            or token in Positive.LPAREN
            or token in Positive.RPAREN)

# test_compile('')
# test_compile('-true')
# test_compile('-true -true -false')
# test_compile('-true -o ( -false ) )')
# test_compile('-ftrual | -tue\\" -o ( -false )')
# test_compile('( ( -true | -true ) ) ! -false')
# test_compile('( -true " "')
# test_compile('true')

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

#endregion filters

#region attributes

class AttributeOwner(enum.Enum):
    MOVIE   = (ListFileMovie,)
    PERSON  = (ListFilePerson,)
    ROLE    = (ListFileRole,)

    def __init__(self, corresponding_type: type) -> None:
        self.corresponding_type = corresponding_type

class Attribute(abc.ABC):
    def __init__(self, owner, name, aliases, is_columnable, is_sortable): # TODO: many more fields. Fields related to sorting, distribution,
        self.owner = owner
        self.name = name
        self.aliases = aliases
        
        # TODO: possibly instead of this make it so it's columnable if it has a "to str" attribute, "sortable" if it has a key extractor attribute
        self.is_columnable = is_columnable
        self.is_sortable = is_sortable

    def extract(self, obj):
        if not isinstance(obj, self.owner.corresponding_type):
            raise Exception(f'Invalid owner: {name} expects {self.owner}, but got {type(obj)}')

        self.ensure_owner_match(obj)
        self._extract_internal(obj)

    @abc.abstractmethod
    def _extract_internal(self, obj):
        pass

#endregion

#region context

# Data structure for using remote/compound lists generically.
LT = typing.TypeVar('LT', RemoteList, CompoundList)

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

    # Had a bitch of a time trying to make this an overload of get_by_uid.
    def get_by_uid_or_none(self, uid: str) -> None | LT:
        return next((l for l in self._lists if l.uid == uid), None)

    def get_by_name(self, name: str) -> LT:
        try:
            return next(l for l in self._lists if l.name == name)
        except StopIteration as e:
            raise exceptions.InputError(f"Invalid {self._type_name} name: '{name}'") from e

    def get_by_name_or_none(self, name: str) -> None | LT:
        return next((l for l in self._lists if l.name == name), None)

# TODO: Register extension attributes, predicates, fetchers, etc. to the context. API goes something like: init context, register extensions, then use context.
# Have a default global context that everything gets registered to if you don't create your own context to isolate it.
# Problem: how to make this compatible with default-imported extensions, we want them to be a feature of flam the API not flam the CLI tool,
# which means we need a way to register them to the specific context.
# Maybe not such a problem, extensions will register to the global context, if you initialize your own context then that's like saying you want to isolate from the global stuff.
# Actually, drop the global context, or at least hide it, have a global "context" that only holds global registrations.
# actual contexts have an option to combine their local registrations with those of the global context.

# This object represents the repository itself mainly. Any creating/writing/reading files from the flam directory should go through here.
# For users who just want to work with volatile memory and not load or save anything, we support a "contextless" mode.
# All the ugly if checks for that are encapsulated in this class.
class FlamContext:
    DEFAULT_FLAM_DIR = os.getenv('FLAM_DIR', os.path.join(os.path.expanduser('~'), '.film_flam'))
    _LISTFILES_DIR = 'list_files'
    _CONFIGURATION_FILE = 'config.json'

    # TODO: Acquire OS lock on the flam_dir so that you can't have multiple contexts operating on it at once?
    def __init__(self, flam_dir: None | str = DEFAULT_FLAM_DIR, import_extensions: bool = False) -> None:
        self._flam_dir = flam_dir

        if self._flam_dir is None:
            self._cfg = Configuration.create()
        else:
            self._flam_dir = os.path.normpath(self._flam_dir)
            self._make_flam_dir()

            cfg_path = self._get_cfg_path()
            self._cfg = Configuration.load(cfg_path) if os.path.exists(cfg_path) else Configuration.create()

        # Since Configuration needs to be serializable, we can't store the lists in there in some funky data structure,
        # and we can't add fields to the object that aren't meant for serialization.
        # The solution I've got is to wrap those lists in this Context.
        self.remote_lists = ConfigurationLists(self.cfg._remote_lists, 'list')
        self.compound_lists = ConfigurationLists(self.cfg._compound_lists, 'compound list')

        # Registered extensions.
        self.fetchers = []
        self.predicates = []
        self.attributes = []

        if import_extensions:
            # TODO: this option does 2 things: import all configured extensions, and subscribe to any globally registered extensions.
            # It's good to make this an option with default false for security, and I prefer to keep the two options as one for simplicity.
            pass

    def _make_flam_dir(self) -> None:
        assert self._flam_dir is not None

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
    def load_list_file(self, abstract_listdef: CanonListdef, must_exist: bool = True) -> ListFile:
        if self._flam_dir is not None:
            try:
                return ListFile.load(self._get_list_file_path(abstract_listdef))
            except FileNotFoundError:
                if must_exist:
                    raise
            except exceptions.FileValidationError as e:
                raise exceptions.FileValidationError(f"{e} You may need to fetch '{self.canon_listdef_pretty(abstract_listdef)}' again from scratch.") from e

        if must_exist:
            raise FileNotFoundError(f"No existing file for LISTDEF '{self.canon_listdef_pretty(abstract_listdef)}' because we're in contextless mode.")

        return ListFile.create()

    def write_list_file(self, list_file: ListFile) -> None:
        # We use devnull in contextless mode, so that we still go through the file validity checks even if we don't write it anywhere.
        if self._flam_dir is None:
            list_file.write(os.devnull)
            return

        file = self._get_list_file_path(list_file.abstract_listdef)
        
        try:
            shutil.copyfile(file, f'{file}.bak')
        except FileNotFoundError:
            pass
        finally:
            # No backup error is worth not writing what we've got.
            list_file.write(file)

    def restore_list_file_to_previous(self, abstract_listdef: CanonListdef) -> None:
        if self._flam_dir is not None:
            file = self._get_list_file_path(abstract_listdef)
            shutil.copyfile(f'{file}.bak', file)
            # TODO: Mark categories dirty.

    # After much deliberation, I decided that files for named lists should be named according to the list type and UID,
    # and unnamed lists' files should be named according to the fetcher type and address.
    # This is mostly as opposed to storing all lists according to the concrete fetcher_type and address.
    # The reason: this lets us change lists to a different fetcher type with a compatible ID type.
    def _get_list_file_path(self, abstract_listdef: CanonListdef) -> str:
        assert self._flam_dir is not None
        filename = utils.slugify(f'{abstract_listdef.fetcher_type}_{abstract_listdef.address}.json')
        return os.path.join(self._flam_dir, self._LISTFILES_DIR, filename)

    # Configuration.
    @property
    def cfg(self) -> Configuration:
        return self._cfg

    def lists_of_type(self, fetcher_type: str) -> ConfigurationLists[RemoteList] | ConfigurationLists[CompoundList]:
        match fetcher_type:
            case RemoteList.FETCHER_TYPE:
                return self.remote_lists
            case CompoundList.FETCHER_TYPE:
                return self.compound_lists
            case _:
                raise ValueError(f"Invalid type '{fetcher_type}': not any kind of list.")

    def get_list_by_abstract_listdef(self, abstract_listdef: CanonListdef) -> RemoteList | CompoundList:
        return self.lists_of_type(abstract_listdef.fetcher_type).get_by_uid(abstract_listdef.address)

    def get_list_by_abstract_listdef_or_none(self, abstract_listdef: CanonListdef) -> None | RemoteList | CompoundList:
        return self.lists_of_type(abstract_listdef.fetcher_type).get_by_uid_or_none(abstract_listdef.address)

    def add_remote_list(self, remote_list: RemoteList) -> None:
        remote_list.uid = str(uuid.uuid4())
        self.cfg._remote_lists.append(remote_list) # pylint: disable=protected-access

        # See if the list was already fetched before it was named, and "claim" the file.
        if self._flam_dir is not None:
            concrete_filename = self._get_list_file_path(remote_list.concrete_listdef)
            abstract_filename = self._get_list_file_path(remote_list.abstract_listdef)
            
            try:
                os.rename(concrete_filename, abstract_filename)
            except FileNotFoundError:
                pass

    def delete_remote_list(self, uid: str) -> None:
        remote_list = self.remote_lists.get_by_uid(uid)

        # We don't mess with removing the list from its dependent compound lists. Let the user do that.
        dependents = [cl.name for cl in self.compound_lists if uid in cl.remote_list_uids]

        if len(dependents) > 0:
            raise exceptions.InputError(f"Failed to delete list '{remote_list.name}' because it is depended on by compound lists: {', '.join(dependents)}")

        if self._flam_dir is not None:
            # Deleting a list doesn't delete it from local storage, only gets it renamed to be anonymous.
            concrete_filename = self._get_list_file_path(remote_list.concrete_listdef)
            abstract_filename = self._get_list_file_path(remote_list.abstract_listdef)

            try:
                os.rename(abstract_filename, concrete_filename)
            except FileNotFoundError:
                pass

        self.cfg._remote_lists.remove(remote_list) # pylint: disable=protected-access

    def add_compound_list(self, compound_list: CompoundList) -> None:
        compound_list.uid = str(uuid.uuid4())
        self.cfg._compound_lists.append(compound_list) # pylint: disable=protected-access

    def delete_compound_list(self, uid: str) -> None:
        compound_list = self.compound_lists.get_by_uid(uid)

        if self._flam_dir is not None:
            # TODO: delete files
            pass

        self.cfg._compound_lists.remove(compound_list) # pylint: disable=protected-access

    def write_cfg(self) -> None:
        # We use devnull in contextless mode, so that we still go through the file validity checks even if we don't write it anywhere.
        file = self._get_cfg_path() if self._flam_dir is not None else os.devnull
        self.cfg.write(file)
        
    def _get_cfg_path(self) -> str:
        assert self._flam_dir is not None
        return os.path.join(self._flam_dir, self._CONFIGURATION_FILE)

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

        # For remote/compound lists we need to convert the name to a uid.
        if eq_idx != -1 and (before_eq == RemoteList.FETCHER_TYPE or before_eq == CompoundList.FETCHER_TYPE):
            return self.lists_of_type(before_eq).get_by_name(after_eq).abstract_listdef
        
        # The generic case where it's whatever=whatever.
        if eq_idx != -1:
            return CanonListdef(before_eq, after_eq)
        
        # If no '=' sign then we'll treat it as a list or compound list, and try to determine which.
        if (list_obj := self._get_implicit_list(before_eq)) is not None:
            return list_obj.abstract_listdef

        raise exceptions.InputError(f"Invalid LISTDEF: '{listdef}'.")

    # This is the most that we can canonicalize/expand listdefs generically. Other transformations are different for fetching vs finding vs whatever.
    def canonicalize_listdefs_with_all_expansion(self, listdefs: typing.Iterable[str]) -> typing.Iterator[CanonListdef]:
        for ldef in listdefs:
            cldef = self.canonicalize_listdef(ldef)

            if cldef.fetcher_type == LISTDEF_ALL:
                yield from (rl.abstract_listdef for rl in self.remote_lists)
            else:
                yield cldef

    # Internally when canonicalizing listdefs it's convenient to convert list names to UIDs,
    # but it means that whenever we print the listdef we need to convert it back to have human-readable list names.
    def canon_listdef_pretty(self, canon_listdef: CanonListdef) -> str:
        return str(canon_listdef._replace(address=self.get_list_by_abstract_listdef(canon_listdef).name) if canon_listdef.is_abstract else canon_listdef)

    def _get_implicit_list(self, name: str) -> None | RemoteList | CompoundList:
        try:
            return self.remote_lists.get_by_name(name)
        except exceptions.InputError:
            pass

        try:
            return self.compound_lists.get_by_name(name)
        except exceptions.InputError:
            pass

        return None

    # Registration.
    # TODO: avoid duplicates, better data structures, whatever? Also get functions and everything, and maybe make the lists private.
    def register_fetcher(self, fetcher: ListFetcher) -> None:
        self.fetchers.append(fetcher)

    def register_predicate(self, predicate: Predicate) -> None:
        self.predicates.append(predicate)

    def register_attribute(self, attribute: Attribute) -> None:
        self.attributes.append(attribute)

#endregion context

#region general

# Users input LISTDEF strings and we turn them into this more convenient representation.
class CanonListdef(typing.NamedTuple):
    fetcher_type: str
    address: str

    @property
    def is_special(self) -> bool:
        return self.fetcher_type in SPECIAL_FETCHER_TYPES

    # RemoteList/CompoundList listdefs are abstract because they can't be fetched directly, only through the underlying "concrete" type.
    @property
    def is_abstract(self) -> bool:
        return self.fetcher_type == RemoteList.FETCHER_TYPE or self.fetcher_type == CompoundList.FETCHER_TYPE

    # "Concrete" listdefs have a type that directly corresponds to a ListFetcher.
    @property
    def is_concrete(self) -> bool:
        return not self.is_special

    def __str__(self) -> str:
        return f'{self.fetcher_type}={self.address}'

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

LISTDEF_ALL = '*'
LISTDEF_DEFAULTS = 'defaults'
SPECIAL_FETCHER_TYPES = {LISTDEF_DEFAULTS, LISTDEF_ALL, RemoteList.FETCHER_TYPE, CompoundList.FETCHER_TYPE}

#endregion general
