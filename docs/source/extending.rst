Extending Flam
=======================

You can extend flam with custom :ref:`attributes <Attributes>`, :ref:`predicates <Predicates>`, and :ref:`fetchers <Fetchers>`.

.. tip::

    The repository includes an `example file <https://github.com/Verpous/film-flam/blob/master/test_extensions.py>`__ demonstrating how to implement custom extensions.

Registering an extension
------------------------

To use an extension, you must register it. There are two ways to register an extension:

#. **Global extension**

    Use :py:func:`~._reg.register`, and the extension will be automatically available from any :py:class:`~._ctx.FlamContext`.
    
    .. code-block:: python
        
        @register
        class MyCustomPredicate(Predicate,
                name_without_type='is-movie-dope',
                findable_type=FindableType.MOVIES):
            # ...

    It's allowed to name your extension the same as an existing builtin. The builtin will be shadowed.
#. **Context extension**

    Use :py:meth:`FlamContext.register() <._ctx.FlamContext.register>`, and the extension will be available to use only from that specific context.

    .. code-block:: python

        class MyCustomPredicate(Predicate,
                name_without_type='is-movie-dope',
                findable_type=FindableType.MOVIES):
            # ...

        ctx = FlamContext()
        ctx.register(MyCustomPredicate)

    It's allowed to name your extension the same as an existing builtin or global extension. They will be shadowed.

Once registered, using an extension is just like using any builtin:

.. code-block:: python

    filter = ctx.compile_movies_filter(['-is-movie-dope'])

.. note::

    For predicates and fetchers, you need to register **the class itself**. For attributes, you must register **an instance of the class!**

    .. code-block:: python

        # DO:
        ctx.register(MyCustomPredicate)
        ctx.register(MyCustomFetcher)
        ctx.register(MyCustomAttribute())
        
        # DON'T:
        ctx.register(MyCustomPredicate())
        ctx.register(MyCustomFetcher())
        ctx.register(MyCustomAttribute)

Importing extensions automatically
----------------------------------

You can configure flam to automatically import your extensions module:

.. code-block:: bash

    flam config extension my_extensions.py

The file must register its extensions **globally**. Now they will be automatically available from any :py:class:`~._ctx.FlamContext` created with ``import_extensions=True``.

Implementing a custom attribute
--------------------------------

Attributes are implemented by inheriting from :py:class:`~._attr.Attribute` and implementing all its abstract members.

However, there is an easier way. The :ref:`flam.attrutils` module provides a suite of utilities to help you implement attributes easily. You only need to provide:

* Your attribute's parameters
* A :py:class:`~.attrutils.TypeHandler` which corresponds to your attribute's return value (we probably already have the one you need)
* An "extractor" function, which returns your attribute's value from the "MLF" (Movie List File) objects. These objects contain the all the raw fetch data about your findable.

.. code-block:: python

    @register
    @easy_attribute(EasyAttributeParams(
        name_without_type = 'title',
        aliases_without_type = ['name', 'movie'],
        findable_type = FindableType.MOVIES,
        type_handler = STR_HANDLER,
        is_ascending = True,
        truncation_style = TruncationStyle.TRIM_END,
        default_max_len = 45,
    ))
    def movie_title_extractor(self, movie: Movie, mlf_movie: MLFMovie) -> None | str:
        return mlf_movie.title

The extractor function should have a different signature based on the findable type:

.. code-block:: python

        # Extractor for movie attributes.
        def movie_title_extractor(self, movie: Movie, mlf_movie: MLFMovie) -> None | str:
            return mlf_movie.title

        # Extractor for people attributes.
        # mlf_people is sorted by uid. People attributes should return the attribute for each person a list with the same order.
        def people_name_extractor(self, people: People, mlf_people: list[MLFPerson]) -> list[None | str]:
            return [mlf_person.name for mlf_person in mlf_people]

        # Extractor for role attributes.
        def role_characters_extractor(self, role: Role, mlf_roles: MLFRolesDict, mlf_movie: MLFMovie, mlf_people: list[MLFPerson]) -> list[str]:
            return [
                char
                for mlf_person in mlf_people
                for ct, mlf_role in mlf_roles[mlf_person.uid].items()
                for char in mlf_role.characters
            ]

.. note::

    * Flam has special handling for attributes with return a ``list``
    * Flam has special handling for attributes which return ``None``. MLF data can often be ``None``, so most attributes should be prepared to return it
    * The MLF objects you get are **readonly!** Don't modify them
    * Always create a copy if your attribute returns a mutable internal object:

        .. code-block:: python

            def _movie_genres_extractor(self, movie: Movie, mlf_movie: MLFMovie) -> list[str]:
                # GOOD: caller gets a copy of the list.
                return list(mlf_movie.genres)

                # BAD: caller gets the same list and might accidentally modify the MLF, which is not allowed.
                return mlf_movie.genres

Implementing a custom predicate
--------------------------------

Predicates are implemented by inheriting from :py:class:`~._filter.Predicate`. You'll need to:

* Fill in some parameters like the predicate's name and type in the :py:meth:`class declaration <._filter.Predicate.__init_subclass__>`
* Implement :py:meth:`~._filter.Predicate.eat`, a classmethod for parsing your predicate
* Implement some ``excrete`` function, for checking if the predicate holds true. The exact signature depends on the predicate's findable type:

    .. code-block:: python

        # Excrete for general predicates (predicates without a specific findable type).
        # General predicates also have the choice of implement all 3 of the type-specific excretes instead.
        def excrete(self, findable: Findable) -> bool:

        # Excrete for movie predicates.
        def _excrete_from_movie(self, movie: Movie, mlf_movie: MLFMovie) -> bool:

        # Excrete for people predicates.
        def _excrete_from_people(self, people: People, mlf_people: list[MLFPerson]) -> bool:

        # Excrete for role predicates.
        def _excrete_from_role(self, role: Role, mlf_roles: MLFRolesDict, mlf_movie: MLFMovie, mlf_people: list[MLFPerson]) -> bool:
* Optionally implement :py:meth:`~._filter.FilterMember.regurgitate`, for decompiling your predicate
* Optionally implement :py:meth:`~._filter.FilterMember.colonoscopy`, for inspecting subfilters in your predicate

Here's what it all looks like:

.. code-block:: python

    # Movie predicate which takes a list of CTGMs and a subfilter for roles, and checks if any role with any of those CTGMs passes the subfilter.
    @register
    class AnyRolePredicate(Predicate, name_without_type='any-role', findable_type=FindableType.MOVIES):
        def __init__(self, ct_gms: list[tuple[CrewType, GroupMode]], filter: Filter) -> None:
            self._ct_gms = ct_gms
            self._filter = filter
        
        @classmethod
        def eat(cls, params: EatParams, at: int) -> tuple[Predicate, int]:
            # Functions which "eat" actually read a few tokens from index `at` and parse them into a result.
            # They return the result and which index they stopped parsing at.
            # We have a number of handy "eat" utils from our parent class.
            ct_gms, filter_idx = cls.eat_listof(cls.eat_ct_gm, params, at)
            sub_params = dataclasses.replace(params, find=FindableType.ROLES)
            filter, until = cls.eat_subfilter(sub_params, filter_idx)
            return cls(ct_gms, filter), until

        def _excrete_from_movie(self, movie: Movie, mlf_movie: _mlf.MLFMovie) -> bool:
            for ct_gm in self._ct_gms:
                for role in movie.associated_roles(*ct_gm):
                    if self._filter.excrete(role):
                        return True

            return False

        def regurgitate(self) -> typing.Iterable[str]:
            # Use `min` because LPAREN, RPAREN are sets of accepted strings and we want to pick one.
            yield from super().regurgitate()
            yield min(Pipeline.LPAREN)
            yield from (ct_gm_to_str(*ct_gm) for ct_gm in self._ct_gms)
            yield min(Pipeline.RPAREN)
            yield from self._filter.regurgitate()

        def colonoscopy(self) -> typing.Iterable[FilterMember]:
            yield self
            yield from self._filter.colonoscopy()

Implementing a custom fetcher
--------------------------------

Fetchers are implemented by inheriting from :py:class:`~._fetch.Fetcher`. You'll need to:

* Fill in some parameters like the fetcher's name in the :py:meth:`class declaration <._fetch.Fetcher.__init_subclass__>`
* Implement :py:meth:`~._fetch.Fetcher._fetch_into_file`

.. code-block:: python

    @register
    class MyCustomFetcher(Fetcher, list_type='my-database'):
        def fetch_into_file(self, movie_list_file: MovieListFile) -> None:
            # ...

Fetchers require gentle care in their implementation:

* Familiarize yourself with the structure of :py:class:`~._mlf.MovieListFile`\
* Remember to delete movies in the file that were removed from the list, and to avoid re-fetching movies already in the file
* When deleting a movie, you don't need to delete its people. That's handled automatically
* Don't add movies to the file until you've acquired all of their data, so that if fetch is interrupted at any point, the file will be in a good, saveable state
* If your fetcher is slow, call :py:meth:`~._fetch.Fetcher._checkpoint` from time to time so that a crash won't cause the data to be lost
* Be sure to handle server errors from the API you're fetching from, and raise :py:exc:`~._exc.FetchInterrupt` as needed
* It's also nice to handle ``KeyboardInterrupt`` by raising :py:exc:`~._exc.FetchInterrupt`

See it all in action:

.. NOTE: every time I change the fetcher I have to change it here too, and remove all `` prefixes.

.. code-block:: python

    # This fetcher takes a size of a list to "fetch" and literally makes up a list with phony data.
    @register
    class RandomDataFetcher(Fetcher, list_type='random-size'):
        def _fetch_into_file(self, movie_list_file: MovieListFile) -> None:
            # Takes the address to mean the number of movies the random list should have.
            num_movies = int(self.concrete_listdef.address)
            
            # We must assign a UID for each movie. Usually this would be, like, the IMDb ID of that movie.
            # For this example we'll just use the index as the uid.
            movie_uids_in_list = [str(movie_idx) for movie_idx in range(num_movies)]

            # Remove all movies that were previously fetched but are no longer part of the list.
            movie_list_file.movies_by_uid = {uid: m for uid, m in movie_list_file.movies_by_uid.items() if uid in movie_uids_in_list}

            # Now add all the movies that aren't already in the list from a previous fetch.
            # Use this progressbar utility to print our progress to stdout as we go.
            with utils.ProgressBar([uid for uid in movie_uids_in_list if uid not in movie_list_file.movies_by_uid],
                    desc='Downloading',
                    keyfunc=lambda uid: uid) as bar:
                for uid in bar:
                    try:
                        self.fetch_movie(movie_list_file, uid)
                    except KeyboardInterrupt as e:
                        raise FetchInterrupt("User interrupted fetch in the middle.") from e

                    # Save what we've fetched so far, so that if we experience a crash, data won't have to be re-fetched.
                    self._checkpoint(movie_list_file)

        def fetch_movie(self, movie_list_file: MovieListFile, uid: str) -> None:
            TITLES_POOL = ['Star Wars', 'Inside Llewyn Davis', 'Lord of the Rings', 'Interstellar']
            CHARACTERS_POOL = ['Darth Vader', 'Llewyn Davis', 'Galadriel', 'Murph']

            # We'll seed the movie's RNG using its uid.
            rng = random.Random(uid)

            # It's important to acquire all the movie's data and populate the file with the people from the movie before we add the movie itself.
            # So we'll start by building the movie's crews.
            crew = {}

            for crew_type in CrewType.iterate_except_any():
                # Randomly decide how many people are in this movie in this crew type.
                # For their uid, we'll add some random base so that you don't get the same people everywhere.
                num_crewmembers = rng.randint(0, 10)
                base_uid = rng.randint(0, 1000)

                crew[crew_type] = MLFCrew(
                    crew_type = crew_type,
                    roles_by_uid = {},
                )

                for person_idx in range(num_crewmembers):
                    # Make up some uid for this fake person.
                    person_uid = str(base_uid + person_idx)

                    # For actors, we'll make up a bit of data about which character they played.
                    # We can always fill in None, or leave lists empty if we're missing that data.
                    crew[crew_type].roles_by_uid[person_uid] = MLFRole(
                        person_uid          = person_uid,
                        is_star             = None,
                        episodes_num        = None,
                        oscar_noms          = [],
                        oscar_wins          = [],
                        characters          = [rng.choice(CHARACTERS_POOL)] if crew_type == CrewType.CAST else [],
                        jobs                = [],
                    )

                    # This person may have already been fetched because of their presence in another movie or another crew type in this movie.
                    if person_uid not in movie_list_file.people_by_uid:
                        self.fetch_person(movie_list_file, person_uid)

            # We support some data about movies which is actually specifically about that movie's presence in this list.
            # For example, the date it was added to this list.
            per_src_data = MLFMoviePerSourceData(
                canon_listdef       = movie_list_file.abstract_listdef,
                list_index          = int(uid),
                list_note           = None,
                listing_date        = None,
            )

            mlf_movie = MLFMovie(
                uid                 = uid,
                per_src_data        = [per_src_data],
                media_type          = 'movie',
                title               = rng.choice(TITLES_POOL),
                original_title      = None,
                tagline             = None,
                synopsis            = None,
                url                 = None,
                runtime_minutes     = 145,
                metascore_votes     = None,
                metascore           = 82,
                votes               = None,
                rating              = 8.5,
                my_rating           = None,
                likes               = None,
                is_liked            = None,
                budget_usd          = None,
                revenue_usd         = None,
                content_rating      = None,
                release_date        = datetime.date(1969, 7, 4),
                watch_dates         = [],
                my_notes            = [],
                episodes_num        = None,
                seasons_num         = None,
                end_date            = None,
                genres              = ['Drama', 'Western'],
                studios             = ['Paramount Pictures', 'Rafran Cinematografica', 'San Marco'],
                languages           = ['English', 'Italian', 'Spanish'],
                countries           = ['Italy', 'United States'],
                crew                = crew,
            )

            # Add the movie to the file only at the end, after all its data is acquired, and all the people from the movie are already added!
            movie_list_file.movies_by_uid[mlf_movie.uid] = mlf_movie

        def fetch_person(self, movie_list_file: MovieListFile, uid: str) -> None:
            NAMES_POOL = ['James', 'Spencer', 'Hayden', 'David', 'Oscar', 'Cate', 'Jessica', 'Ellen']
            GENDERS_POOL = ['male', 'female', 'nonbinary']

            # We'll seed the person's RNG using its uid.
            rng = random.Random(uid)

            movie_list_file.people_by_uid[uid] = MLFPerson(
                uid                 = uid,
                name                = rng.choice(NAMES_POOL),
                gender              = rng.choice(GENDERS_POOL),
                birthday            = datetime.date(1989, 2, 24),
                deathday            = None,
                death_reason        = None,
                height_cm           = 174.0,
                countries           = ['England'],
            )
