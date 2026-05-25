#! python

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

import sys
import flam
import msgspec

# This is just a little utility for changing the encoding of msgspec files. Invoke it like:
# reencode.py MovieListFile msgpack ~/.film_flam/movie_lists/*.json
type_ = getattr(flam, sys.argv[1])
new_encoding = sys.argv[2]

for path in sys.argv[3:]:
    current_encoding = path.split('.')[-1]

    with open(path, 'rb') as f:
        contents = f.read()

    decodelib = getattr(msgspec, current_encoding)
    encodelib = getattr(msgspec, new_encoding)

    obj = decodelib.decode(contents, type=type_)
    encoded = encodelib.encode(obj)

    with open(path.replace(current_encoding, new_encoding), 'wb') as f:
        f.write(encoded)
