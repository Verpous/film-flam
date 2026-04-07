#! python

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

import argparse
import enum
import os
import sys
import typing
import colorama
import contextlib
import csv
import tempfile
import subprocess
import shutil
import functools
import re
import glob
import fnmatch
import time
import itertools

# Unlike all other modules in this package, this one pretends it's from outside the package and simply "imports flam".
import flam
from flam import utils

_start_import_time = time.time()

class Choice(enum.StrEnum):
    YES     = 'yes'
    NO      = 'no'
    ALWAYS  = 'always'
    NEVER   = 'never'
    AUTO    = 'auto'

    @classmethod
    def always_auto_never(cls) -> typing.Iterable[Choice]:
        return (cls.ALWAYS, cls.AUTO, cls.NEVER)

    @classmethod
    def yes_no_auto(cls) -> typing.Iterable[Choice]:
        return (cls.YES, cls.NO, cls.AUTO)

    @classmethod
    def bool2yesno(cls, value: bool) -> Choice:
        return cls.YES if value else cls.NO

    @classmethod
    def bool2alwaysnever(cls, value: bool) -> Choice:
        return cls.ALWAYS if value else cls.NEVER

    # When you give argparse choices and they don't match it prints the error using repr so repr must be user readable.
    def __repr__(self) -> str:
        return str(self)

def split_at_filter(strs: list[str]) -> tuple[list[str], list[str]]:
    filter_begin = next((i for i, s in enumerate(strs) if flam.looks_like_filter_token(s)), len(strs))
    return strs[:filter_begin], strs[filter_begin:]

def print_table(table: list[list[str]],
        color_choice: Choice = Choice.AUTO,
        paginate_choice: Choice = Choice.AUTO,
        spacious: bool = False,
        no_titles: bool = False,
        dsv: None | str = None) -> None:
    match color_choice:
        case Choice.AUTO:
            use_color = sys.stdout.isatty()
        case Choice.ALWAYS:
            use_color = True
        case Choice.NEVER:
            use_color = False
        case _:
            raise RuntimeError(f"Unexpected {color_choice=}")

    match paginate_choice:
        case Choice.AUTO:
            HORIZONTAL_PAGINATION_ENCOURAGEMENT = 7
            VERTICAL_PAGINATION_ENCOURAGEMENT = 2
            terminal_cols, terminal_lines = shutil.get_terminal_size()

            # Auto pagination is a function of a few things. The most complicated part is checking if the table fits in the terminal.
            # Checking if it fits vertically is rather simple, but we do nudge it a bit to encourage pagination if it barely fits.
            # Checking if it fits horizontally is more complicated.
            # It's too complicated to compute exactly the length of the longest row before we generate the table, but we can't generate the table until we decide about pagination.
            # So instead we go with a heuristical approach of estimating the longest row to be the sum of its parts + some encouragement for each cell.
            paginate = (
                sys.stdout.isatty()
                and shutil.which('less') is not None
                and (
                    terminal_lines <= len(table) + VERTICAL_PAGINATION_ENCOURAGEMENT
                    or terminal_cols < max(sum(HORIZONTAL_PAGINATION_ENCOURAGEMENT + len(cell) for cell in row) for row in table)
                )
            )
            spacious |= paginate
        case Choice.ALWAYS:
            paginate = True
        case Choice.NEVER:
            paginate = False
        case _:
            raise RuntimeError(f"Unexpected {paginate_choice=}")

    # Pipe to less if requested. I tried a lot of variations including of course Popen(stdin=PIPE), this is the only one that works.
    # Note: This program hits a harmless 'OSError [Errno 22]' when piping to less.
    # This fixes it: https://stackoverflow.com/a/66874837/12553917, but I'm worried about the consequences of using this and it's not worth the hassle.
    with tempfile.NamedTemporaryFile('w', encoding='utf-8') if paginate else contextlib.nullcontext(sys.stdout) as out: # type: ignore
        # Output as CSV.
        if dsv is not None:
            writer = csv.writer(out, delimiter=dsv)
            writer.writerows(table)
        else:
            # Output in a pretty table.
            line_spacing = '\n\n' if spacious else '\n'
            out.write(line_spacing.join(utils.tabulate(
                table,
                fillchar = '.' if use_color else ' ',
                use_color = use_color,
                header_color = '' if no_titles else '\033[4m\033[K' # Underline, not supported by colorama.
            )))
            out.write('\n')
        
        # NOTE: considered once the file is written to also write it to the logs. But I don't think there's a need - if users have an issue they will show me what was printed.
        out.flush()

        if paginate:
            try:
                subprocess.call(['less', '-RS', out.name])
            except Exception as e:
                raise flam.InputError(f"Pagination failed with error: {e}. You probably don't have less installed.") from e

class SubcommandConfig:
    @classmethod
    def add_subparser(cls, subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
        parser = subparsers.add_parser(
            'config',
            formatter_class=argparse.RawTextHelpFormatter,
            description = (
'''View and modify the flam configuration. There are a few subcommands:

    list        Configure "simple" lists which are fetched from the web.
    composite   Configure "composite" lists which are remixes of your existing lists
    extension   Configure files to be imported containing your own custom attributes, predicates, and fetch sources
'''),
        )

        config_subparsers = parser.add_subparsers(required=True)
        SubcommandConfigList.add_subparser(config_subparsers)
        SubcommandConfigComposite.add_subparser(config_subparsers)
        SubcommandConfigExtension.add_subparser(config_subparsers)
        return parser

class SubcommandConfigExtension:
    @classmethod
    def add_subparser(cls, subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
        parser = subparsers.add_parser(
            'extension',
            formatter_class=argparse.RawTextHelpFormatter,
            description = (
'''View, add, or remove custom extension files. There are various things you can extend:

    Attributes      Values belonging to movies, people, or roles
    Predicates      Tests which can be used to filter movies, people, or roles
    Fetchers        Support for downloading movie lists from some specific website or API

Extensions are simply python scripts which implement and register these custom things.
See the full documentation for how to implement extensions.
'''),
            epilog = (
'''Examples:
    %(prog)s ~/my_extension.py
        (Register the extensions file ~/my_extension.py)
    %(prog)s
        (Print all extensions)
    %(prog)s --delete ~/my_extension.py
        (Delete the extension file ~/my_extension.py)
'''),
        )

        parser.set_defaults(function=cls.execute)

        action_group = parser.add_mutually_exclusive_group(required=False)
        action_group.add_argument('-A', '--add', action='store_true', help='Add IMPORT as an extension. The default if IMPORT is provided.')
        action_group.add_argument('-D', '--delete', action='store_true', help='Delete IMPORT from extensions.')
        action_group.add_argument('-P', '--print', action='store_true', help='Print all extensions. The default if IMPORT is not provided.')

        parser.add_argument('IMPORT', action='store', nargs='?', help='Specify which module or file to import. This can be a full path to a script or a module name if it is in PATH.')
        return parser

    @classmethod
    def execute(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        if args.delete:
            cls.delete(ctx, args)
        # Default to print only if no args.
        elif args.print or (not args.add and args.IMPORT is None):
            cls.print(ctx, args)
        # Default add.
        else:
            cls.add(ctx, args)

    @classmethod
    def delete(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        if args.IMPORT is None:
            raise flam.InputError("Must specify a IMPORT to delete an extension.")

        with ctx.configure() as cfg:
            try:
                cfg.extensions.remove(args.IMPORT)
            except ValueError as e:
                raise flam.InputError(f"No extension named '{args.IMPORT}'.") from e

    @classmethod
    def print(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None: # pylint: disable=unused-argument
        table = [['module / script']]
        table.extend(sorted([e] for e in ctx.cfg_readonly.extensions))
        print_table(table)

    @classmethod
    def add(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        if args.IMPORT is None:
            raise flam.InputError("Must specify a IMPORT to add an extension.")

        with ctx.configure() as cfg:
            cfg.extensions.append(args.IMPORT)

class SubcommandConfigList:
    @classmethod
    def add_subparser(cls, subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
        parser = subparsers.add_parser(
            'list',
            formatter_class=argparse.RawTextHelpFormatter,
            description = (
'''View, add, edit, or remove "simple" lists. These are lists which are directly copied from some external source like an IMDb list.
Once configured, lists can be easily used by their name in other commands like `flam fetch`, `flam find`.
'''),
            epilog = (
'''Examples:
    %(prog)s mylist imdb-browser-apidev-listid=083886771
        (Create a list 'mylist'. It's a local copy of the IMDb list '083886771' - https://www.imdb.com/list/ls083886771/. It's downloaded via the browser+imdbapi.dev)
    %(prog)s mylist --default-fetch=yes --default-find=yes
        (Modify 'mylist' to be default for fetch and find, so if you run `flam fetch` or `flam find` with no arguments they will use this list)
    %(prog)s
        (Print all lists)
    %(prog)s --rename ourlist mylist
        (Rename 'mylist' to 'ourlist')
    %(prog)s --delete ourlist
        (Delete 'ourlist')
'''),
        )

        parser.set_defaults(function=cls.execute)

        action_group = parser.add_mutually_exclusive_group(required=False)
        action_group.add_argument('-E', '--edit', action='store_true', help='Edit or create the list NAME. The default if NAME is provided.')
        action_group.add_argument('-D', '--delete', action='store_true', help='Delete the list named NAME.')
        action_group.add_argument('-P', '--print', action='store_true', help='Print the list NAME, or if NAME not provided, print all lists. The default if NAME is not provided.')

        parser.add_argument('-n', '--rename', metavar='NEW_NAME', default=None, action='store', help='In --edit, rename the list to %(metavar)s.')
        parser.add_argument('-i', '--default-find', choices=Choice.yes_no_auto(), default=Choice.AUTO, action='store', help='In --edit, decide if the list should be default for `flam find`.')
        parser.add_argument('-e', '--default-fetch', choices=Choice.yes_no_auto(), default=Choice.AUTO, action='store', help='In --edit, decide if the list should be default for `flam fetch`.')
        parser.add_argument('NAME', action='store', nargs='?', default=None, help='Operate on the list named %(dest)s.')
        parser.add_argument('LISTDEF', action='store', nargs='?', default=None, help=
'''In --edit, set the list type and address to %(dest)s.
%(dest)ss have the form <list type>=<address>, where the list type is some supported way of downloading list information, and the address indicates the exact list to download.
See the full documentation for a list of supported list types. Below is one recommended example for IMDb lists:
    imdb-browser-apidev-listid      Takes an IMDb list ID and downloads it by opening the list in the browser and exporting to CSV, then filling in information with https://imdbapi.dev
''')
        return parser

    @classmethod
    def execute(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        if args.delete:
            cls.delete(ctx, args)
        # Default to print only if no args.
        elif args.print or (not args.edit and args.NAME is None):
            cls.print(ctx, args)
        # Default edit/create.
        else:
            try:
                ctx.cfg_readonly.simple_lists.get_by_name(args.NAME)
            except flam.InputError:
                cls.create(ctx, args)
            else:
                cls.edit(ctx, args)

    @classmethod
    def delete(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        if args.NAME is None:
            raise flam.InputError("Must specify a NAME to delete a list.")

        with ctx.configure() as cfg:
            del cfg.simple_lists_raw[cfg.simple_lists.get_idx_by_name(args.NAME)]

    @classmethod
    def print(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        simple_lists = list(ctx.cfg_readonly.simple_lists) if args.NAME is None else [ctx.cfg_readonly.simple_lists.get_by_name(args.NAME)]

        table = [['uid', 'name', 'type', 'address', 'default-fetch?', 'default-find?']]
        table.extend(sorted(
            [
                sl.uid.split('-')[0],
                sl.name,
                sl.concrete_listdef.list_type,
                sl.concrete_listdef.address,
                Choice.bool2yesno(sl.is_default_fetch),
                Choice.bool2yesno(sl.is_default_find),
            ]
            for sl in simple_lists
        ))

        print_table(table)

    @classmethod
    def edit(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        with ctx.configure() as cfg:
            # We trust that this succeeds because otherwise this function wouldn't be called.
            simple_list = cfg.simple_lists.get_by_name(args.NAME)

            if args.rename is not None:
                simple_list.name = args.rename

            if args.LISTDEF is not None:
                cldef = flam.CanonListdef.parse(args.LISTDEF, ctx)
                simple_list.concrete_listdef = cldef

            if args.default_fetch != Choice.AUTO:
                simple_list.is_default_fetch = args.default_fetch == Choice.YES

            if args.default_find != Choice.AUTO:
                simple_list.is_default_find = args.default_find == Choice.YES

    @classmethod
    def create(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        if args.NAME is None:
            raise flam.InputError("Must specify a NAME to create or edit a list.")

        if args.LISTDEF is None:
            raise flam.InputError(f"List '{args.NAME}' doesn't exist, so LISTDEF is required.")

        cldef = flam.CanonListdef.parse(args.LISTDEF, ctx)

        simple_list = flam.SimpleList(
            uid = 'INITIALIZED LATER',
            name = args.NAME,
            concrete_listdef = cldef,
            is_default_fetch = args.default_fetch != Choice.NO,
            is_default_find = args.default_find == Choice.YES,
        )

        with ctx.configure() as cfg:
            cfg.simple_lists_raw.append(simple_list)

class SubcommandConfigComposite:
    @classmethod
    def add_subparser(cls, subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
        parser = subparsers.add_parser(
            'composite',
            formatter_class=argparse.RawTextHelpFormatter,
            description = (
'''View, add, edit, or remove "composite" lists. These are remixes of your simple lists which can combine multiple lists together and also filter them.
Once configured, composite lists can be easily used by their name in other commands like `flam fetch`, `flam find`.
'''),
            epilog = (
'''Examples:
    %(prog)s rated mylist -has my-rating
        (Create a composite list 'rated'. It's got every movie in the simple list 'mylist' which has been rated by you)
    %(prog)s owned dvds blurays
        (Create a composite list 'owned'. It's got every movie from both simple lists 'dvds' and 'blurays')
    %(prog)s
        (Print all composite lists)
    %(prog)s --delete rated
        (Delete 'rated')
'''),
        )

        parser.set_defaults(function=cls.execute)

        action_group = parser.add_mutually_exclusive_group(required=False)
        action_group.add_argument('-E', '--edit', action='store_true', help='Edit or create the composite list NAME. The default if NAME is provided.')
        action_group.add_argument('-D', '--delete', action='store_true', help='Delete the composite list named NAME.')
        action_group.add_argument('-P', '--print', action='store_true', help='Print the composite list NAME, or if NAME not provided, print all lists. The default if NAME is not provided.')

        parser.add_argument('-n', '--rename', metavar='NEW_NAME', default=None, action='store', help='In --edit, rename the list to %(metavar)s.')
        parser.add_argument('-i', '--default-find', choices=Choice.yes_no_auto(), default=Choice.AUTO, action='store', help='In --edit, decide if the list should be default for `flam find`.')
        parser.add_argument('-e', '--default-fetch', choices=Choice.yes_no_auto(), default=Choice.AUTO, action='store', help='In --edit, decide if the list should be default for `flam fetch`.')
        parser.add_argument('NAME', nargs='?', action='store', default=None, help='Operate on the composite list named %(dest)s.')
        parser.add_argument('SIMPLE_LIST', nargs='*', action='store', help='In --edit, merge %(dest)ss to form this composite list.')
        parser.add_argument('MOVIE_FILTER', nargs='*', action='store', help=
'''In --edit, apply %(dest)s on the merged SIMPLE_LISTs to form this composite list.
See the full documentation for filter syntax.''')

        # argparse.REMAINDER is an undocumented but very important feature.
        # Basically it's the only way to make positional arguments that start with dashes not be treated as bad options.
        parser.add_argument('REMAINDER', nargs=argparse.REMAINDER, action='store', help=argparse.SUPPRESS)
        return parser

    @classmethod
    def execute(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        if args.delete:
            cls.delete(ctx, args)
        # Default to print only if no args.
        elif args.print or (not args.edit and args.NAME is None):
            cls.print(ctx, args)
        # Default edit/create.
        else:
            try:
                ctx.cfg_readonly.composite_lists.get_by_name(args.NAME)
            except flam.InputError:
                cls.create(ctx, args)
            else:
                cls.edit(ctx, args)

    @classmethod
    def delete(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        if args.NAME is None:
            raise flam.InputError("Must specify a NAME to delete a composite list.")

        with ctx.configure() as cfg:
            del cfg.composite_lists_raw[cfg.composite_lists.get_idx_by_name(args.NAME)]

    @classmethod
    def print(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        composite_lists = list(ctx.cfg_readonly.composite_lists) if args.NAME is None else [ctx.cfg_readonly.composite_lists.get_by_name(args.NAME)]

        table = [['uid', 'name', 'lists', 'filter', 'default-fetch?', 'default-find?']]
        table.extend(sorted(
            [
                cl.uid.split('-')[0],
                cl.name,
                ', '.join(ctx.cfg_readonly.simple_lists.get_by_uid(sl_uid).name for sl_uid in cl.simple_list_uids),
                ' '.join(cl.filter_tokens) if len(cl.filter_tokens) > 0 else '-',
                Choice.bool2yesno(cl.is_default_fetch),
                Choice.bool2yesno(cl.is_default_find),
            ]
            for cl in composite_lists
        ))

        print_table(table)

    @classmethod
    def edit(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        with ctx.configure() as cfg:
            composite_list = cfg.composite_lists.get_by_name(args.NAME)

            if args.rename is not None:
                composite_list.name = args.rename

            simple_list_names, filter_tokens = split_at_filter(args.SIMPLE_LIST + args.MOVIE_FILTER)

            if len(simple_list_names) > 0:
                composite_list.simple_list_uids = [ctx.cfg_readonly.simple_lists.get_by_name(sl_name).uid for sl_name in simple_list_names]

            if len(filter_tokens) > 0:
                # Don't have anything to do with this for now, but we can raise an exception if it doesn't compile.
                ctx.compile_filter(filter_tokens, flam.FindableType.MOVIES)
                composite_list.filter_tokens = filter_tokens

            if args.default_fetch != Choice.AUTO:
                composite_list.is_default_fetch = args.default_fetch == Choice.YES

            if args.default_find != Choice.AUTO:
                composite_list.is_default_find = args.default_find == Choice.YES

    @classmethod
    def create(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        if args.NAME is None:
            raise flam.InputError("Must specify a NAME to create or edit a composite list.")

        simple_list_names, filter_tokens = split_at_filter(args.SIMPLE_LIST + args.MOVIE_FILTER)

        composite_list = flam.CompositeList(
            uid = 'INITIALIZED LATER',
            name = args.NAME,
            simple_list_uids = [ctx.cfg_readonly.simple_lists.get_by_name(sl_name).uid for sl_name in simple_list_names],
            filter_tokens = filter_tokens,
            is_default_fetch = args.default_fetch == Choice.YES,
            is_default_find = args.default_find == Choice.YES,
        )

        with ctx.configure() as cfg:
            cfg.composite_lists_raw.append(composite_list)

class SubcommandFetch:
    UNDO_HISTORY = 3

    @classmethod
    def add_subparser(cls, subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
        parser = subparsers.add_parser(
            'fetch',
            formatter_class=argparse.RawTextHelpFormatter,
            description = (
'''Download information about the movies in your movie lists. Lists must have been fetched at least once upon a time before you can use them.
You should rerun this once in a while if you've made changes in your movie lists to sync them locally.
'''),
            epilog = (
'''Examples:
    %(prog)s
        (Fetch all lists configured with --default-fetch)
    %(prog)s dvds blurays
        (Fetch the configured list "dvds" and "blurays")
    %(prog)s --undo
        (Undo the last fetch operation)
    %(prog)s --refetch 'bojack' shows
        (Refetch Bojack Horseman from the list "shows")
'''),
        )

        parser.set_defaults(function=cls.execute)
        
        parser.add_argument('-u', '--undo', action='store_true', help=
f'''Undo the previous fetch operation in its entirety. Note this will also restore configuration to the old state.
Fetch can be expensive so if something goes wrong and files get messed up this is good to have.
You can rerun this to undo up to the last {cls.UNDO_HISTORY} fetches.''')
        parser.add_argument('-r', '--refetch', metavar='PATTERN', default=None, action='store', help=
'''Forces titles that match %(metavar)s (case-insensitive regular expression) to be redownloaded even if they are already locally stored.
It's enough for %(metavar)s to match any part of the title, not necessarily the whole title.
This feature is intended for redownloading shows after a new season has come out.''')

        parser.add_argument('LISTDEF', nargs='*', action='store', help=
'''Which lists to fetch. There are a few supported forms (in order of priority):
1. "*" for fetching all configured lists
2. A configured list name (simple or composite) e.g. "mylist"
3. An explicit "abstract" %(dest)s: "list=<list name>" for simple lists, and "composite=<list name>" for composite lists.
4. An explicit "concrete" %(dest)s: "<list type>=<address>". See the full documentation for a list of supported types.

In the case of a composite list, will actually fetch the simple lists which it's composited from.
By default fetches all lists configured with --default-fetch.''')

        return parser

    @classmethod
    def execute(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        if args.undo:
            cls.pop_undo(ctx)
            return

        try:
            cls.push_undo(ctx)
        except Exception as e: # pylint: disable=broad-exception-caught
            # Sweep this one silently. Catch any exception type because we don't care too much if it fails.
            flam.logger.error(f"Failed to store state for later undoing with error: {e}")

        listdefs = args.LISTDEF if len(args.LISTDEF) != 0 else [flam.SpecialListType.DEFAULTS]
        ctx.fetch(listdefs, refetch_pattern=args.refetch, quiet=False)

        with utils.ProgressBar(list(ctx.cfg_readonly.composite_lists),
                desc='Regenerating composite lists',
                keyfunc=lambda cl: cl.name) as bar:
            for cl in bar:
                # Easiest way to regenerate dependencies is to just get every composite list and do nothing with it.
                try:
                    ctx.get_movie_list(f'{flam.SpecialListType.COMPOSITE}={cl.name}')
                except flam.FlamError:
                    # Don't care if this fails, and it might fail because we haven't checked if the composite list has all its dependencies.
                    pass

    @classmethod
    def push_undo(cls, ctx: flam.FlamContext) -> None:
        # TODO: Undo is trouble, because it's weird to operate on flam dir while it's in use,
        #       especially pop which needs to completely overwrite it while a context is using it. For now we just live with it.
        #       Maybe if we only backed up the movie_lists folder it will be better, because then we could tell the context to reset its cache,
        #       and everything should more or less work.
        slug = utils.slugify(ctx.flam_dir)
        backups = glob.glob(os.path.join(tempfile.gettempdir(), f'*_{slug}'))
        backups.sort(key=lambda d: os.path.basename(d).split('_')[0])

        while len(backups) >= cls.UNDO_HISTORY:
            flam.logger.info(f"Deleting old backup: {backups[0]}")
            shutil.rmtree(backups[0])
            del backups[0]

        new_backup = os.path.join(tempfile.gettempdir(), f'{int(time.time())}_{slug}')
        shutil.copytree(ctx.flam_dir, new_backup)
        flam.logger.info(f"Created restoration point: {new_backup} for {ctx.flam_dir=}")

    @classmethod
    def pop_undo(cls, ctx: flam.FlamContext) -> None:
        flam_dir = ctx.flam_dir

        slug = utils.slugify(flam_dir)
        backups = glob.glob(os.path.join(tempfile.gettempdir(), f'*_{slug}'))
        backups.sort(key=lambda d: os.path.basename(d).split('_')[0])

        if len(backups) == 0:
            raise flam.FlamError("Nothing to undo.")

        shutil.rmtree(flam_dir)
        shutil.move(backups[-1], flam_dir)
        flam.logger.info(f"Restored backup: {backups[-1]} to: {flam_dir=}")

class SubcommandFind:
    # Use qualified names for performance and to avoid ambiguity.
    DEFAULT_SORT_KEYS = {
        flam.FindableType.MOVIES: ['movies-release-year', 'movies-title', 'movies-runtime'],
        flam.FindableType.PEOPLE: ['people-crew-type', 'people-group-mode', 'people-num-movies', 'people-name'],

        # We think of roles as being a people search more than a movie search, so it's sort first by people, then by movie.
        flam.FindableType.ROLES: ['people-crew-type', 'people-group-mode', 'people-num-movies', 'people-name', 'movies-release-year', 'movies-title', 'movies-runtime'],
    }

    # The printed name will be abbreviated anyway so it's ok to use the qualified name.
    DEFAULT_COLUMN_KEYS = {
        flam.FindableType.MOVIES: ['movies-title', 'movies-runtime', 'movies-release-year', 'movies-rating', 'movies-metascore', 'movies-director'],
        flam.FindableType.PEOPLE: ['people-name', 'people-birth-year', 'people-height-cm', 'people-num-movies', 'people-avg-rating', 'people-avg-metascore'],
        flam.FindableType.ROLES: ['people-name', 'movies-title', 'people-num-movies', 'movies-release-year'],
    }

    @classmethod
    def add_subparser(cls, subparsers: None | argparse._SubParsersAction, main_parser: None | argparse.ArgumentParser) -> argparse.ArgumentParser:
        # Either add find as its own subparser or support its arguments in the main parser.
        if main_parser is not None:
            parser = main_parser
        else:
            assert subparsers is not None
            parser = subparsers.add_parser(
                'find',
                formatter_class=argparse.RawTextHelpFormatter,
                description = (
'''Explore "findables" (movies, people, or roles) in your movie lists, and query for specific ones which answer to some filter.
Found objects are printed in a nice table format, and you can customize what is printed and how it's sorted.'''),
                epilog = (
'''Examples:
    %(prog)s movies
        (Find movies in the default lists)
    %(prog)s cast shows -is-star true
        (Find starring roles in the list 'shows')
    %(prog)s --sort height director-people:separate,writer-people:separate -height +160 -height -180
        (Find directors and writers whose height is between 160 and 180 centimeters and sort them by their height)
    %(prog)s --columns +watch-date movies -metascore +70 -o -every-role [ writer director ] -gender female
        (Find movies with a metascore above 70 or which were written and directed by women, and print their watch date alongside default columns)
'''),
            )

        parser.set_defaults(function=cls.execute)

        # TODO: "--split" option to expand array attributes into a row for each one?
        parser.add_argument('-s', '--sort', metavar='ATTRIBUTES', default=None, action='store', help=
f'''Sort FINDABLEs according to %(metavar)s, which is a comma-delimited list of attributes to sort by, in decreasing priority.
Each findable type has its own default:
    movies      {','.join(k[k.find('-') + 1:] for k in cls.DEFAULT_SORT_KEYS[flam.FindableType.MOVIES])}
    people      {','.join(k[k.find('-') + 1:] for k in cls.DEFAULT_SORT_KEYS[flam.FindableType.PEOPLE])}
    roles       {','.join(k[k.find('-') + 1:] for k in cls.DEFAULT_SORT_KEYS[flam.FindableType.ROLES])}
See the full documentation for a list of supported attributes.''')
        
        parser.add_argument('-c', '--columns', metavar='ATTRIBUTES', default=None, action='store', help=
f'''Comma-delimited list of attributes of FINDABLE to print.
Each findable type has its own defaults. There are also "smart" defaults which are printed only if certain conditions are met.
If %(metavar)s starts with a '+' then they will be printed in addition to the defaults instead of instead.
Supports globbing (e.g. '*-date' for all date attributes).
See the full documentation for a list of supported attributes.''')

        parser.add_argument('-C', '--color', choices=Choice.always_auto_never(), default=Choice.AUTO, action='store', help=
            'Set whether columns should be colored. Defaults to %(default)s.')
        parser.add_argument('-d', '--dsv', metavar='DELIM', default=None, action='store', help=
            "Output in delimiter-separated values format (DSV). I.e. if DELIM is ',' then that is CSV format.")
        parser.add_argument('-v', '--verbose', default=False, action='store_true', help=
            'Use verbose output, where long strings are not truncated and some attributes may be printed in longer format.')
        parser.add_argument('-r', '--reverse', default=False, action='store_true', help=
            'Reverse the sort order. By default some sort keys are ascending and some descending based on what makes sense. This reverses those defaults.')
        parser.add_argument('-S', '--spacious', default=False, action='store_true', help=
            'Add an empty line between entries.')
        parser.add_argument('-P', '--paginate', choices=Choice.always_auto_never(), default=Choice.AUTO, action='store', help=
            'Choose whether to paginate with `less`. Defaults to %(default)s, which depends on the size of the output.')
        parser.add_argument('-t', '--no-titles', default=False, action='store_true', help=
            "Don't print a row with the column titles.")

        parser.add_argument('FINDABLE', type=cls.parse_findable, action='store', help=
f'''Choose what to find: movies, people, or roles.
Movies are simply the movies in the list.

People are the people were in the movies in the list. They can be searched per crew type (i.e. 'director', 'cast') or as 'any' crew type.

Roles are an appearance of a specific people in a specific film. Think "Cristoph Waltz in Inglorious Basterds". They can also be searched per crew type.
So when searching for roles, you will see an entry per person per movie.
Since roles combine a people and a movie, they accept any movie attribute, people attribute, and also their own role attributes.

Supported crew types: {', '.join(flam.CrewType)}

People and roles can be "grouped". Grouping simply combines some people together if they are known collaborators.
For example, if grouping is enabled then the Coen brothers will become a single "people" entry.
Each crew type has its own default grouping mode according to what makes sense, but you can override it

People and roles support limiting the search to a specific crew type and optionally also group mode, and support comma-delimited several types. Use 'crew' to catenate all types.
For roles, it looks like: 'cast', 'director:group', 'composer:separate,stuntcast', 'crew', etc.
For people, it looks like 'cast-people', 'director-people:group', etc.

''') # Empty trailing line because this is a lot of text and we gotta space it out.

        parser.add_argument('LISTDEF', nargs='*', action='store', help=
'''Which lists to search in. They must've been previously fetched. See `flam fetch --help` for information about supported forms.
By default searches in all lists configured with --default-find.

''')
        parser.add_argument('FILTER', nargs='*', action='store', help=
'''Search only for findables which pass %(metavar)s.
Filters can check the values of attributes and more. They support standard constructs like '-and', '-or', '-not' operators and parenthesized expressions.
See the full documentation for filter syntax.''')

        parser.add_argument('REMAINDER', nargs=argparse.REMAINDER, action='store', help=argparse.SUPPRESS)
        return parser

    @classmethod
    def parse_findable(cls, findable: str) -> tuple[flam.FindableType, list[tuple[flam.CrewType, flam.GroupMode]]]:
        if findable == '':
            raise ValueError("Cannot be empty string.")

        if findable == flam.FindableType.MOVIES:
            # Need to return a list of size 1 for execute to work even if its contents are irrelevant.
            return flam.FindableType(findable), [(flam.CrewType.ANY, flam.GroupMode.DEFAULT)]

        split = findable.split(',')
        sample_findable = None
        ct_gms: list[tuple[flam.CrewType, flam.GroupMode]] = []

        for subfindable in split:
            # If there is a group_mode it will be separated with a colon.
            ct_gm_strs = subfindable.split(':', maxsplit=1)

            # Forgive excess commas, but later we'll have to verify there was at least one non-empty subfindable.
            if len(ct_gm_strs) == 0:
                continue

            crew_type_str = ct_gm_strs[0]
            group_mode = flam.GroupMode.DEFAULT if len(ct_gm_strs) == 1 else flam.GroupMode(ct_gm_strs[1])

            # Support 'roles', 'people' as an alias for 'any', 'any-people'.
            if crew_type_str == flam.FindableType.ROLES or crew_type_str == flam.FindableType.PEOPLE:
                findable_type = flam.FindableType(crew_type_str)
                crew_types = [flam.CrewType.ANY]
            else:
                # Handle whether this is a '-people' or just a roles findable.
                findable_type = flam.FindableType.PEOPLE if crew_type_str.endswith(f'-{flam.FindableType.PEOPLE}') else flam.FindableType.ROLES
                crew_type_str = crew_type_str.removesuffix(f'-{flam.FindableType.PEOPLE}')
                
                # Support 'crew' as a shorthand for the list of all crew types.
                if crew_type_str == 'crew':
                    crew_types = list(flam.CrewType.iterate_except_any())
                else:
                    crew_types = [flam.CrewType(crew_type_str)]

            if sample_findable is None:
                sample_findable = findable_type
            elif sample_findable != findable_type:
                raise ValueError('All FINDABLEs must have the same type')

            ct_gms.extend((crew_type, group_mode) for crew_type in crew_types)

        if sample_findable is None:
            raise ValueError('Must specify at least one FINDABLE')

        return sample_findable, ct_gms

    @classmethod
    def execute(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        findable_type, ct_gms = args.FINDABLE

        listdefs, filter_tokens = split_at_filter(args.LISTDEF + args.FILTER)
        filter = ctx.compile_filter(filter_tokens, findable_type)
        movie_list = ctx.get_movie_list(listdefs if len(listdefs) > 0 else flam.SpecialListType.DEFAULTS)

        sort_attrs = cls.parse_sortkeys(args, findable_type, ctx)
        column_attrs = cls.parse_columns(args, findable_type, ct_gms, sort_attrs, movie_list, filter, ctx)

        flam.logger.info("Building findables list")

        findables = [
            findable
            for crew_type, group_mode in ct_gms
                for findable in movie_list.find(findable_type, crew_type=crew_type, group_mode=group_mode, filter=filter)
        ]

        flam.logger.info(f"Sorting findables list of {len(findables)} items")
        cls.sort_findables(sort_attrs, findables, args)

        flam.logger.info("Extracting columns from findables")
        values_table = [[findable.extract(attr) for attr, _ in column_attrs] for findable in findables]

        flam.logger.info("Stringifying the table")
        strs_table = list(cls.build_strs_table(column_attrs, values_table, args))

        flam.logger.info("Printing the table")
        print_table(strs_table, args.color, args.paginate, args.spacious, args.no_titles, args.dsv)

    # Can't do this at argparse time because it depends on the context.
    @classmethod
    def parse_sortkeys(cls, args: argparse.Namespace, findable_type: flam.FindableType, ctx: flam.FlamContext) -> list[tuple[flam.Attribute, None | str]]:
        attributes: list[tuple[flam.Attribute, None | str]]

        if args.sort is None:
            attributes = [(ctx.attributes[a], None) for a in cls.DEFAULT_SORT_KEYS[findable_type]]
        else:
            # Return a tuple with the attribute and also a hint of which string to use to print it to the user,
            # so that if this sort attribute is added as a smart column the user will see it by the same alias he used.
            attribute_names = args.sort.split(',') if args.sort != '' else []
            attributes = [(ctx.attributes.get(a, type_hint=findable_type), a) for a in attribute_names]

            for attr, alias_hint in attributes:
                if not attr.findable_type.is_applicable_to(findable_type):
                    display_str = alias_hint if alias_hint is not None else attr.qualified_name
                    raise flam.InputError(f"ATTRIBUTE '{display_str}' is a {attr.findable_type} attribute, so it is not found on {findable_type}.")

        flam.logger.info(f"Got sort keys: {', '.join(attr.qualified_name for attr, _ in attributes)}")
        return attributes

    # Helper func for parse_columns.
    @classmethod
    def parse_user_column(cls, column_str: str, findable_type: flam.FindableType, ctx: flam.FlamContext) -> typing.Iterable[tuple[flam.Attribute, None | str, bool]]:
        # Only support globbing if it includes '*'. Otherwise we expect to just find a single match for this column name.
        if '*' not in column_str:
            attr = ctx.attributes.get(column_str, type_hint=findable_type)
            
            if not attr.findable_type.is_applicable_to(findable_type):
                raise flam.InputError(f"ATTRIBUTE '{attr.qualified_name}' is a {attr.findable_type} attribute, so it is not found on {findable_type}.")

            # We'll return a list of (attr, name, must_keep) tuple:
            # * name is a hint so that the table printer will user the user-provided name if it's an alias
            # * must_keep is a hint that this user is specifically requested by the user so we won't drop it even if it has duplicates
            yield attr, column_str, True
        else:
            # We'll glob for matches.
            matches = []

            for alias in ctx.attributes:
                attr = ctx.attributes[alias]

                # Only glob attributes that are applicable to this findable type.
                if not ctx.attributes[alias].findable_type.is_applicable_to(findable_type):
                    continue

                # Check if globs match without the type too so you can glob like 'avg-*' and not 'movies-avg-*'.
                _, alias_without_type = flam.decompose_qualified_attr_or_pred_name(alias)

                # I think there's no such thing as an "invalid fnmatch pattern" so no error handling needed here.
                if fnmatch.fnmatch(alias, column_str) or fnmatch.fnmatch(alias_without_type, column_str):
                    matches.append((attr, alias, False))

            # We want them sorted so that the output is nice and consistent.
            matches.sort(key=lambda tup: tup[1])
            yield from matches
    
    # Helper func for parse_columns.
    @classmethod
    def should_add_source_column(cls, findable_type: flam.FindableType, movie_list: flam.MovieList, ctx: flam.FlamContext) -> bool:
        # Easily skip if not applicable.
        if not flam.FindableType.MOVIES.is_applicable_to(findable_type):
            return False
        
        # Always add for anonymous lists. Note that anonymous lists could also just mean the list is filtered, but in the CLI case we apply the filter only later.
        if movie_list.abstract_listdef.list_type == flam.SpecialListType.ANONYMOUS:
            return True

        # For configured composite lists we can check in the configuration if it's made up of multiple sublists.
        # This is much faster than going movie by movie in the list and checking if we can spot more than one sources.
        if movie_list.abstract_listdef.list_type == flam.SpecialListType.COMPOSITE:
            composite_list = ctx.cfg_readonly.composite_lists.get_by_uid(movie_list.abstract_listdef.address)
            return len(composite_list.simple_list_uids) > 1

        return False

    # Can't do this at argparse time because it depends on the context and sortkeys.
    @classmethod
    def parse_columns(cls, args: argparse.Namespace, findable_type: flam.FindableType, ct_gms: list[tuple[flam.CrewType, flam.GroupMode]],
            sort_attrs: list[tuple[flam.Attribute, None | str]], movie_list: flam.MovieList, filter: flam.Filter, ctx: flam.FlamContext) -> list[tuple[flam.Attribute, None | str]]:
        # First we'll parse user columns. It's kind of ugly and tricky.
        user_columns = [] if args.columns is None else args.columns.removeprefix('+').split(',')

        # Start with just getting the attribute of each column which includes expanding globs so each column might expand to multiple attributes.
        user_attrs = [
            tup
            for col in user_columns
                for tup in cls.parse_user_column(col, findable_type, ctx)
        ]

        # Now we need a deduping step - some attributes may have been globbed multiple times by different aliases,
        # or because the user has shadowed some builtin attribute with their custom one.
        # We want to always keep attributes that were added specifically and not by a glob, too. So have to be careful.
        # Iterate over indices in reverse because we'll be removing elements as we go.
        for i in reversed(range(len(user_attrs))):
            attr, _, must_keep = user_attrs[i]

            # Attribute was specifically requested by the user - keep it always.
            if must_keep:
                continue

            # Globbed attribute and there are others like it to the right, remove this one.
            if any(a.qualified_name == attr.qualified_name for a, _, _ in user_attrs[i + 1:]):
                del user_attrs[i]
            # Globbed attribute and there are others like it to the left which are must_keep, also remove this one.
            elif any(a_must_keep and a.qualified_name == attr.qualified_name for a, _, a_must_keep in user_attrs[:i]):
                del user_attrs[i]

        # Now we're done with must_keep. We'll build the final attributes list into this object.
        attributes = [(attr, alias_hint) for attr, alias_hint, _ in user_attrs]
        
        # Helper function - insert to attributes but only if it's not already there.
        # We need this because we'll be avoiding adding default/smart columns if it will cause duplication with the user's columns.
        def uniq_insert(attr: flam.Attribute, alias_hint: None | str, index: int) -> None:
            if any(attr.qualified_name == a.qualified_name for a, _ in attributes):
                return

            attributes.insert(index, (attr, alias_hint))

        # If the string starts with a '+' then we are in additive mode - combine both user-added columns and the default columns.
        is_additive = args.columns is None or args.columns.startswith('+')

        if is_additive:
            # Add defaults to the left of the user columns. In reverse because all are inserted to 0 so that actually results in keeping the original order.
            for col in reversed(cls.DEFAULT_COLUMN_KEYS[findable_type]):
                uniq_insert(ctx.attributes[col], None, 0)

            # Add a column for the crew type at the leftmost if we're searching for multiple crew types.
            # We won't also add a column for the group mode. The user knows what he did.
            if len(ct_gms) > 1:
                uniq_insert(ctx.attributes['people-crew-type'], None, 0)

            # Add a column for the characters at the end if searching for actors.
            if flam.FindableType.ROLES.is_applicable_to(findable_type) and any(crew_type == flam.CrewType.CAST for crew_type, _ in ct_gms):
                uniq_insert(ctx.attributes['roles-characters'], None, len(attributes))

            # Add a column for the origin list at the end if we combined multiple lists. The way to check it is a little complicated.
            if cls.should_add_source_column(findable_type, movie_list, ctx):
                uniq_insert(ctx.attributes['movies-source'], None, len(attributes))

            # Add a column for every sort key in the end if they are not the default sort keys.
            if args.sort is not None:
                for attr, alias_hint in sort_attrs:
                    uniq_insert(attr, alias_hint, len(attributes))

            # Add a column for every attribute referenced in the filter.
            # Anonymous composites are not a worry here because at the CLI level those are never filtered (filter is applied at a later phase).
            # First we need to get the composite list filter since we'll want to search both there and in the filter we'll apply later.
            if movie_list.abstract_listdef.list_type == flam.SpecialListType.COMPOSITE:
                composite_list = ctx.cfg_readonly.composite_lists.get_by_uid(movie_list.abstract_listdef.address)
                composite_list_filter = ctx.compile_filter(composite_list.filter_tokens, findable_type)
            else:
                composite_list_filter = ctx.compile_filter([], findable_type)

            # Now search for attributes in both filters.
            for filter_member in itertools.chain(filter.colonoscopy(), composite_list_filter.colonoscopy()):
                if not isinstance(filter_member, flam.Predicate):
                    continue

                # Implementation is hacky because we don't really want to add an interface for "get_referenced_attributes" in each predicate.
                # So we just check for common ways that perdicates reference their attributes.
                # AttributePredicate has 'ATTRIBUTE' as a classvar.
                if hasattr(type(filter_member), 'ATTRIBUTE'):
                    filter_attr = type(filter_member).ATTRIBUTE # type: ignore
                # Other builtins have '_attribute' as a field.
                elif hasattr(filter_member, '_attribute'):
                    filter_attr = filter_member._attribute # type: ignore
                else:
                    filter_attr = None

                # Filters can have subfilters of different types. So only add applicable attributes.
                if filter_attr is not None and filter_attr.findable_type.is_applicable_to(findable_type):
                    uniq_insert(filter_attr, None, len(attributes))

        flam.logger.info(f"Got columns: {', '.join(attr.qualified_name for attr, _ in attributes)}")
        return attributes

    @classmethod
    def sort_findables(cls, sort_attrs: list[tuple[flam.Attribute, None | str]], findables: list[flam.Findable], args: argparse.Namespace) -> None:
        for attr, _ in reversed(sort_attrs):
            # Use functools.partial to silence "cell-var-from-loop" warning by pylint.
            key = functools.partial(lambda a, f: a.sort_key(f.extract(a)), attr)
            findables.sort(key=key, reverse=(not attr.is_ascending) ^ args.reverse)

    @classmethod
    def build_strs_table(cls, attributes: list[tuple[flam.Attribute, None | str]], values_table: list[list[flam.AttributeValue]], args: argparse.Namespace) -> typing.Iterable[list[str]]:
        if not args.no_titles:
            titles = []

            for attr, alias_hint in attributes:
                # If the user specified the attribute with an alias or a qualified name we want to also print it with that header.
                if alias_hint is not None:
                    titles.append(alias_hint)
                # Use name_without_type unless that would lead to ambiguity.
                elif all(a == attr or a.name_without_type != attr.name_without_type for a, _ in attributes):
                    titles.append(attr.name_without_type)
                else:
                    titles.append(attr.qualified_name)

            yield titles

        for record in values_table:
            yield [attributes[i][0].str_of_value(record[i], abbreviate=not args.verbose) for i in range(len(attributes))]

# class SubcommandChart:
#     @classmethod
#     def add_subparser(cls, subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
#         parser = subparsers.add_parser('chart', formatter_class=argparse.RawTextHelpFormatter)
#         parser.set_defaults(function=cls.execute)

#         parser.add_argument('-o', '--omit-zeroes', choices=Choice.always_auto_never(), default=Choice.AUTO, action='store', help=
#             'Choose whether to omit buckets with 0 movies. Defaults to %(default)s, which uses a mode that depends on DISTRIBUTION')
#         parser.add_argument('-v', '--value-sort', default=False, action='store_true', help='Sort based on the table values, not the keys')
#         parser.add_argument('-n', '--no-number', default=False, action='store_true', help="Don't append the numerical value to each bar.")
#         parser.add_argument('-S', '--spacious', default=False, action='store_true', help='Space out the table')
#         parser.add_argument('-t', '--no-title', default=False, action='store_true', help="Don't print a title.")
#         parser.add_argument('-k', '--no-prefix-key', default=False, action='store_true', help="Don't write the key at the start of each bar.")
#         parser.add_argument('-K', '--suffix-key', default=False, action='store_true', help='Append the key to the end of each bar')
        
#         # TODO: Not sure about these options yet:
#         # '-c', '--crew-types',  CREWS      Comma-delimited list of crew types to count in crew-size distribution. Defaults to '*', which means all crew types.
#     #     parser.add_argument('-f', '--factor', metavar='FACTOR', type=int, action='store', default=0, help=
#     #         '''Define custom scaling factor to apply to the table. Defaults to %(default)s, which means a value will be computed to make the table fit in the terminal width.
#     # Positive numbers stretch, negatives squish.''')

#         parser.add_argument('DISTRIBUTION', action='store', help=
#             '''Which distribution to view (also option for custom distribution based on a field?)''')
#         parser.add_argument('LISTDEF', nargs='+', action='store', help=
#             '''Like find''')
#         parser.add_argument('FILTER', nargs='*', action='store', help=
#             '''find-like expression featuring predicates like -crew, -cast, -release...''')
#         return parser

#     @classmethod
#     def execute(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
#         print('chart')

def make_main_parser(add_subparsers: bool) -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    parser = argparse.ArgumentParser(
        formatter_class = argparse.RawTextHelpFormatter,
        description = (
'''Gain insights on your movie lists. Quickly answer questions like "Where have I seen this actor?", or "Which director have I seen the most movies from?", and so much more.

1. Create movie lists on IMDb, Letterboxd, or your website of choice
2. Configure %(prog)s with how to download those lists with `%(prog)s config list`
3. Download all the information about the movies in those lists with `%(prog)s fetch`
4. Gain insights on the movies in those lists with `%(prog)s find` and `%(prog)s chart`

A bit of information on each subcommand:

    config      View or change the configuration - configure lists, custom extensions, etc.
    fetch       Download movie lists locally so they can be used
    find        Query for movies, people, or roles in your movie lists

The default subcommand is `find`. See `%(prog)s find --help` to know which arguments it accepts. There is a help option for all subcommands.
'''),
        epilog = (
'''Examples:
    %(prog)s config list --default-fetch=yes --default-find=yes mylist imdb-browser-apidev-listid=083886771
        (Create a list 'mylist' with the IMDb list address)
    %(prog)s fetch
        (Fetch all lists configured with --default-fetch)
    %(prog)s find movies
        (View all movies in lists configured with --default-find)
    %(prog)s director mylist -name tarantino
        (Uses find as the default subcommand. View information about directors in 'mylist' named 'tarantino' and all the movies they've directed from the list)
'''),
        exit_on_error = False,
        prog = 'flam', # Needed for when running the script using python -m.
        add_help = add_subparsers, # Don't conflict helps.
    )

    # Main parser option letters mustn't conflict with find's option letters (or: I wish -F could be -C).
    # NOTE: we are strict about proper punctuation, including capital letters at the beginning of each help string and a period at the end.
    # This conflicts with the format that argparse uses for --help, and I hate the inconsistency, but argparse is wrong.
    parser.add_argument('-F', '--flam-dir', metavar='PATH', default=flam.DEFAULT_FLAM_DIR, action='store', help=
        f'Use %(metavar)s as the flam directory - where %(prog)s stores all your data. Uses {flam.FlamEnv.CTX_DIR} environment variable by default, or ~/.film_flam if it is not defined.')
    parser.add_argument('-E', '--no-extensions', action='store_true', help=
        "Don't import configured extensions. Importing extensions executes arbitrary code so use this if you don't trust them.")
    parser.add_argument('-V', '--version', action='version', version=f'%(prog)s version {flam.__version__}')

    if add_subparsers:
        # Subparsers are organized into "static" classes. This is only for code organization reasons, not OOP reasons.
        # The classes are designed to enforce as little "model" as possible so we can be flexible with how we use them.
        subparsers = parser.add_subparsers(required=True)
        SubcommandConfig.add_subparser(subparsers)
        SubcommandFetch.add_subparser(subparsers)
        find_subparser = SubcommandFind.add_subparser(subparsers, None)
        # SubcommandChart.add_subparser(subparsers)
    else:
        find_subparser = SubcommandFind.add_subparser(None, parser)

    return parser, find_subparser

def main() -> None:
    colorama.just_fix_windows_console()

    # This is needed. Trust me.
    try:
        sys.stdout.reconfigure(encoding='utf-8', newline='\n') # type: ignore
    except:
        flam.logger.error("Failed to reconfigure stdout. Proceeding anyway.", exc_info=True)

    flam.logger.info(f"Executed with: {sys.argv=}")

    # We want to support 'find' as the default subparser. This has a few limitations:
    # * argparse sucks at supporting it.
    # * If we transform flam <main-opts> <WHAT> <find-opts> <LISTDEFS> <FILTER> -> flam <main-opts> <find-opts> <WHAT> <LISTDEFS> <FILTER>,
    #   there is ambiguity because LISTDEFS can be empty and then you can have: flam movies -true, is -true a FILTER or the opts -t, -r, -u, -e?
    # * Similar to the point above, argparse.REMAINDER only works if it is preceded by a positional argument.
    # * A few error messages and --help can become confusing.
    # 
    # Our solution is the following:
    # * We first try to build a parser where all subparsers are nested. If it fails to parse due to invalid subcommand choice,
    #   we fallback to a parser where the main parser is configured with both main and find parser configs.
    #   This works because we preserve the trait that <WHAT> isn't followed by optional arguments.
    # * If the fallback parser fails we print the error as if it came from find as a subparser, not find as embedded in the main parser.
    parser, find_subparser = make_main_parser(True)

    try:
        try:
            args = parser.parse_args()
        except argparse.ArgumentError as e:
            # If error was not an invalid subcommand, just forward it.
            if not re.search('invalid choice.*config.*find', str(e)):
                parser.error(str(e))
            
            flam.logger.info(f"Will default to parsing as find due to error: {e}")
            find_mainparser, _ = make_main_parser(False)

            try:
                args = find_mainparser.parse_args()
            except argparse.ArgumentError as e2:
                # Print errors as if they came from "flam find".
                find_subparser.error(str(e2))
            
        flam.logger.info(f"Parsed args into: {args=}")

        # We use the FILTER, REMAINDER trick a lot so we take care of it generically.
        if hasattr(args, 'REMAINDER'):
            if hasattr(args, 'FILTER'):
                args.FILTER += args.REMAINDER
            elif hasattr(args, 'MOVIE_FILTER'):
                args.MOVIE_FILTER += args.REMAINDER
            else:
                raise RuntimeError("Shouldn't get here!")

        ctx = flam.FlamContext(args.flam_dir, import_extensions=not args.no_extensions)
        args.function(ctx, args)
    except flam.FlamError as e:
        if flam.is_debug():
            raise

        # No ugly tracebacks for input errors. Only for internal errors.
        sys.exit(f'{parser.prog}: error: {e}')

flam.logger.info(f'Module import time: {time.time() - _start_import_time}s')

if __name__ == '__main__':
    main()
