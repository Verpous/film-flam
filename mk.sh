#! /bin/bash

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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# Makefiles are crap for anything other than compiling things. We just want helper functions for development so it's better to use a "make-like" bash script.

shopt -s extglob

# Below this point assume we are in the project directory.
project_folder="$(dirname -- "$BASH_SOURCE")"
cd "$project_folder"

mdl=flam
cli=flam
pkg=film-flam
build=dist

flam_dir=.film_flam_dev
srcfiles=($mdl/*.py)

pylint_ignore+=C0103, # invalid-name
pylint_ignore+=C0104, # disallowed-name
pylint_ignore+=C0114, # missing-module-docstring
pylint_ignore+=C0115, # missing-class-docstring
pylint_ignore+=C0116, # missing-function-docstring
pylint_ignore+=C0200, # consider-using-enumerate
pylint_ignore+=C0301, # line-too-long
pylint_ignore+=C0302, # too-many-lines
pylint_ignore+=C0303, # trailing-whitespace
pylint_ignore+=C0411, # wrong-import-order
pylint_ignore+=C0413, # wrong-import-position
pylint_ignore+=C0415, # import-outside-toplevel

pylint_ignore+=R0401, # cyclic-import
pylint_ignore+=R0402, # consider-using-from-import
pylint_ignore+=R0801, # duplicate-code
pylint_ignore+=R0902, # too-many-instance-attributes
pylint_ignore+=R0903, # too-few-public-methods
pylint_ignore+=R0912, # too-many-branches
pylint_ignore+=R0913, # too-many-arguments
pylint_ignore+=R0915, # too-many-statements
pylint_ignore+=R0917, # too-many-positional-arguments
pylint_ignore+=R1708, # stop-iteration-return
pylint_ignore+=R1714, # consider-using-in
pylint_ignore+=R1735, # use-dict-literal

pylint_ignore+=W0124, # confusing-with-statement
pylint_ignore+=W0212, # protected-access
pylint_ignore+=W0511, # fixme
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
        # TODO: When I'm ready to run this for the first time, set up API token.
        actual)
            local flavor=actual
            local twineargs=""
            ;;
        *)
            echo "Invalid release flavor: '$1'" >&2
            false
            ;;
    esac

    _gen_requirements
    _gen_version $flavor force

    # For actual releases, require mypy and pylint to report no problems.
    [[ "$flavor" != actual ]] || { mypy && pylint; } > /dev/null

    rm -rf $build
    python -m build --outdir $build
    twine upload $twineargs $build/*
    sanity $flavor
    echo "Successfully created a release with flavor: $flavor."
}

# Generates requirements.txt file for specifying to pip all flam dependencies.
_gen_requirements() {
    # I refuse to manually keep track of dependencies, so we use pipreqs. But pipreqs SUCKS:
    # 1. Some folders confuse pipreqs so we --ignore them.
    # 2. pipreqs identifies cinemagoer by its old name, IMDbPY, so we rename it.
    # 3. pipreqs fails at identifying packages locally, instead resolving them from the PyPI server where it gets the version wrong,
    #    so we actually use pipreqs to get the names of packages, then grep them with the correct versions from pip freeze.
    _mktemp req_patterns
    pipreqs --mode no-pin --ignore .mypy_cache,.venv --print | sed -E 's/IMDbPY/cinemagoer/g; s/python_dateutil/python-dateutil/g; s/.*/^\0==/g' > "$req_patterns"
    grep -E --file="$req_patterns" <(pip freeze) | sed -E 's/==/>=/g' | tee _gen_requirements.txt

    # Sanity check that we didn't miss any packages.
    (( "$(command wc -l < "$req_patterns")" == "$(command wc -l < _gen_requirements.txt)" ))
}

# Code-generation of the file containing the current version from use from within the code. Supports all release flavors. Optionally can check if the file already exists.
_gen_version() {
    [[ ! "$2" && -f $mdl/_gen_version.py ]] && return

    {
        # We use date versioning because it requires the least manual intervention.
        # TestPyPI won't accept the same version twice, so in dev builds, we also version it with the epoch seconds.
        local datefmt
        [[ "$1" == actual ]] && datefmt=%Y.%-m.%-d || datefmt=%Y.%-m.%-d.dev%s

        echo "# AUTOGENERATED FILE. DO NOT MODIFY."
        echo "__version__ = '$(date +$datefmt)'"
    } > $mdl/_gen_version.py
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
    python -m venv --clear .venv
    source .venv/Scripts/activate
    install $flavor
    cfg

    # This mystery function was sourced from the venv, it deactivates the venv.
    # If cfg fails we miss this but I don't suppose it's important.
    deactivate
}

# Deletes cache files, gitignored items generally. But NOT the dev flam dir!
clean() {
    # Need this buffer so we don't delete a folder while find is iterating its contents.
    # It'd be a lot nicer if we could just not descend into ignored folders, but that's much slower.
    _mktemp ignored_files
    find . -name "$(basename -- "$flam_dir")" -prune -o -print0 | git check-ignore -z --stdin > "$ignored_files"
    xargs -0 rm -vrf < "$ignored_files"
}

# Deletes the dev flam dir.
clean-ctx() {
    rm -rf "$flam_dir"
}

# Reconfigures the dev flam dir with some test lists.
cfg() {
    $cli config list --default-fetch=yes testlist imdb-rest=540302193
    $cli config list --default-fetch=yes netflix imdb-rest=560256455
    $cli config list --default-fetch=yes mubi imdb-rest=571616524
    $cli config composite --default-find=yes testcomp testlist -true
    $cli config composite testcomp testlist -true
    $cli config composite streaming mubi netflix
}

# Runs mypy to check if our code "compiles".
mypy() {
    MYPY_FORCE_COLOR=1 command mypy --disallow-untyped-defs --disallow-incomplete-defs --enable-incomplete-feature=NewGenericSyntax $cli
}

# Runs pylint to check if our code is nice and tidy.
pylint() {
    # PEP 695 support seems to be a little shoddy at this time so we patch it with --additional-builtins.
    command pylint --output-format=colorized --disable="$pylint_ignore" --additional-builtins="T" -- "${srcfiles[@]}" | less -R
}

# Counts how many lines we have in the codebase ^_^
wc() {
    command wc -l -- "${srcfiles[@]}" | sort -n
}

# Opens the logs, with tail -f by default but you can pass a different command to use.
log() {
    # Use LOGLEVEL=critical so that this very action doesn't create new logs.
    ${@:-tail -f} "$(echo "import $mdl; print($mdl.get_log_file_path())" | FLAM_LOGLEVEL=critical python)"
}

# Just a wrapper around running the flam CLI in a debug environment.
flam() {
    _gen_version
    FLAM_DEBUG="${FLAM_DEBUG:-1}" FLAM_DIR="$flam_dir" command flam "$@"
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

# Not polished yet, just want to put this line somewhere
# profile() {
#     python -m cProfile $(BIN)/flam.py fetch imdb-id=540302193
# }

# Little system which lets us make tempfiles without worrying about cleanup.
tmpfiles=()
trap 'rm -f -- "${tmpfiles[@]}"' EXIT

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
