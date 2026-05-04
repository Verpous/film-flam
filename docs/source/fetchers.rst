Fetchers
=======================

Fetchers are how you download data about a movie list from some external source.

When you configure a list, you will need to configure it with a :ref:`listdef <Listdefs>` describing which fetcher to use, and the address of the list to download.

.. note::
    
    Flam supports implementing :ref:`custom fetchers <Implementing a custom fetcher>`.

    Currently, only IMDb has builtin support. You can fix that by implementing, say, a Letterboxd fetcher,
    or `open a GitHub issue <https://github.com/Verpous/film-flam/issues>`__ and convince me to implement it for you :)

List of builtin fetchers
------------------------

.. builtin-fetchers::
