.. Examples for reference:
.. * https://tomobank.readthedocs.io/en/latest/index.html
.. * https://docs.scrapy.org/en/latest/intro/install.html

|project| |version| documentation
=================================

|project| (or just "flam") is a commandline tool and API for extracting insights from your movie lists. Flam enables you to quickly answer questions like "where have I seen this actor?", or "which director have I seen the most movies from?", and so much more - all with short command lines.

For more powerful uses, you can  ``import flam`` and use the underlying API to get data about the movies and people in your movie lists.

Examples
--------

TODO

Usage
-----

TODO

.. toctree::
    :maxdepth: 2
    :caption: Contents:

    install
    examples
    findables
    listdefs
    filters
    attributes
    predicates
    fetchers
    cli/cli
    api/api
    extending

Supported platforms
-------------------

|project| is written to be cross-platform so it should work on both Windows and Linux. However since I am using Windows, I never tested it on Linux. Please let me know if you encounter issues on Linux.

The commandline tool has a soft dependency on ``less`` so if you are on Windows it's recommended to install it - one easy way is to just install `git <https://git-scm.com/>`__.

Getting help
------------

If you encounter issues or have questions, you can `open a GitHub issue <https://github.com/Verpous/film-flam/issues>`__, or email me at ederyaviv2@gmail.com.
