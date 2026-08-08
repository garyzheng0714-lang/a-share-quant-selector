/** 复盘整包 / 单策略本地缓存：切换策略读内存+IndexedDB，不重复打网。 */

import type { StrategyReviewCatalogItem, StrategyReviewResponse } from "@/lib/api";

const DB_NAME = "ashare-quant-review";
const DB_VERSION = 1;
const STORE = "strategy-reviews";
const META_KEY = "__catalog__";

export type ReviewCacheSnapshot = {
  catalog: StrategyReviewCatalogItem[];
  defaultStrategy: string;
  reviews: Record<string, StrategyReviewResponse>;
  fetchedAt: number;
};

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("indexedDB open failed"));
  });
}

async function idbGet<T>(key: string): Promise<T | null> {
  try {
    const db = await openDb();
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readonly");
      const req = tx.objectStore(STORE).get(key);
      req.onsuccess = () => resolve((req.result as T) ?? null);
      req.onerror = () => reject(req.error);
    });
  } catch {
    return null;
  }
}

async function idbSet(key: string, value: unknown): Promise<void> {
  try {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    // 本地缓存失败不阻断主流程
  }
}

export async function loadReviewCache(): Promise<ReviewCacheSnapshot | null> {
  const meta = await idbGet<{
    catalog: StrategyReviewCatalogItem[];
    defaultStrategy: string;
    fetchedAt: number;
  }>(META_KEY);
  if (!meta?.catalog?.length) return null;
  const reviews: Record<string, StrategyReviewResponse> = {};
  await Promise.all(
    meta.catalog
      .filter((item) => item.has_data)
      .map(async (item) => {
        const review = await idbGet<StrategyReviewResponse>(item.key);
        if (review) reviews[item.key] = review;
      }),
  );
  return {
    catalog: meta.catalog,
    defaultStrategy: meta.defaultStrategy,
    reviews,
    fetchedAt: meta.fetchedAt,
  };
}

export async function saveReviewCatalog(
  catalog: StrategyReviewCatalogItem[],
  defaultStrategy: string,
): Promise<void> {
  await idbSet(META_KEY, {
    catalog,
    defaultStrategy,
    fetchedAt: Date.now(),
  });
}

export async function saveStrategyReview(
  strategy: string,
  review: StrategyReviewResponse,
): Promise<void> {
  await idbSet(strategy, review);
}
