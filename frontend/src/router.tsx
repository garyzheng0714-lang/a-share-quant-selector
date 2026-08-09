import { lazy, Suspense, useMemo } from "react";
import { RootLayout } from "@/components/layout/root-layout";
import { Navigate, RouteProvider, useLocation } from "@/lib/spa-router";

const StocksPage = lazy(() => import("@/pages/stocks").then((module) => ({ default: module.Component })));
const ReviewPage = lazy(() => import("@/pages/review").then((module) => ({ default: module.Component })));
const AdminPage = lazy(() => import("@/pages/admin").then((module) => ({ default: module.Component })));
const StockDetailPage = lazy(() => import("@/pages/stock-detail").then((module) => ({ default: module.Component })));
const DataPipelinePage = lazy(() => import("@/pages/data-pipeline").then((module) => ({ default: module.Component })));

export function AppRouter() {
  const location = useLocation();
  const route = useMemo(() => {
    const stockMatch = location.pathname.match(/^\/stock\/([^/]+)\/?$/);
    if (stockMatch) return { element: <StockDetailPage />, params: { code: decodeURIComponent(stockMatch[1]) } };
    if (location.pathname === "/stocks") return { element: <StocksPage />, params: {} };
    if (location.pathname === "/review") return { element: <ReviewPage />, params: {} };
    if (location.pathname === "/admin") return { element: <AdminPage />, params: {} };
    if (location.pathname === "/data-pipeline") return { element: <DataPipelinePage />, params: {} };
    if (["/performance", "/history"].includes(location.pathname)) return { element: <Navigate to="/review" replace />, params: {} };
    if (location.pathname === "/sectors" || location.pathname.startsWith("/sectors/")) return { element: <Navigate to="/stocks" replace />, params: {} };
    if (location.pathname === "/today") return { element: <Navigate to="/stocks" replace />, params: {} };
    return { element: <Navigate to="/stocks" replace />, params: {} };
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
