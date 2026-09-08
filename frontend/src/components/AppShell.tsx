import { useEffect, useRef, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "../lib/auth";

export interface NavEntry {
  to: string;
  label: string;
  icon: string;
  locked?: boolean;
  lockReason?: string;
}

export interface NavSection {
  heading: string;
  items: NavEntry[];
}

export function AppShell({
  sections,
  contextLabel,
  children,
}: {
  sections: NavSection[];
  contextLabel: string;
  children: ReactNode;
}) {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  // Escape closes the drawer and returns focus to the control that opened it.
  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDrawerOpen(false);
        menuButtonRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="shell">
      {drawerOpen && (
        <button
          type="button"
          className="drawer-backdrop"
          aria-label="Close navigation"
          onClick={() => setDrawerOpen(false)}
        />
      )}

      <nav
        className={drawerOpen ? "sidebar sidebar--open" : "sidebar"}
        aria-label="Primary"
        id="primary-navigation"
      >
        <div className="brand">
          <span className="brand__mark">NTX</span>
          <span className="brand__sub">Automation Co.</span>
        </div>

        {sections.map((section) => (
          <div className="nav" key={section.heading}>
            <p className="nav__heading">{section.heading}</p>
            {section.items.map((item) =>
              item.locked ? (
                <span
                  key={item.label}
                  className="nav__item nav__item--locked"
                  title={item.lockReason}
                >
                  <span>
                    <span aria-hidden="true" style={{ marginRight: 8 }}>
                      {item.icon}
                    </span>
                    {item.label}
                  </span>
                  <span className="nav__lock">Soon</span>
                </span>
              ) : (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end
                  className={({ isActive }) =>
                    isActive ? "nav__item nav__item--active" : "nav__item"
                  }
                  onClick={() => setDrawerOpen(false)}
                >
                  <span>
                    <span aria-hidden="true" style={{ marginRight: 8 }}>
                      {item.icon}
                    </span>
                    {item.label}
                  </span>
                </NavLink>
              ),
            )}
          </div>
        ))}
      </nav>

      <div className="main">
        <header className="topbar">
          <button
            ref={menuButtonRef}
            type="button"
            className="btn btn--icon menu-button"
            aria-label="Open navigation"
            aria-expanded={drawerOpen}
            aria-controls="primary-navigation"
            onClick={() => setDrawerOpen(true)}
          >
            <span aria-hidden="true">☰</span>
          </button>
          <strong style={{ fontSize: 13 }}>{contextLabel}</strong>
          <div className="topbar__spacer" />
          <div className="topbar__user">
            <span>{me?.user.display_name ?? me?.user.email}</span>
            <button type="button" className="btn" onClick={handleLogout}>
              Sign out
            </button>
          </div>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
