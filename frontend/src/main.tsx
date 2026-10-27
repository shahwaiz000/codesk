import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./index.css";
import { AuthGate } from "./auth";
import { BusinessDayProvider } from "./businessDay";
import Layout from "./components/Layout";
import Collections from "./pages/Collections";
import Drivers from "./pages/Drivers";
import PosCheck from "./pages/PosCheck";
import Settings from "./pages/Settings";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthGate>
        <BusinessDayProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Navigate to="/collections" replace />} />
            <Route path="collections" element={<Collections />} />
            <Route path="pos" element={<PosCheck />} />
            <Route path="drivers" element={<Drivers />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
        </BusinessDayProvider>
      </AuthGate>
    </BrowserRouter>
  </React.StrictMode>,
);
