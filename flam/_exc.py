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
import colorama

from . import _dbg

class FlamError(Exception):
    def __init__(self, *args: object, log_trace: bool = True, stacklevel: int = 2) -> None:
        super().__init__(*args)

        # Use stacklevel=2 at least so that the file:function:lineno is from where the exception was raised and not here.
        # If the child class implements its own __init__, it must pass a higher stacklevel.
        _dbg.logger.error(f"Raised exception: {self}", stacklevel=stacklevel, stack_info=log_trace)

class InputError(FlamError):
    pass

class FilterSyntaxError(InputError):
    def __init__(self, message: str, tokens: list[str], error_indices: int | typing.Iterable[int] = -1, is_terminal: bool = True) -> None:
        super().__init__(f'FILTER syntax error{'' if is_terminal else ' (not terminal)'}: {message}\nIn: {self.join_tokens(tokens, error_indices)}',
            log_trace=is_terminal, stacklevel=3)

        # This is for exceptions that only mean we guessed wrong on which type of expression the tokens are, and we should try different options.
        # For exceptions which are terminal, if they are raised then we know there is no reason to check if the tokens match a different expression,
        # so we should propagate that exception to get the most meaningful error message.
        # Invariant: I don't want to think about the possibility of a nonterminal message propagated from the deep.
        # Anyone who calls a function which raises nonterminal exceptions, should handle them directly.
        self.is_terminal = is_terminal

    # shlex.join wouldn't allow us to color the quotes around error tokens that need quoting, so we need a custom solution.
    @classmethod
    def join_tokens(cls, tokens: list[str], error_indices: int | typing.Iterable[int]) -> str:
        error_indices_set = (set(error_indices) if not isinstance(error_indices, int)
            else set() if error_indices == -1
            else {error_indices})
        return ' '.join(cls.format_token(t, i in error_indices_set) for i, t in enumerate(tokens))

    @classmethod
    def format_token(cls, token: str, is_error: bool = False) -> str:
        # shlex.quote will quote tokens like (, &, etc., and also create a horrible mess of backslashes if the token contains single/double quotation marks.
        # We don't need output that can be safely fed into a shell, only output that is readable. So we go with much simpler rules for when/how to quote.
        quoted = f"'{token}'" if any(c.isspace() for c in token) else token
        colorized = f'{colorama.Fore.RED}{quoted}{colorama.Fore.RESET}' if is_error else quoted
        return colorized

class FetchInterrupt(FlamError):
    pass

class FileValidationError(FlamError):
    pass
