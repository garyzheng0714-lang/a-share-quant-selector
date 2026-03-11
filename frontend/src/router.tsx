import { createBrowserRouter } from "react-router-dom";
import { RootLayout } from "@/components/layout/root-layout";

const basename = import.meta.env.BASE_URL.replace(/\/$/, "") || "/";

export const router = createBrowserRouter(
  [
    {
      path: "/",
      element: <RootLayout />,
      children: [
        { index: true, lazy: () => import("@/pages/ranking") },
        { path: "history", lazy: () => import("@/pages/history") },
        { path: "stock/:code", lazy: () => import("@/pages/stock-detail") },
      ],
    },
  ],
  { basename },
);
