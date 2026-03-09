import { createBrowserRouter } from "react-router-dom";
import { RootLayout } from "@/components/layout/root-layout";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <RootLayout />,
    children: [
      { index: true, lazy: () => import("@/pages/dashboard") },
      { path: "selection", lazy: () => import("@/pages/selection") },
      { path: "stocks", lazy: () => import("@/pages/stocks") },
      { path: "history", lazy: () => import("@/pages/history") },
      { path: "ranking", lazy: () => import("@/pages/ranking") },
      { path: "stock/:code", lazy: () => import("@/pages/stock-detail") },
    ],
  },
]);
