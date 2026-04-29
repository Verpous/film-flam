# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import sphinx
import flam
import flam.attrutils as attrutils
import docutils
import docutils.parsers.rst
import docutils.statemachine

logger = sphinx.util.logging.getLogger(__name__)

project = 'FilmFlam'
copyright = '2026, Aviv Edery'
author = 'Aviv Edery'
version = flam.__version__
release = flam.__version__

extensions = [
    # We use automodule a lot.
    'sphinx.ext.autodoc',

    # We use this for copying the flam --help outputs to the documentation - pip install sphinxcontrib-programoutput.
    'sphinxcontrib.programoutput',

    # Creates a .nojekyll file as part of html build so that GitHub pages will work as a static html host.
    "sphinx.ext.githubpages",
]

# pip install sphinx-rtd-theme
html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']

rst_prolog = f"""
.. |project| replace:: {project}
"""

templates_path = ['_templates']
exclude_patterns = []

# This makes it so type hints are both in the function signature and in the docstring.
autodoc_typehints = 'both'

# Sort members according to the order they show up in the source code. It's the easiest way to generically bundle members that are related.
autodoc_member_order = 'bysource'

# If for example I have FlamContext.__init__'s flam_dir have a default value of DEFAULT_FLAM_DIR, this will show it exactly as that instead of turning it into a literal value.
autodoc_preserve_defaults = True

# These options get passed to all our automodules.
# NOTE: another annoying sphinx issue, in some cases it joins multiple properties on a single line in the browser. No way to fix that without digging into custom CSS, which, fuck that.
autodoc_default_options = {
    # Don't document recursively, because we actually have automodule per src file. But do document everything in the file that is public.
    'members': True,
    
    # NOTE: Even with undoc-members, undocumented global variables aren't shown. This is an ancient issue the Sphinx idiots still haven't fixed: https://github.com/sphinx-doc/sphinx/issues/1063.
    'undoc-members': True,

    # NOTE: I wanted to have inherited-members=True actually but that floods the docs with members we don't need inherited from like, enum.Enum or something.
    # What I really want is to only show members inherited from a class that is also defined inside flam, but I tried fiddling with it for a while and it's too complicated.
    # What we get now is that inherited members aren't shown, unless the inheriting class overrides them, which is significant especially for abstract classes and kind of sucks.
    'inherited-members': False,

    # Some dunders are not default and we want to show it if we support them.
    'special-members': ','.join([
        '__iter__',
        '__lt__',
        '__gt__',
        '__enter__',
        '__exit__',
        '__getitem__',
        '__contains__',
        '__call__',
        '__init_subclass__',
    ]),
    
    'exclude-members': ','.join([
        # Enums have __new__ and we don't want to show it.
        '__new__',
    ]),
}

# This helps us find places where like, a public function takes an argument with a private type.
# It works like shit though so we have to manually ignore some cases, namely it has trouble with generics.
nitpicky = True
nitpick_ignore = [
    ('py:class', 'T'),
    ('py:class', 'TElem'),
    ('py:class', 'TKey'),
    ('py:class', 'TRet'),
    ('py:class', 'types.TracebackType'),
    ('py:class', 'types.ModuleType'),
    ('py:class', 're.Pattern'),
    ('py:class', 'datetime.date'),
    ('py:class', 'flam._attr.SupportsRichComparison'),
]

# Because we use automodule per src file and not once for all of flam (long story), without this all the members will be listed as coming from flam._file.member.
# I tried a LOT to make it work so that they show up under flam.member but nothing works, so instead we'll omit the module name entirely.
# NOTE: in some places the full module name still shows (ex: RegistriesOf.get). I don't know why, but we'll let it slide.
add_module_names = False 

# Some classes are part of the public interface but supposed to be constructed internally, So we separate the __init__ from the main class signature,
# and we have this ability to mark classes with __no_init_doc__ which makes their __init__ not be documented.
# For some reason :meta private: doesn't work on __init__ functions, so this is really needed.
autodoc_class_signature = 'separated'

def skip_private_inits(app, what, name, obj, skip, options):
    if name != '__init__':
        return None

    parent = getattr(obj, '__qualname__', '')

    if '.' in parent:
        cls_name = parent.split('.')[0]
        module = getattr(obj, '__module__', None)

        try:
            mod = __import__(module, fromlist=[cls_name])
            cls = getattr(mod, cls_name, None)
        except Exception:
            cls = None

        if cls and getattr(cls, '__no_init_doc__', False):
            return True

    return None

# Warn about undocumented members.
def warn_undocumented(app, what, name, obj, options, lines):
    if obj.__doc__ is None:
        logger.warning(f"Missing docstring for: {name}")

def parse_rst(directive, rst):
    container = docutils.nodes.container()
    lines = docutils.statemachine.StringList(rst.splitlines())
    directive.state.nested_parse(lines, directive.content_offset, container)
    return container.children    

class BuiltinAttributesDirective(docutils.parsers.rst.Directive):
    required_arguments = 1
    optional_arguments = 0

    def run(self):
        rst = ''
        findable_type = flam.FindableType(self.arguments[0])

        for attr_name in flam._reg._builtins._attributes:
            attr = flam._reg._builtins._attributes[attr_name]

            # Skip attributes we reached by an alias.
            if attr_name != attr.qualified_name:
                continue

            # Skip attributes which belong to a different findable type.
            if attr.findable_type != findable_type:
                continue

            if isinstance(attr, attrutils.ArrayLengthAttribute | attrutils.StringLengthAttribute | attrutils.SumAttribute | attrutils.AverageAttribute):
                continue

            if attr.__doc__ is None:
                logger.warning(f"Missing docstring for attribute: {attr_name}")

            # A little hacky but for every attribute we collect a list of all variants it supports.
            variants = []

            if flam.compose_qualified_attr_or_pred_name(attr.findable_type, f'len-{attr.name_without_type}') in flam._reg._builtins._attributes:
                variants.append('len')

            if flam.compose_qualified_attr_or_pred_name(attr.findable_type, f'num-{attr.name_without_type}') in flam._reg._builtins._attributes:
                variants.append('num')

            if attr.findable_type != flam.FindableType.ROLES:
                flipped = attrutils.AverageAttribute._flip_findable_type(attr.findable_type)

                # Don't check for avg-as or sum-as. If it supports avg / sum that's enough.
                if flam.compose_qualified_attr_or_pred_name(flipped, f'avg-{attr.name_without_type}') in flam._reg._builtins._attributes:
                    variants.append('avg')

                if flam.compose_qualified_attr_or_pred_name(flipped, f'sum-{attr.name_without_type}') in flam._reg._builtins._attributes:
                    variants.append('sum')

            # NOTE: Attributes don't show up in the sidebar. I wanted them to, but the only way to achieve it is to use section headers (i.e. ~~~~~),
            # and because sphinx is fucking dumb, section headers are not supported in directives. So we would have to generate the entire .rst file instead if we want that..
            rst += f"""
**{attr.name_without_type}** - {attr.__doc__}

    :variants: {', '.join(variants)}
    :aliases: {', '.join(attr.aliases_without_type)}
    :ascending: {attr.is_ascending}
    :default op: '{attr.default_op}'
"""

        return parse_rst(self, rst)

class BuiltinPredicatesDirective(docutils.parsers.rst.Directive):
    required_arguments = 1
    optional_arguments = 0

    def run(self):
        rst = ''
        findable_type = flam.FindableType(self.arguments[0]) if self.arguments[0] != 'general' else None

        for pred_name in flam._reg._builtins._predicates:
            pred = flam._reg._builtins._predicates[pred_name]

            # Skip predicates we reached by an alias.
            if pred_name != pred.qualified_name:
                continue

            # Skip predicates which belong to a different findable type.
            if pred.findable_type != findable_type:
                continue

            # Skip AttributePredicates.
            if hasattr(pred, 'ATTRIBUTE'):
                continue

            if pred.__doc__ is None:
                logger.warning(f"Missing docstring for predicate: {pred_name}")

            if findable_type is None:
                name_without_type = pred_name
            else:
                _, name_without_type = flam._reg.decompose_qualified_attr_or_pred_name(pred_name)
            
            # NOTE: Because sphinx is fucking dumb, the entire first line gets bolded instead of just the predicate name.
            # This could be fixed by adding an extra line before the description but that also adds more line spacing I don't want so we'll just live with this.
            # Predicates are expected to format their docstring with the predicate args in the first line and the description in the next line, which should be indented.
            rst += f"""
**-{name_without_type}** {pred.__doc__}
"""

        return parse_rst(self, rst)

class BuiltinFetchersDirective(docutils.parsers.rst.Directive):
    def run(self):
        rst = ''

        for fetcher_name in flam._reg._builtins._fetchers:
            fetcher = flam._reg._builtins._fetchers[fetcher_name]

            # Skip fetchers we reached by an alias.
            if fetcher_name != fetcher.qualified_name:
                continue

            if fetcher.__doc__ is None:
                logger.warning(f"Missing docstring for fetcher: {fetcher_name}")

            rst += f"""
**{fetcher_name}**\\={fetcher.__doc__}
"""

        return parse_rst(self, rst)

def setup(app):
    app.connect('autodoc-skip-member', skip_private_inits)
    # app.connect('autodoc-process-docstring', warn_undocumented) # NOTE: this is disabled because it raises a bunch of false alarms not worth fixing.
    app.add_directive('builtin-attributes', BuiltinAttributesDirective)
    app.add_directive('builtin-predicates', BuiltinPredicatesDirective)
    app.add_directive('builtin-fetchers', BuiltinFetchersDirective)
    