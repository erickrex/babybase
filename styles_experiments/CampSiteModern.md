# CampSiteModern

## Brand Direction
CampSiteModern is warm, social, and premium. It should feel like modern outdoor hospitality: clean cards, soft glow, warm neutrals, and high-trust UI.

## Visual System
- Color foundation:
  - Background: deep charcoal and layered dark gradients.
  - Primary accent: amber/campfire orange.
  - Secondary accents: cool blue for friends, rose for dating.
  - Feedback: emerald success, red danger, zinc muted text.
- Surfaces:
  - Rounded cards (12-20px) with subtle border and light blur.
  - Avoid flat panels; use light depth and elevation hierarchy.
- Typography:
  - High contrast headings, compact body copy, consistent scale.
  - Keep headings confident and short; avoid long paragraphs.

## Layout Rules
- App shell always provides one visual language: same spacing rhythm, same card treatment, same button families.
- Mobile-first vertical flow with clear sections:
  - Header context
  - Primary action
  - Content module(s)
  - Secondary actions
- Keep bottom tab nav persistent and visually integrated.

## Component Patterns
- Buttons:
  - Primary = filled accent.
  - Secondary = muted background with border.
  - Destructive = red, always explicit confirmation.
- Inputs:
  - Dark field with strong focus ring.
  - Clear helper text and lightweight validation.
- Chips/tags:
  - Used for interests, modes, filters.
  - Distinct semantic color per domain (Friends, Dating, Campfire).
- Cards:
  - Always include clear title, useful metadata, and one obvious CTA.

## Feature-by-Feature Application
- Onboarding:
  - Calm progression, large tap targets, clear context text.
  - Keep each step focused; one decision cluster per step.
- Friends Feed:
  - Swipe-first discovery with same mechanics as dating.
  - Keep friend identity: blue accent and social-copy language.
- Dating:
  - High-clarity swipe interactions, match-first CTA, polished chat.
- Matches & Chat:
  - Real-time feel with clear unread state.
  - Message pane scrolls independently; page should not jump.
- Campfire:
  - Same shell, card, and nav language as other tabs.
  - Accent can be amber, but structure must remain consistent.
- Profiles:
  - Media-first hero, quick stats, highlights, prompts, interests.
  - Remove non-supported social actions (follow/friend request).

## Motion & Interaction
- Motion should communicate state change, not decoration:
  - Card transitions for swipes.
  - Modal fade/scale for focus.
  - Small feedback for taps and send actions.
- Keep durations tight (150-300ms) and consistent.

## Implementation Notes
- Centralize tokens in global styles:
  - Color, radius, spacing, shadow, focus ring.
- Keep reusable primitives:
  - app-card, app-btn-primary-*, app-btn-secondary, app-shell.
- Enforce consistency by refactoring one-off classes into shared utilities.

## Quality Bar Checklist
- Same spacing rhythm across pages.
- Same visual hierarchy for headers/cards/actions.
- No tab-specific page that looks like a different app.
- Core user flows are obvious in under 3 seconds.
