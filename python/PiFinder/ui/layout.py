"""
Resolution-flexible layout helpers for UI modules.

Geometry derives from the display instance's resolution, title-bar height and
font metrics, so the same screen code lays out on the 128x128 SSD1351 and the
176x176 SSD1333 (and any future panel). The hand-tuned per-display knobs these
read live on ``DisplayBase`` subclasses: font sizes, ``titlebar_height`` and
``menu_visible_items``.
"""

from dataclasses import dataclass

from PiFinder.ui.fonts import Font


@dataclass
class CarouselRow:
    """One visible row of a UITextMenu carousel."""

    y: int
    font: Font
    brightness: int
    distance: int  # rows away from the focus (selected) line


@dataclass
class CarouselLayout:
    rows: list  # list[CarouselRow], ordered top -> bottom
    center_index: int  # index into rows of the focus / selected line
    selection_box: tuple  # (x0, y0, x1, y1) outline bracketing the focus row
    text_x: int  # left x for item text
    check_x: int  # left x for the multi-select checkmark


@dataclass
class ListRow:
    """One visible row of a uniform-height object list."""

    y: int
    is_focus: bool
    distance: int  # rows away from the focus (selected) line


@dataclass
class ListLayout:
    rows: list  # list[ListRow], ordered top -> bottom
    center_index: int  # index into rows of the focus / selected line
    selection_box: tuple  # (x0, y0, x1, y1) outline bracketing the focus row
    text_x: int  # left x for item text (after the type marker)
    marker_x: int  # left x for the object-type marker
    marker_dy: int  # vertical offset to paste the marker relative to a row's y
    row_font: Font  # font for the non-focus rows (base)
    focus_font: Font  # font for the focus / selected row (bold)


def _tier(distance: int, fonts) -> tuple:
    """Font + brightness for a row ``distance`` rows from the focus line.

    Reproduces the legacy 128 carousel for distances 0-3 (large/bold/base/base
    at 256/192/128/96) and extends it for the taller 176 carousel (distance >=4
    -> small font at 64), keeping the symmetric fisheye falloff.
    """
    if distance == 0:
        return fonts.large, 256
    if distance == 1:
        return fonts.bold, 192
    if distance == 2:
        return fonts.base, 128
    if distance == 3:
        return fonts.base, 96
    return fonts.small, 64


def carousel_layout(display_class) -> CarouselLayout:
    """Compute the carousel row layout for the given display instance.

    Rows are stacked top-to-bottom by their tier font height plus a small gap
    and the whole block is centred in the area below the title bar, so the
    focus (selected) line lands near the vertical centre of the screen.
    """
    fonts = display_class.fonts
    n = display_class.menu_visible_items
    half = n // 2
    tb = display_class.titlebar_height
    resX = display_class.resX
    resY = display_class.resY

    # font + brightness per row, top -> bottom (symmetric around the focus line)
    rows_meta = [_tier(abs(i - half), fonts) for i in range(n)]
    heights = [font.height for font, _ in rows_meta]

    gap = max(2, fonts.base.height // 4)
    block = sum(heights) + gap * (n - 1)
    area = resY - tb
    top = tb + max(0, (area - block) // 2)

    rows = []
    y = top
    for i, (font, brightness) in enumerate(rows_meta):
        rows.append(
            CarouselRow(y=y, font=font, brightness=brightness, distance=abs(i - half))
        )
        y += font.height + gap

    focus = rows[half]
    pad = max(2, gap)
    box = (-1, focus.y - pad, resX, focus.y + focus.font.height + pad)

    # x indents scale with width (13 / 3 px on the 128 panel).
    text_x = round(resX * 13 / 128)
    check_x = round(resX * 3 / 128)
    return CarouselLayout(
        rows=rows,
        center_index=half,
        selection_box=box,
        text_x=text_x,
        check_x=check_x,
    )


def list_layout(display_class) -> ListLayout:
    """Compute the uniform-row layout for a UIObjectList.

    Unlike the carousel, the object list draws every row in the base font (the
    focus / selected row in bold), so rows are near-uniform height. The focus
    row reserves extra vertical space for its selection box; rows stack by font
    height plus a small gap and the block is centred below the title bar so the
    focus line lands near the screen centre. Reproduces the legacy 128 layout
    (7 rows) within a couple of pixels and extends to the taller 176 panel
    (``menu_visible_items`` rows).
    """
    fonts = display_class.fonts
    n = display_class.menu_visible_items
    center = n // 2
    tb = display_class.titlebar_height
    resX = display_class.resX
    resY = display_class.resY
    base = fonts.base
    bold = fonts.bold

    gap = max(2, base.height // 4)
    pad = gap  # padding between the focus text and its selection box

    # The focus row reserves room for the bold text plus the box padding so the
    # outline never collides with its neighbours.
    focus_slot = bold.height + 2 * pad
    heights = [focus_slot if i == center else base.height for i in range(n)]
    block = sum(heights) + gap * (n - 1)
    area = resY - tb
    top = tb + max(0, (area - block) // 2)

    rows = []
    y = top
    for i in range(n):
        if i == center:
            rows.append(ListRow(y=y + pad, is_focus=True, distance=0))
        else:
            rows.append(ListRow(y=y, is_focus=False, distance=abs(i - center)))
        y += heights[i] + gap

    focus = rows[center]
    box = (-1, focus.y - pad, resX, focus.y + bold.height + pad)

    return ListLayout(
        rows=rows,
        center_index=center,
        selection_box=box,
        text_x=round(resX * 12 / 128),
        marker_x=0,
        marker_dy=2,
        row_font=base,
        focus_font=bold,
    )
