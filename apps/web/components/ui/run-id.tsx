import { cn } from "@/lib/utils";

export function RunId({ value, className }: { value: string; className?: string }) {
  return (
    <p className={cn("min-w-0 break-all text-xs leading-5 text-muted-foreground", className)}>
      <span className="font-medium text-foreground">Run ID:</span>{" "}
      <code className="font-mono tabular-nums">{value}</code>
    </p>
  );
}
