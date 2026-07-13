import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "./index.css";

// Dev-only token handoff receiver. The backend's GET /dev/login (development only)
// 302-redirects here with the token in a URL fragment (#dev_token=<jwt>). localStorage
// is per-origin, so the token MUST be stored here on the frontend origin — a write on
// the backend origin (localhost:8000) is invisible to this one (localhost:5173). We
// store it under the same key App.jsx reads, strip the fragment (so it isn't left in
// the URL/history — fragments never reach servers or logs), and reload clean.
if (import.meta.env?.DEV && window.location.hash.startsWith("#dev_token=")) {
  try {
    const token = decodeURIComponent(window.location.hash.slice("#dev_token=".length));
    if (token) localStorage.setItem("upskillize_token", token);
  } catch { /* noop */ }
  history.replaceState(null, "", window.location.pathname + window.location.search);
  window.location.reload();
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
