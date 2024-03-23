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


import filmflam.flam as flam

def main():
    flam.helloworld()

if __name__ == '__main__':
    main()


# Subcommands:
# flam config
# Define your lists, categories, maybe where the movie folder is, etc.
# Similar field-by-field prompts like gh release?

# flam fetch <list-def>...
# Downloads lists and generates files from those lists, I'm thinking of generating more than just list JSONs to accelerate things like grouping,
# also possibly output in a file format made to be more quickly machine-readable than JSON,
# because I want to avoid pre-generating mprint outputs and instead favor dynamically whipping up whichever prompt you have.
# OR only generate the bare minimum, and in browse/grep cache the additional files.
# Also write it with an abstraction layer that will let us replace which API we use instead of cinemagoer,
# so that we'll be able to add support for letterboxd, or if cinemagoer shits the bed one day.
# The idea is <list-def> can be a configured list name, or a list id, or a csv file, and we will use the right "ListLoader" for the type of list address.
# I want this part to be extensible, so that people can add their own ListLoaders.
# To avoid amguity, maybe allow to specify the def-type to override the usual priority order, like: name=movies, csv=... or listid=...
# Problem: how to distinguish lists to download with the browser vs lists to download via curl?

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
