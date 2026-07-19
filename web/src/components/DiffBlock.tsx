import { useMemo } from "react";

interface DiffBlockProps {
  diff: string;
  maxLines?: number;
  compact?: boolean;
}

type DiffLineKind = "meta" | "added" | "removed" | "hunk" | "context";

function classifyLine(line: string): DiffLineKind {
  if (line.startsWith("+++") || line.startsWith("---")) return "meta";
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+")) return "added";
  if (line.startsWith("-")) return "removed";
  return "context";
}

export function DiffBlock({ diff, maxLines, compact = false }: DiffBlockProps) {
  const lines = useMemo(() => {
    const all = diff.split("\n");
    return typeof maxLines === "number" ? all.slice(0, maxLines) : all;
  }, [diff, maxLines]);

  return (
    <div className={`diff-block ${compact ? "compact" : ""}`}>
      {lines.map((line, index) => {
        const kind = classifyLine(line);
        return (
          <div key={`${index}-${line.slice(0, 12)}`} className={`diff-line diff-line-${kind}`}>
            <span className="diff-line-gutter">{kind === "context" && !line ? "·" : line.slice(0, 1) || " "}</span>
            <code className="diff-line-code">{line || " "}</code>
          </div>
        );
      })}
    </div>
  );
}
