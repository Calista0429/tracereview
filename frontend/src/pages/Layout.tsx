import { Link, Outlet } from "react-router-dom";

export function Layout() {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="masthead">
        <Link to="/" className="masthead__brand" aria-label="TraceReview home">
          TraceReview
        </Link>
        <p className="masthead__note">
          Every number traced back to its PDF. Fictional demo data, one local reviewer.
        </p>
      </header>
      <main id="main" className="main">
        <Outlet />
      </main>
    </>
  );
}
