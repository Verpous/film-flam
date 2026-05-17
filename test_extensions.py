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
# along with this program. If not, see <https://www.gnu.org/licenses/>.

# pylint: disable=unused-argument

import typing
import random
import datetime
import dataclasses

import flam
from flam import utils
from flam import attrutils

# This fetcher takes a size of a list to "fetch" and literally makes up a list with phony data.
@flam.register
class RandomDataFetcher(flam.Fetcher, list_type='random-size'):
    def _fetch_into_file(self, movie_list_file: flam.MovieListFile) -> None:
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
                    raise flam.FetchInterrupt("User interrupted fetch in the middle.") from e

                # Save what we've fetched so far, so that if we experience a crash, data won't have to be re-fetched.
                self._checkpoint(movie_list_file)

    def fetch_movie(self, movie_list_file: flam.MovieListFile, uid: str) -> None:
        TITLES_POOL = ['Star Wars', 'Inside Llewyn Davis', 'Lord of the Rings', 'Interstellar']
        CHARACTERS_POOL = ['Darth Vader', 'Llewyn Davis', 'Galadriel', 'Murph']

        # We'll seed the movie's RNG using its uid.
        rng = random.Random(uid)

        # It's important to acquire all the movie's data and populate the file with the people from the movie before we add the movie itself.
        # So we'll start by building the movie's crews.
        crew = {}

        for crew_type in flam.CrewType.iterate_except_any():
            # Randomly decide how many people are in this movie in this crew type.
            # For their uid, we'll add some random base so that you don't get the same people everywhere.
            num_crewmembers = rng.randint(0, 10)
            base_uid = rng.randint(0, 1000)

            crew[crew_type] = flam.MLFCrew(
                crew_type = crew_type,
                roles_by_uid = {},
            )

            for person_idx in range(num_crewmembers):
                # Make up some uid for this fake person.
                person_uid = str(base_uid + person_idx)

                # For actors, we'll make up a bit of data about which character they played.
                # We can always fill in None, or leave lists empty if we're missing that data.
                crew[crew_type].roles_by_uid[person_uid] = flam.MLFRole(
                    person_uid          = person_uid,
                    is_star             = None,
                    episodes_num        = None,
                    oscar_noms          = [],
                    oscar_wins          = [],
                    characters          = [rng.choice(CHARACTERS_POOL)] if crew_type == flam.CrewType.CAST else [],
                    jobs                = [],
                )

                # This person may have already been fetched because of their presence in another movie or another crew type in this movie.
                if person_uid not in movie_list_file.people_by_uid:
                    self.fetch_person(movie_list_file, person_uid)

        # We support some data about movies which is actually specifically about that movie's presence in this list.
        # For example, the date it was added to this list.
        per_src_data = flam.MLFMoviePerSourceData(
            canon_listdef       = movie_list_file.abstract_listdef,
            list_index          = int(uid),
            list_note           = None,
            listing_date        = None,
        )

        mlf_movie = flam.MLFMovie(
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

    def fetch_person(self, movie_list_file: flam.MovieListFile, uid: str) -> None:
        NAMES_POOL = ['James', 'Spencer', 'Hayden', 'David', 'Oscar', 'Cate', 'Jessica', 'Ellen']
        GENDERS_POOL = ['male', 'female', 'nonbinary']

        # We'll seed the person's RNG using its uid.
        rng = random.Random(uid)

        movie_list_file.people_by_uid[uid] = flam.MLFPerson(
            uid                 = uid,
            name                = rng.choice(NAMES_POOL),
            gender              = rng.choice(GENDERS_POOL),
            birthday            = datetime.date(1989, 2, 24),
            deathday            = None,
            death_reason        = None,
            height_cm           = 174.0,
            countries           = ['England'],
        )

# People predicate which checks if no movies the people were in pass the subfilter.
@flam.register
class NoMoviePredicate(flam.Predicate, name_without_type='no-movie', findable_type=flam.FindableType.PEOPLE):
    def __init__(self, filter: flam.Filter) -> None:
        self._filter = filter
    
    @classmethod
    def eat(cls, params: flam.EatParams, at: int) -> tuple[flam.Predicate, int]:
        sub_params = dataclasses.replace(params, find=flam.FindableType.MOVIES)
        filter, until = cls.eat_subfilter(sub_params, at)
        return cls(filter), until

    # Because this is a people predicate, we must implement _excrete_from_people.
    def _excrete_from_people(self, people: flam.People, mlf_people: list[flam.MLFPerson]) -> bool:
        for movie in people.associated_movies():
            if self._filter.excrete(movie):
                return False

        return True

    # Implementing this is optional. It enables us to decompile the filter.
    def regurgitate(self) -> typing.Iterable[str]:
        yield from super().regurgitate()
        yield from self._filter.regurgitate()

    # Implementing this is optional. It enables us to walk the filter nodes.
    def colonoscopy(self) -> typing.Iterable[flam.FilterMember]:
        yield self
        yield from self._filter.colonoscopy()

@flam.register
@attrutils.easy_attribute(attrutils.EasyAttributeParams(
    name_without_type = 'title-uppercase',
    aliases_without_type = [],
    findable_type = flam.FindableType.MOVIES,
    type_handler = attrutils.STR_HANDLER,
    is_ascending = True,
    truncation_style = utils.TruncationStyle.NO_TRIM,
    default_max_len = 999,
))
def movie_uppercase_title_extractor(self: attrutils.EasyAttribute, movie: flam.Movie, mlf_movie: flam.MLFMovie) -> None | str:
    return mlf_movie.title.upper() if mlf_movie.title is not None else None
