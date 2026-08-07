/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  forwardRef,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type AnchorHTMLAttributes,
  type MouseEvent,
  type ReactNode,
} from "react";

const NAVIGATION_EVENT = "qselect:navigate";
const basename = import.meta.env.BASE_URL.replace(/\/$/, "");

type Params = Record<string, string | undefined>;
type SearchParamsInit = URLSearchParams | string | Record<string, string>;

interface RouteContextValue {
  outlet: ReactNode;
  params: Params;
}

const RouteContext = createContext<RouteContextValue>({ outlet: null, params: {} });

function subscribe(listener: () => void) {
  window.addEventListener("popstate", listener);
  window.addEventListener(NAVIGATION_EVENT, listener);
  return () => {
    window.removeEventListener("popstate", listener);
    window.removeEventListener(NAVIGATION_EVENT, listener);
  };
}

function snapshot() {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`;
}

function routePath(pathname: string) {
  if (!basename || basename === "/") return pathname;
  const isInsideBase = pathname === basename || pathname.startsWith(`${basename}/`);
  return isInsideBase ? pathname.slice(basename.length) || "/" : pathname;
}

function destination(to: string) {
  if (!basename || basename === "/" || !to.startsWith("/") || to.startsWith("//")) return to;
  return `${basename}${to}`;
}

function isExternal(to: string) {
  return /^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(to);
}

export interface LocationValue {
  pathname: string;
  search: string;
  hash: string;
}

export function useLocation(): LocationValue {
  const current = useSyncExternalStore(subscribe, snapshot, () => "/");
  return useMemo(() => {
    const url = new URL(current, window.location.origin);
    return { pathname: routePath(url.pathname), search: url.search, hash: url.hash };
  }, [current]);
}

export function useNavigate() {
  return useCallback((to: string | number, options?: { replace?: boolean }) => {
    if (typeof to === "number") {
      window.history.go(to);
      return;
    }
    if (isExternal(to)) {
      window.location.assign(to);
      return;
    }
    const target = destination(to);
    if (options?.replace) window.history.replaceState(null, "", target);
    else window.history.pushState(null, "", target);
    window.dispatchEvent(new Event(NAVIGATION_EVENT));
  }, []);
}

export function useSearchParams(): [URLSearchParams, (next: SearchParamsInit, options?: { replace?: boolean }) => void] {
  const location = useLocation();
  const navigate = useNavigate();
  const params = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const setParams = useCallback((next: SearchParamsInit, options?: { replace?: boolean }) => {
    const query = new URLSearchParams(next).toString();
    navigate(`${location.pathname}${query ? `?${query}` : ""}${location.hash}`, options);
  }, [location.hash, location.pathname, navigate]);
  return [params, setParams];
}

export function useParams<T extends Params = Params>() {
  return useContext(RouteContext).params as T;
}

export function Outlet() {
  return useContext(RouteContext).outlet;
}

export function RouteProvider({ children, outlet, params = {} }: { children: ReactNode; outlet: ReactNode; params?: Params }) {
  const value = useMemo(() => ({ outlet, params }), [outlet, params]);
  return <RouteContext.Provider value={value}>{children}</RouteContext.Provider>;
}

export function Navigate({ to, replace = false }: { to: string; replace?: boolean }) {
  const navigate = useNavigate();
  useEffect(() => navigate(to, { replace }), [navigate, replace, to]);
  return null;
}

export interface LinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> {
  to: string;
}

export const Link = forwardRef<HTMLAnchorElement, LinkProps>(({ to, onClick, target, ...props }, ref) => {
  const navigate = useNavigate();
  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey ||
      (target !== undefined && target !== "_self") ||
      isExternal(to)
    ) return;
    event.preventDefault();
    navigate(to);
  };
  return <a ref={ref} href={destination(to)} target={target} onClick={handleClick} {...props} />;
});
Link.displayName = "Link";

export const NavLink = forwardRef<HTMLAnchorElement, LinkProps & { end?: boolean }>(({ end, ...props }, ref) => {
  void end;
  return <Link ref={ref} {...props} />;
});
NavLink.displayName = "NavLink";
