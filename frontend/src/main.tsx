import { StrictMode, forwardRef } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, type LinkProps } from "react-router";
import { Theme } from "@astryxdesign/core/theme";
import { LinkProvider } from "@astryxdesign/core/Link";
import { neutralTheme } from "@astryxdesign/theme-neutral/built";
import { AppRouter } from "./router";
import "./index.css";

export const RouterLink = forwardRef<HTMLAnchorElement, Omit<LinkProps, "to"> & { href: string }>(
  ({ href, ...props }, ref) => <Link ref={ref} to={href} {...props} />,
);
RouterLink.displayName = "RouterLink";

const routerBasename = import.meta.env.BASE_URL === "/"
  ? undefined
  : import.meta.env.BASE_URL.replace(/\/$/, "");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Theme theme={neutralTheme} mode="light">
      <BrowserRouter basename={routerBasename}>
        <LinkProvider component={RouterLink}>
          <AppRouter />
        </LinkProvider>
      </BrowserRouter>
    </Theme>
  </StrictMode>,
);
