import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import { useStation } from "../stations";
import { StationPicker } from "./StationPicker";
import { Icon, IconName, Mark } from "./icons";

type NavItem = { to: string; label: string; icon: IconName };
/* Pages are added here as each stage is finished, so the menu never points at an empty page. */
export const NAV: { title: string; items: NavItem[] }[] = [
  { title: "Daily desk", items: [
    { to: "/", label: "Dashboard", icon: "dashboard" },
    { to: "/collections", label: "Collections", icon: "cash" },
    { to: "/pos", label: "POS check", icon: "card" },
    { to: "/expenses", label: "Expenses & advances", icon: "receipt" },
    { to: "/deposits", label: "Bank deposits", icon: "bank" },
  ] },
  { title: "Records", items: [
    { to: "/reports", label: "Reports", icon: "report" },
    { to: "/ask", label: "Ask CODesk", icon: "spark" },
    { to: "/drivers", label: "Drivers", icon: "drivers" },
    { to: "/stations", label: "Stations", icon: "warehouse" },
  ] },
];

function Sidebar() {
  const { username, loginEnabled, logout } = useAuth();
  return (
    <div className="flex h-full flex-col">
      <Link to="/" className="flex items-center gap-3 px-6 pb-6 pt-7">
        <Mark />
        <span className="leading-tight">
          <span className="block text-[16px] font-semibold text-white">CODesk</span>
          <span className="block text-xs text-ledger-300">Logistics finance</span>
        </span>
      </Link>
      <StationPicker />
      <nav aria-label="Main" className="flex-1 space-y-7 overflow-y-auto px-3">
        {NAV.map((g) => (
          <div key={g.title}>
            <p className="mb-2 px-3 text-xs text-ledger-300/80">{g.title}</p>
            <div className="space-y-0.5">
              {g.items.map((l) => (
                <NavLink key={l.to} to={l.to} end={l.to === "/"}
                  className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${isActive ? "bg-white/10 text-white" : "text-ledger-300 hover:bg-white/[0.05] hover:text-white"}`}>
                  {({ isActive }) => (<>
                    <Icon name={l.icon} className={`h-[18px] w-[18px] ${isActive ? "text-brass-glow" : ""}`} />
                    {l.label}
                  </>)}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>
      <div className="space-y-0.5 border-t border-white/[0.07] px-3 py-3">
        <NavLink to="/settings" className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium ${isActive ? "bg-white/10 text-white" : "text-ledger-300 hover:bg-white/[0.05] hover:text-white"}`}>
          <Icon name="settings" className="h-[18px] w-[18px]" />Settings
        </NavLink>
        {loginEnabled && username && (
          <button onClick={logout} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm text-ledger-300 hover:bg-white/[0.05] hover:text-white">
            <Icon name="logout" className="h-[18px] w-[18px]" />
            <span className="min-w-0 flex-1 truncate">Log out <span className="text-ledger-300/70">({username})</span></span>
          </button>
        )}
      </div>
    </div>
  );
}

export default function Layout() {
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const { station, version } = useStation();

  useEffect(() => { setOpen(false); }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="min-h-screen md:flex">
      <aside className="hidden bg-ledger-900 md:sticky md:top-0 md:block md:h-screen md:w-60 md:shrink-0">
        <Sidebar />
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden">
          <button aria-label="Close menu" onClick={() => setOpen(false)} className="absolute inset-0 bg-ledger-950/60" />
          <aside id="mobile-menu" className="relative h-full w-72 max-w-[85vw] animate-slideIn bg-ledger-900">
            <button aria-label="Close menu" onClick={() => setOpen(false)} className="absolute right-3 top-6 rounded-lg p-2 text-ledger-300 hover:bg-white/10">
              <Icon name="close" />
            </button>
            <Sidebar />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-paper-line bg-paper/90 px-4 backdrop-blur md:hidden">
          <button aria-label="Open menu" aria-expanded={open} aria-controls="mobile-menu" onClick={() => setOpen(true)}
            className="rounded-lg p-2 text-ink-soft hover:bg-white"><Icon name="menu" /></button>
          <Mark className="h-7 w-7" /><span className="font-semibold">CODesk</span>
          <span className="ml-auto flex items-center gap-1 truncate text-xs text-ink-soft"><Icon name="pin" className="h-3.5 w-3.5" />{station ? station.name : "All stations"}</span>
        </header>
        <main className="mx-auto w-full max-w-[1280px] min-w-0 flex-1 px-4 pb-12 pt-6 md:px-10 md:pt-9"><Outlet key={version} /></main>
      </div>
    </div>
  );
}
