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

import filmflam.repo as repo
import filmflam.fetching as fetching
import filmflam.filtering as filtering
import filmflam.exceptions as exceptions

class Choice(enum.StrEnum):
    YES     = 'yes'
    NO      = 'no'
    ALWAYS  = 'always'
    NEVER   = 'never'
    AUTO    = 'auto'

    @classmethod
    def always_auto_never(cls) -> list[str]:
        return [cls.ALWAYS, cls.AUTO, cls.NEVER]

    @classmethod
    def yes_no_auto(cls) -> list[str]:
        return [cls.YES, cls.NO, cls.AUTO]

    def __repr__(self) -> str:
        return str(self)

def split_at_filter(positional_args):
    filter_begin = next((i for i, arg in enumerate(positional_args) if filtering.is_filter_token(arg)), len(positional_args))
    return positional_args[:filter_begin], positional_args[filter_begin:]

def subcommand_config_list(ctx, args):
    if args.delete:
        config_list_delete(ctx, args)
    elif args.print:
        config_list_print(ctx, args)
    # Default edit/create.
    elif (remote_list := next((rl for rl in ctx.cfg.remote_lists if rl.name == args.NAME), None)) is not None:
        config_list_edit(ctx, args, remote_list)
    else:
        config_list_create(ctx, args)

def config_list_delete(ctx, args):
    if args.NAME is None:
        raise exceptions.InputError(f"Must specify a NAME to delete a list.")

    remote_list = ctx.cfg.get_remote_list_by_name(args.NAME)
    ctx.delete_remote_list(remote_list.uid)
    ctx.write_cfg()

def config_list_print(ctx, args):
    # TODO: improve this in the future
    if args.NAME is None:
        for rl in ctx.cfg.remote_lists:
            print(rl)
    else:
        print(ctx.get_remote_list_by_name(args.NAME))

def config_list_edit(ctx, args, remote_list):
    if args.rename is not None and args.rename != remote_list.name:
        remote_list.name = args.rename

    if args.LISTDEF is not None:
        cldef = ctx.canonicalize_listdef(args.LISTDEF)
        remote_list.fetcher_type = cldef.fetcher_type
        remote_list.address = cldef.address

    if args.default_fetch != Choice.AUTO:
        remote_list.is_default_fetch = args.default_fetch == Choice.YES

    if args.default_find != Choice.AUTO:
        remote_list.is_default_find = args.default_find == Choice.YES

    ctx.write_cfg()

def config_list_create(ctx, args):
    if args.NAME is None:
        raise exceptions.InputError(f"Must specify a NAME to create or edit a list.")

    if args.LISTDEF is None:
        raise exceptions.InputError(f"List '{args.NAME}' doesn't exist, so LISTDEF is required.")

    cldef = ctx.canonicalize_listdef(args.LISTDEF)

    remote_list = repo.RemoteList.create(
        name = args.NAME,
        fetcher_type = cldef.fetcher_type,
        address = cldef.address,
        is_default_fetch = args.default_fetch != Choice.NO,
        is_default_find = args.default_find == Choice.YES,
    )

    ctx.add_remote_list(remote_list)
    ctx.write_cfg()

def subcommand_config_compound(ctx, args):
    if args.delete:
        config_compound_delete(ctx, args)
    elif args.print:
        config_compound_print(ctx, args)
    # Default edit/create.
    elif (compound_list := next((cl for cl in ctx.cfg.compound_lists if cl.name == args.NAME), None)) is not None:
        config_compound_edit(ctx, args, compound_list)
    else:
        config_compound_create(ctx, args)

def config_compound_delete(ctx, args):
    if args.NAME is None:
        raise exceptions.InputError(f"Must specify a NAME to delete a compound list.")

    compound_list = ctx.cfg.get_compound_list_by_name(args.NAME)
    ctx.delete_compound_list(compound_list.uid)
    ctx.write_cfg()

def config_compound_print(ctx, args):
    # TODO: improve this in the future
    if args.NAME is None:
        for cl in ctx.cfg.compound_lists:
            print(cl)
    else:
        print(ctx.cfg.get_compound_list_by_name(args.NAME))

def config_compound_edit(ctx, args, compound_list):
    if args.rename is not None:
        compound_list.name = args.rename

    remote_list_names, filter_tokens = split_at_filter(args.LIST + args.FILTER)

    if len(remote_list_names) > 0:
        compound_list.remote_list_uids = [ctx.get_remote_list_by_name(rl_name).uid for rl_name in remote_list_names]

    if len(filter_tokens) > 0:
        # Don't have anything to do with this for now, but we can raise an exception if it doesn't compile.
        filtering.compile(filter_tokens)
        compound_list.filter_tokens = filter_tokens

    if args.default_fetch != Choice.AUTO:
        compound_list.is_default_fetch = args.default_fetch == Choice.YES

    if args.default_find != Choice.AUTO:
        compound_list.is_default_find = args.default_find == Choice.YES

    # TODO: regenerate the compound list/mark it dirty so it gets regenerated?
    ctx.write_cfg()

def config_compound_create(ctx, args):
    if args.NAME is None:
        raise exceptions.InputError(f"Must specify a NAME to create or edit a compound list.")

    remote_list_names, filter_tokens = split_at_filter(args.LIST + args.FILTER)

    compound_list = repo.CompoundList.create(
        name = args.NAME,
        remote_list_uids = [ctx.cfg.get_remote_list_by_name(rl_name).uid for rl_name in remote_list_names],
        filter_tokens = filter_tokens,
        is_default_fetch = args.default_fetch == Choice.YES,
        is_default_find = args.default_find == Choice.YES,
    )

    ctx.add_compound_list(compound_list)
    ctx.write_cfg()

def subcommand_clean(ctx, args):
    print('clean')

def subcommand_fetch(ctx, args):
    fetchers = fetching.parse_listdefs(args.LISTDEF if len(args.LISTDEF) != 0 else [repo.LISTDEF_DEFAULTS], ctx)

    for fetcher in fetchers:
        print(f"Fetching {ctx.canon_listdef_pretty(fetcher.abstract_listdef)}...")
        list_file, is_changed = fetcher.fetch(ctx, refetch_pattern=args.refetch, from_scratch=args.from_scratch, quiet=False)

def subcommand_find(ctx, args):
    print('find')

def subcommand_chart(ctx, args):
    print('chart')

def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description='I dunno lol.')
    parser.add_argument('-C', '--flam-dir', metavar='PATH', default=repo.FlamContext.DEFAULT_FLAM_DIR, action='store', help=
        'Use %(metavar)s as the flam directory. Uses FLAM_DIR environment variable by default, or ~/.film_flam if it is not defined.')

    subparsers = parser.add_subparsers(required=True)

    # Config options.
    config_parser = subparsers.add_parser('config', formatter_class=argparse.RawTextHelpFormatter)

    config_subparsers = config_parser.add_subparsers(required=True)

    # Config list.
    config_list_parser = config_subparsers.add_parser('list', formatter_class=argparse.RawTextHelpFormatter)
    config_list_parser.set_defaults(function=subcommand_config_list)

    config_list_parser_action_group = config_list_parser.add_mutually_exclusive_group(required=False)
    config_list_parser_action_group.add_argument('-E', '--edit', action='store_true', help='edit or create a list. This is the default behavior.')
    config_list_parser_action_group.add_argument('-D', '--delete', action='store_true', help='delete the list.')
    config_list_parser_action_group.add_argument('-P', '--print', action='store_true', help='print the list, or if NAME not provided, print all lists.')

    config_list_parser.add_argument('-n', '--rename', metavar='NEW_NAME', default=None, action='store', help='if renaming a list, this will be the new name %(metavar)s')
    config_list_parser.add_argument('-i', '--default-find', choices=Choice.yes_no_auto(), default=Choice.AUTO, action='store', help='decide if this list should be default for flam find')
    config_list_parser.add_argument('-e', '--default-fetch', choices=Choice.yes_no_auto(), default=Choice.AUTO, action='store', help='decide if this list should be fetched by default')
    config_list_parser.add_argument('NAME', action='store', nargs='?', default=None, help='Operate on the list named %(dest)s')
    config_list_parser.add_argument('LISTDEF', action='store', nargs='?', default=None, help='set the list type and address to %(dest)s')

    # Config compound list.
    config_compound_parser = config_subparsers.add_parser('compound', formatter_class=argparse.RawTextHelpFormatter)
    config_compound_parser.set_defaults(function=subcommand_config_compound)

    config_compound_parser_action_group = config_compound_parser.add_mutually_exclusive_group(required=False)
    config_compound_parser_action_group.add_argument('-E', '--edit', action='store_true', help='edit or create a compound list. This is the default behavior.')
    config_compound_parser_action_group.add_argument('-D', '--delete', action='store_true', help='delete the list.')
    config_compound_parser_action_group.add_argument('-P', '--print', action='store_true', help='print the list, or if NAME not provided, print all lists.')

    config_compound_parser.add_argument('-n', '--rename', metavar='NEW_NAME', default=None, action='store', help='if renaming a list, this will be the new name %(metavar)s')
    config_compound_parser.add_argument('-i', '--default-find', choices=Choice.yes_no_auto(), default=Choice.AUTO, action='store', help='decide if this list should be default for flam find %(metavar)s')
    config_compound_parser.add_argument('-e', '--default-fetch', choices=Choice.yes_no_auto(), default=Choice.AUTO, action='store', help='decide if this list should be fetched by default %(metavar)s')
    config_compound_parser.add_argument('NAME', nargs='?', action='store', default=None, help='Operate on the list named %(dest)s')
    config_compound_parser.add_argument('LIST', nargs='*', action='store', help='Set the list names to %(dest)s')
    config_compound_parser.add_argument('FILTER', nargs='*', action='store', help='Set the FILTER to %(dest)s')

    # argparse.REMAINDER is an undocumented but very important feature.
    # Basically it's the only way to make positional arguments that start with dashes not be treated as bad options.
    config_compound_parser.add_argument('REMAINDER', nargs=argparse.REMAINDER, action='store') # TODO: somehow don't show this in the help

    # Clean options.
    # TODO: still gotta figure this one out. Maybe it should just be flags in the other commands?
    clean_parser = subparsers.add_parser('clean', formatter_class=argparse.RawTextHelpFormatter)
    clean_parser.set_defaults(function=subcommand_clean)
    clean_parser.add_argument('-t', '--tempfiles', action='store_true', help='Deletes tempfiles related to the %(dest)s as well')
    clean_parser.add_argument('-f', '--fetched', action='store_true', help='Deletes tempfiles related to the %(dest)s as well')
    clean_parser.add_argument('-a', '--all', action='store_true', help='Delete everything fetched or stored by this program')

    clean_parser.add_argument('LISTDEF', nargs='*', action='store', help=
        '''Like find. Will delete ''')

    # Fetch options.
    fetch_parser = subparsers.add_parser('fetch', formatter_class=argparse.RawTextHelpFormatter)
    fetch_parser.set_defaults(function=subcommand_fetch)
    fetch_parser.add_argument('-s', '--from-scratch', action='store_true', help="Don't try to update existing fetched lists. Refetch everything from scratch.")
    fetch_parser.add_argument('-r', '--refetch', metavar='PATTERN', default=None, action='store', help=
        '''Forces titles that match %(metavar)s (case-insensitive) to be redownloaded even if they are already locally stored.
It's enough for %(metavar)s to match any part of the title, not necessarily the whole title.
%(metavar)s uses regex syntax from python's re library, which is identical to egrep unless you use very advanced features.
This feature is intended for redownloading shows after a new season has come out.''')

    fetch_parser.add_argument('LISTDEF', nargs='*', action='store', help=
        '''Each %(dest)s describes a list to fetch. Supports, in order of priority:
1. Configured list name (type: list)
2. Configured compound list name (will fetch all lists under it) (type: compound)
3. Address to fetch the list from (IMDb list id for instance). But for these the type is not inferred, you must specify it.

To avoid ambiguity and for downloading addresses directly, you can specify the %(dest)s type by writing <type>=%(dest)s. Supported types are:
* 'list'
* 'compound'
* 'imdb-id'
* 'imdb-private-id'
* 'imdb-csv'
* Any custom types you define...

If no %(dest)s provided, fetches all lists configured as defaults.''')

    find_parser = subparsers.add_parser('find', formatter_class=argparse.RawTextHelpFormatter)
    find_parser.set_defaults(function=subcommand_find)

    # The idea is that we have movie-specific attributes, person-specific attributes, and role-specific attributes. Instead of the idea that an attribute "merges" when you go from roles->people,
    # these are just 3 exclusive sets of attributes and when you find movies, you can only query (or print) movie-specific attributes (like the title of the film),
    # when you find people, you can only query people-specific attributes (like if the movies they've been in contains one matching a title),
    # and when you find roles, you can query attributes on the movie, on the person, or on the role like which crew type is it.

    # TODO: flam movies/roles/people as a subcommand shorthand for flam find movies/roles/people

    # What if you find people/movies/roles and the question of which crew types is a filter, not a "what"?
    # For "lesser" attributes, a --split option will suffice. --what is only for movies/people/roles.

    # Some decisions:
    # 1. movies that get filtered don't affect attributes of a person related to that movie. For instance, the average rating still factors in that movie.
    # 2. the way to omit movies from the computation entirely is to define a metalist for them
    # 3. metalists are only for movies. You cannot save into the metalist that it's actually about roles or people
    find_parser.add_argument('-s', '--sort', metavar='KEYS', type=None, default=['leaving', 'runtime', 'alpha', 'dunnolol'], action='store', help= # TODO: type=sort_aliases
        f'''Sort movies according to %(metavar)s, which is a comma-delimited list of keys to sort by, in decreasing priority. Defaults to 'leaving,runtime,alphabetical'.
        Valid sort keys: ...''')
    find_parser.add_argument('-g', '--group', metavar='CREWS', type=None, default='', action='store', help= # TODO: type=crew_aliases
        f'''Force apply grouping for these crew types''')
    find_parser.add_argument('-G', '--ungroup', metavar='CREWS', type=None, default='', action='store', help= # TODO: type=crew_aliases
        f'''Force apply non-grouping for these crew types''')
    find_parser.add_argument('-c', '--color', choices=Choice.always_auto_never(), default=Choice.AUTO, action='store', help=
        'Set whether columns should be colored. Defaults to %(default)s')
    find_parser.add_argument('-d', '--dsv', metavar='DELIM', default=None, action='store', help=
        "Output in delimiter-separated values format (DSV).")
    find_parser.add_argument('-C', '--columns', metavar='COLUMNS', type=None, action='store', default=(True, []), help= # TODO: type=column_aliases
        'List of columns to print, delimited by commas. Defaults to \'title,leaving,runtime,released,rating,metascore,director\','
        f''' with a few other "smart" columns which activate when a condition is met.
This option overrides the defaults and smart columns. Only the columns you specify will be printed.
Beginning this string with a '+' will cause the columns to be added to the default (and smart) columns instead of replacing them.
If %(metavar)s is '*', will print all columns.
Valid column names: ...''')
    find_parser.add_argument('-v', '--verbose', default=False, action='store_true', help=
        'Use verbose output, like writing the full release date instead of just the year, and not chopping long strings')
    find_parser.add_argument('-r', '--reverse', default=False, action='store_true', help=
        'Reverse the sort order. By default some sort keys are ascending and some descending based on what makes sense to me. This reverses those defaults')
    find_parser.add_argument('-S', '--spacious', default=False, action='store_true', help=
        'Add an empty line between entries')
    find_parser.add_argument('-P', '--paginate', choices=Choice.always_auto_never(), default=Choice.AUTO, action='store', help=
        'Choose whether to paginate with less. Defaults to %(default)s, which depends on the size of the output')
    find_parser.add_argument('-f', '--date-format', metavar='FORMAT', default=None, action='store', help=
        'Override format for date columns. Default depends on verbosity and which column. See python datetime.strftime documentation for format syntax')
    find_parser.add_argument('-t', '--no-titles', default=False, action='store_true', help=
        'Don\'t print a row with the column titles')

    # TODO: future problem: REMAINDER doesn't work if there are no positional arguments before it. If we add the shorthand subcommands a la "flam WHAT",
    # the WHAT won't be a positional argument anymore and REMAINDER won't work.
    find_parser.add_argument('WHAT', choices=['movies', 'people', 'roles'], action='store', help=
        '''Choose what to find: movies, people, or roles. Roles have all the attributes of the movie and the person, and then a few role-specific ones.''')
    find_parser.add_argument('LISTDEF', nargs='*', action='store', help=
        '''Like fetch but with different defaults, and if the LISTDEFs aren't already fetched, it fails with a nice error message.''')
    find_parser.add_argument('FILTER', nargs='*', action='store', help=
        '''find-like expression featuring predicates like -crew, -cast, -release...''')
    find_parser.add_argument('REMAINDER', nargs=argparse.REMAINDER, action='store')

    # Chart options.
    chart_parser = subparsers.add_parser('chart', formatter_class=argparse.RawTextHelpFormatter)
    chart_parser.set_defaults(function=subcommand_chart)

    chart_parser.add_argument('-o', '--omit-zeroes', choices=Choice.always_auto_never(), default=Choice.AUTO, action='store', help=
        'Choose whether to omit buckets with 0 movies. Defaults to %(default)s, which uses a mode that depends on DISTRIBUTION.')
    chart_parser.add_argument('-v', '--value-sort', default=False, action='store_true', help='Sort based on the table values, not the keys.')
    chart_parser.add_argument('-n', '--no-number', default=False, action='store_true', help="Don't append the numerical value to each bar.")
    chart_parser.add_argument('-S', '--spacious', default=False, action='store_true', help='Space out the table.')
    chart_parser.add_argument('-t', '--no-title', default=False, action='store_true', help="Don't print a title.")
    chart_parser.add_argument('-k', '--no-prefix-key', default=False, action='store_true', help="Don't write the key at the start of each bar.")
    chart_parser.add_argument('-K', '--suffix-key', default=False, action='store_true', help='Append the key to the end of each bar.')
    
    # TODO: Not sure about these options yet:
    # '-c', '--crew-types',  CREWS      Comma-delimited list of crew types to count in crew-size distribution. Defaults to '*', which means all crew types.
#     chart_parser.add_argument('-f', '--factor', metavar='FACTOR', type=int, action='store', default=0, help=
#         '''Define custom scaling factor to apply to the table. Defaults to %(default)s, which means a value will be computed to make the table fit in the terminal width.
# Positive numbers stretch, negatives squish.''')

    chart_parser.add_argument('DISTRIBUTION', action='store', help=
        '''Which distribution to view (also option for custom distribution based on a field?)''')
    chart_parser.add_argument('LISTDEF', nargs='+', action='store', help=
        '''Like find''')
    chart_parser.add_argument('FILTER', nargs='*', action='store', help=
        '''find-like expression featuring predicates like -crew, -cast, -release...''')

    args = parser.parse_args()

    # We use the FILTER, REMAINDER trick a lot so we take care of it generically.
    if hasattr(args, 'FILTER') and hasattr(args, 'REMAINDER'):
        args.FILTER += args.REMAINDER

    ctx = repo.FlamContext(args.flam_dir)

    try:
        args.function(ctx, args)
    except (exceptions.InputError, exceptions.FetchInterrupt) as e:
        # No ugly tracebacks for input errors. Only for internal errors.
        sys.exit(f'{os.path.basename(__file__)}: error: {e}')

if __name__ == '__main__':
    main()

# flam browse
# mbrowse but with pivoting around either people, or movies, or both, and possibly with find-like filter syntax as explained below
# Sample: flam browse --pivot both movies shows -cast tarantino -release +2019 -release -2022
# Problems: 1. Not sure I like this way of specifying the pivot 2. with mgrep you can search *all* crew types, but with mbrowse I thought we'd be pivoting on a single crew type
# Solution to 2: in addition to -cast, -director, etc. prereqs, also have a -crew prereq that checks if he is in any crew type. And when pivoting around people COMBINED with movies,
# have a column which says which crew types he is in this movie?

# flam grep (or search, look, find)
# Actually I think this makes more sense as an option/subcommand of browse. It's basically a filter on mbrowse results,
# and we could even merge the syntax used to filter movies in categories with the syntax used to grep them here.
# Also I think "flam find" with find-like filter syntax could be great. Could do things like ' -title "lord.*rings" ', with aliases and all, to check if column equals expected.
# And could have prereqs to filter movie fields or people fields.

# flam dist (or graph, chart)
# Take the people/movies output by browse (filters and all) and create distributions out of it like mdist

# Thought: it sounds like all we want is fetch & browse, and everything else (grep, dist) are basically a feature of browse. So maybe we need to do the git "plumbing/porcelain" thing.
# That is: actually have a plumbing command which creates basically the output of mbrowse but as a JSON. browse, dist, grep, then take that result and print it the desired way.
# Is grep even necessary then?
# Maybe the "plumbing" command should be an internal function, not a command?
