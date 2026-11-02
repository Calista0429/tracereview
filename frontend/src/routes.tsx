import { Link, type RouteObject } from "react-router-dom";

import { DocumentListPage } from "./pages/DocumentListPage";
import { Layout } from "./pages/Layout";
import { ReviewPage } from "./pages/ReviewPage";

function NotFound() {
  return (
    <div className="page-message">
      <h1>This page does not exist</h1>
      <p>
        <Link to="/">Go to all documents</Link>
      </p>
    </div>
  );
}

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <DocumentListPage /> },
      { path: "documents/:id", element: <ReviewPage /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];
