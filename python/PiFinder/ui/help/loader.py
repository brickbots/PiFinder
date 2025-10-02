"""
Help content loading with caching and internationalization support.
Integrates with existing Babel translation system.
"""

from .content import get_help_content
from .rendering import HelpRenderer
import PiFinder.i18n  # noqa: F401  # Enables _() function for translations


class PageProcessor:
    """Handles content splitting and navigation generation."""
    
    def __init__(self, renderer):
        self.renderer = renderer
    
    def process_pages(self, pages):
        """Process pages and auto-split long content with proper navigation."""
        processed_pages = []
        
        for page in pages:
            content = page.get("content", [])
            split_pages = self.renderer.split_content_into_pages(content)
            
            if len(split_pages) <= 1:
                # Content fits on one page
                processed_pages.append(page)
            else:
                # Content needs multiple pages - create them with proper navigation
                title = page.get("title", "HELP")
                
                for i, page_content in enumerate(split_pages):
                    new_page = {
                        "title": title,
                        "content": page_content
                    }
                    
                    # Add navigation indicators
                    if i == 0 and len(split_pages) > 1:
                        # First page of multiple has down "more"
                        new_page["footer"] = _("more")
                    elif i > 0 and i < len(split_pages) - 1:
                        # Middle pages have both up and down "more"
                        new_page["navigation"] = {
                            "up": _("more"),
                            "down": _("more")
                        }
                    elif i == len(split_pages) - 1 and i > 0:
                        # Last page has only up "more"
                        new_page["navigation"] = {
                            "up": _("more")
                        }
                    
                    processed_pages.append(new_page)
        
        return processed_pages


class HelpLoader:
    """Loads and caches rendered help content."""
    
    def __init__(self, display_class):
        self.display_class = display_class
        self.renderer = HelpRenderer(display_class)
        self.page_processor = PageProcessor(self.renderer)
        self._cache = {}
        
    def get_help_images(self, help_name):
        """Get list of help images for a specific help module."""
        # Check cache first
        cache_key = f"{help_name}_{self.display_class.resolution}"
        if cache_key in self._cache:
            return self._cache[cache_key]
            
        # Get help content (with translations applied)
        help_content = get_help_content()
        
        if help_name not in help_content:
            return None
            
        module_help = help_content[help_name]
        pages = module_help.get("pages", [])
        
        if not pages:
            return None
            
        # Process pages and auto-split long content
        processed_pages = self.page_processor.process_pages(pages)
        
        # Render all processed pages to images
        rendered_images = []
        for page in processed_pages:
            try:
                image = self.renderer.render_page(page)
                rendered_images.append(image)
            except Exception as e:
                print(f"ERROR: Failed to render help page for {help_name}: {e}")
                continue
                
        # Cache the results
        if rendered_images:
            self._cache[cache_key] = rendered_images
            
        return rendered_images if rendered_images else None
    
    def clear_cache(self):
        """Clear the image cache (useful for language changes)."""
        self._cache.clear()
    
    def get_available_help_modules(self):
        """Get list of available help modules."""
        help_content = get_help_content()
        return list(help_content.keys())