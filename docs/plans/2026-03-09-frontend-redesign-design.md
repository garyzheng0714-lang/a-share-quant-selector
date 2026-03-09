# Frontend Redesign Design Document

## Overview

Redesign the A-Share Quant Selector frontend from a traditional dark-themed financial terminal into a modern, warm-toned, interaction-rich experience. The goal is a premium product feel that breaks away from conventional stock system aesthetics while maintaining full functional parity.

## Design Decisions

| Dimension | Decision |
|-----------|----------|
| Color tone | Warm cream/ivory (`#f5f0e8`) + dark gray text (`#2d2b28`), Claude-inspired |
| Interactions | Full polish across all touchpoints |
| Layout | Minimal fullscreen with lightweight tab switching, no persistent sidebar |
| K-line colors | Desaturated: brick red `#c0392b` (bull), muted green `#27896e` (bear) |
| Stock list display | Hybrid mode: compact list (default) + card view toggle |
| Tech stack | React + Next.js + Framer Motion + TradingView Lightweight Charts |

## Color System (Design Tokens)

### Backgrounds (light to deep)

| Token | Hex | Usage |
|-------|-----|-------|
| `canvas` | `#faf6f0` | Page outermost background |
| `surface` | `#f5f0e8` | Card/panel background (core cream) |
| `elevated` | `#ede8df` | Hover/popover background |
| `inset` | `#e8e2d8` | Input/inset area background |
| `overlay` | `rgba(45,43,40, 0.6)` | Modal backdrop |

### Text

| Token | Hex | Usage |
|-------|-----|-------|
| `ink` | `#2d2b28` | Primary text (dark gray, not pure black) |
| `ink-secondary` | `#6b6560` | Secondary text |
| `ink-muted` | `#9c9590` | Placeholder/disabled text |
| `ink-inverse` | `#faf6f0` | Text on dark backgrounds |

### Accent

| Token | Hex | Usage |
|-------|-----|-------|
| `accent` | `#c0785a` | Primary accent (warm copper) |
| `accent-hover` | `#a8654a` | Hover state |
| `accent-dim` | `rgba(192,120,90, 0.12)` | Light accent background |

### K-line

| Token | Hex | Usage |
|-------|-----|-------|
| `bull` | `#c0392b` | Bullish/rising (brick red) |
| `bear` | `#27896e` | Bearish/falling (muted green) |
| `bull-dim` | `rgba(192,57,43, 0.08)` | Bull light background |
| `bear-dim` | `rgba(39,137,110, 0.08)` | Bear light background |

### Borders

| Token | Hex | Usage |
|-------|-----|-------|
| `border` | `rgba(45,43,40, 0.08)` | Default border |
| `border-hover` | `rgba(45,43,40, 0.15)` | Hover border |
| `border-focus` | `#c0785a` | Focus border (matches accent) |

## Layout Architecture

### Fullscreen with floating top nav

The navigation is a floating top bar with frosted glass effect. No persistent sidebar. Each page occupies the full viewport.

```
+-----------------------------------------------------+
|  Top bar (frosted glass, 48px)                      |
|  Logo    Overview  Selection  Stocks  History  Rank  |
+-----------------------------------------------------+
|                                                     |
|              Full-screen content area               |
|              (page fills viewport)                  |
|                                                     |
+-----------------------------------------------------+
```

### Top nav bar properties

- Frosted glass: `backdrop-filter: blur(16px)` + `rgba(250,246,240, 0.8)`
- Auto-hide on scroll down, reappear on scroll up (Safari-style)
- Active tab: thin underline indicator that slides between tabs (Framer Motion `layoutId`)
- Height: 48px (compact)

### Mobile adaptation

- Top bar becomes bottom tab bar (iOS-style placement)
- Same frosted glass effect
- Sliding indicator preserved

## Page Transition System

Direction-aware transitions using Framer Motion `AnimatePresence`:

- Navigate right: current page slides left + fades, new page enters from right
- Navigate left: current page slides right + fades, new page enters from left
- Duration: 300ms, easing: `[0.25, 0.1, 0.25, 1]`

## K-line Immersive Experience

K-line view is a full-screen page (not a modal). Clicking a stock triggers a shared layout animation from the stock card/row to the full-screen chart view.

### Layout

```
+-----------------------------------------------------+
|  <- Back    600519 Kweichow Moutai    $1,856 +2.3%  |
|                                    Daily Weekly Monthly|
+---------------------------------------------------------+
|                                                       |
|              Candlestick chart (60%)                  |
|              MA5 / MA10 / MA20 / MA60                 |
|                                                       |
+---------------------------------------------------------+
|              Volume (15%)                             |
+---------------------------------------------------------+
|              KDJ indicator (15%)                      |
+---------------------------------------------------------+
|  <- Previous    3/15                     Next ->      |
+-----------------------------------------------------+
```

### Interaction details

| Interaction | Behavior |
|-------------|----------|
| Enter animation | Shared layout animation from card/row position to fullscreen (400ms, spring damping: 25) |
| Exit animation | Reverse shrink back to original position (350ms) |
| Crosshair | Follows cursor/finger, all 3 chart areas linked, frosted glass data panel |
| Swipe navigation | Left/right swipe to switch stocks (mobile), with elastic bounce |
| Period switching | Candlestick morph transition between daily/weekly/monthly |
| Zoom | Pinch zoom (mobile) / scroll zoom (desktop), with inertia |
| Data panel | Semi-transparent panel at top-left showing OHLC + MA values + KDJ, real-time update |

### TradingView Lightweight Charts advantages

- Native touch gestures and inertial scrolling
- Built-in crosshair and data tooltips
- Superior rendering performance (canvas-based)
- ~40KB bundle (vs ECharts ~1MB)

## Stock List - Hybrid Mode

Toggle between compact list and card view. Switching uses Framer Motion `layout` animation where list rows "inflate" into cards.

### List mode (default)

- Row height: 56px
- Hover: background transitions to `elevated`, 2px copper left border appears
- Match score: gradient progress bar (copper for high, gray for low)
- Click row: fullscreen transition to K-line

### Card mode

- Grid: `auto-fill, minmax(280px, 1fr)`
- Each card contains 30-day mini K-line thumbnail (TradingView mini mode)
- Hover: `translateY(-4px)` + shadow deepens
- Bottom: three sub-score bars (trend, KDJ, volume)
- Click card: card becomes animation origin for K-line fullscreen

## Micro-interaction & Animation System

### Loading states

| Scenario | Effect |
|----------|--------|
| Initial load | Skeleton screen: cream-colored blocks + warm shimmer sweep |
| K-line loading | Thin pulse line animation in chart area |
| Selection running | Ring progress + jumping percentage + current phase text |
| API requests | 2px copper progress line at top bar bottom (YouTube-style) |

### Button & control interactions

| Interaction | Effect |
|-------------|--------|
| Button hover | Background darkens + `scale(1.02)`, 150ms |
| Button press | `scale(0.97)` pressed feel, 100ms |
| Button success | Text morphs to checkmark then bounces back |
| Toggle switch | Circular slider slides + background color gradient |
| Slider drag | Thumb enlarges + floating value label |
| Input focus | Border color transitions to copper + subtle glow |

### Data change animations

| Scenario | Effect |
|----------|--------|
| Number update | Digit flip animation (old value scrolls to new) |
| Price change | Number briefly flashes corresponding color (red/green), then reverts |
| List sort | Items smoothly reorder (Framer Motion `layout`) |
| New data | New row slides in from top + brief highlight |

### Toast notifications

- Capsule shape, frosted glass background
- Left dot indicates type: copper (info), muted green (success), brick red (error)
- Enter: slide in from right + spring; Exit: slide out right
- Auto-dismiss after 3 seconds

## Dashboard (Overview Page)

### Structure

```
+-----------------------------------------------------+
|     Today's Selection Overview             2026-03-09|
|                                                     |
|  +-------------+ +-------------+ +-------------+   |
|  |      15     | |    +3.2%    | |     92%     |   |
|  |  Stocks     | |  Avg Gain   | |  Top Match  |   |
|  +-------------+ +-------------+ +-------------+   |
|                                                     |
|  +---------------------------------------------+   |
|  |         Recent selection trend chart         |   |
|  |         (area chart, copper gradient fill)   |   |
|  +---------------------------------------------+   |
|                                                     |
|  Latest Signals                                     |
|  +---------------------------------------------+   |
|  |  600519 Moutai      92%  Just triggered      |   |
|  |  000858 Wuliangye   78%  2 hours ago         |   |
|  +---------------------------------------------+   |
+-----------------------------------------------------+
```

### Stat card properties

- Numbers in `font-mono`, 32px, digit flip animation on entry
- Cards: no border, `surface` background + subtle shadow
- Hover: number color transitions to copper

## Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Framework | React 18 + Next.js 14 (App Router) | SSR, routing, page structure |
| Language | TypeScript (strict mode) | Type safety |
| Animation | Framer Motion 11 | All transitions and animations |
| Charts | TradingView Lightweight Charts | K-line and mini charts |
| Styling | Tailwind CSS v4 | Utility-first + custom design tokens |
| State | Zustand | Lightweight state management |
| Data fetching | SWR | Requests + caching + revalidation |

## Project Structure

```
src/
  app/
    layout.tsx              # Root layout + top nav
    page.tsx                # Overview Dashboard
    selection/
      page.tsx              # Selection views management
    stocks/
      page.tsx              # Stock list (hybrid mode)
    history/
      page.tsx              # Historical results
    ranking/
      page.tsx              # Ranking page
    stock/
      [code]/
        page.tsx            # K-line fullscreen (dynamic route)
  components/
    ui/                     # Base components (Button, Card, Input, Badge, Toast...)
    charts/                 # Chart components (KlineChart, MiniChart, AreaChart...)
    stock/                  # Stock-related (StockList, StockCard, StockRow...)
    layout/                 # Layout components (NavBar, PageTransition, ScrollHide...)
  lib/
    api.ts                  # API request wrappers
    store.ts                # Zustand store definitions
    tokens.ts               # Design tokens (exported as TS constants)
  styles/
    globals.css             # Tailwind config + CSS custom properties
```

## API Compatibility

The new frontend must be fully compatible with the existing Flask backend API:

```
GET    /api/views              # List views
POST   /api/views              # Create view
GET    /api/views/<id>         # View details
PUT    /api/views/<id>         # Update view
DELETE /api/views/<id>         # Delete view
POST   /api/views/<id>/run     # Run selection
GET    /api/views/<id>/run/status?task_id=xxx  # Poll progress

GET    /api/stock/<code>/kline?period=daily|weekly  # K-line data

GET    /api/ranking            # Ranking data
GET    /api/stocks             # Stock list

GET    /api/scheduler/status   # Scheduler status
POST   /api/scheduler/start    # Start scheduler
POST   /api/scheduler/stop     # Stop scheduler
POST   /api/data/update        # Update data
```

## Design Principles

1. **Content is the interface** - Navigation recedes, data takes center stage
2. **Warm over cold** - Every color in the palette has warm undertones
3. **Motion with purpose** - Every animation communicates state change, not decoration
4. **Density on demand** - List view for efficiency, card view for exploration
5. **Immersive charts** - K-line charts deserve the full viewport
