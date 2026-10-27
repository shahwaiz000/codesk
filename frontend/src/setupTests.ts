import "@testing-library/jest-dom/vitest";

// jsdom has no ResizeObserver, which chart components (Recharts) need.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = globalThis.ResizeObserver ?? (ResizeObserverStub as unknown as typeof ResizeObserver);
