import { IconButton } from "@astryxdesign/core/IconButton";
import { Icon } from "@astryxdesign/core/Icon";
import { useCallback, useState } from "react";

interface CopyButtonProps {
  text: string;
  className?: string;
}

export function CopyButton({ text, className }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(
    (event: React.MouseEvent) => {
      event.stopPropagation();
      void navigator.clipboard.writeText(text).then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      });
    },
    [text],
  );

  return (
    <IconButton
      className={className}
      label={copied ? "已复制" : "复制代码"}
      tooltip={copied ? "已复制" : "复制代码"}
      variant="ghost"
      size="sm"
      icon={<Icon icon={copied ? "success" : "copy"} size="xsm" color={copied ? "success" : "secondary"} />}
      onClick={handleCopy}
    />
  );
}
