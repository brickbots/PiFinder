# Fonts class which, in its init, declares all kind of fonts which are
# used in the UI

from pathlib import Path
from PIL import ImageFont
from PiFinder import config


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
        use_layout_engine: bool = True,
    ) -> None:
        # Some languages (zh) work better without layout_engine
        # for better Unicode support
        if use_layout_engine:
            self.font = ImageFont.truetype(
                ttf_file, size, layout_engine=ImageFont.Layout.BASIC
            )
        else:
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
        font_path = str(Path(Path.cwd(), "../fonts"))

        # Check for chinese language specifically
        cfg = config.Config()
        lang = cfg.get_option("language", "en")
        if lang == "zh":
            # Use Chinese font for Chinese language
            chinesettf = str(
                Path(font_path, "sarasa-mono-sc-light-nerd-font+patched.ttf")
            )
            boldttf = chinesettf
            regularttf = chinesettf
            use_layout_engine = False
        else:
            # Use default fonts for other languages
            boldttf = str(Path(font_path, "RobotoMonoNerdFontMono-Bold.ttf"))
            regularttf = str(Path(font_path, "RobotoMonoNerdFontMono-Regular.ttf"))
            use_layout_engine = True

        self.base = Font(
            boldttf, base_size, screen_width, use_layout_engine=use_layout_engine
        )  # 10
        self.bold = Font(
            boldttf, bold_size, screen_width, use_layout_engine=use_layout_engine
        )  # 12
        self.large = Font(
            regularttf, large_size, screen_width, use_layout_engine=use_layout_engine
        )  # 15
        self.small = Font(
            boldttf, small_size, screen_width, use_layout_engine=use_layout_engine
        )  # 8
        self.huge = Font(
            boldttf, huge_size, screen_width, use_layout_engine=use_layout_engine
        )  # 35

        self.icon_bold_large = Font(
            boldttf,
            int(base_size * 1.5),
            screen_width,
            use_layout_engine=use_layout_engine,
        )  # 15
