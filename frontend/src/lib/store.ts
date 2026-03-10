import { create } from "zustand";
import type { ViewData, SelectionResult, SignalStock } from "./api";

interface AppStore {
  views: ViewData[];
  setViews: (views: ViewData[]) => void;
  currentViewId: number | null;
  setCurrentViewId: (id: number | null) => void;

  selectionResults: SelectionResult | null;
  setSelectionResults: (data: SelectionResult | null) => void;

  stockNavList: SignalStock[];
  stockNavIndex: number;
  setStockNav: (list: SignalStock[], index: number) => void;
  setStockNavIndex: (index: number) => void;

  stockListViewMode: "list" | "card";
  toggleStockListViewMode: () => void;

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
  setStockNav: (list, index) => set({ stockNavList: list, stockNavIndex: index }),
  setStockNavIndex: (index) => set({ stockNavIndex: index }),

  stockListViewMode: "list",
  toggleStockListViewMode: () =>
    set((s) => ({ stockListViewMode: s.stockListViewMode === "list" ? "card" : "list" })),

  categoryFilter: "all",
  setCategoryFilter: (cat) => set({ categoryFilter: cat }),
}));
