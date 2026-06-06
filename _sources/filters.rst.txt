Filters
=======================

Flam lets you easily apply a filter when you search for :ref:`findables <Findables>`. Filters can be very simple:

.. code-block:: bash

    # Filter directors to only ones named tarantino.
    flam find director -name tarantino

Or more complex:

.. code-block:: bash

    # Find only movies released since 1980 and which contain at least one actor who was in either Lord of the Rings or Star Wars.
    flam find movies -release-year +1980 -any-role cast [ -movies lord.of.the.rings -o -movies star.wars ]


Filters are essentially a combination of **predicates**. Each predicate checks one thing about the findable object.
By default predicates are joined together using AND (i.e., ``-pred1 -pred2`` means "pred1 AND pred2"), but filters support all the standard features you'd expect:

* AND: &, -a, -and
    
    This is the default
* OR: \|, -o, -or

    ``-pred1 -or -pred2``
* NOT: !, -n, -not
    
    ``-not -pred``
* Parentheses: [ ], ( ), -lparen -rparen
    
    Control the order of operations: ``[ -pred1 -pred2 ] -or [ -pred3 -pred4 ]``

.. tip::

    Click :ref:`here <Predicates>` to read more about predicates and see a list of all builtin predicates.

Formal syntax
-------------

Below is the formal syntax for filters. Note that filters are case-sensitive!

.. code-block:: text

    FILTER    := PIPELINE | <epsilon>
    PIPELINE  := SINGLE JOINABLE*
    SINGLE    := NEGATIVE | POSITIVE
    POSITIVE  := PREDICATE | [ PIPELINE ]
    NEGATIVE  := NOT POSITIVE
    JOINABLE  := CONJOINED | DISJOINED | SINGLE
    CONJOINED := AND SINGLE
    DISJOINED := OR SINGLE
    PREDICATE := -<name> <arg1> <arg2>...

    OR        := -o | -or  | `|`
    AND       := -a | -and | &
    NOT       := -n | -not | !
    [         := [  | (    | -lparen
    ]         := ]  | )    | -rparen
