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

html_theme = "sphinx_rtd_theme"
# html_theme = "sphinx_pdj_theme"
# html_theme = "sphinx_book_theme"
# html_theme = "python_docs_theme"
# import better
# html_theme = "better"
# html_theme_path = [better.better_theme_path]
# html_theme_options = {"navigation_depth": 3}
# html_theme_path = [sphinx_pdj_theme.get_html_theme_path()]
html_logo = "images/WebLogo_RED.png"
# html_logo = "images/square_logo.png"
html_static_path = ["_static"]
html_theme_options = {
    "analytics_anonymize_ip": False,
    "logo_only": True,
    "display_version": True,
    "prev_next_buttons_location": "bottom",
    "style_external_links": False,
    "vcs_pageview_mode": "",
    "style_nav_header_background": "#343131",
    # Toc options
    "collapse_navigation": True,
    "sticky_navigation": True,
    "navigation_depth": 4,
    "includehidden": True,
    "titles_only": False,
}
