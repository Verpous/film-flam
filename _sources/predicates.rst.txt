Predicates
=======================

TODO

List of builtin predicates
---------------------------

General predicates
~~~~~~~~~~~~~~~~~~

.. builtin-predicates:: general

Attribute predicates
~~~~~~~~~~~~~~~~~~~~

Every attribute in flam can also be used as a predicate to compare the attribute to a value. They have the form ``-<attribute> CMPTO``. For example:

.. code-block:: text

    -title lord.of.the.rings    (Check if movie title matches a regular expression)
    -height +180                (Check if the person is taller than 180cm)

Movie predicates
~~~~~~~~~~~~~~~~

.. builtin-predicates:: movies

People predicates
~~~~~~~~~~~~~~~~~

.. builtin-predicates:: people

Role predicates
~~~~~~~~~~~~~~~

In addition to the below, all movie, people predicates are also valid role predicates.

.. builtin-predicates:: roles


Implementing a custom predicate
--------------------------------
