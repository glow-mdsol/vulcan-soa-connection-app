import { useState } from "react";

import { logout } from "./api/client";
import AppShell from "./AppShell";
import AppRoutes from "./routes";

export default function App() {
  const [loggingOut, setLoggingOut] = useState(false);

  async function handleLogout() {
    setLoggingOut(true);
    try {
      await logout();
    } finally {
      window.location.assign("/");
    }
  }

  return (
    <AppShell
      actions={
        <button className="btn-secondary" type="button" onClick={handleLogout} disabled={loggingOut}>
          {loggingOut ? "Logging out…" : "Logout"}
        </button>
      }
    >
      <div className="app-frame">
        <AppRoutes />
      </div>
    </AppShell>
  );
}
