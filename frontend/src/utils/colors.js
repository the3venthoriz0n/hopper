// SYSTEM DESIGN: RGB values stored separately for opacity support
// Use rgba() helper function for colors with opacity

export const HOPPER_COLORS = {
  // Primary Palette - Deep, Slate-based tones
  base: '#0F1115',
  secondary: '#1A1D23',
  accent: '#969D9E',
  light: '#E2E1D5',
  white: '#FFFFFF',
  black: '#0F1115',

  // Semantic colors - Refined to match the muted palette
  success: '#43A047',
  error: '#E53935',
  warning: '#FFB300',
  info: '#1E88E5',
  link: '#0066cc',
  linkHover: '#0052a3',
  grey: '#666666',
  greyLight: '#CCCCCC',
  greyBorder: '#EEEEEE',

  // Additional semantic colors found in codebase
  adminRed: '#ef4444',
  infoBlue: '#3b82f6',
  warningAmber: '#f59e0b',
  tokenGreen: '#22c55e',
  lightGreyBg: '#f5f5f5',
  errorDark: '#dc2626',
  indigo: '#6366f1',
  purple: '#a855f7',

  // Platform-specific colors
  youtubeRed: '#FF0000',
  tiktokBlack: '#000000',
  instagramPink: '#E4405F',

  // RGB values for opacity support
  rgb: {
    base: '15, 17, 21',
    secondary: '26, 29, 35',
    accent: '120, 149, 150',
    light: '226, 225, 213',
    white: '255, 255, 255',
    success: '67, 160, 71',
    error: '229, 57, 53',
    warning: '255, 179, 0',
    info: '30, 136, 229',
    link: '0, 102, 204',
    linkHover: '0, 82, 163',
    grey: '102, 102, 102',
    greyLight: '204, 204, 204',
    greyBorder: '238, 238, 238',
    adminRed: '239, 68, 68',
    infoBlue: '59, 130, 246',
    warningAmber: '245, 158, 11',
    tokenGreen: '34, 197, 94',
    lightGreyBg: '245, 245, 245',
    errorDark: '220, 38, 38',
    indigo: '99, 102, 241',
    purple: '168, 85, 247',
    youtubeRed: '255, 0, 0',
    tiktokBlack: '0, 0, 0',
    instagramPink: '228, 64, 95',
  }
};

/**
 * Helper function for rgba colors with opacity
 * @param {string} rgb - RGB values as string "r, g, b"
 * @param {number} opacity - Opacity value between 0 and 1
 * @returns {string} rgba color string
 * @example rgba(HOPPER_COLORS.rgb.error, 0.5) => 'rgba(229, 57, 53, 0.5)'
 */
export const rgba = (rgb, opacity) => `rgba(${rgb}, ${opacity})`;

/**
 * Get gradient background for a color
 * @param {string} color - Hex color or color key from HOPPER_COLORS
 * @param {number} opacityStart - Starting opacity (default: 1.0)
 * @param {number} opacityEnd - Ending opacity (default: 0.9)
 * @returns {string} CSS gradient string
 */
export const getGradient = (color, opacityStart = 1.0, opacityEnd = 0.9) => {
  let rgbValue;
  if (color.startsWith('#')) {
    // Convert hex to rgb
    const hex = color.replace('#', '');
    const r = parseInt(hex.substring(0, 2), 16);
    const g = parseInt(hex.substring(2, 4), 16);
    const b = parseInt(hex.substring(4, 6), 16);
    rgbValue = `${r}, ${g}, ${b}`;
  } else if (HOPPER_COLORS[color]) {
    const rgbKey = HOPPER_COLORS.rgb[color] || HOPPER_COLORS.rgb[color];
    if (rgbKey) {
      rgbValue = rgbKey;
    } else {
      // Fallback: try to get from color directly
      const hex = HOPPER_COLORS[color].replace('#', '');
      const r = parseInt(hex.substring(0, 2), 16);
      const g = parseInt(hex.substring(2, 4), 16);
      const b = parseInt(hex.substring(4, 6), 16);
      rgbValue = `${r}, ${g}, ${b}`;
    }
  } else {
    // Assume it's already an RGB string
    rgbValue = color;
  }
  return `linear-gradient(135deg, ${rgba(rgbValue, opacityStart)} 0%, ${rgba(rgbValue, opacityEnd)} 100%)`;
};

/**
 * Get hover color (slightly lighter/darker version)
 * @param {string} color - Color key from HOPPER_COLORS or hex color
 * @returns {string} Hover color hex value
 */
export const getHoverColor = (color) => {
  if (color.startsWith('#')) {
    return color;
  }
  
  // Map common colors to their hover variants
  const hoverMap = {
    link: HOPPER_COLORS.linkHover,
    error: HOPPER_COLORS.errorDark,
    adminRed: HOPPER_COLORS.errorDark,
  };
  
  return hoverMap[color] || HOPPER_COLORS[color] || color;
};

/**
 * Get platform-specific color
 * @param {string} platform - Platform name ('youtube', 'tiktok', 'instagram')
 * @returns {string} Platform color hex value
 */
export const getPlatformColor = (platform) => {
  const platformColors = {
    youtube: HOPPER_COLORS.youtubeRed,
    tiktok: HOPPER_COLORS.tiktokBlack,
    instagram: HOPPER_COLORS.instagramPink,
  };
  return platformColors[platform] || HOPPER_COLORS.accent;
};

