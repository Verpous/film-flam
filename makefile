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

FLAM_DIR=~/.film_flam
PKG=filmflam
BIN=bin
CLI=$(BIN)/flam.py

PYLINT_IGNORE += C0103 # invalid-name
PYLINT_IGNORE += C0104 # disallowed-name
PYLINT_IGNORE += C0114 # missing-module-docstring
PYLINT_IGNORE += C0115 # missing-class-docstring
PYLINT_IGNORE += C0116 # missing-function-docstring
PYLINT_IGNORE += C0200 # consider-using-enumerate
PYLINT_IGNORE += C0301 # line-too-long
PYLINT_IGNORE += C0302 # too-many-lines
PYLINT_IGNORE += C0303 # trailing-whitespace
PYLINT_IGNORE += C0411 # wrong-import-order
PYLINT_IGNORE += C0413 # wrong-import-position
PYLINT_IGNORE += C0415 # import-outside-toplevel

PYLINT_IGNORE += R0401 # cyclic-import
PYLINT_IGNORE += R0402 # consider-using-from-import
PYLINT_IGNORE += R0902 # too-many-instance-attributes
PYLINT_IGNORE += R0903 # too-few-public-methods
PYLINT_IGNORE += R0913 # too-many-arguments
PYLINT_IGNORE += R0917 # too-many-positional-arguments
PYLINT_IGNORE += R1708 # stop-iteration-return
PYLINT_IGNORE += R1714 # consider-using-in

PYLINT_IGNORE += W0124 # confusing-with-statement
PYLINT_IGNORE += W0212 # protected-access
PYLINT_IGNORE += W0511 # fixme
PYLINT_IGNORE += W0622 # redefined-builtin
PYLINT_IGNORE += W0702 # bare-except
PYLINT_IGNORE += W1514 # unspecified-encoding
PYLINT_IGNORE += W1203 # logging-fstring-interpolation

FILES:=$(wildcard $(PKG)/*.py $(BIN)/*.py)

view = tail -f

.PHONY: all install uinstall clean cfg mypy pylint wc log

all: install

install:
	pip install -e .

uninstall:
	pip uninstall $(PKG)

clean:
	rm -rf $(FLAM_DIR)

cfg:
	$(CLI) config list testlist imdb-id=540302193
	$(CLI) config composite testcomp testlist -true

mypy:
	MYPY_FORCE_COLOR=1 mypy --disallow-untyped-defs --disallow-incomplete-defs --enable-incomplete-feature=NewGenericSyntax $(CLI)

# PEP 695 support seems to be a little shoddy at this time so we patch it with a grep.
pylint:
	pylint --output-format=colorized --disable="$$(printf %s, $(PYLINT_IGNORE))" -- $(FILES) | grep -v "Undefined variable 'T'" | less -R

wc:
	@wc -l -- $(FILES)

# Use LOGLEVEL=critical so that this very action doesn't create new logs.
log:
	$(view) "$$(echo "import filmflam; print(filmflam.get_log_file_path())" | FLAM_LOGLEVEL=critical python)"

# Not really a target, but want to put this someplace for now.
# profile:
# 	python -m cProfile $(BIN)/flam.py fetch imdb-id=540302193