Fetchers
=======================

Fetchers are how you download data about a movie list from some external source.

When you configure a list, you will need to configure it with a :ref:`listdef <Listdefs>` describing which fetcher to use, and the address of the list to download.

Some fetchers allow you to control additional fetch settings using ``--fetch-param``.

.. tip::
    
    Flam supports implementing :ref:`custom fetchers <Implementing a custom fetcher>`.

List of builtin fetchers
------------------------

.. builtin-fetchers::
