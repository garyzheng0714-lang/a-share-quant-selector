import { StrictMode, forwardRef } from "react";
import { createRoot } from "react-dom/client";
import { Link, type LinkProps } from "@/lib/spa-router";
import { Theme } from "@astryxdesign/core/theme";
import { LinkProvider } from "@astryxdesign/core/Link";
import { neutralTheme } from "@astryxdesign/theme-neutral/built";
import { AppRouter } from "./router";
import "./index.css";

export const RouterLink = forwardRef<HTMLAnchorElement, Omit<LinkProps, "to"> & { href: string }>(
  ({ href, ...props }, ref) => <Link ref={ref} to={href} {...props} />,
);
RouterLink.displayName = "RouterLink";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Theme theme={neutralTheme} mode="light">
      <LinkProvider component={RouterLink}>
        <AppRouter />
      </LinkProvider>
    </Theme>
  </StrictMode>,
);
