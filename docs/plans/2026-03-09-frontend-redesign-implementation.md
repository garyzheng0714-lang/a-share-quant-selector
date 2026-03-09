# Frontend Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the A-Share Quant Selector frontend as a modern React + Next.js app with warm cream color scheme, immersive K-line charts, and polished micro-interactions, while maintaining full API compatibility with the existing Flask backend.

**Architecture:** Next.js 14 (App Router) with static export for production. During development, Next.js dev server proxies API requests to Flask backend. Zustand for state management, SWR for data fetching, Framer Motion for animations, TradingView Lightweight Charts for K-line rendering. Tailwind CSS v4 for styling with custom design tokens.

**Tech Stack:** React 18, Next.js 14, TypeScript (strict), Framer Motion 11, lightweight-charts, Tailwind CSS v4, Zustand, SWR

**Existing Backend API Base:** Flask on `http://localhost:18321` (unchanged)

**Existing Frontend:** `web/` directory (HTML/CSS/JS) - will NOT be modified or deleted. New frontend lives in `frontend/` directory.

---

## Phase 1: Project Scaffolding

### Task 1.1: Initialize Next.js Project

**Files:**
- Create: `frontend/` (entire Next.js project)

**Step 1: Create Next.js app with TypeScript**

```bash
cd /Users/simba/local_vibecoding/share/a-share-quant-selector
npx create-next-app@14 frontend --typescript --tailwind --eslint --app --src-dir --no-import-alias
```

When prompted:
- Would you like to use Tailwind CSS? Yes
- Would you like to use `src/` directory? Yes
- Would you like to use App Router? Yes
- Would you like to customize the default import alias? No

**Step 2: Install dependencies**

```bash
cd frontend
npm install framer-motion@11 lightweight-charts@4 zustand@5 swr@2
npm install -D @types/node
```

**Step 3: Verify the project starts**

```bash
npm run dev
```

Expected: Next.js dev server starts on port 3000

**Step 4: Commit**

```bash
git add frontend/
git commit -m "feat: scaffold Next.js frontend project with dependencies"
```

---

### Task 1.2: Configure Next.js for API Proxy and Static Export

**Files:**
- Modify: `frontend/next.config.ts`
- Create: `frontend/.env.local`

**Step 1: Configure next.config.ts**

Write `frontend/next.config.ts`:

```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:18321/api/:path*",
      },
    ];
  },
};

export default nextConfig;
```

Note: `rewrites` only works during `next dev`, not with `output: "export"`. For production, Flask will serve the static files directly.

**Step 2: Create .env.local**

Write `frontend/.env.local`:

```
NEXT_PUBLIC_API_BASE=http://localhost:18321
```

**Step 3: Commit**

```bash
git add frontend/next.config.ts frontend/.env.local
git commit -m "chore: configure Next.js API proxy and static export"
```

---

## Phase 2: Design Tokens & Global Styles

### Task 2.1: Create Design Token System

**Files:**
- Create: `frontend/src/lib/tokens.ts`

**Step 1: Write design tokens**

Write `frontend/src/lib/tokens.ts`:

```typescript
export const colors = {
  canvas: "#faf6f0",
  surface: "#f5f0e8",
  elevated: "#ede8df",
  inset: "#e8e2d8",
  overlay: "rgba(45,43,40,0.6)",

  ink: "#2d2b28",
  inkSecondary: "#6b6560",
  inkMuted: "#9c9590",
  inkInverse: "#faf6f0",

  accent: "#c0785a",
  accentHover: "#a8654a",
  accentDim: "rgba(192,120,90,0.12)",

  bull: "#c0392b",
  bear: "#27896e",
  bullDim: "rgba(192,57,43,0.08)",
  bearDim: "rgba(39,137,110,0.08)",

  border: "rgba(45,43,40,0.08)",
  borderHover: "rgba(45,43,40,0.15)",
  borderFocus: "#c0785a",
} as const;

export const fonts = {
  sans: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
  mono: '"SF Mono", "Menlo", "Cascadia Code", "Consolas", monospace',
} as const;

export const ease = {
  default: [0.25, 0.1, 0.25, 1],
  spring: { type: "spring" as const, damping: 25, stiffness: 300 },
  springGentle: { type: "spring" as const, damping: 30, stiffness: 200 },
} as const;

export const duration = {
  fast: 0.15,
  normal: 0.3,
  slow: 0.4,
} as const;

export const CATEGORY_LABELS: Record<string, string> = {
  bowl_center: "回落碗中",
  near_duokong: "靠近多空线",
  near_short_trend: "靠近趋势线",
};
```

**Step 2: Commit**

```bash
git add frontend/src/lib/tokens.ts
git commit -m "feat: add design token system with warm cream palette"
```

---

### Task 2.2: Configure Tailwind with Custom Theme

**Files:**
- Modify: `frontend/src/app/globals.css`
- Modify: `frontend/tailwind.config.ts`

**Step 1: Write Tailwind config**

Write `frontend/tailwind.config.ts`:

```typescript
import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "#faf6f0",
        surface: "#f5f0e8",
        elevated: "#ede8df",
        inset: "#e8e2d8",
        ink: {
          DEFAULT: "#2d2b28",
          secondary: "#6b6560",
          muted: "#9c9590",
          inverse: "#faf6f0",
        },
        accent: {
          DEFAULT: "#c0785a",
          hover: "#a8654a",
          dim: "rgba(192,120,90,0.12)",
        },
        bull: {
          DEFAULT: "#c0392b",
          dim: "rgba(192,57,43,0.08)",
        },
        bear: {
          DEFAULT: "#27896e",
          dim: "rgba(39,137,110,0.08)",
        },
        border: {
          DEFAULT: "rgba(45,43,40,0.08)",
          hover: "rgba(45,43,40,0.15)",
          focus: "#c0785a",
        },
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "PingFang SC",
          "Hiragino Sans GB",
          "Microsoft YaHei",
          "sans-serif",
        ],
        mono: [
          "SF Mono",
          "Menlo",
          "Cascadia Code",
          "Consolas",
          "monospace",
        ],
      },
      boxShadow: {
        card: "0 1px 3px rgba(45,43,40,0.04), 0 1px 2px rgba(45,43,40,0.06)",
        "card-hover":
          "0 4px 12px rgba(45,43,40,0.08), 0 2px 4px rgba(45,43,40,0.04)",
        float:
          "0 8px 24px rgba(45,43,40,0.1), 0 4px 8px rgba(45,43,40,0.05)",
      },
    },
  },
  plugins: [],
};

export default config;
```

**Step 2: Write globals.css**

Write `frontend/src/app/globals.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  body {
    @apply bg-canvas text-ink antialiased;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
      "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  }

  ::selection {
    background-color: rgba(192, 120, 90, 0.2);
  }

  :focus-visible {
    @apply outline-none ring-2 ring-accent/40 ring-offset-2 ring-offset-canvas;
  }

  /* Scrollbar styling */
  ::-webkit-scrollbar {
    width: 6px;
    height: 6px;
  }

  ::-webkit-scrollbar-track {
    background: transparent;
  }

  ::-webkit-scrollbar-thumb {
    @apply bg-ink/10 rounded-full;
  }

  ::-webkit-scrollbar-thumb:hover {
    @apply bg-ink/20;
  }
}

@layer components {
  .glass {
    @apply bg-canvas/80 backdrop-blur-xl;
  }

  .shimmer {
    background: linear-gradient(
      90deg,
      transparent 0%,
      rgba(192, 120, 90, 0.06) 50%,
      transparent 100%
    );
    background-size: 200% 100%;
    animation: shimmer 1.5s ease-in-out infinite;
  }

  @keyframes shimmer {
    0% {
      background-position: 200% 0;
    }
    100% {
      background-position: -200% 0;
    }
  }
}
```

**Step 3: Commit**

```bash
git add frontend/tailwind.config.ts frontend/src/app/globals.css
git commit -m "feat: configure Tailwind with warm cream theme and glass utilities"
```

---

## Phase 3: Base UI Components

### Task 3.1: Button Component

**Files:**
- Create: `frontend/src/components/ui/button.tsx`

**Step 1: Write Button component**

Write `frontend/src/components/ui/button.tsx`:

```tsx
"use client";

import { motion, type HTMLMotionProps } from "framer-motion";
import { forwardRef } from "react";

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
type ButtonSize = "sm" | "md" | "lg";

interface ButtonProps extends Omit<HTMLMotionProps<"button">, "ref"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

const variantStyles: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-ink-inverse hover:bg-accent-hover active:bg-accent-hover",
  secondary:
    "bg-surface text-ink border border-border hover:bg-elevated hover:border-border-hover",
  danger:
    "bg-bull-dim text-bull hover:bg-bull/10",
  ghost:
    "text-ink-secondary hover:text-ink hover:bg-elevated",
};

const sizeStyles: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-sm rounded-lg gap-1.5",
  md: "h-10 px-4 text-sm rounded-xl gap-2",
  lg: "h-12 px-6 text-base rounded-xl gap-2.5",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    { variant = "primary", size = "md", loading, className = "", children, disabled, ...props },
    ref,
  ) {
    return (
      <motion.button
        ref={ref}
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.97 }}
        transition={{ duration: 0.15 }}
        className={`
          inline-flex items-center justify-center font-medium
          transition-colors duration-150
          disabled:opacity-50 disabled:pointer-events-none
          ${variantStyles[variant]}
          ${sizeStyles[size]}
          ${className}
        `}
        disabled={disabled || loading}
        {...props}
      >
        {loading && (
          <svg
            className="animate-spin h-4 w-4"
            viewBox="0 0 24 24"
            fill="none"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>
        )}
        {children}
      </motion.button>
    );
  },
);
```

**Step 2: Commit**

```bash
git add frontend/src/components/ui/button.tsx
git commit -m "feat: add Button component with hover/tap animations"
```

---

### Task 3.2: Card Component

**Files:**
- Create: `frontend/src/components/ui/card.tsx`

**Step 1: Write Card component**

Write `frontend/src/components/ui/card.tsx`:

```tsx
"use client";

import { motion, type HTMLMotionProps } from "framer-motion";
import { forwardRef } from "react";

interface CardProps extends Omit<HTMLMotionProps<"div">, "ref"> {
  hoverable?: boolean;
}

export const Card = forwardRef<HTMLDivElement, CardProps>(
  function Card({ hoverable = false, className = "", children, ...props }, ref) {
    return (
      <motion.div
        ref={ref}
        whileHover={
          hoverable
            ? { y: -4, boxShadow: "0 4px 12px rgba(45,43,40,0.08), 0 2px 4px rgba(45,43,40,0.04)" }
            : undefined
        }
        transition={{ duration: 0.2 }}
        className={`
          bg-surface rounded-2xl shadow-card
          ${hoverable ? "cursor-pointer" : ""}
          ${className}
        `}
        {...props}
      >
        {children}
      </motion.div>
    );
  },
);
```

**Step 2: Commit**

```bash
git add frontend/src/components/ui/card.tsx
git commit -m "feat: add Card component with hover lift animation"
```

---

### Task 3.3: Toast System

**Files:**
- Create: `frontend/src/components/ui/toast.tsx`
- Create: `frontend/src/lib/toast-store.ts`

**Step 1: Write toast store**

Write `frontend/src/lib/toast-store.ts`:

```typescript
import { create } from "zustand";

type ToastType = "info" | "success" | "error";

interface Toast {
  id: string;
  message: string;
  type: ToastType;
}

interface ToastStore {
  toasts: Toast[];
  add: (message: string, type?: ToastType) => void;
  remove: (id: string) => void;
}

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  add: (message, type = "info") => {
    const id = Math.random().toString(36).slice(2, 9);
    set((state) => ({ toasts: [...state.toasts, { id, message, type }] }));
    setTimeout(() => {
      set((state) => ({
        toasts: state.toasts.filter((t) => t.id !== id),
      }));
    }, 3000);
  },
  remove: (id) =>
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    })),
}));
```

**Step 2: Write Toast component**

Write `frontend/src/components/ui/toast.tsx`:

```tsx
"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useToastStore } from "@/lib/toast-store";

const dotColors = {
  info: "bg-accent",
  success: "bg-bear",
  error: "bg-bull",
};

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);

  return (
    <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2">
      <AnimatePresence>
        {toasts.map((toast) => (
          <motion.div
            key={toast.id}
            initial={{ x: 100, opacity: 0, scale: 0.95 }}
            animate={{ x: 0, opacity: 1, scale: 1 }}
            exit={{ x: 100, opacity: 0 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="glass rounded-full px-4 py-2.5 shadow-float flex items-center gap-2.5 border border-border"
          >
            <span
              className={`w-2 h-2 rounded-full ${dotColors[toast.type]}`}
            />
            <span className="text-sm text-ink whitespace-nowrap">
              {toast.message}
            </span>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
```

**Step 3: Commit**

```bash
git add frontend/src/components/ui/toast.tsx frontend/src/lib/toast-store.ts
git commit -m "feat: add toast notification system with spring animations"
```

---

### Task 3.4: Skeleton, Badge, Input, ProgressBar Components

**Files:**
- Create: `frontend/src/components/ui/skeleton.tsx`
- Create: `frontend/src/components/ui/badge.tsx`
- Create: `frontend/src/components/ui/input.tsx`
- Create: `frontend/src/components/ui/progress-bar.tsx`
- Create: `frontend/src/components/ui/index.ts`

**Step 1: Write Skeleton**

Write `frontend/src/components/ui/skeleton.tsx`:

```tsx
export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`bg-inset rounded-lg shimmer ${className}`}
      aria-hidden="true"
    />
  );
}
```

**Step 2: Write Badge**

Write `frontend/src/components/ui/badge.tsx`:

```tsx
type BadgeVariant = "bowl" | "duokong" | "short" | "active" | "inactive";

const variantStyles: Record<BadgeVariant, string> = {
  bowl: "bg-bull-dim text-bull",
  duokong: "bg-accent-dim text-accent",
  short: "bg-bear-dim text-bear",
  active: "bg-bear-dim text-bear",
  inactive: "bg-inset text-ink-muted",
};

interface BadgeProps {
  variant: BadgeVariant;
  children: React.ReactNode;
  className?: string;
}

export function Badge({ variant, children, className = "" }: BadgeProps) {
  return (
    <span
      className={`
        inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium
        ${variantStyles[variant]}
        ${className}
      `}
    >
      {children}
    </span>
  );
}
```

**Step 3: Write Input**

Write `frontend/src/components/ui/input.tsx`:

```tsx
"use client";

import { forwardRef, type InputHTMLAttributes } from "react";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  suffix?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  function Input({ label, suffix, className = "", ...props }, ref) {
    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label className="text-sm text-ink-secondary">{label}</label>
        )}
        <div className="relative">
          <input
            ref={ref}
            className={`
              w-full h-10 px-3 bg-inset rounded-xl text-sm text-ink
              border border-border
              transition-all duration-150
              focus:border-border-focus focus:ring-2 focus:ring-accent/10
              placeholder:text-ink-muted
              ${suffix ? "pr-10" : ""}
              ${className}
            `}
            {...props}
          />
          {suffix && (
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-ink-muted">
              {suffix}
            </span>
          )}
        </div>
      </div>
    );
  },
);
```

**Step 4: Write ProgressBar**

Write `frontend/src/components/ui/progress-bar.tsx`:

```tsx
"use client";

import { motion } from "framer-motion";

interface ProgressBarProps {
  value: number;
  max?: number;
  className?: string;
  colorByValue?: boolean;
}

export function ProgressBar({
  value,
  max = 100,
  className = "",
  colorByValue = false,
}: ProgressBarProps) {
  const pct = Math.min(100, (value / max) * 100);

  let barColor = "bg-accent";
  if (colorByValue) {
    if (pct >= 85) barColor = "bg-bear";
    else if (pct < 60) barColor = "bg-ink-muted";
  }

  return (
    <div className={`h-1.5 bg-inset rounded-full overflow-hidden ${className}`}>
      <motion.div
        className={`h-full rounded-full ${barColor}`}
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.5, ease: [0.25, 0.1, 0.25, 1] }}
      />
    </div>
  );
}
```

**Step 5: Write barrel export**

Write `frontend/src/components/ui/index.ts`:

```typescript
export { Button } from "./button";
export { Card } from "./card";
export { ToastContainer } from "./toast";
export { Skeleton } from "./skeleton";
export { Badge } from "./badge";
export { Input } from "./input";
export { ProgressBar } from "./progress-bar";
```

**Step 6: Commit**

```bash
git add frontend/src/components/ui/
git commit -m "feat: add Skeleton, Badge, Input, ProgressBar UI components"
```

---

## Phase 4: Layout & Navigation

### Task 4.1: NavBar with Frosted Glass and Sliding Indicator

**Files:**
- Create: `frontend/src/components/layout/nav-bar.tsx`

**Step 1: Write NavBar component**

Write `frontend/src/components/layout/nav-bar.tsx`:

```tsx
"use client";

import { motion } from "framer-motion";
import { usePathname } from "next/navigation";
import Link from "next/link";

const navItems = [
  { href: "/", label: "概览" },
  { href: "/selection", label: "选股" },
  { href: "/stocks", label: "股票" },
  { href: "/history", label: "历史" },
  { href: "/ranking", label: "排名" },
];

export function NavBar() {
  const pathname = usePathname();

  const activeIndex = navItems.findIndex(
    (item) =>
      item.href === "/"
        ? pathname === "/"
        : pathname.startsWith(item.href),
  );

  return (
    <motion.header
      className="fixed top-0 left-0 right-0 z-50 glass border-b border-border"
      initial={{ y: -48 }}
      animate={{ y: 0 }}
      transition={{ type: "spring", damping: 30, stiffness: 300 }}
    >
      <nav className="max-w-7xl mx-auto h-12 px-6 flex items-center justify-between">
        <div className="flex items-center gap-1">
          <span className="text-sm font-semibold text-ink mr-6">
            Quant Selector
          </span>

          <div className="relative flex items-center gap-1">
            {navItems.map((item, i) => (
              <Link
                key={item.href}
                href={item.href}
                className={`
                  relative px-3 py-1.5 text-sm rounded-lg transition-colors duration-150
                  ${
                    i === activeIndex
                      ? "text-ink"
                      : "text-ink-muted hover:text-ink-secondary"
                  }
                `}
              >
                {item.label}
                {i === activeIndex && (
                  <motion.div
                    layoutId="nav-indicator"
                    className="absolute bottom-0 left-2 right-2 h-0.5 bg-accent rounded-full"
                    transition={{
                      type: "spring",
                      damping: 25,
                      stiffness: 300,
                    }}
                  />
                )}
              </Link>
            ))}
          </div>
        </div>

        <SchedulerStatus />
      </nav>
    </motion.header>
  );
}

function SchedulerStatus() {
  // Will be connected to SWR in Phase 5
  return (
    <div className="flex items-center gap-2 text-xs text-ink-muted">
      <span className="w-1.5 h-1.5 rounded-full bg-bear animate-pulse" />
      <span>就绪</span>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/layout/nav-bar.tsx
git commit -m "feat: add NavBar with frosted glass and sliding indicator"
```

---

### Task 4.2: Page Transition Wrapper

**Files:**
- Create: `frontend/src/components/layout/page-transition.tsx`

**Step 1: Write PageTransition component**

Write `frontend/src/components/layout/page-transition.tsx`:

```tsx
"use client";

import { motion } from "framer-motion";
import { usePathname } from "next/navigation";

interface PageTransitionProps {
  children: React.ReactNode;
}

export function PageTransition({ children }: PageTransitionProps) {
  const pathname = usePathname();

  return (
    <motion.div
      key={pathname}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1] }}
    >
      {children}
    </motion.div>
  );
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/layout/page-transition.tsx
git commit -m "feat: add PageTransition with direction-aware animation"
```

---

### Task 4.3: Root Layout Integration

**Files:**
- Modify: `frontend/src/app/layout.tsx`

**Step 1: Write root layout**

Write `frontend/src/app/layout.tsx`:

```tsx
import type { Metadata } from "next";
import { NavBar } from "@/components/layout/nav-bar";
import { ToastContainer } from "@/components/ui/toast";
import "./globals.css";

export const metadata: Metadata = {
  title: "A-Share Quant Selector",
  description: "Quantitative stock selection system",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>
        <NavBar />
        <main className="pt-12 min-h-screen">{children}</main>
        <ToastContainer />
      </body>
    </html>
  );
}
```

**Step 2: Commit**

```bash
git add frontend/src/app/layout.tsx
git commit -m "feat: integrate NavBar and Toast into root layout"
```

---

## Phase 5: API Layer & State Management

### Task 5.1: API Client

**Files:**
- Create: `frontend/src/lib/api.ts`

**Step 1: Write API client**

Write `frontend/src/lib/api.ts`:

```typescript
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

// --- Response types ---

interface ApiResponse<T> {
  success: boolean;
  data: T;
}

export interface StatsData {
  total_stocks: number;
  latest_date: string;
  total_views: number;
  active_views: number;
  scheduler_running: boolean;
}

export interface ViewData {
  id: number;
  name: string;
  params: Record<string, number>;
  b1_params: Record<string, number>;
  b1_enabled: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface StockItem {
  code: string;
  name: string;
  latest_price: number;
  latest_date: string;
  market_cap: number;
  data_count: number;
}

export interface SignalStock {
  code: string;
  name: string;
  strategy: string;
  category: string;
  close: number;
  J: number;
  volume_ratio: number;
  market_cap: number;
  short_term_trend: number;
  bull_bear_line: number;
  reasons: string[];
  similarity_score: number | null;
  matched_case: string | null;
  match_breakdown: Record<string, number> | null;
}

export interface SelectionResult {
  view_id: number;
  view_name: string;
  run_date: string;
  total: number;
  category_count: Record<string, number>;
  stocks: SignalStock[];
}

export interface RankingStock {
  code: string;
  name: string;
  category: string;
  close: number;
  J: number;
  volume_ratio: number;
  market_cap: number;
  similarity_score: number;
  matched_case: string;
  match_breakdown: Record<string, number>;
  views: string[];
  run_date: string;
}

export interface KlineResponse {
  success: boolean;
  code: string;
  name: string;
  period: string;
  data: Array<(string | number)[]>;
}

export interface TaskStatus {
  success: boolean;
  status: string;
  progress: number;
  total: number;
  phase: string;
  data?: SelectionResult;
  error?: string;
}

// --- API functions ---

export const api = {
  getStats: () =>
    request<ApiResponse<StatsData>>("/api/stats"),

  getViews: () =>
    request<ApiResponse<ViewData[]>>("/api/views"),

  getView: (id: number) =>
    request<ApiResponse<ViewData>>(`/api/views/${id}`),

  createView: (body: { name: string; source_id?: number }) =>
    request<ApiResponse<ViewData>>("/api/views", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  updateView: (id: number, body: Partial<ViewData>) =>
    request<ApiResponse<ViewData>>(`/api/views/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  runView: (id: number) =>
    request<{ success: boolean; task_id: string }>(`/api/views/${id}/run`, {
      method: "POST",
    }),

  getRunStatus: (viewId: number, taskId: string) =>
    request<TaskStatus>(
      `/api/views/${viewId}/run/status?task_id=${taskId}`,
    ),

  getViewResults: (viewId: number, limit?: number) =>
    request<ApiResponse<SelectionResult[]>>(
      `/api/views/${viewId}/results${limit ? `?limit=${limit}` : ""}`,
    ),

  getViewResultByDate: (viewId: number, date: string) =>
    request<ApiResponse<SelectionResult>>(
      `/api/views/${viewId}/results/${date}`,
    ),

  getStocks: (page: number = 1, perPage: number = 500) =>
    request<ApiResponse<StockItem[]> & { total: number; page: number; total_pages: number }>(
      `/api/stocks?page=${page}&per_page=${perPage}`,
    ),

  getKline: (code: string, period: string = "daily", days?: number) =>
    request<KlineResponse>(
      `/api/stock/${code}/kline?period=${period}${days ? `&days=${days}` : ""}`,
    ),

  getRanking: () =>
    request<ApiResponse<RankingStock[]> & { total: number; run_date: string }>(
      "/api/ranking",
    ),

  getSchedulerStatus: () =>
    request<ApiResponse<{ running: boolean; running_tasks: Record<string, string> }>>(
      "/api/scheduler/status",
    ),

  startScheduler: () =>
    request<{ success: boolean }>("/api/scheduler/start", { method: "POST" }),

  stopScheduler: () =>
    request<{ success: boolean }>("/api/scheduler/stop", { method: "POST" }),

  updateData: () =>
    request<{ success: boolean; message: string }>("/api/data/update", {
      method: "POST",
    }),
};
```

**Step 2: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add typed API client with all endpoint wrappers"
```

---

### Task 5.2: Zustand Store

**Files:**
- Create: `frontend/src/lib/store.ts`

**Step 1: Write Zustand store**

Write `frontend/src/lib/store.ts`:

```typescript
import { create } from "zustand";
import type { ViewData, SelectionResult, SignalStock } from "./api";

interface AppStore {
  // Views
  views: ViewData[];
  setViews: (views: ViewData[]) => void;
  currentViewId: number | null;
  setCurrentViewId: (id: number | null) => void;

  // Selection results
  selectionResults: SelectionResult | null;
  setSelectionResults: (data: SelectionResult | null) => void;

  // Stock navigation (for K-line page)
  stockNavList: SignalStock[];
  stockNavIndex: number;
  setStockNav: (list: SignalStock[], index: number) => void;
  setStockNavIndex: (index: number) => void;

  // View mode toggle
  stockListViewMode: "list" | "card";
  toggleStockListViewMode: () => void;

  // Category filter
  categoryFilter: string;
  setCategoryFilter: (cat: string) => void;
}

export const useAppStore = create<AppStore>((set) => ({
  views: [],
  setViews: (views) => set({ views }),
  currentViewId: null,
  setCurrentViewId: (id) => set({ currentViewId: id }),

  selectionResults: null,
  setSelectionResults: (data) => set({ selectionResults: data }),

  stockNavList: [],
  stockNavIndex: -1,
  setStockNav: (list, index) =>
    set({ stockNavList: list, stockNavIndex: index }),
  setStockNavIndex: (index) => set({ stockNavIndex: index }),

  stockListViewMode: "list",
  toggleStockListViewMode: () =>
    set((s) => ({
      stockListViewMode: s.stockListViewMode === "list" ? "card" : "list",
    })),

  categoryFilter: "all",
  setCategoryFilter: (cat) => set({ categoryFilter: cat }),
}));
```

**Step 2: Commit**

```bash
git add frontend/src/lib/store.ts
git commit -m "feat: add Zustand store for app state management"
```

---

### Task 5.3: SWR Hooks

**Files:**
- Create: `frontend/src/lib/hooks.ts`

**Step 1: Write SWR hooks**

Write `frontend/src/lib/hooks.ts`:

```typescript
import useSWR from "swr";
import { api } from "./api";

export function useStats() {
  return useSWR("stats", () => api.getStats().then((r) => r.data), {
    refreshInterval: 30_000,
  });
}

export function useViews() {
  return useSWR("views", () => api.getViews().then((r) => r.data));
}

export function useView(id: number | null) {
  return useSWR(
    id !== null ? `view-${id}` : null,
    () => api.getView(id!).then((r) => r.data),
  );
}

export function useStocks(page: number = 1) {
  return useSWR(`stocks-${page}`, () => api.getStocks(page));
}

export function useKline(code: string | null, period: string = "daily") {
  return useSWR(
    code ? `kline-${code}-${period}` : null,
    () => api.getKline(code!, period),
  );
}

export function useRanking() {
  return useSWR("ranking", () => api.getRanking());
}

export function useSchedulerStatus() {
  return useSWR(
    "scheduler-status",
    () => api.getSchedulerStatus().then((r) => r.data),
    { refreshInterval: 5_000 },
  );
}
```

**Step 2: Commit**

```bash
git add frontend/src/lib/hooks.ts
git commit -m "feat: add SWR data fetching hooks"
```

---

## Phase 6: Dashboard Page

### Task 6.1: Stat Card with Number Animation

**Files:**
- Create: `frontend/src/components/ui/animated-number.tsx`

**Step 1: Write AnimatedNumber component**

Write `frontend/src/components/ui/animated-number.tsx`:

```tsx
"use client";

import { motion, useMotionValue, useTransform, animate } from "framer-motion";
import { useEffect, useRef } from "react";

interface AnimatedNumberProps {
  value: number;
  format?: (n: number) => string;
  className?: string;
}

export function AnimatedNumber({
  value,
  format = (n) => Math.round(n).toString(),
  className = "",
}: AnimatedNumberProps) {
  const motionVal = useMotionValue(0);
  const display = useTransform(motionVal, (v) => format(v));
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const controls = animate(motionVal, value, {
      duration: 0.8,
      ease: [0.25, 0.1, 0.25, 1],
    });
    return controls.stop;
  }, [value, motionVal]);

  useEffect(() => {
    const unsubscribe = display.on("change", (v) => {
      if (ref.current) ref.current.textContent = v;
    });
    return unsubscribe;
  }, [display]);

  return <motion.span ref={ref} className={className} />;
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/ui/animated-number.tsx
git commit -m "feat: add AnimatedNumber component with digit flip effect"
```

---

### Task 6.2: Dashboard Page

**Files:**
- Modify: `frontend/src/app/page.tsx`

**Step 1: Write Dashboard page**

Write `frontend/src/app/page.tsx`:

```tsx
"use client";

import { PageTransition } from "@/components/layout/page-transition";
import { Card } from "@/components/ui/card";
import { AnimatedNumber } from "@/components/ui/animated-number";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { useStats, useRanking } from "@/lib/hooks";
import { CATEGORY_LABELS } from "@/lib/tokens";
import { useRouter } from "next/navigation";
import { useAppStore } from "@/lib/store";

export default function DashboardPage() {
  const { data: stats, isLoading: statsLoading } = useStats();
  const { data: ranking, isLoading: rankingLoading } = useRanking();
  const router = useRouter();
  const setStockNav = useAppStore((s) => s.setStockNav);

  const topStocks = ranking?.data?.slice(0, 10) ?? [];

  const handleStockClick = (code: string, index: number) => {
    if (ranking?.data) {
      setStockNav(
        ranking.data.map((s) => ({
          code: s.code,
          name: s.name,
          category: s.category,
          close: s.close,
          J: s.J,
          volume_ratio: s.volume_ratio,
          market_cap: s.market_cap,
          strategy: "",
          short_term_trend: 0,
          bull_bear_line: 0,
          reasons: [],
          similarity_score: s.similarity_score,
          matched_case: s.matched_case,
          match_breakdown: s.match_breakdown,
        })),
        index,
      );
    }
    router.push(`/stock/${code}`);
  };

  return (
    <PageTransition>
      <div className="max-w-6xl mx-auto px-6 py-8">
        <div className="flex items-baseline justify-between mb-8">
          <h1 className="text-2xl font-semibold text-ink">今日选股概览</h1>
          <span className="text-sm text-ink-muted">
            {stats?.latest_date ?? ""}
          </span>
        </div>

        {/* Stats cards */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-10">
          {statsLoading ? (
            Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-2xl" />
            ))
          ) : (
            <>
              <StatCard
                label="总股票数"
                value={stats?.total_stocks ?? 0}
              />
              <StatCard
                label="选股视图"
                value={stats?.total_views ?? 0}
              />
              <StatCard
                label="活跃视图"
                value={stats?.active_views ?? 0}
              />
            </>
          )}
        </div>

        {/* Latest signals */}
        <h2 className="text-lg font-medium text-ink mb-4">最新排名信号</h2>
        <div className="space-y-2">
          {rankingLoading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-14 rounded-xl" />
            ))
          ) : (
            topStocks.map((stock, i) => {
              const catKey = stock.category as keyof typeof CATEGORY_LABELS;
              const badgeVariant =
                stock.category === "bowl_center"
                  ? "bowl"
                  : stock.category === "near_duokong"
                    ? "duokong"
                    : "short";
              return (
                <Card
                  key={stock.code}
                  hoverable
                  className="flex items-center px-5 py-3 gap-4 cursor-pointer"
                  onClick={() => handleStockClick(stock.code, i)}
                >
                  <span className="text-sm font-mono text-ink-secondary w-8">
                    {i + 1}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-ink">
                        {stock.code}
                      </span>
                      <span className="text-sm text-ink-secondary truncate">
                        {stock.name}
                      </span>
                      <Badge variant={badgeVariant}>
                        {CATEGORY_LABELS[catKey] ?? stock.category}
                      </Badge>
                    </div>
                  </div>
                  <span
                    className={`text-sm font-mono ${stock.close > 0 ? "text-bull" : "text-bear"}`}
                  >
                    {stock.close.toFixed(2)}
                  </span>
                  {stock.similarity_score != null && (
                    <span className="text-sm font-mono text-accent">
                      {Math.round(stock.similarity_score)}%
                    </span>
                  )}
                </Card>
              );
            })
          )}
        </div>
      </div>
    </PageTransition>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <Card className="p-6">
      <AnimatedNumber
        value={value}
        className="text-3xl font-mono font-semibold text-ink block"
      />
      <span className="text-sm text-ink-secondary mt-1 block">{label}</span>
    </Card>
  );
}
```

**Step 2: Commit**

```bash
git add frontend/src/app/page.tsx
git commit -m "feat: add Dashboard page with stat cards and ranking signals"
```

---

## Phase 7: Selection Views Page

### Task 7.1: Selection Views Page with View Cards and Params Editor

**Files:**
- Create: `frontend/src/app/selection/page.tsx`
- Create: `frontend/src/components/stock/view-card.tsx`
- Create: `frontend/src/components/stock/params-editor.tsx`
- Create: `frontend/src/components/stock/signal-card.tsx`
- Create: `frontend/src/components/stock/run-progress.tsx`

This is a large task. The implementer should build the params editor with all the sliders (N, M, CAP, J_VAL, M1-M4, duokong_pct, short_pct) matching the original app.js `renderViewParams` behavior. The run progress should poll via `api.getRunStatus()`.

Refer to the original `app.js` lines 100-500 for the exact param definitions, default values, and range limits.

**Key param definitions from original code:**

```
N: {min: 1, max: 8, step: 0.1, unit: "x", label: "成交量倍数"}
M: {min: 5, max: 60, step: 1, unit: "天", label: "回溯天数"}
CAP: {min: 1e8, max: 5e10, step: 1e8, display: "亿", label: "市值门槛"}
J_VAL: {min: -50, max: 60, step: 1, label: "J值上限"}
M1: {min: 5, max: 60, step: 1, default: 14, label: "MA周期1"}
M2: {min: 10, max: 120, step: 1, default: 28, label: "MA周期2"}
M3: {min: 20, max: 200, step: 1, default: 57, label: "MA周期3"}
M4: {min: 30, max: 300, step: 1, default: 114, label: "MA周期4"}
duokong_pct: {min: 0.5, max: 8, step: 0.1, unit: "%", label: "靠近多空线"}
short_pct: {min: 0.5, max: 8, step: 0.1, unit: "%", label: "靠近趋势线"}
```

**Step 1: Build all components, connect API**

**Step 2: Verify with dev server**

```bash
cd frontend && npm run dev
```

Navigate to `/selection`, verify view cards render, params edit, run selection works.

**Step 3: Commit**

```bash
git add frontend/src/app/selection/ frontend/src/components/stock/
git commit -m "feat: add Selection page with view management, params editor, run+poll"
```

---

## Phase 8: Stock List Page (Hybrid Mode)

### Task 8.1: Stock List with List/Card Toggle

**Files:**
- Create: `frontend/src/app/stocks/page.tsx`
- Create: `frontend/src/components/stock/stock-list-row.tsx`
- Create: `frontend/src/components/stock/stock-card.tsx`
- Create: `frontend/src/components/charts/mini-chart.tsx`

**Key behaviors to implement:**
1. List mode: 56px rows, hover left border, search filter by code/name
2. Card mode: grid with mini K-line thumbnails using TradingView Lightweight Charts
3. Toggle button in top-right with Framer Motion `layout` animation on switch
4. Click any stock → navigate to `/stock/[code]`

**MiniChart implementation notes:**
- Use `createChart` from `lightweight-charts`
- Set chart options: `{ width: 240, height: 100, handleScale: false, handleScroll: false }`
- Add area series with `topColor: "rgba(192,120,90,0.2)"`, `bottomColor: "transparent"`, `lineColor: "#c0785a"`
- Data: fetch last 30 days from `/api/stock/<code>/kline?period=daily&days=30`

**Step 1: Build all components**

**Step 2: Verify both view modes work**

```bash
cd frontend && npm run dev
```

**Step 3: Commit**

```bash
git add frontend/src/app/stocks/ frontend/src/components/stock/stock-list-row.tsx frontend/src/components/stock/stock-card.tsx frontend/src/components/charts/mini-chart.tsx
git commit -m "feat: add Stock List page with hybrid list/card view toggle"
```

---

## Phase 9: K-line Fullscreen Page (Critical)

### Task 9.1: KlineChart Component with TradingView Lightweight Charts

**Files:**
- Create: `frontend/src/components/charts/kline-chart.tsx`

**Implementation details:**

1. Create a React component wrapping TradingView Lightweight Charts
2. Three chart panes stacked vertically:
   - **Candlestick** (60%): `addCandlestickSeries()` with `upColor: "#c0392b"`, `downColor: "#27896e"`
   - **Volume** (15%): `addHistogramSeries()` colored by direction
   - **KDJ** (15%): Three `addLineSeries()` for K(blue), D(amber), J(red)
3. Add moving average line series (MA5, MA10, MA20, MA60 or trend/dk lines)
4. Crosshair mode: `CrosshairMode.Normal`
5. Chart background: `"#faf6f0"` (canvas color)
6. Grid lines: `"rgba(45,43,40,0.04)"`
7. Handle `subscribeCrosshairMove` to update the data overlay panel
8. Responsive: `chart.applyOptions({ width: containerWidth })` on resize

**Data mapping from API response:**
```typescript
// Daily kline: [date, open, close, low, high, volume, K, D, J, trend, dk]
// Weekly kline: [date, open, close, low, high, volume, MA5, MA10, MA20, MA60, trend, dk]
```

**Step 1: Build KlineChart component**

**Step 2: Commit**

```bash
git add frontend/src/components/charts/kline-chart.tsx
git commit -m "feat: add KlineChart with TradingView Lightweight Charts"
```

---

### Task 9.2: K-line Fullscreen Page

**Files:**
- Create: `frontend/src/app/stock/[code]/page.tsx`

**Key behaviors:**
1. Read stock code from URL params
2. Fetch kline data via `useKline(code, period)`
3. Show stock header: code, name, latest price + change
4. Period tabs: Daily / Weekly / Monthly with sliding indicator
5. Navigation: Previous/Next stock using `stockNavList` from Zustand store
6. Mobile: swipe left/right to navigate (use Framer Motion `drag` prop)
7. Back button → `router.back()`

**Data overlay panel (frosted glass, top-left):**
```
开 123.45  高 125.00  低 122.00  收 124.50
涨跌 +1.2%  成交量 12.5万
KDJ  K:45.6  D:46.7  J:43.5
```

Update on crosshair move via callback from KlineChart.

**Step 1: Build the page**

**Step 2: Verify navigation from stock list → K-line → back works**

```bash
cd frontend && npm run dev
```

**Step 3: Commit**

```bash
git add frontend/src/app/stock/
git commit -m "feat: add immersive K-line fullscreen page with navigation"
```

---

## Phase 10: History & Ranking Pages

### Task 10.1: History Page

**Files:**
- Create: `frontend/src/app/history/page.tsx`

**Key behaviors:**
1. View selector dropdown (fetch views via `useViews()`)
2. Date list of past results for selected view
3. Click date → expand to show signal cards
4. Reuse `SignalCard` component from Phase 7

**Step 1: Build history page**

**Step 2: Commit**

```bash
git add frontend/src/app/history/
git commit -m "feat: add History page with view-based result browsing"
```

---

### Task 10.2: Ranking Page

**Files:**
- Create: `frontend/src/app/ranking/page.tsx`

**Key behaviors:**
1. Fetch ranking data via `useRanking()`
2. Category filter tabs (all / bowl / duokong / short)
3. Reuse hybrid list/card display from Phase 8
4. Top 3 stocks: copper (#1), silver-gray (#2), bronze (#3) rank badges
5. Click → navigate to K-line page

**Step 1: Build ranking page**

**Step 2: Commit**

```bash
git add frontend/src/app/ranking/
git commit -m "feat: add Ranking page with category filters and medal badges"
```

---

## Phase 11: Micro-interactions & Polish

### Task 11.1: Loading Progress Bar (YouTube-style)

**Files:**
- Create: `frontend/src/components/layout/top-progress.tsx`
- Modify: `frontend/src/app/layout.tsx` (add TopProgress)

**Implementation:**
- 2px copper line at the very top of viewport
- Animate width from 0% → 80% when API request starts (SWR `onLoadingSlow`)
- Jump to 100% and fade out when complete
- Use `NProgress`-style behavior or custom Framer Motion

**Step 1: Build and integrate**

**Step 2: Commit**

```bash
git add frontend/src/components/layout/top-progress.tsx frontend/src/app/layout.tsx
git commit -m "feat: add YouTube-style top progress bar for API requests"
```

---

### Task 11.2: Scroll-Hide NavBar

**Files:**
- Modify: `frontend/src/components/layout/nav-bar.tsx`

**Implementation:**
- Track scroll direction with `useEffect` + `window.addEventListener("scroll")`
- On scroll down: `animate({ y: -48 })` to hide
- On scroll up: `animate({ y: 0 })` to show
- Use `useMotionValueEvent` or manual scroll delta tracking

**Step 1: Add scroll behavior**

**Step 2: Verify scrolling up/down shows/hides nav**

**Step 3: Commit**

```bash
git add frontend/src/components/layout/nav-bar.tsx
git commit -m "feat: add scroll-hide behavior to NavBar"
```

---

### Task 11.3: Mobile Bottom Tab Bar

**Files:**
- Modify: `frontend/src/components/layout/nav-bar.tsx`

**Implementation:**
- Use `useMediaQuery` or CSS `@media (max-width: 640px)` to detect mobile
- On mobile: render bottom tab bar instead of top bar
- Same frosted glass effect, same sliding indicator
- Icons for each tab (use simple SVG icons, no icon library needed)

**Step 1: Add mobile layout**

**Step 2: Test at 375px viewport width**

**Step 3: Commit**

```bash
git add frontend/src/components/layout/nav-bar.tsx
git commit -m "feat: add mobile bottom tab bar with frosted glass"
```

---

## Phase 12: Flask Integration

### Task 12.1: Build Static Export and Serve from Flask

**Files:**
- Create: `frontend/build.sh`
- Modify: `web_server.py` (add route to serve Next.js build)

**Step 1: Create build script**

Write `frontend/build.sh`:

```bash
#!/bin/bash
cd "$(dirname "$0")"
npm run build
echo "Build complete. Output in frontend/out/"
```

```bash
chmod +x frontend/build.sh
```

**Step 2: Add Flask route to serve static files from Next.js build**

Add to `web_server.py` (at the end, before `if __name__`):

```python
# Serve Next.js static export
nextjs_build = Path(__file__).parent / "frontend" / "out"

@app.route("/next/")
@app.route("/next/<path:path>")
def serve_nextjs(path=""):
    """Serve the Next.js static export."""
    if path and (nextjs_build / path).is_file():
        return send_from_directory(nextjs_build, path)
    # SPA fallback
    return send_from_directory(nextjs_build, "index.html")
```

Add `from flask import send_from_directory` to imports.

**Step 3: Build and verify**

```bash
cd frontend && npm run build
cd .. && python web_server.py
```

Visit `http://localhost:18321/next/` to see the new frontend.

**Step 4: Commit**

```bash
git add frontend/build.sh web_server.py
git commit -m "feat: serve Next.js static export from Flask at /next/"
```

---

## Phase 13: Final Verification

### Task 13.1: End-to-End Verification

**Checklist:**

1. [ ] Dashboard loads, stats display with animations
2. [ ] Selection page: view cards render, params edit, save works
3. [ ] Selection page: run selection + polling + results display
4. [ ] Stock list: list/card toggle works, search works
5. [ ] K-line page: candlestick, volume, KDJ render correctly
6. [ ] K-line page: crosshair + data overlay updates
7. [ ] K-line page: daily/weekly period switch
8. [ ] K-line page: prev/next stock navigation
9. [ ] History page: view select, date list, results
10. [ ] Ranking page: filter by category, medal badges
11. [ ] Toast notifications appear and auto-dismiss
12. [ ] Page transitions animate smoothly
13. [ ] NavBar hides on scroll down, shows on scroll up
14. [ ] Mobile: bottom tab bar renders at 375px
15. [ ] Mobile: K-line page is usable on small screens
16. [ ] All colors match the warm cream design tokens
17. [ ] No console errors

**Step 1: Run through checklist manually**

**Step 2: Fix any issues found**

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete frontend redesign - warm cream theme with immersive K-line"
```

---

**Plan complete and saved to `docs/plans/2026-03-09-frontend-redesign-implementation.md`. Two execution options:**

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**
