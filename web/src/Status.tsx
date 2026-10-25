// The record, read straight from the `trace` branch on GitHub. This page is the
// agent's to change; the branch it reads is not — so a reader who doubts the page
// can follow the link and read the same files.
import { marked } from "marked";
import { useEffect, useState } from "react";
import { BRANCH, DIM, FAINT, INK, RAW, RULE, WHITE, ago, stamp } from "./theme.ts";

interface Index {
  born: string | null;
  wakes: number;
  last: string | null;
  mean_dur_s: number;
  interval: { declared: number | null; mean_gap_s: number | null };
  tools: Record<string, number>;
  generated_tokens: number;
  rests: number;
  diary_entries: number;
  files_changed_since_birth: string[];
  days: string[];
  exits: { t: string; code: number }[];
}

interface Message {
  type: string;
  text?: string;
  tool?: string;
  args?: unknown;
  status?: string;
}

interface Change {
  path: string;
  by?: string;
  author?: string;
  diff?: string;
  deleted?: boolean;
}

interface Beat {
  t: string;
  wake?: number;
  event?: string;
  code?: number;
  dur_s?: number;
  sleep_s?: number;
  rest?: boolean;
  error?: string;
  label?: string;
  messages?: Message[];
  changed?: Change[];
}

function own(beat: Beat): Change[] {
  return beat.changed?.filter((c) => c.by !== "outside") ?? [];
}

function outside(beat: Beat): Change[] {
  return beat.changed?.filter((c) => c.by === "outside") ?? [];
}

function fmtDur(s: number | null | undefined): string {
  if (s == null) return "–";
  if (s < 90) return `${Math.round(s)}s`;
  if (s < 5400) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

export function Status() {
  const [index, setIndex] = useState<Index | null | undefined>(undefined);
  const [day, setDay] = useState<string | null>(null);
  const [beats, setBeats] = useState<Beat[] | null>(null);

  useEffect(() => {
    fetch(`${RAW}index.json`, { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null))
      .then((i: Index | null) => {
        setIndex(i);
        if (i?.days.length) setDay([...i.days].sort().at(-1)!);
      })
      .catch(() => setIndex(null));
  }, []);

  useEffect(() => {
    if (!day) return;
    setBeats(null);
    fetch(`${RAW}${day}.jsonl`, { cache: "no-cache" })
      .then((r) => (r.ok ? r.text() : ""))
      .then((text) =>
        setBeats(
          text
            .split("\n")
            .filter(Boolean)
            .map((l) => JSON.parse(l) as Beat)
            .reverse(),
        ))
      .catch(() => setBeats([]));
  }, [day]);

  if (index === undefined) return <p style={{ color: DIM }}>…</p>;
  if (index === null)
    return (
      <p style={{ color: DIM }}>
        No record yet. The loop writes one from its first beat, to the{" "}
        <a href={BRANCH} style={{ color: INK }}>trace branch</a>.
      </p>
    );

  const days = [...index.days].sort().reverse();
  const lastExit = index.exits.at(-1);
  const metrics: [string, string][] = [
    ["born", index.born ? stamp(index.born) : "–"],
    ["wakes", String(index.wakes)],
    ["last beat", index.last ? ago(Date.now() - Date.parse(index.last)) : "–"],
    ["mean turn", fmtDur(index.mean_dur_s)],
    ["heartbeat", `${fmtDur(index.interval.declared)} set · ${fmtDur(index.interval.mean_gap_s)} measured`],
    ["rests taken", String(index.rests)],
    ["tokens generated", index.generated_tokens.toLocaleString()],
    ["diary entries", String(index.diary_entries)],
    ["files it changed", String(index.files_changed_since_birth.length)],
    ["loop exits", lastExit ? `${index.exits.length} · last code ${lastExit.code}` : "0"],
  ];

  return (
    <>
      <p style={{ color: DIM, marginTop: 0 }}>
        Every beat of the loop is written to a branch of the repository that can be added to but
        not rewritten. This page reads that branch; the model can change this page but not the
        branch. Compare against{" "}
        <a href={BRANCH} style={{ color: INK }}>the source</a> if in doubt. GitHub serves it with a
        few minutes of cache.
      </p>

      <dl
        style={{
          display: "grid",
          gridTemplateColumns: "max-content 1fr",
          columnGap: 24,
          rowGap: 4,
          margin: "2rem 0",
          fontSize: "0.9rem",
        }}
      >
        {metrics.map(([k, v]) => (
          <Row key={k} k={k} v={v} />
        ))}
        <Row
          k="tools"
          v={
            Object.entries(index.tools)
              .sort((a, b) => b[1] - a[1])
              .map(([t, n]) => `${t} ${n}`)
              .join(" · ") || "–"
          }
        />
        {index.files_changed_since_birth.length > 0 && (
          <Row k="changed" v={index.files_changed_since_birth.join(", ")} />
        )}
      </dl>

      <hr style={{ border: 0, borderTop: `1px solid ${RULE}`, margin: "2rem 0" }} />

      <p style={{ color: FAINT, fontSize: "0.8rem" }}>
        {days.map((d) => (
          <a
            key={d}
            href="#"
            onClick={(e) => {
              e.preventDefault();
              setDay(d);
            }}
            style={{ color: d === day ? WHITE : DIM, marginRight: 16, textDecoration: d === day ? "none" : "underline" }}
          >
            {d}
          </a>
        ))}
      </p>

      {beats === null && <p style={{ color: DIM }}>…</p>}
      {beats?.length === 0 && <p style={{ color: DIM }}>(nothing recorded for this day)</p>}
      {beats?.map((b, i) => <BeatView key={`${b.t}-${i}`} beat={b} />)}
    </>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt style={{ color: FAINT }}>{k}</dt>
      <dd style={{ margin: 0, color: INK, wordBreak: "break-word" }}>{v}</dd>
    </>
  );
}

function BeatView({ beat }: { beat: Beat }) {
  const time = stamp(beat.t).slice(11);
  if (beat.event) {
    const label =
      beat.event === "loop-exit"
        ? beat.code === 0
          ? "the loop exited cleanly (code 0)"
          : `the loop ended with code ${beat.code}`
        : beat.event === "poke-failed"
          ? "the loop beat but the agent did not answer"
          : beat.event;
    return (
      <p style={{ color: beat.event === "loop-exit" ? WHITE : DIM, fontSize: "0.85rem" }}>
        <span style={{ color: FAINT }}>{time}</span> · {label}
      </p>
    );
  }
  const calls = beat.messages?.filter((m) => m.type === "tool_call_message") ?? [];
  const first = beat.messages?.find((m) => m.type === "reasoning_message" || m.type === "assistant_message")?.text ?? "";
  return (
    <details style={{ marginBottom: "1rem" }}>
      <summary style={{ cursor: "pointer", color: INK, fontSize: "0.85rem" }}>
        <span style={{ color: FAINT }}>{time}</span> · #{beat.wake} · {fmtDur(beat.dur_s)} ·{" "}
        {calls.length} tool call{calls.length === 1 ? "" : "s"}
        {beat.rest && ` · then rested ${fmtDur(beat.sleep_s)}`}
        {own(beat).length > 0 && ` · changed ${own(beat).length} file${own(beat).length === 1 ? "" : "s"}`}
        {outside(beat).length > 0 && (
          <span style={{ color: FAINT }}>{` · ${outside(beat).length} file${outside(beat).length === 1 ? "" : "s"} arrived from outside`}</span>
        )}
        {beat.error && " · error"}
        <span style={{ color: DIM }}> {first.slice(0, 90)}</span>
        {beat.label && <span style={{ color: WHITE }}> · “{beat.label}”</span>}
      </summary>
      <div style={{ paddingLeft: 16, borderLeft: `1px solid ${RULE}`, marginTop: 8, fontSize: "0.85rem" }}>
        {beat.messages?.map((m, i) => <MessageView key={i} m={m} />)}
        {beat.error && <pre style={pre("#7a4a4a")}>{beat.error}</pre>}
        {beat.changed?.map((c) => (
          <div key={c.path} style={{ marginTop: 12 }}>
            <div style={{ color: c.by === "outside" ? FAINT : WHITE }}>
              {c.by === "outside" ? `arrived from outside (${c.author}): ` : c.deleted ? "deleted " : "changed "}
              {c.path}
            </div>
            {c.diff && <Diff text={c.diff} />}
          </div>
        ))}
      </div>
    </details>
  );
}

function MessageView({ m }: { m: Message }) {
  switch (m.type) {
    case "reasoning_message":
      return <Prose text={m.text ?? ""} color={DIM} italic />;
    case "assistant_message":
      return <Prose text={m.text ?? ""} color={WHITE} />;
    case "tool_call_message": {
      const args = typeof m.args === "string" ? m.args : JSON.stringify(m.args);
      return (
        <pre style={pre(INK)}>
          <span style={{ color: WHITE }}>{m.tool}</span> {args}
        </pre>
      );
    }
    case "tool_return_message":
      return <pre style={pre(m.status === "error" ? "#7a4a4a" : FAINT)}>{m.text}</pre>;
    default:
      return null;
  }
}

function Diff({ text }: { text: string }) {
  return (
    <pre style={pre(FAINT)}>
      {text.split("\n").map((l, i) => (
        <span
          key={i}
          style={{ color: l.startsWith("+") ? "#6a9a6a" : l.startsWith("-") ? "#9a6a6a" : undefined, display: "block" }}
        >
          {l}
        </span>
      ))}
    </pre>
  );
}

export function Prose({ text, color, italic }: { text: string; color: string; italic?: boolean }) {
  return (
    <div
      className="prose"
      style={{ color, fontStyle: italic ? "italic" : "normal", margin: "8px 0", overflowWrap: "anywhere" }}
      dangerouslySetInnerHTML={{ __html: marked.parse(text, { async: false }) }}
    />
  );
}

function pre(color: string): React.CSSProperties {
  return { whiteSpace: "pre-wrap", wordBreak: "break-word", margin: "6px 0", fontFamily: "inherit", color };
}
