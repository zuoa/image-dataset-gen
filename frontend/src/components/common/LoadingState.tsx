import { Skeleton } from "antd";

interface LoadingStateProps {
  rows?: number;
  className?: string;
}

export function LoadingState({ rows = 3, className }: LoadingStateProps) {
  return (
    <div className={className}>
      <Skeleton active paragraph={{ rows }} />
    </div>
  );
}

export function CardLoadingState({ className }: { className?: string }) {
  return (
    <div className={className}>
      <Skeleton active paragraph={{ rows: 4 }} />
    </div>
  );
}
