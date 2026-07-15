import { PageTransition } from "@/components/layout/page-transition";
import { QuantPickCard } from "@/components/dashboard/quant-pick-card";

/**
 * 今日页 = 只回答一个问题：**今天买哪个，明天盯哪个。**
 *
 * 2026-07-14 大砍（用户："主页塞那么多信息是没有用的，底部的查看是非常失败的"）。
 * 砍掉的和去向：
 * - AI 荐票卡（自己推另一只票，和量化版打架）→ AI 降级为解释者，并进今日一票卡内
 * - 板块风向侧栏（10 行数字）→ 热度并进每只推荐票（顺不顺风是票的属性，不是独立模块）
 * - 底部三个 tab + 28 个公式卡片瀑布流 → 整体搬到「复盘」页
 *
 * 为什么底部那一坨必须搬走：它是**工具箱**，不是决策。把 28 个公式全铺出来，
 * 本质是在展示"我干了多少活"——而其中 13 个我自己都测出"任何周期都不赚钱"。
 * 用户要的是"傻瓜似的知道今天买哪个"，那 28 张卡没有一张在回答这句话。
 */
export function Component() {
  return (
    <PageTransition>
      <div className="max-w-2xl mx-auto px-4 lg:px-8 py-6 lg:py-10">
        <QuantPickCard />
      </div>
    </PageTransition>
  );
}
