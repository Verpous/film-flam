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
import warnings
import typing

from . import _reg
from . import _fetch
from . import _exc
from . import _mlf
from . import _ml
from . import _dbg
from . import utils

_UID_FAMILY = 'letterboxd'
_PARAM_MAX = 'max'

# Letterboxd has an official API but they're currently only handing out API keys on special request and they won't approve it for a personal project.
# Letterboxd doesn't have a way to export a list to CSV, unless that list is your list,
# and then they let you actually export your entire profile: all your lists, your watchlist, your watched list, your reviewed list, everything.

@dataclasses.dataclass
class _MovieBasicInfo:
    slug:               str
    title:              str

# The only unofficial API I can find is letterboxdpy, so we'll be using that.
# They have a shit documentation but here it is: https://github.com/nmcassa/letterboxdpy/tree/main/docs.
@_reg._register_builtin
class LetterboxdpyFetcher(_fetch.Fetcher, list_type='letterboxd-user-list', uid_family=_UID_FAMILY):
    """LETTERBOXD_USER_LIST
        
    Takes a Letterboxd user and list name in the form ``<username>/<list_slug>`` as an input, and downloads the list using `letterboxdpy <https://github.com/nmcassa/letterboxdpy>`__.

    List slugs are just the list name as it appears in the list URL. Just open it in the browser, and the URL should look like this: https://letterboxd.com/verpous/list/movies-ive-watched/.
    The ``<username>/<list_slug>`` in this example is "verpous/movies-ive-watched".

    A few special lists are also supported:
    
        * ``<username>/films`` - the user's watched films
        * ``<username>/likes`` - the user's liked films
        * ``<username>/reviews`` - the user's reviewed films
        * ``<username>/watchlist`` - the user's watchlist

    Note that Letterboxd provides us a lot of information about movies, but not so much about people. So this fetcher has a blindspot there.
    """
    def _fetch_into_file(self, movie_list_file: _mlf.MovieListFile) -> None:
        # Expensive import so do it lazily.
        from letterboxdpy.user import User # type: ignore
        from letterboxdpy.core.exceptions import AccessDeniedError, ResourceNotFoundError # type: ignore

        _dbg.logger.info(f"Going to download Letterboxd list: {self.concrete_listdef.address}")

        # For debugging, support limiting to only a few movies fetched.
        try:
            max_movies = int(self.get_param(_PARAM_MAX))
        except _exc.InputError:
            max_movies = None
        except ValueError as e:
            raise _exc.InputError(f"Invalid param '{_PARAM_MAX}': {e}") from e

        try:
            username, list_slug = self.concrete_listdef.address.split('/', maxsplit=1)
        except ValueError as e:
            raise _exc.InputError(f"Invalid LISTDEF: '{self.concrete_listdef}': address must have the form '<username>/<list-slug>'.") from e

        # NOTE: letterboxdpy has a way to authenticate, and maybe give us access to private lists.
        # But it errors out for me, doesn't work at all. So we won't support it.
        try:
            # Pretty much everything may sometimes fail with AccessDeniedError so we employ retries all over the place.
            user = _do_with_retries(lambda: User(username))
        except ResourceNotFoundError as e:
            raise _exc.InputError(f"Invalid LISTDEF: '{self.concrete_listdef}': user '{username}' does not exist.") from e

        # We acquire these lists in all cases because they contains some information we'll always want to incorporate, like the user rating and watch date.
        # NOTE: works even when the user has no watched films. For future reference, I found an empty user to test that with: https://letterboxd.com/bbbbbbbbbbbbbbb/.
        watched_films = _do_with_retries(user.get_films)

        # NOTE: works even when the user has no reviewed films (because I opened an issue and the letterboxdpy dev fixed it ^_^).
        reviewed_films = _do_with_retries(user.get_reviews)

        # {'entries': {'1309696594': {'name': 'Gangster Squad', 'slug': 'gangster-squad', 'id': None, 'release': 2013, 'runtime': None, 'actions': {'rewatched': False, 'rating': None, 'liked': False, 'reviewed': False}, 'date': '2026-05-09T00:00:00.000000Z', 'page': {'url': 'https://letterboxd.com/verpous/films/diary/page/1/', 'no': 1}}
        # We need to catch warnings here because this may warn "Runtime data is missing for some entries", which is harmless.
        # NOTE: I wanted to capture the warnings and redirect them to the logger but python makes that really difficult.
        with warnings.catch_warnings(action='ignore'):
            # NOTE: works even when the user has no diary entries.
            diary = _do_with_retries(user.get_diary)

        _dbg.logger.info(f"User '{username}' has {len(watched_films['movies'])} watched films, {len(reviewed_films['reviews'])} reviews, {len(diary['entries'])} diary entries")

        # NOTE: I wanted to also have a 'reviews' option, or at least fetch the review information to add as the MLFMovie.note, but User.get_reviews doesn't work.
        match list_slug:
            case 'films':
                # {'movies': {'project-hail-mary': {'slug': 'project-hail-mary', 'name': 'Project Hail Mary', 'year': 2026, 'url': 'https://letterboxd.com/film/project-hail-mary/', 'id': '611288', 'rating': None, 'liked': False}
                movie_basic_infos = [
                    _MovieBasicInfo(
                        slug = m['slug'],
                        title = m['name'],
                    )
                    for m in watched_films['movies'].values()
                ]
            case 'likes':
                # NOTE: I thought maybe instead of a 'likes' list, you should just be expected to `flam find movies -is-liked true`.
                # But it looks like letterboxd doesn't enforce that if a movie is liked it has to also be watched, so there's an argument for keeping this.
                
                # {'movies': {'spider-man-into-the-spider-verse': {'slug': 'spider-man-into-the-spider-verse', 'name': 'Spider-Man: Into the Spider-Verse', 'year': 2018, 'url': 'https://letterboxd.com/film/spider-man-into-the-spider-verse/', 'id': '251943', 'rating': 4.5, 'liked': True}
                # NOTE: works even when the user has no liked films.
                liked_films = _do_with_retries(user.get_liked_films)
                movie_basic_infos = [
                    _MovieBasicInfo(
                        slug = m['slug'],
                        title = m['name'],
                    )
                    for m in liked_films['movies'].values()
                ]
            case 'reviews':
                # {'reviews': {'186434167': {'movie': {'name': 'V for Vendetta', 'slug': 'v-for-vendetta', 'id': '51400', 'release': 2005, 'link': 'https://letterboxd.com/film/v-for-vendetta/'}, 'type': 'Watched', 'no': 0, 'link': 'https://letterboxd.com/verpous/film/v-for-vendetta/', 'rating': None, 'review': {'content': 'remember remember', 'spoiler': False}, 'date': '2020-10-12T00:00:00.000000Z', 'page': 1}
                # NOTE: the same film can have multiple reviews.
                movie_basic_infos = [
                    _MovieBasicInfo(
                        slug = m['movie']['slug'],
                        title = m['movie']['name'],
                    )
                    for m in reviewed_films['reviews'].values()
                ]
            case 'watchlist':
                # {'217531': {'slug': 'anomalisa', 'name': 'Anomalisa', 'year': 2015, 'url': 'https://letterboxd.com/film/anomalisa/', 'page': 1, 'no': 56}
                try:
                    # NOTE: works even if the user hasn't watchlisted anything.
                    watchlist = _do_with_retries(user.get_watchlist_movies)
                except AccessDeniedError as e:
                    raise _exc.InputError(f"Failed to fetch the Letterboxd watchlist for user {username}. It's probably set to private.") from e

                # NOTE: don't be mislead by m['no'] - it's not a list_index, it depends on the page too. Not worth the hassle of computing the list_index.
                movie_basic_infos = [
                    _MovieBasicInfo(
                        slug = m['slug'],
                        title = m['name'],
                    )
                    for m in watchlist.values()
                ]
            case _:
                # {'45944': {'slug': 'escape-from-alcatraz', 'name': 'Escape from Alcatraz', 'year': 1979, 'url': 'https://letterboxd.com/film/escape-from-alcatraz/'}
                try:
                    user_list = _do_with_retries(user.get_list(list_slug).get_movies)
                except ResourceNotFoundError as e:
                    raise _exc.InputError(f"Invalid LISTDEF: '{self.concrete_listdef}': user '{username}' has no such list '{list_slug}'.") from e

                movie_basic_infos = [
                    _MovieBasicInfo(
                        slug = m['slug'],
                        title = m['name'],
                    )
                    for m in user_list.values()
                ]

        _dbg.logger.info(f"MLF has {len(movie_list_file.movies_by_uid)} movies from prior fetch")
        
        # Movies have integer uids but they're a little bit confusing and not very useful. Slugs will serve as our uids.
        # It is a bit unforunate though as slugs can run rather long...
        uids = {m.slug for m in movie_basic_infos}
        movie_list_file.movies_by_uid = {uid: m for uid, m in movie_list_file.movies_by_uid.items() if uid in uids}
        
        _dbg.logger.info(f"MLF has {len(movie_list_file.movies_by_uid)} movies after omitting ones no longer in the list")

        # Only fetch movies not already in the list, and also if the same movie appears multiple times in the list, fetch it only once.
        # Multiple appearances of the same movie are not supported.
        movies_to_fetch = list(utils.stable_dedup(
            (m for m in movie_basic_infos if m.slug not in movie_list_file.movies_by_uid),
            key=lambda m: m.slug
        ))

        _dbg.logger.info(f"There are {len(movies_to_fetch)} new movies to fetch")

        if max_movies is not None:
            _dbg.logger.info(f"Limiting fetch to a maximum of {max_movies} movies.")
            movies_to_fetch = movies_to_fetch[:max_movies]

        try:
            with utils.ProgressBar(movies_to_fetch,
                    desc='Downloading',
                    keyfunc=lambda m: m.title) as bar:
                for i, movie_basic_info in enumerate(bar):
                    self._fetch_movie(movie_basic_info, watched_films, reviewed_films, diary, movie_list_file)

                    # Fetcher works fast enough that checkpoint after each movie will slow it down.
                    if i % 10 == 0:
                        self._checkpoint(movie_list_file)
        # If we get a KeyboardInterrupt, gracefully end the fetching early.
        # NOTE: Letterboxdpy actually creates an error popup and doesn't propagate the interrupt when the user Ctrl+C's, so this doesn't really work.
        # It's horrible, and I've tried opening an issue and investigating it a bunch, but it's too much: https://github.com/nmcassa/letterboxdpy/issues/173.
        except KeyboardInterrupt as e:
            raise _exc.FetchInterrupt(f"{type(e).__name__}: {e}") from e
        
        _dbg.logger.info("Done fetching movies")

    def _fetch_movie(self, movie_basic_info: _MovieBasicInfo, watched_films: dict, reviewed_films: dict, diary: dict, mlf: _mlf.MovieListFile) -> None:
        from letterboxdpy.movie import Movie # type: ignore

        _dbg.logger.info(f"Fetching movie: {movie_basic_info}")
        lbox_movie = _do_with_retries(lambda: Movie(movie_basic_info.slug))
        lbox_watched_movie = watched_films['movies'].get(movie_basic_info.slug, None)
        lbox_reviews = [r for r in reviewed_films['reviews'].values() if r['movie']['slug'] == movie_basic_info.slug]

        # NOTE: Letterboxd's diarykeeping is crap and most of the times diary entries aren't created, but this is the best we've got.
        lbox_diary_movie = [d for d in diary['entries'].values() if d['slug'] == movie_basic_info.slug]

        mlf_crew = {
            crew_type: _mlf.MLFCrew(crew_type=crew_type, roles_by_uid={})
            for crew_type in _ml.CrewType.iterate_except_any()
        }

        # {'director': [{'name': 'Joel Coen', 'slug': 'joel-coen', 'url': 'https://letterboxd.com/director/joel-coen/'}]
        # NOTE: There's no need to _do_with_retries every lbox_movie.get_X() call because those are all already fetched when we requested the movie (I checked).
        for lbox_crew_type, lbox_crew in lbox_movie.get_crew().items():
            crew_type = self.crew_type_lbox2flam(lbox_crew_type)

            for lbox_role in lbox_crew:
                # There's no uid we can use except the slug, which unfortunately may run long..
                # NOTE: Letterboxd does assign different slugs to different people with the same name (e.g. matt-smith-2, matt-smith-8).
                # I *think* they also guarantee someone will keep their slug across crew types.
                person_uid = lbox_role['slug']

                # ADDITIONAL can stand in for multiple crew types so the same person can appear multiple times.
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

                    # Might overwrite an already existing person.
                    # NOTE: Letterboxdpy is really slim on people information. If it hurts, we might be able to fill it in with tmdb..
                    mlf.people_by_uid[person_uid] = _mlf.MLFPerson(
                        uid                 = person_uid,
                        name                = lbox_role['name'],
                        gender              = None,
                        birthday            = None,
                        deathday            = None,
                        death_reason        = None,
                        height_cm           = None,
                        countries           = [],
                    )
                else:
                    assert crew_type == _ml.CrewType.ADDITIONAL
                
                if crew_type == _ml.CrewType.ADDITIONAL:
                    mlf_crew[crew_type].roles_by_uid[person_uid].jobs.append(lbox_crew_type)

        # [{'name': 'Jeff Bridges', 'role_name': 'The Dude', 'slug': 'jeff-bridges', 'url': 'https://letterboxd.com/actor/jeff-bridges/'}
        for castmember in lbox_movie.get_cast():
            person_uid = castmember['slug']

            # I verified if the same actor played multiple characters, they still only appear once.
            assert person_uid not in mlf_crew[_ml.CrewType.CAST].roles_by_uid

            # Multiple characters are separated by ' / '. We could split it, but I think it's risky and not worth it.
            characters = [castmember['role_name']] if castmember['role_name'] is not None else []

            mlf_crew[_ml.CrewType.CAST].roles_by_uid[person_uid] = _mlf.MLFRole(
                person_uid              = person_uid,
                is_star                 = None,
                episodes_num            = None,
                oscar_noms              = [],
                oscar_wins              = [],
                characters              = characters,
                jobs                    = [],
            )

            # Might overwrite an already existing person.
            mlf.people_by_uid[person_uid] = _mlf.MLFPerson(
                uid                     = person_uid,
                name                    = castmember['name'],
                gender                  = None,
                birthday                = None,
                deathday                = None,
                death_reason            = None,
                height_cm               = None,
                countries               = [],
            )

        # {'type': 'studio', 'name': 'PolyGram Filmed Entertainment', 'slug': 'polygram-filmed-entertainment', 'url': 'https://letterboxd.com/studio/polygram-filmed-entertainment/'}
        # Contains more than just 'studio' information. It also has languages, countries, etc.
        details = lbox_movie.get_details()
        
        # {'members': 265822, 'fans': 605, 'likes': 57541, 'reviews': 24378, 'lists': 35852}
        watchers = lbox_movie.get_watchers_stats()

        # [{'type': 'genre', 'name': 'Comedy', 'slug': 'comedy', 'url': 'https://letterboxd.com/films/genre/comedy/'}
        # Also contains some other types we don't care about like 'mini-theme'.
        genres = lbox_movie.get_genres()

        per_src_data = _mlf.MLFMoviePerSourceData(
            canon_listdef       = mlf.abstract_listdef,
            list_index          = None,
            list_note           = None,
            listing_date        = None,
        )

        mlf_movie = _mlf.MLFMovie(
            uid                 = movie_basic_info.slug,
            per_src_data        = [per_src_data],
            media_type          = 'movie',
            title               = lbox_movie.get_title(),
            original_title      = lbox_movie.get_original_title(),
            tagline             = lbox_movie.get_tagline(),
            synopsis            = lbox_movie.get_description(),
            url                 = lbox_movie.get_url(),
            runtime_minutes     = lbox_movie.get_runtime(),
            metascore_votes     = None,
            metascore           = None,
            votes               = None,
            rating              = lbox_movie.get_rating(),
            my_rating           = lbox_watched_movie['rating'] if lbox_watched_movie is not None else None,
            likes               = watchers['likes'],
            is_liked            = lbox_watched_movie['liked'] if lbox_watched_movie is not None else None,
            budget_usd          = None,
            revenue_usd         = None,
            content_rating      = None,
            release_date        = datetime.date(lbox_movie.get_year(), 1, 1),
            watch_dates         = [datetime.datetime.fromisoformat(d['date']).date() for d in lbox_diary_movie],
            my_notes            = [r['review']['content'] for r in lbox_reviews],
            episodes_num        = None,
            seasons_num         = None,
            end_date            = None,
            genres              = [g['name'] for g in genres if g['type'] == 'genre'],
            studios             = [d['name'] for d in details if d['type'] == 'studio'],
            languages           = [d['name'] for d in details if d['type'] == 'language'],
            countries           = [d['name'] for d in details if d['type'] == 'country'],
            crew                = mlf_crew,
        )

        mlf.movies_by_uid[mlf_movie.uid] = mlf_movie

    @classmethod
    def crew_type_lbox2flam(cls, lbox_crew_type: str) -> _ml.CrewType:
        # Performance doesn't matter here, and we won't turn this into a dictionary.
        match lbox_crew_type:
            case 'director':                    return _ml.CrewType.DIRECTOR
            case 'co_director':                 return _ml.CrewType.ADDITIONAL
            case 'additional_directing':        return _ml.CrewType.ADDITIONAL
            case 'producer':                    return _ml.CrewType.PRODUCER
            case 'writer':                      return _ml.CrewType.WRITER
            case 'original_writer':             return _ml.CrewType.ADDITIONAL
            case 'story':                       return _ml.CrewType.ADDITIONAL
            case 'casting':                     return _ml.CrewType.CASTING_DIRECTOR
            case 'editor':                      return _ml.CrewType.EDITOR
            case 'cinematography':              return _ml.CrewType.CINEMATOGRAPHER
            case 'assistant_director':          return _ml.CrewType.ASSISTANT_DIRECTOR
            case 'executive_producer':          return _ml.CrewType.EXECUTIVE_PRODUCER
            case 'lighting':                    return _ml.CrewType.ADDITIONAL
            case 'camera_operator':             return _ml.CrewType.ADDITIONAL
            case 'production_design':           return _ml.CrewType.ADDITIONAL
            case 'set_decoration':              return _ml.CrewType.ADDITIONAL
            case 'special_effects':             return _ml.CrewType.ADDITIONAL
            case 'composer':                    return _ml.CrewType.COMPOSER
            case 'songs':                       return _ml.CrewType.ADDITIONAL
            
            # NOTE: If sound is worthy of an oscar, it's surely worthy of its own crew type. But 'sound' is too broad: there are sound engineers, sound mixers, sound editors..
            # I'll need another API with support for sound crew to understand how to categorize sound people.
            case 'sound':                       return _ml.CrewType.ADDITIONAL
            case 'makeup':                      return _ml.CrewType.ADDITIONAL
            case 'additional_photography':      return _ml.CrewType.ADDITIONAL
            case 'art_direction':               return _ml.CrewType.ART_DIRECTOR
            case 'visual_effects':              return _ml.CrewType.ADDITIONAL
            case 'title_design':                return _ml.CrewType.ADDITIONAL
            case 'stunts':                      return _ml.CrewType.STUNTCAST
            case 'choreography':                return _ml.CrewType.CHOREOGRAPHER
            case 'costume_design':              return _ml.CrewType.ADDITIONAL
            case 'hairstyling':                 return _ml.CrewType.ADDITIONAL
            case _:
                raise RuntimeError(f'Unexpected {lbox_crew_type=}.')

# The benefit of this wrapper is we get the defaults that we want here locally.
def _do_with_retries[T](action: typing.Callable[[], T], num_retries: int = 3, sleep_between_retries: float = 1.0) -> T:
    return utils.do_with_retries(action, num_retries, sleep_between_retries)
