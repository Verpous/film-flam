# Copyright (C) 2024 Aviv Edery.

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
import requests

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import ElementClickInterceptedException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.chromium.options import ChromiumOptions

from . import _reg
from . import _fetch
from . import _exc
from . import _mlf
from . import _ml
from . import _ldef
from . import _dbg
from . import utils

# TODO: since cinemagoer is dead there are a few alternative fetchers to consider implementing:
# * https://github.com/tveronesi/imdbinfo
#   - actively maintained but currently broken which is not a good sign
# * https://github.com/itsmehemant7/PyMovieDb - requires imdb API key?
#   - seems to not work
# * https://imdbapi.dev/
#   - a little sus, wouldn't be surprised if it vanishes someday, but for now seems to work great and contains all the information I need and then some
# * https://www.themoviedb.org/
#   - requires API key so users will have to set themselves up with one
#   - requires crediting tmdb somehow https://www.themoviedb.org/about/logos-attribution
#   - supports querying by imdb ID
#   - seems to have a lot of information
#   - has rate limits to be mindful of but they should be rather generous
# * https://www.omdbapi.com/
#   - supports querying by imdb ID
#   - very barebones

_UID_FAMILY = 'imdb'
_REQUEST_QUIT = 'quit'

#region Fetching

@dataclasses.dataclass
class _CsvRow:
    # Order of the fields *must* match up with what is actually served by IMDb.
    list_index:         str
    uid:                str
    watch_date:         str
    modified:           str
    description:        str
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
    myrating:           None | str = None
    myrating_date:      None | str = None

    def mlf_fields(self) -> dict[str, typing.Any]:
        # If any of the conversions fail we simply propagate the error.
        return dict(
            list_index        = int(self.list_index),
            description       = self.description,
            rating            = float(self.rating) if self.rating != '' else None, # I've actually found shorts which have no rating.
            runtime_minutes   = int(self.runtime_minutes),
            genres            = self.genres.split(', '),
            votes             = int(self.votes),
            myrating          = float(self.myrating) if (self.myrating is not None and self.myrating != '') else None,
            watch_date        = self._date(self.watch_date),
            release_date      = self._date(self.release_date),
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

@_reg._register_builtin
class SeleniumCinemagoerListFetcher(_fetch.ListFetcher, list_type='imdb-id', uid_family=_UID_FAMILY):
    exports_server: None | multiprocessing.Process = None
    requests_queue: multiprocessing.Queue = multiprocessing.Queue()

    def fetch_into_file(self, movie_list_file: _mlf.MovieListFile) -> None:
        _dbg.logger.info(f"Cinemagoer: Going to download the CSV for IMDb list id: {self.concrete_listdef.address}")
        movies_csv = self.download_csv(self.concrete_listdef)
        _fetch_movies_in_csv(movies_csv, movie_list_file, _Cinemagoer.fetch_movies_from_api)

    @classmethod
    def download_csv(cls, concrete_listdef: _ldef.CanonListdef) -> list[_CsvRow]:
        NUM_RETRIES = 2
        CSV_DOWNLOAD_TIMEOUT_SECS = 40

        downloads_dir = _dbg.FlamEnv.DOWNLOADS_DIR.get_or_default(os.path.join(os.path.expanduser('~'), 'Downloads'))

        if not os.path.isdir(downloads_dir):
            raise _exc.InputError(f"Invalid FLAM_DOWNLOADS: '{downloads_dir}': not a directory.")

        _dbg.logger.info(f"CSV should be downloaded into {downloads_dir=}")

        # We do retries because of a particularly horrible issue that makes the download sometimes fail.
        for i in range(NUM_RETRIES):
            cls.spin_server_if_needed()

            try:
                latest_csv = utils.download_file_using_browser(
                    download_cmd=lambda: cls.requests_queue.put_nowait(concrete_listdef.address),
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
        with open(latest_csv, 'r', newline='') as movies_csv_file:
            movies_csv = _read_csv(movies_csv_file)

        # TODO: Instead of remove, mov it to the flam dir and figure out how the hell to support using the already-downloaded CSV to refetch?
        # Once the CSV is renamed, we can know from the abstract listdef of SeleniumFetcher where to get the CSV from.
        os.remove(latest_csv)
        return movies_csv

    @classmethod
    def spin_server_if_needed(cls) -> None:
        if cls.exports_server is not None and cls.exports_server.is_alive():
            _dbg.logger.info("CSV server is alive, no need to spin it.")
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

@_reg._register_builtin
class CsvCinemagoerListFetcher(_fetch.ListFetcher, list_type='imdb-csv', uid_family=_UID_FAMILY):
    def fetch_into_file(self, movie_list_file: _mlf.MovieListFile) -> None:
        _dbg.logger.info(f"Cinemagoer: Fetching IMDb list by CSV: '{self.concrete_listdef.address}'")
        movies_csv = self.open_csv(self.concrete_listdef)
        _fetch_movies_in_csv(movies_csv, movie_list_file, _Cinemagoer.fetch_movies_from_api)
    
    @classmethod
    def open_csv(cls, concrete_listdef: _ldef.CanonListdef) -> list[_CsvRow]:
        try:
            movies_csv_file = open(concrete_listdef.address, 'r', newline='')
        except FileNotFoundError as e:
            raise _exc.InputError(f"Invalid LISTDEF {concrete_listdef}: no such file.") from e

        with movies_csv_file:
            return _read_csv(movies_csv_file)

# TODO: Do a pass on list_type names in this file once ready.
@_reg._register_builtin
class SeleniumRESTListFetcher(_fetch.ListFetcher, list_type='imdb-rest', uid_family=_UID_FAMILY):
    def fetch_into_file(self, movie_list_file: _mlf.MovieListFile) -> None:
        _dbg.logger.info(f"IMDbREST: Going to download the CSV for IMDb list id: {self.concrete_listdef.address}")
        movies_csv = SeleniumCinemagoerListFetcher.download_csv(self.concrete_listdef)
        _fetch_movies_in_csv(movies_csv, movie_list_file, _IMDbREST.fetch_movies_from_api)

@_reg._register_builtin
class CsvRESTListFetcher(_fetch.ListFetcher, list_type='imdb-rest-csv', uid_family=_UID_FAMILY):
    def fetch_into_file(self, movie_list_file: _mlf.MovieListFile) -> None:
        _dbg.logger.info(f"IMDbREST: Fetching IMDb list by CSV: '{self.concrete_listdef.address}'")
        movies_csv = CsvCinemagoerListFetcher.open_csv(self.concrete_listdef)
        _fetch_movies_in_csv(movies_csv, movie_list_file, _IMDbREST.fetch_movies_from_api)

class _Cinemagoer:
    @classmethod
    def fetch_movies_from_api(cls, movies_csv: list[_CsvRow], movie_list_file: _mlf.MovieListFile) -> None:
        ia = imdb.Cinemagoer()

        # Now we do a pass where we fetch fields using Cinemagoer.
        # Note that we not only skip movies that were previously fetched, but also duplicates in case the same movie appears in the CSV twice.
        with utils.ProgressBar([m for m in movies_csv if m.uid not in movie_list_file.movies_by_uid],
                desc='Downloading',
                keyfunc=lambda m: m.title) as bar:
            for movie_csv in bar:
                cls.fetch_movie(movie_csv, movie_list_file, ia)

        _dbg.logger.info("Done fetching movies")

        # We have this "bad names" problem with cinemagoer, so here we refetch any people with bad names.
        with utils.ProgressBar([p for p in movie_list_file.people_by_uid.values() if _is_person_name_bad(p.name)],
                desc='Cleansing data',
                keyfunc=lambda p: p.uid) as bar:
            for mlf_person in bar:
                cls.refetch_person(mlf_person, ia)

        _dbg.logger.info("Done fetching people")

    @classmethod
    def fetch_movie(cls, movie_csv: _CsvRow, movie_list_file: _mlf.MovieListFile, ia: imdb.Cinemagoer) -> None:
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
        
        for crew_type in _ml.CrewType:
            # I generally tried to choose the CrewType values to match imdb's, but this one goddamn type has a space in it and I don't like that.
            imdb_crew_type = crew_type.value if crew_type != _ml.CrewType.STUNTCAST else 'stunt performer'

            # Building this list as a dictionary solves two problems:
            # 1. Sometimes you get empty people, so those are discarded.
            # 2. Sometimes you get the same person twice. Also discarded.
            crew_imdb_by_uid = {p.getID(): p for p in _safe_get(movie_imdb, imdb_crew_type, default=[]) if p}

            crew[str(crew_type)] = _mlf.MLFCrew(
                crew_type = crew_type,
                roles_by_uid = {r.person_uid: r for r in cls._build_roles(crew_imdb_by_uid)},
            )

            # We are unafraid to add people to the file before the movie, because we "clean up" unused people before the file is written.
            _update_people_by_uid(movie_list_file.people_by_uid, ((p.uid, p) for p in cls._build_people(crew_imdb_by_uid)))

        mlf_movie = _mlf.MLFMovie(
            uid = movie_csv.uid,

            # I prefer to get the title from Cinemagoer because they have better titles for foreign language films, but it's good to have a fallback (not that we ever need it).
            title = _safe_get(movie_imdb, 'title', default=movie_csv.title),
            metascore = _safe_get(movie_imdb, 'metascore'),
            crew = crew,

            **movie_csv.mlf_fields(),
        )

        movie_list_file.movies_by_uid[mlf_movie.uid] = mlf_movie

    @classmethod
    def refetch_person(cls, mlf_person: _mlf.MLFPerson, ia: imdb.Cinemagoer) -> None:
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
    def build_characters(cls, current_role: typing.Any) -> typing.Iterable[None | str]:
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
                characters = [c for c in cls.build_characters(person_imdb.currentRole) if c is not None],
            )

    @classmethod
    def _build_people(cls, crew_imdb_by_uid: dict[str, imdb.Person.Person]) -> typing.Iterable[_mlf.MLFPerson]:
        for person_imdb in crew_imdb_by_uid.values():
            yield _mlf.MLFPerson(
                uid = person_imdb.getID(),
                name = _safe_get(person_imdb, 'name', person_imdb.getID())
            )

class _IMDbREST:
    @classmethod
    def fetch_movies_from_api(cls, movies_csv: list[_CsvRow], movie_list_file: _mlf.MovieListFile) -> None:
        BATCH_SIZE = 5
        batch = []
        movies_to_fetch = [m for m in movies_csv if m.uid not in movie_list_file.movies_by_uid]

        # Now we do a pass where we fetch fields using imdbapi.dev.
        # Note that we not only skip movies that were previously fetched, but also duplicates in case the same movie appears in the CSV twice.
        with utils.ProgressBar(movies_to_fetch,
                desc='Downloading',
                keyfunc=lambda m: m.title) as bar:
            for i, movie_csv in enumerate(bar):
                if i % BATCH_SIZE == 0:
                    batch = movies_to_fetch[i:i + BATCH_SIZE]

                    # Ex: https://api.imdbapi.dev/titles:batchGet?titleIds=tt0054331&titleIds=tt0110200&titleIds=tt0405422&titleIds=tt0047437&titleIds=tt27847051
                    title_ids = '&'.join(f'titleIds=tt{m.uid}' for m in batch)
                    batch_json = cls.rest_call(f'titles:batchGet?{title_ids}')
                
                movie_json = next(m for m in batch_json['titles'] if movie_csv.uid in m['id'])
                cls.fetch_movie(movie_csv, movie_list_file, movie_json)

        _dbg.logger.info("Done fetching movies")

    @classmethod
    def fetch_movie(cls, movie_csv: _CsvRow, movie_list_file: _mlf.MovieListFile, movie_json: dict[str, typing.Any]) -> None:
        try:
            metascore = movie_json['metacritic']['score']
        except KeyError:
            metascore = None

        # Build crews dictionary and also people.
        crew = {
            str(crew_type): _mlf.MLFCrew(
                    crew_type = crew_type,
                    roles_by_uid = {}
                )
            for crew_type in _ml.CrewType
        }

        characters: list[str] = []

        # Ex: https://api.imdbapi.dev/titles/tt0054331/credits?pageSize=50
        for credits_json in cls.paginated_rest_call(f'titles/tt{movie_csv.uid}/credits'):
            for person_json in credits_json['credits']:
                match person_json['category']:
                    case 'director':
                        crew_type = _ml.CrewType.DIRECTOR
                    case 'writer':
                        crew_type = _ml.CrewType.WRITER
                    case 'actor' | 'actress':
                        # TODO: Theoretically we could flag it if the actor is in a starring role!
                        crew_type = _ml.CrewType.CAST
                        characters.extend(person_json.get('characters', []))
                    case _:
                        raise RuntimeError(f'Unexpected {person_json["category"]=}')

                person_uid = person_json['name']['id'][2:]
                crew[crew_type].roles_by_uid[person_uid] = _mlf.MLFRole(
                    person_uid = person_uid,
                    characters = characters,
                )

                # We are unafraid to add people to the file before the movie, because we "clean up" unused people before the file is written.
                if person_uid not in movie_list_file.people_by_uid:
                    movie_list_file.people_by_uid[person_uid] = _mlf.MLFPerson(
                        uid = person_uid,
                        name = person_json['name']['displayName'],
                    )
        
        # TODO: With this API we can also get interesting stuff like languages, countries.
        mlf_movie = _mlf.MLFMovie(
            uid = movie_csv.uid,

            # I prefer to get the title from Cinemagoer because they have better titles for foreign language films, but it's good to have a fallback (not that we ever need it).
            title = movie_json['primaryTitle'],
            metascore = metascore,
            crew = crew,

            **movie_csv.mlf_fields(),
        )

        movie_list_file.movies_by_uid[mlf_movie.uid] = mlf_movie

    @classmethod
    def rest_call(cls, endpoint: str, **kwargs: typing.Any) -> dict:
        response = requests.get(f'https://api.imdbapi.dev/{endpoint}', timeout=30, params=kwargs)
        _dbg.logger.info(f"Requested: {response.url} with res: {response.status_code}")
        response.raise_for_status()
        return response.json()

    @classmethod
    def paginated_rest_call(cls, endpoint: str, **kwargs: typing.Any) -> typing.Iterable[dict]:
        PAGE_SIZE = 50
        response = cls.rest_call(endpoint, pageSize=PAGE_SIZE, **kwargs)
        yield response

        while 'nextPageToken' in response:
            response = cls.rest_call(endpoint, pageSize=PAGE_SIZE, pageToken=response['nextPageToken'], **kwargs)
            yield response

def _fetch_movies_in_csv(movies_csv: list[_CsvRow], movie_list_file: _mlf.MovieListFile,
        fetch_from_api_func: typing.Callable[[list[_CsvRow], _mlf.MovieListFile], None]) -> None:
    _dbg.logger.info(f"MLF has {len(movie_list_file.movies_by_uid)} movies from prior")

    # First we will build the list of all movies that we already have fetched, and overwrite movie_list_file with this immediately.
    # This lets us bail in the middle if an exception occurs and not lose progress.
    csv_uids = {m.uid for m in movies_csv}
    movie_list_file.movies_by_uid = {uid: m for uid, m in movie_list_file.movies_by_uid.items() if uid in csv_uids}

    _dbg.logger.info(f"MLF has {len(movie_list_file.movies_by_uid)} movies after omitting ones not in the CSV")

    try:
        fetch_from_api_func(movies_csv, movie_list_file)
    # If fetch_movie or refetch_person raise an IMDb error, or we get a KeyboardInterrupt,
    # it will break us out of that loop, seal the progress bar nicely, and then we'll handle the exception here by turning it into a FetchInterrupt.
    # HACK: technically we shouldn't reference imdb here, it should be encapsulated. But whatever.
    except (imdb.IMDbError, KeyboardInterrupt) as e:
        # Do this even if an IMDb error took place.
        _add_csv_fields(movies_csv, movie_list_file)
        raise _exc.FetchInterrupt(f"{type(e).__name__}: {e}") from e
        
    _add_csv_fields(movies_csv, movie_list_file)

def _read_csv(movies_csv_file: typing.Iterable[str]) -> list[_CsvRow]:
    reader = csv.reader(movies_csv_file)

    # Drop the titles row. If the CSV format doesn't match up we should fail on creating one of the rows.
    movies_csv = [_CsvRow(*row) for row in reader][1:]
    
    # The first 2 characters of the uid are a prefix that we wish to discard.
    for movie in movies_csv:
        movie.uid = movie.uid[2:]

    _dbg.logger.info(f"Read CSV with {len(movies_csv)} rows (excluding the titles row)")
    return movies_csv

def _add_csv_fields(movies_csv: list[_CsvRow], movie_list_file: _mlf.MovieListFile) -> None:
    for movie_csv in movies_csv:
        if movie_csv.uid not in movie_list_file.movies_by_uid:
            _dbg.logger.warning(f"Movie by UID {movie_csv.uid} wasn't fetched. This shouldn't happen unless we hit an IMDbError while fetching")
            continue

        # This isn't very efficient - we create a copy instead of modifying inplace,
        # and we do this even for newly fetched files, even though they were already constructed with the right CSV fields.
        # I don't think this is the place to worry about performance though, and this is just the easiest way.
        movie_list_file.movies_by_uid[movie_csv.uid] = movie_list_file.movies_by_uid[movie_csv.uid].replace(**movie_csv.mlf_fields())

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
        return webdriver.Chrome(options=self.options)
        
class _EdgeController(_BrowserController):
    def __init__(self) -> None:
        self.options = webdriver.EdgeOptions()
        _ChromeController.set_chromium_basic_options(self.options)

    def set_profile(self, profile: str) -> None:
        _ChromeController.set_chromium_profile(self.options, profile)

    def launch(self) -> WebDriver:
        return webdriver.Edge(options=self.options)

class _FirefoxController(_BrowserController):
    def __init__(self) -> None:
        self.options = webdriver.FirefoxOptions()

    def set_profile(self, profile: str) -> None:
        # Takes a super long time to load fat profiles, and there's no way around it. Users are advised to create a lean profile just for this.
        self.options.profile = profile # type: ignore

    def launch(self) -> WebDriver:
        return webdriver.Firefox(options=self.options)

def _do_with_retries[T](action: typing.Callable[[], T], num_retries: int = 10, sleep_between_retries: float = 1.0) -> T:
    for i in range(num_retries):
        try:
            return action()
        except:
            if i == num_retries - 1:
                raise

            time.sleep(sleep_between_retries)

    raise RuntimeError('This should never be reached!')

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

def _export_lists_handler(requests_queue: multiprocessing.Queue, browser_type: _BrowserType = _BrowserType.AUTO, browser_profile_path: str = '') -> None:
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
                _export_list(driver, request)
            except Exception as e: # pylint: disable=broad-exception-caught
                _dbg.logger.error("Got exception while exporting list!", exc_info=True)
                print(e, file=sys.stderr)

#endregion
