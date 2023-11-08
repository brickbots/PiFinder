# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "PiFinder"
copyright = "2023, Richard Wolff-Jacobson"
author = "Richard Wolff-Jacobson"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

templates_path = ["_templates"]
exclude_patterns = []

extensions = [
    "sphinx.ext.autosectionlabel",
    "sphinx_rtd_theme",
]

autosectionlabel_prefix_document = True

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
html_logo = "images/WebLogo_RED.png"
# html_logo = "images/square_logo.png"
html_static_path = ["_static"]
html_theme_options = {
    "style_nav_header_background": "#343131",
    "logo_only": True,
    "prev_next_buttons_location": "None",
}
