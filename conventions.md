# Coding conventions

* Try to abide by PEP8
* Use 4 spaces, not tabs
* Avoid `from` imports, prefer to write the fully qualified name
* Prefer `''` strings, not `""` strings
* Prefer `@classmethod` to `@staticmethod`
* Private members begin with a `_`
* Members which are public internally but private to outside users should be named as private members
* Public members should have docstrings
* Docstrings should have `:param:`s but no `:return:`, `:raise:`, etc. That should be documented by docstring prologue
* Docstrings and the docs assume things are `from` imported, i.e. don't write `flam.<member>`, just write `<member>`
* Docstrings capitalize the prologue but not each `:param:`. The prologue as well as `:param:`s all use a period at the end of the sentence.
* Comments begin with a space, are capitalized, and end with a period: `# This is a proper comment.`
* Logs start with a capital letter and don't end with a period
* Exceptions start with a capital letter and end with a period
* Don't validate argument types at runtime - put your faith in mypy
* Always type hint function definitions
* Don't type hint anything else unless mypy requires it
* Always use `from __future__ import annotations`
* Code must pass `mk pylint` and `mk mypy`