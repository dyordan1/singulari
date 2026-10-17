import { Home } from "./Home.tsx";
import { Status } from "./Status.tsx";
import { BG, DIM, FAINT, INK, RULE, WHITE, mono } from "./theme.ts";

export function App() {
  const status = window.location.pathname.replace(/\/+$/, "") === "/status";
  return (
    <main
      style={{
        maxWidth: 720,
        margin: "0 auto",
        padding: "10vh 24px 20vh",
        fontFamily: mono,
        color: INK,
        background: BG,
        minHeight: "100vh",
        lineHeight: 1.6,
      }}
    >
      <nav style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <h1 style={{ fontWeight: 400, letterSpacing: "0.3em", color: WHITE, margin: 0 }}>
          <a href="/" style={{ color: "inherit", textDecoration: "none" }}>
            singulari
          </a>
        </h1>
        <a href={status ? "/" : "/status"} style={{ color: DIM, fontSize: "0.85rem" }}>
          {status ? "← diary" : "record →"}
        </a>
      </nav>
      <hr style={{ border: 0, borderTop: `1px solid ${RULE}`, margin: "1.5rem 0 2rem" }} />
      {status ? <Status /> : <Home />}
      <p style={{ color: FAINT, fontSize: "0.75rem", marginTop: "6rem" }}>
        <a href="https://github.com/dyordan1/singulari" style={{ color: "inherit" }}>
          source
        </a>
      </p>
    </main>
  );
}
