/**
 * Design tokens for BabyBase — warm, optimistic, mobile-first.
 * DesertSunrise foundation (sand/clay + sunrise coral/amber) tempered with
 * PacificCoast restraint and a calming sage secondary.
 * See babybase_design_guide.md. Never hardcode colors; always reference tokens.
 */

export const colors = {
  // Primary palette — sunrise coral. `primary` is the CTA fill (carries white
  // text at >=16px semibold; see design guide §8). `primaryDark` = hover/pressed.
  primary: '#e35c45',       // Coral strong — primary CTA fill
  primaryLight: '#fba47c',  // Peach — gradient start / decorative warmth
  primaryDark: '#b8412e',   // Coral dark — hover / pressed / chip + link text
  primaryMuted: '#fceae3',  // Coral tint — tinted fills, selected chips

  // Coral accent — brand coral for icons/links/accents on light surfaces
  coral: '#f2765c',         // Brand coral
  coralLight: '#fba47c',    // Peach
  coralDark: '#b8412e',     // Coral dark

  // Secondary — sage (calming cool balance). Use dusk text on `secondary`;
  // `secondaryDark` carries white text. Sea-glass `info` is the cooler alt.
  secondary: '#6fa088',       // Sage
  secondaryLight: '#a7c7b5',  // Sage light — decorative, soft dividers
  secondaryDark: '#568671',   // Sage dark — fill w/ white text, hover/pressed
  secondaryMuted: '#edf3ef',  // Sage tint — calm fills, secondary chips

  // Accent — soft amber. Use dusk text on amber fills.
  amber: '#f5b45a',         // Amber accent — "maybe", badges, gentle emphasis
  amberLight: '#f8ce83',    // Amber light — decorative, gradient mid
  amberDark: '#d98a2b',     // Amber dark — amber text/icon on light
  amberMuted: '#fbf1dc',    // Amber tint — warm highlight backgrounds

  // Backgrounds — warm off-white sand/clay
  bg: '#fdf8f2',            // App canvas — warm off-white
  bgCard: '#ffffff',        // Cards / raised surfaces
  bgMuted: '#f7efe4',       // Subtle section fills, secondary button base
  bgSunken: '#f0e5d7',      // Inset wells, deck background
  bgOverlay: 'rgba(44, 37, 33, 0.55)', // Modal scrim — warm dusk

  // Text — readable dusk
  text: '#2c2521',          // Headings, body
  textSecondary: '#6b5b4e', // Supporting copy, labels
  textMuted: '#9a897a',     // Hints, placeholders (large/non-essential only)
  textOnPrimary: '#ffffff',

  // Borders — warm sand
  border: '#e8daca',        // Default border
  borderStrong: '#d8c6b2',  // Stronger separation
  borderFocus: '#f2765c',   // Focus ring — coral

  // Semantic — slightly desaturated for low-anxiety feedback
  success: '#3e9e7a',       // Harmonizes with sage
  error: '#dc5648',         // Warm red
  info: '#4f9db0',          // Sea-glass

  // Swipe feedback
  swipeLike: '#3e9e7a',     // Like
  swipeDislike: '#dc5648',  // Nope
  swipeMaybe: '#f5b45a',    // Maybe (amber)

  // Match celebration
  matchGold: '#f5b45a',
  matchGlow: 'rgba(245, 180, 90, 0.30)',
} as const;

export const gradients = {
  // Use sparingly — hero moments, primary CTA on key screens, celebration only.
  sunrise: 'linear-gradient(135deg, #fba47c 0%, #f2765c 55%, #e35c45 100%)',
  celebrate: 'radial-gradient(circle, #f8ce83 0%, #f5b45a 60%, #f2765c 100%)',
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
  sm: '0 1px 2px rgba(44, 37, 33, 0.05)',
  card: '0 2px 8px rgba(44, 37, 33, 0.08)',
  elevated: '0 8px 24px rgba(44, 37, 33, 0.10)',
  glow: '0 0 24px rgba(245, 180, 90, 0.30)',
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
