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

import re
import os
import glob
import time
import types
import typing
import shutil
import unicodedata
import importlib.util
import colorama

class ProgressBar[T]:
    MAX_DESC = 30
    MAX_SUFFIX = 40
    FRAC_FMT = '({} / {})'

    def __init__(self, elements: list[T], desc: None | str = None, keyfunc: None | typing.Callable[[T], str] = None) -> None:
        self._elements = elements
        self._num_of = len(self._elements)

        self._desc = (f'{desc}: ' if desc is not None else '').ljust(self.MAX_DESC)
        self._keyfunc = keyfunc if keyfunc is not None else lambda elem: ''

        # Type checker needs this hint.
        self._iterator: None | typing.Iterator[tuple[int, T]] = None
        self._is_done = True

        # The progress fraction's size is fixed to the maximal length it may reach, which is when it's num_of / num_of.
        self._max_frac_len = len(self.FRAC_FMT.format(self._num_of, self._num_of))

        # Of the bar's components, the description and suffix are fixed-size, and the fraction's size is a little flexible but we already took care of it.
        # The most flexible part is the bar itself, which is computed to take up all the space the others haven't.
        self._bar_width = 0
        empty_bar = self._build_bar(0, None)
        self._bar_width = max(shutil.get_terminal_size().columns - len(empty_bar), 0) # os.get_terminal_size fails if output is not a tty.

    def _build_bar(self, idx: int, elem: None | T) -> str:
        fill_amt = int((float(idx) / float(self._num_of)) * self._bar_width) if idx != self._num_of else self._bar_width
        fill_str = (fill_amt * '#').ljust(self._bar_width)
        frac_str = self.FRAC_FMT.format(idx, self._num_of).ljust(self._max_frac_len)
        suff_str = (truncate(self._keyfunc(elem), self.MAX_SUFFIX) if elem is not None else '').ljust(self.MAX_SUFFIX)
        return f'{self._desc} [{fill_str}] {frac_str} {suff_str}'
    
    def _repaint(self, idx: int, elem: None | T) -> None:
        print(self._build_bar(idx, elem), end='\r')

    def __iter__(self) -> typing.Iterator[T]:
        self._iterator = iter(enumerate(self._elements))
        self._is_done = False
        return self

    def __next__(self) -> T:
        assert self._iterator is not None

        try:
            idx, elem = next(self._iterator)
            self._repaint(idx, elem)
        except StopIteration:
            self._is_done = True
            raise

        return elem

    def __enter__(self) -> typing.Self:
        return self

    def __exit__(self, exc_type: type[BaseException], exc_value: None | BaseException, traceback: None | types.TracebackType) -> None:
        if self._iterator is None:
            return

        # This variable is needed because if we just checked if__next__ raises StopIteration, we fail the edge case where we break on the last element.
        if self._is_done:
            self._repaint(self._num_of, None)

        print()

class Timeout:
    def __init__(self, timeout_secs: float = float('inf')) -> None:
        self._timeout_secs = timeout_secs
        self._enter_time = float('nan')

    def tick(self) -> None:
        if time.time() - self._enter_time > self._timeout_secs:
            raise TimeoutError(f"Operation timed out after {self._timeout_secs} seconds.")

    def __enter__(self) -> typing.Self:
        self._enter_time = time.time()
        return self

    def __exit__(self, exc_type: type[BaseException], exc_value: None | BaseException, traceback: None | types.TracebackType) -> None:
        self._enter_time = float('nan')

def truncate(s: str, max_len: int, ellipsis: str = '...', is_big_endian: bool = True) -> str:
    if max_len < len(ellipsis):
        raise ValueError(f'Ellipsis must not be longer than max_len. {ellipsis=}, {max_len=}.')

    return (s if len(s) <= max_len
        else s[:max_len - len(ellipsis)] + ellipsis if is_big_endian
        else ellipsis + s[-(max_len - len(ellipsis)):])

def subclasses_recursive(cls: type) -> set[type]:
    classes = set(cls.__subclasses__())
    return classes.union(sc for c in classes for sc in subclasses_recursive(c))

def download_file_using_browser(download_cmd: typing.Callable[[], typing.Any], file_extension: str, downloads_dir: str, timeout_secs: float = float('inf')) -> str:
    # We do a little closures.
    def get_latest_in_downloads() -> None | str:
        files_in_dowloads = glob.glob(os.path.join(downloads_dir, f'*.{file_extension}'))
        latest_file = max(files_in_dowloads, key=os.path.getctime, default=None)
        return latest_file

    with Timeout(timeout_secs) as timeout:
        latest_file_before = get_latest_in_downloads()
        download_cmd()

        # We hit a URL in the browser that should download a CSV. Now we'll monitor the downloads directory until the latest CSV there is different than what it was before.
        # When that happens, we will have the CSV that was downloaded.
        while (latest_file := get_latest_in_downloads()) == latest_file_before or latest_file is None:
            time.sleep(0.5) # Sleep between ticks otherwise the computer goes into turbo mode busy-waiting.
            timeout.tick()

        # When the file is created it's sometimes empty for a bit. At some point it jumps to being fully written, without any inbetween.
        # So this waits for the file size to not be zero.
        while True:
            # This sleep is meant to alleviate a problem that is way too much to explain so just see my question about it on StackOverflow:
            # https://stackoverflow.com/questions/78300917/checking-the-size-of-a-file-thats-being-downloaded-by-the-browser-causes-it-to
            time.sleep(1)

            if os.path.getsize(latest_file) != 0:
                break

            try:
                time.sleep(0.2)
                timeout.tick()
            except TimeoutError:
                # For the same reason as the sleep above, we do a trick: we'll check if a different file with a similar name has appeared, and return it.
                latest_file_last_minute = get_latest_in_downloads()

                if (latest_file_last_minute is not None
                        and latest_file_last_minute != latest_file
                        and latest_file.removesuffix(f'.{file_extension}') in latest_file_last_minute
                        and os.path.getsize(latest_file_last_minute) != 0):
                    os.remove(latest_file)
                    latest_file = latest_file_last_minute
                    break

                raise

    return latest_file

# Thanks to this guy: https://stackoverflow.com/a/295466/12553917.
# Converts a string into a valid filename (meant for URLs but whatever).
def slugify(value: str) -> str:
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s.-]', '', value.lower())
    return re.sub(r'[-\s]+', '-', value).strip('-_')

def import_file(file: str) -> types.ModuleType:
    module_name = os.path.splitext(os.path.basename(file))[0]
    spec = importlib.util.spec_from_file_location(module_name, file)

    if spec is None:
        raise ModuleNotFoundError(f"No module in path '{file}'")

    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# Courtesy of https://stackoverflow.com/a/59109706/12553917.
_tree_space =  '    '
_tree_branch = '│   '
_tree_tee =    '├── '
_tree_last =   '└── '

def tree(dir_path: str, prefix: str = '', stats: None | typing.Callable[[str], str] = None) -> typing.Iterator[str]:
    contents = os.listdir(dir_path)
    
    # contents each get pointers that are ├── with a final └──
    pointers = [_tree_tee] * (len(contents) - 1) + [_tree_last]

    for pointer, basename in zip(pointers, contents):
        path = os.path.join(dir_path, basename)

        if os.path.isfile(path) and stats is not None:
            yield prefix + pointer + basename + stats(path)
        else:
            yield prefix + pointer + basename

        # Extend the prefix and recurse.
        if os.path.isdir(path):
            extension = _tree_branch if pointer == _tree_tee else _tree_space

            # i.e. space because last, └── , above so no more |
            yield from tree(path, prefix=prefix + extension, stats=stats)

def tabulate(
        records: list[list[str]],
        fillchar: str = ' ',
        use_color: bool = True,
        header_color: str = '', 
        fill_color: str = colorama.Fore.BLACK + colorama.Style.BRIGHT,
        column_colors: None | list[str] = None) -> typing.Iterable[str]:

    # Do default value like this to avoid "dangerous default" warning by pylint.
    if column_colors is None:
        column_colors = [
            colorama.Fore.WHITE,
            colorama.Fore.GREEN + colorama.Style.BRIGHT,
            colorama.Fore.YELLOW,
            colorama.Fore.BLUE + colorama.Style.BRIGHT,
            colorama.Fore.RED + colorama.Style.BRIGHT,
            colorama.Fore.MAGENTA + colorama.Style.BRIGHT,
            colorama.Fore.CYAN + colorama.Style.BRIGHT,
            colorama.Fore.YELLOW + colorama.Style.BRIGHT,
        ]

    if len(fillchar) != 1:
        raise ValueError(f"Invalid fillchar: '{fillchar}': must be a single character.")

    # We need the max length of each column for alignment. +2 so that there's always enough spacing between columns.
    ncolumns = len(records[0])
    maxlens = [2 + max(len(record[col]) for record in records) for col in range(ncolumns)]

    # Setting it up so that the code following can be the same regardless of color usage.
    if use_color:
        reset = colorama.Style.RESET_ALL
    else:
        column_colors = ['']
        fill_color = ''
        header_color = ''
        reset = ''

    # Yield all the rows, with alignment and color!
    for record in records:
        yield ''.join(
            f'{column_colors[col % len(column_colors)]}{header_color}{entry}{reset}{fill_color}{(maxlens[col] - len(entry)) * fillchar}{reset}'
            for col, entry in enumerate(record)
        )

        # Get rid of this after the first row.
        header_color = ''

_magnitudes = ['', 'K', 'M', 'B', 'T']

def num_pretty(num: int | float, abbreviate: bool = True) -> str:
    if abbreviate:
        # I graciously thank this StackOverflow user https://stackoverflow.com/a/45846841/12553917.
        num = float(f'{num:.3g}')
        magnitude = 0

        while abs(num) >= 1000 and magnitude + 1 < len(_magnitudes):
            magnitude += 1
            num /= 1000

        num_str = f'{num:,f}'.rstrip('0').rstrip('.')
        return num_str + _magnitudes[magnitude]
    else:
        return f'{num:,}'
        