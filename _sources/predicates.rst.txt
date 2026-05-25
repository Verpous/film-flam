Predicates
=======================

Predicates are the part of your :ref:`filter <Filters>` that actually checks something about a :ref:`findable <Findables>`:

.. code-block:: bash

    # -title is a predicate which checks if movie titles match some regular expression.
    flam find movies -title star.wars

    # -every-movie is a predicate which checks if every movie the people were in passes some subfilter.
    # -release-year is a subfilter, in this case we check if the movie was released not before the year 2000.
    flam find cast -every-movie -release-year +2000

There are :ref:`general predicates <General predicates>` which are valid in any filter,
and there's predicates specific to some findable type, which may only be used in filters for object of that type.

.. tip::
    
    Flam supports implementing :ref:`custom predicates <Implementing a custom predicate>`.

Predicate arguments
--------------------

Most predicates have arguments. Below is a list of some common arguments predicates may have:

ATTRIBUTE
~~~~~~~~~

The name of some attribute:

.. code-block:: bash

    # Find only movies you've personally rated. my-rating is an ATTRIBUTE.
    flam find movies -has my-rating

CMPTO
~~~~~

CmpTo's express a comparison of some attribute's values to a constant, using a comparison operator of your choice.

CmpTo's look like ``<operator><value>``, as in "compare to <value> using <operator>". The <operator> is optional; every attribute has a default operator. For example:

.. code-block:: bash

    # '1980' is a CMPTO. It checks for equality by default.
    flam find movies -release-year 1980

    # Same as above but the operator is explicit. '=1980' is a CMPTO.
    flam find movies -release-year =1980

Below are all supported operators:

    * ``-`` : Less or equal
    * ``+`` : Greater or equal
    * ``=`` : Exactly equal
    * ``.-`` : Strictly less than
    * ``.+`` : Strictly greater than
    * ``~`` : Matches regular expression

CTGM (crew type + group mode)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

CTGMs are a combination of a :ref:`crew type <Crew type>` and a :ref:`group mode <Group mode>`.

CTGMs look like ``<crew type>:<group mode>``. The <group mode> is optional; every crew type has a default group mode. For example:

.. code-block:: bash

    # Find movies that Brad Pitt acted in. 'cast' is a CTGM.
    flam find movies -any-role cast -name brad.pitt

    # Same as above. Castmembers are separate by default.
    flam find movies -any-role cast:separate -name brad.pitt

    # Find the writer duo of Peter Jackson and Frash Walsh. 'writer:group' is a CTGM.
    flam find movies -any-role writer:group [ -name peter.jackson -name fran.walsh ]

SUBFILTER
~~~~~~~~~

Some predicates accept an argument which is itself an entire filter. **If the subfilter is made up of more than one predicate it must be parenthesized**:

.. code-block:: bash

    # Find movies where every actor has an "e" in their name. '-name e' is a subfilter.
    flam find movies -every-role cast -name e

    # Find people who were in movies released between 1939 and 1945.
    # The subfilter is complex so it must be parenthesized.
    flam find people -any-movie [ -release-year +1939 -release-year -1945 ]

LISTDEF
~~~~~~~

Reference to some other movie list. See :ref:`Listdefs`.

``...`` : List arguments
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Some predicates are documented like:

.. code-block:: text
    
    -in-list LISTDEF...

The ``...`` means that it accepts a variable number of LISTDEF arguments. **If you want to pass more than one, you'll have to parenthesize it**:

.. code-block:: bash

    # Only one LISTDEF, no need to parenthesize.
    flam find movies -in-list cool-movies

    # Multiple LISTDEFs, must parenthesize.
    flam find movies -in-list [ cool-movies chill-movies ]

List of builtin predicates
---------------------------

Attribute predicates
~~~~~~~~~~~~~~~~~~~~

Every :ref:`attribute <List of builtin attributes>` in flam can also be used as a predicate to compare the attribute to a value. They look like ``-<attribute> CMPTO``:

.. code-block:: bash

    # Check if the 'title' attribute matches a regular expression.
    flam find movies -title lord.of.the.rings

    # Check if the 'height' attribute is at least 180cm.
    flam find people -height +180

.. note::
    
    If an attribute returns a list, this will actually check if **any** element in the list matches this value.

General predicates
~~~~~~~~~~~~~~~~~~

These predicates don't have a specific findable type. They may be used in any filter of any type.

.. builtin-predicates:: general

Movie predicates
~~~~~~~~~~~~~~~~

.. builtin-predicates:: movies

People predicates
~~~~~~~~~~~~~~~~~

.. builtin-predicates:: people

Role predicates
~~~~~~~~~~~~~~~

There are currently no role-specific builtin predicates, but **all movie and people predicates are also valid role predicates!**

.. builtin-predicates:: roles
