# A-Share Quant Selector — Design System

## Direction
Dark analytical cockpit for quantitative stock analysis.
Warm-dark palette (not pure black) with gold accent for signals and actions.
Chinese A-share market convention: red=bullish, green=bearish.

## Tokens
- Canvas: #131a2b (warm dark navy)
- Surface: #1c2539 (cards, panels)
- Elevated: #243049 (dropdowns, param groups)
- Inset: #0f1520 (input backgrounds)
- Ink: #e2e8f0 / #94a3b8 / #64748b / #475569 (4-level text hierarchy)
- Borders: rgba(148, 163, 184, 0.08 / 0.15 / 0.25) (3-level)
- Accent: #f59e0b (gold — signal & action)
- Bull: #ef4444 (red — up/buy)
- Bear: #22c55e (green — down/sell)
- Info: #3b82f6

## Depth Strategy
Surface color shifts + subtle borders. No shadows in dark mode.

## Typography
- UI: System sans-serif (PingFang SC, Microsoft YaHei)
- Data: System monospace (SF Mono, Menlo, Consolas)

## Spacing
4px base unit: 4, 8, 12, 16, 20, 24, 32, 48

## Border Radius
- sm: 4px (inputs, small buttons)
- md: 6px (cards, buttons)
- lg: 10px (modals, large containers)

## Charts
- ECharts for K-line (candlestick) charts
- Dark theme with matching token colors
- Chinese market colors: red candles up, green candles down

## Key Patterns
- Stat cards with colored top accent bar
- Signal cards with colored left border by category
- Gold slider thumbs for parameter editors
- Monospace for all numeric data
- SVG stroke icons (16-18px)
