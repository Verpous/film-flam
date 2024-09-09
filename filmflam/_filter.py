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
from . import _xcept
from . import _list

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
_EinGafrurError = _xcept.FilterSyntaxError

@dataclasses.dataclass(frozen=True)
class EatParams:
    tokens: list[str]
    find: _list.FindableType
    ctx: _ctx.FlamContext

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
    def eat_str(cls, params: EatParams, at: int, description: str, error_indices: int | typing.Iterable[int] = -1, is_terminal: bool = False) -> str:
        if at >= len(params.tokens):
            raise _EinGafrurError(f"Expected {description}, but reached the end of input.", tokens=params.tokens, is_terminal=is_terminal, error_indices=error_indices)

        return params.tokens[at]

    @classmethod
    def eat_one_of(cls, params: EatParams, at: int, description: str, options: set[str], is_terminal: bool = False) -> str:
        s = cls.eat_str(params, at, description, is_terminal)
        
        if s not in options:
            raise _EinGafrurError(f"Expected {description}, but got: '{s}'.", tokens=params.tokens, is_terminal=is_terminal, error_indices=at)

        return s

    @classmethod
    def eat_attribute(cls, params: EatParams, at: int, is_array: bool = False) -> _attr.Attribute:
        description = 'a valid attribute name'
        attribute_name = cls.eat_str(params, at, description)
        attribute = next((registry.get_attribute(attribute_name) for registry in params.ctx.registries_to_try() if registry.has_attribute(attribute_name)), None)

        if attribute is None:
            raise _EinGafrurError(f"Expected {description}, but got: '{attribute_name}'.", tokens=params.tokens, error_indices=at)

        if not attribute.findable_type.is_compatible(params.find):
            raise _EinGafrurError(f"Expected attribute of {params.find}, but got: '{attribute_name}' which belongs to {attribute.findable_type}.",
                tokens=params.tokens, error_indices=at)

        if is_array and not attribute.is_array:
            # TODO: "which is of type X"? Or nah?
            raise _EinGafrurError(f"Expected attribute to be an array type, but got: '{attribute_name}'.", tokens=params.tokens, error_indices=at)

        return attribute

    @classmethod
    def eat_cmp_value(cls, params: EatParams, at: int, default_cmp: _attr.ComparisonOp) -> tuple[_attr.ComparisonOp, str]:
        cmp_value = cls.eat_str(params, at, 'a value')
        # TODO: Cast value into correct type?
        return cls.split_cmp_value(cmp_value, default_cmp)

    # TODO: if the type is regex compile it right here right now? Probably not since why would it be special when all other values are parsed later.
    @classmethod
    def split_cmp_value(cls, cmp_value: str, default_cmp: _attr.ComparisonOp) -> tuple[_attr.ComparisonOp, str]:
        for cmp in _attr.ComparisonOp:
            if cmp_value.startswith(cmp.sign):
                return cmp, cmp_value.removeprefix(cmp.sign)

        return default_cmp, cmp_value

class Filter(FilterMember):
    def __init__(self, pipeline: None | Pipeline, find: _list.FindableType) -> None:
        self._pipeline = pipeline
        self._find = find

    @property
    def findable_type(self) -> _list.FindableType:
        return self._find

    @property
    def is_empty(self) -> bool:
        return self._pipeline is None

    # We compile by defining "eat" classmethods for all the FilterMembers (and some classes which aren't FilterMembers).
    # Generally, eat receives the *full* tokenized expression, the index where "uneaten" tokens begin, and some extras.
    # It "eats" tokens starting from the given index and returns the FilterMember object created from them, and the index where it stopped eating.
    # Filter is the root object so it's a little different, it expects to eat everything to it doesn't need start or end indices.
    @classmethod
    def eat(cls, params: EatParams) -> Filter:
        if len(params.tokens) == 0:
            return cls(None, params.find)

        pipeline, _ = Pipeline.eat(params, 0, expect_eat_everything=True)
        return cls(pipeline, params.find)

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
    def eat(cls, params: EatParams, at: int, expect_eat_everything: bool = False) -> tuple[Pipeline, int]:
        single, until = Single.eat(params, at)
        joinables = []

        while until < len(params.tokens):
            try:
                jable, until = Joinable.eat(params, until)
            except _EinGafrurError:
                # Doing it this way "breaks" the model (by giving Pipeline a unique eat signature),
                # but it lets us raise a meaningful error instead of some cryptic "some tokens weren't eaten".
                if expect_eat_everything:
                    raise
                    
                break

            joinables.append(jable)

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
                raise RuntimeError(f"Pipeline ate a joinable of type: {type(joinable)}. This shouldn't happen.")

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
    LPAREN = {'(', '[', '-lparen'}
    RPAREN = {')', ']', '-rparen'}
    _RPAREN_DESC = 'matching right parenthesis'

    @classmethod
    def eat(cls, params: EatParams, at: int) -> tuple[Predicate | Pipeline, int]:
        # Only raise parenthesis errors if we have reason to believe this was meant to be a parenthesis expression.
        if at < len(params.tokens) and params.tokens[at] in cls.LPAREN:
            pipeline, until = Pipeline.eat(params, at + 1)
            
            # Doesn't use eat_one_of because different error_indices.
            rparen = FilterMember.eat_str(params, until, cls._RPAREN_DESC, error_indices=at)

            if rparen not in cls.RPAREN:
                raise _EinGafrurError(f"Expected {cls._RPAREN_DESC}, but got: '{rparen}'.", tokens=params.tokens, error_indices=[at, until])

            return pipeline, until + 1

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

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        return not self._positive.excrete(item, general)

    def regurgitate(self) -> typing.Iterable[str]:
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
    def eat(cls, params: EatParams, at: int) -> tuple[Predicate, int]:
        prefixed_name = cls.eat_str(params, at, 'a predicate name')
        name = prefixed_name.removeprefix(Predicate.PREFIX)

        if name != prefixed_name:
            # Instead of going predicate by predicate and checking for _EinGafrurError,
            # it's more optimal to pick the only possibly right predicate from a dictionary,
            # and eat the name token right here and let the predicate eat its arguments alone.
            for registry in params.ctx.registries_to_try():
                if registry.has_predicate(name):
                    # Mypy wouldn't like this line if we annotated with typing.Self.
                    return registry.get_predicate(name).eat(params, at + 1)
                
                # Special treatment for AttributePredicate because it's not wise to make a predicate for each attribute.
                if registry.has_attribute(name):
                    attribute = registry.get_attribute(name)

                    if not attribute.findable_type.is_compatible(params.find):
                        raise _EinGafrurError(f"Expected attribute of {params.find}, but got: '{attribute.name}' which belongs to {attribute.findable_type}.",
                            tokens=params.tokens, error_indices=at)

                    return AttributePredicate.eat_shit(params, at + 1, registry.get_attribute(name))

        if prefixed_name in Positive.RPAREN:
            raise _EinGafrurError('Right parenthesis has no matching left parenthesis.', tokens=params.tokens, error_indices=at)
            
        all_pred_names = (
            Predicate.PREFIX + k
            for registry in params.ctx.registries_to_try()
                for keyvals in (registry.predicate_keyvals(), registry.attribute_keyvals())
                    for k, _ in keyvals
        )

        close_matches = difflib.get_close_matches(prefixed_name, all_pred_names)
        suggestions = f' (did you mean: {", ".join(close_matches)}?)' if len(close_matches) > 0 else '.'
        raise _EinGafrurError(f"Expected valid predicate name, but got: '{prefixed_name}'{suggestions}", tokens=params.tokens, error_indices=at)

    def regurgitate(self) -> typing.Iterable[str]:
        yield self.PREFIX + self.name

# This should be the only concrete predicate that is in this file, because it's special.
class AttributePredicate(Predicate, name='attribute'):
    def __init__(self, attribute: _attr.Attribute, cmp: _attr.ComparisonOp, value: typing.Any) -> None: # TODO: not "Any"?
        self._attribute = attribute
        self._cmp = cmp
        self._value = value

        # Shadow the name with that of the attribute. Python lets you shadow class variables with instance variables like this.
        self.name = attribute.name

    # Part of being a special predicate means its "eat" has a different signature so we have to give it a different name.
    @classmethod
    def eat_shit(cls, params: EatParams, at: int, attribute: _attr.Attribute) -> tuple[Predicate, int]:
        cmp, value_str = cls.eat_cmp_value(params, at, attribute.default_cmp)
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

def split_at_filter(strs: list[str]) -> tuple[list[str], list[str]]:
    filter_begin = next((i for i, s in enumerate(strs) if is_filter_token(s)), len(strs))
    return strs[:filter_begin], strs[filter_begin:]
