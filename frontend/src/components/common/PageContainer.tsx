import type { PropsWithChildren } from "react";

export function PageContainer({ children }: PropsWithChildren) {
  return <div className="mx-auto w-full max-w-[1600px]">{children}</div>;
}
