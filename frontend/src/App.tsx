import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { api } from "./lib/api";
import { useAuth } from "./lib/auth";
import type { NavModule } from "./lib/types";
import { AppShell } from "./components/AppShell";
import type { NavSection } from "./components/AppShell";
import { ErrorState, Loading } from "./components";
import { LoginPage } from "./features/auth/LoginPage";
import { ControlCenterRoutes } from "./features/admin/ControlCenter";
import { ClientDashboardRoutes } from "./features/client/ClientDashboard";

/** Gate: unauthenticated users never render an app screen at all. */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const { me, loading } = useAuth();
  if (loading) return <Loading rows={4} label="Checking your session" />;
  if (!me) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function ControlCenter() {
  const { me } = useAuth();
  if (!me?.can_access_control_center) {
    return <Navigate to="/" replace />;
  }

  const sections: NavSection[] = [
    {
      heading: "Platform",
      items: [
        { to: "/admin", label: "Control Center", icon: "◉" },
        { to: "/admin/businesses", label: "Businesses", icon: "▦" },
        { to: "/admin/conversations", label: "Conversations", icon: "◍" },
        { to: "/admin/delivery", label: "Delivery", icon: "◎" },
        { to: "/admin/calendar", label: "Calendar", icon: "▣" },
        { to: "/admin/webhooks", label: "Webhooks", icon: "◌" },
        { to: "/admin/audit", label: "Audit log", icon: "❑" },
      ],
    },
  ];

  return (
    <AppShell sections={sections} contextLabel="NTX Automation Co. — internal">
      <ControlCenterRoutes readOnly={me.is_read_only} />
    </AppShell>
  );
}

function ClientWorkspace() {
  const { businessId = "" } = useParams();
  const { me } = useAuth();
  const [modules, setModules] = useState<NavModule[] | null>(null);
  const [businessName, setBusinessName] = useState("");
  const [role, setRole] = useState("viewer");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<{ business: { name: string }; modules: NavModule[]; role: string }>(
        `/api/dashboard/businesses/${businessId}/navigation`,
      )
      .then((payload) => {
        if (cancelled) return;
        setModules(payload.modules);
        setBusinessName(payload.business.name);
        setRole(payload.role);
      })
      .catch((err: Error) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [businessId]);

  if (error) {
    return (
      <div className="content">
        <ErrorState title="No access" body={error} />
      </div>
    );
  }
  if (!modules) return <Loading rows={5} label="Loading your dashboard" />;

  const readOnly = Boolean(me?.is_read_only) || role === "viewer";

  // Navigation is built from server-supplied entitlements, so a module the
  // business is not entitled to never appears -- and its API refuses it too.
  const sections: NavSection[] = [
    {
      heading: businessName,
      items: modules.map((module) => ({
        to: module.implemented
          ? `/b/${businessId}${module.key === "overview" ? "" : `/${module.key}`}`
          : "#",
        label: module.label,
        icon: iconFor(module.key),
        locked: !module.implemented,
        lockReason: module.description,
      })),
    },
  ];

  return (
    <AppShell sections={sections} contextLabel={`Good afternoon, ${businessName}`}>
      <ClientDashboardRoutes modules={modules} readOnly={readOnly} />
    </AppShell>
  );
}

function iconFor(key: string): string {
  const icons: Record<string, string> = {
    overview: "⌂",
    leads: "◈",
    conversations: "◍",
    appointments: "▣",
    ai_intake: "◉",
    website: "◇",
    local_seo: "◎",
    reviews: "★",
    analytics: "▤",
    campaigns: "➤",
    contacts: "❑",
    qr_sources: "▦",
    coupons: "◆",
    settings: "⚙",
  };
  return icons[key] ?? "•";
}

/** Sends each signed-in user to the right home without leaking the other one. */
function HomeRedirect() {
  const { me } = useAuth();
  if (!me) return <Navigate to="/login" replace />;
  if (me.can_access_control_center) return <Navigate to="/admin" replace />;
  if (me.businesses.length > 0) return <Navigate to={`/b/${me.businesses[0].id}`} replace />;
  return (
    <div className="content">
      <ErrorState
        title="No business assigned"
        body="Your account is not a member of any business yet. Contact NTX Automation Co. to get access."
      />
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/admin/*"
        element={
          <RequireAuth>
            <ControlCenter />
          </RequireAuth>
        }
      />
      <Route
        path="/b/:businessId/*"
        element={
          <RequireAuth>
            <ClientWorkspace />
          </RequireAuth>
        }
      />
      <Route
        path="/"
        element={
          <RequireAuth>
            <HomeRedirect />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
