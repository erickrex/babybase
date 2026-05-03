/**
 * Design tokens for BabyBase — warm, emotional aesthetic.
 * Never hardcode colors or spacing; always reference these tokens.
 */

export const colors = {
  // Primary palette — warm amber/coral
  primary: '#f59e0b',       // Amber 500
  primaryLight: '#fbbf24',  // Amber 400
  primaryDark: '#d97706',   // Amber 600
  primaryMuted: '#fef3c7',  // Amber 50

  // Coral accent
  coral: '#fb7185',         // Rose 400
  coralLight: '#fecdd3',    // Rose 200
  coralDark: '#e11d48',     // Rose 600

  // Backgrounds — warm neutrals
  bg: '#fffbf5',            // Warm off-white
  bgCard: '#ffffff',        // Card background
  bgMuted: '#fef7ed',       // Slightly warm muted
  bgOverlay: 'rgba(0, 0, 0, 0.5)',

  // Text
  text: '#1c1917',          // Stone 900
  textSecondary: '#57534e', // Stone 600
  textMuted: '#a8a29e',     // Stone 400
  textOnPrimary: '#ffffff',

  // Borders
  border: '#e7e5e4',        // Stone 200
  borderFocus: '#f59e0b',   // Amber 500

  // Semantic
  success: '#10b981',       // Emerald 500
  error: '#ef4444',         // Red 500
  info: '#3b82f6',          // Blue 500

  // Swipe feedback
  swipeLike: '#10b981',     // Green
  swipeDislike: '#ef4444',  // Red
  swipeMaybe: '#f59e0b',    // Amber

  // Match celebration
  matchGold: '#fbbf24',
  matchGlow: 'rgba(251, 191, 36, 0.3)',
} as const;

export const spacing = {
  xs: '4px',
  sm: '8px',
  md: '12px',
  lg: '16px',
  xl: '20px',
  '2xl': '24px',
  '3xl': '32px',
  '4xl': '40px',
  '5xl': '48px',
} as const;

export const radii = {
  sm: '6px',
  md: '10px',
  lg: '16px',
  xl: '20px',
  '2xl': '24px',
  full: '9999px',
} as const;

export const shadows = {
  sm: '0 1px 2px rgba(0, 0, 0, 0.05)',
  card: '0 2px 8px rgba(0, 0, 0, 0.08)',
  elevated: '0 4px 16px rgba(0, 0, 0, 0.12)',
  glow: '0 0 20px rgba(251, 191, 36, 0.25)',
} as const;

export const typography = {
  fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  sizes: {
    xs: '0.75rem',    // 12px
    sm: '0.875rem',   // 14px
    base: '1rem',     // 16px
    lg: '1.125rem',   // 18px
    xl: '1.25rem',    // 20px
    '2xl': '1.5rem',  // 24px
    '3xl': '1.875rem', // 30px
    '4xl': '2.25rem', // 36px
  },
  weights: {
    normal: '400',
    medium: '500',
    semibold: '600',
    bold: '700',
  },
} as const;
