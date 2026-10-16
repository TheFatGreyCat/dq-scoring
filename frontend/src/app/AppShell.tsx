import {
  BookOpen,
  Activity,
  ClipboardCheck,
  Database,
  Globe,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Menu,
  Moon,
  Play,
  Settings,
  SlidersHorizontal,
  Sun,
  X,
} from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router";
import { logout } from "../api/endpoints";
import { useSession } from "../features/auth/useSession";
import { useI18n } from "../lib/i18n";
import { BrandMark } from "./BrandMark";
import { useUiPreferences } from "./useUiPreferences";
import { useIdentity } from "../features/auth/useIdentity";
import { ProblemAlert } from "../components/ProblemAlert";
import { UsageGuide } from "../components/UsageGuide";

function Nav({ onNavigate, collapsed = false }: { onNavigate?: () => void; collapsed?: boolean }) {
  const { t } = useI18n();
  const identity = useIdentity();

  const navItems = [
    { to: "/", label: t("nav.overview"), icon: LayoutDashboard, end: true },
    { to: "/assets", label: t("nav.assets"), icon: Database },
    { to: "/rulesets", label: t("nav.rulesets"), icon: ListChecks },
    { to: "/policies", label: t("nav.policies"), icon: SlidersHorizontal },
    { to: "/templates", label: t("nav.templates"), icon: BookOpen },
    { to: "/runs", label: t("nav.runs"), icon: Play },
    { to: "/assessments", label: t("nav.assessments"), icon: ClipboardCheck },
    { to: "/settings", label: t("nav.settings"), icon: Settings },
  ];
  if (identity.data?.role === "WORKSPACE_ADMIN") navItems.splice(7, 0, { to: "/monitor", label: t("operations.title"), icon: Activity });

  return (
    <ul className="space-y-1 p-3">
      {navItems.map(({ to, label, icon: Icon, end }) => (
        <li key={to}>
          <NavLink
            to={to}
            end={end}
            onClick={onNavigate}
            aria-label={label}
            title={collapsed ? label : undefined}
            className={({ isActive }) =>
              `relative flex items-center gap-3 min-h-11 px-3 rounded-control font-medium transition-colors ${
                isActive
                  ? "bg-nav-active text-nav-fg before:absolute before:left-0 before:inset-y-2 before:w-1 before:rounded-full before:bg-brand"
                  : "text-nav-fg/85 hover:bg-nav-active/60"
              }`
            }
          >
            <Icon aria-hidden className="size-5" />
            <span className={collapsed ? "sr-only" : ""}>{label}</span>
          </NavLink>
        </li>
      ))}
    </ul>
  );
}

export function AppShell() {
  const { theme, setTheme, collapsed, setCollapsed } = useUiPreferences();
  const identity = useIdentity();
  const { lang, toggleLang, t } = useI18n();
  const { email } = useSession();
  const navigate = useNavigate();
  const [drawerOpen, setDrawerOpen] = useState(false);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
  };

  const signOut = async () => {
    await logout().catch(() => undefined);
    navigate("/login", { replace: true });
  };

  return (
    <div className="h-dvh overflow-hidden flex flex-col">
      <div className="h-1 shrink-0 bg-brand" aria-hidden />
      <header className="shrink-0 z-30 flex items-center gap-3 h-16 px-4 bg-surface border-b border-border">
        <button
          type="button"
          className="lg:hidden grid place-items-center size-11 rounded-control hover:bg-surface-muted cursor-pointer"
          aria-label={t(drawerOpen ? "nav.close" : "nav.open")}
          aria-expanded={drawerOpen}
          aria-controls="mobile-nav"
          onClick={() => setDrawerOpen((o) => !o)}
        >
          {drawerOpen ? <X aria-hidden /> : <Menu aria-hidden />}
        </button>
        <BrandMark />
        <div className="leading-tight">
          <p className="font-bold">{t("header.title")}</p>
          <p className="text-xs text-fg-muted hidden sm:block">{t("header.subtitle")}</p>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          <UsageGuide />
          {email && (
            <span className="hidden md:inline text-sm text-fg-muted mr-1" title={t("header.signed_in_as")}>
              {email}
            </span>
          )}

          {/* Language Switcher right next to Theme Toggle */}
          <button
            type="button"
            onClick={toggleLang}
            className="flex items-center gap-1 px-2.5 h-10 rounded-control border border-border hover:bg-surface-muted cursor-pointer text-xs font-semibold transition-colors shadow-xs"
            aria-label={t("header.lang.switch")}
            title={t("header.lang.switch")}
          >
            <Globe aria-hidden className="size-4 text-brand" />
            <span className="font-mono">{lang === "vi" ? "VI" : "EN"}</span>
          </button>

          {/* Theme Toggle */}
          <button
            type="button"
            onClick={toggleTheme}
            className="grid place-items-center size-10 rounded-control border border-border hover:bg-surface-muted cursor-pointer shadow-xs"
            aria-label={theme === "dark" ? t("header.theme.to_light") : t("header.theme.to_dark")}
            title={theme === "dark" ? t("header.theme.to_light") : t("header.theme.to_dark")}
          >
            {theme === "dark" ? <Sun aria-hidden className="size-4 text-amber-400" /> : <Moon aria-hidden className="size-4 text-slate-700" />}
          </button>

          <button type="button" onClick={signOut} aria-label={t("header.sign_out")} className="btn-secondary ml-1">
            <LogOut aria-hidden className="size-4" />
            <span className="hidden sm:inline">{t("header.sign_out")}</span>
          </button>
        </div>
      </header>

      <div className="flex flex-1 min-h-0">
        <nav id="desktop-nav" aria-label={t("nav.main")} className={`hidden lg:flex flex-col h-full shrink-0 bg-nav ${collapsed ? "w-16" : "w-60"}`}>
          <div className="flex-1 min-h-0 overflow-y-auto"><Nav collapsed={collapsed} /></div>
          <button className="min-h-11 shrink-0 text-nav-fg" aria-expanded={!collapsed} aria-controls="desktop-nav" aria-label={t(collapsed ? "nav.expand" : "nav.collapse")} onClick={() => setCollapsed(!collapsed)}>{collapsed ? "»" : "«"}</button>
        </nav>
        {drawerOpen && (
          <div
            id="mobile-nav"
            className="fixed inset-0 z-40 lg:hidden flex"
            role="dialog"
            aria-modal="true"
            aria-label={t("nav.drawer")}
          >
            <div className="fixed inset-0 bg-black/50" onClick={() => setDrawerOpen(false)} aria-hidden />
            <nav className="relative z-10 w-72 max-w-[80vw] bg-surface h-full flex flex-col p-4 shadow-xl">
              <div className="flex items-center justify-between pb-3 border-b border-border">
                <span className="font-semibold">{t("header.title")}</span>
                <button
                  type="button"
                  className="grid place-items-center size-10 rounded-control hover:bg-surface-muted cursor-pointer"
                  onClick={() => setDrawerOpen(false)}
                  aria-label={t("nav.close")}
                >
                  <X aria-hidden />
                </button>
              </div>
              <div className="mt-2 flex-1 overflow-y-auto">
                <Nav onNavigate={() => setDrawerOpen(false)} />
              </div>
            </nav>
          </div>
        )}
        <main id="main" className="flex-1 min-w-0 min-h-0 overflow-y-auto" tabIndex={-1}>
          <div className="p-4 md:p-8 max-w-6xl w-full mx-auto">
            {identity.isPending ? <p aria-busy="true">…</p> : identity.isError ? <ProblemAlert error={identity.error} onRetry={() => void identity.refetch()} /> : <Outlet />}
          </div>
        </main>
      </div>
    </div>
  );
}
