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

import logging
import logging.handlers
import os
import sys
import types
import enum
import colorama
import typing

# TODO: Hate this enum. Why did I add it?
class FlamEnv(enum.StrEnum):
    DEBUG               = 'FLAM_DEBUG'
    LOG2CONSOLE         = 'FLAM_LOG2CONSOLE'
    CTX_DIR             = 'FLAM_DIR'
    DOWNLOADS_DIR       = 'FLAM_DOWNLOADS'
    BROWSER             = 'FLAM_BROWSER'
    BROWSER_PROFILE     = 'FLAM_BROWSER_PROFILE'
    LOGLEVEL            = 'FLAM_LOGLEVEL'

    @property
    def is_defined(self) -> bool:
        return self in os.environ

    @property
    def is_truthy(self) -> bool:
        val = self.get_or_default()
        return val != '' and val != '0'

    def get_or_default(self, default: str = '') -> str:
        return os.environ.get(self, default)

def is_debug() -> bool:
    return FlamEnv.DEBUG.is_truthy

def get_log_file_path() -> str:
    DIRNAME = 'film_flam'
    FILENAME = 'output.log'

    if sys.platform.startswith('win'):
        return os.path.join(os.environ['LOCALAPPDATA'], DIRNAME, FILENAME)

    if sys.platform.startswith('linux'):
        return os.path.join(os.path.expanduser('~'), '.local', 'state', DIRNAME, FILENAME)

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
    formatter = logging.Formatter(
        '%(asctime)s [%(levelcolor)s%(levelname)-8s%(resetcolor)s] [%(scriptName)s:%(processName)s:%(process)d:%(thread)d] %(filename)s:%(funcName)s:%(lineno)d: %(message)s')

    logs_path = get_log_file_path()
    os.makedirs(os.path.dirname(logs_path), exist_ok=True)

    # TODO: This isn't good for multiple processes. Not just because logs may get garbled,
    # but also because we hit an error if file rotation takes place while two processes are using it.
    # Storing logs in the flam dir ain't good neither though,
    # because logger initialization must precede context creation and because of volatile mode.
    # There's an easy solution and a hard solution:
    # Easy: name the file something unique each time. Avoid conflicts but logs will be a bitch to open and read.
    # Hard: log to a SocketHandler and implement server which listens on the socket and writes incoming logs to a file.
    #       The server will be single-instance, probably implement using multiprocessing and make it so only once instance can catch the "lock"
    #       and the others spin until the current master server dies and one of the others takes its place.
    fh = logging.handlers.RotatingFileHandler(logs_path, maxBytes=1 << 24, backupCount=1, encoding='utf-8')
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
    record.levelcolor = _levelcolors[record.levelno]
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

_prev_excepthook = sys.excepthook
sys.excepthook = _log_exception

logger.info(f"Environment variables:\n{'\n    '.join(f'"{k}": \t"{v}"' for k, v in os.environ.items())}")
