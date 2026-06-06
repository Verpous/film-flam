#! /bin/bash

# Copyright (C) 2026 Aviv Edery.

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# Makefiles are crap for anything other than compiling things. We just want helper functions for development so it's better to use a "make-like" bash script.

shopt -s extglob
shopt -s globstar

# Below this point assume we are in the project directory.
project_folder="$(dirname -- "$BASH_SOURCE")"
cd "$project_folder"

mdl=flam
cli=flam
pkg=the-film-flam
build=dist
docs=docs

flam_dir=.film_flam_dev
srcfiles=($mdl/*.py test_extensions.py)
profiles=profiles

pylint_ignore+=C0103, # invalid-name
pylint_ignore+=C0104, # disallowed-name
pylint_ignore+=C0114, # missing-module-docstring
pylint_ignore+=C0115, # missing-class-docstring
pylint_ignore+=C0116, # missing-function-docstring
pylint_ignore+=C0200, # consider-using-enumerate
pylint_ignore+=C0301, # line-too-long
pylint_ignore+=C0302, # too-many-lines
pylint_ignore+=C0303, # trailing-whitespace
pylint_ignore+=C0325, # superfluous-parens
pylint_ignore+=C0411, # wrong-import-order
pylint_ignore+=C0413, # wrong-import-position
pylint_ignore+=C0415, # import-outside-toplevel
pylint_ignore+=C3001, # unnecessary-lambda-assignment

pylint_ignore+=R0401, # cyclic-import
pylint_ignore+=R0402, # consider-using-from-import
pylint_ignore+=R0801, # duplicate-code
pylint_ignore+=R0902, # too-many-instance-attributes
pylint_ignore+=R0903, # too-few-public-methods
pylint_ignore+=R0911, # too-many-return-statements
pylint_ignore+=R0912, # too-many-branches
pylint_ignore+=R0913, # too-many-arguments
pylint_ignore+=R0914, # too-many-locals
pylint_ignore+=R0915, # too-many-statements
pylint_ignore+=R0917, # too-many-positional-arguments
pylint_ignore+=R1708, # stop-iteration-return
pylint_ignore+=R1714, # consider-using-in
pylint_ignore+=R1735, # use-dict-literal
pylint_ignore+=W0124, # confusing-with-statement
pylint_ignore+=W0212, # protected-access
pylint_ignore+=W0511, # fixme
pylint_ignore+=W0602, # global-variable-not-assigned
pylint_ignore+=W0603, # global-statement
pylint_ignore+=W0622, # redefined-builtin
pylint_ignore+=W0702, # bare-except
pylint_ignore+=W1514, # unspecified-encoding
pylint_ignore+=W1203, # logging-fstring-interpolation

# Installs flam. Supports multiple install flavors: 'local' (for development, the default), 'test' (install from the test pypi site), and 'actual' (install the actual release).
install() {
    uninstall

    case "${1,,}" in
        ""|local)
            pip install -e .
            ;;
        test)
            # https://test.pypi.org/project/film-flam/
            pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ $pkg
            ;;
        actual)
            pip install $pkg
            ;;
        *)
            echo "Invalid install flavor: '$1'" >&2
            false
            ;;
    esac
}

# Uninstalls flam.
uninstall() {
    pip uninstall -y $pkg
}

# Creates AND PUBLISHES a flam release! Supports release flavors: 'test' (upload to the test pypi site), or 'actual' (upload to the real pypi site).
release() {
    case "${1,,}" in
        ""|test)
            local flavor=test
            local twineargs="--repository testpypi"
            ;;
        actual)
            local flavor=actual
            local twineargs=""
            ;;
        *)
            echo "Invalid release flavor: '$1'" >&2
            false
            ;;
    esac

    # Clean the old build, old docs, old version file, etc.
    clean
    _gen_requirements
    local version="$(_gen_version $flavor)"

    # Special thanks to the magical person who wrote this guide: https://olgarithms.github.io/sphinx-tutorial/docs/7-hosting-on-github-pages.html
    # We'll be pushing the new docs by mounting a worktree in the path where sphinx generates the html docs.
    # This needs to happen after the `clean` above, but that doesn't actually delete directories, so we must thorougly remove the directory first.
    html_worktree=docs/build/html
    rm -rf $html_worktree
    git worktree add --force --force $html_worktree gh-pages

    # Only after the worktree is created we should build files into it with sphinx.
    sphinx

    # Require mypy and pylint to report no problems.
    mypy > /dev/null
    pylint > /dev/null
    
    python -m build --outdir $build

    # Twine can fail with HTTP 403 if the API token is bad. There should be a ~/.pypirc with the API token, and it's also saved in my Bitwarden.
    twine upload --verbose $twineargs $build/*
    sanity $flavor

    # For actual releases only, publish the docs to GitHub Pages. They're hosted on https://verpous.github.io/film-flam/.
    if [[ "$flavor" == actual ]]; then
        (
            cd $html_worktree
            git add .
            git commit -m "docs for version $version"
            git push
        )
    fi

    echo "Successfully created a release with flavor: $flavor."
}

# Generates requirements.txt file for specifying to pip all flam dependencies.
_gen_requirements() {
    # I refuse to manually keep track of dependencies, so we use pipreqs. But pipreqs SUCKS:
    # 1. Some folders confuse pipreqs so we --ignore them.
    # 2. pipreqs identifies some packages by the wrong name, like cinemagoer is recognized by its old name, IMDbPY, so we rename them.
    # 3. pipreqs fails at identifying packages locally, instead resolving them from the PyPI server where it gets the version wrong,
    #    so we actually use pipreqs to get the names of packages, then grep them with the correct versions from pip freeze.
    _mktemp req_patterns

    # Don't pipe pipreqs to sed, instead write file with pipreqs and edit it inplace with sed. This is to not sweep pipreq failure under the rug.
    pipreqs --mode no-pin --print $mdl > "$req_patterns"
    sed -iE '
s/IMDbPY/cinemagoer/g
s/python_dateutil/python-dateutil/g
s/concurrent_log_handler/concurrent-log-handler/g
s/Requests/requests/g
s/currencyconverter/CurrencyConverter/g
s/.*/^\0==/g' "$req_patterns" # Add a "==" so that the next step will grep these packages exactly and not count substrings.
    grep -E --file="$req_patterns" <(pip freeze) | sed -E 's/==/>=/g' | tee _gen_requirements.txt

    # Sanity check that we didn't miss any packages.
    (( "$(command wc -l < "$req_patterns")" == "$(command wc -l < _gen_requirements.txt)" ))
}

# Code-generation of the file containing the current version from use from within the code. Supports all release flavors.
_gen_version() {
    # Don't actually create the file if it already exists. It can mess with a couple of places.
    [[ -f $mdl/_gen_version.py ]] && return

    {
        # We use date versioning because it requires the least manual intervention.
        # PyPI won't accept the same version twice, so in dev builds, we also version it with the epoch seconds.
        # NOTE: Not having leading zeroes is mandatory even though it sucks because it means we can't sort versions lexicographically.
        local datefmt
        [[ "$1" == actual ]] && datefmt=%Y.%-m.%-d || datefmt=%Y.%-m.%-d.dev%s
        local version="$(date +$datefmt)"

        echo "# AUTOGENERATED FILE. DO NOT MODIFY."
        echo "__version__ = '$version'"
    } > $mdl/_gen_version.py

    # Print it for the caller too because they may wanna know.
    echo "$version"
}

# Just some basic sanity checks to run before publishing a release.
sanity() {
    case "${1,,}" in
        ""|test)
            local flavor=test
            ;;
        actual)
            local flavor=actual
            ;;
        *)
            echo "Invalid sanity flavor: '$1'" >&2
            false
            ;;
    esac

    # Spin a venv and run cfg in it mainly to see if we hit import errors.
    # This can fail with access denied, I think because vscode is holding onto the files it wants to delete. Should be safe to `rm -rf .venv` if that happens.
    python -m venv --clear .venv
    source .venv/Scripts/activate
    install $flavor
    coverage

    # This mystery function was sourced from the venv, it deactivates the venv.
    # If coverage fails we miss this but I don't suppose it's important.
    deactivate
}

# Deletes cache files, gitignored items generally. But NOT the dev flam dir!
# Note this also deletes sphinx's cache files. We could also delete those with sphinx's make clean, but it hits errors with file permissions. Because sphinx sucks!
clean() {
    # Need this buffer so we don't delete a folder while find is iterating its contents.
    # It'd be a lot nicer if we could just not descend into ignored folders, but that's much slower.
    # We tolerate check-ignore failures because it fails when there are no files and that happens when you call clean twice.
    _mktemp ignored_files
    find -name "$(basename -- "$flam_dir")" -prune -o -print0 | { git check-ignore -z --stdin || true; } > "$ignored_files"
    xargs -0 rm -vrf < "$ignored_files"
}

# Deletes the dev flam dir.
clean-ctx() {
    local confirm;
    read -ep "About to delete the flam context. Are you sure? " confirm;
    [[ "$confirm" == *([[:space:]])[yY]* ]] && rm -rf "$flam_dir"
}

# Deletes the dev flam dir cache files.
clean-vault() {
    rm -rf "$flam_dir"/cache
}

# Reconfigures the dev flam dir with some test lists.
cfg() {
    $cli config list --default-fetch=no     testlist                    imdb-listid=540302193
    $cli config list --default-fetch=yes    movies                      imdb-listid=083886771
    $cli config list --default-fetch=yes    shows                       imdb-listid=560024227
    $cli config list --default-fetch=yes    specials                    imdb-listid=560318295
    $cli config list --default-fetch=no     mubi                        imdb-listid=571616524
    $cli config list --default-fetch=no     netflix                     imdb-listid=560256455
    $cli config list --default-fetch=no     disney                      imdb-listid=565212657
    $cli config list --default-fetch=no     blurays                     imdb-listid=539518913
    $cli config list --default-fetch=no     dvds                        imdb-listid=537497285
    $cli config list --default-fetch=no     elsewhere                   imdb-listid=566138441

    $cli config list --default-fetch=no     lbox-movies                 letterboxd-user-list=verpous/movies-ive-watched
    $cli config list --default-fetch=no     lbox-films                  letterboxd-user-list=verpous/films
    $cli config list --default-fetch=no     lbox-likes                  letterboxd-user-list=verpous/likes
    $cli config list --default-fetch=no     lbox-reviews                letterboxd-user-list=verpous/reviews
    $cli config list --default-fetch=no     lbox-watchlist              letterboxd-user-list=verpous/watchlist
    
    $cli config list --default-fetch=no     tmdb-movies                 tmdb-list=7103008
    $cli config list --default-fetch=no     tmdb-fav-movies             tmdb-list=favorite-movies
    $cli config list --default-fetch=no     tmdb-fav-shows              tmdb-list=favorite-shows
    $cli config list --default-fetch=no     tmdb-rated-movies           tmdb-list=rated-movies
    $cli config list --default-fetch=no     tmdb-rated-shows            tmdb-list=rated-shows
    $cli config list --default-fetch=no     tmdb-watchlist-movies       tmdb-list=watchlist-movies
    $cli config list --default-fetch=no     tmdb-watchlist-shows        tmdb-list=watchlist-shows

    $cli config composite --default-find=yes    all         movies shows
    $cli config composite --default-find=no     rated       movies shows    -has my-rating
    $cli config composite --default-find=no     home        blurays dvds
    $cli config composite --default-find=no     streaming   mubi netflix
}

# Runs mypy to check if our code "compiles".
mypy() {
    MYPY_FORCE_COLOR=1 command mypy --disallow-untyped-defs --disallow-incomplete-defs --enable-incomplete-feature=NewGenericSyntax $mdl test_extensions.py
}

# Runs pylint to check if our code is nice and tidy.
pylint() {
    # PEP 695 support seems to be a little shoddy at this time so we patch it with --additional-builtins.
    command pylint --output-format=colorized --disable="$pylint_ignore" --additional-builtins="T" -- "${srcfiles[@]}" | less -R
}

# Counts how many lines we have in the codebase ^_^
wc() {
    # Count all non-ignored .py, .rst, or .sh files.
    find -name .git -prune -o \( -name \*.py -o -name \*.rst -o -name \*.sh -o -name \*.toml \) -print | _check_not_ignored | xargs wc -l -- | sort -n
}

_check_not_ignored() {
    _mktemp ignored_files
    find -print | git check-ignore --stdin > "$ignored_files"
    grep -Fxvf "$ignored_files"
}

# Opens the logs, with tail -f by default but you can pass a different command to use.
log() {
    local cmd

    # Default to tail -f for TTYs and cat otherwise.
    if (( $# == 0 )); then
        [[ -t 1 ]] && cmd="tail -f" || cmd=cat
    else
        cmd="$*"
    fi

    # Use LOGLEVEL=critical so that this very action doesn't create new logs.
    $cmd "$(FLAM_LOGLEVEL=critical python -c "import $mdl; print($mdl.get_log_file_path())")"
}

# A wrapper around running the flam CLI in a debug environment - with optional support for profiling.
flam() {
    _gen_version

    if [[ "${FLAM_PROFILE:-0}" != 0 ]]; then
        mkdir -p "$profiles"

        # Delete 2 day old profiles.
        find -- $profiles -name '*.prof' -cmin +$(( 60 * 24 * 2 )) -delete

        # Create a filename from the date and command. Replace or delete special characters in the command so it's a valid filename.
        local profile_path="$profiles/$(date +%Y-%m-%d_%H_%M_%S)_$(printf %s "${mdl}_$*" | tr [:space:] _ | tr -cd [:alnum:]_).prof"

        # Write profile output to a file, and drop the output of flam itself.
        FLAM_DEBUG="${FLAM_DEBUG:-1}" FLAM_DIR="$flam_dir" python -m cProfile -o "$profile_path" -m $mdl "$@" > /dev/null

        # Open the profile results. It will also be available to reinspect later.
        pstats "$profile_path"
    else
        FLAM_DEBUG="${FLAM_DEBUG:-1}" FLAM_DIR="$flam_dir" command $cli "$@"
    fi
}

# A wrapper around running the flam CLI in a dev environment with profiling enabled. Will show the profiling results instead of flam output once done.
# NOTE: this only does CPU profiling. I am really curious to use a memory profiler, but sadly python seems to be lacking in good ones.
# The best one is memray but it doesn't support Windows. The others look like crap, so I think I'll pass.
profile() {
    FLAM_PROFILE=1 $cli "$@"
}

# Inspects the results of a profiled run. By default looks at the most recent run but you can provide a path (all runs are stored in profiles/).
pstats() {
    # If no arguments, default to the latest profile.
    if (( $# == 0 )); then
        # Globbing expands alphabetically and we name files by date so the latest file should be the last in the array.
        local files=($profiles/*)
        files=("${files[-1]}")
    else
        local files=("$@")
    fi

    local file

    for file in "${files[@]}"; do
        # It's cumtime!
        # Dump stderr because it keeps bitching about non-issues.
        printf '%s\n' "sort cumtime" stats EOF | { python -m pstats "$file" || true; } 2> /dev/null | less
    done
}

# Runs some subset of flam commands designed to provide the most code coverage with the least amount of commands.
# This is just an easy enough solution to spin up until maybe one day we'll have a more robust test suite.
coverage() {
    # Support `coverage profile` for coverage with profiling.
    local cmd="${1:-$cli}"
    local i

    # This step is not part of the test, it's just cleanup from the previus run.
    $cli config extension -D "$PWD"/test_extensions.py 2> /dev/null || true
    $cli config list -D coverage 2> /dev/null || true
    $cli config composite -D coverage 2> /dev/null || true

    # Also cleanup the vault so the test is consistent.
    clean-vault

    # Run everything in a scope that's redirected to devnull. If profiling, it will break us out of pstats. If not profiling, it will dump the output of flam.
    time {
        time "$cmd" config extension "$PWD"/test_extensions.py
        time "$cmd" config extension
        time "$cmd" config extension -D "$PWD"/test_extensions.py

        time "$cmd" config list cov imdb-listid=540302193
        time "$cmd" config list --rename coverage cov imdb-listid=083886771
        time "$cmd" config list
        time "$cmd" config list -D coverage

        time "$cmd" config composite cov dvds blurays -name the
        time "$cmd" config composite --rename coverage cov movies shows -rating +8
        time "$cmd" config composite
        time "$cmd" config composite -D coverage

        # Fetch is optional since it's so slow.
        if [[ ! "$2" ]]; then
            # To really get good code coverage we need to fetch:
            # * At least one movie and one show - handpicked Mandibles and Don't Hug Me I'm Scared because they have small crews and should fetch quickly.
            # * All special list paths for fetchers which support them: watchlist, liked films, etc.
            time "$cmd" fetch --refetch 'mandibles|hug me.*scared' specials shows
            time "$cmd" fetch --refetch 'mandibles|hug me.*scared' lbox-films lbox-likes lbox-reviews lbox-watchlist
            time "$cmd" fetch --refetch 'mandibles|hug me.*scared' tmdb-movies tmdb-fav-movies tmdb-fav-shows tmdb-rated-movies tmdb-rated-shows tmdb-watchlist-movies tmdb-watchlist-shows
        else
            time "$cmd" fetch --nothing
        fi

        # Clean the vault again, then run all find commands twice. The first time they'll test vault caching, the second time they will test vault loading.
        clean-vault

        for i in 1 2; do
            time "$cmd" find -c\* movies specials [ -true -o -false ] -every director '.*' -has title -has-index countries 0 -index countries 0 '.*' \
                -superset cast [ a e o i e ] -subset cast [ a e o i e ] -sameset cast [ a e o i e ] -in-list movies -any-role [] -true -every-role [] -true

            time "$cmd" find -c\* any-people:group specials -any-movie -true -every-movie -true -as cast -true -any-person -true -every-person -true
            time "$cmd" find -c\* any-people:separate specials -any-movie -true -every-movie -true -as cast -true -any-person -true -every-person -true
            time "$cmd" find -c\* cast-people:group specials -any-movie -true -every-movie -true -as director -true -any-person -true -every-person -true
            time "$cmd" find -c\* cast-people:separate specials -any-movie -true -every-movie -true -as director -true -any-person -true -every-person -true

            time "$cmd" find -croles-\* any:group specials -any-movie -true -every-movie -true -as cast -true -any-person -true -every-person -true
            time "$cmd" find -croles-\* any:separate specials -any-movie -true -every-movie -true -as cast -true -any-person -true -every-person -true
            time "$cmd" find -croles-\* cast:group specials -any-movie -true -every-movie -true -as director -true -any-person -true -every-person -true
            time "$cmd" find -croles-\* cast:separate specials -any-movie -true -every-movie -true -as director -true -any-person -true -every-person -true
            
        done

        # Test precaching again now that lots of things are vaulted.
        time "$cmd" fetch --nothing
    } > /dev/null
}

# Compiles the documentation.
sphinx() {
    _gen_version
    
    (
        cd $docs

        case "${1,,}" in
            ""|actual)
                # Build HTML for viewing the docs online.
                make html

                # Build man for viewing the docs in the terminal with `flam docs`.
                make man
                man_build=build/man
                
                # For systems without `man`, also generate a plaintext version. Sphinx has a 'text' builder for generating text files prettier than this,
                # but it compiles each .rst into its own .txt, whereas man essentially catenates all files together. We'll live with it.
                # NOTE: this logs a warning every time which we will live with. We don't want to ignore all of stderr because it's useful sometimes.
                # HACK: man is set up weird on my environment, and this is the only way I can get it to work. This won't work on other people's machines.
                MSYS_NO_PATHCONV=1 cmd /c man $man_build/filmflam.1 > $man_build/_gen_docs.txt

                # Copy everything to the package folder so it will be accessible and packaged with flam.
                cp $man_build/* ../$mdl/data/

                # The man is built with the default name, which is the package name, and then renamed only after being copied out, so sphinx will know not to rebuild it.
                # There is a way to name it this to begin with by defining man_pages in conf.py, but it also fucks with the title of the page.
                mv ../$mdl/data/filmflam.1 ../$mdl/data/_gen_docs.1
                ;;
            live)
                # Only for HTML docs, we have this ability to edit them live with the browser window refreshing on every change.
                # We go aggressive with --write-all, --fresh-env, and --watch the mdl dir so that anywhere we make a change will cause a sync.
                # Without these you'd have to change the specific .rst file to sync, even if the change you made was in the conf.py or the python docstrings.
                sphinx-autobuild --open-browser --quiet --fail-on-warning --show-traceback --write-all --fresh-env --watch ../$mdl ./source/ ./build/
                ;;
            *)
                echo "Invalid sphinx flavor: '$1'" >&2
                false
                ;;
        esac
    )
}

# Prints which commands this "makefile" has.
help() {
    if (( $# == 0 )); then
        # If no args, print all (public) functions.
        declare -pF | cut -d ' ' -f 3 | grep -Ev '^_'
    else
        # With args, print what that function does.
        type -- "$@"
    fi
}

# Little system which lets us make tempfiles without worrying about cleanup (also log when a failure happens).
tmpfiles=()
trap '(( $? != 0 )) && echo "Quitting early because of an error!"; rm -f -- "${tmpfiles[@]}"' EXIT

# This function must be executed not in a subshell, so instead of printing the result it writes it to a variable.
_mktemp() {
    declare -n res="$1"
    shift
    tmpfiles+=("$(mktemp "$@")")
    res="${tmpfiles[-1]}"
}

# Try to emulate makefile behavior. Enable it a moment before the command so we don't print all the shit above.
set -exo pipefail

# Do whatever was asked, default to help.
"${@:-help}"
