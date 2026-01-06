// Platform configuration - DRY, extensible, matches backend config.py structure
// Backend source of truth: backend/app/services/video/config.py
// UI-only fields (icon, color) are added for frontend display

import { HOPPER_COLORS } from './colors';

export const PLATFORM_CONFIG = {
  youtube: {
    // Backend fields (must match backend/app/services/video/config.py exactly)
    enabled_key: 'youtube_enabled',
    id_keys: ['youtube_id'],
    error_keywords: ['youtube', 'google'],
    title_field: 'youtube_title',
    recompute_fields: {
      title: { template_key: 'title_template', field: 'generated_title', custom_key: 'title' },
      description: { template_key: 'description_template', field: 'custom_settings', custom_key: 'description' },
      tags: { template_key: 'tags_template', field: 'custom_settings', custom_key: 'tags' },
    },
    per_video_settings: ['title', 'description', 'tags', 'visibility', 'made_for_kids'],
    
    // UI-only fields (not in backend)
    icon: 'youtube',
    color: HOPPER_COLORS.youtubeRed,
  },
  tiktok: {
    // Backend fields (must match backend/app/services/video/config.py exactly)
    enabled_key: 'tiktok_enabled',
    id_keys: ['tiktok_id', 'tiktok_publish_id'],
    error_keywords: ['tiktok'],
    title_field: 'tiktok_title',
    recompute_fields: {
      title: { template_key: 'title_template', field: 'generated_title', custom_key: 'title' },
    },
    per_video_settings: ['title', 'privacy_level', 'allow_comments', 'allow_duet', 'allow_stitch'],
    
    // UI-only fields (not in backend)
    icon: 'tiktok',
    color: HOPPER_COLORS.tiktokBlack,
  },
  instagram: {
    // Backend fields (must match backend/app/services/video/config.py exactly)
    enabled_key: 'instagram_enabled',
    id_keys: ['instagram_id'],
    error_keywords: ['instagram', 'facebook'],
    title_field: 'instagram_caption',
    recompute_fields: {
      caption: { template_key: 'caption_template', field: 'custom_settings', custom_key: 'caption' },
    },
    per_video_settings: ['caption', 'media_type', 'share_to_feed', 'cover_url', 'disable_comments', 'disable_likes'],
    
    // UI-only fields (not in backend)
    icon: 'instagram',
    color: HOPPER_COLORS.instagramPink,
  },
};

