"""Template utilities for video titles and descriptions"""
import random
from typing import Dict, Any


def replace_template_placeholders(template: str, filename: str, wordbank: list) -> str:
    """Replace template placeholders with actual values"""
    # Replace {filename}
    result = template.replace('{filename}', filename)
    
    # Replace each {random} with a random word from wordbank
    if wordbank:
        # Find all {random} occurrences and replace each independently
        while '{random}' in result:
            random_word = random.choice(wordbank)
            result = result.replace('{random}', random_word, 1)  # Replace only first occurrence
    else:
        # If wordbank is empty, just remove {random} placeholders
        result = result.replace('{random}', '')
    
    return result


def get_video_title(
    video,
    custom_settings: dict,
    destination_settings: dict,
    global_settings: dict,
    filename_no_ext: str,
    template_key: str = 'title_template'
) -> str:
    """
    Get video title following consistent priority across all destinations.
    
    Priority order (matches GUI display):
    1. Per-video custom title (custom_settings['title'])
    2. Generated title (video.generated_title) - already generated once, prevents re-randomization
    3. Destination-specific template (destination_settings[template_key])
    4. Global template (global_settings['title_template'])
    5. Filename (filename_no_ext)
    
    This ensures what you see in the GUI is what gets uploaded, preventing
    title mismatches when templates use {random} placeholders.
    
    Args:
        video: Video object with generated_title attribute
        custom_settings: Per-video custom settings dict
        destination_settings: Destination-specific settings (youtube/tiktok/instagram)
        global_settings: Global settings dict
        filename_no_ext: Filename without extension
        template_key: Key to use for destination template (default: 'title_template', 
                      use 'caption_template' for Instagram)
    
    Returns:
        str: The resolved title
    """
    # Priority 1: Per-video custom title
    if 'title' in custom_settings:
        return custom_settings['title']
    
    # Priority 2: Generated title (already generated once, prevents re-randomization)
    if video.generated_title:
        return video.generated_title
    
    # Priority 3 & 4: Destination template or global template
    title_template = destination_settings.get(template_key, '') or global_settings.get('title_template', '{filename}')
    if title_template:
        return replace_template_placeholders(
            title_template,
            filename_no_ext,
            global_settings.get('wordbank', [])
        )
    
    # Priority 5: Filename fallback
    return filename_no_ext


def get_video_description(
    video,
    custom_settings: dict,
    destination_settings: dict,
    global_settings: dict,
    filename_no_ext: str,
    template_key: str = 'description_template',
    default: str = ''
) -> str:
    """
    Get video description following consistent priority across all destinations.
    
    Priority order (matches title logic to prevent re-randomization):
    1. Per-video custom description (custom_settings['description'])
    2. Generated description (video.generated_description) - already generated once, prevents re-randomization
    3. Destination-specific template (destination_settings[template_key])
    4. Global template (global_settings['description_template'])
    5. Default value (empty string or provided default)
    
    This ensures what you see in the GUI is what gets uploaded, preventing
    description mismatches when templates use {random} placeholders.
    
    Args:
        video: Video object with generated_description attribute
        custom_settings: Per-video custom settings dict
        destination_settings: Destination-specific settings (youtube/tiktok/instagram)
        global_settings: Global settings dict
        filename_no_ext: Filename without extension
        template_key: Key to use for destination template (default: 'description_template')
        default: Default value if no template is found (default: empty string)
    
    Returns:
        str: The resolved description
    """
    # Priority 1: Per-video custom description
    if 'description' in custom_settings:
        return custom_settings['description']
    
    # Priority 2: Generated description (already generated once, prevents re-randomization)
    if video.generated_description:
        return video.generated_description
    
    # Priority 3 & 4: Destination template or global template
    desc_template = destination_settings.get(template_key, '') or global_settings.get('description_template', '')
    if desc_template:
        return replace_template_placeholders(
            desc_template,
            filename_no_ext,
            global_settings.get('wordbank', [])
        )
    
    # Priority 5: Default fallback
    return default

