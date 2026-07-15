import { useState, useCallback } from "react";
import { Copy, Check } from "lucide-react";

interface CopyButtonProps {
  text: string;
  className?: string;
}

export function CopyButton({ text, className = "" }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      navigator.clipboard.writeText(text).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      });
    },
    [text],
  );

  return (
    <button
      onClick={handleCopy}
      aria-label="复制代码"
      className={`inline-flex items-center justify-center shrink-0 rounded transition-colors ${
        copied
          ? "text-bear"
          : "text-ink-muted hover:text-ink"
      } ${className}`}
      title="复制代码"
    >
      {copied ? (
        <Check size={14} strokeWidth={2.5} />
      ) : (
        <Copy size={14} strokeWidth={2} />
      )}
    </button>
  );
}
