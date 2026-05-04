Findables
=======================

It's good to understand the "findable" objects in flam - objects that can be found in a movie list. There are three findable types: **movies**, **people**, or **roles**.

Findable objects have many **attributes**. For example, 'title' is a movie attribute, and 'birthday' is a people's attribute.
Click :ref:`here <Attributes>` to read more about attributes and see a list of all builtin attributes.

Movies
------

Movies are exactly what you think - movies. You can browse all the movies in your list:

.. code-block:: bash

    flam find movies

People
------

In the simplest case, you can find all the people in any of the movies in the list.
But people can also be confined to a specific **crew type** (e.g. director, cast, etc.), and they can also be **grouped** by collaborators.

Formally, when finding people, each object is a list of people (could be more than 1) + a crew type + a group mode.

Crew type
~~~~~~~~~

Flam supports the following crew types:

    cast, stuntcast, director, writer, producer, composer, cinematographer, editor, any

The same person can have different properties when presented as different crew types.
For example, Quentin Tarantino will have a different 'num-movies' attribute as a director than as a cast member.

The 'any' crew type is special - it means you don't care about the crew type, you just want to find the people who were in the movies regardless of what they did in those movies.

Group mode
~~~~~~~~~~

Grouping lets you turn collaborators into a single entity - when you search for directors, you might want to see the Coen brothers as a single director.

People objects are always attached to a group mode: 'separate' or 'group'.

When separate, each returned object represents a single person.

When grouped, flam will find people who've collaborated on movies together and return them as a single object.

Every crew type has a default group mode that makes sense for it. Directors are grouped by default, actors are separate. This means that if you:

.. code-block:: bash

    flam find director-people

The Coen brothers will be shown as a single entry.

Roles
-----

A role is an appearance of some people in some movie. Think "Cristoph Waltz as a castmember in Inglorious Basterds".
So when searching for roles, you will see an entry per people per movie.

Roles also have a crew type and a group mode like people do.

Since they combine a people and a movie, **roles support any movie attribute, people attribute, and also their own role attributes**.

.. code-block:: bash

    # Browse directors and also the movies they directed from the list.
    flam find director

