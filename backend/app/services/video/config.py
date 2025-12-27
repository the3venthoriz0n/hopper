"""Video service configuration constants"""

# Constants for redis locking
TOKEN_REFRESH_LOCK_TIMEOUT = 10  # seconds
DATA_REFRESH_COOLDOWN = 60  # seconds

# Platform configuration - DRY, extensible, single source of truth
# To add a new platform, just add an entry here
PLATFORM_CONFIG = {
    'youtube': {
        'enabled_key': 'youtube_enabled',
        'id_keys': ['youtube_id'],
        'error_keywords': ['youtube', 'google'],
        'recompute_fields': {
            'title': {'template_key': 'title_template', 'field': 'generated_title', 'custom_key': 'title'},
            'description': {'template_key': 'description_template', 'field': 'custom_settings', 'custom_key': 'description'},
            'tags': {'template_key': 'tags_template', 'field': 'custom_settings', 'custom_key': 'tags'},
        },
    },
    'tiktok': {
        'enabled_key': 'tiktok_enabled',
        'id_keys': ['tiktok_id', 'tiktok_publish_id'],
        'error_keywords': ['tiktok'],
        'recompute_fields': {
            'title': {'template_key': 'title_template', 'field': 'generated_title', 'custom_key': 'title'},
        },
    },
    'instagram': {
        'enabled_key': 'instagram_enabled',
        'id_keys': ['instagram_id', 'instagram_container_id'],
        'error_keywords': ['instagram', 'facebook'],
        'recompute_fields': {
            'caption': {'template_key': 'caption_template', 'field': 'custom_settings', 'custom_key': 'caption'},
        },
    },
}

