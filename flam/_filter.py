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

import abc
import typing
import difflib
import dataclasses

from . import _ctx
from . import _attr
from . import _exc
from . import _ml

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
_EinGafrurError = _exc.FilterSyntaxError

@dataclasses.dataclass(frozen=True)
class EatParams:
    tokens: list[str]
    find: _ml.FindableType
    ctx: _ctx.FlamContext

# We represent filters as an AST of FilterMembers.
class FilterMember(abc.ABC):
    # Takes in a found item (movie, person, or role) and returns true if it passes the filter.
    @abc.abstractmethod
    def excrete(self, findable: _ml.Findable, ctx: _ctx.FlamContext) -> bool:
        pass

    # Decompiles the filter into a list of tokens.
    @abc.abstractmethod
    def regurgitate(self) -> typing.Iterator[str]:
        pass

    def __str__(self) -> str:
        return ' '.join(self.regurgitate())

    # Helper methods for parsing below.
    @classmethod
    def eat_str(cls, params: EatParams, at: int, description: str, error_indices: int | typing.Iterable[int] = -1, is_terminal: bool = True) -> str:
        if at >= len(params.tokens):
            raise _EinGafrurError(f"Expected {description}, but reached the end of input.", tokens=params.tokens, error_indices=error_indices, is_terminal=is_terminal)

        return params.tokens[at]

    # eatfunc is assumed to only consume 1.
    @classmethod
    def eat_listof[T](cls, eatfunc: typing.Callable[[EatParams, int], T], params: EatParams, at: int, at_least_one: bool) -> tuple[list[T], int]:
        if at < len(params.tokens) and params.tokens[at] in Pipeline.LPAREN:
            try:
                rparen_idx = next(i for i in range(at + 1, len(params.tokens)) if params.tokens[i] in Pipeline.RPAREN)
            except StopIteration as e:
                raise _EinGafrurError(f"Expected {Pipeline._RPAREN_DESC}, but reached the end of input.", tokens=params.tokens, error_indices=at) from e

            if at_least_one and rparen_idx == at + 1:
                raise _EinGafrurError("Expected non empty list.", tokens=params.tokens, error_indices=[at, rparen_idx])

            return [eatfunc(params, i) for i in range(at + 1, rparen_idx)], rparen_idx + 1

        return [eatfunc(params, at)], at + 1

    @classmethod
    def eat_one_of(cls, params: EatParams, at: int, description: str, options: set[str], is_terminal: bool = True) -> str:
        s = cls.eat_str(params, at, description, is_terminal=is_terminal)
        
        if s not in options:
            raise _EinGafrurError(f"Expected {description}, but got: '{s}'.", tokens=params.tokens, error_indices=at, is_terminal=is_terminal)

        return s

    @classmethod
    def eat_attribute(cls, params: EatParams, at: int) -> _attr.Attribute:
        description = 'a valid attribute name'
        attribute_name = cls.eat_str(params, at, description)

        try:
            attribute = params.ctx.attributes[attribute_name]
        except _exc.InputError as e:
            raise _EinGafrurError(f"Expected {description}, but got: '{attribute_name}'.", tokens=params.tokens, error_indices=at) from e

        if not attribute.findable_type.is_applicable_to(params.find):
            raise _EinGafrurError(f"Expected attribute of {params.find}, but got: '{attribute_name}' which belongs to {attribute.findable_type}.",
                tokens=params.tokens, error_indices=at)

        return attribute

    @classmethod
    def eat_cmpto(cls, params: EatParams, at: int, attribute: _attr.Attribute) -> _attr.CmpTo:
        cmpto_str = cls.eat_str(params, at, 'a value')
        op, value_str = cls.split_cmpto_str(cmpto_str, attribute.default_op)

        try:
            return attribute.make_cmpto(op, value_str)
        except _exc.InputError as e:
            raise _EinGafrurError(str(e), tokens=params.tokens, error_indices=at) from e

    @classmethod
    def split_cmpto_str(cls, cmpto: str, default_op: _attr.ComparisonOp) -> tuple[_attr.ComparisonOp, str]:
        for op in _attr.ComparisonOp:
            if cmpto.startswith(op.sign):
                return op, cmpto.removeprefix(op.sign)

        return default_op, cmpto

    @classmethod
    def eat_movie_list(cls, params: EatParams, at: int) -> tuple[_ml.MovieList, int]:
        listdefs, until = cls.eat_listof(lambda p, a: cls.eat_str(p, a, 'a LISTDEF'), params, at, True)

        try:
            return params.ctx.get_movie_list(listdefs), until
        except _exc.InputError as e:
            raise _exc.FilterSyntaxError(f"Expected valid LISTDEFs, but got error: {e}", tokens=params.tokens, error_indices=at) from e

    @classmethod
    def eat_ct_gm(cls, params: EatParams, at: int) -> tuple[_ml.CrewType, _ml.GroupMode]:
        ct_gm_str = cls.eat_str(params, at, 'crew type[:group mode]')

        try:
            return _ml.parse_ct_gm(ct_gm_str)
        except _exc.InputError as e:
            raise _EinGafrurError(f"Expected a valid crew type[:group mode], but got error: {e}", tokens=params.tokens, error_indices=at) from e

class Filter(FilterMember):
    def __init__(self, filter: None | Predicate | Negative | Pipeline, find: _ml.FindableType, ctx: _ctx.FlamContext) -> None:
        self._filter = filter
        self._find = find
        self._ctx = ctx

        self._regurgitation: None | list[str] = None

    @property
    def findable_type(self) -> _ml.FindableType:
        return self._find

    # Yes, the context is part of the filter's state. The reason is the filter may contain predicates like -in-other which bind it to the context.
    @property
    def ctx(self) -> _ctx.FlamContext:
        return self._ctx

    @property
    def is_empty(self) -> bool:
        return self._filter is None

    # We compile by defining "eat" classmethods for all the FilterMembers (and some classes which aren't FilterMembers).
    # Generally, eat receives the *full* tokenized expression, the index where "uneaten" tokens begin, and some extras.
    # It "eats" tokens starting from the given index and returns the FilterMember object created from them, and the index where it stopped eating.
    # Filter is the root object so it's a little different, it expects to eat everything to it doesn't need start or end indices.
    @classmethod
    def eat(cls, params: EatParams) -> Filter:
        if len(params.tokens) == 0:
            return cls(None, params.find, params.ctx)
        
        pipeline, _ = Pipeline.eat(params, 0, True)
        return cls(pipeline, params.find, params.ctx)

    # Some predicates take a Single as an argument. But this Single should be wrapped in a Filter so that we can treat it as a complete expression of its own.
    @classmethod
    def eat_single(cls, params: EatParams, at: int) -> tuple[Filter, int]:
        # Allow a way to indicate "empty" because we require tokens to have something in it to eat.
        if at < len(params.tokens) and params.tokens[at] in ('', '-'):
            return cls(None, params.find, params.ctx), at + 1
        
        single, until = Single.eat(params, at)
        return cls(single, params.find, params.ctx), until

    def excrete(self, findable: _ml.Findable, ctx: _ctx.FlamContext) -> bool:
        return self._filter is None or self._filter.excrete(findable, ctx)

    def regurgitate(self) -> typing.Iterator[str]:
        # Cache it since due to logging it's pretty much guaranteed we will want this multiple times.
        if self._regurgitation is None:
            self._regurgitation = [] if self._filter is None else list(self._filter.regurgitate())

        return iter(self._regurgitation)

class Pipeline(FilterMember):
    LPAREN = {'(', '[', '-lparen'}
    RPAREN = {')', ']', '-rparen'}
    _LPAREN_DESC = 'left parenthesis'
    _RPAREN_DESC = 'matching right parenthesis'

    # Yes the type annotations are a little ugly, but there's no way to alias them due to their recursive nature.
    def __init__(self, single: Predicate | Negative | Pipeline, joinables: list[Disjoined | Predicate | Negative | Pipeline], is_entire_filter: bool) -> None:
        self._single = single
        self._joinables = joinables
        self._is_entire_filter = is_entire_filter
        
    @classmethod
    def eat(cls, params: EatParams, at: int, is_entire_filter: bool) -> tuple[Pipeline, int]:
        # If we don't expect to eat the entire filter what we do eat must be parenthesized.
        if is_entire_filter:
            single_idx = at
        else:
            cls.eat_one_of(params, at, cls._LPAREN_DESC, cls.LPAREN, is_terminal=False)
            single_idx = at + 1

        closed_parentheses = False
        single, until = Single.eat(params, single_idx)
        joinables = []

        while until < len(params.tokens):
            # Don't use eat_one_of because we know we aren't at end of input and we don't want to spam exceptions.
            if not is_entire_filter and params.tokens[until] in cls.RPAREN:
                closed_parentheses = True
                until += 1
                break

            jable, until = Joinable.eat(params, until)
            joinables.append(jable)

        if not is_entire_filter and not closed_parentheses:
            raise _EinGafrurError(f"Expected {cls._RPAREN_DESC}, but reached the end of input.", tokens=params.tokens, error_indices=[at])

        return cls(single, joinables, is_entire_filter), until

    def excrete(self, findable: _ml.Findable, ctx: _ctx.FlamContext) -> bool:
        accept = self._single.excrete(findable, ctx)
        
        for joinable in self._joinables:
            # Conjunction is the default, so only disjunction must be specified.
            if isinstance(joinable, Negative | Predicate | Pipeline):
                accept = accept and joinable.excrete(findable, ctx)
            elif isinstance(joinable, Disjoined):
                accept = accept or joinable.excrete(findable, ctx)
            else:
                raise RuntimeError(f"Pipeline ate a joinable of type: {type(joinable)}. This shouldn't happen.")

        return accept

    def regurgitate(self) -> typing.Iterator[str]:
        # Parentheses around entire filters are useless, and they make it so if you repeatedly compile(regurgitate(compile(regurgitate...))),
        # each iteration wraps the expression in an additional parentheses.
        if not self._is_entire_filter:
            # We use min because these are sets so next(iter(...)) returns different things every time.
            yield min(Pipeline.LPAREN)

        yield from self._single.regurgitate()
        yield from (tok for jable in self._joinables for tok in jable.regurgitate())

        if not self._is_entire_filter:
            yield min(Pipeline.RPAREN)

# Some "FilterMembers" (as defined in the BNF) don't need to be instantiated. Eating a "Single" directly returns what its "child" would be.
class Single:
    @classmethod
    def eat(cls, params: EatParams, at: int) -> tuple[Predicate | Negative | Pipeline, int]:
        # The order is important for raising the most meaningful exception.
        try:
            return Negative.eat(params, at)
        except _EinGafrurError as e:
            # If the exception was that there isn't a 'not' symbol, we want to try parsing this as a Positive.
            # Otherwise, there's no point to even try, and the most meaningful exception we can raise is this one.
            if e.is_terminal:
                raise

        return Positive.eat(params, at)

class Positive:
    @classmethod
    def eat(cls, params: EatParams, at: int) -> tuple[Predicate | Pipeline, int]:
        try:
            return Pipeline.eat(params, at, False)
        except _EinGafrurError as e:
            if e.is_terminal:
                raise

        return Predicate.eat(params, at)

class Negative(FilterMember):
    NEGATE = {'!', '-n', '-not'}
    _DESC = "'not' symbol"

    def __init__(self, positive: Predicate | Pipeline) -> None:
        self._positive = positive

    @classmethod
    def eat(cls, params: EatParams, at: int) -> tuple[Negative, int]:
        cls.eat_one_of(params, at, cls._DESC, cls.NEGATE, is_terminal=False)
        positive, until = Positive.eat(params, at + 1)
        return cls(positive), until

    def excrete(self, findable: _ml.Findable, ctx: _ctx.FlamContext) -> bool:
        return not self._positive.excrete(findable, ctx)

    def regurgitate(self) -> typing.Iterator[str]:
        yield min(self.NEGATE)
        yield from self._positive.regurgitate()

class Joinable(FilterMember):
    @classmethod
    def eat(cls, params: EatParams, at: int) -> tuple[Disjoined | Predicate | Negative | Pipeline, int]:
        # Ordered this way so we raise the most meaningful exception possible.
        try:
            return Disjoined.eat(params, at)
        except _EinGafrurError as e:
            if e.is_terminal:
                raise

        try:
            return Conjoined.eat(params, at)
        except _EinGafrurError as e:
            if e.is_terminal:
                raise

        return Single.eat(params, at)

class Conjoined:
    CONJOIN = {'&', '-a', '-and'}
    _DESC = "'and' symbol"

    @classmethod
    def eat(cls, params: EatParams, at: int) -> tuple[Predicate | Negative | Pipeline, int]:
        FilterMember.eat_one_of(params, at, cls._DESC, cls.CONJOIN, is_terminal=False)

        # There is no need to return a Coinjoined object because conjoining is the default behavior when boolean operators are omitted.
        return Single.eat(params, at + 1)

class Disjoined(FilterMember):
    DISJOIN = {'|', '-o', '-or'}
    _DESC = "'or' symbol"

    def __init__(self, single: Predicate | Negative | Pipeline) -> None:
        self._single = single

    @classmethod
    def eat(cls, params: EatParams, at: int) -> tuple[Disjoined, int]:
        cls.eat_one_of(params, at, cls._DESC, cls.DISJOIN, is_terminal=False)
        single, until = Single.eat(params, at + 1)
        return cls(single), until

    def excrete(self, findable: _ml.Findable, ctx: _ctx.FlamContext) -> bool:
        return self._single.excrete(findable, ctx)

    def regurgitate(self) -> typing.Iterator[str]:
        yield min(self.DISJOIN)
        yield from self._single.regurgitate()

class Predicate(FilterMember):
    PREFIX = '-'
    name: str
    findable_type: None | _ml.FindableType
    
    def __init_subclass__(cls, name: str, findable_type: None | _ml.FindableType = None, **kwargs: typing.Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.name = name
        cls.findable_type = findable_type

    @classmethod
    def eat(cls, params: EatParams, at: int) -> tuple[Predicate, int]:
        prefixed_name = cls.eat_str(params, at, 'a predicate name')
        name = prefixed_name.removeprefix(Predicate.PREFIX)

        if name != prefixed_name:
            # Instead of going predicate by predicate and checking for _EinGafrurError,
            # it's more optimal to pick the only possibly right predicate from a dictionary,
            # and eat the name token right here and let the predicate eat its arguments alone.
            if name in params.ctx.predicates:
                # Mypy wouldn't like this line if we annotated with typing.Self.
                predicate = params.ctx.predicates[name]

                if predicate.findable_type is not None and not predicate.findable_type.is_applicable_to(params.find):
                    raise _EinGafrurError(f"Expected predicate of {params.find}, but got: '{prefixed_name}' which belongs to {predicate.findable_type}.",
                        tokens=params.tokens, error_indices=at)

                return predicate.eat(params, at + 1)

            # Special treatment for AttributePredicate because it's not wise to make a predicate for each attribute.
            # TODO: Don't like that we go first-pred, then-attribute when we should go level by level pred-then-attribute.
            if name in params.ctx.attributes:
                attribute = params.ctx.attributes[name]

                if not attribute.findable_type.is_applicable_to(params.find):
                    raise _EinGafrurError(f"Expected attribute of {params.find}, but got: '{attribute.name}' which belongs to {attribute.findable_type}.",
                        tokens=params.tokens, error_indices=at)

                return AttributePredicate.eat_shit(params, at + 1, attribute)

        if prefixed_name in Pipeline.RPAREN:
            raise _EinGafrurError('Unexpected right parenthesis. It either has no matching left parenthesis or a predicate was expected.',
                tokens=params.tokens, error_indices=at)
            
        close_matches = difflib.get_close_matches(prefixed_name, (Predicate.PREFIX + pred.name for pred in params.ctx.predicates))
        suggestions = f' (did you mean: {", ".join(close_matches)}?)' if len(close_matches) > 0 else '.'
        raise _EinGafrurError(f"Expected valid predicate name, but got: '{prefixed_name}'{suggestions}", tokens=params.tokens, error_indices=at)

    def regurgitate(self) -> typing.Iterator[str]:
        yield self.PREFIX + self.name

# This should be the only concrete predicate that is in this file, because it's special.
class AttributePredicate(Predicate, name='attribute'):
    def __init__(self, attribute: _attr.Attribute, cmpto: _attr.CmpTo) -> None:
        self._attribute = attribute
        self._cmpto = cmpto

        # Shadow the name with that of the attribute. Python lets you shadow class variables with instance variables like this.
        self.name = attribute.name

    # Part of being a special predicate means its "eat" has a different signature so we have to give it a different name.
    @classmethod
    def eat_shit(cls, params: EatParams, at: int, attribute: _attr.Attribute) -> tuple[Predicate, int]:
        cmpto = cls.eat_cmpto(params, at, attribute)
        return cls(attribute, cmpto), at + 1

    def excrete(self, findable: _ml.Findable, ctx: _ctx.FlamContext) -> bool:
        actual = findable.extract(self._attribute)

        # For lists we do "contains". There is an "-all" predicate for those who want that behavior.
        if isinstance(actual, list):
            return any(self._cmpto(elem) for elem in actual)

        return self._cmpto(actual)

    def regurgitate(self) -> typing.Iterator[str]:
        yield from super().regurgitate()
        yield str(self._cmpto)

# Doesn't guarantee that token is valid, only indicates that it looks like it should be.
def is_filter_token(token: str) -> bool:
    return (token.startswith(Predicate.PREFIX)
            or token in Negative.NEGATE
            or token in Disjoined.DISJOIN
            or token in Conjoined.CONJOIN
            or token in Pipeline.LPAREN
            or token in Pipeline.RPAREN)
