# Fonts class which, in its init, declares all kind of fonts which are
# used in the UI

from pathlib import Path
from PIL import ImageFont
import gettext
import os


class Font:
    """
    Stores a image font object + some typographic details

    if height/width is not provided, it's calculated
    """

    def __init__(
        self,
        ttf_file: str,
        size: int,
        screen_width: int = 128,
        height: int = 0,
        width: int = 0,
    ):
        # CHANGED: Removed layout_engine for better Unicode support
        self.font = ImageFont.truetype(ttf_file, size)

        # calculate height/width
        # Use several chars to get space between
        bbox = self.font.getbbox("MMMMMMMMMM")
        self.height = bbox[3] if height == 0 else height
        self.width = int(bbox[2] / 10) if width == 0 else width

        self.line_length = int(screen_width / self.width)


class Fonts:
    def __init__(
        self,
        base_size=10,
        bold_size=12,
        small_size=8,
        large_size=15,
        huge_size=35,
        screen_width=128,
    ):
        base_dir = Path(__file__).parent.parent.parent
        font_path = str(Path(Path.cwd(), "../fonts"))
        print(font_path) 
        # CHANGED: Check if Chinese language is active
        is_chinese = False
        try:
            locale_path = str(base_dir / "locale")
            # Try to load Chinese translation
            lang = gettext.translation(
                "messages", 
                locale_path, 
                languages=["zh"], 
                fallback=True
            )
            # Check if translation is actually Chinese (not fallback)
            info = lang.info()
            if info and info.get('language', '').startswith('zh'):
                # Additional check: verify translation works
                test = lang.gettext("Star")
                if test and test != "Star":
                    is_chinese = True
        except Exception:
            pass
        
        if is_chinese:
            # Use Chinese font for Chinese language
            chinesettf = str(Path(font_path, "sarasa-mono-sc-light-nerd-font+patched.ttf"))
            boldttf = chinesettf
            regularttf = chinesettf
        else:
            # Use default fonts for other languages
            boldttf = str(Path(font_path, "RobotoMonoNerdFontMono-Bold.ttf"))
            regularttf = str(Path(font_path, "RobotoMonoNerdFontMono-Regular.ttf"))
        print(boldttf)
        self.base = Font(boldttf, base_size, screen_width)  # 10
        self.bold = Font(boldttf, bold_size, screen_width)  # 12
        self.large = Font(regularttf, large_size, screen_width)  # 15
        self.small = Font(boldttf, small_size, screen_width)  # 8
        self.huge = Font(boldttf, huge_size, screen_width)  # 35

        self.icon_bold_large = Font(boldttf, int(base_size * 1.5), screen_width)  # 15
