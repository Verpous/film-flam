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

import os
import csv
import imdb # type: ignore
import urllib.request
import codecs
import typing
import dataclasses

import filmflam.repo as repo
import filmflam.fetching as fetching
import filmflam._utils as utils
import filmflam.exceptions as exceptions

_ID_TYPE = 'imdb'

@dataclasses.dataclass
class CsvRow:
    # Order of the fields *must* match up with what is actually served by IMDb.
    list_index:         str
    uid:                str
    watch_date:         str
    modified:           str
    description:        str
    title:              str
    url:                str
    _type:              str
    rating:             str
    runtime_minutes:    str
    year:               str
    genres:             str
    votes:              str
    release_date:       str
    directors:          str

    # These only appear in CSVs of lists made by the logged in user.
    myrating:           None | str = None
    myrating_date:      None | str = None

class PublicListFetcher(fetching.ListFetcher):
    @classmethod
    def fetcher_type(cls) -> str:
        return 'imdb-id'

    def id_type(self) -> str:
        return _ID_TYPE

    def fetch_into_file(self, list_file: repo.ListFile) -> None:
        try:
            movies_csv_file = urllib.request.urlopen(_get_csv_url(self.concrete_listdef.address))
        except urllib.error.HTTPError as e:
            raise exceptions.InputError(f"Failed to download LISTDEF: '{self.concrete_listdef}' from IMDb with error: {e}. Are you sure the address is valid?")

        with movies_csv_file:
            movies_csv = _read_csv(codecs.iterdecode(movies_csv_file, encoding='utf-8'))

        _fetch_movies_in_csv(movies_csv, list_file)

class PrivateListFetcher(fetching.ListFetcher):
    @classmethod
    def fetcher_type(cls) -> str:
        return 'imdb-private-id'

    def id_type(self) -> str:
        return _ID_TYPE

    def fetch_into_file(self, list_file: repo.ListFile) -> None:
        NUM_RETRIES = 1 # TODO: if we never experience timeouts, get rid of this.
        CSV_DOWNLOAD_TIMEOUT_SECS = 20
        DOWNLOADS_DIR = os.getenv('FLAM_DOWNLOADS', os.path.join(os.path.expanduser('~'), 'Downloads'))

        if not os.path.isdir(DOWNLOADS_DIR):
            raise exceptions.InputError(f"Invalid FLAM_DOWNLOADS: '{DOWNLOADS_DIR}': not a directory.")

        # We do retries because of a particularly horrible issue that makes the download sometimes fail.
        for i in range(NUM_RETRIES):
            try:
                latest_csv = utils.download_file_using_browser(
                    url=_get_csv_url(self.concrete_listdef.address),
                    file_extension='csv',
                    downloads_dir=DOWNLOADS_DIR,
                    timeout_secs=CSV_DOWNLOAD_TIMEOUT_SECS)
            except TimeoutError as e:
                if i == NUM_RETRIES - 1:
                    raise exceptions.InputError(f"Timed out trying to download LISTDEF: '{self.concrete_listdef}' from IMDb. Are you sure the address is valid?") from e

        # CSV documentation says to use newline=''.
        with open(latest_csv, 'r', newline='') as movies_csv_file:
            movies_csv = _read_csv(movies_csv_file)

        os.remove(latest_csv)
        _fetch_movies_in_csv(movies_csv, list_file)

class CsvListFetcher(fetching.ListFetcher):
    @classmethod
    def fetcher_type(cls) -> str:
        return 'imdb-csv'

    def id_type(self) -> str:
        return _ID_TYPE

    def fetch_into_file(self, list_file: repo.ListFile) -> None:
        try:
            movies_csv_file = open(self.concrete_listdef.address, 'r', newline='')
        except FileNotFoundError as e:
            raise exceptions.InputError(f"Invalid LISTDEF: {self.concrete_listdef}: no such file.") from e

        with movies_csv_file:
            movies_csv = _read_csv(movies_csv_file)

        _fetch_movies_in_csv(movies_csv, list_file)

def _get_csv_url(list_id: str) -> str:
    return f'https://www.imdb.com/list/ls{list_id}/export?ref_=ttls_exp'

def _read_csv(movies_csv_file: typing.Iterable[str]) -> list[CsvRow]:
    reader = csv.reader(movies_csv_file)

    # Drop the titles row.
    movies_csv = [CsvRow(*row) for row in reader][1:]
    
    # The first 2 characters of the uid are a prefix that we wish to discard.
    for movie in movies_csv:
        movie.uid = movie.uid[2:]

    return movies_csv

def _fetch_movies_in_csv(movies_csv: list[CsvRow], list_file: repo.ListFile) -> None:
    # First we will build the list of all movies that we already have fetched, and overwrite list_file with this immediately.
    # This lets us bail in the middle if an exception occurs and not lose progress.
    csv_uids = {m.uid for m in movies_csv}
    list_file.movies_by_uid = {uid: m for uid, m in list_file.movies_by_uid.items() if uid in csv_uids}

    ia = imdb.Cinemagoer()
    imdb_error = None

    try:
        # Now we do a pass where we fetch fields using Cinemagoer.
        # Note that we not only skip movies that were previously fetched, but also duplicates in case the same movie appears in the CSV twice.
        with utils.ProgressBar([m for m in movies_csv if m.uid not in list_file.movies_by_uid],
                desc='Downloading',
                keyfunc=lambda m: m.title) as bar:
            for movie_csv in bar:
                _fetch_movie(movie_csv, list_file, ia)

        # We have this "bad names" problem with cinemagoer, so here we refetch any people with bad names.
        with utils.ProgressBar([p for p in list_file.people_by_uid.values() if _is_person_name_bad(p.name)],
                desc='Cleansing data',
                keyfunc=lambda p: p.uid) as bar:
            for person_lf in bar:
                _refetch_person(person_lf, ia)
    # If _fetch_movie or _refetch_person raise an IMDb error, it will break us out of that loop, seal the progress bar nicely, and then we'll handle the exception here.
    except imdb.IMDbError as e:
        imdb_error = e
        
    # Now a pass where we add CSV fields. We reach this even if an IMDb error took place, it's not in a finally block because we don't want to do it for just any exception.
    for movie_csv in movies_csv:
        # This shouldn't happen unless we hit an exception earlier.
        if movie_csv.uid not in list_file.movies_by_uid:
            continue

        movie_lf = list_file.movies_by_uid[movie_csv.uid]

        movie_lf.list_index         = int(movie_csv.list_index)
        movie_lf.watch_date         = movie_csv.watch_date
        movie_lf.description        = movie_csv.description
        movie_lf.rating             = float(movie_csv.rating)
        movie_lf.runtime_minutes    = int(movie_csv.runtime_minutes)
        movie_lf.genres             = movie_csv.genres.split(', ')
        movie_lf.votes              = int(movie_csv.votes)
        movie_lf.release_date       = movie_csv.release_date
        movie_lf.myrating           = float(movie_csv.myrating) if (movie_csv.myrating is not None and movie_csv.myrating != '') else None

    if imdb_error is not None:
        raise exceptions.FetchInterrupt(str(imdb_error))

def _fetch_movie(movie_csv: CsvRow, list_file: repo.ListFile, ia: imdb.Cinemagoer) -> None:
    NUM_RETRIES = 5
    info_to_fetch = (*imdb.Movie.Movie.default_info, 'critic reviews', 'full credits')

    for i in range(NUM_RETRIES):
        try:
            movie_imdb = ia.get_movie(movie_csv.uid, info=info_to_fetch)
            break
        except imdb.IMDbError:
            if i == NUM_RETRIES - 1:
                raise

    movie_lf = repo.ListFileMovie.create(uid=movie_csv.uid)

    # Prefer to get the title from Cinemagoer because in the CSV it's more often in English, but it's good to have a fallback (not that we ever need it).
    movie_lf.title = _safe_get(movie_imdb, 'title', default=movie_csv.title) 
    movie_lf.metascore = _safe_get(movie_imdb, 'metascore')

    for crew_type in repo.CREW_TYPES:
        # Building this list as a dictionary solves two problems:
        # 1. Sometimes you get empty people, so those are discarded.
        # 2. Sometimes you get the same person twice. Also discarded.
        crew_imdb_by_uid = {p.getID(): p for p in _safe_get(movie_imdb, crew_type, default=[]) if p}

        movie_lf.crew[crew_type] = repo.ListFileCrew.create(
            crew_type=crew_type,
            roles_by_uid={r.person_uid: r for r in _build_roles(crew_imdb_by_uid)})
        _update_people_by_uid(list_file.people_by_uid, ((p.uid, p) for p in _build_people(crew_imdb_by_uid)))

    list_file.movies_by_uid[movie_csv.uid] = movie_lf

def _refetch_person(person_lf: repo.ListFilePerson, ia: imdb.Cinemagoer) -> None:
    NUM_RETRIES = 5

    for i in range(NUM_RETRIES):
        try:
            person_imdb = ia.get_person(person_lf.uid)
            break
        except imdb.IMDbError:
            if i == NUM_RETRIES - 1:
                raise

    person_lf.name = _safe_get(person_imdb, 'name', person_lf.name)

# I don't know wtf current_role might be.
def _build_characters(current_role: typing.Any) -> typing.Iterator[None | str]:
    # Sometimes it's empty.
    if not current_role:
        return

    if isinstance(current_role, imdb.Character.Character | imdb.Person.Person):
        yield _safe_get(current_role, 'name')
    elif isinstance(current_role, imdb.utils.RolesList):
        yield from (_safe_get(role_imdb, 'name') for role_imdb in current_role)

def _build_roles(crew_imdb_by_uid: dict[str, imdb.Person.Person]) -> typing.Iterable[repo.ListFileRole]:
    for person_imdb in crew_imdb_by_uid.values():
        role_lf = repo.ListFileRole.create(
            person_uid=person_imdb.getID(),
            characters=[c for c in _build_characters(person_imdb.currentRole) if c is not None])

        yield role_lf

def _build_people(crew_imdb_by_uid: dict[str, imdb.Person.Person]) -> typing.Iterable[repo.ListFilePerson]:
    for person_imdb in crew_imdb_by_uid.values():
        person_lf = repo.ListFilePerson.create(uid=person_imdb.getID())
        person_lf.name = _safe_get(person_imdb, 'name', person_lf.uid)
        yield person_lf

# Because of this deal with bad names, when we merge two people dictionaries we want to keep the person with the good name if there is one.
def _update_people_by_uid(dst_people: dict[str, repo.ListFilePerson], src_people: typing.Iterable[tuple[str, repo.ListFilePerson]]) -> None:
    # NOT src_people.items(). That's the responsibility of the callers.
    dst_people.update((uid, p) for uid, p in src_people if uid not in dst_people or _is_person_name_bad(dst_people[uid].name))

# There seems to be a bug in Cinemagoer, sometimes when you get a person from the cast list of a TV show,
# his name goes something like "2011 Alan Tudyk\n          \n          \n          \n          1 episode".
# We fix this by trying to find people with a name like that and replacing it with the correct name.
# By doing this after everything is downloaded and not when the name was added to the dictionary,
# we are able to optimize by using the same person's appearance in something else instead of doing the big download when possible.
def _is_person_name_bad(name: repo.UnsetType | str) -> bool:
    assert not isinstance(name, repo.UnsetType)
    return '\n' in name or ' episode' in name.lower()

def _safe_get(obj: typing.Any, key: str, default: typing.Any = None) -> typing.Any:
    # I don't trust cinemagoer's __contains__ because it has given some weird results.
    try:
        val = obj[key]
    except KeyError:
        val = default

    return val
