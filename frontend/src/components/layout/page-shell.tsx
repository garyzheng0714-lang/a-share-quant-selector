import type { ReactNode } from "react";
import { Heading } from "@astryxdesign/core/Heading";
import { Text } from "@astryxdesign/core/Text";
import { Stack } from "@astryxdesign/core/Stack";

/**
 * 全站内容页统一壳：工作台档，max-width 1440，页边与块间距一把尺子。
 * 全宽三栏工作台（FactorWorkbench / stock-detail）不要包这层。
 */
export function PageShell({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-5 sm:py-7 ${className}`}>
      <div className="flex flex-col gap-5">{children}</div>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  endContent,
}: {
  title: ReactNode;
  description?: ReactNode;
  endContent?: ReactNode;
}) {
  return (
    <header className="mb-5 flex min-h-12 items-start justify-between gap-4 border-b border-border pb-4">
      <div className="min-w-0">
        <Heading level={1} className="truncate">
          {title}
        </Heading>
        {description ? (
          <Text type="supporting" className="mt-1 block leading-5">
            {description}
          </Text>
        ) : null}
      </div>
      {endContent ? <div className="shrink-0 self-center">{endContent}</div> : null}
    </header>
  );
}

export function PageStack({ children }: { children: ReactNode }) {
  return (
    <Stack gap={4} width="100%">
      {children}
    </Stack>
  );
}
