import { create } from "zustand";
import type { SignalStock } from "./api";

interface AppStore {
  stockNavList: SignalStock[];
  stockNavIndex: number;
  setStockNav: (list: SignalStock[], index: number) => void;
  setStockNavIndex: (index: number) => void;

}

export const useAppStore = create<AppStore>((set) => ({
  stockNavList: [],
  stockNavIndex: -1,
  setStockNav: (list, index) => set({ stockNavList: list, stockNavIndex: index }),
  setStockNavIndex: (index) => set({ stockNavIndex: index }),
}));
