import { lazy, Suspense, useMemo } from "react";
import { RootLayout } from "@/components/layout/root-layout";
import { Navigate, RouteProvider, useLocation } from "@/lib/spa-router";

const SelectPage = lazy(() => import("@/pages/select").then((module) => ({ default: module.Component })));
const StockDetailPage = lazy(() => import("@/pages/stock-detail").then((module) => ({ default: module.Component })));

export function AppRouter() {
  const location = useLocation();
  const route = useMemo(() => {
    const stockMatch = location.pathname.match(/^\/stock\/([^/]+)\/?$/);
    if (stockMatch) return { element: <StockDetailPage />, params: { code: decodeURIComponent(stockMatch[1]) } };
    if (location.pathname === "/select") return { element: <SelectPage />, params: {} };
    return { element: <Navigate to="/select" replace />, params: {} };
  }, [location.pathname]);

  return (
    <RouteProvider
      params={route.params}
      outlet={<Suspense fallback={<div className="min-h-[60vh]" aria-label="页面加载中" />}>{route.element}</Suspense>}
    >
      <RootLayout />
    </RouteProvider>
  );
}
