"""
Help content rendering system with clean separation of concerns.
Converts text-based help content to PIL Images for display.
"""

from PIL import Image, ImageDraw
import textwrap
from PiFinder.ui.base import UIModule


class LayoutConfig:
    """Centralized layout configuration and calculations."""
    
    def __init__(self, display_class):
        self.display_class = display_class
        self.resolution = display_class.resolution
        
        # Layout constants
        self.title_height = 17 if self.resolution[0] == 128 else 22
        self.margin_x = 3
        self.margin_y = 1
        self.bottom_margin = 25  # Space for navigation
        
        # Font configuration
        self.content_font = display_class.fonts.base    # Size 10 for content
        self.title_font = display_class.fonts.bold      # Size 12 for titles  
        self.nav_font = display_class.fonts.base        # Size 10 for navigation
        
        # Line spacing
        self.line_height = self.content_font.height + 3
        
        # Color scheme
        self.colors = display_class.colors if hasattr(display_class, 'colors') else None
        self.bg_color = (0, 0, 0)                       # Black background
        self.title_bg_color = (64, 64, 64)              # Dark gray title bar
        self.text_color = (255, 255, 255)               # White text
        self.nav_color = (192, 192, 192)                # Light gray navigation
        
        # Calculated areas
        self.content_width = self.resolution[0] - (2 * self.margin_x)
        self.content_height = self.resolution[1] - self.title_height - (2 * self.margin_y)
        self.chars_per_line = self.content_width // self.content_font.width


class HelpIcons:
    """Icon definitions and resolution using Nerd Font glyphs."""
    
    # Navigation arrows - use proper Nerd Font arrow glyphs
    UP = "\uf062"        # Nerd Font arrow-up
    DOWN = "\uf063"      # Nerd Font arrow-down
    LEFT = "\uf060"      # Nerd Font arrow-left
    RIGHT = "\uf061"     # Nerd Font arrow-right
    UP_DOWN = "\uf062\uf063"    # Combined up/down
    LEFT_RIGHT = "\uf060\uf061" # Combined left/right
    
    # Action icons using actual PiFinder Nerd Font icons
    SQUARE = UIModule._SQUARE_      # Nerd Font square
    PLUS = UIModule._PLUS_          # Nerd Font plus  
    MINUS = UIModule._MINUS_        # Nerd Font minus
    PLUS_MINUS = UIModule._PLUSMINUS_  # Combined plus/minus
    
    # Additional common icons
    CHECKMARK = UIModule._CHECKMARK if UIModule._CHECKMARK else "✓"
    GPS = UIModule._GPS_ICON if UIModule._GPS_ICON else "GPS"
    CAMERA = UIModule._CAM_ICON if UIModule._CAM_ICON else "CAM"
    
    # Number ranges (as strings for consistency)
    NUMBERS_0_9 = "0-9"
    NUMBERS_0_5 = "0-5"
    NUMBER_0 = "0"
    NUMBER_1 = "1"
    
    @classmethod
    def get_icon(cls, icon_name):
        """Get the actual icon character for a given icon name."""
        return getattr(cls, icon_name.upper(), icon_name)


class TextProcessor:
    """Handles all text wrapping and chunking operations."""
    
    def __init__(self, layout_config):
        self.config = layout_config
    
    def wrap_text(self, text):
        """Wrap text to fit display width."""
        if not text:
            return []
            
        effective_chars = max(12, self.config.chars_per_line - 2)
        return textwrap.wrap(
            text, 
            width=effective_chars,
            break_long_words=True,
            break_on_hyphens=True
        )
    
    def split_text_into_chunks(self, text, max_lines_per_chunk):
        """Split long text into chunks that fit within page limits."""
        if not text:
            return []
            
        wrapped_lines = self.wrap_text(text)
        chunks = []
        current_chunk_lines = []
        
        for line in wrapped_lines:
            if len(current_chunk_lines) >= max_lines_per_chunk:
                # Current chunk is full, start a new chunk
                if current_chunk_lines:
                    chunks.append(" ".join(current_chunk_lines))
                current_chunk_lines = [line]
            else:
                current_chunk_lines.append(line)
        
        # Add the last chunk if it has content
        if current_chunk_lines:
            chunks.append(" ".join(current_chunk_lines))
            
        return chunks if chunks else [text]
    
    def calculate_max_lines_per_page(self):
        """Calculate how many lines fit on a page."""
        basic_reserved_space = (self.config.title_height + 
                               (2 * self.config.margin_y) + 
                               self.config.bottom_margin)
        available_height = self.config.resolution[1] - basic_reserved_space
        return max(4, available_height // self.config.line_height)
    
    def estimate_text_height(self, text):
        """Estimate height needed to render text."""
        if not text:
            return 0
        wrapped_lines = self.wrap_text(text)
        return len(wrapped_lines) * self.config.line_height


class HelpRenderer:
    """Main rendering coordinator for help pages."""
    
    def __init__(self, display_class):
        self.config = LayoutConfig(display_class)
        self.text_processor = TextProcessor(self.config)
    
    def render_page(self, page_content):
        """Render a single help page to PIL Image."""
        image = Image.new("RGB", self.config.resolution, color=self.config.bg_color)
        draw = ImageDraw.Draw(image)
        
        self._render_title_bar(draw, page_content)
        content_start_y = self._calculate_content_start_y(page_content)
        self._render_content(draw, page_content, content_start_y)
        self._render_navigation(draw, page_content)
        
        return image
    
    def split_content_into_pages(self, content):
        """Split content into multiple pages if needed."""
        if not content:
            return []
            
        pages = []
        current_page_content = []
        current_y = self.config.title_height + self.config.margin_y
        max_y = self.config.resolution[1] - self.config.bottom_margin
        
        for item in content:
            if "text" in item:
                # Handle long text by splitting into chunks
                max_lines = self.text_processor.calculate_max_lines_per_page()
                text_chunks = self.text_processor.split_text_into_chunks(
                    item["text"], max_lines
                )
                
                for chunk in text_chunks:
                    chunk_item = {"text": chunk}
                    chunk_height = self._estimate_item_height(chunk_item)
                    
                    if current_y + chunk_height > max_y and current_page_content:
                        pages.append(current_page_content)
                        current_page_content = [chunk_item]
                        current_y = self.config.title_height + self.config.margin_y + chunk_height
                    else:
                        current_page_content.append(chunk_item)
                        current_y += chunk_height
            else:
                # Handle non-text items (icons, etc.)
                item_height = self._estimate_item_height(item)
                
                if current_y + item_height > max_y and current_page_content:
                    pages.append(current_page_content)
                    current_page_content = [item]
                    current_y = self.config.title_height + self.config.margin_y + item_height
                else:
                    current_page_content.append(item)
                    current_y += item_height
        
        if current_page_content:
            pages.append(current_page_content)
            
        return pages
    
    def _render_title_bar(self, draw, page_content):
        """Render the title bar section."""
        draw.rectangle(
            [(0, 0), (self.config.resolution[0], self.config.title_height)], 
            fill=self.config.title_bg_color
        )
        
        title = page_content.get("title", "HELP")
        draw.text(
            (self.config.margin_x, 2),
            title,
            font=self.config.title_font.font,
            fill=self.config.text_color
        )
    
    def _calculate_content_start_y(self, page_content):
        """Calculate where content should start based on navigation."""
        start_y = self.config.title_height + self.config.margin_y
        navigation = page_content.get("navigation", {})
        if "up" in navigation:
            start_y += self.config.nav_font.height + 4
        return start_y
    
    def _render_content(self, draw, page_content, start_y):
        """Render the main content area."""
        current_y = start_y
        content_items = page_content.get("content", [])
        max_y = self.config.resolution[1] - self.config.bottom_margin
        
        for item in content_items:
            if current_y >= max_y:
                break
                
            if "icon" in item and "action" in item:
                current_y = self._render_icon_action_line(draw, item, current_y)
            elif "text" in item:
                current_y = self._render_text_content(draw, item, current_y, max_y)
    
    def _render_icon_action_line(self, draw, item, y_pos):
        """Render a single icon + action line."""
        icon_name = item.get("icon", "")
        action = item.get("action", "")
        
        icon_glyph = HelpIcons.get_icon(icon_name) if icon_name else ""
        
        if icon_glyph and action:
            display_text = f"{icon_glyph} {action}"
        elif icon_glyph:
            display_text = icon_glyph
        elif action:
            display_text = action
        else:
            return y_pos
            
        draw.text(
            (self.config.margin_x, y_pos),
            display_text,
            font=self.config.content_font.font,
            fill=self.config.text_color
        )
        
        return y_pos + self.config.line_height
    
    def _render_text_content(self, draw, item, y_pos, max_y):
        """Render flowing text content."""
        text = item.get("text", "")
        if not text:
            return y_pos
        
        wrapped_lines = self.text_processor.wrap_text(text)
        
        for line in wrapped_lines:
            if y_pos >= max_y:
                break
                
            draw.text(
                (self.config.margin_x, y_pos),
                line,
                font=self.config.content_font.font,
                fill=self.config.text_color
            )
            y_pos += self.config.line_height
            
        return y_pos
    
    def _render_navigation(self, draw, page_content):
        """Render navigation indicators and footer."""
        navigation = page_content.get("navigation", {})
        
        # Up navigation
        if "up" in navigation:
            up_arrow = HelpIcons.get_icon("UP")
            up_text = f"{up_arrow} {navigation['up']} {up_arrow}"
            bbox = draw.textbbox((0, 0), up_text, font=self.config.nav_font.font)
            text_width = bbox[2] - bbox[0]
            x_pos = (self.config.resolution[0] - text_width) // 2
            
            draw.text(
                (x_pos, self.config.title_height + 2),
                up_text,
                font=self.config.nav_font.font,
                fill=self.config.nav_color
            )
            
        # Down navigation
        if "down" in navigation:
            down_arrow = HelpIcons.get_icon("DOWN")
            down_text = f"{down_arrow} {navigation['down']} {down_arrow}"
            bbox = draw.textbbox((0, 0), down_text, font=self.config.nav_font.font)
            text_width = bbox[2] - bbox[0]
            x_pos = (self.config.resolution[0] - text_width) // 2
            bottom_y = self.config.resolution[1] - self.config.nav_font.height - 2
            
            draw.text(
                (x_pos, bottom_y),
                down_text,
                font=self.config.nav_font.font,
                fill=self.config.nav_color
            )
        
        # Footer
        footer = page_content.get("footer", "")
        if footer:
            down_arrow = HelpIcons.get_icon("DOWN")
            footer_text = f"{down_arrow} {footer} {down_arrow}"
            bbox = draw.textbbox((0, 0), footer_text, font=self.config.nav_font.font)
            text_width = bbox[2] - bbox[0]
            x_pos = (self.config.resolution[0] - text_width) // 2
            y_pos = self.config.resolution[1] - self.config.nav_font.height - 2
            
            draw.text(
                (x_pos, y_pos),
                footer_text,
                font=self.config.nav_font.font,
                fill=self.config.nav_color
            )
    
    def _estimate_item_height(self, item):
        """Estimate the height needed for a content item."""
        if "icon" in item and "action" in item:
            return self.config.line_height
        elif "text" in item:
            return self.text_processor.estimate_text_height(item.get("text", ""))
        return 0