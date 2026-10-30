import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./index.css";
import { AuthGate } from "./auth";
import { BusinessDayProvider } from "./businessDay";
import Layout from "./components/Layout";
import Ask from "./pages/Ask";
import Dashboard from "./pages/Dashboard";
import Deposits from "./pages/Deposits";
import Drivers from "./pages/Drivers";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";
import StationDay from "./pages/StationDay";
import Stations from "./pages/Stations";
import { StationProvider } from "./stations";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthGate>
        <StationProvider>
        <BusinessDayProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="station" element={<StationDay />} />
            <Route path="collections" element={<StationDay tab="collection" />} />
            <Route path="pos" element={<StationDay tab="pos" />} />
            <Route path="expenses" element={<StationDay tab="expenses" />} />
            <Route path="deposits" element={<Deposits />} />
            <Route path="reports" element={<Reports />} />
            <Route path="ask" element={<Ask />} />
            <Route path="drivers" element={<Drivers />} />
            <Route path="stations" element={<Stations />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
        </BusinessDayProvider>
        </StationProvider>
      </AuthGate>
    </BrowserRouter>
  </React.StrictMode>,
);
