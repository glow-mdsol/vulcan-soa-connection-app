import type { ReactNode } from "react";

export default function AppShell({
  children,
  actions,
}: {
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header-inner">
          <div>
            <h1 className="brand">
              <span className="brand-mark" aria-hidden="true">
                ◈
              </span>
              Vulcan Schedule of Activities
            </h1>
            <p className="brand-tag">Study enrollment and visit coordination</p>
          </div>
          {actions}
        </div>
      </header>
      <main className="container">{children}</main>
    </div>
  );
}
