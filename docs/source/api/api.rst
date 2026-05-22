API
=======================

Flam is not just a commandline tool, it's also a python API for using from your scripts:

.. Usually we're against qualified names in code examples, but here I think it's good to have.
.. code-block:: python

    import flam

    # Most interfacing with flam happens through a FlamContext. Create one then start using it.
    ctx = flam.FlamContext()

    # Configure a list 'watched' based on your IMDb list of movies you've watched.
    with ctx.configure() as cfg:
        simple_list = flam.SimpleList(
            uid = "what you set here doesn't matter, it will be overwritten anyway",
            name = 'watched',
            concrete_listdef = ctx.parse_listdef('imdb-listid=083886771'),
            is_default_fetch = False,
            is_default_find = False,
        )

        cfg.simple_lists_raw.append(simple_list)

    # Download the list and store it persistently. Next time you won't have to fetch it again.
    ctx.fetch(['watched'])

    # Print the titles of watched movies from the year 1999.
    watched_movies = ctx.get_movie_list('watched')
    filter = ctx.compile_movies_filter(['-release-year', '1999'])

    for movie in watched_movies.find_movies(filter):
        print(movie['title'])

.. toctree::
    :caption: Contents:

    flam
    flam.utils
    flam.attrutils
