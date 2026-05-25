Attributes
=======================

Attributes are all the information bits you can know about a :ref:`findable <Findables>` object.
Things like the title of a film, its metascore, the name of a person, his height, etc. are all attributes.

Attributes provide some facilities for using them generically without caring about the specific attribute:

* They let you sort the attribute's values
* They let you convert values to strings
* They let you parse those strings back into values
* Flam generically handles attributes which return lists
* Flam generically handles attributes whose values are missing (i.e. not available in the fetch source)
* There are a few more ways that attributes support generic handling

Each attribute is specific to some findable type, but role attributes support any attribute of movies or people!

.. tip::

    Flam supports implementing :ref:`custom attributes <Implementing a custom attribute>`.

List of builtin attributes
---------------------------

Note that almost every attribute may return ``None`` if the data is not available. As a string, it looks like ``'-'``.

Many attributes below support variants. Here are the variants we support:

len-X
~~~~~

For some attribute X, "len-X" is the length of the attribute as a string.

Ex: ``len-title`` - the length of the movie's title.

num-X
~~~~~

For some attribute X, "num-X" is the number of elements in the attribute if it returns a list. For non-lists, the value is 1.

Ex: ``num-cast`` - the number of cast members in a movie.

avg-X
~~~~~

For some movie attribute X, "avg-X" is a people attribute which returns the average of X across all movies those people were in.

Ex: ``avg-rating`` - the average rating across all movies the person was in.

For a people attribute X, "avg-X" is a movie attribute which returns the average of X for all the people in the movie.

Ex: ``avg-height`` - the average height of everyone in the movie.

avg-X-as-CT
~~~~~~~~~~~

Any attribute which supports :ref:`avg-X` also supports "avg-X-as-CT", where CT is a :ref:`crew type <Crew type>`.

For some movie attribute X, "avg-X-as-CT" is a people attribute which returns the average of X across all movies those people were in as the crew type CT.

Ex: ``avg-rating-as-director`` - the average rating across all movies the person directed.

For a people attribute X, "avg-X-as-CT" is a movie attribute which returns the average of X for all the people in the movie as the crew type CT.

Ex: ``avg-height-as-cast`` - the average height of all actors in the movie.

sum-X
~~~~~

Same as :ref:`avg-X`, but with summation instead of averaging.

sum-X-as-CT
~~~~~~~~~~~

Same as :ref:`avg-X-as-CT`, but with summation instead of averaging.

Movie attributes
~~~~~~~~~~~~~~~~

.. builtin-attributes:: movies

People attributes
~~~~~~~~~~~~~~~~~

.. builtin-attributes:: people

Role attributes
~~~~~~~~~~~~~~~

In addition to the below, **all movie and people attributes are also valid role attributes!**

.. builtin-attributes:: roles
