# Fonts class which, in its init, declares all kind of fonts which are
# used in the UI

from pathlib import Path
from PIL import ImageFont


class Fonts:
    font_path = str(Path(Path.cwd(), "../fonts"))
    base = ImageFont.truetype(str(Path(font_path, "RobotoMono-Regular.ttf")), 10)
    base_width = 21
    bold = ImageFont.truetype(str(Path(font_path, "RobotoMono-Bold.ttf")), 12)
    bold_width = 18
    large = ImageFont.truetype(str(Path(font_path, "RobotoMono-Regular.ttf")), 15)
    small = ImageFont.truetype(str(Path(font_path, "RobotoMono-Bold.ttf")), 8)
    huge = ImageFont.truetype(str(Path(font_path, "RobotoMono-Bold.ttf")), 35)
    # fira_base = ImageFont.truetype(str(Path(font_path, "FiraCode-Regular.ttf")), 10)
