# Design System — Prey Dark

A dark analytical design system inspired by kiro.dev and Discord.
Pure black canvas, purple accent, pill-shaped surfaces, mono display headings.
Reusable across all projects.

---

## Direction

Dark cockpit aesthetic. Pure black canvas with warm purple-gray surfaces.
Depth via surface color shifts + subtle shadows (not flat, not heavy).
Pill-shaped cards and buttons. Mono font for display headings, creating
contrast with sans-serif body text. Feels premium, dense, and alive.

Chinese finance context: red = bullish/up, green = bearish/down.

---

## Color Tokens

### Surfaces (prey palette — warm purple-gray, NOT cool slate)

| Token          | Value                       | Usage                              |
|----------------|-----------------------------|------------------------------------|
| canvas         | `#000000`                   | Page background                    |
| surface        | `#28242e`                   | Cards, panels                      |
| surface-hover  | `#312c38`                   | Card/row hover                     |
| elevated       | `#19161d`                   | Dropdowns, icon containers, inputs |
| inset          | `rgba(255,255,255,0.03)`    | Segmented controls, recessed areas |

### Ink (text — warm gray, NOT cool slate)

| Token         | Value      | Usage                          |
|---------------|------------|--------------------------------|
| ink           | `#fafafa`  | Primary text                   |
| ink-secondary | `#c1bec6`  | Labels, descriptions           |
| ink-muted     | `#938f9b`  | Placeholders, timestamps, meta |
| ink-inverse   | `#000000`  | Text on accent buttons         |

### Accent

| Token        | Value                          | Usage                     |
|--------------|--------------------------------|---------------------------|
| accent       | `#9046ff`                      | Primary actions, links    |
| accent-hover | `#7c3aed`                      | Hover state               |
| accent-dim   | `oklch(0.5 0.15 285 / 0.12)`  | Tinted backgrounds        |
| accent-light | `#c6a0ff`                      | Secondary accent text     |

### Semantic

| Token    | Value     | Usage                    |
|----------|-----------|--------------------------|
| bull     | `#ef4444` | Up/buy/danger            |
| bear     | `#22c55e` | Down/sell/success        |
| bull-dim | `oklch(0.55 0.18 25 / 0.12)` | Tinted bg        |
| bear-dim | `oklch(0.6 0.14 155 / 0.12)` | Tinted bg        |
| info     | `#3b82f6` | Informational            |

### Borders (3 levels)

| Token        | Value                      | Usage         |
|--------------|----------------------------|---------------|
| border       | `#352f3d`                  | Default       |
| border-hover | `rgba(255,255,255,0.18)`   | Interactive   |
| border-focus | `#9046ff`                  | Focus ring    |

---

## Depth Strategy

Three shadow levels. Dark mode shadows use pure black with high opacity.
Glass surfaces use `backdrop-filter` for nav and overlays.

```
shadow-card:       0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2)
shadow-card-hover: 0 8px 24px rgba(0,0,0,0.4), 0 2px 8px rgba(0,0,0,0.3)
shadow-float:      0 12px 40px rgba(0,0,0,0.5), 0 4px 12px rgba(0,0,0,0.3)
```

Glass:
```
glass:          backdrop-filter: blur(20px) saturate(1.4); bg: rgba(10,8,18,0.82)
glass-elevated: backdrop-filter: blur(16px) saturate(1.3); bg: rgba(144,70,255,0.06)
```

---

## Typography

### Font Stack
- **Sans** (body): `-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif`
- **Mono** (display headings + data): `"SF Mono", Menlo, "Cascadia Code", Consolas, monospace`

### Scale (kiro-style: mono headings with tight tracking)

| Role         | Size              | Weight | Tracking       | Font  |
|--------------|-------------------|--------|----------------|-------|
| Display      | 48-68px           | 700    | -1.2 to -0.9px | mono  |
| H1 (page)    | 24px / sm:30px    | 700    | -0.03em        | sans  |
| H2 (section) | 16-18px           | 600    | normal         | sans  |
| H3 (card)    | 14px              | 600    | normal         | sans  |
| Body         | 14px (text-sm)    | 400    | normal         | sans  |
| Small        | 12px (text-xs)    | 400    | normal         | sans  |
| Micro        | 10px              | 400    | normal         | mono  |
| Nav link     | 13px              | 500    | 0.02em         | sans, uppercase |

---

## Spacing

4px base unit.

```
Scale: 2, 4, 6, 8, 12, 16, 20, 24, 32, 48, 64, 80
```

### Page Layout
- Horizontal padding: `px-5 sm:px-8 lg:px-16`
- Vertical padding: `py-6 sm:py-12`
- Max width: `max-w-6xl` (72rem / 1152px)
- Section gap: `space-y-6 sm:space-y-8`

### Component Spacing
- Card padding: `p-4` (compact) / `p-6 sm:p-8` (large)
- Grid gap: `gap-4 sm:gap-5`
- Inline gap: `gap-2` (tight) / `gap-3` (normal) / `gap-4` (loose)

---

## Border Radius

Pill-shaped aesthetic. Large radii everywhere.

| Token | Value        | Usage                                   |
|-------|--------------|-----------------------------------------|
| sm    | `rounded-md` (6px)   | Tags, inline badges, param inputs |
| md    | `rounded-lg` (8px)   | Badges, skeleton, small surfaces  |
| lg    | `rounded-xl` (12px)  | Button sm, nav links              |
| xl    | `rounded-[16px]`     | Button md/lg, inputs, tabs, list items |
| 2xl   | `rounded-2xl` (16px) | Icon containers, skeletons        |
| pill  | `rounded-[32px]`     | Cards, modals (signature shape)   |
| mega  | `rounded-[48px]`     | Hero sections, CTA blocks (kiro-style) |
| full  | `rounded-full`       | Toasts, dots, progress, avatars   |

---

## Component Patterns

### Nav Bar (floating island, centered)
```
Position: fixed top, centered horizontally
Shape:    rounded-[18px], bg rgba(25,25,25,0.6), border border-prey-700
          backdrop-filter: blur(4px)
Height:   h-11 (44px)
Behavior: auto-hide on scroll down, show on scroll up (spring animation)
Links:    text-[13px] uppercase font-medium tracking-[0.02em]
Active:   bg-white/10 rounded-xl with layoutId shared animation
```

### Bottom Nav (mobile, glass)
```
Position: fixed bottom, full-width
Surface:  glass (blur + semi-transparent)
Height:   h-14 (56px) + safe-area-inset
Icons:    20x20 SVG stroke, strokeWidth 1.5
Active:   text-accent + w-8 h-0.5 indicator bar at top (layoutId animation)
Labels:   text-[10px]
```

### Card
```
Base:     bg-surface + border border-border + rounded-[32px]
Hover:    border-color -> border-hover, shadow-card-hover, y: -1 (framer-motion)
Selected: border-2 border-accent shadow-lg
Padding:  p-4 (compact) or p-6 (large)
```

### Button
```
Sizes:
  sm: h-8  px-3  text-sm  rounded-xl    gap-1.5
  md: h-12 px-6  text-sm  rounded-[16px] gap-2
  lg: h-14 px-8  text-base rounded-[16px] gap-2.5

Variants:
  primary:   bg-accent text-ink-inverse hover:bg-accent-hover
  secondary: bg-transparent border border-white/20 hover:border-white/40
  danger:    bg-bull-dim text-bull hover:bg-bull/15
  ghost:     text-ink-secondary hover:text-ink hover:bg-elevated

Micro-interaction: whileHover scale(1.01), whileTap scale(0.98)
```

### Input
```
Height:   h-10 (40px)
Padding:  px-3
Shape:    rounded-[16px]
Surface:  bg-elevated border-border
Focus:    border-accent ring-2 ring-accent/15
Param:    h-8 px-2 bg-inset rounded-lg (smaller variant)
```

### Badge
```
Shape:   px-2 py-0.5 rounded-lg text-xs font-medium
Style:   colored bg-dim + matching text + border-color/20
```

### Segmented Control
```
Container: bg-inset rounded-[16px] p-1
Active:    bg-surface text-ink shadow-sm
Inactive:  text-ink-muted hover:text-ink
```

### Toast
```
Shape:  glass-elevated rounded-full px-4 py-2.5 shadow-float
Status: w-2 h-2 dot (accent=info, bear=success, bull=error)
Enter:  spring from right (damping 25, stiffness 300)
```

### Modal
```
Backdrop:  bg-canvas/80 backdrop-blur-sm
Card:      solid-card rounded-[32px] p-6 sm:p-8 shadow-float
Enter:     scale 0.96 y:12 -> scale 1 y:0 (spring)
Step dots: h-1.5 rounded-full, active w-24 accent, inactive w-8 white/15
```

### Empty State
```
Icon:        bg-elevated w-14 h-14 rounded-2xl, centered icon
Title:       text-sm font-semibold text-ink
Description: text-xs text-ink-muted max-w-xs text-center
CTA:         Button sm
```

### Stat Card
```
Base:      Card with AnimatedNumber + label
Number:    text-2xl sm:text-4xl font-mono font-semibold
Label:     text-xs sm:text-sm text-ink-secondary
Accent:    optional top-edge glow gradient
```

### Skeleton
```
Shape:  bg-surface + shimmer animation
Radius: inherit from context (rounded-2xl for cards, rounded-[32px] for list items)
```

### Progress Bar
```
Track: h-1.5 rounded-full bg-elevated
Fill:  rounded-full, animated width
Color: bg-accent (default), bg-bear (>=85%), bg-ink-muted (<60%)
```

---

## Animation Tokens

### Duration
```
fast:   0.15s   Micro-interactions, button press, step transitions
normal: 0.2s    Page transitions, reveals, fades
slow:   0.3s    Progress bars, complex transitions
count:  0.8s    Number counting animation
```

### Easing
```
default:      [0.25, 0.1, 0.25, 1]              Standard ease
spring:       { type: spring, damping: 25, stiffness: 300 }   Modals, toasts, nav
springGentle: { type: spring, damping: 30, stiffness: 200 }   Soft reveals
```

### Stagger
```
fast:   0.03s   Dense lists
normal: 0.05s   Card grids
list:   0.04s   Standard lists
Cap:    delay max 0.5s total
```

### Page Transition
```
Enter: opacity 0, y: 8  -> opacity 1, y: 0
Exit:  opacity 0, y: -8
```

### Scroll-triggered (kiro-style, for future use)
```
Cards:    fade-in + slide-up on viewport entry
Sections: staggered reveal with intersection observer
Terminal: typewriter / ASCII art animation
Marquee:  horizontal auto-scroll for testimonials
```

---

## Icons

```
Size:        16-20px for UI, 14px for inline actions (copy button)
Style:       SVG stroke, fill="none"
StrokeWidth: 1.5 (nav, content), 2 (emphasis), 2.5 (checkmark)
Large:       40x40 for modal illustrations (strokeWidth 2)
```

---

## Responsive Strategy

Mobile-first. Three breakpoints.

```
default:  Mobile (< 640px)
sm:       640px   Show desktop nav, expand padding/type
lg:       1024px  Wider page padding
```

- Mobile: bottom tab bar + compact cards
- Desktop: floating centered nav island + expanded layouts
- Max content: `max-w-6xl` (1152px)
- Grid: 1 col -> sm:2 col -> lg:3 col

---

## Focus & Accessibility

```
:focus-visible  outline-none ring-2 ring-accent/30 ring-offset-2
                --tw-ring-offset-color: #000000
```

---

## Charts (domain-specific)

- Engine: ECharts
- Theme: dark, matching prey palette
- Colors: red candles up, green candles down (Chinese market)
- Chart tokens centralized in `tokens.ts` -> `chartColors`

---

## Anti-patterns (things to AVOID)

- Cool slate grays (use warm purple-grays from prey palette)
- Small border-radius (< 8px on cards — always use pill shape)
- Heavy shadows on every element (reserve for float/hover)
- Pure white text on all levels (use 3-level ink hierarchy)
- Flat buttons without micro-interactions (always add scale)
- Generic sans-serif headings (use mono for display/data contrast)
