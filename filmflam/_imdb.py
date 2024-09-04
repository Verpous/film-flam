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
import typing
import dataclasses
import datetime
import multiprocessing
import queue
import time
import webbrowser
import traceback
import abc
import atexit

import filmflam.infra as ff
import filmflam._utils as utils
import filmflam.exceptions as exceptions

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import ElementClickInterceptedException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.chromium.options import ChromiumOptions

_UID_TYPE = 'imdb'

_REQUEST_QUIT = 'quit'

_AUTO = 'auto'
_CHROME = 'chrome'
_EDGE = 'edge'
_FIREFOX = 'firefox'

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

@ff._register_builtin
class SeleniumListFetcher(ff.ListFetcher, fetcher_type='imdb-id', uid_type=_UID_TYPE):
    exports_server: None | multiprocessing.Process = None
    requests_queue: multiprocessing.Queue = multiprocessing.Queue()

    def fetch_into_file(self, list_file: ff.ListFile) -> None:
        self.spin_server_if_needed()

        NUM_RETRIES = 1 # TODO: if we never experience timeouts, get rid of this.
        CSV_DOWNLOAD_TIMEOUT_SECS = 40
        DOWNLOADS_DIR = os.environ.get('FLAM_DOWNLOADS', os.path.join(os.path.expanduser('~'), 'Downloads'))

        if not os.path.isdir(DOWNLOADS_DIR):
            raise exceptions.InputError(f"Invalid FLAM_DOWNLOADS: '{DOWNLOADS_DIR}': not a directory.")

        # We do retries because of a particularly horrible issue that makes the download sometimes fail.
        for i in range(NUM_RETRIES):
            try:
                latest_csv = utils.download_file_using_browser(
                    download_cmd=lambda: SeleniumListFetcher.requests_queue.put_nowait(self.concrete_listdef.address),
                    file_extension='csv',
                    downloads_dir=DOWNLOADS_DIR,
                    timeout_secs=CSV_DOWNLOAD_TIMEOUT_SECS)
            except TimeoutError as e:
                # TODO: Don't fail terminally, inform the user of the error but carry on to the next list? Not sure, since a rerun to fix things really hurts now.
                if i == NUM_RETRIES - 1:
                    raise exceptions.InputError(f"Timed out trying to download LISTDEF '{self.concrete_listdef}' from IMDb. Are you sure the address is valid?") from e

        # CSV documentation says to use newline=''.
        with open(latest_csv, 'r', newline='') as movies_csv_file:
            movies_csv = _read_csv(movies_csv_file)

        os.remove(latest_csv)
        _fetch_movies_in_csv(movies_csv, list_file)

    @classmethod
    def spin_server_if_needed(cls) -> None:
        if cls.exports_server is not None and cls.exports_server.is_alive():
            return

        BROWSER = os.environ.get('FLAM_BROWSER', _AUTO)
        PROFILE = os.environ.get('FLAM_BROWSER_PROFILE', '')

        # On re-spins create a new queue. The first go-around it's already instantiated to give mypy an easier time.
        if cls.exports_server is not None:
            cls.requests_queue = multiprocessing.Queue()

        # TODO: Consider a mechanism that blocks until the server informs that the browser is running and it's ready to take requests.
        # TODO: If python doesn't cleanly terminate the server, we'll need to send it a quit message ourselves.
        cls.exports_server = multiprocessing.Process(target=_export_lists_handler, args=(cls.requests_queue, BROWSER, PROFILE), daemon=True)
        cls.exports_server.start()
    
# Python devs made a dumbass decision to terminate multiprocesses in a way that doesn't run exit handlers,
# and we must kill it cleanly to kill the browser.
# NOTE: I tried instead to make the child process terminate itself when it detects that it's orphaned,
# but multiprocess doesn't actually let you orphan children, because fuck you that's why.
@atexit.register
def _exports_server_cleanup() -> None:
    if SeleniumListFetcher.exports_server is not None and SeleniumListFetcher.exports_server.is_alive():
        SeleniumListFetcher.requests_queue.put_nowait(_REQUEST_QUIT)

        # Join is needed because the subprocess is a daemon, which means it dies when we die,
        # and we don't want it to die before it handles this request.
        SeleniumListFetcher.exports_server.join()

@ff._register_builtin
class CsvListFetcher(ff.ListFetcher, fetcher_type='imdb-csv', uid_type=_UID_TYPE):
    def fetch_into_file(self, list_file: ff.ListFile) -> None:
        try:
            movies_csv_file = open(self.concrete_listdef.address, 'r', newline='')
        except FileNotFoundError as e:
            raise exceptions.InputError(f"Invalid LISTDEF {self.concrete_listdef}: no such file.") from e

        with movies_csv_file:
            movies_csv = _read_csv(movies_csv_file)

        _fetch_movies_in_csv(movies_csv, list_file)

def _get_csv_url(list_id: str) -> str:
    return f'https://www.imdb.com/list/ls{list_id}/export?ref_=ttls_exp'

def _read_csv(movies_csv_file: typing.Iterable[str]) -> list[_CsvRow]:
    reader = csv.reader(movies_csv_file)

    # Drop the titles row. If the CSV format doesn't match up we should fail on creating one of the rows.
    movies_csv = [_CsvRow(*row) for row in reader][1:]
    
    # The first 2 characters of the uid are a prefix that we wish to discard.
    for movie in movies_csv:
        movie.uid = movie.uid[2:]

    return movies_csv

def _fetch_movies_in_csv(movies_csv: list[_CsvRow], list_file: ff.ListFile) -> None:
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

        # If any of the conversions fail we simply propagate the error.
        movie_lf.list_index         = int(movie_csv.list_index)
        movie_lf.description        = movie_csv.description
        movie_lf.rating             = float(movie_csv.rating)
        movie_lf.runtime_minutes    = int(movie_csv.runtime_minutes)
        movie_lf.genres             = movie_csv.genres.split(', ')
        movie_lf.votes              = int(movie_csv.votes)
        movie_lf.myrating           = float(movie_csv.myrating) if (movie_csv.myrating is not None and movie_csv.myrating != '') else None
        movie_lf.watch_date         = _format_date_from_csv(movie_csv.watch_date)
        movie_lf.release_date       = _format_date_from_csv(movie_csv.release_date)

    if imdb_error is not None:
        raise exceptions.FetchInterrupt(str(imdb_error))

def _fetch_movie(movie_csv: _CsvRow, list_file: ff.ListFile, ia: imdb.Cinemagoer) -> None:
    NUM_RETRIES = 5
    info_to_fetch = (*imdb.Movie.Movie.default_info, 'critic reviews', 'full credits')

    for i in range(NUM_RETRIES):
        try:
            movie_imdb = ia.get_movie(movie_csv.uid, info=info_to_fetch)
            break
        except imdb.IMDbError:
            if i == NUM_RETRIES - 1:
                raise

    movie_lf = ff.ListFileMovie.create(uid=movie_csv.uid)

    # Prefer to get the title from Cinemagoer because they have better titles for foreign language films, but it's good to have a fallback (not that we ever need it).
    movie_lf.title = _safe_get(movie_imdb, 'title', default=movie_csv.title) 
    movie_lf.metascore = _safe_get(movie_imdb, 'metascore')

    for crew_type in ff.CrewType:
        # I generally tried to choose the CrewType values to match imdb's, but this one goddamn type has a space in it and I don't like that.
        imdb_crew_type = crew_type.value if crew_type != ff.CrewType.STUNTCAST else 'stunt performer'

        # Building this list as a dictionary solves two problems:
        # 1. Sometimes you get empty people, so those are discarded.
        # 2. Sometimes you get the same person twice. Also discarded.
        crew_imdb_by_uid = {p.getID(): p for p in _safe_get(movie_imdb, imdb_crew_type, default=[]) if p}

        movie_lf.crew[imdb_crew_type] = ff.ListFileCrew.create(
            crew_type=imdb_crew_type,
            roles_by_uid={r.person_uid: r for r in _build_roles(crew_imdb_by_uid)})
        _update_people_by_uid(list_file.people_by_uid, ((p.uid, p) for p in _build_people(crew_imdb_by_uid)))

    list_file.movies_by_uid[movie_csv.uid] = movie_lf

def _refetch_person(person_lf: ff.ListFilePerson, ia: imdb.Cinemagoer) -> None:
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

def _build_roles(crew_imdb_by_uid: dict[str, imdb.Person.Person]) -> typing.Iterable[ff.ListFileRole]:
    for person_imdb in crew_imdb_by_uid.values():
        role_lf = ff.ListFileRole.create(
            person_uid=person_imdb.getID(),
            characters=[c for c in _build_characters(person_imdb.currentRole) if c is not None])

        yield role_lf

def _build_people(crew_imdb_by_uid: dict[str, imdb.Person.Person]) -> typing.Iterable[ff.ListFilePerson]:
    for person_imdb in crew_imdb_by_uid.values():
        person_lf = ff.ListFilePerson.create(uid=person_imdb.getID())
        person_lf.name = _safe_get(person_imdb, 'name', person_lf.uid)
        yield person_lf

# Because of this deal with bad names, when we merge two people dictionaries we want to keep the person with the good name if there is one.
def _update_people_by_uid(dst_people: dict[str, ff.ListFilePerson], src_people: typing.Iterable[tuple[str, ff.ListFilePerson]]) -> None:
    # NOT src_people.items(). That's the responsibility of the callers.
    dst_people.update((uid, p) for uid, p in src_people if uid not in dst_people or _is_person_name_bad(dst_people[uid].name))

# There seems to be a bug in Cinemagoer, sometimes when you get a person from the cast list of a TV show,
# his name goes something like "2011 Alan Tudyk\n          \n          \n          \n          1 episode".
# We fix this by trying to find people with a name like that and replacing it with the correct name.
# By doing this after everything is downloaded and not when the name was added to the dictionary,
# we are able to optimize by using the same person's appearance in something else instead of doing the big download when possible.
def _is_person_name_bad(name: ff.UnsetType | str) -> bool:
    assert not isinstance(name, ff.UnsetType)
    return '\n' in name or ' episode' in name.lower()

def _safe_get(obj: typing.Any, key: str, default: typing.Any = None) -> typing.Any:
    # I don't trust cinemagoer's __contains__ because it has given some weird results.
    try:
        val = obj[key]
    except KeyError:
        val = default

    return val

def _format_date_from_csv(date: str) -> str:
    # IMDb used to only serve %Y-%m-%d, but now it sometimes serves a partial date.
    for fmt in ('%Y-%m-%d', '%Y-%m', '%Y'):
        try:
            return datetime.datetime.strptime(date, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass

    raise ValueError(f'Invalid date: {date}')

#endregion

#region Selenium server

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

def _get_default_browser() -> str:
    try:
        import winreg
        
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\\Microsoft\\Windows\\Shell\\Associations\\UrlAssociations\\http\\UserChoice") as key:
            browser_id = winreg.QueryValueEx(key, 'ProgId')[0]

        if 'ChromeHTML' in browser_id:
            return _CHROME
        if 'AppXq0fevzme2pys62n3e0fbqa7peapykr8v' in browser_id: # WTF Microsoft.
            return _EDGE
        if 'FirefoxURL' in browser_id:
            return _FIREFOX
    except ModuleNotFoundError:
        # On Windows this is an empty string, thanks webbrowser.
        browser_name = webbrowser.get().name

        for name in (_CHROME, _EDGE, _FIREFOX):
            if name in browser_name:
                return name

    # Default to edge. Sorry linux users.
    return _EDGE

def _do_with_retries(action: typing.Callable[[], typing.Any], num_retries: int = 10, sleep_between_retries: float = 1.0) -> typing.Any: # pylint: disable=inconsistent-return-statements
    for i in range(num_retries):
        try:
            return action()
        except:
            if i == num_retries - 1:
                raise

            time.sleep(sleep_between_retries)

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
    driver.get(f'https://www.imdb.com/list/ls{list_id}')

    # Begin exporting.
    export_button = _do_with_retries(
        lambda: driver.find_element(By.XPATH, "//button[@aria-label='Export']"))
    _do_with_retries(lambda: _click_export_button(driver, export_button))

    # Go to exports page once the popup tells us.
    exports_page_link = _do_with_retries(
        lambda: driver.find_element(By.XPATH, "//a[@aria-label='Open exports page']"))
    _do_with_retries(exports_page_link.click)

    # Hit the download button once the list is ready.
    download_button = _do_with_retries(lambda: _get_download_button(driver))
    _do_with_retries(download_button.click)

# TODO: Selenium errors are ugly and quite possible for users to encounter. We should hide that ugly from users, while not losing it for troubleshooting purposes.
def _export_lists_handler(requests_queue: multiprocessing.Queue, browser_name: str = _AUTO, browser_profile_path: str = '') -> None:
    if browser_name == _AUTO:
        browser_name = _get_default_browser()

    # Match statements suck. Don't try to refactor this.
    controller = (
        _ChromeController() if browser_name == _CHROME else
        _EdgeController() if browser_name == _EDGE else
        _FirefoxController() if browser_name == _FIREFOX else
        None
    )

    assert controller is not None

    # Use empty instead of None as default because it's easier for callers to use.
    # TODO: auto detect the default profile for all browsers?
    if browser_profile_path != '':
        controller.set_profile(browser_profile_path)

    # RATIONALE: we spin a server instead of running this code once per list ID because launching the browser takes time and we don't want to pay that cost multiple times.
    # NOTE: I wanted to minimize the browser window but it causes things to fail.
    with controller.launch() as driver:
        while True:
            # TODO: consider spinning a new browser instance instead?
            assert _is_browser_alive(driver)

            try:
                # We use a timeout so we can periodically check if the browser is still alive.
                request = requests_queue.get(block=True, timeout=1)
            except queue.Empty:
                continue

            if request == _REQUEST_QUIT:
                return

            try:
                _export_list(driver, request)
            except:
                # TODO: Nicer error printing except in debug runs?
                traceback.print_exc()

#endregion
