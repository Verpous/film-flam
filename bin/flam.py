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

import argparse
import enum
import os
import sys
import typing
import itertools
import colorama
import contextlib
import csv
import tempfile
import subprocess
import re
import shutil

import filmflam as ff
from filmflam import utils

def split_at_filter(strs: list[str]) -> tuple[list[str], list[str]]:
    filter_begin = next((i for i, s in enumerate(strs) if ff.is_filter_token(s)), len(strs))
    return strs[:filter_begin], strs[filter_begin:]

# TODO: need reverse? In mbrowse we only use it for the "source" column (i.e. the abstract address the movie came from)
def clampstr(s: str, maxlen: int = 30, ellipsis: str = '...', keep_lhs: bool = True) -> str:
    if maxlen < len(ellipsis):
        raise ValueError(f'Ellipsis must not be longer than maxlen. {ellipsis=}, {maxlen=}.')

    return (s if len(s) <= maxlen
        else s[:maxlen - len(ellipsis)] + ellipsis if keep_lhs
        else ellipsis + s[-(maxlen - len(ellipsis)):])

class Choice(enum.StrEnum):
    YES     = 'yes'
    NO      = 'no'
    ALWAYS  = 'always'
    NEVER   = 'never'
    AUTO    = 'auto'

    @classmethod
    def always_auto_never(cls) -> typing.Iterable[str]:
        return (cls.ALWAYS, cls.AUTO, cls.NEVER)

    @classmethod
    def yes_no_auto(cls) -> typing.Iterable[str]:
        return (cls.YES, cls.NO, cls.AUTO)

    # When you give argparse choices and they don't match it prints the error using repr so repr must be user readable.
    def __repr__(self) -> str:
        return str(self)

class SubcommandConfig:
    @classmethod
    def add_parser(cls, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser('config', formatter_class=argparse.RawTextHelpFormatter)
        config_subparsers = parser.add_subparsers(required=True)

        SubcommandConfigList.add_parser(config_subparsers)
        SubcommandConfigComposite.add_parser(config_subparsers)

class SubcommandConfigList:
    @classmethod
    def add_parser(cls, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser('list', formatter_class=argparse.RawTextHelpFormatter)
        parser.set_defaults(function=cls.execute)

        action_group = parser.add_mutually_exclusive_group(required=False)
        action_group.add_argument('-E', '--edit', action='store_true', help='edit or create a list. This is the default behavior.')
        action_group.add_argument('-D', '--delete', action='store_true', help='delete the list.')
        action_group.add_argument('-P', '--print', action='store_true', help='print the list, or if NAME not provided, print all lists.')

        parser.add_argument('-n', '--rename', metavar='NAME', default=None, action='store', help='in edit mode, rename the list to %(metavar)s')
        parser.add_argument('-i', '--default-find', choices=Choice.yes_no_auto(), default=Choice.AUTO, action='store', help='decide if this list should be default for flam find')
        parser.add_argument('-e', '--default-fetch', choices=Choice.yes_no_auto(), default=Choice.AUTO, action='store', help='decide if this list should be fetched by default')
        parser.add_argument('NAME', action='store', nargs='?', default=None, help='Operate on the list named %(dest)s')
        parser.add_argument('LISTDEF', action='store', nargs='?', default=None, help='set the list type and address to %(dest)s')

    @classmethod
    def execute(cls, ctx: ff.FlamContext, args: argparse.Namespace) -> None:
        if args.delete:
            cls.delete(ctx, args)
        elif args.print:
            cls.print(ctx, args)
        # Default edit/create.
        else:
            try:
                simple_list = ctx.simple_lists.get_by_name(args.NAME)
            except ff.InputError:
                cls.create(ctx, args)
            else:
                cls.edit(ctx, args, simple_list)

    @classmethod
    def delete(cls, ctx: ff.FlamContext, args: argparse.Namespace) -> None:
        if args.NAME is None:
            raise ff.InputError(f"Must specify a NAME to delete a list.")

        simple_list = ctx.simple_lists.get_by_name(args.NAME)
        assert not isinstance(simple_list.uid, ff.UnsetType)
        ctx.delete_simple_list(simple_list.uid)
        ctx.write_cfg()

    @classmethod
    def print(cls, ctx: ff.FlamContext, args: argparse.Namespace) -> None:
        # TODO: improve this in the future
        if args.NAME is None:
            for sl in ctx.simple_lists:
                print(sl)
        else:
            print(ctx.simple_lists.get_by_name(args.NAME))

    @classmethod
    def edit(cls, ctx: ff.FlamContext, args: argparse.Namespace, simple_list: ff.SimpleList) -> None:
        if args.rename is not None and args.rename != simple_list.name:
            simple_list.name = args.rename

        if args.LISTDEF is not None:
            cldef = ff.CanonListdef.parse(args.LISTDEF, ctx)
            simple_list.list_type = cldef.list_type
            simple_list.address = cldef.address

        if args.default_fetch != Choice.AUTO:
            simple_list.is_default_fetch = args.default_fetch == Choice.YES

        if args.default_find != Choice.AUTO:
            simple_list.is_default_find = args.default_find == Choice.YES

        ctx.write_cfg()

    @classmethod
    def create(cls, ctx: ff.FlamContext, args: argparse.Namespace) -> None:
        if args.NAME is None:
            raise ff.InputError(f"Must specify a NAME to create or edit a list.")

        if args.LISTDEF is None:
            raise ff.InputError(f"List '{args.NAME}' doesn't exist, so LISTDEF is required.")

        cldef = ff.CanonListdef.parse(args.LISTDEF, ctx)

        simple_list = ff.SimpleList.create(
            name = args.NAME,
            list_type = cldef.list_type,
            address = cldef.address,
            is_default_fetch = args.default_fetch != Choice.NO,
            is_default_find = args.default_find == Choice.YES,
        )

        ctx.add_simple_list(simple_list)
        ctx.write_cfg()

class SubcommandConfigComposite:
    @classmethod
    def add_parser(cls, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser('composite', formatter_class=argparse.RawTextHelpFormatter)
        parser.set_defaults(function=cls.execute)

        action_group = parser.add_mutually_exclusive_group(required=False)
        action_group.add_argument('-E', '--edit', action='store_true', help='edit or create a composite list. This is the default behavior.')
        action_group.add_argument('-D', '--delete', action='store_true', help='delete the list.')
        action_group.add_argument('-P', '--print', action='store_true', help='print the list, or if NAME not provided, print all lists.')

        parser.add_argument('-n', '--rename', metavar='NAME', default=None, action='store', help='in edit mode, rename the list to %(metavar)s')
        parser.add_argument('-i', '--default-find', choices=Choice.yes_no_auto(), default=Choice.AUTO, action='store', help='decide if this list should be default for flam find %(metavar)s')
        parser.add_argument('-e', '--default-fetch', choices=Choice.yes_no_auto(), default=Choice.AUTO, action='store', help='decide if this list should be fetched by default %(metavar)s')
        parser.add_argument('NAME', nargs='?', action='store', default=None, help='Operate on the list named %(dest)s')
        parser.add_argument('LIST', nargs='*', action='store', help='Set the list names to %(dest)s')
        parser.add_argument('FILTER', nargs='*', action='store', help='Set the FILTER to %(dest)s')

        # argparse.REMAINDER is an undocumented but very important feature.
        # Basically it's the only way to make positional arguments that start with dashes not be treated as bad options.
        parser.add_argument('REMAINDER', nargs=argparse.REMAINDER, action='store') # TODO: somehow don't show this in the help

    @classmethod
    def execute(cls, ctx: ff.FlamContext, args: argparse.Namespace) -> None:
        if args.delete:
            cls.delete(ctx, args)
        elif args.print:
            cls.print(ctx, args)
        # Default edit/create.
        else:
            try:
                composite_list = ctx.composite_lists.get_by_name(args.NAME)
            except ff.InputError:
                cls.create(ctx, args)
            else:
                cls.edit(ctx, args, composite_list)

    @classmethod
    def delete(cls, ctx: ff.FlamContext, args: argparse.Namespace) -> None:
        if args.NAME is None:
            raise ff.InputError(f"Must specify a NAME to delete a composite list.")

        composite_list = ctx.composite_lists.get_by_name(args.NAME)
        assert not isinstance(composite_list.uid, ff.UnsetType)
        ctx.delete_composite_list(composite_list.uid)
        ctx.write_cfg()

    @classmethod
    def print(cls, ctx: ff.FlamContext, args: argparse.Namespace) -> None:
        # TODO: improve this in the future
        if args.NAME is None:
            for cl in ctx.composite_lists:
                print(cl)
        else:
            print(ctx.composite_lists.get_by_name(args.NAME))

    @classmethod
    def edit(cls, ctx: ff.FlamContext, args: argparse.Namespace, composite_list: ff.CompositeList) -> None:
        if args.rename is not None:
            composite_list.name = args.rename

        simple_list_names, filter_tokens = split_at_filter(args.LIST + args.FILTER)

        if len(simple_list_names) > 0:
            # The unset check should always be true, but the type checker wants it.
            composite_list.simple_list_uids = [sl_uid for sl_name in simple_list_names if not isinstance(sl_uid := ctx.simple_lists.get_by_name(sl_name).uid, ff.UnsetType)]

        if len(filter_tokens) > 0:
            # Don't have anything to do with this for now, but we can raise an exception if it doesn't compile.
            ctx.compile_filter(filter_tokens, ff.FindableType.MOVIES)
            composite_list.filter_tokens = filter_tokens

        if args.default_fetch != Choice.AUTO:
            composite_list.is_default_fetch = args.default_fetch == Choice.YES

        if args.default_find != Choice.AUTO:
            composite_list.is_default_find = args.default_find == Choice.YES

        # TODO: regenerate the composite list/mark it dirty so it gets regenerated? Probably should be an internal thing to the API.
        ctx.write_cfg()

    @classmethod
    def create(cls, ctx: ff.FlamContext, args: argparse.Namespace) -> None:
        if args.NAME is None:
            raise ff.InputError(f"Must specify a NAME to create or edit a composite list.")

        simple_list_names, filter_tokens = split_at_filter(args.LIST + args.FILTER)

        composite_list = ff.CompositeList.create(
            name = args.NAME,
            simple_list_uids = [ctx.simple_lists.get_by_name(sl_name).uid for sl_name in simple_list_names],
            filter_tokens = filter_tokens,
            is_default_fetch = args.default_fetch == Choice.YES,
            is_default_find = args.default_find == Choice.YES,
        )

        ctx.add_composite_list(composite_list)
        ctx.write_cfg()

class SubcommandFetch:
    @classmethod
    def add_parser(cls, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser('fetch', formatter_class=argparse.RawTextHelpFormatter)
        parser.set_defaults(function=cls.execute)
        
        parser.add_argument('-u', '--undo', action='store_true', help="Restore LISTDEFs to their previous versions."
            "Fetch can be expensive so if something goes wrong and files get messed up this is good to have.")
        parser.add_argument('-s', '--from-scratch', action='store_true', help="Don't try to update existing fetched lists. Refetch everything from scratch.") # TODO: re-implement some nicer way
        parser.add_argument('-r', '--refetch', metavar='PATTERN', default=None, action='store', help=
            '''Forces titles that match %(metavar)s (case-insensitive) to be redownloaded even if they are already locally stored.
It's enough for %(metavar)s to match any part of the title, not necessarily the whole title.
%(metavar)s uses regex syntax from python's re library, which is identical to egrep unless you use very advanced features.
This feature is intended for redownloading shows after a new season has come out.''')

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

If no %(dest)s provided, fetches all lists configured as defaults.''')

    @classmethod
    def execute(cls, ctx: ff.FlamContext, args: argparse.Namespace) -> None:
        # TODO: Hate this feature. It should either be scratched or changed to be a CLI feature that we backup the entire folder
        if args.undo:
            pass
        else:
            # TODO: maybe defaults shouldn't be configured on the API side, maybe it's more of a CLI thing and we should have our own separate configuration for it.
            listdefs = args.LISTDEF if len(args.LISTDEF) != 0 else [ff.SpecialListType.DEFAULTS]
            ctx.fetch(listdefs, refetch_pattern=args.refetch, quiet=False)

class SubcommandClean:
    @classmethod
    def add_parser(cls, subparsers: argparse._SubParsersAction) -> None:
        # TODO: still gotta figure this one out. Maybe it should just be flags in the other commands? I don't want to complicate this program with "not user friendly" subcommands.
        parser = subparsers.add_parser('clean', formatter_class=argparse.RawTextHelpFormatter)
        parser.set_defaults(function=cls.execute)
        parser.add_argument('-t', '--tempfiles', action='store_true', help='Deletes tempfiles related to the %(dest)s as well')
        parser.add_argument('-f', '--fetched', action='store_true', help='Deletes tempfiles related to the %(dest)s as well')
        parser.add_argument('-a', '--all', action='store_true', help='Delete everything fetched or stored by this program')

        parser.add_argument('LISTDEF', nargs='*', action='store', help=
            '''Like find. Will delete ''')

    @classmethod
    def execute(cls, ctx: ff.FlamContext, args: argparse.Namespace) -> None:
        print('clean')

class SubcommandFind:
    @classmethod
    def add_parser(cls, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser('find', formatter_class=argparse.RawTextHelpFormatter)
        parser.set_defaults(function=cls.execute)

        # TODO: "--split" option to expand array attributes into a row for each one?
        parser.add_argument('-s', '--sort', metavar='KEYS', type=str, default=['leaving', 'runtime', 'alpha', 'dunnolol'], action='store', help= # TODO: type=sort_aliases
            f'''Sort movies according to %(metavar)s, which is a comma-delimited list of keys to sort by, in decreasing priority. Defaults to 'leaving,runtime,alphabetical'.
            Valid sort keys: ...''')
        parser.add_argument('-c', '--color', choices=Choice.always_auto_never(), default=Choice.AUTO, action='store', help=
            'Set whether columns should be colored. Defaults to %(default)s')
        parser.add_argument('-d', '--dsv', metavar='DELIM', default=None, action='store', help=
            "Output in delimiter-separated values format (DSV).")
        parser.add_argument('-C', '--columns', metavar='COLUMNS', action='store', default=None, help=
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

        # TODO: future problem: REMAINDER doesn't work if there are no positional arguments before it. If we add the shorthand subcommands a la "flam WHAT",
        # the WHAT won't be a positional argument anymore and REMAINDER won't work.
        parser.add_argument('FINDABLE', type=cls.parse_findable, action='store', help= # TODO: support comma-delimited crew types? If ROLES, use all crew types.
            '''Choose what to find: movies, people, or roles. Roles have all the attributes of the movie and the person, and then a few role-specific ones.''')
        parser.add_argument('LISTDEF', nargs='*', action='store', help=
            '''Like fetch but with different defaults, and if the LISTDEFs aren't already fetched, it fails with a nice error message.''')
        parser.add_argument('FILTER', nargs='*', action='store', help=
            '''find-like expression featuring predicates like -crew, -cast, -release...''')
        parser.add_argument('REMAINDER', nargs=argparse.REMAINDER, action='store')

    @classmethod
    def parse_findable(cls, findable: str) -> tuple[ff.FindableType, list[tuple[ff.GroupMode, None | ff.CrewType]]]:
        if findable == ff.FindableType.ROLES:
            return ff.FindableType.ROLES, list(zip([ff.GroupMode.DEFAULT] * len(ff.CrewType), ff.CrewType))

        if findable in ff.FindableType:
            return ff.FindableType(findable), [(ff.GroupMode.DEFAULT, None)]

        modal_crew_types = []

        for modal_crew_type in findable.split(','):
            colon_idx = modal_crew_type.find('=')
            group_mode, crew_type = (modal_crew_type[:colon_idx], modal_crew_type[colon_idx + 1:]) if colon_idx != -1 else (ff.GroupMode.DEFAULT, modal_crew_type)
            modal_crew_types.append((ff.GroupMode(group_mode), ff.CrewType(crew_type)))

        return ff.FindableType.ROLES, modal_crew_types # type: ignore

    @classmethod
    def execute(cls, ctx: ff.FlamContext, args: argparse.Namespace) -> None:
        findable_type, modal_crew_types = args.FINDABLE
        is_additive, attributes = cls.parse_columns(args, findable_type, ctx)

        listdefs, filter_tokens = split_at_filter(args.LISTDEF + args.FILTER)
        filter = ctx.compile_filter(filter_tokens, findable_type)

        movie_list = ctx.get_movie_list(listdefs if len(listdefs) > 0 else ff.SpecialListType.DEFAULTS)

        values = list(cls.extract_values(attributes, movie_list, filter, modal_crew_types, args))
        cls.sort_values(attributes, values, args)
        table = list(cls.build_table(attributes, values, args))
        cls.print_table(table, args)

    # Can't do this at argparse time because it depends on the context.
    @classmethod
    def parse_columns(cls, args: argparse.Namespace, findable_type: ff.FindableType, ctx: ff.FlamContext) -> tuple[bool, list[ff.Attribute]]:
        is_additive = args.columns is None or args.columns.startswith('+')
        columns = [] if args.columns is None else args.columns.removeprefix('+').split(',')

        if is_additive:
            # TODO: Decide on default columns for PEOPLE, ROLES, and also what do we do about the 'leaving' column? Also uniq_append!
            match findable_type:
                case ff.FindableType.MOVIES:
                    columns = ['title', 'leaving', 'runtime', 'released', 'rating', 'metascore', 'director'] + columns
                case ff.FindableType.PEOPLE:
                    pass
                case ff.FindableType.ROLES:
                    pass
                case _:
                    raise RuntimeError(f"Unexpected {findable_type=}")

        # TODO: "smart" columns
        # if sk_watched in sort_keys:
        #     uniq_append(column_keys, ck_watched)

        # if sk_votes in sort_keys:
        #     uniq_append(column_keys, ck_votes)

        # if sk_myrating in sort_keys:
        #     uniq_append(column_keys, ck_myrating)

        # if sk_description in sort_keys:
        #     uniq_append(column_keys, ck_description)
            
        # if len(jsonfiles) > 1:
        #     uniq_append(column_keys, ck_source)
        
        attributes = [ctx.attributes[c] for c in columns]
        return is_additive, attributes

    @classmethod
    def extract_values(cls, attributes: list[ff.Attribute], movie_list: ff.MovieList, filter: ff.Filter,
            modal_crew_types: list[tuple[ff.GroupMode, None | ff.CrewType]], args: argparse.Namespace) -> typing.Iterable[list[typing.Any]]:
        for group_mode, crew_type in modal_crew_types:
            for findable in movie_list.find(filter.findable_type, crew_type=crew_type, group_mode=group_mode, filter=filter):
                yield [findable.extract(attr) for attr in attributes]

    @classmethod
    def sort_values(cls, attributes: list[ff.Attribute], values: list[list[typing.Any]], args: argparse.Namespace) -> None:
        # TODO: this.
        pass

    @classmethod
    def build_table(cls, attributes: list[ff.Attribute], values: list[list[typing.Any]], args: argparse.Namespace) -> typing.Iterable[list[str]]:
        if not args.no_titles:
            yield [attr.name for attr in attributes]

        for record in values:
            yield [attributes[i].type_handler.stringify(record[i]) for i in range(len(attributes))]

    @classmethod
    def print_table(cls, table: list[list[str]], args: argparse.Namespace) -> None:
        if not args.verbose:
            for row in table:
                for i in range(len(row)):
                    row[i] = clampstr(row[i])

        match args.color:
            case Choice.AUTO:
                use_color = sys.stdout.isatty()
            case Choice.ALWAYS:
                use_color = True
            case Choice.NEVER:
                use_color = False
            case _:
                raise RuntimeError(f"Unexpected {args.color=}")

        match args.paginate:
            case Choice.AUTO:
                paginate = sys.stdout.isatty() and os.get_terminal_size().lines < len(table) and shutil.which('less') is not None
                args.spacious |= paginate
            case Choice.ALWAYS:
                paginate = True
            case Choice.NEVER:
                paginate = False
            case _:
                raise RuntimeError(f"Unexpected {args.paginate=}")

        # Pipe to less if requested. I tried a lot of variations including of course Popen(stdin=PIPE), this is the only one that works.
        # Note: This program hits a harmless 'OSError [Errno 22]' when piping to less.
        # This fixes it: https://stackoverflow.com/a/66874837/12553917, but I'm worried about the consequences of using this and it's not worth the hassle.
        with tempfile.NamedTemporaryFile('w', encoding='utf-8') if paginate else contextlib.nullcontext(sys.stdout) as out: # type: ignore
            # Output as CSV.
            if args.dsv is not None:
                writer = csv.writer(out, delimiter=args.dsv)
                writer.writerows(table)
            else:
                # Output in a pretty table.
                line_spacing = '\n\n' if args.spacious else '\n'
                out.write(line_spacing.join(utils.tabulate(
                    table,
                    fillchar = '.' if use_color else ' ', 
                    use_color = use_color,
                    header_color = '' if args.no_titles else '\033[4m\033[K' # Underline, not supported by colorama.
                )))
            
            out.flush()

            if paginate:
                try:
                    subprocess.call(['less', '-RS', out.name])
                except Exception as e:
                    raise ff.InputError(f"Pagination failed with error: {e}. You probably don't have less installed.") from e

class SubcommandChart:
    @classmethod
    def add_parser(cls, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser('chart', formatter_class=argparse.RawTextHelpFormatter)
        parser.set_defaults(function=cls.execute)

        parser.add_argument('-o', '--omit-zeroes', choices=Choice.always_auto_never(), default=Choice.AUTO, action='store', help=
            'Choose whether to omit buckets with 0 movies. Defaults to %(default)s, which uses a mode that depends on DISTRIBUTION.')
        parser.add_argument('-v', '--value-sort', default=False, action='store_true', help='Sort based on the table values, not the keys.')
        parser.add_argument('-n', '--no-number', default=False, action='store_true', help="Don't append the numerical value to each bar.")
        parser.add_argument('-S', '--spacious', default=False, action='store_true', help='Space out the table.')
        parser.add_argument('-t', '--no-title', default=False, action='store_true', help="Don't print a title.")
        parser.add_argument('-k', '--no-prefix-key', default=False, action='store_true', help="Don't write the key at the start of each bar.")
        parser.add_argument('-K', '--suffix-key', default=False, action='store_true', help='Append the key to the end of each bar.')
        
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
    def execute(cls, ctx: ff.FlamContext, args: argparse.Namespace) -> None:
        print('chart')

def main() -> None:
    colorama.just_fix_windows_console()

    # This is needed. Trust me.
    try:
        sys.stdout.reconfigure(encoding='utf-8', newline='\n') # type: ignore
    except:
        ff.logger.error(f"Failed to reconfigure stdout", exc_info=True)

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description='I dunno lol.')
    parser.add_argument('-C', '--flam-dir', metavar='PATH', default=ff.FlamContext.DEFAULT_FLAM_DIR, action='store', help=
        f'Use %(metavar)s as the flam directory. Uses {ff.FlamEnv.CTX_DIR} environment variable by default, or ~/.film_flam if it is not defined.')
    parser.add_argument('-e', '--no-extensions', action='store_true', help=
        "Don't import configured extensions.")

    # Subparsers are organized into "static" classes. This is only for code organization reasons, not OOP reasons.
    # The classes are designed to enforce as little "model" as possible so we can be flexible with how we use them.
    subparsers = parser.add_subparsers(required=True)
    SubcommandConfig.add_parser(subparsers)
    SubcommandFetch.add_parser(subparsers)
    SubcommandFind.add_parser(subparsers) # TODO: flam movies/roles/people as a subcommand shorthand for flam find movies/roles/people
    SubcommandChart.add_parser(subparsers)

    args = parser.parse_args()

    # We use the FILTER, REMAINDER trick a lot so we take care of it generically.
    if hasattr(args, 'FILTER') and hasattr(args, 'REMAINDER'):
        args.FILTER += args.REMAINDER

    ctx = ff.FlamContext(args.flam_dir, import_extensions=not args.no_extensions)

    try:
        args.function(ctx, args)
    except ff.FlamError as e:
        if ff.is_debug():
            raise

        # No ugly tracebacks for input errors. Only for internal errors.
        sys.exit(f'{os.path.basename(__file__)}: error: {e}')

if __name__ == '__main__':
    main()
