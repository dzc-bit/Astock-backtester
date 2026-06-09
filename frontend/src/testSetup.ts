import "@testing-library/jest-dom/vitest";

class ResizeObserverMock {
  private callback: ResizeObserverCallback;

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
  }

  observe(target: Element) {
    this.callback(
      [
        {
          target,
          contentRect: {
            width: 800,
            height: 220,
            top: 0,
            left: 0,
            bottom: 220,
            right: 800,
            x: 0,
            y: 0,
            toJSON: () => ({})
          } as DOMRectReadOnly
        } as ResizeObserverEntry
      ],
      this
    );
  }

  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverMock;

Object.defineProperty(HTMLElement.prototype, "getBoundingClientRect", {
  configurable: true,
  value() {
    return {
      width: 800,
      height: 220,
      top: 0,
      left: 0,
      bottom: 220,
      right: 800,
      x: 0,
      y: 0,
      toJSON: () => ({})
    };
  }
});
