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
import time

# Unlike all other modules in this package, this one pretends it's from outside the package and simply "imports flam".
import flam
from flam import utils

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
            # Slightly nudge up the length of the table to encourage pagination.
            paginate = sys.stdout.isatty() and os.get_terminal_size().lines <= len(table) + 2 and shutil.which('less') is not None
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
        
        out.flush()

        if paginate:
            try:
                subprocess.call(['less', '-RS', out.name])
            except Exception as e:
                raise flam.InputError(f"Pagination failed with error: {e}. You probably don't have less installed.") from e

class SubcommandConfig:
    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        config_subparsers = parser.add_subparsers(required=True)
        SubcommandConfigList.configure_parser(config_subparsers.add_parser('list', formatter_class=argparse.RawTextHelpFormatter))
        SubcommandConfigComposite.configure_parser(config_subparsers.add_parser('composite', formatter_class=argparse.RawTextHelpFormatter))
        SubcommandConfigExtension.configure_parser(config_subparsers.add_parser('extension', formatter_class=argparse.RawTextHelpFormatter))

class SubcommandConfigExtension:
    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        parser.set_defaults(function=cls.execute)

        action_group = parser.add_mutually_exclusive_group(required=False)
        action_group.add_argument('-A', '--add', action='store_true', help='Add an extension. This is the default behavior')
        action_group.add_argument('-D', '--delete', action='store_true', help='Delete an extension')
        action_group.add_argument('-P', '--print', action='store_true', help='Print all extensions')

        parser.add_argument('IMPORT', action='store', nargs='?', help='Specify which module or file to import')

    @classmethod
    def execute(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        if args.delete:
            cls.delete(ctx, args)
        elif args.print:
            cls.print(ctx, args)
        # Default add.
        else:
            cls.add(ctx, args)

    @classmethod
    def delete(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        if args.IMPORT is None:
            raise flam.InputError(f"Must specify a IMPORT to delete an extension.")

        with ctx.configure() as cfg:
            try:
                cfg.extensions.remove(args.IMPORT)
            except ValueError as e:
                raise flam.InputError(f"No extension named '{args.IMPORT}'.") from e

    @classmethod
    def print(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        table = [['module / script']]
        table.extend(sorted([e] for e in ctx.cfg_readonly.extensions))
        print_table(table)

    @classmethod
    def add(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        if args.IMPORT is None:
            raise flam.InputError(f"Must specify a IMPORT to add an extension.")

        with ctx.configure() as cfg:
            cfg.extensions.append(args.IMPORT)

class SubcommandConfigList:
    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        parser.set_defaults(function=cls.execute)

        action_group = parser.add_mutually_exclusive_group(required=False)
        action_group.add_argument('-E', '--edit', action='store_true', help='edit or create a list. This is the default behavior')
        action_group.add_argument('-D', '--delete', action='store_true', help='delete the list')
        action_group.add_argument('-P', '--print', action='store_true', help='print the list, or if NAME not provided, print all lists')

        parser.add_argument('-n', '--rename', metavar='NAME', default=None, action='store', help='in edit mode, rename the list to %(metavar)s')
        parser.add_argument('-i', '--default-find', choices=Choice.yes_no_auto(), default=Choice.AUTO, action='store', help='decide if this list should be default for flam find')
        parser.add_argument('-e', '--default-fetch', choices=Choice.yes_no_auto(), default=Choice.AUTO, action='store', help='decide if this list should be fetched by default')
        parser.add_argument('NAME', action='store', nargs='?', default=None, help='Operate on the list named %(dest)s')
        parser.add_argument('LISTDEF', action='store', nargs='?', default=None, help='set the list type and address to %(dest)s')

    @classmethod
    def execute(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        if args.delete:
            cls.delete(ctx, args)
        elif args.print:
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
            raise flam.InputError(f"Must specify a NAME to delete a list.")

        with ctx.configure() as cfg:
            del cfg.simple_lists_raw[cfg.simple_lists.get_idx_by_name(args.NAME)]

    @classmethod
    def print(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        simple_lists = list(ctx.cfg_readonly.simple_lists) if args.NAME is None else [ctx.cfg_readonly.simple_lists.get_by_name(args.NAME)]

        table = [['uid', 'name', 'type', 'address', 'default-fetch?', 'default-find?']]
        table.extend(sorted(
            [
                typing.cast(str, sl.uid).split('-')[0],
                sl.name,
                sl.list_type,
                sl.address,
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
                simple_list.list_type = cldef.list_type
                simple_list.address = cldef.address

            if args.default_fetch != Choice.AUTO:
                simple_list.is_default_fetch = args.default_fetch == Choice.YES

            if args.default_find != Choice.AUTO:
                simple_list.is_default_find = args.default_find == Choice.YES

    @classmethod
    def create(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        if args.NAME is None:
            raise flam.InputError(f"Must specify a NAME to create or edit a list.")

        if args.LISTDEF is None:
            raise flam.InputError(f"List '{args.NAME}' doesn't exist, so LISTDEF is required.")

        cldef = flam.CanonListdef.parse(args.LISTDEF, ctx)

        simple_list = flam.SimpleList(
            uid = 'INITIALIZED LATER',
            name = args.NAME,
            list_type = cldef.list_type,
            address = cldef.address,
            is_default_fetch = args.default_fetch != Choice.NO,
            is_default_find = args.default_find == Choice.YES,
        )

        with ctx.configure() as cfg:
            cfg.simple_lists_raw.append(simple_list)

class SubcommandConfigComposite:
    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        parser.set_defaults(function=cls.execute)

        action_group = parser.add_mutually_exclusive_group(required=False)
        action_group.add_argument('-E', '--edit', action='store_true', help='edit or create a composite list. This is the default behavior')
        action_group.add_argument('-D', '--delete', action='store_true', help='delete the list')
        action_group.add_argument('-P', '--print', action='store_true', help='print the list, or if NAME not provided, print all lists')

        parser.add_argument('-n', '--rename', metavar='NAME', default=None, action='store', help='in edit mode, rename the list to %(metavar)s')
        parser.add_argument('-i', '--default-find', choices=Choice.yes_no_auto(), default=Choice.AUTO, action='store', help='decide if this list should be default for flam find')
        parser.add_argument('-e', '--default-fetch', choices=Choice.yes_no_auto(), default=Choice.AUTO, action='store', help='decide if this list should be fetched by default')
        parser.add_argument('NAME', nargs='?', action='store', default=None, help='Operate on the list named %(dest)s')
        parser.add_argument('LIST', nargs='*', action='store', help='Set the list names to %(dest)s')
        parser.add_argument('FILTER', nargs='*', action='store', help='Set the FILTER to %(dest)s')

        # argparse.REMAINDER is an undocumented but very important feature.
        # Basically it's the only way to make positional arguments that start with dashes not be treated as bad options.
        parser.add_argument('REMAINDER', nargs=argparse.REMAINDER, action='store', help=argparse.SUPPRESS)

    @classmethod
    def execute(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        if args.delete:
            cls.delete(ctx, args)
        elif args.print:
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
            raise flam.InputError(f"Must specify a NAME to delete a composite list.")

        with ctx.configure() as cfg:
            del cfg.composite_lists_raw[cfg.composite_lists.get_idx_by_name(args.NAME)]

    @classmethod
    def print(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        composite_lists = list(ctx.cfg_readonly.composite_lists) if args.NAME is None else [ctx.cfg_readonly.composite_lists.get_by_name(args.NAME)]

        table = [['uid', 'name', 'lists', 'filter', 'default-fetch?', 'default-find?']]
        table.extend(sorted(
            [
                typing.cast(str, cl.uid).split('-')[0],
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

            simple_list_names, filter_tokens = split_at_filter(args.LIST + args.FILTER)

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
            raise flam.InputError(f"Must specify a NAME to create or edit a composite list.")

        simple_list_names, filter_tokens = split_at_filter(args.LIST + args.FILTER)

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
    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        parser.set_defaults(function=cls.execute)
        
        parser.add_argument('-u', '--undo', action='store_true', help="Undo the previous fetch operation in its entirety. Note this will also restore configuration to the old state. "
            "Fetch can be expensive so if something goes wrong and files get messed up this is good to have.")
        parser.add_argument('-r', '--refetch', metavar='PATTERN', default=None, action='store', help=
            '''Forces titles that match %(metavar)s (case-insensitive) to be redownloaded even if they are already locally stored.
It's enough for %(metavar)s to match any part of the title, not necessarily the whole title.
%(metavar)s uses regex syntax from python's re library, which is identical to egrep unless you use very advanced features.
This feature is intended for redownloading shows after a new season has come out''')

        parser.add_argument('LISTDEF', nargs='*', action='store', help=
            '''Each %(dest)s describes a list to fetch. Supports, in order of priority:
1. Configured list name (type: list)
2. Configured composite list name (will fetch all lists under it) (type: composite)
3. Address to fetch the list from (IMDb list id for instance). But for these the type is not inferred, you must specify it.

To avoid ambiguity and for downloading addresses directly, you can specify the %(dest)s type by writing <type>=%(dest)s. Supported types are:
* 'list'
* 'composite'
* 'imdb-id'
* 'imdb-private-id'
* 'imdb-csv'
* Any custom types you define...

If no %(dest)s provided, fetches all lists configured as defaults''')

    @classmethod
    def execute(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        if args.undo:
            cls.pop_undo(ctx)
        else:
            try:
                cls.push_undo(ctx)
            except Exception as e:
                # Sweep this one silently.
                flam.logger.warning(f"Failed to store state for later undoing with error: {e}")

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

        while len(backups) >= 3:
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
    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        parser.set_defaults(function=cls.execute)

        # TODO: "--split" option to expand array attributes into a row for each one?
        parser.add_argument('-s', '--sort', metavar='ATTRIBUTES', default=None, action='store', help=
            f'''Sort movies according to %(metavar)s, which is a comma-delimited list of keys to sort by, in decreasing priority. Defaults to 'leaving,runtime,alphabetical'.
            Valid sort keys: ...''')
        parser.add_argument('-C', '--color', choices=Choice.always_auto_never(), default=Choice.AUTO, action='store', help=
            'Set whether columns should be colored. Defaults to %(default)s')
        parser.add_argument('-d', '--dsv', metavar='DELIM', default=None, action='store', help=
            "Output in delimiter-separated values format (DSV).")
        parser.add_argument('-c', '--columns', metavar='ATTRIBUTES', default=None, action='store', help=
            'List of columns to print, delimited by commas. Defaults to \'title,leaving,runtime,released,rating,metascore,director\','
            f''' with a few other "smart" columns which activate when a condition is met.
This option overrides the defaults and smart columns. Only the columns you specify will be printed.
Beginning this string with a '+' will cause the columns to be added to the default (and smart) columns instead of replacing them.
If %(metavar)s is '*', will print all columns.
Valid column names: ...''')
        parser.add_argument('-v', '--verbose', default=False, action='store_true', help=
            'Use verbose output, like writing the full release date instead of just the year, and not chopping long strings')
        parser.add_argument('-r', '--reverse', default=False, action='store_true', help=
            'Reverse the sort order. By default some sort keys are ascending and some descending based on what makes sense to me. This reverses those defaults')
        parser.add_argument('-S', '--spacious', default=False, action='store_true', help=
            'Add an empty line between entries')
        parser.add_argument('-P', '--paginate', choices=Choice.always_auto_never(), default=Choice.AUTO, action='store', help=
            'Choose whether to paginate with less. Defaults to %(default)s, which depends on the size of the output')
        parser.add_argument('-f', '--date-format', metavar='FORMAT', default=None, action='store', help=
            'Override format for date columns. Default depends on verbosity and which column. See python datetime.strftime documentation for format syntax')
        parser.add_argument('-t', '--no-titles', default=False, action='store_true', help=
            'Don\'t print a row with the column titles')

        parser.add_argument('FINDABLE', type=cls.parse_findable, action='store', help=
            '''Choose what to find: movies, people, or roles.
For people and roles, supports limiting the search to a specific crew type and group mode, and supports comma-delimited several types. Use 'crew' to catenate all types.
For roles, it looks like: 'cast', 'director:group', 'composer:separate,stuntcast', 'crew', etc.
For people, it looks like 'cast-people', 'director-people:group', etc.''')
        parser.add_argument('LISTDEF', nargs='*', action='store', help=
            '''Like fetch but with different defaults, and if the LISTDEFs aren't already fetched, it fails with a nice error message''')
        parser.add_argument('FILTER', nargs='*', action='store', help=
            '''find-like expression featuring predicates like -crew, -cast, -release...''')
        parser.add_argument('REMAINDER', nargs=argparse.REMAINDER, action='store', help=argparse.SUPPRESS)

    @classmethod
    def parse_findable(cls, findable: str) -> tuple[flam.FindableType, list[tuple[flam.CrewType, flam.GroupMode]]]:
        if findable == '':
            raise ValueError(f"Cannot be empty string.")

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
        column_attrs = cls.parse_columns(args, findable_type, ct_gms, sort_attrs, movie_list, ctx)

        flam.logger.info(f"Building findables list")

        findables = [
            findable
            for crew_type, group_mode in ct_gms
                for findable in movie_list.find(findable_type, crew_type=crew_type, group_mode=group_mode, filter=filter)
        ]

        flam.logger.info(f"Sorting findables list of {len(findables)} items")
        cls.sort_findables(sort_attrs, findables, args)

        flam.logger.info(f"Extracting columns from findables")
        values_table = [[findable.extract(attr) for attr, _ in column_attrs] for findable in findables]

        flam.logger.info(f"Stringifying the table")
        strs_table = list(cls.build_strs_table(column_attrs, values_table, args))

        flam.logger.info(f"Printing the table")
        cls.print_table(strs_table, [attr for attr, _ in column_attrs], args)

    # Can't do this at argparse time because it depends on the context.
    @classmethod
    def parse_sortkeys(cls, args: argparse.Namespace, findable_type: flam.FindableType, ctx: flam.FlamContext) -> list[flam.Attribute]:
        if args.sort is None:
            default_attribute_names = {
                flam.FindableType.MOVIES: ['runtime', 'title'],
                flam.FindableType.PEOPLE: ['crew-type', 'group-mode', 'nmovies', 'name'],
                flam.FindableType.ROLES: ['crew-type', 'group-mode', 'nmovies', 'name', 'release-year', 'title'],
            }

            attribute_names = default_attribute_names[findable_type]
        else:
            attribute_names = args.sort.split(',') if args.sort != '' else []

        attributes = [ctx.attributes.get(a, type_hint=findable_type) for a in attribute_names]

        for i, attr in enumerate(attributes):
            if not attr.findable_type.is_applicable_to(findable_type):
                raise flam.InputError(f"ATTRIBUTE '{attribute_names[i]}' is a {attr.findable_type} attribute, so it is not found on {findable_type}.")
        
        flam.logger.info(f"Got sort keys: {', '.join(attr.qualified_name for attr in attributes)}")
        return attributes

    # Can't do this at argparse time because it depends on the context and sortkeys.
    @classmethod
    def parse_columns(cls, args: argparse.Namespace, findable_type: flam.FindableType, ct_gms: list[tuple[flam.CrewType, flam.GroupMode]],
            sort_attrs: list[flam.Attribute], movie_list: flam.MovieList, ctx: flam.FlamContext) -> list[tuple[flam.Attribute, None | str]]:
        is_additive = args.columns is None or args.columns.startswith('+')
        columns = [] if args.columns is None else args.columns.removeprefix('+').split(',')

        # We'll return a list of (attr, name) tuples where name is just a hint so that the table printer will user the user-provided name if it's an alias.
        attributes = [(ctx.attributes.get(c, type_hint=findable_type), c) for c in columns]

        if is_additive:
            # TODO: Decide on default columns for PEOPLE, ROLES
            default_columns = {
                flam.FindableType.MOVIES: ['title', 'runtime', 'release-year', 'rating', 'metascore', 'director'],
                flam.FindableType.PEOPLE: ['name', 'nmovies', 'avg-rating', 'avg-metascore'],
                flam.FindableType.ROLES: ['people-name', 'title', 'avg-rating', 'avg-metascore'],
            }

            # Use default columns even if the same attribute is also in the custom columns from the user.
            # Print the default columns before the additions, and additions before smart columns.
            attributes = [(ctx.attributes.get(c, type_hint=findable_type), None) for c in default_columns[findable_type]] + attributes
            smart_columns = []

            # "Smart" columns that aren't default unless conditions are met.
            # TODO: maybe we should generalize and just say that any sort key also becomes a column key,
            # and maybe we should consider not just sort keys but also attributes referenced in the filter?
            if any(attr.qualified_name == 'movies-watched' for attr in sort_attrs):
                smart_columns.append('movies-watched')

            if any(attr.qualified_name == 'movies-votes' for attr in sort_attrs):
                smart_columns.append('movies-votes')

            if any(attr.qualified_name == 'movies-my-rating' for attr in sort_attrs):
                smart_columns.append('movies-my-rating')

            if any(attr.qualified_name == 'movies-description' for attr in sort_attrs):
                smart_columns.append('movies-description')
            
            if len(ct_gms) > 1:
                smart_columns.append('crew-type')

            # If more than one CTGM and one of them isn't the default group mode, show the group mode.
            if len(ct_gms) > 1 and any(group_mode != crew_type.default_group_mode for crew_type, group_mode in ct_gms):
                smart_columns.append('group-mode')

            if findable_type == flam.FindableType.ROLES and any(crew_type == flam.CrewType.CAST for crew_type, _ in ct_gms):
                smart_columns.append('characters')

            # If we combined multiple lists, tag each element with the list(s) it came from.
            # if movie_list.list_type == flam.SpecialListType.ANNONYMOUS:
            #     smart_columns.append('origin')

            # Only use smart columns that aren't already in the attributes list.
            for c in smart_columns:
                smart_attr = ctx.attributes.get(c, type_hint=findable_type)

                if all(a.qualified_name != smart_attr.qualified_name for a, _ in attributes):
                    attributes.append((smart_attr, None))

        for attr, _ in attributes:
            if not attr.findable_type.is_applicable_to(findable_type):
                raise flam.InputError(f"ATTRIBUTE '{attr.qualified_name}' is a {attr.findable_type} attribute, so it is not found on {findable_type}.")

        flam.logger.info(f"Got columns: {', '.join(attr.qualified_name for attr, _ in attributes)}")
        return attributes

    @classmethod
    def sort_findables(cls, sort_attrs: list[flam.Attribute], findables: list[flam.Findable], args: argparse.Namespace) -> None:
        for attr in reversed(sort_attrs):
            # Use functools.partial to silence "cell-var-from-loop" warning by pylint.
            key = functools.partial(lambda a, f: a.sort_key(f.extract(a)), attr)
            findables.sort(key=key, reverse=(not attr.is_ascending) ^ args.reverse)

    @classmethod
    def build_strs_table(cls, attributes: list[tuple[flam.Attribute, None | str]], values_table: list[list[flam.AttributeValue]], args: argparse.Namespace) -> typing.Iterable[list[str]]:
        if not args.no_titles:
            titles = []

            for attr, name_hint in attributes:
                # If the user specified the attribute with an alias or a qualified name we want to also print it with that header.
                if name_hint is not None:
                    titles.append(name_hint)
                # Use name_without_type unless that would lead to ambiguity.
                elif all(a == attr or a.name_without_type != attr.name_without_type for a, _ in attributes):
                    titles.append(attr.name_without_type)
                else:
                    titles.append(attr.qualified_name)

            yield titles

        for record in values_table:
            yield [attributes[i][0].str_of(record[i]) for i in range(len(attributes))]

    @classmethod
    def print_table(cls, table: list[list[str]], attributes: list[flam.Attribute], args: argparse.Namespace) -> None:
        if not args.verbose:
            for row in table:
                for i in range(len(row)):
                    # For now I'm ok with this being tacked on instead of max_len as a property of each attribute.
                    max_len = 45 if attributes[i].qualified_name == 'movies-title' else 30
                    row[i] = utils.truncate(row[i], max_len, is_big_endian=attributes[i].is_big_endian)

        print_table(table, args.color, args.paginate, args.spacious, args.no_titles, args.dsv)

class SubcommandChart:
    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        parser.set_defaults(function=cls.execute)

        parser.add_argument('-o', '--omit-zeroes', choices=Choice.always_auto_never(), default=Choice.AUTO, action='store', help=
            'Choose whether to omit buckets with 0 movies. Defaults to %(default)s, which uses a mode that depends on DISTRIBUTION')
        parser.add_argument('-v', '--value-sort', default=False, action='store_true', help='Sort based on the table values, not the keys')
        parser.add_argument('-n', '--no-number', default=False, action='store_true', help="Don't append the numerical value to each bar.")
        parser.add_argument('-S', '--spacious', default=False, action='store_true', help='Space out the table')
        parser.add_argument('-t', '--no-title', default=False, action='store_true', help="Don't print a title.")
        parser.add_argument('-k', '--no-prefix-key', default=False, action='store_true', help="Don't write the key at the start of each bar.")
        parser.add_argument('-K', '--suffix-key', default=False, action='store_true', help='Append the key to the end of each bar')
        
        # TODO: Not sure about these options yet:
        # '-c', '--crew-types',  CREWS      Comma-delimited list of crew types to count in crew-size distribution. Defaults to '*', which means all crew types.
    #     parser.add_argument('-f', '--factor', metavar='FACTOR', type=int, action='store', default=0, help=
    #         '''Define custom scaling factor to apply to the table. Defaults to %(default)s, which means a value will be computed to make the table fit in the terminal width.
    # Positive numbers stretch, negatives squish.''')

        parser.add_argument('DISTRIBUTION', action='store', help=
            '''Which distribution to view (also option for custom distribution based on a field?)''')
        parser.add_argument('LISTDEF', nargs='+', action='store', help=
            '''Like find''')
        parser.add_argument('FILTER', nargs='*', action='store', help=
            '''find-like expression featuring predicates like -crew, -cast, -release...''')

    @classmethod
    def execute(cls, ctx: flam.FlamContext, args: argparse.Namespace) -> None:
        print('chart')

def make_main_parser(add_subparsers: bool) -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    parser = argparse.ArgumentParser(
        formatter_class = argparse.RawTextHelpFormatter,
        description = 'I dunno lol',
        exit_on_error = False,
        prog = 'flam', # Needed for when running the script using python -m.
        add_help = add_subparsers, # Don't conflict helps.
    )

    # Main parser option letters mustn't conflict with find's option letters (or: I wish -F could be -C).
    parser.add_argument('-F', '--flam-dir', metavar='PATH', default=flam.DEFAULT_FLAM_DIR, action='store', help=
        f'Use %(metavar)s as the flam directory. Uses {flam.FlamEnv.CTX_DIR} environment variable by default, or ~/.film_flam if it is not defined')
    parser.add_argument('-E', '--no-extensions', action='store_true', help=
        "Don't import configured extensions")
    parser.add_argument('-V', '--version', action='version', version=f'%(prog)s version {flam.__version__}')

    if add_subparsers:
        # Subparsers are organized into "static" classes. This is only for code organization reasons, not OOP reasons.
        # The classes are designed to enforce as little "model" as possible so we can be flexible with how we use them.
        subparsers = parser.add_subparsers(required=True)
        SubcommandConfig.configure_parser(subparsers.add_parser('config', formatter_class=argparse.RawTextHelpFormatter))
        SubcommandFetch.configure_parser(subparsers.add_parser('fetch', formatter_class=argparse.RawTextHelpFormatter))
        SubcommandFind.configure_parser(find_subparser := subparsers.add_parser('find', formatter_class=argparse.RawTextHelpFormatter))
        SubcommandChart.configure_parser(subparsers.add_parser('chart', formatter_class=argparse.RawTextHelpFormatter))
    else:
        find_subparser = parser
        SubcommandFind.configure_parser(parser)

    return parser, find_subparser

def main() -> None:
    colorama.just_fix_windows_console()

    # This is needed. Trust me.
    try:
        sys.stdout.reconfigure(encoding='utf-8', newline='\n') # type: ignore
    except:
        flam.logger.error(f"Failed to reconfigure stdout. Proceeding anyway.", exc_info=True)

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
        if hasattr(args, 'FILTER') and hasattr(args, 'REMAINDER'):
            args.FILTER += args.REMAINDER

        ctx = flam.FlamContext(args.flam_dir, import_extensions=not args.no_extensions)
        args.function(ctx, args)
    except flam.FlamError as e:
        if flam.is_debug():
            raise

        # No ugly tracebacks for input errors. Only for internal errors.
        sys.exit(f'{parser.prog}: error: {e}')

if __name__ == '__main__':
    main()
