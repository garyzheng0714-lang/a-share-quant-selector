import { motion, AnimatePresence } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { Card, Button } from "@/components/ui";
import { useOnboardingState } from "@/lib/onboarding";
import { duration, ease } from "@/lib/tokens";

const STEPS = [
  {
    num: 1,
    title: "创建视图",
    desc: "定义你的选股策略参数组合",
  },
  {
    num: 2,
    title: "调整参数",
    desc: "设定量价、均线、市值等筛选条件",
  },
  {
    num: 3,
    title: "运行选股",
    desc: "一键执行策略，查看信号股列表",
  },
];

export function WorkflowGuideBanner() {
  const { guideDismissed, dismissGuide } = useOnboardingState();
  const navigate = useNavigate();

  return (
    <AnimatePresence>
      {!guideDismissed && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: duration.normal, ease: ease.default }}
          className="overflow-hidden"
        >
          <Card className="p-4 sm:p-5 border border-accent/20">
            <div className="flex items-start justify-between mb-4">
              <div>
                <p className="text-sm font-semibold text-ink">
                  快速上手
                </p>
                <p className="text-xs text-ink-muted mt-0.5">
                  3 步完成你的第一次量化选股
                </p>
              </div>
              <button
                onClick={dismissGuide}
                className="text-ink-muted hover:text-ink transition-colors p-1 -mr-1 -mt-1"
                aria-label="关闭引导"
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 16 16"
                  fill="none"
                >
                  <path
                    d="M4 4l8 8M12 4l-8 8"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4 mb-4">
              {STEPS.map((step) => (
                <div
                  key={step.num}
                  className="flex items-start gap-3"
                >
                  <div className="w-7 h-7 rounded-full bg-accent/10 text-accent flex items-center justify-center text-xs font-bold shrink-0">
                    {step.num}
                  </div>
                  <div>
                    <p className="text-xs font-medium text-ink">
                      {step.title}
                    </p>
                    <p className="text-[11px] text-ink-muted mt-0.5">
                      {step.desc}
                    </p>
                  </div>
                </div>
              ))}
            </div>

            <div className="flex justify-end">
              <Button
                size="sm"
                onClick={() => {
                  navigate("/selection");
                }}
              >
                去创建视图
              </Button>
            </div>
          </Card>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
