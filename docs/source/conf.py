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

extensions = []

templates_path = ["_templates"]
exclude_patterns = []

# extensions = [
#    "sphinx_rtd_theme",
# ]

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

# html_theme = "sphinx_rtd_theme"
html_theme = "sphinx_pdj_theme"
# html_theme_options = {"navigation_depth": 3}
# html_theme_path = [sphinx_pdj_theme.get_html_theme_path()]
html_logo = "images/WebLogo_RED.png"
html_static_path = ["_static"]
html_theme_options = {
    "home_link": "hide",
    "prefers-color-scheme": "light",
}
