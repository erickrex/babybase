# BabyBase Design Guide

> Warm, optimistic, mobile-first. Parents are making a personal choice together, so
> every screen should feel low-anxiety, inviting, and clear. This guide is the single
> source of truth for color, type, spacing, surfaces, components, and motion.

## 1. Brand Direction

BabyBase is **emotional and optimistic**. The visual identity blends two of our style
experiments:

- **[DesertSunrise](styles_experiments/DesertSunrise.md) — the foundation.** Sand and
  clay neutrals, sunrise warmth (peach, coral, amber), deep dusk text, breathable
  rhythm, and energetic CTAs. This is the emotional core: early light, open landscape,
  optimism.
- **[PacificCoast](styles_experiments/PacificCoast.md) — the restraint.** Whitespace as
  structure, one card = one intent, crisp surfaces, restrained shadows, muted status
  indicators, and precise (not playful) motion. This keeps the warmth from tipping into
  noise and keeps a personal, high-stakes decision feeling calm and trustworthy.

The result: **warm off-white surfaces, peach/coral primary CTAs, soft amber accents,
readable dusk text, and a calming sage secondary** for balance.

### Principles

1. **Warmth is the default, restraint is the discipline.** Neutrals dominate; saturated
   color is reserved for actions, feedback, and celebration.
2. **One intent per surface.** A card, a step, a sheet does one job. (PacificCoast)
3. **Breathable rhythm.** Generous vertical spacing and tonal section breaks instead of
   heavy borders. (DesertSunrise)
4. **Calm under high stakes.** Choosing a child's name is personal. Avoid alarm,
   pressure, or visual shouting outside of genuine celebration moments.
5. **Mobile-first at 375px.** Design the phone first, then expand. Key CTA stays above
   the fold.

## 2. Color Palette

All values are token-ready. Token names map 1:1 to `frontend/src/theme/tokens.ts`
(TypeScript) and the `@theme` CSS custom properties in `frontend/src/index.css`.

### Surfaces — warm off-white (sand/clay)

| Token | Hex | Use |
| --- | --- | --- |
| `bg` (canvas) | `#FDF8F2` | App background. Warm off-white, not pure white. |
| `bg-card` | `#FFFFFF` | Cards and raised surfaces. |
| `bg-muted` | `#F7EFE4` | Subtle section fills, secondary button base. |
| `bg-sunken` | `#F0E5D7` | Inset wells, deck background behind cards. |
| `bg-overlay` | `rgba(44, 37, 33, 0.55)` | Modal/scrim. Warm dusk, not cold black. |

### Text — readable dusk (warm dark)

| Token | Hex | Use | Contrast on `bg` |
| --- | --- | --- | --- |
| `text` | `#2C2521` | Headings, body. | ~14.3:1 (AAA) |
| `text-secondary` | `#6B5B4E` | Supporting copy, labels. | ~6.2:1 (AA) |
| `text-muted` | `#9A897A` | Hints, placeholders. **Large/non-essential only.** | ~3.2:1 (AA Large) |
| `text-on-color` | `#FFFFFF` | Text on coral-strong/sage-dark fills (see §8). | see §8 |

### Primary — peach / coral CTAs

A graded coral scale. Peach is the decorative/gradient end; the deeper coral is the
fill that carries white text.

| Token | Hex | Use |
| --- | --- | --- |
| `coral-tint` (`primary-muted`) | `#FCEAE3` | Tinted backgrounds, selected chips. |
| `peach` (`primary-light`) | `#FBA47C` | Gradient start, decorative warmth, illustrations. |
| `coral` (`primary`) | `#F2765C` | Brand coral. Icons/accents on light surfaces, links. |
| `coral-strong` (`primary-cta`) | `#E35C45` | **Primary button fill (white text).** |
| `coral-dark` (`primary-dark`) | `#C44A35` | Hover / pressed. |

### Accent — soft amber

| Token | Hex | Use |
| --- | --- | --- |
| `amber-tint` | `#FBF1DC` | Warm highlight backgrounds. |
| `amber-light` | `#F8CE83` | Decorative accent, gradient mid. |
| `amber` (`accent`) | `#F5B45A` | "Maybe" state, badges, gentle emphasis. |
| `amber-dark` | `#D98A2B` | Amber text/icon on light when contrast is needed. |

### Secondary — sage (calming balance)

The cool, low-saturation counterweight that keeps the palette from running hot.
Sea-glass (`#4F9DB0`) is the approved alternative where a cooler blue reads better
(e.g. informational states).

| Token | Hex | Use |
| --- | --- | --- |
| `sage-tint` | `#EDF3EF` | Calm section fills, secondary chips. |
| `sage-light` | `#A7C7B5` | Decorative, soft dividers. |
| `sage` (`secondary`) | `#6FA088` | Secondary accents, calm fills (use **dusk text**, not white). |
| `sage-dark` (`secondary-cta`) | `#568671` | Sage button fill (white text), hover / pressed. |

### Semantic & swipe feedback

Kept slightly desaturated (PacificCoast restraint) so feedback informs without alarming.

| Token | Hex | Use |
| --- | --- | --- |
| `success` / `swipe-like` | `#3E9E7A` | "Like", success. Harmonizes with sage. |
| `error` / `swipe-dislike` | `#DC5648` | "Nope", errors. Warm red, not fire-engine. |
| `swipe-maybe` | `#F5B45A` | "Maybe" (amber). |
| `info` | `#4F9DB0` | Informational (sea-glass). |
| `match-gold` | `#F5B45A` | Match celebration. |

### Gradients

Use sparingly — hero moments, the primary CTA on key screens, and match celebration
only. Never as a default card background.

- `gradient-sunrise`: `linear-gradient(135deg, #FBA47C 0%, #F2765C 55%, #E35C45 100%)`
  — primary CTA emphasis, onboarding hero.
- `gradient-celebrate`: `radial-gradient(circle, #F8CE83 0%, #F5B45A 60%, #F2765C 100%)`
  — match screen glow.

## 3. Typography

- **Family:** `'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`.
- **Headings:** bold (`700`), confident and short. Generous line-height (~1.2).
- **Body:** `400`, line-height ~1.6 for breathable reading.
- **Scale** (unchanged from current tokens):

| Token | Size | Typical use |
| --- | --- | --- |
| `xs` | 0.75rem / 12px | Captions, metadata |
| `sm` | 0.875rem / 14px | Secondary copy, labels |
| `base` | 1rem / 16px | Body, inputs, button text |
| `lg` | 1.125rem / 18px | Lead paragraph |
| `xl` | 1.25rem / 20px | Card titles |
| `2xl` | 1.5rem / 24px | Section headings |
| `3xl` | 1.875rem / 30px | Page titles |
| `4xl` | 2.25rem / 36px | Hero / name display |

Weights: `normal 400`, `medium 500`, `semibold 600`, `bold 700`.

## 4. Spacing & Radii

Breathable rhythm. Keep the existing scale; lean toward the larger end for vertical
section spacing.

- **Spacing:** `xs 4 · sm 8 · md 12 · lg 16 · xl 20 · 2xl 24 · 3xl 32 · 4xl 40 · 5xl 48`.
- **Radii:** `sm 6 · md 10 · lg 16 · xl 20 · 2xl 24 · full 9999`.
  - Buttons & inputs: `xl` (20px).
  - Cards & sheets: `2xl` (24px) — DesertSunrise's large, friendly corners.
  - Chips/avatars: `full`.

## 5. Surfaces & Elevation

Restrained, warm-tinted shadows. Use elevation to separate intent, not to decorate.

| Token | Value | Use |
| --- | --- | --- |
| `shadow-sm` | `0 1px 2px rgba(44,37,33,0.05)` | Inputs, subtle lift. |
| `shadow-card` | `0 2px 8px rgba(44,37,33,0.08)` | Default card. |
| `shadow-elevated` | `0 8px 24px rgba(44,37,33,0.10)` | Swipe card, sheets, modals. |
| `shadow-glow` | `0 0 24px rgba(245,180,90,0.30)` | Match celebration only. |

Prefer tonal shifts (`bg` → `bg-muted` → `bg-sunken`) over borders for section breaks.
When a border is needed, use `#E8DACA` (warm sand), `#D8C6B2` for stronger separation,
and `coral` for focus rings.

## 6. Components

### Buttons

- **Primary:** `coral-strong (#E35C45)` fill, white semibold text, radius `xl`,
  `shadow-card`. Hover → `coral-dark`. On hero screens may use `gradient-sunrise`.
  Keep label ≥16px semibold (see §8 contrast note).
- **Secondary:** `bg-muted` fill, `#E8DACA` border, `text` label. For calm/alternative
  actions, use a `sage` outline / `sage-tint` fill with **dusk text**, or a solid
  `sage-dark (#568671)` fill with white text. (White on `sage` itself fails contrast.)
- **Tertiary / text:** `coral` label, no fill.
- **Destructive:** `error` fill or outline, always with explicit confirmation.

### Inputs

- `bg-card` field, `#E8DACA` border, `text` value, `text-muted` placeholder.
- Focus: `coral` border + 2px `coral`/20% ring (`focus:ring-primary/20`).
- Lightweight inline validation in `error`; helper text in `text-secondary`.

### Cards

- `bg-card`, radius `2xl`, `shadow-card`. One title, useful metadata, one obvious CTA.
- Layer neutrals for depth; avoid heavy outlines.

### Chips / tags

- Color-coded by context, low saturation: `coral-tint` (recommended/active),
  `sage-tint` (calm/filter), `amber-tint` (highlight). Selected state uses the solid
  token with `text-on-color` or dusk text as contrast allows.

### Bottom navigation

- `bg-card`, top border `#E8DACA`, active item `coral`, inactive `text-muted`.
- Matches the portrait container width (see Layout).

### Swipe deck card

- `bg-card`, radius `2xl`, `shadow-elevated`. Name in `4xl` bold `text`.
- Directional feedback overlays: `swipe-like` (right), `swipe-dislike` (left),
  `swipe-maybe` (up), each at low opacity tint.

### Match celebration

- `gradient-celebrate` background or `shadow-glow` accent, `match-gold` highlights.
- The one place playful motion and saturation are encouraged.

## 7. Layout & Motion

### Layout

- **Mobile-first at 375px.** Vertical flow: header context → primary action →
  content module(s) → secondary actions.
- **Portrait container:** full-width on mobile/tablet; max 50vw centered with blank
  sidebars and side borders on desktop (≥1024px). Persistent bottom nav, matched width.
- Keep the key CTA above the fold.

### Motion

- Duration **180–280ms**, ease-out. Precise and state-driven (PacificCoast), not
  decorative — except match celebration.
- One animation pattern per context: card transitions for swipes, fade/scale for modals,
  small tap/send feedback. Respect `prefers-reduced-motion`.

## 8. Accessibility

Target **WCAG 2.1 AA**. Verified contrast on the canvas `#FDF8F2`:

- `text` 14.3:1, `text-secondary` 6.2:1 — both pass AA for normal text.
- `text-muted` ~3.2:1 — **AA Large only.** Use for non-essential hints/placeholders, not
  body copy.
- **White on `coral-strong` (#E35C45) ≈ 3.6:1** — passes AA for *large/bold* text only.
  Primary button labels must be **≥16px semibold**. For smaller white text, use
  `coral-dark` (#C44A35 ≈ 4.8:1, passes AA normal). White on lighter `coral`/`peach`
  fails — use dusk text on those instead.
- **Solid color fills carry white text only when dark enough.** White passes (large/bold)
  on `error` (3.8:1) but **fails on `sage` (3.0:1), `success` (3.3:1), and `info`
  (3.1:1)** even at large sizes. On those, either use **dusk `text` (#2C2521)** — e.g.
  dusk on `sage` is 5.1:1, on `amber` 8.3:1 — or switch to the darker variant
  (`sage-dark` + white = 4.2:1).
- Don't rely on color alone for swipe feedback or status; pair with icon/label.
- Maintain visible focus rings (`coral`) on all interactive elements.

> Full conformance requires manual testing with assistive technologies (screen readers,
> keyboard-only navigation) and expert review. These ratios are a baseline, not a
> substitute for that validation.

## 9. Implementation Notes

Tokens live in two mirrored places — keep them in sync:

- `frontend/src/theme/tokens.ts` — TypeScript token objects (`colors`, `spacing`,
  `radii`, `shadows`, `typography`).
- `frontend/src/index.css` — the same values as `@theme` CSS custom properties, consumed
  by Tailwind utility classes (`bg-bg`, `text-text`, `bg-primary`, etc.).

Rules:

- Never hardcode hex or inline styles in components. Always reference tokens / Tailwind
  theme classes (enforced by `AGENTS.md`).
- Add new colors as tokens here first, then use them.
- Migration from the current amber/stone palette is a follow-up task (not done by this
  guide): update the two token files, then audit buttons, inputs, cards, nav, and the
  swipe/match screens against §6.

## 10. Quality Checklist

- [ ] Warm sand/off-white identity is consistent across every tab.
- [ ] Coral CTAs are instantly distinguishable from passive elements.
- [ ] Saturated color appears only on actions, feedback, and celebration.
- [ ] Sage/sea-glass provides visible cool balance somewhere on each major flow.
- [ ] Text passes the contrast targets in §8; muted text is never used for body copy.
- [ ] Spacing rhythm and card/button language are identical across pages.
- [ ] Motion is 180–280ms, subtle, and respects reduced-motion.
- [ ] No screen looks like a different app.
