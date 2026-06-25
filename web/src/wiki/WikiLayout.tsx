import { Suspense, useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { GITHUB_URL, NAV } from "./nav";
import { toggleTheme, useTheme } from "./theme";

// A small ghost button that flips the palette. Shows the glyph of the theme it
// will switch *to* (☾ when light, ☼ when dark) so the action reads ahead.
function ThemeToggle() {
  const theme = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      className="theme-toggle"
      type="button"
      aria-label={`Switch to ${next} theme`}
      onClick={() => toggleTheme()}
    >
      {theme === "dark" ? "☼" : "☾"}
    </button>
  );
}

// The wiki chrome: a slim top bar (brand + repo link + theme toggle + mobile
// menu) and a left sidebar of sections, with the active page in <Outlet/>.
export function WikiLayout() {
  const [open, setOpen] = useState(false);

  return (
    <div className="wiki">
      <header className="wiki-top">
        <button
          className="menu-toggle"
          aria-label="Toggle navigation"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          ☰
        </button>
        <Link to="/" className="brand" onClick={() => setOpen(false)}>
          pyverdex
        </Link>
        <span className="brand-tag">multi-dimensional test verification</span>
        <span className="top-spacer" />
        <a className="gh-link" href={GITHUB_URL} target="_blank" rel="noreferrer">
          GitHub ↗
        </a>
        <ThemeToggle />
      </header>

      <div className="wiki-body">
        <nav className={`wiki-nav ${open ? "open" : ""}`} aria-label="Wiki sections">
          {NAV.map((section) => (
            <div className="nav-section" key={section.title}>
              <div className="nav-section-title">{section.title}</div>
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
                  onClick={() => setOpen(false)}
                >
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <main className="wiki-main">
          <Suspense fallback={<div className="muted">Loading…</div>}>
            <Outlet />
          </Suspense>
        </main>
      </div>

      <footer className="wiki-foot">
        <span className="ff-h">pyverdex</span>
        <span>coverage counts lines, pyverdex counts proof</span>
        <a href={GITHUB_URL} target="_blank" rel="noreferrer">
          github → JuanSync7/pyverdex
        </a>
        <span className="ff-sig">// a deterministic LangGraph pipeline</span>
      </footer>
    </div>
  );
}
