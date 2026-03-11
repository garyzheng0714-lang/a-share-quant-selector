import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "@/components/ui";
import { ease, duration } from "@/lib/tokens";

interface WelcomeModalProps {
  onDismiss: () => void;
}

const STEPS = [
  {
    title: "欢迎使用 QSelect",
    description:
      "A 股量化选股系统，基于多因子模型帮你快速筛选信号股。告别手动翻 K 线，让数据驱动你的投资决策。",
    icon: (
      <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
        <rect
          x="4"
          y="8"
          width="32"
          height="24"
          rx="4"
          stroke="currentColor"
          strokeWidth="2"
        />
        <path
          d="M12 24l4-6 4 3 8-9"
          stroke="var(--color-accent)"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="28" cy="12" r="2" fill="var(--color-accent)" />
      </svg>
    ),
  },
  {
    title: "核心工作流",
    description:
      "创建选股视图 → 调整策略参数（量价、均线、市值）→ 运行选股 → 查看信号股和综合排名。每个视图是一套独立的参数组合，方便你对比不同策略。",
    icon: (
      <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
        <circle
          cx="10"
          cy="20"
          r="5"
          stroke="currentColor"
          strokeWidth="2"
        />
        <circle
          cx="20"
          cy="20"
          r="5"
          stroke="var(--color-accent)"
          strokeWidth="2"
        />
        <circle
          cx="30"
          cy="20"
          r="5"
          stroke="currentColor"
          strokeWidth="2"
        />
        <path
          d="M15 20h-0.5M25 20h-0.5"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
    ),
  },
  {
    title: "开始探索",
    description:
      "系统已内置默认策略参数，你可以直接创建视图并运行选股。结果页会展示信号股的 KDJ、量能、形态等多维匹配度分析。",
    icon: (
      <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
        <path
          d="M20 6l2.47 7.6h7.99l-6.47 4.7 2.47 7.6L20 21.2l-6.47 4.7 2.47-7.6-6.47-4.7h7.99L20 6z"
          stroke="var(--color-accent)"
          strokeWidth="2"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
];

export function WelcomeModal({ onDismiss }: WelcomeModalProps) {
  const [step, setStep] = useState(0);
  const navigate = useNavigate();
  const isLast = step === STEPS.length - 1;

  const handleNext = () => {
    if (isLast) {
      onDismiss();
      navigate("/selection");
    } else {
      setStep((s) => s + 1);
    }
  };

  const handlePrev = () => {
    if (step > 0) setStep((s) => s - 1);
  };

  const current = STEPS[step];

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: duration.normal }}
      className="fixed inset-0 z-[200] flex items-center justify-center p-4"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-canvas/80 backdrop-blur-sm"
        onClick={onDismiss}
      />

      {/* Card */}
      <motion.div
        initial={{ scale: 0.96, y: 12 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.96, y: 12 }}
        transition={ease.spring}
        className="glass-elevated glow-accent relative w-full max-w-md rounded-3xl p-6 sm:p-8 shadow-float"
      >
        {/* Skip button */}
        <button
          onClick={onDismiss}
          className="absolute top-4 right-4 text-xs text-ink-muted hover:text-ink transition-colors"
        >
          跳过
        </button>

        {/* Step content */}
        <div className="flex flex-col items-center text-center">
          <AnimatePresence mode="wait">
            <motion.div
              key={step}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: duration.fast }}
              className="flex flex-col items-center"
            >
              <div className="glass-card w-16 h-16 rounded-2xl flex items-center justify-center mb-6 text-ink-secondary">
                {current.icon}
              </div>
              <h2 className="text-lg font-semibold text-ink mb-2">
                {current.title}
              </h2>
              <p className="text-sm text-ink-secondary leading-relaxed max-w-xs">
                {current.description}
              </p>
            </motion.div>
          </AnimatePresence>
        </div>

        {/* Step indicators */}
        <div className="flex justify-center gap-2 mt-6 mb-6">
          {STEPS.map((_, i) => (
            <motion.div
              key={i}
              className="h-1.5 rounded-full"
              animate={{
                width: i === step ? 24 : 8,
                backgroundColor:
                  i === step
                    ? "var(--color-accent)"
                    : "rgba(255,255,255,0.15)",
              }}
              transition={{ duration: duration.fast }}
            />
          ))}
        </div>

        {/* Actions */}
        <div className="flex items-center justify-between">
          <div>
            {step > 0 && (
              <Button variant="ghost" size="sm" onClick={handlePrev}>
                上一步
              </Button>
            )}
          </div>
          <Button size="sm" onClick={handleNext}>
            {isLast ? "去创建视图" : "下一步"}
          </Button>
        </div>
      </motion.div>
    </motion.div>
  );
}
