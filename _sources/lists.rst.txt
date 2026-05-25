Lists
=======================

To work with flam is to work with movie lists. So it's good to familiarize yourself with how to reference lists, and what types of lists flam supports.

Composite lists
---------------

Flam lets you define lists which are remixes of other lists you've configured.
After you've configured "simple" lists with ``flam config list``, you may use them to define "composite" lists:

.. code-block:: bash

    # Define a list "rated" of only the movies from your "watched" list which you've personally rated.
    flam config composite rated watched -has my-rating

    # Define a list "all" which combines both your "watched-movies" and "watched-shows" lists.
    flam config composite all watched-movies watched-shows

Generally, composite lists are one or more simple lists combined together, then optionally filtered.

Listdefs
--------

"Listdefs" are how you describe which list you're talking about to flam. They have a number of forms:

* ``"<fetcher>=<address>"`` (ex: "imdb-listid=083886771")
    
    A raw form for lists which haven't been given a name. The kind of address it expects depends on the :ref:`fetcher <Fetchers>`.
* ``"<name>"`` (ex: "watched")

    The name of a list configured with ``flam config list`` or ``flam config composite``.
* ``"<list type>=<name>"`` (ex: "list=watched")

    Like above, but with an explicit list type so there's no ambiguity. <list type> is either 'list' or 'composite'.
* ``"*"``
    
    A special listdef indicating to use all configured lists.
* ``"defaults"``

    A special listdef indicating to use all lists configured as ``--default-fetch`` (if you're using fetch), or ``--default-find`` (if you're using find).
