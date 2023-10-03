# Fonts class which, in its init, declares all kind of fonts which are
# used in the UI

from pathlib import Path
from PIL import ImageFont


class Fonts:
    font_path = str(Path(Path.cwd(), "../fonts"))
    boldttf = str(Path(font_path, "RobotoMonoNerdFontMono-Bold.ttf"))
    regularttf = str(Path(font_path, "RobotoMonoNerdFontMono-Regular.ttf"))
    base = ImageFont.truetype(boldttf, 10)
    base_width = 21
    bold = ImageFont.truetype(boldttf, 12)
    bold_width = 18
    # for indicator icon usage only
    icon_bold_large = ImageFont.truetype(boldttf, 15)
    large = ImageFont.truetype(regularttf, 15)
    small = ImageFont.truetype(boldttf, 8)
    huge = ImageFont.truetype(boldttf, 35)
