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

import logging
import logging.handlers
import os
import sys
import types
import enum
import colorama
import typing
import concurrent_log_handler

# Very on the fence about this enum. I guess it's kind of nice but also I kind of don't like it. Whatever. It stays.
class FlamEnv(enum.StrEnum):
    """
    Collection of environment variables used by flam.
    """

    DEBUG               = 'FLAM_DEBUG'
    """
    If :py:attr:`is_truthy`, flam will operate in debug mode. We're more strict with exceptions in debug mode.
    """

    LOG2CONSOLE         = 'FLAM_LOG2CONSOLE'
    """
    If :py:attr:`is_truthy`, logs will be printed not just to their log file but also to the console.
    """

    CTX_DIR             = 'FLAM_DIR'
    """
    Overrides the default path used to store files.
    """

    DOWNLOADS_DIR       = 'FLAM_DOWNLOADS'
    """
    Overrides the default path searched for files downloaded from the browser when fetching from IMDb.
    """

    BROWSER             = 'FLAM_BROWSER'
    """
    Manually decide which browser to use to download CSVs from IMDb: 'chrome', 'edge', or 'firefox'.
    """

    BROWSER_PROFILE     = 'FLAM_BROWSER_PROFILE'
    """
    Path to a browser profile to open the browser with when downloading CSVs from IMDb.
    
    This is only needed if your list is set to private so a profile is needed where you are expected to be already logged in.
    """

    LOGLEVEL            = 'FLAM_LOGLEVEL'
    """
    Suppresses logs below this level. See the `python docs on logging levels <https://docs.python.org/3/library/logging.html#levels>`__.
    """

    @property
    def is_defined(self) -> bool:
        """
        True if this environment variable is defined.
        """
        return self in os.environ

    @property
    def is_truthy(self) -> bool:
        """
        True if this environment variable is defined, not empty, and not '0'.
        """
        val = self.get_or_default()
        return val != '' and val != '0'

    def get_or_default(self, default: str = '') -> str:
        """
        Return the value of this environment variable, or some default if it is not defined.
        """
        return os.environ.get(self, default)

def is_debug() -> bool:
    """
    True if flam is in debug mode.
    """
    return FlamEnv.DEBUG.is_truthy

def get_log_file_path() -> str:
    """
    Returns the path where flam stores its logs:

    * Windows: %LOCALAPPDATA%/film_flam/output.log
    * Linux: ~/.local/state/film_flam/output.log
    * macOS: ~/Library/Logs/film_flam/output.log
    * On unidentified platforms, uses the current directory (./output.log)
    """
    DIRNAME = 'film_flam'
    FILENAME = 'output.log'

    if sys.platform.startswith('win'):
        return os.path.join(os.environ['LOCALAPPDATA'], DIRNAME, FILENAME)

    if sys.platform.startswith('linux'):
        return os.path.join(os.path.expanduser('~'), '.local', 'state', DIRNAME, FILENAME)

    # Darwin is mac.
    if sys.platform.startswith('darwin'):
        return os.path.join(os.path.expanduser('~'), 'Library', 'Logs', DIRNAME, FILENAME)
        
    # Use cwd for unknown platforms.
    return FILENAME

def _make_logger() -> logging.Logger:
    # Ignore exceptions except in debug mode. I hate using logging because it's global but there's no nice way to enable this per-logger or per-handler.
    logging.raiseExceptions = is_debug()

    # Underscore to not conflict with the global.
    logger_ = logging.Logger('film_flam')
    logger_.setLevel(getattr(logging, FlamEnv.LOGLEVEL.get_or_default('DEBUG').upper()))

    # Timestamp is first because when catenating log with backups it's easy to sort.
    # Example log: 2026-04-01 15:40:11,373 [INFO    ] [flam.exe:MainProcess:17996:21432] __main__.py:execute:618: Printing the table
    formatter = logging.Formatter(
        '%(asctime)s [%(levelcolor)s%(levelname)-8s%(resetcolor)s] [%(scriptName)s:%(processName)s:%(process)d:%(thread)d] %(filename)s:%(funcName)s:%(lineno)d: %(message)s')

    logs_path = get_log_file_path()
    os.makedirs(os.path.dirname(logs_path), exist_ok=True)

    # I hate to bring in a dependency, but we need ConcurrentRotatingFileHandler. It solves two problems:
    # 1. Prevents logs from being garbled if multiple flam instances are running in parallel. In the future if we support context parallelism, this will be especially important.
    # 2. On windows if the logs need to get rotated while they are opened in another process (say tail -f for following the logs), you get a crash.
    fh = concurrent_log_handler.ConcurrentRotatingFileHandler(logs_path, maxBytes=1 << 24, backupCount=1, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger_.addHandler(fh)

    if FlamEnv.LOG2CONSOLE.is_truthy:
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(formatter)
        logger_.addHandler(ch)

    return logger_

# Support for colored logging and logging the script name. I prefer this approach to a custom formatter.
def _flam_record_factory(*args: typing.Any, **kwargs: typing.Any) -> logging.LogRecord:
    record = _prev_record_factory(*args, **kwargs)
    record.resetcolor = colorama.Style.RESET_ALL
    record.levelcolor = _levelcolors.get(record.levelno, '') # Sphinx hits an error if we don't have a default.
    record.scriptName = _script_name
    return record

# Handler for uncaught exceptions.
def _log_exception(exc_type: type[BaseException], exc_value: BaseException, exc_traceback: None | types.TracebackType) -> None:
    logger.critical('Uncaught exception!', exc_info=(exc_type, exc_value, exc_traceback))
    _prev_excepthook(exc_type, exc_value, exc_traceback)

_script_name = os.path.basename(sys.argv[0]) if len(sys.argv) > 0 else 'n/a'
_levelcolors = {
    logging.DEBUG:      '',
    logging.INFO:       '',
    logging.WARNING:    colorama.Fore.YELLOW,
    logging.ERROR:      colorama.Style.BRIGHT + colorama.Fore.RED,
    logging.CRITICAL:   colorama.Fore.RED,
}

_prev_record_factory = logging.getLogRecordFactory()
logging.setLogRecordFactory(_flam_record_factory)

logger = _make_logger()
"""
The logger flam uses for all its logs. It is thread-safe and multiprocess-safe, and you may also use it.

:meta hide-value:
"""

_prev_excepthook = sys.excepthook
sys.excepthook = _log_exception

# As a rule, flam logs should start with a capital letter and not end with a period!
# NOTE: I am aware this log could be a problem because sometimes users store secrets in their env vars. I think I'll keep it anyway.
logger.info(f"Environment variables:\n    {'\n    '.join(f'"{k}": \t"{v}"' for k, v in os.environ.items())}")
