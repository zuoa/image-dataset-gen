import { Alert } from "antd";

interface UserFacingErrorProps {
  title: string;
  description: string;
  error?: unknown;
  className?: string;
  closable?: boolean;
  onClose?: () => void;
}

function errorDetail(error: unknown) {
  if (typeof error === "string") return error.trim();
  if (error instanceof Error) return error.message.trim();
  return "";
}

export function UserFacingError({
  title,
  description,
  error,
  className,
  closable,
  onClose,
}: UserFacingErrorProps) {
  const detail = errorDetail(error);

  return (
    <Alert
      className={className}
      type="error"
      showIcon
      closable={closable}
      onClose={onClose}
      message={title}
      description={
        <div className="space-y-2">
          <div>{description}</div>
          {detail && detail !== title ? (
            <details className="text-xs text-neutral-500 dark:text-neutral-400">
              <summary className="cursor-pointer select-none">查看技术详情</summary>
              <div className="mt-2 break-words font-mono">{detail}</div>
            </details>
          ) : null}
        </div>
      }
    />
  );
}
