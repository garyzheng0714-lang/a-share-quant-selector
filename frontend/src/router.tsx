import { createBrowserRouter, Navigate } from "react-router-dom";
import { RootLayout } from "@/components/layout/root-layout";

const basename = import.meta.env.BASE_URL.replace(/\/$/, "") || "/";

export const router = createBrowserRouter(
  [
    {
      path: "/",
      element: <RootLayout />,
      children: [
        { index: true, element: <Navigate to="/sectors" replace /> },
        { path: "sectors", lazy: () => import("@/pages/sectors") },
        { path: "sectors/:name", lazy: () => import("@/pages/sector-detail") },
        { path: "stocks", lazy: () => import("@/pages/stocks") },
        { path: "review", lazy: () => import("@/pages/review") },
        { path: "stock/:code", lazy: () => import("@/pages/stock-detail") },
        // 旧路径重定向，书签不失效
        { path: "performance", element: <Navigate to="/review" replace /> },
        { path: "history", element: <Navigate to="/review" replace /> },
        { path: "today", element: <Navigate to="/stocks" replace /> },
      ],
    },
  ],
  { basename },
);
