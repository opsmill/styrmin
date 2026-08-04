import { Toaster } from 'frontend';

// ⚠️ STATIC-CARD LIMITATION
// `Toaster` only renders Base UI's Toast.Provider + empty Portal/Viewport.
// Actual toasts are pushed at runtime via `Toast.useToastManager().add(...)`
// (see `useToast`), so there is NO prop to seed a visible toast statically —
// and the viewport is a fixed, portalled, empty container. In a static
// headless card this renders effectively nothing visible. Flagged: needs
// runtime triggering / a cardMode override, or mark skip.

export const Empty = () => (
  <Toaster>
    <div style={{ padding: 16, fontSize: 14, color: 'var(--muted-foreground)' }}>
      Toast host — notifications appear here at runtime.
    </div>
  </Toaster>
);
