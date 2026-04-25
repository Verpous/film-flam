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

import os
import csv
import imdb # type: ignore
import typing
import dataclasses
import datetime
import multiprocessing
import queue
import time
import webbrowser
import abc
import atexit
import enum
import sys

from . import _reg
from . import _fetch
from . import _exc
from . import _mlf
from . import _ml
from . import _ldef
from . import _dbg
from . import utils

_UID_FAMILY = 'imdb'
_REQUEST_QUIT = 'quit'

#region Fetching

@dataclasses.dataclass
class _CsvRow:
    # Order of the fields *must* match up with what is actually served by IMDb.
    list_index:         str
    uid:                str
    listing_date:       str
    modified:           str
    note:               str
    title:              str
    original_title:     str
    url:                str
    _type:              str
    rating:             str
    runtime_minutes:    str
    year:               str
    genres:             str
    votes:              str
    release_date:       str
    directors:          str

    # These have defaults because they only appear in CSVs of lists made by the logged in user.
    my_rating:          None | str = None
    my_rating_date:     None | str = None

    # https://youtu.be/2xptOSaBDhg?si=Hmj2GDmWrkLUUPjx
    def mlf_universal_fields(self) -> dict[str, typing.Any]:
        # If any of the conversions fail we simply propagate the error.
        return dict(
            rating              = float(self.rating) if self.rating != '' else None, # I've actually found shorts which have no rating.
            runtime_minutes     = int(self.runtime_minutes),
            genres              = self.genres.split(', '),
            votes               = int(self.votes),
            my_rating           = float(self.my_rating) if (self.my_rating is not None and self.my_rating != '') else None,
            watch_dates         = [self._date(self.listing_date)], # Treat the listing date as the date the movie was watched, and we don't support multiple watch dates.
            release_date        = self._date(self.release_date),
        )

    def mlf_per_src_fields(self) -> dict[str, typing.Any]:
        # If any of the conversions fail we simply propagate the error.
        return dict(
            list_index          = int(self.list_index),
            note                = self.note,
            listing_date        = self._date(self.listing_date),
        )

    @classmethod
    def _date(cls, date: str) -> datetime.date:
        # IMDb used to only serve %Y-%m-%d, but now it sometimes serves a partial date.
        for fmt in ('%Y-%m-%d', '%Y-%m', '%Y'):
            try:
                return datetime.datetime.strptime(date, fmt).date()
            except ValueError:
                pass

        raise ValueError(f'Invalid date: {date}')

# NOTE: not registered because cinemagoer is broken so this fetcher is temporarily (permanently?) unsupported.
# @_reg._register_builtin
class SeleniumCinemagoerListFetcher(_fetch.ListFetcher, list_type='imdb-browser-cinemagoer-listid', uid_family=_UID_FAMILY):
    exports_server: None | multiprocessing.Process = None
    requests_queue: multiprocessing.Queue = multiprocessing.Queue()

    def _fetch_into_file(self, movie_list_file: _mlf.MovieListFile) -> None:
        _dbg.logger.info(f"Cinemagoer: Going to download the CSV for IMDb list id: {self.concrete_listdef.address}")
        movies_csv = self.download_csv(self.concrete_listdef)
        _fetch_movies_in_csv(movies_csv, movie_list_file, self, _Cinemagoer.fetch_movies_from_api)

    @classmethod
    def download_csv(cls, concrete_listdef: _ldef.CanonListdef) -> list[_CsvRow]:
        NUM_RETRIES = 2
        CSV_DOWNLOAD_TIMEOUT_SECS = 120

        downloads_dir = _dbg.FlamEnv.DOWNLOADS_DIR.get_or_default(os.path.join(os.path.expanduser('~'), 'Downloads'))

        if not os.path.isdir(downloads_dir):
            raise _exc.InputError(f"Invalid {_dbg.FlamEnv.DOWNLOADS_DIR}: '{downloads_dir}': not a directory.")

        _dbg.logger.info(f"CSV should be downloaded into {downloads_dir=}")

        # Support optional 'ls' prefix.
        list_id = concrete_listdef.address.removeprefix('ls')

        # We do retries because of a particularly horrible issue that makes the download sometimes fail.
        for i in range(NUM_RETRIES):
            cls._spin_server_if_needed()

            try:
                latest_csv = utils.download_file_using_browser(
                    download_cmd=lambda: cls.requests_queue.put_nowait(list_id),
                    file_extension='csv',
                    downloads_dir=downloads_dir,
                    timeout_secs=CSV_DOWNLOAD_TIMEOUT_SECS)
                break
            except TimeoutError as e:
                # Issue might've been with the server so respin it.
                _exports_server_cleanup()
                _dbg.logger.warning(f"Download timed out after {CSV_DOWNLOAD_TIMEOUT_SECS} seconds. This is retry {i + 1} / {NUM_RETRIES}")

                if i == NUM_RETRIES - 1:
                    raise _exc.InputError(f"Timed out trying to download LISTDEF '{concrete_listdef}' from IMDb. Are you sure the address is valid?") from e

        _dbg.logger.info(f"Successfully downloaded CSV: '{latest_csv}'")

        # CSV documentation says to use newline=''.
        with open(latest_csv, 'r', newline='', encoding='utf-8') as movies_csv_file:
            movies_csv = _read_csv(movies_csv_file)

        # TODO: Instead of remove, mov it to the flam dir and figure out how the hell to support using the already-downloaded CSV to refetch?
        # Once the CSV is renamed, we can know from the abstract listdef of SeleniumFetcher where to get the CSV from.
        os.remove(latest_csv)
        return movies_csv

    @classmethod
    def _spin_server_if_needed(cls) -> None:
        if cls.exports_server is not None and cls.exports_server.is_alive():
            _dbg.logger.info("CSV server is alive, no need to spin it")
            return

        profile = _dbg.FlamEnv.BROWSER_PROFILE.get_or_default()
        browser_type_str = _dbg.FlamEnv.BROWSER.get_or_default(_BrowserType.AUTO)

        try:
            browser_type = _BrowserType(browser_type_str)
        except ValueError as e:
            raise _exc.InputError(f"Invalid {_dbg.FlamEnv.BROWSER}: '{browser_type_str}' (must be one of {', '.join(_BrowserType)}).") from e

        # On re-spins create a new queue. The first go-around it's already instantiated to give mypy an easier time.
        if cls.exports_server is not None:
            cls.requests_queue = multiprocessing.Queue()

        _dbg.logger.info(f"Spinning new CSV server with {browser_type=}, {profile=}")

        # TODO: Consider a mechanism that blocks until the server informs that the browser is running and it's ready to take requests.
        cls.exports_server = multiprocessing.Process(target=_export_lists_handler, name='ExportsServer', args=(cls.requests_queue, browser_type, profile), daemon=True)
        cls.exports_server.start()
    
# Python devs made a dumbass decision to terminate multiprocesses in a way that doesn't run exit handlers,
# and we must kill it cleanly to kill the browser.
# NOTE: I tried instead to make the child process terminate itself when it detects that it's orphaned,
# but multiprocess doesn't actually let you orphan children, because fuck you that's why.
@atexit.register
def _exports_server_cleanup() -> None:
    if SeleniumCinemagoerListFetcher.exports_server is not None and SeleniumCinemagoerListFetcher.exports_server.is_alive():
        _dbg.logger.info("Sending QUIT message to server")
        SeleniumCinemagoerListFetcher.requests_queue.put_nowait(_REQUEST_QUIT)

        # Join is needed because the subprocess is a daemon, which means it dies when we die,
        # and we don't want it to die before it handles this request.
        SeleniumCinemagoerListFetcher.exports_server.join()
        _dbg.logger.info("Server is dead")
    else:
        _dbg.logger.info("No need to do server cleanup")

# NOTE: not registered because cinemagoer is broken so this fetcher is temporarily (permanently?) unsupported.
# @_reg._register_builtin
class CsvCinemagoerListFetcher(_fetch.ListFetcher, list_type='imdb-csv-cinemagoer-path', uid_family=_UID_FAMILY):
    def _fetch_into_file(self, movie_list_file: _mlf.MovieListFile) -> None:
        _dbg.logger.info(f"Cinemagoer: Fetching IMDb list by CSV: '{self.concrete_listdef.address}'")
        movies_csv = self.open_csv(self.concrete_listdef)
        _fetch_movies_in_csv(movies_csv, movie_list_file, self, _Cinemagoer.fetch_movies_from_api)
    
    @classmethod
    def open_csv(cls, concrete_listdef: _ldef.CanonListdef) -> list[_CsvRow]:
        try:
            movies_csv_file = open(concrete_listdef.address, 'r', newline='', encoding='utf-8')
        except FileNotFoundError as e:
            raise _exc.InputError(f"Invalid LISTDEF {concrete_listdef}: no such file.") from e

        with movies_csv_file:
            return _read_csv(movies_csv_file)

@_reg._register_builtin
class SeleniumApiDevListFetcher(_fetch.ListFetcher, list_type='imdb-browser-apidev-listid', uid_family=_UID_FAMILY):
    """IMDB_LIST_ID

    Takes an IMDb list ID as an input, and downloads information in two steps:

    #. Export the list to CSV from the IMDb website - this will automatically launch your browser and click some buttons!
    #. Fill in a bunch of additional information using this free API: https://imdbapi.dev/
    
    It's easy to check what is your list's ID. Just open it in the browser, and the URL should look like this: https://www.imdb.com/list/ls083886771. The list ID in this example is "083886771".

    There are a few environment variables you can export to control the browser use:

    * **FLAM_DOWNLOADS** - Path to the downloads folder on your computer so flam will know where to look for the downloaded CSV. If your browser doesn't download things to ~/Downloads, you must set this variable for this fetcher to work
    * **FLAM_BROWSER** - Which browser to use: 'chrome', 'edge', or 'firefox'. By default flam tries to detect your default browser
    * **FLAM_BROWSER_PROFILE** - Path to your browser profile. This is only needed if your list is set to private so a profile is needed where you are expected to be already logged in
    """
    def _fetch_into_file(self, movie_list_file: _mlf.MovieListFile) -> None:
        _dbg.logger.info(f"IMDbApiDev: Going to download the CSV for IMDb list id: {self.concrete_listdef.address}")
        movies_csv = SeleniumCinemagoerListFetcher.download_csv(self.concrete_listdef)
        _fetch_movies_in_csv(movies_csv, movie_list_file, self, _IMDbApiDev.fetch_movies_from_api)

@_reg._register_builtin
class CsvApiDevListFetcher(_fetch.ListFetcher, list_type='imdb-csv-apidev-path', uid_family=_UID_FAMILY):
    """CSV_PATH

    Takes a CSV that was manually exported from an IMDb list, and downloads additional information using this free API: https://imdbapi.dev/.
    """
    def _fetch_into_file(self, movie_list_file: _mlf.MovieListFile) -> None:
        _dbg.logger.info(f"IMDbApiDev: Fetching IMDb list by CSV: '{self.concrete_listdef.address}'")
        movies_csv = CsvCinemagoerListFetcher.open_csv(self.concrete_listdef)
        _fetch_movies_in_csv(movies_csv, movie_list_file, self, _IMDbApiDev.fetch_movies_from_api)

# TODO: cinemagoer doesn't really work anymore, but there's https://github.com/cinemagoer/cinemagoerng which might work?
class _Cinemagoer:
    @classmethod
    def fetch_movies_from_api(cls, movies_csv: list[_CsvRow], mlf: _mlf.MovieListFile, fetcher: _fetch.ListFetcher) -> None:
        ia = imdb.Cinemagoer()

        # Now we do a pass where we fetch fields using Cinemagoer.
        # Note that we not only skip movies that were previously fetched, but also duplicates in case the same movie appears in the CSV twice.
        with utils.ProgressBar([m for m in movies_csv if m.uid not in mlf.movies_by_uid],
                desc='Downloading',
                keyfunc=lambda m: m.title) as bar:
            for movie_csv in bar:
                cls._fetch_movie(movie_csv, mlf, ia)
                
                # Checkpoint after each film I guess.
                fetcher._checkpoint(mlf)

        _dbg.logger.info("Done fetching movies")

        # We have this "bad names" problem with cinemagoer, so here we refetch any people with bad names.
        with utils.ProgressBar([p for p in mlf.people_by_uid.values() if _is_person_name_bad(p.name)],
                desc='Cleansing data',
                keyfunc=lambda p: p.uid) as bar:
            for mlf_person in bar:
                cls._refetch_person(mlf_person, ia)

                # After each fixed person too..
                fetcher._checkpoint(mlf)

        _dbg.logger.info("Done fetching people")

    @classmethod
    def _fetch_movie(cls, movie_csv: _CsvRow, mlf: _mlf.MovieListFile, ia: imdb.Cinemagoer) -> None:
        NUM_RETRIES = 5
        info_to_fetch = (*imdb.Movie.Movie.default_info, 'critic reviews', 'full credits')
        _dbg.logger.info(f"Fetching movie: {movie_csv}")

        for i in range(NUM_RETRIES):
            try:
                movie_imdb = ia.get_movie(movie_csv.uid, info=info_to_fetch)
                break
            except imdb.IMDbError as e:
                _dbg.logger.warning(f"Error while fetching movie: {e}. This is retry {i + 1} / {NUM_RETRIES}")

                if i == NUM_RETRIES - 1:
                    raise

        # Build crews dictionary and also people.
        crew = {}
        
        for crew_type in _ml.CrewType.iterate_except_any():
            # I generally tried to choose the CrewType values to match imdb's, but this one goddamn type has a space in it and I don't like that.
            imdb_crew_type = str(crew_type) if crew_type != _ml.CrewType.STUNTCAST else 'stunt performer'

            # Building this list as a dictionary solves two problems:
            # 1. Sometimes you get empty people, so those are discarded.
            # 2. Sometimes you get the same person twice. Also discarded.
            crew_imdb_by_uid = {p.getID(): p for p in _safe_get(movie_imdb, imdb_crew_type, default=[]) if p}

            crew[crew_type] = _mlf.MLFCrew(
                crew_type = crew_type,
                roles_by_uid = {r.person_uid: r for r in cls._build_roles(crew_imdb_by_uid)},
            )

            # We are unafraid to add people to the file before the movie, because we "clean up" unused people before the file is written.
            _update_people_by_uid(mlf.people_by_uid, ((p.uid, p) for p in cls._build_people(crew_imdb_by_uid)))

        per_src_data = _mlf.MLFMoviePerSourceData(
            canon_listdef = mlf.abstract_listdef,
            **movie_csv.mlf_per_src_fields(),
        )

        mlf_movie = _mlf.MLFMovie(
            uid = movie_csv.uid,
            per_src_data = [per_src_data],

            # I prefer to get the title from Cinemagoer because they have better titles for foreign language films, but it's good to have a fallback (not that we ever need it).
            title = _safe_get(movie_imdb, 'title', default=movie_csv.title),
            synopsis = None,
            metascore = _safe_get(movie_imdb, 'metascore'),
            metascore_votes = None,
            languages = [],
            countries = [],
            crew = crew,

            **movie_csv.mlf_universal_fields(),
        )

        mlf.movies_by_uid[mlf_movie.uid] = mlf_movie

    @classmethod
    def _refetch_person(cls, mlf_person: _mlf.MLFPerson, ia: imdb.Cinemagoer) -> None:
        NUM_RETRIES = 5
        _dbg.logger.info(f"Refetching person: {mlf_person.uid}")

        for i in range(NUM_RETRIES):
            try:
                person_imdb = ia.get_person(mlf_person.uid)
                break
            except imdb.IMDbError as e:
                _dbg.logger.warning(f"Error while fetching person: {e}. This is retry {i + 1} / {NUM_RETRIES}")

                if i == NUM_RETRIES - 1:
                    raise

        new_name = _safe_get(person_imdb, 'name', mlf_person.name)
        _dbg.logger.info(f"Replacing bad name: {mlf_person.name} with: {new_name}")
        mlf_person.name = _safe_get(person_imdb, 'name', mlf_person.name)

    # I don't know wtf current_role might be.
    @classmethod
    def _build_characters(cls, current_role: typing.Any) -> typing.Iterable[None | str]:
        # Sometimes it's empty.
        if not current_role:
            return

        if isinstance(current_role, imdb.Character.Character | imdb.Person.Person):
            yield _safe_get(current_role, 'name')
        elif isinstance(current_role, imdb.utils.RolesList):
            yield from (_safe_get(role_imdb, 'name') for role_imdb in current_role)
        else:
            _dbg.logger.warning(f"Type is not recognized: {current_role=}, {type(current_role)=}")

    @classmethod
    def _build_roles(cls, crew_imdb_by_uid: dict[str, imdb.Person.Person]) -> typing.Iterable[_mlf.MLFRole]:
        for person_imdb in crew_imdb_by_uid.values():
            yield _mlf.MLFRole(
                person_uid = person_imdb.getID(),
                characters = [c for c in cls._build_characters(person_imdb.currentRole) if c is not None],
                is_star = None,
            )

    @classmethod
    def _build_people(cls, crew_imdb_by_uid: dict[str, imdb.Person.Person]) -> typing.Iterable[_mlf.MLFPerson]:
        for person_imdb in crew_imdb_by_uid.values():
            yield _mlf.MLFPerson(
                uid = person_imdb.getID(),
                name = _safe_get(person_imdb, 'name', person_imdb.getID()),
                gender = None,
                birthday = None,
                height_cm = None,
                countries = [],
            )

# As an alternative to Cinemagoer since Cinemagoer is dead, found this handy API: https://imdbapi.dev/.
class _IMDbApiDev:
    @classmethod
    def fetch_movies_from_api(cls, movies_csv: list[_CsvRow], mlf: _mlf.MovieListFile, fetcher: _fetch.ListFetcher) -> None:
        BATCH_SIZE = 5
        batch = []
        movies_to_fetch = [m for m in movies_csv if m.uid not in mlf.movies_by_uid]

        # Now we do a pass where we fetch fields using imdbapi.dev.
        # Note that we not only skip movies that were previously fetched, but also duplicates in case the same movie appears in the CSV twice.
        with utils.ProgressBar(movies_to_fetch,
                desc='Downloading',
                keyfunc=lambda m: m.title) as bar:
            for i, movie_csv in enumerate(bar):
                if i % BATCH_SIZE == 0:
                    # Save the progress so far after every batch to mitigate the pain of potential crashes in the middle of the download.
                    fetcher._checkpoint(mlf)

                    batch = movies_to_fetch[i:i + BATCH_SIZE]

                    # Ex: https://api.imdbapi.dev/titles:batchGet?titleIds=tt0054331&titleIds=tt0110200&titleIds=tt0405422&titleIds=tt0047437&titleIds=tt27847051
                    # I kind of want to actually make the 'tt' prefix part of the uid, but that's kind of an annoying refactor, and also it's less convenient for Cinemagoer fetchers,
                    # and we want to have the same uids as them to be part of the same uid family.
                    title_ids = '&'.join(f'titleIds=tt{m.uid}' for m in batch)
                    batch_json = cls._rest_call(f'titles:batchGet?{title_ids}')
                
                movie_json = next(m for m in batch_json['titles'] if movie_csv.uid in m['id'])
                cls._fetch_movie(movie_csv, mlf, movie_json)

        _dbg.logger.info("Done fetching movies")

    @classmethod
    def _fetch_movie(cls, movie_csv: _CsvRow, mlf: _mlf.MovieListFile, movie_json: dict[str, typing.Any]) -> None:
        _dbg.logger.info(f"Fetching movie: {movie_csv}")

        # Build crews dictionary and also people.
        crew = {
            crew_type: _mlf.MLFCrew(crew_type=crew_type, roles_by_uid={})
            for crew_type in _ml.CrewType.iterate_except_any()
        }

        # Some movies (for example Waltz with Bashir) don't have a stars key.
        star_uids = {star['id'].removeprefix('nm') for star in movie_json.get('stars', [])}
        people_to_add = []

        # Ex: https://api.imdbapi.dev/titles/tt0054331/credits?pageSize=50
        for credits_json in cls._paginated_rest_call(f'titles/tt{movie_csv.uid}/credits'):
            # Actually had an instance of receiving no credits key in the response, for the Netflix movie Troll.
            for person_json in credits_json.get('credits', []):
                person_uid = person_json['name']['id'].removeprefix('nm')
                characters: list[str] = []
                is_star = None
                gender = None

                match person_json['category']:
                    case 'director':
                        crew_type = _ml.CrewType.DIRECTOR
                    case 'writer':
                        crew_type = _ml.CrewType.WRITER
                    case 'actor' | 'actress':
                        crew_type = _ml.CrewType.CAST
                        characters.extend(person_json.get('characters', []))
                        is_star = person_uid in star_uids
                        gender = 'male' if person_json['category'] == 'actor' else 'female'
                    case _:
                        raise RuntimeError(f'Unexpected {person_json["category"]=}')

                crew[crew_type].roles_by_uid[person_uid] = _mlf.MLFRole(
                    person_uid = person_uid,
                    characters = characters,
                    is_star = is_star,
                )

                people_to_add.append((person_uid, gender))

        # Have to add the people before we add the movie, because otherwise we run the risk that we get an interrupt after adding the movie,
        # and on the next retry this movie will be skipped due to already being in the list.
        # Adding a person before the movie is safe because in case of an interrupt we'll "clean up" unreferenced people.
        cls._fetch_people(mlf, people_to_add)
        
        try:
            metascore = movie_json['metacritic']['score']
            metascore_votes = movie_json['metacritic'].get('reviewCount', None)
        except KeyError:
            metascore = None
            metascore_votes = None

        per_src_data = _mlf.MLFMoviePerSourceData(
            canon_listdef = mlf.abstract_listdef,
            **movie_csv.mlf_per_src_fields(),
        )

        mlf_movie = _mlf.MLFMovie(
            uid = movie_csv.uid,
            per_src_data = [per_src_data],

            # I prefer to get the title not from the CSV because this API has better titles for foreign language films.
            title = movie_json['primaryTitle'],
            synopsis = movie_json['plot'],
            metascore = metascore,
            metascore_votes = metascore_votes,
            
            # Sometimes there's an empty lang object. For example if you query movie tt2177771 (the monuments men).
            languages = [lang['name'] for lang in movie_json['spokenLanguages'] if 'name' in lang],
            countries = [country['name'] for country in movie_json['originCountries']],
            crew = crew,

            **movie_csv.mlf_universal_fields(),
        )

        mlf.movies_by_uid[mlf_movie.uid] = mlf_movie

    @classmethod
    def _fetch_people(cls, mlf: _mlf.MovieListFile, people_to_add: list[tuple[str, None | str]]) -> None:
        BATCH_SIZE = 5
        batch = []

        new_uids = list(set(uid for uid, _ in people_to_add if uid not in mlf.people_by_uid))

        for i, uid in enumerate(new_uids):
            if i % BATCH_SIZE == 0:
                batch = new_uids[i: i + BATCH_SIZE]

                # Ex: https://api.imdbapi.dev/names:batchGet?nameIds=nm0315041&nameIds=nm0577908
                person_ids = '&'.join(f'nameIds=nm{uid}' for uid in batch)
                batch_json = cls._rest_call(f'names:batchGet?{person_ids}')

            person_json = next(p for p in batch_json['names'] if uid in p['id'])
            _dbg.logger.info(f"Fetching person: {person_json['id']}")

            try:
                # Most people have a displayName, which is best.
                name = person_json['displayName']
            except KeyError:
                try:
                    # Some people have no displayName but have alternativeNames, so we'll take the longest alt name.
                    name = max(person_json['alternativeNames'], key=len)
                except (KeyError, ValueError):
                    name = None

            try:
                birthday_year = person_json['birthDate']['year']
            except KeyError:
                # If there isn't even a year then we'll consider the birthday unknown.
                birthday = None
            else:
                # If there is a year there may still not be the rest, but then we'll round it.
                birthday_month = person_json['birthDate'].get('month', 1)
                birthday_day = person_json['birthDate'].get('day', 1)
                birthday = datetime.date(birthday_year, birthday_month, birthday_day)
            
            mlf.people_by_uid[uid] = _mlf.MLFPerson(
                uid = uid,
                name = name,
                gender = None,
                birthday = birthday,
                height_cm = float(person_json['heightCm']) if 'heightCm' in person_json else None,
                countries = [person_json['birthLocation']] if 'birthLocation' in person_json else [],
            )

        # There is no gender information in the people query but for 'actors' and 'actresses' we can distinguish it based on their crew type in the movie information.
        # So after all MLFPersons are created we'll do a pass of seeing if there's anyone we have a gender hint for and store that.
        for uid, gender in people_to_add:
            if gender is None:
                continue

            mlf_person = mlf.people_by_uid[uid]

            if mlf_person.gender is not None and mlf_person.gender != gender:
                _dbg.logger.warning(f'Got two different genders for person {uid}: {mlf_person.gender} vs {gender}. Using {gender}')

            mlf_person.gender = gender

    @classmethod
    def _rest_call(cls, endpoint: str, **kwargs: typing.Any) -> dict:
        # Import requests only here because it's actually a very expensive import so we don't wanna pay that price for every import of flam when most of them don't need it.
        import requests

        NUM_RETRIES = 10
        SLEEP_BETWEEN_RETRIES = 2

        for i in range(NUM_RETRIES):
            response = requests.get(f'https://api.imdbapi.dev/{endpoint}', timeout=30, params=kwargs)
            _dbg.logger.info(f"Requested: {response.url} with res: {response.status_code}")

            # We actually get this a lot when doing names:batchGet and it reaaaally slows us down. I tried to space out requests by like a second to preempt this warning,
            # but nothing seems as fast as just firing requests at our maximum pace and then sleeping when the API complains.
            # For the record, guy on telegram says that the counter is per endpoint, and limited to 5 requests per second for most endpoints,
            # but 20 requests per 10 seconds for batch endpoints.
            # Sometimes we actually get status code 500 (server error), and the response text explains it was actually a 429, so we need to catch that case too..
            if response.status_code == requests.codes.too_many_requests or '429' in response.text: # pylint: disable=no-member
                time.sleep(SLEEP_BETWEEN_RETRIES)
                _dbg.logger.warning(f"Request failed because of too many requests. Will try again in {SLEEP_BETWEEN_RETRIES} seconds (retry {i}/{NUM_RETRIES})")
                continue

            # Retries are only for too_many_requests - not for other errors.
            try:
                response.raise_for_status()
            except requests.HTTPError as e:
                # Server errors are fetch-interrupts.
                if 500 <= response.status_code < 600:
                    # The response text sometimes contains additional information.
                    _dbg.logger.error(f'Got this response alongside server error: {response.text}')
                    raise _exc.FetchInterrupt(f"{type(e).__name__}: {e}") from e

                # Everything else is a crash.
                raise

            return response.json()

        raise _exc.FlamError('imdbapi.dev is refusing our requests due to sending too many. Try again later.')

    @classmethod
    def _paginated_rest_call(cls, endpoint: str, **kwargs: typing.Any) -> list[dict]:
        PAGE_SIZE = 50
        NUM_RETRIES = 2

        for i in range(NUM_RETRIES):
            try:
                all_responses = []
                page_token = None
                response = cls._rest_call(endpoint, pageSize=PAGE_SIZE, **kwargs)
                all_responses.append(response)

                while 'nextPageToken' in response:
                    # This is some bizarre thing I got once when querying Troll (2022). It looped 1600 times before breaking out of it.
                    # I don't know if this will reproduce or what should we do if we get it again.
                    # Let it break out naturally after some time? Sweep it under the rug? FetchInterrupt? Crash?
                    # For now we raise FetchInterrupt.
                    if page_token is not None and page_token == response['nextPageToken']:
                        raise _exc.FetchInterrupt(f"Got same page token: '{page_token}' twice in a row for endpoint: {endpoint}")

                    page_token = response['nextPageToken']
                    response = cls._rest_call(endpoint, pageSize=PAGE_SIZE, pageToken=page_token, **kwargs)
                    all_responses.append(response)

                return all_responses
            except _exc.FetchInterrupt:
                if i == NUM_RETRIES - 1:
                    raise

        raise RuntimeError("Shouldn't get here!")

def _fetch_movies_in_csv(movies_csv: list[_CsvRow], mlf: _mlf.MovieListFile, fetcher: _fetch.ListFetcher,
        fetch_from_api_func: typing.Callable[[list[_CsvRow], _mlf.MovieListFile, _fetch.ListFetcher], None]) -> None:
    _dbg.logger.info(f"MLF has {len(mlf.movies_by_uid)} movies from prior fetch")

    # First we will build the list of all movies that we already have fetched, and overwrite mlf with this immediately.
    # This lets us bail in the middle if an exception occurs and not lose progress.
    csv_uids = {m.uid for m in movies_csv}
    mlf.movies_by_uid = {uid: m for uid, m in mlf.movies_by_uid.items() if uid in csv_uids}

    _dbg.logger.info(f"MLF has {len(mlf.movies_by_uid)} movies after omitting ones not in the CSV")
    
    # CSV fields are super cheap to write into the file so we'll write them even for movies that were already written, maybe something's changed (like vote count).
    # Better to do this before fetching new movies so that we'll already have that data in when checkpointing.
    _refresh_csv_fields(movies_csv, mlf)

    try:
        fetch_from_api_func(movies_csv, mlf, fetcher)
    # If _fetch_movie or _refetch_person raise an IMDb error, or we get a KeyboardInterrupt,
    # it will break us out of that loop, seal the progress bar nicely, and then we'll handle the exception here by turning it into a FetchInterrupt.
    # HACK: technically we shouldn't reference imdb here, it should be encapsulated. But whatever.
    except (imdb.IMDbError, KeyboardInterrupt) as e:
        raise _exc.FetchInterrupt(f"{type(e).__name__}: {e}") from e

def _read_csv(movies_csv_file: typing.Iterable[str]) -> list[_CsvRow]:
    reader = csv.reader(movies_csv_file)

    # Drop the titles row. If the CSV format doesn't match up we should fail on creating one of the rows.
    movies_csv = [_CsvRow(*row) for row in reader][1:]
    
    # The first 2 characters of the uid are a prefix that we wish to discard.
    for movie in movies_csv:
        movie.uid = movie.uid.removeprefix('tt')

    _dbg.logger.info(f"Read CSV with {len(movies_csv)} rows (excluding the titles row)")
    return movies_csv

def _refresh_csv_fields(movies_csv: list[_CsvRow], mlf: _mlf.MovieListFile) -> None:
    for movie_csv in movies_csv:
        # This function expected to be called while the MLF only has preexisting movies, so we fully expect the fresh new ones to not be in the file yet.
        if movie_csv.uid not in mlf.movies_by_uid:
            continue

        # Not very efficient to create a copy instead of modifying inplace, but I don't think this is the place to worry about performance.
        mlf_movie = mlf.movies_by_uid[movie_csv.uid]
        mlf_movie.per_src_data[0] = mlf_movie.per_src_data[0].replace(**movie_csv.mlf_per_src_fields())
        mlf.movies_by_uid[movie_csv.uid] = mlf_movie.replace(**movie_csv.mlf_universal_fields())

# Because of this deal with bad names, when we merge two people dictionaries we want to keep the person with the good name if there is one.
def _update_people_by_uid(dst_people: dict[str, _mlf.MLFPerson], src_people: typing.Iterable[tuple[str, _mlf.MLFPerson]]) -> None:
    # NOT src_people.items(). That's the responsibility of the callers.
    dst_people.update((uid, p) for uid, p in src_people if uid not in dst_people or _is_person_name_bad(dst_people[uid].name))

# There seems to be a bug in Cinemagoer, sometimes when you get a person from the cast list of a TV show,
# his name goes something like "2011 Alan Tudyk\n          \n          \n          \n          1 episode".
# We fix this by trying to find people with a name like that and replacing it with the correct name.
# By doing this after everything is downloaded and not when the name was added to the dictionary,
# we are able to optimize by using the same person's appearance in something else instead of doing the big download when possible.
def _is_person_name_bad(name: None | str) -> bool:
    assert name is not None
    return '\n' in name or ' episode' in name.lower()

def _safe_get(obj: typing.Any, key: str, default: typing.Any = None) -> typing.Any:
    # I don't trust cinemagoer's __contains__ because it has given some weird results.
    try:
        val = obj[key]
    except KeyError as e:
        _dbg.logger.warning(f"{obj=} is missing {key=}. Defaulting to {default} (error: {e})")
        val = default

    return val

#endregion

#region Selenium server

class _BrowserType(enum.StrEnum):
    AUTO        = 'auto'
    CHROME      = 'chrome'
    EDGE        = 'edge'
    FIREFOX     = 'firefox'

    @classmethod
    def get_system_default(cls) -> _BrowserType:
        try:
            import winreg
            
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\\Microsoft\\Windows\\Shell\\Associations\\UrlAssociations\\http\\UserChoice") as key:
                browser_id = winreg.QueryValueEx(key, 'ProgId')[0]

            _dbg.logger.info(f"This is a Windows machine. Got {browser_id=}")

            if 'ChromeHTML' in browser_id:
                return cls.CHROME
            if 'AppXq0fevzme2pys62n3e0fbqa7peapykr8v' in browser_id: # WTF Microsoft.
                return cls.EDGE
            if 'FirefoxURL' in browser_id:
                return cls.FIREFOX
        except ModuleNotFoundError as e:
            _dbg.logger.info(f"Not a Windows machine: {e}")

        # On Windows this is an empty string, thanks webbrowser.
        webbrowser_name = webbrowser.get().name
        _dbg.logger.info(f"Got {webbrowser_name=}")

        if webbrowser_name != cls.AUTO:
            try:
                return cls(webbrowser_name)
            except ValueError:
                pass
            
        _dbg.logger.warning("Failed to detect default browser. Going with edge (sorry linux users)")
        return cls.EDGE

# This function is "the server". It looks like a huge function but do not be alarmed!
# Selenium is an expensive import, so we only want to import it if it's going to be used. This means that selenium is only imported inside this function,
# and that means that all functions using selenium also need to only be defined inside this function.
# So the first half of this function is a bunch of helper definitions. The function code only begins at the end.
def _export_lists_handler(requests_queue: multiprocessing.Queue, browser_type: _BrowserType = _BrowserType.AUTO, browser_profile_path: str = '') -> None:
    from selenium import webdriver
    from selenium.common.exceptions import NoSuchElementException
    from selenium.common.exceptions import ElementClickInterceptedException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement
    from selenium.webdriver.chromium.options import ChromiumOptions

    class _BrowserController(abc.ABC):
        @abc.abstractmethod
        def set_profile(self, profile: str) -> None:
            pass

        @abc.abstractmethod
        def launch(self) -> WebDriver:
            pass

    class _ChromeController(_BrowserController):
        # Since Edge is also chromium-based, it shares a lot of code with Chrome.
        @classmethod
        def set_chromium_basic_options(cls, options: ChromiumOptions) -> None:
            options.add_argument('--no-sandbox') # Otherwise get an error.
            options.add_experimental_option('excludeSwitches', ['enable-logging']) # Suppress annoying startup message.

        @classmethod
        def set_chromium_profile(cls, options: ChromiumOptions, profile: str) -> None:
            # When you set user-data-dir to a dir that is already in use, this doesn't work. There's no solution but to create a copy of the profile which I don't want to do.
            # Instead users should be suggested to either use Firefox, or create a new profile exclusively for this.
            user_data_dir = os.path.dirname(profile)
            profile_directory = os.path.basename(profile)
            options.add_argument(f'--user-data-dir={user_data_dir}')
            options.add_argument(f'--profile-directory={profile_directory}')

        def __init__(self) -> None:
            self.options = webdriver.ChromeOptions()
            _ChromeController.set_chromium_basic_options(self.options)

        def set_profile(self, profile: str) -> None:
            _ChromeController.set_chromium_profile(self.options, profile)

        def launch(self) -> WebDriver:
            return webdriver.Chrome(options=self.options) # pylint: disable=not-callable
            
    class _EdgeController(_BrowserController):
        def __init__(self) -> None:
            self.options = webdriver.EdgeOptions()
            _ChromeController.set_chromium_basic_options(self.options)

        def set_profile(self, profile: str) -> None:
            _ChromeController.set_chromium_profile(self.options, profile)

        def launch(self) -> WebDriver:
            return webdriver.Edge(options=self.options) # pylint: disable=not-callable

    class _FirefoxController(_BrowserController):
        def __init__(self) -> None:
            self.options = webdriver.FirefoxOptions()

        def set_profile(self, profile: str) -> None:
            # Takes a super long time to load fat profiles, and there's no way around it. I've looked and looked. Users are advised to create a lean profile just for this.
            # The good news is nobody uses Firefox but me and the other browsers seem to be faster.
            self.options.profile = profile # type: ignore

        def launch(self) -> WebDriver:
            return webdriver.Firefox(options=self.options) # pylint: disable=not-callable

    def _do_with_retries[T](action: typing.Callable[[], T], num_retries: int = 10, sleep_between_retries: float = 1.0) -> T:
        for i in range(num_retries):
            try:
                return action()
            except:
                if i == num_retries - 1:
                    raise

                time.sleep(sleep_between_retries)

        raise RuntimeError("Shouldn't get here!")

    def _is_browser_alive(driver: WebDriver) -> bool:
        try:
            driver.title # pylint: disable=pointless-statement
            return True
        except:
            return False

    def _click_export_button(driver: WebDriver, export_button: WebElement) -> None:
        # Annoying popup that asks you to sign in hides the export button sometimes.
        try:
            export_button.click()
        except ElementClickInterceptedException:
            close_popup_button = driver.find_element(By.XPATH, "//button[@aria-label='Close']")
            close_popup_button.click()
            raise

    def _get_download_button(driver: WebDriver) -> WebElement:
        # Try obtain the "in progress" text from the page. If it's there, that means the list isn't ready yet so we raise an exception.
        try:
            driver.find_element(By.XPATH, "//span[text()='In progress']")
            raise RuntimeError('List export status is still in progress.')
        # If there's no more "in progress" element in the page, we return the topmost download button.
        except NoSuchElementException:
            return driver.find_element(By.XPATH, "//button[contains(@aria-label, 'Start download for')]")
        # If still in progress or failed to find it due to an unexpected exception type, refresh the page and propagate the exception so we'll retry.
        except:
            driver.refresh()
            raise

    def _export_list(driver: WebDriver, list_id: str) -> None:
        _dbg.logger.info(f"Exporting {list_id=}. Stage: open list page")
        driver.get(f'https://www.imdb.com/list/ls{list_id}')

        _dbg.logger.info("Stage: click export button")
        export_button = _do_with_retries(
            lambda: driver.find_element(By.XPATH, "//button[@aria-label='Export']"))
        _do_with_retries(lambda: _click_export_button(driver, export_button))

        # Opening the link like this instead of below stage might be better but also might not confirm that the export actually started first. Needs more investigation.
        # _dbg.logger.info("Stage: open exports page")
        # driver.get(f'https://www.imdb.com/exports/')

        _dbg.logger.info("Stage: wait for exports page popup")
        exports_page_link = _do_with_retries(
            lambda: driver.find_element(By.XPATH, "//a[@aria-label='Open exports page']"))

        _dbg.logger.info("Stage: click exports page link")
        _do_with_retries(exports_page_link.click)

        _dbg.logger.info("Stage: get download button")
        download_button = _do_with_retries(lambda: _get_download_button(driver))

        _dbg.logger.info("Stage: click download button")
        _do_with_retries(download_button.click)

        _dbg.logger.info("Successful export")

    # Above was all definitions that will help us later and are only defined inside this function for performance reasons. Actual server code starts here.
    if browser_type == _BrowserType.AUTO:
        browser_type = _BrowserType.get_system_default()

    # I prefer to keep this flexible in case certain controllers need to be instantiated differently, so no enum field for the Controller class.
    controller: _BrowserController

    match browser_type:
        case _BrowserType.CHROME:
            controller = _ChromeController()
        case _BrowserType.EDGE:
            controller = _EdgeController()
        case _BrowserType.FIREFOX:
            controller = _FirefoxController()
        case _:
            raise RuntimeError(f"Unsupported browser type: {browser_type}")

    _dbg.logger.info(f"Server will handle export requests for {browser_type=}, {browser_profile_path=}")

    # Use empty instead of None as default because it's easier for callers to use.
    # TODO: auto detect the default profile for all browsers?
    if browser_profile_path != '':
        controller.set_profile(browser_profile_path)

    # RATIONALE: we spin a server instead of running this code once per list ID because launching the browser takes time and we don't want to pay that cost multiple times.
    # NOTE: I wanted to minimize the browser window but it causes things to fail.
    with controller.launch() as driver:
        _dbg.logger.info("Successful launch")

        while True:
            assert _is_browser_alive(driver)

            try:
                # We use a timeout so we can periodically check if the browser is still alive.
                request = requests_queue.get(block=True, timeout=1)
            except queue.Empty:
                continue

            _dbg.logger.info(f"Got {request=}")

            if request == _REQUEST_QUIT:
                _dbg.logger.info("Quitting by request")
                return

            try:
                # There are retries for specific steps within the exports process, and retries at the client side.
                # But things go faster if we also have a retry for the entire flow at the server side.
                # Maybe in the future we'll have two-way communication and could inform the client of the failure to let him retry without waiting the whole timeout.
                _do_with_retries((lambda: _export_list(driver, request)), num_retries=3)
            except Exception as e: # pylint: disable=broad-exception-caught
                _dbg.logger.error("Got exception while exporting list!", exc_info=True)
                print(e, file=sys.stderr)

#endregion
