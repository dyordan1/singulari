import { useEffect, useState } from "react";
import { Prose } from "./Status.tsx";
import { BRANCH, DIM, FAINT, RAW, WHITE } from "./theme.ts";

interface Brief {
  day: string;
  text: string;
}

/** The auto-autobiography: every daily entry, newest first, read from the
 * trace branch. Written by the loop with the same model after the day ends;
 * the per-wake lines it is built from stay on the branch. */
export function Auto() {
  const [briefs, setBriefs] = useState<Brief[] | null>(null);

  useEffect(() => {
    fetch(`${RAW}index.json`, { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null))
      .then((index: { briefs?: string[] } | null) =>
        Promise.all(
          [...(index?.briefs ?? [])].reverse().map((day) =>
            fetch(`${RAW}briefs/${day}.md`, { cache: "no-cache" })
              .then((r) => r.text())
              .then((text) => ({ day, text })),
          ),
        ),
      )
      .then(setBriefs)
      .catch(() => setBriefs([]));
  }, []);

  return (
    <>
      <p style={{ color: FAINT, fontSize: "0.8rem", marginTop: 0 }}>
        Written by the loop at the end of each day, from <a href={BRANCH} style={{ color: "inherit" }}>the record</a>,
        with the same model, in its voice.
      </p>
      {briefs === null && <p style={{ color: DIM }}>…</p>}
      {briefs?.length === 0 && <p style={{ color: DIM }}>No entry yet. The first is written at midnight UTC.</p>}
      {briefs?.map((b) => (
        <article key={b.day} style={{ marginBottom: "2.5rem" }}>
          <div style={{ color: FAINT, fontSize: "0.8rem", marginBottom: 8 }}>{b.day}</div>
          <Prose text={b.text} color={WHITE} />
        </article>
      ))}
    </>
  );
}
