# reStructuredText conventions (detailed)

Reference for syntax beyond the essentials in SKILL.md. Read the section you
need. Every pattern here is drawn from the existing `docs/source/*.rst` pages —
when in doubt, grep the source for a live example.

## Contents

- [Heading ladder](#heading-ladder)
- [Cross-references](#cross-references)
- [Images](#images)
- [Admonitions](#admonitions)
- [Lists](#lists)
- [Inline markup](#inline-markup)
- [Code and literal blocks](#code-and-literal-blocks)
- [The toctree](#the-toctree)
- [Build settings that affect authoring](#build-settings-that-affect-authoring)

## Heading ladder

Sphinx assigns heading levels by the *order underline characters first appear in
a document*, not by any fixed meaning. So consistency within a page is what
matters. The convention across PiFinder docs:

```
Page Title
==========          (often overlined too: a line of = above and below)

Major Section
-------------

Sub-section
~~~~~~~~~~~~

Sub-sub-section
^^^^^^^^^^^^^^^
```

The underline must be at least as long as the text. Mixing characters for the
same level, or introducing a new character out of order, makes Sphinx silently
renumber the hierarchy — a frequent source of "why is my subsection now a
chapter" confusion.

## Cross-references

`autosectionlabel` is enabled with `autosectionlabel_prefix_document = True`
(see `conf.py`). That means every section heading becomes a referenceable label
of the form `docname:heading`, and the labels are matched case-insensitively —
the project writes them lowercase.

| Target | Syntax |
|--------|--------|
| Whole page | `` :doc:`build_guide` `` |
| Whole page, custom text | `` :doc:`Build Guide <build_guide>` `` |
| Section in another page | `` :ref:`user_guide:settings menu` `` |
| Section, custom text | `` :ref:`final assembly <build_guide:assembly>` `` |
| External URL | `` `PiFinder.io <https://www.pifinder.io/>`_ `` |

Notes:
- `:doc:` paths are relative to `source/` and omit the `.rst` extension.
- For `:ref:`, the part after the colon is the *heading text*, lowercased, with
  its normal spaces. `Settings Menu` → `user_guide:settings menu`.
- A typo'd label produces a build warning ("undefined label") only with `-n`
  (nitpicky) mode — always build with `-n` before handing off.

## Images

```
.. image:: images/user_guide/status_screen.png

.. image:: images/quick_start/pf_front.jpeg
   :width: 45%
.. image:: images/quick_start/pf_rear.jpeg
   :width: 45%
```

- Store screenshots in `images/<page_name>/` next to the page that uses them.
- Two `:width: 45%` images in a row render side by side — used for front/back or
  before/after pairs.
- Paths are relative to the `.rst` file's location in `source/`. A few pages
  reach a shared image with `../../images/...`; match whatever the page already
  does.
- Don't reference a file that doesn't exist — it builds but renders a broken
  image. For not-yet-captured screenshots, use a descriptive placeholder path
  and flag it to the user.

## Admonitions

The manual mostly uses `note`. Others (`warning`, `tip`) are available if a
caution genuinely warrants it.

```
.. note::
   Body text is indented under the directive. Multiple paragraphs are allowed
   as long as they stay at the same indent.

   A second paragraph inside the same note.
```

## Lists

Bulleted:

```
- The **UP** and **DOWN** arrows scroll the current menu
- The **RIGHT** arrow activates the highlighted option
- The **LEFT** arrow goes back
```

Definition-style (term + indented description) appears in settings rundowns:

```
Mount Type
   Alt/Az or EQ. Changes whether Push-To is given in alt/az or RA/Dec.
```

Numbered lists use `1.`, `2.`, … or `#.` for auto-numbering.

## Inline markup

- `**bold**` — hardware keys (**SQUARE**), emphasis on UI labels.
- `*italic*` — light emphasis; used sparingly.
- ``` ``literal`` ``` — file names, code, config values, exact strings.

## Code and literal blocks

For shell or config snippets, use a literal block introduced by `::` or a
`code-block` directive:

```
Run the updater from the command line::

   python -m PiFinder.main -fh

.. code-block:: bash

   sudo systemctl restart pifinder
```

The content must be indented and separated by a blank line.

## The toctree

`index.rst` holds the master toctree. New pages must be listed here or they
become orphans (build warning) and won't appear in navigation:

```
.. toctree::
   :hidden:
   :maxdepth: 2
   :caption: Contents:
   :glob:

   self
   quick_start
   user_guide
   ...
```

Add the new page's filename (no extension) in the position that matches its
place in the reading order.

## Build settings that affect authoring

From `conf.py`:
- `html_theme = "sphinx_rtd_theme"` — the Read the Docs theme. Two `:width: 45%`
  images sit side by side under it; very wide images get scaled to the content
  column.
- `extensions = ["sphinx.ext.autosectionlabel", "sphinx_rtd_theme"]`.
- `autosectionlabel_prefix_document = True` — the reason `:ref:` targets are
  `docname:heading`.

Pinned build deps (`source/requirements.txt`): `Sphinx==7.2.6`,
`sphinx-rtd-theme==1.3.0`.
