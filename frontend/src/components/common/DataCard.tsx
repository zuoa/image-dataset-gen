import { Card, Statistic } from "antd";
import type { ReactNode } from "react";

interface DataCardProps {
  label: ReactNode;
  value: ReactNode;
  suffix?: ReactNode;
  className?: string;
}

export function DataCard({ label, value, suffix, className }: DataCardProps) {
  return (
    <Card className={className}>
      <Statistic title={label} value={value as string | number} suffix={suffix} />
    </Card>
  );
}

interface StatCardProps {
  label: ReactNode;
  value: ReactNode;
  prefix?: ReactNode;
  suffix?: ReactNode;
  className?: string;
}

export function StatCard({ label, value, prefix, suffix, className }: StatCardProps) {
  return (
    <Card className={className}>
      <div className="text-xs uppercase tracking-[0.2em] text-neutral-500 dark:text-neutral-400">{label}</div>
      <div className="mt-3 flex items-baseline gap-2">
        {prefix ? <span className="text-lg text-neutral-500">{prefix}</span> : null}
        <div className="text-3xl font-medium text-neutral-900 dark:text-white">{value}</div>
        {suffix ? <span className="text-sm text-neutral-500">{suffix}</span> : null}
      </div>
    </Card>
  );
}
