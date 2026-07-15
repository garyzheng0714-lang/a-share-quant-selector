import { useState } from "react";
import { CandidateList } from "@/components/today/candidate-list";
import { SuperB1Card } from "@/components/today/super-b1-card";
import { FactorWorkbench } from "@/components/today/factor-workbench";

type ListSource = "factors" | "strategy" | "superb1";

const SOURCES: { key: ListSource; label: string }[] = [
  { key: "factors", label: "策略因子" },
  { key: "strategy", label: "碗口B1" },
  { key: "superb1", label: "超级B1" },
];

/**
 * 选股名单 = 各套公式今天分别选了哪些票。
 *
 * 2026-07-14 从主页搬到复盘页，原样保留三选一切换。搬迁理由（用户："底部的查看
 * 是非常失败的"）：这是**研究用的工具箱，不是决策**。主页要回答"今天买哪个"，
 * 而 28 个公式里有 13 个我自己都测出"任何周期都不赚钱"——把它们铺在首页最大的
 * 一块地上，是在展示工作量，不是在帮用户下单。放进复盘页（研究区）才名正言顺。
 */
export function SelectionLists() {
  const [source, setSource] = useState<ListSource>("factors");

  return (
    <div>
      <div className="flex items-center gap-1 bg-surface rounded-full p-1 mb-4 w-full sm:w-fit">
        {SOURCES.map((s) => (
          <button
            key={s.key}
            onClick={() => setSource(s.key)}
            className={`flex-1 sm:flex-initial px-4 py-1.5 text-xs sm:text-sm rounded-full whitespace-nowrap transition-colors duration-150 ${
              source === s.key
                ? "bg-elevated text-ink font-medium ring-1 ring-border"
                : "text-ink-muted hover:text-ink-secondary"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {source === "factors" ? (
        <FactorWorkbench />
      ) : source === "strategy" ? (
        <CandidateList />
      ) : (
        <SuperB1Card />
      )}
    </div>
  );
}
