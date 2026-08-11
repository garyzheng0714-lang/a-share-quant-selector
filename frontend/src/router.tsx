import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router";
import { RootLayout } from "@/components/layout/root-layout";

const StocksPage = lazy(() => import("@/pages/stocks").then((module) => ({ default: module.Component })));
const ReviewPage = lazy(() => import("@/pages/review").then((module) => ({ default: module.Component })));
const AdminPage = lazy(() => import("@/pages/admin").then((module) => ({ default: module.Component })));
const StockDetailPage = lazy(() => import("@/pages/stock-detail").then((module) => ({ default: module.Component })));
const DataPipelinePage = lazy(() => import("@/pages/data-pipeline").then((module) => ({ default: module.Component })));

export function AppRouter() {
  return (
    <Routes>
      <Route element={<RootLayout />}>
        <Route index element={<Navigate to="/stocks" replace />} />
        <Route path="stocks" element={<Page><StocksPage /></Page>} />
        <Route path="review" element={<Page><ReviewPage /></Page>} />
        <Route path="admin" element={<Page><AdminPage /></Page>} />
        <Route path="data-pipeline" element={<Page><DataPipelinePage /></Page>} />
        <Route path="stock/:code" element={<Page><StockDetailPage /></Page>} />
        <Route path="performance" element={<Navigate to="/review" replace />} />
        <Route path="history" element={<Navigate to="/review" replace />} />
        <Route path="sectors/*" element={<Navigate to="/stocks" replace />} />
        <Route path="today" element={<Navigate to="/stocks" replace />} />
        <Route path="*" element={<Navigate to="/stocks" replace />} />
      </Route>
    </Routes>
  );
}

function Page({ children }: { children: ReactNode }) {
  return <Suspense fallback={<div className="min-h-[60vh]" aria-label="页面加载中" />}>{children}</Suspense>;
}
