# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'pyMHF'
copyright = '2025, monkeyman192'
author = 'monkeyman192'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.intersphinx',
    'sphinx.ext.napoleon',
]

templates_path = ['_templates']
exclude_patterns = []
intersphinx_mapping = {'python': ('https://docs.python.org/3', None)}
add_function_parentheses = False

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "pydata_sphinx_theme"
html_static_path = ['_static']
html_theme_options = {
    "secondary_sidebar_items": [],
    "icon_links": [
        {
            "name": "GitHub",
            "url": "https://github.com/monkeyman192/pyMHF",
            "icon": "fa-brands fa-square-github",
            "type": "fontawesome",
        }
    ],
    "back_to_top_button": False,
    "show_nav_level": 0,
    "pygments_light_style": "tango",
    "pygments_dark_style": "monokai"
}
