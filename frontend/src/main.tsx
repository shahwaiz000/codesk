import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./index.css";
import { AuthGate } from "./auth";
import { BusinessDayProvider } from "./businessDay";
import Layout from "./components/Layout";
import Ask from "./pages/Ask";
import Collections from "./pages/Collections";
import Dashboard from "./pages/Dashboard";
import Deposits from "./pages/Deposits";
import Drivers from "./pages/Drivers";
import Expenses from "./pages/Expenses";
import PosCheck from "./pages/PosCheck";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthGate>
        <BusinessDayProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="collections" element={<Collections />} />
            <Route path="pos" element={<PosCheck />} />
            <Route path="expenses" element={<Expenses />} />
            <Route path="deposits" element={<Deposits />} />
            <Route path="reports" element={<Reports />} />
            <Route path="ask" element={<Ask />} />
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
