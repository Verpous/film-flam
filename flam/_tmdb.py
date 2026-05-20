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

from __future__ import annotations

import dataclasses
import datetime
import typing
import time

from . import _reg
from . import _fetch
from . import _exc
from . import _mlf
from . import _ml
from . import _dbg
from . import utils

_UID_FAMILY = 'tmdb'

# These are the names TMDB uses specifically. I hate to put this inside a class but it's necessary for match statements to work with it.
# Note I don't think there's a reason to turn this class into an enum.
class _MediaType:
    MOVIE = 'movie'
    SHOW = 'tv'

@dataclasses.dataclass
class MovieExternalInfo:
    # Metadata.
    uid:                str
    loading_title:      str
    media_type:         None | str

    # Per src data.
    list_index:         None | int
    list_note:          None | str
    listing_date:       None | datetime.date

    # Universal data.
    my_rating:          None | float
    is_liked:           None | bool
    watch_dates:        list[datetime.date]
    my_notes:           list[str]

# https://developer.themoviedb.org/v4/reference/getting-started
@_reg._register_builtin
class TMDBFetcher(_fetch.Fetcher, list_type='tmdb-list', uid_family=_UID_FAMILY):
    """TMDB_LIST_ID
        
    Takes a TMDB list ID as an input, and downloads the list using the `TMDB API <https://developer.themoviedb.org/docs/getting-started>`__.

    It's easy to check what is your list's ID. Just open it in the browser, and the URL should look like this: https://www.themoviedb.org/list/7103008-movies-i-ve-watched.
    The list ID in this example is "7103008".

    A few special list IDs are also supported:
    
        * ``favorite-movies``
        * ``favorite-shows``
        * ``rated-movies``
        * ``rated-shows``
        * ``watchlist-movies``
        * ``watchlist-shows``

    In order to use this fetcher, you **MUST** have a TMDB API token, and export it to the environment.
    You can request an API token from your `profile settings on TMDB <https://www.themoviedb.org/settings/api>`__.
    
    Once you've been granted access, take the "API Read Access Token" from your profile page and assign it to an environment variable named **FLAM_TMDB_API_TOKEN**:

    .. code-block:: bash
        
        export FLAM_TMDB_API_TOKEN="abcdefgverylongstringofrandomcharacters"
    """
    def _fetch_into_file(self, movie_list_file: _mlf.MovieListFile) -> None:
        list_id = self.concrete_listdef.address
        list_index = 1
        mexs = []
        _dbg.logger.info(f"Going to download TMDB list: {list_id}")

        # TMDB legally requires us to not cache data for more than 6 months.
        if len(movie_list_file.movies_by_uid) == 0:
            movie_list_file.expiration_date = datetime.date.today() + datetime.timedelta(days=6 * 30)

        match list_id:
            case 'favorite-movies':
                # https://developer.themoviedb.org/reference/account-get-favorites
                # TMDB accepts "null" account because it actually knows the account from the access token.
                # Use v3 of the API for favorites, rated, watchlist because v4 requires a real PITA authentication process.
                for favorite_movies_json in self._paginated_rest_call('3/account/null/favorite/movies'):
                    for movie_json in favorite_movies_json['results']:
                        mexs.append(MovieExternalInfo(
                            uid             = str(movie_json['id']),
                            loading_title   = movie_json['title'],
                            media_type      = _MediaType.MOVIE,

                            list_index      = list_index,
                            list_note       = None,
                            listing_date    = None,

                            my_rating       = None,
                            is_liked        = None,
                            watch_dates     = [],
                            my_notes        = [],
                        ))
                        
                        list_index += 1
            case 'favorite-shows':
                # https://developer.themoviedb.org/reference/account-favorite-tv
                for favorite_shows_json in self._paginated_rest_call('3/account/null/favorite/tv'):
                    for show_json in favorite_shows_json['results']:
                        mexs.append(MovieExternalInfo(
                            uid             = str(show_json['id']),
                            loading_title   = show_json['name'],
                            media_type      = _MediaType.SHOW,

                            list_index      = list_index,
                            list_note       = None,
                            listing_date    = None,

                            my_rating       = None,
                            is_liked        = None,
                            watch_dates     = [],
                            my_notes        = [],
                        ))
                        
                        list_index += 1
            case 'rated-movies':
                # https://developer.themoviedb.org/reference/account-rated-movies
                for rated_movies_json in self._paginated_rest_call('3/account/null/rated/movies'):
                    for movie_json in rated_movies_json['results']:
                        mexs.append(MovieExternalInfo(
                            uid             = str(movie_json['id']),
                            loading_title   = movie_json['title'],
                            media_type      = _MediaType.MOVIE,

                            list_index      = list_index,
                            list_note       = None,
                            listing_date    = None,

                            my_rating       = None, # We'll fetch the rating later anyway.
                            is_liked        = None,
                            watch_dates     = [],
                            my_notes        = [],
                        ))
                        
                        list_index += 1
            case 'rated-shows':
                # https://developer.themoviedb.org/reference/account-rated-tv
                for rated_shows_json in self._paginated_rest_call('3/account/null/rated/tv'):
                    for show_json in rated_shows_json['results']:
                        mexs.append(MovieExternalInfo(
                            uid             = str(show_json['id']),
                            loading_title   = show_json['name'],
                            media_type      = _MediaType.SHOW,

                            list_index      = list_index,
                            list_note       = None,
                            listing_date    = None,

                            my_rating       = None,
                            is_liked        = None,
                            watch_dates     = [],
                            my_notes        = [],
                        ))
                        
                        list_index += 1
            case 'watchlist-movies':
                # https://developer.themoviedb.org/reference/account-watchlist-movies
                for watchlist_movies_json in self._paginated_rest_call('3/account/null/watchlist/movies'):
                    for movie_json in watchlist_movies_json['results']:
                        mexs.append(MovieExternalInfo(
                            uid             = str(movie_json['id']),
                            loading_title   = movie_json['title'],
                            media_type      = _MediaType.MOVIE,

                            list_index      = list_index,
                            list_note       = None,
                            listing_date    = None,

                            my_rating       = None, # We'll fetch the rating later anyway.
                            is_liked        = None,
                            watch_dates     = [],
                            my_notes        = [],
                        ))
                        
                        list_index += 1
            case 'watchlist-shows':
                # https://developer.themoviedb.org/reference/account-watchlist-tv
                for watchlist_shows_json in self._paginated_rest_call('3/account/null/watchlist/tv'):
                    for show_json in watchlist_shows_json['results']:
                        mexs.append(MovieExternalInfo(
                            uid             = str(show_json['id']),
                            loading_title   = show_json['name'],
                            media_type      = _MediaType.SHOW,

                            list_index      = list_index,
                            list_note       = None,
                            listing_date    = None,

                            my_rating       = None,
                            is_liked        = None,
                            watch_dates     = [],
                            my_notes        = [],
                        ))
                        
                        list_index += 1
            case _:
                # https://developer.themoviedb.org/v4/reference/list-details
                # Use v4 of the API for list details because it gives us access to private lists and mixed-type lists.
                for list_details_json in self._paginated_rest_call(f'4/list/{list_id}'):
                    for movie_json in list_details_json['results']:
                        mexs.append(MovieExternalInfo(
                            uid             = str(movie_json['id']),
                            loading_title   = movie_json['title'] if movie_json['media_type'] == _MediaType.MOVIE else movie_json['name'],
                            media_type      = movie_json['media_type'],

                            list_index      = list_index,
                            list_note       = list_details_json['comments'][f"{movie_json['media_type']}:{movie_json['id']}"],
                            listing_date    = None,

                            my_rating       = None,
                            is_liked        = None,
                            watch_dates     = [],
                            my_notes        = [],
                        ))
                        
                        # Easier and safer than knowing TMDB's page size and calculating the index.
                        list_index += 1

        self._fetch_external_movies_into_file(mexs, None, self, movie_list_file)
        _dbg.logger.info("Done fetching movies")

    # Valid external_sources: imdb_id, facebook_id, instagram_id, instagram_id, tvdb_id, tiktok_id, twitter_id, wikidata_id, youtube_id.
    @classmethod
    def _fetch_external_movies_into_file(cls, movie_external_infos: list[MovieExternalInfo], external_source: None | str, fetcher: _fetch.Fetcher, mlf: _mlf.MovieListFile) -> None:
        _dbg.logger.info(f"MLF has {len(mlf.movies_by_uid)} movies from prior fetch")

        # Only fetch movies not already in the list, and also if the same movie appears multiple times in the list, fetch it only once.
        # Multiple appearances of the same movie are not supported.
        # For external movies we can remove duplicates but we can't know yet if it's already in the list so will have to fetch it anyway (at least partially).
        movies_to_fetch = list(utils.stable_dedup(
            (m for m in movie_external_infos if external_source is not None or m.uid not in mlf.movies_by_uid),
            key=lambda m: m.uid
        ))

        _dbg.logger.info(f"There are {len(movies_to_fetch)} new movies to fetch")

        try:
            # NOTE: I prefer a single pass where you convert the UIDs and fetch the movie details rather than two passes.
            # With two passes, the first pass would do a lot of work that can't be checkpointed and if you Ctrl+C you lose it all.
            with utils.ProgressBar(movies_to_fetch,
                    desc='Downloading',
                    keyfunc=lambda m: m.loading_title) as bar:
                for movie_external_info in bar:
                    cls._fetch_media(movie_external_info, external_source, mlf)

                    # Checkpoint after every movie because this fetcher ain't so fast.
                    fetcher._checkpoint(mlf)
        # If we get a KeyboardInterrupt, gracefully end the fetching early.
        except KeyboardInterrupt as e:
            raise _exc.FetchInterrupt(f"{type(e).__name__}: {e}") from e

        # Only if fetch wasn't interrupted and we've reached the end, we can be sure that all uids have been converted and we can omit movies no longer in the list.
        uids = {m.uid for m in movie_external_infos}
        mlf.movies_by_uid = {uid: m for uid, m in mlf.movies_by_uid.items() if uid in uids}
        _dbg.logger.info(f"MLF has {len(mlf.movies_by_uid)} movies after omitting ones no longer in the list")

    @classmethod
    def _fetch_media(cls, mex: MovieExternalInfo, external_source: None | str, mlf: _mlf.MovieListFile) -> None:
        _dbg.logger.info(f"Fetching movie: {mex.uid} ({mex.loading_title})")

        if external_source is not None:
            if not cls._translate_external_info(mex, external_source):
                return

            # We've only just discovered what the uid is, so naturally we couldn't know until now if this movie is already fetched and can be skipped.
            # This kind of sucks because it means with this fetcher even when there's only 1 new movie in the list you still have to spend time on every movie.
            # TODO: consider some cache of ID translations.
            # TODO: actually, TMDB can discover external_ids of things. So we can change the UID family to the source,
            #       and then we'll be able to even skip translating everything just to know what needs to be fetched!
            #       This should work dandy for IMDb but not for letterboxd because TMDB has no letterboxd ids.. but letterboxdpy has TMDB ids, don't it?
            if mex.uid in mlf.movies_by_uid:
                return

        # Should've been set by the translate call above.
        assert mex.media_type is not None

        match mex.media_type:
            case _MediaType.MOVIE:
                cls._fetch_movie(mex, external_source, mlf)
            case _MediaType.SHOW:
                cls._fetch_tv_show(mex, external_source, mlf)
            case _:
                raise RuntimeError(f'Unexpected {mex.media_type=}')

    @classmethod
    def _fetch_movie(cls, mex: MovieExternalInfo, external_source: None | str, mlf: _mlf.MovieListFile) -> None:
        # https://developer.themoviedb.org/reference/movie-credits
        details_of_interest = ['credits']
        
        if external_source is None:
            # https://developer.themoviedb.org/reference/movie-account-states
            details_of_interest.append('account_states')

        # https://developer.themoviedb.org/reference/movie-details
        movie_json = cls._rest_call(f'3/movie/{mex.uid}', append_to_response=','.join(details_of_interest))

        # If this is originally a TMDB list, fill in some user-specific details about that film.
        # Otherwise we expect to already have that information from the external source.
        if external_source is None:
            # If no rating you get false, if rating you get a json sub object..
            mex.my_rating = movie_json['account_states']['rated']['value'] if movie_json['account_states']['rated'] is not False else None
            mex.is_liked = movie_json['account_states']['favorite']
            mex.watch_dates = []

            # NOTE: TMDB does actually have global reviews we could populate here, but no way to reach them for a specific user.
            mex.my_notes = []

        mlf_crew = {
            crew_type: _mlf.MLFCrew(crew_type=crew_type, roles_by_uid={})
            for crew_type in _ml.CrewType.iterate_except_any()
        }

        for crewmember_json in movie_json['credits']['crew']:
            crew_type = cls._crew_type_tmdb2flam(crewmember_json['job'])
            person_uid = str(crewmember_json['id'])

            # Sometimes we map multiple TMDB crew types to the same flam crew type. This is especially true for ADDITIONAL crew type, but not only.
            if person_uid not in mlf_crew[crew_type].roles_by_uid:
                mlf_crew[crew_type].roles_by_uid[person_uid] = _mlf.MLFRole(
                    person_uid          = person_uid,
                    is_star             = None,
                    episodes_num        = None,
                    oscar_noms          = [],
                    oscar_wins          = [],
                    characters          = [],
                    jobs                = [],
                )
            
            # For ADDITIONAL crew type we can record all the multiple occurrences of that person. For other crew types, we'll not record it.
            if crew_type == _ml.CrewType.ADDITIONAL:
                mlf_crew[crew_type].roles_by_uid[person_uid].jobs.append(crewmember_json['job'])

            # Castmembers generally shouldn't be here, but sometimes they are, so we'll add their 'job' as the character (e.g. "Stand In").
            if crew_type == _ml.CrewType.CAST:
                mlf_crew[crew_type].roles_by_uid[person_uid].characters.append(crewmember_json['job'])

        for castmember_json in movie_json['credits']['cast']:
            person_uid = str(castmember_json['id'])

            # Usually even if the same person played multiple characters they appear only once, but there are exceptions so we must be vigilant.
            if person_uid not in mlf_crew[_ml.CrewType.CAST].roles_by_uid:
                mlf_crew[_ml.CrewType.CAST].roles_by_uid[person_uid] = _mlf.MLFRole(
                    person_uid          = person_uid,
                    is_star             = None,
                    episodes_num        = None,
                    oscar_noms          = [],
                    oscar_wins          = [],
                    characters          = [],
                    jobs                = [],
                )

            # Multiple characters are separated by ' / '. We could split it, but I think it's risky and not worth it.
            mlf_crew[_ml.CrewType.CAST].roles_by_uid[person_uid].characters.append(castmember_json['character'])

        cls._fetch_people(mlf_crew, mlf)

        per_src_data = _mlf.MLFMoviePerSourceData(
            canon_listdef       = mlf.abstract_listdef,
            list_index          = mex.list_index,
            list_note           = mex.list_note,
            listing_date        = mex.listing_date,
        )

        mlf_movie = _mlf.MLFMovie(
            uid                 = mex.uid,
            per_src_data        = [per_src_data],
            media_type          = _MediaType.MOVIE,
            title               = movie_json['title'],
            original_title      = movie_json['original_title'],
            tagline             = movie_json['tagline'],
            synopsis            = movie_json['overview'],

            # NOTE: movie_json['homepage'] is not what we want - it's an external link to the movie's own website.
            url                 = f'https://www.themoviedb.org/movie/{mex.uid}',
            runtime_minutes     = movie_json['runtime'],
            metascore_votes     = None,
            metascore           = None,
            votes               = movie_json['vote_count'],
            rating              = movie_json['vote_average'],
            my_rating           = mex.my_rating,
            likes               = None,
            is_liked            = mex.is_liked,
            budget_usd          = movie_json['budget'],
            revenue_usd         = movie_json['revenue'],
            content_rating      = None,
            release_date        = cls._parse_date(movie_json['release_date']),
            watch_dates         = mex.watch_dates,
            my_notes            = mex.my_notes,
            episodes_num        = None,
            seasons_num         = None,
            end_date            = None,
            genres              = [g['name'] for g in movie_json['genres']],
            studios             = [p['name'] for p in movie_json['production_companies']],
            
            # NOTE: there's also 'name' (in its own language) and 'iso_639_1' (standardized name like "en").
            languages           = [l['english_name'] for l in movie_json['spoken_languages']],

            # NOTE: there's also 'origin_country' but it's not what we want.
            countries           = [c['name'] for c in movie_json['production_countries']],
            crew                = mlf_crew,
        )

        mlf.movies_by_uid[mlf_movie.uid] = mlf_movie

    @classmethod
    def _fetch_tv_show(cls, mex: MovieExternalInfo, external_source: None | str, mlf: _mlf.MovieListFile) -> None:
        # NOTE: TV also has content_ratings but as long as we don't have that for movies I think it's not interesting.
        # https://developer.themoviedb.org/reference/tv-series-aggregate-credits
        details_of_interest = ['aggregate_credits']
        
        if external_source is None:
            # https://developer.themoviedb.org/reference/tv-series-account-states
            details_of_interest.append('account_states')

        # https://developer.themoviedb.org/reference/tv-series-details
        show_json = cls._rest_call(f'3/tv/{mex.uid}', append_to_response=','.join(details_of_interest))

        # If this is originally a TMDB list, fill in some user-specific details about that film.
        # Otherwise we expect to already have that information from the external source.
        if external_source is None:
            # If no rating you get false, if rating you get a json sub object... AND the API documents this as an int for TV shows but it's a float!
            mex.my_rating = show_json['account_states']['rated']['value'] if show_json['account_states']['rated'] is not False else None
            mex.is_liked = show_json['account_states']['favorite']
            mex.watch_dates = []

            # NOTE: TMDB does actually have global reviews we could populate here, but no way to reach them for a specific user.
            mex.my_notes = []

        mlf_crew = {
            crew_type: _mlf.MLFCrew(crew_type=crew_type, roles_by_uid={})
            for crew_type in _ml.CrewType.iterate_except_any()
        }

        for crewmember_json in show_json['aggregate_credits']['crew']:
            person_uid = str(crewmember_json['id'])

            for job_json in crewmember_json['jobs']:
                crew_type = cls._crew_type_tmdb2flam(job_json['job'])

                # Sometimes we map multiple TMDB crew types to the same flam crew type. This is especially true for ADDITIONAL crew type, but not only.
                if person_uid not in mlf_crew[crew_type].roles_by_uid:
                    mlf_crew[crew_type].roles_by_uid[person_uid] = _mlf.MLFRole(
                        person_uid          = person_uid,
                        is_star             = None,
                        
                        # NOTE: this can wind up misleading because not all episodes had to be in this crew type.
                        # We do have access to episodes count per job, but that too could be misleading because a person can have multiple jobs in the same crew type.
                        episodes_num        = crewmember_json['total_episode_count'],
                        oscar_noms          = [],
                        oscar_wins          = [],
                        characters          = [],
                        jobs                = [],
                    )
                
                # For ADDITIONAL crew type we can record all the multiple occurrences of that person. For other crew types, we'll not record it.
                if crew_type == _ml.CrewType.ADDITIONAL:
                    mlf_crew[crew_type].roles_by_uid[person_uid].jobs.append(job_json['job'])

                # Castmembers generally shouldn't be here, but sometimes they are, so we'll add their 'job' as the character (e.g. "Stand In").
                if crew_type == _ml.CrewType.CAST:
                    mlf_crew[crew_type].roles_by_uid[person_uid].characters.append(job_json['job'])

        for castmember_json in show_json['aggregate_credits']['cast']:
            person_uid = str(castmember_json['id'])

            # Usually even if the same person played multiple characters they appear only once, but there are exceptions so we must be vigilant.
            if person_uid not in mlf_crew[_ml.CrewType.CAST].roles_by_uid:
                mlf_crew[_ml.CrewType.CAST].roles_by_uid[person_uid] = _mlf.MLFRole(
                    person_uid              = person_uid,
                    is_star                 = None,
                    episodes_num            = castmember_json['total_episode_count'],
                    oscar_noms              = [],
                    oscar_wins              = [],
                    characters              = [],
                    jobs                    = [],
                )

            mlf_crew[_ml.CrewType.CAST].roles_by_uid[person_uid].characters.extend(r['character'] for r in castmember_json['roles'])

        cls._fetch_people(mlf_crew, mlf)

        per_src_data = _mlf.MLFMoviePerSourceData(
            canon_listdef       = mlf.abstract_listdef,
            list_index          = mex.list_index,
            list_note           = mex.list_note,
            listing_date        = mex.listing_date,
        )

        mlf_movie = _mlf.MLFMovie(
            uid                 = mex.uid,
            per_src_data        = [per_src_data],
            media_type          = _MediaType.SHOW,
            title               = show_json['name'],
            original_title      = show_json['original_name'],
            tagline             = show_json['tagline'],
            synopsis            = show_json['overview'],

            # NOTE: movie_json['homepage'] is not what we want - it's an external link to the movie's own website.
            url                 = f'https://www.themoviedb.org/tv/{mex.uid}',
            runtime_minutes     = int(sum(show_json['episode_run_time']) / len(show_json['episode_run_time'])) if len(show_json['episode_run_time']) > 0 else None,
            metascore_votes     = None,
            metascore           = None,
            votes               = show_json['vote_count'],
            rating              = show_json['vote_average'],
            my_rating           = mex.my_rating,
            likes               = None,
            is_liked            = mex.is_liked,
            budget_usd          = None,
            revenue_usd         = None,
            content_rating      = None,
            release_date        = cls._parse_date(show_json['first_air_date']),
            watch_dates         = mex.watch_dates,
            my_notes            = mex.my_notes,
            episodes_num        = show_json['number_of_episodes'],
            seasons_num         = show_json['number_of_seasons'],

            # This will be the last episode to air so far if the show is still running, and that's OK.
            end_date            = cls._parse_date(show_json['last_air_date']),
            genres              = [g['name'] for g in show_json['genres']],
            studios             = [p['name'] for p in show_json['production_companies']],
            
            # NOTE: there's also 'name' (in its own language) and 'iso_639_1' (standardized name like "en").
            languages           = [l['english_name'] for l in show_json['spoken_languages']],

            # NOTE: there's also 'origin_country' but it's not what we want.
            countries           = [c['name'] for c in show_json['production_countries']],
            crew                = mlf_crew,
        )

        mlf.movies_by_uid[mlf_movie.uid] = mlf_movie

    @classmethod
    def _translate_external_info(cls, mex: MovieExternalInfo, external_source: None | str) -> bool:
        _dbg.logger.info(f"Translating movie uid: {mex.uid=}, {external_source=}, {mex.loading_title=}")

        # https://developer.themoviedb.org/reference/find-by-id
        # NOTE: for imdb it is expected to include the 'tt'.
        matches_json = cls._rest_call(f'3/find/{mex.uid}', external_source=external_source)

        # NOTE: the result also includes matching people, TV seasons, and TV episodes.
        # We're ignoring those although it may be worth checking them to raise a meaningful exception.
        matching_ids = [
            *((str(m['id']), m['media_type'], m['title']) for m in matches_json['movie_results']),
            *((str(s['id']), s['media_type'], s['name']) for s in matches_json['tv_results']),
        ]

        # We can't raise an error for failed translations, some titles really are missing. For example המובילים is not on TMDB.
        if len(matching_ids) == 0:
            _dbg.logger.warning(f"Failed to find TMDB ID for {external_source}: '{mex.uid}' (movie: {mex.loading_title}).")
            return False

        # We can easily discover the media type for ourselves, but we'll allow users to specify the media type to resolve ambiguities.
        matching_ids_and_type = [
            (uid, media_type, title)
            for uid, media_type, title in matching_ids
            if mex.media_type is None or mex.media_type == media_type
        ]

        if len(matching_ids_and_type) == 0:
            _dbg.logger.warning(f"Failed to find TMDB ID for {external_source}: '{mex.uid}' (movie: {mex.loading_title}): "
                f"all matching titles have a different type than {mex.media_type}: {', '.join(
                f'{media_type}: {uid} ({title})' for uid, media_type, title in matching_ids_and_type)}")
            return False

        if len(matching_ids_and_type) > 1:
            raise _exc.InputError(f"Failed to find TMDB ID for {external_source}: '{mex.uid}' (movie: {mex.loading_title}): "
                f"too many matching titles: {', '.join(f'{media_type}: {uid} ({title})' for uid, media_type, title in matching_ids_and_type)}.")
        
        uid, media_type, _ = matching_ids_and_type[0]
        mex.uid = uid
        mex.media_type = media_type
        return True

    @classmethod
    def _fetch_people(cls, mlf_crew: dict[_ml.CrewType, _mlf.MLFCrew], mlf: _mlf.MovieListFile) -> None:
        # They're new and unique - they're newniq!
        newniq_people_uids = {
            uid
            for crew in mlf_crew.values()
                for uid in crew.roles_by_uid
                    if uid not in mlf.people_by_uid
        }

        # They don't need to be sorted, but I guess it's good for debugging if the order is consistent.
        for uid in sorted(newniq_people_uids):
            _dbg.logger.info(f"Fetching person: {uid}")

            # https://developer.themoviedb.org/reference/person-details
            person_json = cls._rest_call(f'3/person/{uid}')

            # This is documented on the API.
            match person_json['gender']:
                case 0: gender = None
                case 1: gender = 'female'
                case 2: gender = 'male'
                case 3: gender = 'nonbinary'
                case _:
                    raise RuntimeError(f"Unexpected {person_json['gender']=}.")

            mlf.people_by_uid[uid] = _mlf.MLFPerson(
                uid             = uid,
                name            = person_json['name'],
                gender          = gender,
                birthday        = cls._parse_date(person_json['birthday']),
                deathday        = cls._parse_date(person_json['deathday']),
                death_reason    = None,
                height_cm       = None,
                countries       = [person_json['place_of_birth']] if person_json['place_of_birth'] is not None else [],
            )

    @classmethod
    def _rest_call(cls, endpoint: str, **kwargs: typing.Any) -> dict:
        # Import requests only here because it's actually a very expensive import so we don't wanna pay that price for every import of flam when most of them don't need it.
        import requests

        NUM_RETRIES = 20
        SLEEP_BETWEEN_RETRIES = 2
        
        if not _dbg.FlamEnv.TMDB_API_TOKEN.is_defined:
            raise _exc.InputError(f"Can't fetch from TMDB: please export your API read access token in {_dbg.FlamEnv.TMDB_API_TOKEN}.")
        
        read_access_token = _dbg.FlamEnv.TMDB_API_TOKEN.get_or_default()

        headers = dict(
            authorization = f'Bearer {read_access_token}',
            accept = 'application/json',
        )

        for i in range(NUM_RETRIES):
            response = requests.get(f'https://api.themoviedb.org/{endpoint}', headers=headers, timeout=30, params=kwargs)
            _dbg.logger.info(f"Requested: {response.url} with res: {response.status_code}")

            try:
                response.raise_for_status()
            except requests.HTTPError as e:
                should_retry = (
                   response.status_code == requests.codes.too_many_requests # pylint: disable=no-member
                   or 500 <= response.status_code < 600
                )
                
                # Everything not known to be retry-worthy is a crash.
                if not should_retry:
                    raise

                # Known errors that failed every retry are fetch-interrupts.
                if i == NUM_RETRIES - 1:
                    raise _exc.FetchInterrupt(f"TMDB error: {type(e).__name__}: {e}") from e

                # The response text sometimes contains additional information.
                _dbg.logger.warning(f"RETRY {i}/{NUM_RETRIES}: request failed with status code: {response.status_code}, text: {response.text}.")
                time.sleep(SLEEP_BETWEEN_RETRIES)
                continue

            return response.json()

        raise RuntimeError("Shouldn't get here!")

    @classmethod
    def _paginated_rest_call(cls, endpoint: str, **kwargs: typing.Any) -> list[dict]:
        all_responses = []
        response = cls._rest_call(endpoint, **kwargs)
        all_responses.append(response)

        while response['page'] < response['total_pages']:
            response = cls._rest_call(endpoint, page=response['page'] + 1, **kwargs)
            all_responses.append(response)

        return all_responses

    @classmethod
    def _parse_date(cls, date_str: None | str) -> None | datetime.date:
        if date_str is None:
            return None

        return datetime.datetime.strptime(date_str, '%Y-%m-%d').date()

    # NOTE: this function must never return CAST.
    @classmethod
    def _crew_type_tmdb2flam(cls, tmdb_crew_type: str) -> _ml.CrewType:
        try:
            # TMDB is usually consistent about having the exact same casing but on occasion they do slip.
            return _crew_type_tmdb2flam_mapping[tmdb_crew_type.lower()]
        except KeyError:
            # We've done painstaking work to manually identify and map every possible crew type, yet we still get unrecognized types from time to time.
            _dbg.logger.warning(f"Got unexpected TMDB crew type: '{tmdb_crew_type}'. Mapping it to ADDITIONAL.")
            return _ml.CrewType.ADDITIONAL

# This is a complete list of possible credits in TMDB acquired from this endpoint: https://developer.themoviedb.org/reference/configuration-jobs.
# There are some credits not returned by TMDB which we've gathered ourselves over time.
# NOTE: TMDB can actually have the same crew type in several departments. We've gotten rid of duplicates here, but this note is in case it'll be important someday.
# NOTE: python imports this blazing quick so there's no need to lazy-load it.
_crew_type_tmdb2flam_mapping = {
    # Department: Production.
    "casting":                                              _ml.CrewType.CASTING_DIRECTOR, # Often there's no "Casting Director" but there is this.
    "line producer":                                        _ml.CrewType.ADDITIONAL,
    "co-producer":                                          _ml.CrewType.PRODUCER,
    "accounting trainee":                                   _ml.CrewType.ADDITIONAL,
    "assistant extras casting":                             _ml.CrewType.ADDITIONAL,
    "first assistant accountant":                           _ml.CrewType.ADDITIONAL,
    "general manager":                                      _ml.CrewType.ADDITIONAL,
    "head of production":                                   _ml.CrewType.ADDITIONAL,
    "locale casting director":                              _ml.CrewType.ADDITIONAL,
    "location assistant":                                   _ml.CrewType.ADDITIONAL,
    "location coordinator":                                 _ml.CrewType.ADDITIONAL,
    "post production technical engineer":                   _ml.CrewType.ADDITIONAL,
    "location manager":                                     _ml.CrewType.ADDITIONAL,
    "production accountant":                                _ml.CrewType.ADDITIONAL,
    "supervising producer":                                 _ml.CrewType.ADDITIONAL,
    "production manager":                                   _ml.CrewType.ADDITIONAL,
    "consulting producer":                                  _ml.CrewType.ADDITIONAL,
    "assistant production manager":                         _ml.CrewType.ADDITIONAL,
    "other":                                                _ml.CrewType.ADDITIONAL,
    "finance":                                              _ml.CrewType.ADDITIONAL,
    "character technical supervisor":                       _ml.CrewType.ADDITIONAL,
    "development manager":                                  _ml.CrewType.ADDITIONAL,
    "production coordinator":                               _ml.CrewType.ADDITIONAL,
    "adr voice casting":                                    _ml.CrewType.ADDITIONAL,
    "additional post-production supervisor":                _ml.CrewType.ADDITIONAL,
    "art department production assistant":                  _ml.CrewType.ADDITIONAL,
    "back-up truck production assistant":                   _ml.CrewType.ADDITIONAL,
    "accounting clerk assistant":                           _ml.CrewType.ADDITIONAL,
    "broadcast producer":                                   _ml.CrewType.ADDITIONAL,
    "extras casting coordinator":                           _ml.CrewType.ADDITIONAL,
    "grip production assistant":                            _ml.CrewType.ADDITIONAL,
    "key set production assistant":                         _ml.CrewType.ADDITIONAL,
    "musical casting":                                      _ml.CrewType.ADDITIONAL,
    "post production accountant":                           _ml.CrewType.ADDITIONAL,
    "development producer":                                 _ml.CrewType.ADDITIONAL,
    "key accountant":                                       _ml.CrewType.ADDITIONAL,
    "production assistant":                                 _ml.CrewType.ADDITIONAL,
    "production consultant":                                _ml.CrewType.ADDITIONAL,
    "second assistant production coordinator":              _ml.CrewType.ADDITIONAL,
    "truck production assistant":                           _ml.CrewType.ADDITIONAL,
    "executive consultant":                                 _ml.CrewType.ADDITIONAL,
    "accounting supervisor":                                _ml.CrewType.ADDITIONAL,
    "assistant location manager":                           _ml.CrewType.ADDITIONAL,
    "director of operations":                               _ml.CrewType.ADDITIONAL,
    "executive assistant":                                  _ml.CrewType.ADDITIONAL,
    "insert unit location manager":                         _ml.CrewType.ADDITIONAL,
    "key grip production assistant":                        _ml.CrewType.ADDITIONAL,
    "location casting":                                     _ml.CrewType.ADDITIONAL,
    "unit swing":                                           _ml.CrewType.ADDITIONAL,
    "executive producer":                                   _ml.CrewType.EXECUTIVE_PRODUCER,
    "producer":                                             _ml.CrewType.PRODUCER,
    "executive in charge of production":                    _ml.CrewType.ADDITIONAL,
    "senior executive consultant":                          _ml.CrewType.ADDITIONAL,
    "unit manager":                                         _ml.CrewType.ADDITIONAL,
    "additional casting":                                   _ml.CrewType.ADDITIONAL,
    "assistant accountant":                                 _ml.CrewType.ADDITIONAL,
    "contract manager":                                     _ml.CrewType.ADDITIONAL,
    "extras casting":                                       _ml.CrewType.ADDITIONAL,
    "production driver":                                    _ml.CrewType.ADDITIONAL,
    "production trainee":                                   _ml.CrewType.ADDITIONAL,
    "associate producer":                                   _ml.CrewType.ADDITIONAL,
    "attorney":                                             _ml.CrewType.ADDITIONAL,
    "casting coordinator":                                  _ml.CrewType.ADDITIONAL,
    "casting consultant":                                   _ml.CrewType.ADDITIONAL,
    "local casting":                                        _ml.CrewType.ADDITIONAL,
    "casting producer":                                     _ml.CrewType.ADDITIONAL,
    "first assistant production coordinator":               _ml.CrewType.ADDITIONAL,
    "key art production assistant":                         _ml.CrewType.ADDITIONAL,
    "post production producer":                             _ml.CrewType.ADDITIONAL,
    "production office coordinator":                        _ml.CrewType.ADDITIONAL,
    "back-up set production assistant":                     _ml.CrewType.ADDITIONAL,
    "controller":                                           _ml.CrewType.ADDITIONAL,
    "payroll accountant":                                   _ml.CrewType.ADDITIONAL,
    "post production coordinator":                          _ml.CrewType.ADDITIONAL,
    "production designer":                                  _ml.CrewType.ADDITIONAL,
    "street casting":                                       _ml.CrewType.ADDITIONAL,
    "trainee production coordinator":                       _ml.CrewType.ADDITIONAL,
    "administration":                                       _ml.CrewType.ADDITIONAL,
    "co-executive producer":                                _ml.CrewType.EXECUTIVE_PRODUCER,
    "casting associate":                                    _ml.CrewType.ADDITIONAL,
    "finishing producer":                                   _ml.CrewType.ADDITIONAL,
    "production runner":                                    _ml.CrewType.ADDITIONAL,
    "unit production manager":                              _ml.CrewType.ADDITIONAL,
    "researcher":                                           _ml.CrewType.ADDITIONAL,
    "accountant":                                           _ml.CrewType.ADDITIONAL,
    "human resources":                                      _ml.CrewType.ADDITIONAL,
    "post producer":                                        _ml.CrewType.ADDITIONAL,
    "research assistant":                                   _ml.CrewType.ADDITIONAL,
    "second assistant unit manager":                        _ml.CrewType.ADDITIONAL,
    "production supervisor":                                _ml.CrewType.ADDITIONAL,
    "publicist":                                            _ml.CrewType.ADDITIONAL,
    "assistant production coordinator":                     _ml.CrewType.ADDITIONAL,
    "script researcher":                                    _ml.CrewType.ADDITIONAL,
    "executive in charge of post production":               _ml.CrewType.ADDITIONAL,
    "production director":                                  _ml.CrewType.ADDITIONAL,
    "casting assistant":                                    _ml.CrewType.ADDITIONAL,
    "coordinating producer":                                _ml.CrewType.ADDITIONAL,
    "executive co-producer":                                _ml.CrewType.EXECUTIVE_PRODUCER,
    "key production assistant":                             _ml.CrewType.ADDITIONAL,
    "location production assistant":                        _ml.CrewType.ADDITIONAL,
    "production executive":                                 _ml.CrewType.ADDITIONAL,
    "business affairs coordinator":                         _ml.CrewType.ADDITIONAL,
    "data management technician":                           _ml.CrewType.ADDITIONAL,
    "executive producer's assistant":                       _ml.CrewType.ADDITIONAL,
    "extras casting assistant":                             _ml.CrewType.ADDITIONAL,
    "feature finishing producer":                           _ml.CrewType.ADDITIONAL,
    "original casting":                                     _ml.CrewType.ADDITIONAL,
    "production secretary":                                 _ml.CrewType.ADDITIONAL,
    "travel coordinator":                                   _ml.CrewType.ADDITIONAL,
    "additional production assistant":                      _ml.CrewType.ADDITIONAL,
    "casting director":                                     _ml.CrewType.CASTING_DIRECTOR,
    "head of research":                                     _ml.CrewType.ADDITIONAL,
    "post coordinator":                                     _ml.CrewType.ADDITIONAL,
    "second assistant accountant":                          _ml.CrewType.ADDITIONAL,
    "assistant unit manager":                               _ml.CrewType.ADDITIONAL,
    "background casting director":                          _ml.CrewType.ADDITIONAL,
    "casting researcher":                                   _ml.CrewType.ADDITIONAL,
    "delegated producer":                                   _ml.CrewType.ADDITIONAL,
    "producer's assistant":                                 _ml.CrewType.ADDITIONAL,
    "second unit location manager":                         _ml.CrewType.ADDITIONAL,
    "consulting accountant":                                _ml.CrewType.ADDITIONAL,
    "head of programming":                                  _ml.CrewType.ADDITIONAL,

    # Department: Costume & Make-Up.
    "costume design":                                       _ml.CrewType.ADDITIONAL,
    "first assistant hairstylist":                          _ml.CrewType.ADDITIONAL,
    "hair department head":                                 _ml.CrewType.ADDITIONAL,
    "ager/dyer":                                            _ml.CrewType.ADDITIONAL,
    "key costumer":                                         _ml.CrewType.ADDITIONAL,
    "costume supervisor":                                   _ml.CrewType.ADDITIONAL,
    "costume coordinator":                                  _ml.CrewType.ADDITIONAL,
    "key set costumer":                                     _ml.CrewType.ADDITIONAL,
    "wig designer":                                         _ml.CrewType.ADDITIONAL,
    "additional wardrobe assistant":                        _ml.CrewType.ADDITIONAL,
    "daily makeup & hair":                                  _ml.CrewType.ADDITIONAL,
    "hair assistant":                                       _ml.CrewType.ADDITIONAL,
    "wardrobe assistant":                                   _ml.CrewType.ADDITIONAL,
    "wardrobe master":                                      _ml.CrewType.ADDITIONAL,
    "hair designer":                                        _ml.CrewType.ADDITIONAL,
    "costume illustrator":                                  _ml.CrewType.ADDITIONAL,
    "extras makeup artist":                                 _ml.CrewType.ADDITIONAL,
    "hairdresser":                                          _ml.CrewType.ADDITIONAL,
    "contact lens designer":                                _ml.CrewType.ADDITIONAL,
    "costume assistant":                                    _ml.CrewType.ADDITIONAL,
    "costume mistress":                                     _ml.CrewType.ADDITIONAL,
    "makeup & hair":                                        _ml.CrewType.ADDITIONAL,
    "wardrobe coordinator":                                 _ml.CrewType.ADDITIONAL,
    "facial setup artist":                                  _ml.CrewType.ADDITIONAL,
    "hair setup":                                           _ml.CrewType.ADDITIONAL,
    "first assistant makeup artist":                        _ml.CrewType.ADDITIONAL,
    "prosthetics painter":                                  _ml.CrewType.ADDITIONAL,
    "special effects key makeup artist":                    _ml.CrewType.ADDITIONAL,
    "truck costumer":                                       _ml.CrewType.ADDITIONAL,
    "hair supervisor":                                      _ml.CrewType.ADDITIONAL,
    "makeup supervisor":                                    _ml.CrewType.ADDITIONAL,
    "tailor":                                               _ml.CrewType.ADDITIONAL,
    "makeup artist":                                        _ml.CrewType.ADDITIONAL,
    "set dressing supervisor":                              _ml.CrewType.ADDITIONAL,
    "key hair stylist":                                     _ml.CrewType.ADDITIONAL,
    "assistant hairstylist":                                _ml.CrewType.ADDITIONAL,
    "wardrobe designer":                                    _ml.CrewType.ADDITIONAL,
    "wigmaker":                                             _ml.CrewType.ADDITIONAL,
    "key makeup artist":                                    _ml.CrewType.ADDITIONAL,
    "tattoo designer":                                      _ml.CrewType.ADDITIONAL,
    "wardrobe specialized technician":                      _ml.CrewType.ADDITIONAL,
    "set dressing artist":                                  _ml.CrewType.ADDITIONAL,
    "prosthetic supervisor":                                _ml.CrewType.ADDITIONAL,
    "contact lens technician":                              _ml.CrewType.ADDITIONAL,
    "extras dresser":                                       _ml.CrewType.ADDITIONAL,
    "key dresser":                                          _ml.CrewType.ADDITIONAL,
    "principal costumer":                                   _ml.CrewType.ADDITIONAL,
    "truck supervisor":                                     _ml.CrewType.ADDITIONAL,
    "hairstylist":                                          _ml.CrewType.ADDITIONAL,
    "contact lens painter":                                 _ml.CrewType.ADDITIONAL,
    "makeup & hair assistant":                              _ml.CrewType.ADDITIONAL,
    "special effects makeup artist":                        _ml.CrewType.ADDITIONAL,
    "co-costume designer":                                  _ml.CrewType.ADDITIONAL,
    "wardrobe supervisor":                                  _ml.CrewType.ADDITIONAL,
    "assistant makeup artist":                              _ml.CrewType.ADDITIONAL,
    "dresser":                                              _ml.CrewType.ADDITIONAL,
    "prosthetics":                                          _ml.CrewType.ADDITIONAL,
    "prosthetics sculptor":                                 _ml.CrewType.ADDITIONAL,
    "set dressing manager":                                 _ml.CrewType.ADDITIONAL,
    "set costumer":                                         _ml.CrewType.ADDITIONAL,
    "key hairdresser":                                      _ml.CrewType.ADDITIONAL,
    "on set dresser":                                       _ml.CrewType.ADDITIONAL,
    "set dressing production assistant":                    _ml.CrewType.ADDITIONAL,
    "makeup department head":                               _ml.CrewType.ADDITIONAL,
    "prosthetic designer":                                  _ml.CrewType.ADDITIONAL,
    "additional hairstylist":                               _ml.CrewType.ADDITIONAL,
    "makeup trainee":                                       _ml.CrewType.ADDITIONAL,
    "shoe design":                                          _ml.CrewType.ADDITIONAL,
    "makeup designer":                                      _ml.CrewType.ADDITIONAL,
    "seamstress":                                           _ml.CrewType.ADDITIONAL,
    "assistant costume designer":                           _ml.CrewType.ADDITIONAL,
    "makeup effects designer":                              _ml.CrewType.ADDITIONAL,
    "costume consultant":                                   _ml.CrewType.ADDITIONAL,
    "prosthetic makeup artist":                             _ml.CrewType.ADDITIONAL,
    "costume designer":                                     _ml.CrewType.ADDITIONAL,
    "costume set supervisor":                               _ml.CrewType.ADDITIONAL,
    "costume standby":                                      _ml.CrewType.ADDITIONAL,
    "costumer":                                             _ml.CrewType.ADDITIONAL,
    "daily wardrobe":                                       _ml.CrewType.ADDITIONAL,
    "assistant hairdresser":                                _ml.CrewType.ADDITIONAL,
    "lead costumer":                                        _ml.CrewType.ADDITIONAL,
    "wardrobe intern":                                      _ml.CrewType.ADDITIONAL,

    # Department: Lighting.
    "rigging gaffer":                                       _ml.CrewType.ADDITIONAL,
    "assistant chief lighting technician":                  _ml.CrewType.ADDITIONAL,
    "lighting technician":                                  _ml.CrewType.ADDITIONAL,
    "master lighting artist":                               _ml.CrewType.ADDITIONAL,
    "lighting supervisor":                                  _ml.CrewType.ADDITIONAL,
    "lighting manager":                                     _ml.CrewType.ADDITIONAL,
    "lighting coordinator":                                 _ml.CrewType.ADDITIONAL,
    "rigging grip":                                         _ml.CrewType.ADDITIONAL,
    "assistant gaffer":                                     _ml.CrewType.ADDITIONAL,
    "best boy lighting technician":                         _ml.CrewType.ADDITIONAL,
    "lighting design":                                      _ml.CrewType.ADDITIONAL,
    "underwater gaffer":                                    _ml.CrewType.ADDITIONAL,
    "lighting director":                                    _ml.CrewType.ADDITIONAL,
    "additional gaffer":                                    _ml.CrewType.ADDITIONAL,
    "lighting production assistant":                        _ml.CrewType.ADDITIONAL,
    "electrician":                                          _ml.CrewType.ADDITIONAL,
    "gaffer":                                               _ml.CrewType.ADDITIONAL,
    "chief lighting technician":                            _ml.CrewType.ADDITIONAL,
    "rigging supervisor":                                   _ml.CrewType.ADDITIONAL,
    "key rigging grip":                                     _ml.CrewType.ADDITIONAL,
    "daily electrics":                                      _ml.CrewType.ADDITIONAL,
    "best boy electrician":                                 _ml.CrewType.ADDITIONAL,
    "genetator operator":                                   _ml.CrewType.ADDITIONAL,
    "lighting programmer":                                  _ml.CrewType.ADDITIONAL,
    "directing lighting artist":                            _ml.CrewType.ADDITIONAL,
    "best boy electric":                                    _ml.CrewType.ADDITIONAL,
    "lighting artist":                                      _ml.CrewType.ADDITIONAL,
    "o.b. lighting":                                        _ml.CrewType.ADDITIONAL,
    "additional lighting technician":                       _ml.CrewType.ADDITIONAL,
    "standby rigger":                                       _ml.CrewType.ADDITIONAL,
    "assistant electrician":                                _ml.CrewType.ADDITIONAL,

    # Department: Actors.
    "stunt double":                                         _ml.CrewType.STUNTCAST,
    "actor":                                                _ml.CrewType.CAST,
    "cameo":                                                _ml.CrewType.CAST,
    "special guest":                                        _ml.CrewType.CAST,
    "voice":                                                _ml.CrewType.CAST,

    # Department: Crew.
    "special effects":                                      _ml.CrewType.ADDITIONAL,
    "production artist":                                    _ml.CrewType.ADDITIONAL,
    "sequence supervisor":                                  _ml.CrewType.ADDITIONAL,
    "photoscience manager":                                 _ml.CrewType.ADDITIONAL,
    "post-production manager":                              _ml.CrewType.ADDITIONAL,
    "video assist operator":                                _ml.CrewType.ADDITIONAL,
    "series publicist":                                     _ml.CrewType.ADDITIONAL,
    "technical advisor":                                    _ml.CrewType.ADDITIONAL,
    "temp sound editor":                                    _ml.CrewType.ADDITIONAL,
    "motion capture artist":                                _ml.CrewType.ADDITIONAL,
    "utility stunts":                                       _ml.CrewType.ADDITIONAL,
    "score engineer":                                       _ml.CrewType.ADDITIONAL,
    "associate choreographer":                              _ml.CrewType.ADDITIONAL,
    "additional music":                                     _ml.CrewType.ADDITIONAL,
    "assistant vehicles coordinator":                       _ml.CrewType.ADDITIONAL,
    "clearances consultant":                                _ml.CrewType.ADDITIONAL,
    "generator operator":                                   _ml.CrewType.ADDITIONAL,
    "military consultant":                                  _ml.CrewType.ADDITIONAL,
    "playback coordinator":                                 _ml.CrewType.ADDITIONAL,
    "vehicles coordinator":                                 _ml.CrewType.ADDITIONAL,
    "weapons wrangler":                                     _ml.CrewType.ADDITIONAL,
    "stunts":                                               _ml.CrewType.STUNTCAST,
    "special effects coordinator":                          _ml.CrewType.ADDITIONAL,
    "software team lead":                                   _ml.CrewType.ADDITIONAL,
    "mix technician":                                       _ml.CrewType.ADDITIONAL,
    "tattooist":                                            _ml.CrewType.ADDITIONAL,
    "mixing engineer":                                      _ml.CrewType.ADDITIONAL,
    "craft service":                                        _ml.CrewType.ADDITIONAL,
    "animatronic and prosthetic effects":                   _ml.CrewType.ADDITIONAL,
    "dramaturgy":                                           _ml.CrewType.ADDITIONAL,
    "lighting camera":                                      _ml.CrewType.ADDITIONAL,
    "carpenter":                                            _ml.CrewType.ADDITIONAL,
    "editorial staff":                                      _ml.CrewType.ADDITIONAL,
    "armory coordinator":                                   _ml.CrewType.ADDITIONAL,
    "assistant picture car coordinator":                    _ml.CrewType.ADDITIONAL,
    "health and safety":                                    _ml.CrewType.ADDITIONAL,
    "interactive manager":                                  _ml.CrewType.ADDITIONAL,
    "key special effects":                                  _ml.CrewType.ADDITIONAL,
    "scientific consultant":                                _ml.CrewType.ADDITIONAL,
    "security coordinator":                                 _ml.CrewType.ADDITIONAL,
    "special effects manager":                              _ml.CrewType.ADDITIONAL,
    "sponsorship director":                                 _ml.CrewType.ADDITIONAL,
    "transcriptions":                                       _ml.CrewType.ADDITIONAL,
    "post production supervisor":                           _ml.CrewType.ADDITIONAL,
    "stunt coordinator":                                    _ml.CrewType.ADDITIONAL,
    "stunts coordinator":                                   _ml.CrewType.ADDITIONAL,
    "projection":                                           _ml.CrewType.ADDITIONAL,
    "compositor":                                           _ml.CrewType.ADDITIONAL,
    "compositors":                                          _ml.CrewType.ADDITIONAL,
    "machinist":                                            _ml.CrewType.ADDITIONAL,
    "systems administrators & support":                     _ml.CrewType.ADDITIONAL,
    "prop maker":                                           _ml.CrewType.ADDITIONAL,
    "transportation co-captain":                            _ml.CrewType.ADDITIONAL,
    "sound design assistant":                               _ml.CrewType.ADDITIONAL,
    "script":                                               _ml.CrewType.WRITER,
    "armorer":                                              _ml.CrewType.ADDITIONAL,
    "dialect coach":                                        _ml.CrewType.ADDITIONAL,
    "cableman":                                             _ml.CrewType.ADDITIONAL,
    "transportation coordinator":                           _ml.CrewType.ADDITIONAL,
    "driver":                                               _ml.CrewType.ADDITIONAL,
    "second unit cinematographer":                          _ml.CrewType.ADDITIONAL,
    "quality control supervisor":                           _ml.CrewType.ADDITIONAL,
    "public relations":                                     _ml.CrewType.ADDITIONAL,
    "martial arts choreographer":                           _ml.CrewType.ADDITIONAL,
    "pyrotechnician":                                       _ml.CrewType.ADDITIONAL,
    "cinematography":                                       _ml.CrewType.ADDITIONAL,
    "visual effects editor":                                _ml.CrewType.ADDITIONAL,
    "animatronics designer":                                _ml.CrewType.ADDITIONAL,
    "digital effects producer":                             _ml.CrewType.ADDITIONAL,
    "clearances coordinator":                               _ml.CrewType.ADDITIONAL,
    "special effects best boy":                             _ml.CrewType.ADDITIONAL,
    "special effects technician":                           _ml.CrewType.ADDITIONAL,
    "intern":                                               _ml.CrewType.ADDITIONAL,
    "unit medic":                                           _ml.CrewType.ADDITIONAL,
    "choreographer":                                        _ml.CrewType.CHOREOGRAPHER,
    "department administrator":                             _ml.CrewType.ADDITIONAL,
    "picture car coordinator":                              _ml.CrewType.ADDITIONAL,
    "production intern":                                    _ml.CrewType.ADDITIONAL,
    "chef":                                                 _ml.CrewType.ADDITIONAL,
    "title graphics":                                       _ml.CrewType.ADDITIONAL,
    "telecine colorist":                                    _ml.CrewType.ADDITIONAL,
    "commissioning editor":                                 _ml.CrewType.ADDITIONAL,
    "drone operator":                                       _ml.CrewType.ADDITIONAL,
    "in memory of":                                         _ml.CrewType.ADDITIONAL,
    "presenter":                                            _ml.CrewType.ADDITIONAL,
    "digital supervisor":                                   _ml.CrewType.ADDITIONAL,
    "director of communications":                           _ml.CrewType.ADDITIONAL,
    "police consultant":                                    _ml.CrewType.ADDITIONAL,
    "set medic":                                            _ml.CrewType.ADDITIONAL,
    "production controller":                                _ml.CrewType.ADDITIONAL,
    "scenic artist":                                        _ml.CrewType.ADDITIONAL,
    "digital effects supervisor":                           _ml.CrewType.ADDITIONAL,
    "video game":                                           _ml.CrewType.ADDITIONAL,
    "animal wrangler":                                      _ml.CrewType.ADDITIONAL,
    "fight choreographer":                                  _ml.CrewType.ADDITIONAL,
    "acting double":                                        _ml.CrewType.CAST,
    "cast driver":                                          _ml.CrewType.ADDITIONAL,
    "production office assistant":                          _ml.CrewType.ADDITIONAL,
    "information systems manager":                          _ml.CrewType.ADDITIONAL,
    "sets & props supervisor":                              _ml.CrewType.ADDITIONAL,
    "stand in":                                             _ml.CrewType.CAST,
    "manager of operations":                                _ml.CrewType.ADDITIONAL,
    "steadycam":                                            _ml.CrewType.ADDITIONAL,
    "digital producer":                                     _ml.CrewType.ADDITIONAL,
    "makeup effects":                                       _ml.CrewType.ADDITIONAL,
    "poem":                                                 _ml.CrewType.ADDITIONAL,
    "child wrangler":                                       _ml.CrewType.ADDITIONAL,
    "special effects assistant":                            _ml.CrewType.ADDITIONAL,
    "sponsorship coordinator":                              _ml.CrewType.ADDITIONAL,
    "supervising armorer":                                  _ml.CrewType.ADDITIONAL,
    "second unit":                                          _ml.CrewType.ADDITIONAL,
    "visual effects design consultant":                     _ml.CrewType.ADDITIONAL,
    "cgi supervisor":                                       _ml.CrewType.ADDITIONAL,
    "graphic novel illustrator":                            _ml.CrewType.ADDITIONAL,
    "supervising technical director":                       _ml.CrewType.ADDITIONAL,
    "transportation captain":                               _ml.CrewType.ADDITIONAL,
    "post production consulting":                           _ml.CrewType.ADDITIONAL,
    "set production intern":                                _ml.CrewType.ADDITIONAL,
    "loader":                                               _ml.CrewType.ADDITIONAL,
    "legal services":                                       _ml.CrewType.ADDITIONAL,
    "executive music producer":                             _ml.CrewType.ADDITIONAL,
    "thanks":                                               _ml.CrewType.ADDITIONAL,
    "creator":                                              _ml.CrewType.ADDITIONAL,
    "marine coordinator":                                   _ml.CrewType.ADDITIONAL,
    "assistant chef":                                       _ml.CrewType.ADDITIONAL,
    "catering":                                             _ml.CrewType.ADDITIONAL,
    "chaperone":                                            _ml.CrewType.ADDITIONAL,
    "logistics coordinator":                                _ml.CrewType.ADDITIONAL,
    "master at arms":                                       _ml.CrewType.ADDITIONAL,
    "post production scripts":                              _ml.CrewType.ADDITIONAL,
    "receptionist":                                         _ml.CrewType.ADDITIONAL,
    "set runner":                                           _ml.CrewType.ADDITIONAL,
    "stunt driver":                                         _ml.CrewType.STUNTCAST,
    "second film editor":                                   _ml.CrewType.ADDITIONAL,
    "post production assistant":                            _ml.CrewType.ADDITIONAL,
    "sets & props artist":                                  _ml.CrewType.ADDITIONAL,
    "visual effects art director":                          _ml.CrewType.ADDITIONAL,
    "pilot":                                                _ml.CrewType.ADDITIONAL,
    "techno crane operator":                                _ml.CrewType.ADDITIONAL,
    "administrative assistant":                             _ml.CrewType.ADDITIONAL,
    "captain driver":                                       _ml.CrewType.ADDITIONAL,
    "head driver":                                          _ml.CrewType.ADDITIONAL,
    "actor's assistant":                                    _ml.CrewType.ADDITIONAL,
    "propmaker":                                            _ml.CrewType.ADDITIONAL,
    "creative consultant":                                  _ml.CrewType.ADDITIONAL,
    "aerial coordinator":                                   _ml.CrewType.ADDITIONAL,
    "key scenic artist":                                    _ml.CrewType.ADDITIONAL,
    "supervising animator":                                 _ml.CrewType.ADDITIONAL,
    "temp music editor":                                    _ml.CrewType.ADDITIONAL,
    "motion actor":                                         _ml.CrewType.CAST,
    "studio teacher":                                       _ml.CrewType.ADDITIONAL,
    "studio teachers":                                      _ml.CrewType.ADDITIONAL,
    "executive visual effects producer":                    _ml.CrewType.ADDITIONAL,
    "radio play":                                           _ml.CrewType.ADDITIONAL,
    "additional script supervisor":                         _ml.CrewType.ADDITIONAL,
    "assistant script":                                     _ml.CrewType.ADDITIONAL,
    "chaperone tutor":                                      _ml.CrewType.ADDITIONAL,
    "dialogue coach":                                       _ml.CrewType.ADDITIONAL,
    "software engineer":                                    _ml.CrewType.ADDITIONAL,
    "schedule coordinator":                                 _ml.CrewType.ADDITIONAL,
    "supervisor of production resources":                   _ml.CrewType.ADDITIONAL,
    "special sound effects":                                _ml.CrewType.ADDITIONAL,
    "translator":                                           _ml.CrewType.ADDITIONAL,
    "cg supervisor":                                        _ml.CrewType.ADDITIONAL,
    "executive in charge of finance":                       _ml.CrewType.ADDITIONAL,
    "technical supervisor":                                 _ml.CrewType.ADDITIONAL,
    "additional dialogue":                                  _ml.CrewType.ADDITIONAL,
    "catering head chef":                                   _ml.CrewType.ADDITIONAL,
    "film processor":                                       _ml.CrewType.ADDITIONAL,
    "floor runner":                                         _ml.CrewType.ADDITIONAL,
    "sequence lead":                                        _ml.CrewType.ADDITIONAL,
    "sequence leads":                                       _ml.CrewType.ADDITIONAL,
    "documentation & support":                              _ml.CrewType.ADDITIONAL,
    "sequence artist":                                      _ml.CrewType.ADDITIONAL,
    "unit publicist":                                       _ml.CrewType.ADDITIONAL,
    "set production assistant":                             _ml.CrewType.ADDITIONAL,
    "security":                                             _ml.CrewType.ADDITIONAL,
    "additional writing":                                   _ml.CrewType.ADDITIONAL,
    "series writer":                                        _ml.CrewType.WRITER,
    "treatment":                                            _ml.CrewType.ADDITIONAL,
    "animal coordinator":                                   _ml.CrewType.ADDITIONAL,
    "animatronics supervisor":                              _ml.CrewType.ADDITIONAL,
    "base camp operator":                                   _ml.CrewType.ADDITIONAL,
    "marine pilot":                                         _ml.CrewType.ADDITIONAL,
    "assistant craft service":                              _ml.CrewType.ADDITIONAL,
    "medical consultant":                                   _ml.CrewType.ADDITIONAL,
    "charge scenic artist":                                 _ml.CrewType.ADDITIONAL,
    "file footage":                                         _ml.CrewType.ADDITIONAL,
    "specialized driver":                                   _ml.CrewType.ADDITIONAL,
    "vehicles wrangler":                                    _ml.CrewType.ADDITIONAL,
    "weapons master":                                       _ml.CrewType.ADDITIONAL,

    # Department: Directing.
    "additional third assistant director":                  _ml.CrewType.ASSISTANT_DIRECTOR,
    "insert unit director":                                 _ml.CrewType.ADDITIONAL,
    "series director":                                      _ml.CrewType.ADDITIONAL,
    "insert unit first assistant director":                 _ml.CrewType.ADDITIONAL,
    "script coordinator":                                   _ml.CrewType.ADDITIONAL,
    "co-director":                                          _ml.CrewType.DIRECTOR,
    "director":                                             _ml.CrewType.DIRECTOR,
    "second unit director":                                 _ml.CrewType.ADDITIONAL,
    "assistant director trainee":                           _ml.CrewType.ADDITIONAL,
    "second unit first assistant director":                 _ml.CrewType.ADDITIONAL,
    "first assistant director (prep)":                      _ml.CrewType.ADDITIONAL,
    "second assistant director trainee":                    _ml.CrewType.ADDITIONAL,
    "first assistant director":                             _ml.CrewType.ASSISTANT_DIRECTOR,
    "special guest director":                               _ml.CrewType.ADDITIONAL,
    "second assistant director":                            _ml.CrewType.ASSISTANT_DIRECTOR,
    "field director":                                       _ml.CrewType.ADDITIONAL,
    "third assistant director":                             _ml.CrewType.ASSISTANT_DIRECTOR,
    "layout":                                               _ml.CrewType.ADDITIONAL,
    "stage director":                                       _ml.CrewType.ADDITIONAL,
    "script supervisor":                                    _ml.CrewType.ADDITIONAL,
    "assistant director":                                   _ml.CrewType.ASSISTANT_DIRECTOR,
    "continuity":                                           _ml.CrewType.ADDITIONAL,
    "action director":                                      _ml.CrewType.ADDITIONAL,
    "crowd assistant director":                             _ml.CrewType.ADDITIONAL,
    "first assistant director trainee":                     _ml.CrewType.ADDITIONAL,
    "second second assistant director":                     _ml.CrewType.ADDITIONAL,
    "additional second assistant director":                 _ml.CrewType.ASSISTANT_DIRECTOR,

    # Department: Writing.
    "dialogue":                                             _ml.CrewType.ADDITIONAL,
    "theatre play":                                         _ml.CrewType.ADDITIONAL,
    "screenplay":                                           _ml.CrewType.WRITER,
    "idea":                                                 _ml.CrewType.ADDITIONAL,
    "executive story editor":                               _ml.CrewType.ADDITIONAL,
    "writers' production":                                  _ml.CrewType.ADDITIONAL,
    "adaptation":                                           _ml.CrewType.ADDITIONAL,
    "scenario writer":                                      _ml.CrewType.ADDITIONAL,
    "comic book":                                           _ml.CrewType.ADDITIONAL,
    "author":                                               _ml.CrewType.ADDITIONAL,
    "script editor":                                        _ml.CrewType.ADDITIONAL,
    "story manager":                                        _ml.CrewType.ADDITIONAL,
    "story supervisor":                                     _ml.CrewType.ADDITIONAL,
    "writer":                                               _ml.CrewType.WRITER,
    "lyricist":                                             _ml.CrewType.ADDITIONAL,
    "original film writer":                                 _ml.CrewType.ADDITIONAL,
    "storyboard":                                           _ml.CrewType.ADDITIONAL,
    "musical":                                              _ml.CrewType.ADDITIONAL,
    "series composition":                                   _ml.CrewType.ADDITIONAL,
    "staff writer":                                         _ml.CrewType.ADDITIONAL,
    "novel":                                                _ml.CrewType.ADDITIONAL,
    "story artist":                                         _ml.CrewType.ADDITIONAL,
    "book":                                                 _ml.CrewType.ADDITIONAL,
    "opera":                                                _ml.CrewType.ADDITIONAL,
    "creative producer":                                    _ml.CrewType.ADDITIONAL,
    "characters":                                           _ml.CrewType.ADDITIONAL,
    "original story":                                       _ml.CrewType.ADDITIONAL,
    "screenstory":                                          _ml.CrewType.ADDITIONAL,
    "teleplay":                                             _ml.CrewType.ADDITIONAL,
    "co-writer":                                            _ml.CrewType.WRITER,
    "short story":                                          _ml.CrewType.ADDITIONAL,
    "script consultant":                                    _ml.CrewType.ADDITIONAL,
    "writers' assistant":                                   _ml.CrewType.ADDITIONAL,
    "story":                                                _ml.CrewType.ADDITIONAL,
    "story editor":                                         _ml.CrewType.ADDITIONAL,
    "original series creator":                              _ml.CrewType.ADDITIONAL,
    "junior story editor":                                  _ml.CrewType.ADDITIONAL,
    "senior story editor":                                  _ml.CrewType.ADDITIONAL,
    "story consultant":                                     _ml.CrewType.ADDITIONAL,
    "head of story":                                        _ml.CrewType.ADDITIONAL,
    "original concept":                                     _ml.CrewType.ADDITIONAL,
    "graphic novel":                                        _ml.CrewType.ADDITIONAL,
    "story coordinator":                                    _ml.CrewType.ADDITIONAL,
    "story developer":                                      _ml.CrewType.ADDITIONAL,

    # Department: Editing.
    "editor":                                               _ml.CrewType.EDITOR,
    "additional editorial assistant":                       _ml.CrewType.ADDITIONAL,
    "3d editor":                                            _ml.CrewType.ADDITIONAL,
    "colorist":                                             _ml.CrewType.ADDITIONAL,
    "first assistant picture editor":                       _ml.CrewType.ADDITIONAL,
    "senior colorist":                                      _ml.CrewType.ADDITIONAL,
    "editorial production assistant":                       _ml.CrewType.ADDITIONAL,
    "archival footage coordinator":                         _ml.CrewType.ADDITIONAL,
    "digital intermediate assistant":                       _ml.CrewType.ADDITIONAL,
    "epk editor":                                           _ml.CrewType.ADDITIONAL,
    "editorial coordinator":                                _ml.CrewType.ADDITIONAL,
    "assistant editor":                                     _ml.CrewType.ADDITIONAL,
    "co-editor":                                            _ml.CrewType.EDITOR,
    "additional colorist":                                  _ml.CrewType.ADDITIONAL,
    "digital intermediate colorist":                        _ml.CrewType.ADDITIONAL,
    "color assistant":                                      _ml.CrewType.ADDITIONAL,
    "dailies technician":                                   _ml.CrewType.ADDITIONAL,
    "supervising film editor":                              _ml.CrewType.ADDITIONAL,
    "digital colorist":                                     _ml.CrewType.ADDITIONAL,
    "digital intermediate":                                 _ml.CrewType.ADDITIONAL,
    "editorial consultant":                                 _ml.CrewType.ADDITIONAL,
    "project manager":                                      _ml.CrewType.ADDITIONAL,
    "3d digital colorist":                                  _ml.CrewType.ADDITIONAL,
    "digital intermediate producer":                        _ml.CrewType.ADDITIONAL,
    "first assistant editor":                               _ml.CrewType.ADDITIONAL,
    "color timer":                                          _ml.CrewType.ADDITIONAL,
    "negative cutter":                                      _ml.CrewType.ADDITIONAL,
    "additional editor":                                    _ml.CrewType.ADDITIONAL,
    "assistant picture editor":                             _ml.CrewType.ADDITIONAL,
    "supervising editor":                                   _ml.CrewType.ADDITIONAL,
    "editorial manager":                                    _ml.CrewType.ADDITIONAL,
    "atmos editor":                                         _ml.CrewType.ADDITIONAL,
    "digital intermediate data wrangler":                   _ml.CrewType.ADDITIONAL,
    "associate editor":                                     _ml.CrewType.ADDITIONAL,
    "color grading":                                        _ml.CrewType.ADDITIONAL,
    "lead editor":                                          _ml.CrewType.EDITOR,
    "editorial services":                                   _ml.CrewType.ADDITIONAL,
    "additional editing":                                   _ml.CrewType.ADDITIONAL,
    "archival footage research":                            _ml.CrewType.ADDITIONAL,
    "dailies manager":                                      _ml.CrewType.ADDITIONAL,
    "dailies operator":                                     _ml.CrewType.ADDITIONAL,
    "senior digital intermediate colorist":                 _ml.CrewType.ADDITIONAL,
    "digital color timer":                                  _ml.CrewType.ADDITIONAL,
    "digital intermediate editor":                          _ml.CrewType.ADDITIONAL,
    "digital conform editor":                               _ml.CrewType.ADDITIONAL,
    "online editor":                                        _ml.CrewType.ADDITIONAL,
    "consulting editor":                                    _ml.CrewType.ADDITIONAL,
    "stereoscopic editor":                                  _ml.CrewType.ADDITIONAL,

    # Department: Sound.
    "sound director":                                       _ml.CrewType.ADDITIONAL,
    "sound recordist":                                      _ml.CrewType.ADDITIONAL,
    "additional sound re-recordist":                        _ml.CrewType.ADDITIONAL,
    "foley editor":                                         _ml.CrewType.ADDITIONAL,
    "utility sound":                                        _ml.CrewType.ADDITIONAL,
    "joint adr mixer":                                      _ml.CrewType.ADDITIONAL,
    "sound re-recording assistant":                         _ml.CrewType.ADDITIONAL,
    "vocals":                                               _ml.CrewType.ADDITIONAL,
    "sound engineer":                                       _ml.CrewType.ADDITIONAL,
    "assistant sound engineer":                             _ml.CrewType.ADDITIONAL,
    "original music composer":                              _ml.CrewType.COMPOSER,
    "dolby consultant":                                     _ml.CrewType.ADDITIONAL,
    "orchestrator":                                         _ml.CrewType.ADDITIONAL,
    "boom operator":                                        _ml.CrewType.ADDITIONAL,
    "sound mixer":                                          _ml.CrewType.ADDITIONAL,
    "dialogue editor":                                      _ml.CrewType.ADDITIONAL,
    "additional music supervisor":                          _ml.CrewType.ADDITIONAL,
    "music programmer":                                     _ml.CrewType.ADDITIONAL,
    "playback singer":                                      _ml.CrewType.ADDITIONAL,
    "supervising music editor":                             _ml.CrewType.ADDITIONAL,
    "theme song performance":                               _ml.CrewType.ADDITIONAL,
    "assistant music supervisor":                           _ml.CrewType.ADDITIONAL,
    "music score producer":                                 _ml.CrewType.ADDITIONAL,
    "adr post producer":                                    _ml.CrewType.ADDITIONAL,
    "sound designer":                                       _ml.CrewType.ADDITIONAL,
    "songs":                                                _ml.CrewType.ADDITIONAL,
    "foley mixer":                                          _ml.CrewType.ADDITIONAL,
    "location sound recordist":                             _ml.CrewType.ADDITIONAL,
    "sound editor":                                         _ml.CrewType.ADDITIONAL,
    "adr & dubbing":                                        _ml.CrewType.ADDITIONAL,
    "adr editor":                                           _ml.CrewType.ADDITIONAL,
    "digital foley artist":                                 _ml.CrewType.ADDITIONAL,
    "keyboard programmer":                                  _ml.CrewType.ADDITIONAL,
    "music sound design and processing":                    _ml.CrewType.ADDITIONAL,
    "music supervisor":                                     _ml.CrewType.ADDITIONAL,
    "sound":                                                _ml.CrewType.ADDITIONAL,
    "adr supervisor":                                       _ml.CrewType.ADDITIONAL,
    "apprentice sound editor":                              _ml.CrewType.ADDITIONAL,
    "assistant sound editor":                               _ml.CrewType.ADDITIONAL,
    "sound effects":                                        _ml.CrewType.ADDITIONAL,
    "o.b. sound":                                           _ml.CrewType.ADDITIONAL,
    "additional soundtrack":                                _ml.CrewType.ADDITIONAL,
    "sound re-recording mixer":                             _ml.CrewType.ADDITIONAL,
    "main title theme composer":                            _ml.CrewType.COMPOSER,
    "supervising sound editor":                             _ml.CrewType.ADDITIONAL,
    "music":                                                _ml.CrewType.ADDITIONAL,
    "vocal coach":                                          _ml.CrewType.ADDITIONAL,
    "sound effects editor":                                 _ml.CrewType.ADDITIONAL,
    "first assistant sound editor":                         _ml.CrewType.ADDITIONAL,
    "music producer":                                       _ml.CrewType.ADDITIONAL,
    "sound post production coordinator":                    _ml.CrewType.ADDITIONAL,
    "foley":                                                _ml.CrewType.ADDITIONAL,
    "conductor":                                            _ml.CrewType.ADDITIONAL,
    "sound montage associate":                              _ml.CrewType.ADDITIONAL,
    "musician":                                             _ml.CrewType.ADDITIONAL,
    "adr engineer":                                         _ml.CrewType.ADDITIONAL,
    "location sound assistant":                             _ml.CrewType.ADDITIONAL,
    "sound mix technician":                                 _ml.CrewType.ADDITIONAL,
    "sound post supervisor":                                _ml.CrewType.ADDITIONAL,
    "production sound mixer":                               _ml.CrewType.ADDITIONAL,
    "supervising sound effects editor":                     _ml.CrewType.ADDITIONAL,
    "recording supervision":                                _ml.CrewType.ADDITIONAL,
    "music director":                                       _ml.CrewType.ADDITIONAL,
    "additional sound re-recording mixer":                  _ml.CrewType.ADDITIONAL,
    "sound effects designer":                               _ml.CrewType.ADDITIONAL,
    "supervising adr editor":                               _ml.CrewType.ADDITIONAL,
    "supervising dialogue editor":                          _ml.CrewType.ADDITIONAL,
    "music editor":                                         _ml.CrewType.ADDITIONAL,
    "scoring mixer":                                        _ml.CrewType.ADDITIONAL,
    "adr recordist":                                        _ml.CrewType.ADDITIONAL,
    "audio post coordinator":                               _ml.CrewType.ADDITIONAL,
    "foley supervisor":                                     _ml.CrewType.ADDITIONAL,
    "location sound mixer":                                 _ml.CrewType.ADDITIONAL,
    "music arranger":                                       _ml.CrewType.ADDITIONAL,
    "music consultant":                                     _ml.CrewType.ADDITIONAL,
    "sound supervisor":                                     _ml.CrewType.ADDITIONAL,
    "foley recordist":                                      _ml.CrewType.ADDITIONAL,
    "second assistant sound":                               _ml.CrewType.ADDITIONAL,
    "sound assistant":                                      _ml.CrewType.ADDITIONAL,
    "additional production sound mixer":                    _ml.CrewType.ADDITIONAL,
    "adr mixer":                                            _ml.CrewType.ADDITIONAL,
    "adr recording engineer":                               _ml.CrewType.ADDITIONAL,
    "foley artist":                                         _ml.CrewType.ADDITIONAL,
    "music co-supervisor":                                  _ml.CrewType.ADDITIONAL,
    "music coordinator":                                    _ml.CrewType.ADDITIONAL,
    "adr coordinator":                                      _ml.CrewType.ADDITIONAL,
    "assistant dialogue editor":                            _ml.CrewType.ADDITIONAL,
    "assistant foley artist":                               _ml.CrewType.ADDITIONAL,
    "assistant sound designer":                             _ml.CrewType.ADDITIONAL,
    "foley recording engineer":                             _ml.CrewType.ADDITIONAL,
    "loop group coordinator":                               _ml.CrewType.ADDITIONAL,
    "music supervision assistant":                          _ml.CrewType.ADDITIONAL,
    "sound technical supervisor":                           _ml.CrewType.ADDITIONAL,

    # Department: Visual Effects.
    "animation manager":                                    _ml.CrewType.ADDITIONAL,
    "visual effects coordinator":                           _ml.CrewType.ADDITIONAL,
    "key animation":                                        _ml.CrewType.ADDITIONAL,
    "animation technical director":                         _ml.CrewType.ADDITIONAL,
    "compositing artist":                                   _ml.CrewType.ADDITIONAL,
    "compositing lead":                                     _ml.CrewType.ADDITIONAL,
    "matte painter":                                        _ml.CrewType.ADDITIONAL,
    "pre-visualization coordinator":                        _ml.CrewType.ADDITIONAL,
    "visual effects assistant editor":                      _ml.CrewType.ADDITIONAL,
    "special effects supervisor":                           _ml.CrewType.ADDITIONAL,
    "2d artist":                                            _ml.CrewType.ADDITIONAL,
    "3d artist":                                            _ml.CrewType.ADDITIONAL,
    "visual effects technical director":                    _ml.CrewType.ADDITIONAL,
    "cg artist":                                            _ml.CrewType.ADDITIONAL,
    "senior generalist":                                    _ml.CrewType.ADDITIONAL,
    "visual effects production assistant":                  _ml.CrewType.ADDITIONAL,
    "visual effects":                                       _ml.CrewType.ADDITIONAL,
    "creature design":                                      _ml.CrewType.ADDITIONAL,
    "cg painter":                                           _ml.CrewType.ADDITIONAL,
    "animation department coordinator":                     _ml.CrewType.ADDITIONAL,
    "battle motion coordinator":                            _ml.CrewType.ADDITIONAL,
    "i/o supervisor":                                       _ml.CrewType.ADDITIONAL,
    "pyrotechnic supervisor":                               _ml.CrewType.ADDITIONAL,
    "3d director":                                          _ml.CrewType.ADDITIONAL,
    "mechanical designer":                                  _ml.CrewType.ADDITIONAL,
    "animation":                                            _ml.CrewType.ADDITIONAL,
    "animation supervisor":                                 _ml.CrewType.ADDITIONAL,
    "animation fix coordinator":                            _ml.CrewType.ADDITIONAL,
    "digital compositor":                                   _ml.CrewType.ADDITIONAL,
    "digital compositors":                                  _ml.CrewType.ADDITIONAL,
    "additional effects development":                       _ml.CrewType.ADDITIONAL,
    "cg animator":                                          _ml.CrewType.ADDITIONAL,
    "matchmove supervisor":                                 _ml.CrewType.ADDITIONAL,
    "opening/ending animation":                             _ml.CrewType.ADDITIONAL,
    "roto supervisor":                                      _ml.CrewType.ADDITIONAL,
    "2d sequence supervisor":                               _ml.CrewType.ADDITIONAL,
    "lead creature designer":                               _ml.CrewType.ADDITIONAL,
    "pipeline technical director":                          _ml.CrewType.ADDITIONAL,
    "rotoscoping artist":                                   _ml.CrewType.ADDITIONAL,
    "visual effects compositor":                            _ml.CrewType.ADDITIONAL,
    "simulation & effects artist":                          _ml.CrewType.ADDITIONAL,
    "vfx supervisor":                                       _ml.CrewType.ADDITIONAL,
    "simulation & effects production assistant":            _ml.CrewType.ADDITIONAL,
    "3d coordinator":                                       _ml.CrewType.ADDITIONAL,
    "vfx director of photography":                          _ml.CrewType.ADDITIONAL,
    "vfx lighting artist":                                  _ml.CrewType.ADDITIONAL,
    "senior modeller":                                      _ml.CrewType.ADDITIONAL,
    "supervising animation director":                       _ml.CrewType.ADDITIONAL,
    "chief technician / stop-motion expert":                _ml.CrewType.ADDITIONAL,
    "color designer":                                       _ml.CrewType.ADDITIONAL,
    "3d supervisor":                                        _ml.CrewType.ADDITIONAL,
    "lead character designer":                              _ml.CrewType.ADDITIONAL,
    "additional visual effects":                            _ml.CrewType.ADDITIONAL,
    "compositing supervisor":                               _ml.CrewType.ADDITIONAL,
    "creature effects technical director":                  _ml.CrewType.ADDITIONAL,
    "senior visual effects supervisor":                     _ml.CrewType.ADDITIONAL,
    "smoke artist":                                         _ml.CrewType.ADDITIONAL,
    "modeling":                                             _ml.CrewType.ADDITIONAL,
    "fix animator":                                         _ml.CrewType.ADDITIONAL,
    "visual effects supervisor":                            _ml.CrewType.ADDITIONAL,
    "visual effects producer":                              _ml.CrewType.ADDITIONAL,
    "3d generalist":                                        _ml.CrewType.ADDITIONAL,
    "3d sequence supervisor":                               _ml.CrewType.ADDITIONAL,
    "character modelling supervisor":                       _ml.CrewType.ADDITIONAL,
    "director of previsualization":                         _ml.CrewType.ADDITIONAL,
    "visual effects production manager":                    _ml.CrewType.ADDITIONAL,
    "animation production assistant":                       _ml.CrewType.ADDITIONAL,
    "mechanical & creature designer":                       _ml.CrewType.ADDITIONAL,
    "cloth setup":                                          _ml.CrewType.ADDITIONAL,
    "vfx artist":                                           _ml.CrewType.ADDITIONAL,
    "vfx production coordinator":                           _ml.CrewType.ADDITIONAL,
    "3d tracking layout":                                   _ml.CrewType.ADDITIONAL,
    "cgi director":                                         _ml.CrewType.ADDITIONAL,
    "24 frame playback":                                    _ml.CrewType.ADDITIONAL,
    "visual effects designer":                              _ml.CrewType.ADDITIONAL,
    "layout supervisor":                                    _ml.CrewType.ADDITIONAL,
    "3d modeller":                                          _ml.CrewType.ADDITIONAL,
    "digital film recording":                               _ml.CrewType.ADDITIONAL,
    "visual effects camera":                                _ml.CrewType.ADDITIONAL,
    "animation director":                                   _ml.CrewType.ADDITIONAL,
    "vfx editor":                                           _ml.CrewType.ADDITIONAL,
    "3d animator":                                          _ml.CrewType.ADDITIONAL,
    "pre-visualization supervisor":                         _ml.CrewType.ADDITIONAL,
    "cyber scanning supervisor":                            _ml.CrewType.ADDITIONAL,
    "shading":                                              _ml.CrewType.ADDITIONAL,
    "visual development":                                   _ml.CrewType.ADDITIONAL,
    "cg engineer":                                          _ml.CrewType.ADDITIONAL,
    "2d supervisor":                                        _ml.CrewType.ADDITIONAL,
    "lead animator":                                        _ml.CrewType.ADDITIONAL,
    "imaging science":                                      _ml.CrewType.ADDITIONAL,
    "i/o manager":                                          _ml.CrewType.ADDITIONAL,
    "stereoscopic coordinator":                             _ml.CrewType.ADDITIONAL,
    "character designer":                                   _ml.CrewType.ADDITIONAL,
    "creature technical director":                          _ml.CrewType.ADDITIONAL,
    "visual effects lineup":                                _ml.CrewType.ADDITIONAL,
    "visual effects director":                              _ml.CrewType.ADDITIONAL,
    "animation coordinator":                                _ml.CrewType.ADDITIONAL,
    "generalist":                                           _ml.CrewType.ADDITIONAL,
    "photo retouching":                                     _ml.CrewType.ADDITIONAL,
    "senior animator":                                      _ml.CrewType.ADDITIONAL,
    "stereoscopic supervisor":                              _ml.CrewType.ADDITIONAL,
    "modelling supervisor":                                 _ml.CrewType.ADDITIONAL,
    "stereoscopic technical director":                      _ml.CrewType.ADDITIONAL,
    "effects supervisor":                                   _ml.CrewType.ADDITIONAL,
    "head of animation":                                    _ml.CrewType.ADDITIONAL,

    # Department: Camera.
    "camera intern":                                        _ml.CrewType.ADDITIONAL,
    "ultimate arm operator":                                _ml.CrewType.ADDITIONAL,
    "clapper loader":                                       _ml.CrewType.ADDITIONAL,
    "camera truck":                                         _ml.CrewType.ADDITIONAL,
    "phantom operator":                                     _ml.CrewType.ADDITIONAL,
    "second assistant \"c\" camera":                        _ml.CrewType.ADDITIONAL,
    "third assistant \"a\" camera":                         _ml.CrewType.ADDITIONAL,
    "third assistant \"c\" camera":                         _ml.CrewType.ADDITIONAL,
    "underwater epk photographer":                          _ml.CrewType.ADDITIONAL,
    "steadicam operator":                                   _ml.CrewType.ADDITIONAL,
    "dolly grip":                                           _ml.CrewType.ADDITIONAL,
    "key grip":                                             _ml.CrewType.ADDITIONAL,
    "additional director of photography":                   _ml.CrewType.ADDITIONAL,
    "best boy grip":                                        _ml.CrewType.ADDITIONAL,
    "bts videographer":                                     _ml.CrewType.ADDITIONAL,
    "epk producer":                                         _ml.CrewType.ADDITIONAL,
    "first assistant \"a\" camera":                         _ml.CrewType.ADDITIONAL,
    "videojournalist":                                      _ml.CrewType.ADDITIONAL,
    "helicopter camera":                                    _ml.CrewType.ADDITIONAL,
    "second assistant \"a\" camera":                        _ml.CrewType.ADDITIONAL,
    "camera trainee":                                       _ml.CrewType.ADDITIONAL,
    "first assistant \"b\" camera":                         _ml.CrewType.ADDITIONAL,
    "third assistant \"b\" camera":                         _ml.CrewType.ADDITIONAL,
    "drone pilot":                                          _ml.CrewType.ADDITIONAL,
    "head of layout":                                       _ml.CrewType.ADDITIONAL,
    "libra head technician":                                _ml.CrewType.ADDITIONAL,
    "second assistant \"b\" camera":                        _ml.CrewType.ADDITIONAL,
    "video report":                                         _ml.CrewType.ADDITIONAL,
    "camera car":                                           _ml.CrewType.ADDITIONAL,
    "camera department production assistant":               _ml.CrewType.ADDITIONAL,
    "drone cinematographer":                                _ml.CrewType.ADDITIONAL,
    "set photographer":                                     _ml.CrewType.ADDITIONAL,
    "third assistant camera":                               _ml.CrewType.ADDITIONAL,
    "director of photography":                              _ml.CrewType.CINEMATOGRAPHER,
    "aerial director of photography":                       _ml.CrewType.ADDITIONAL,
    "additional first assistant camera":                    _ml.CrewType.ADDITIONAL,
    "additional key grip":                                  _ml.CrewType.ADDITIONAL,
    "data wrangler":                                        _ml.CrewType.ADDITIONAL,
    "first assistant \"c\" camera":                         _ml.CrewType.ADDITIONAL,
    "additional still photographer":                        _ml.CrewType.ADDITIONAL,
    "russian arm operator":                                 _ml.CrewType.ADDITIONAL,
    "assistant camera":                                     _ml.CrewType.ADDITIONAL,
    "bts photographer":                                     _ml.CrewType.ADDITIONAL,
    "digital imaging technician":                           _ml.CrewType.ADDITIONAL,
    "epk director":                                         _ml.CrewType.ADDITIONAL,
    "jimmy jib operator":                                   _ml.CrewType.ADDITIONAL,
    "second assistant \"d\" camera":                        _ml.CrewType.ADDITIONAL,
    "underwater stills photographer":                       _ml.CrewType.ADDITIONAL,
    "camera supervisor":                                    _ml.CrewType.ADDITIONAL,
    "grip":                                                 _ml.CrewType.ADDITIONAL,
    "additional camera":                                    _ml.CrewType.ADDITIONAL,
    "first assistant camera":                               _ml.CrewType.ADDITIONAL,
    "second unit director of photography":                  _ml.CrewType.ADDITIONAL,
    "assistant grip":                                       _ml.CrewType.ADDITIONAL,
    "camera production assistant":                          _ml.CrewType.ADDITIONAL,
    "camera department manager":                            _ml.CrewType.ADDITIONAL,
    "aerial camera technician":                             _ml.CrewType.ADDITIONAL,
    "camera loader":                                        _ml.CrewType.ADDITIONAL,
    "\"b\" camera operator":                                _ml.CrewType.ADDITIONAL,
    "bts footage":                                          _ml.CrewType.ADDITIONAL,
    "camera operator":                                      _ml.CrewType.ADDITIONAL,
    "still photographer":                                   _ml.CrewType.ADDITIONAL,
    "camera technician":                                    _ml.CrewType.ADDITIONAL,
    "aerial camera":                                        _ml.CrewType.ADDITIONAL,
    "underwater director of photography":                   _ml.CrewType.ADDITIONAL,
    "\"c\" camera operator":                                _ml.CrewType.ADDITIONAL,
    "additional set photographer":                          _ml.CrewType.ADDITIONAL,
    "red technician":                                       _ml.CrewType.ADDITIONAL,
    "third assistant \"d\" camera":                         _ml.CrewType.ADDITIONAL,
    "focus puller":                                         _ml.CrewType.ADDITIONAL,
    "epk camera operator":                                  _ml.CrewType.ADDITIONAL,
    "\"a\" camera operator":                                _ml.CrewType.ADDITIONAL,
    "additional grip":                                      _ml.CrewType.ADDITIONAL,
    "additional second assistant camera":                   _ml.CrewType.ADDITIONAL,
    "additional underwater photography":                    _ml.CrewType.ADDITIONAL,
    "first assistant \"d\" camera":                         _ml.CrewType.ADDITIONAL,
    "second assistant camera":                              _ml.CrewType.ADDITIONAL,
    "underwater camera":                                    _ml.CrewType.ADDITIONAL,
    "additional photography":                               _ml.CrewType.ADDITIONAL,
    "second company grip":                                  _ml.CrewType.ADDITIONAL,
    "\"d\" camera operator":                                _ml.CrewType.ADDITIONAL,
    "first company grip":                                   _ml.CrewType.ADDITIONAL,

    # Department: Art.
    "production design":                                    _ml.CrewType.ADDITIONAL,
    "conceptual illustrator":                               _ml.CrewType.ADDITIONAL,
    "art designer":                                         _ml.CrewType.ADDITIONAL,
    "daily grip":                                           _ml.CrewType.ADDITIONAL,
    "property builder":                                     _ml.CrewType.ADDITIONAL,
    "set decoration":                                       _ml.CrewType.ADDITIONAL,
    "greensman":                                            _ml.CrewType.ADDITIONAL,
    "construction foreman":                                 _ml.CrewType.ADDITIONAL,
    "creative director":                                    _ml.CrewType.ADDITIONAL,
    "key construction grip":                                _ml.CrewType.ADDITIONAL,
    "special props":                                        _ml.CrewType.ADDITIONAL,
    "textile artist":                                       _ml.CrewType.ADDITIONAL,
    "settings":                                             _ml.CrewType.ADDITIONAL,
    "art department coordinator":                           _ml.CrewType.ADDITIONAL,
    "draughtsman":                                          _ml.CrewType.ADDITIONAL,
    "additional key construction grip":                     _ml.CrewType.ADDITIONAL,
    "runner art department":                                _ml.CrewType.ADDITIONAL,
    "second assistant art director":                        _ml.CrewType.ADDITIONAL,
    "art direction":                                        _ml.CrewType.ART_DIRECTOR,
    "assistant property master":                            _ml.CrewType.ADDITIONAL,
    "sign painter":                                         _ml.CrewType.ADDITIONAL,
    "set decoration buyer":                                 _ml.CrewType.ADDITIONAL,
    "prop designer":                                        _ml.CrewType.ADDITIONAL,
    "additional construction grip":                         _ml.CrewType.ADDITIONAL,
    "construction manager":                                 _ml.CrewType.ADDITIONAL,
    "helping hand":                                         _ml.CrewType.ADDITIONAL,
    "assistant director of photography":                    _ml.CrewType.ADDITIONAL,
    "assistant set decoration":                             _ml.CrewType.ADDITIONAL,
    "concept artist":                                       _ml.CrewType.ADDITIONAL,
    "dressing prop":                                        _ml.CrewType.ADDITIONAL,
    "petty cash buyer":                                     _ml.CrewType.ADDITIONAL,
    "on set key props":                                     _ml.CrewType.ADDITIONAL,
    "storyboard assistant":                                 _ml.CrewType.ADDITIONAL,
    "art department assistant":                             _ml.CrewType.ADDITIONAL,
    "property master":                                      _ml.CrewType.ADDITIONAL,
    "art department trainee":                               _ml.CrewType.ADDITIONAL,
    "assistant decorator":                                  _ml.CrewType.ADDITIONAL,
    "head carpenter":                                       _ml.CrewType.ADDITIONAL,
    "standby painter":                                      _ml.CrewType.ADDITIONAL,
    "lead set dresser":                                     _ml.CrewType.ADDITIONAL,
    "property graphic designer":                            _ml.CrewType.ADDITIONAL,
    "standby art director":                                 _ml.CrewType.ADDITIONAL,
    "co-art director":                                      _ml.CrewType.ART_DIRECTOR,
    "location scout":                                       _ml.CrewType.ADDITIONAL,
    "supervising art director":                             _ml.CrewType.ADDITIONAL,
    "storyboard designer":                                  _ml.CrewType.ADDITIONAL,
    "title designer":                                       _ml.CrewType.ADDITIONAL,
    "additional set dresser":                               _ml.CrewType.ADDITIONAL,
    "assistant set decoration buyer":                       _ml.CrewType.ADDITIONAL,
    "shop electric":                                        _ml.CrewType.ADDITIONAL,
    "interior designer":                                    _ml.CrewType.ADDITIONAL,
    "art department manager":                               _ml.CrewType.ADDITIONAL,
    "gun wrangler":                                         _ml.CrewType.ADDITIONAL,
    "construction coordinator":                             _ml.CrewType.ADDITIONAL,
    "set dresser":                                          _ml.CrewType.ADDITIONAL,
    "additional construction":                              _ml.CrewType.ADDITIONAL,
    "art direction intern":                                 _ml.CrewType.ADDITIONAL,
    "first assistant art direction":                        _ml.CrewType.ADDITIONAL,
    "graphic designer":                                     _ml.CrewType.ADDITIONAL,
    "on set computer graphics":                             _ml.CrewType.ADDITIONAL,
    "on set props":                                         _ml.CrewType.ADDITIONAL,
    "set dressing buyer":                                   _ml.CrewType.ADDITIONAL,
    "set painter":                                          _ml.CrewType.ADDITIONAL,
    "standby carpenter":                                    _ml.CrewType.ADDITIONAL,
    "storyboard artist":                                    _ml.CrewType.ADDITIONAL,
    "leadman":                                              _ml.CrewType.ADDITIONAL,
    "assistant set designer":                               _ml.CrewType.ADDITIONAL,
    "opening title sequence":                               _ml.CrewType.ADDITIONAL,
    "property buyer":                                       _ml.CrewType.ADDITIONAL,
    "assistant set propsman":                               _ml.CrewType.ADDITIONAL,
    "first assistant property master":                      _ml.CrewType.ADDITIONAL,
    "key set painter":                                      _ml.CrewType.ADDITIONAL,
    "set designer":                                         _ml.CrewType.ADDITIONAL,
    "conceptual design":                                    _ml.CrewType.ADDITIONAL,
    "background designer":                                  _ml.CrewType.ADDITIONAL,
    "production illustrator":                               _ml.CrewType.ADDITIONAL,
    "assistant set dresser":                                _ml.CrewType.ADDITIONAL,
    "additional storyboarding":                             _ml.CrewType.ADDITIONAL,
    "construction grip":                                    _ml.CrewType.ADDITIONAL,
    "props":                                                _ml.CrewType.ADDITIONAL,
    "set supervisor":                                       _ml.CrewType.ADDITIONAL,
    "standby property master":                              _ml.CrewType.ADDITIONAL,
    "web designer":                                         _ml.CrewType.ADDITIONAL,
    "assistant art director":                               _ml.CrewType.ADDITIONAL,
    "sculptor":                                             _ml.CrewType.ADDITIONAL,
    "digital storyboarding":                                _ml.CrewType.ADDITIONAL,
    "key carpenter":                                        _ml.CrewType.ADDITIONAL,
    "main title designer":                                  _ml.CrewType.ADDITIONAL,
    "paint coordinator":                                    _ml.CrewType.ADDITIONAL,
    "set propsman":                                         _ml.CrewType.ADDITIONAL,
    "set buyer":                                            _ml.CrewType.ADDITIONAL,
    "title illustration":                                   _ml.CrewType.ADDITIONAL,
    "lead painter":                                         _ml.CrewType.ADDITIONAL,
    "painter":                                              _ml.CrewType.ADDITIONAL,
    "set decorating coordinator":                           _ml.CrewType.ADDITIONAL,
    "construction buyer":                                   _ml.CrewType.ADDITIONAL,
    "decorator":                                            _ml.CrewType.ADDITIONAL,
    "head decorator":                                       _ml.CrewType.ADDITIONAL,
    "head greensman":                                       _ml.CrewType.ADDITIONAL,
    "original series design":                               _ml.CrewType.ADDITIONAL,
    "assistant production design":                          _ml.CrewType.ADDITIONAL,
    "swing":                                                _ml.CrewType.ADDITIONAL,
    "head designer":                                        _ml.CrewType.ADDITIONAL,
    "supervising carpenter":                                _ml.CrewType.ADDITIONAL,
}
