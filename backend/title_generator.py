import re

class TitleGenerator:
    """Simple title generator - uses filename for now"""
    
    def generate(self, filename):
        """Generate title from filename"""
        # Remove extension
        clean_name = re.sub(r'\.[^.]+$', '', filename)
        # Replace underscores/hyphens with spaces
        clean_name = re.sub(r'[_-]', ' ', clean_name)
        # Clean up whitespace
        clean_name = clean_name.strip()
        return clean_name
