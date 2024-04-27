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

class FilterMember(abc.ABC):
    @abc.abstractmethod
    def excrete(self, item, general):
        pass

    @abc.abstractmethod
    def regurgitate(self):
        pass

class Filter(FilterMember):
    def __init__(self, pipeline):
        self.pipeline = pipeline
        
    @classmethod
    def eat(cls, tokens: list[str]) -> FilterMember:
        if len(tokens) == 0:
            return cls(None)

        pipeline, _ = Pipeline.eat(tokens, 0, expect_eat_everything=True)
        return cls(pipeline)

    def excrete(self, item, general):
        return True if self.pipeline is None else self.pipeline.excrete(item, general)

    def regurgitate(self):
        if self.pipeline is not None:
            # Parentheses around the whole filter are useless, and they make it so if you repeatedly compile(regurgitate(compile(regurgitate...))),
            # each iteration wraps the expression in an additional parentheses.
            yield from self.pipeline.regurgitate(parenthesize=False)

class Pipeline(FilterMember):
    def __init__(self, value, joinables):
        self.value = value
        self.joinables = joinables
        
    @classmethod
    def eat(cls, tokens: list[str], at, expect_eat_everything=False) -> tuple[FilterMember, int]:
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

    def excrete(self, item, general):
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

    def regurgitate(self, parenthesize: bool = True):
        if parenthesize:
            yield min(Positive.LPAREN)

        yield from self.value.regurgitate()
        yield from (tok for jable in self.joinables for tok in jable.regurgitate())

        if parenthesize:
            yield min(Positive.RPAREN)

# Some classes, such as this one, don't need to be instantiated. Eating a "Value" directly returns what its "child" would be.
class Value:
    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[FilterMember, int]:
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
    def eat(cls, tokens: list[str], at: int) -> tuple[FilterMember, int]:
        # Only raise parenthesis errors if we have reason to believe this was meant to be a parenthesis expression.
        if at < len(tokens) and tokens[at] in cls.LPAREN:
            pipeline, until = Pipeline.eat(tokens, at + 1)
            
            if until >= len(tokens):
                raise EinGafrurError('expected matching right parenthesis, but reached the end of input.', tokens=tokens, error_indices=at)

            if tokens[until] not in cls.RPAREN:
                raise EinGafrurError(f"expected matching right parenthesis, but got: '{tokens[until]}'.", tokens=tokens, error_indices=[at, until])

            return pipeline, until + 1

        return Predicate.eat(tokens, at)

class Negative(FilterMember):
    NEGATE = {'!', '-n', '-not'}

    def __init__(self, positive):
        self.positive = positive

    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[FilterMember, int]:
        if at >= len(tokens):
            raise EinGafrurError("expected 'not' symbol, but reached the end of input.", is_terminal=False, tokens=tokens)

        if tokens[at] not in cls.NEGATE:
            raise EinGafrurError(f"expected 'not' symbol, but got: '{tokens[at]}'.", is_terminal=False, tokens=tokens, error_indices=at)

        positive, until = Positive.eat(tokens, at + 1)
        return cls(positive), until

    def excrete(self, item, general):
        return not self.positive.excrete(item, general)

    def regurgitate(self):
        yield min(self.NEGATE)
        yield from self.positive.regurgitate()

class Joinable(FilterMember):
    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[FilterMember, int]:
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
    def eat(cls, tokens: list[str], at: int) -> tuple[FilterMember, int]:
        if at >= len(tokens):
            raise EinGafrurError("expected 'and' symbol, but reached the end of input.", is_terminal=False, tokens=tokens)

        if tokens[at] not in cls.CONJOIN:
            raise EinGafrurError(f"expected 'and' symbol, but got: '{tokens[at]}'.", is_terminal=False, tokens=tokens, error_indices=at)

        # There is no need to return a Coinjoined object because conjoining is the default behavior when boolean operators are omitted.
        return Value.eat(tokens, at + 1)

class Disjoined(FilterMember):
    DISJOIN = {'|', '-o', '-or'}

    def __init__(self, value):
        self.value = value

    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[FilterMember, int]:
        if at >= len(tokens):
            raise EinGafrurError("expected 'or' symbol, but reached the end of input.", is_terminal=False, tokens=tokens)

        if tokens[at] not in cls.DISJOIN:
            raise EinGafrurError(f"expected 'or' symbol, but got: '{tokens[at]}'.", is_terminal=False, tokens=tokens, error_indices=at)

        value, until = Value.eat(tokens, at + 1)
        return cls(value), until

    def excrete(self, item, general):
        return self.value.excrete(item, general)

    def regurgitate(self):
        yield min(self.DISJOIN)
        yield from self.value.regurgitate()

class Predicate(FilterMember):
    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[FilterMember, int]:
        if at >= len(tokens):
            raise EinGafrurError('expected a predicate name, but reached the end of input.', tokens=tokens)

        name = tokens[at]

        # Instead of going predicate by predicate and checking for EinGafrurError,
        # it's more optimal to pick the only possibly right predicate from a dictionary,
        # and eat the name token right here and let the predicate eat its arguments alone.
        if name not in PREDICATES:
            if name in Positive.RPAREN:
                raise EinGafrurError('right parenthesis has no matching left parenthesis.', tokens=tokens, error_indices=at)
                
            close_matches = difflib.get_close_matches(name, PREDICATES.keys())
            suggestions = f' (did you mean: {", ".join(close_matches)}?)' if len(close_matches) > 0 else ''
            raise EinGafrurError(f"expected valid predicate name, but got: '{name}'{suggestions}.", tokens=tokens, error_indices=at)

        return PREDICATES[name].eat(tokens, at + 1)

    @classmethod
    @abc.abstractmethod
    def predicate_name(cls):
        pass

class TruePredicate(Predicate):
    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[FilterMember, int]:
        return cls(), at

    @classmethod
    def predicate_name(cls):
        return '-true'

    def excrete(self, item, general):
        return True

    def regurgitate(self):
        yield self.predicate_name()

class FalsePredicate(Predicate):
    @classmethod
    def eat(cls, tokens: list[str], at: int) -> tuple[FilterMember, int]:
        return cls(), at

    @classmethod
    def predicate_name(cls):
        return '-false'

    def excrete(self, item, general):
        return False

    def regurgitate(self):
        yield self.predicate_name()

class MoviePredicate(Predicate):
    pass
        
class PersonPredicate(Predicate):
    pass

class RolePredicate(Predicate):
    pass

# TODO: think about how to make this support custom extensions.
PREDICATES = {cls.predicate_name(): cls for cls in [TruePredicate, FalsePredicate]}

# Named this way to avoid shadowing the builtin compile.
def compile_filter(tokens):
    return Filter.eat(tokens)

def decompile_filter(_filter):
    return list(_filter.regurgitate())

def test_compile(line):
    import shlex
    tokens = shlex.split(line)

    try:
        filtr = compile(tokens)
        regurg = ' '.join(EinGafrurError.format_token(t) for t in filtr.regurgitate())
        print(line, '->', regurg)
    except EinGafrurError as e:
        print(e)

def is_filter_member(s: str) -> bool:
    return (s.startswith('-')
            or s in Negative.NEGATE
            or s in Disjoined.DISJOIN
            or s in Conjoined.CONJOIN
            or s in Positive.LPAREN
            or s in Positive.RPAREN)

# test_compile('')
# test_compile('-true')
# test_compile('-true -true -false')
# test_compile('-true -o ( -false ) )')
# test_compile('-ftrual | -tue\\" -o ( -false )')
# test_compile('( ( -true | -true ) ) ! -false')
# test_compile('( -true " "')
