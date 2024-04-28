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

# The type annotations here are way too recursive to resolve any other way.
from __future__ import annotations

import typing
import abc
import difflib

import filmflam.repo as repo
import filmflam._utils as utils
import filmflam.exceptions as exceptions

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

    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[Predicate, int]:
        if at >= len(tokens):
            raise EinGafrurError('Expected a predicate name, but reached the end of input.', tokens=tokens)

        prefixed_name = tokens[at]
        name = prefixed_name.removeprefix(Predicate.PREFIX)

        # Instead of going predicate by predicate and checking for EinGafrurError,
        # it's more optimal to pick the only possibly right predicate from a dictionary,
        # and eat the name token right here and let the predicate eat its arguments alone.
        if prefixed_name == name or name not in PREDICATES:
            if prefixed_name in Positive.RPAREN:
                raise EinGafrurError('Right parenthesis has no matching left parenthesis.', tokens=tokens, error_indices=at)
                
            close_matches = difflib.get_close_matches(prefixed_name, (Predicate.PREFIX + k for k in PREDICATES.keys()))
            suggestions = f' (did you mean: {", ".join(close_matches)}?)' if len(close_matches) > 0 else ''
            raise EinGafrurError(f"Expected valid predicate name, but got: '{prefixed_name}'{suggestions}.", tokens=tokens, error_indices=at)

        # Throughout this file we annotate return types with the class name and not typing.Self.
        # I don't like this, but it's the best way to get mypy to shut up about this line.
        return PREDICATES[name].eat(tokens, at + 1)

    @classmethod
    @abc.abstractmethod
    def predicate_name(cls) -> str:
        pass

class TruePredicate(Predicate):
    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[Predicate, int]:
        return cls(), at

    @classmethod
    def predicate_name(cls) -> str:
        return 'true'

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        return True

    def regurgitate(self) -> typing.Iterable[str]:
        yield self.predicate_name()

class FalsePredicate(Predicate):
    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[Predicate, int]:
        return cls(), at

    @classmethod
    def predicate_name(cls) -> str:
        return 'false'

    def excrete(self, item: typing.Any, general: typing.Any) -> bool:
        return False

    def regurgitate(self) -> typing.Iterable[str]:
        yield self.predicate_name()

class MoviePredicate(Predicate):
    pass
        
class PersonPredicate(Predicate):
    pass

class RolePredicate(Predicate):
    pass

# TODO: think about how to make this support custom extensions.
PREDICATES = {cls.predicate_name(): cls for cls in [TruePredicate, FalsePredicate]}

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
