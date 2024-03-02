# Fonts class which, in its init, declares all kind of fonts which are
# used in the UI

from pathlib import Path
from PIL import ImageFont


class Fonts:
    def __init__(self, base_font_size=10):
        font_path = str(Path(Path.cwd(), "../fonts"))
        boldttf = str(Path(font_path, "RobotoMonoNerdFontMono-Bold.ttf"))
        regularttf = str(Path(font_path, "RobotoMonoNerdFontMono-Regular.ttf"))

        self.base_height = base_font_size  # 10
        self.base = ImageFont.truetype(boldttf, self.base_height)
        self.base_width = int(self.base_height * 2.1)  # 21

        self.bold_height = int(base_font_size * 1.2)  # 12
        self.bold = ImageFont.truetype(boldttf, self.bold_height)
        self.bold_width = int(self.bold_height * 1.5)  # 18

        # for indicator icon usage only
        self.icon_height = int(base_font_size * 1.5)  # 15
        self.icon_bold_large = ImageFont.truetype(boldttf, self.icon_height)

        self.large_height = int(base_font_size * 1.5)  # 15
        self.large = ImageFont.truetype(regularttf, self.large_height)

        self.small_height = int(base_font_size * 0.8)  # 8
        self.small = ImageFont.truetype(boldttf, self.small_height)

        self.huge_height = int(base_font_size * 3.5)  # 35
        self.huge = ImageFont.truetype(boldttf, self.huge_height)
