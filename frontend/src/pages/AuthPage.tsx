import { useState } from "react";
import { Navigate } from "react-router-dom";

import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { SectionCard } from "../components/ui/SectionCard";
import { useAuthStore } from "../store/auth";

export function AuthPage() {
  const { token, signIn, isLoading, error } = useAuthStore();
  const [username, setUsername] = useState("dataset");
  const [password, setPassword] = useState("Dataset123!");

  if (token) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="relative min-h-screen overflow-hidden bg-white text-neutral-900 dark:bg-neutral-950 dark:text-white">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(0,0,0,0.035),transparent_38%),linear-gradient(180deg,rgba(0,0,0,0.018),transparent_30%)] dark:bg-[radial-gradient(circle_at_top,rgba(255,255,255,0.05),transparent_38%),linear-gradient(180deg,rgba(255,255,255,0.025),transparent_30%)]" />
      <div className="relative mx-auto grid min-h-screen max-w-6xl items-center gap-8 px-6 py-10 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="max-w-2xl">
          <div className="text-xs uppercase tracking-[0.35em] text-neutral-400 dark:text-neutral-500">Synthetic Vision Ops Platform</div>
          <h1 className="mt-6 text-5xl font-medium leading-tight md:text-6xl">Dataset Forge</h1>
          <p className="mt-4 max-w-2xl text-xl leading-9 text-neutral-700 dark:text-neutral-200">
            用结构化工作流压缩图像数据集生产周期。
          </p>
          <p className="mt-6 max-w-xl text-base leading-8 text-neutral-500 dark:text-neutral-400">
            从需求配置、Prompt 构建、图片生成、增强、自动标注到导出，全链路在一个控制台里完成。
          </p>
        </div>

        <SectionCard className="mx-auto w-full max-w-md p-8 dark:bg-[#14171c]/95">
          <div className="space-y-4">
            <Input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="账号" />
            <Input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="密码"
            />
            <Button className="w-full" disabled={isLoading} onClick={() => signIn(username, password)}>
              {isLoading ? "处理中..." : "进入控制台"}
            </Button>
            {error ? <div className="text-sm text-red-600 dark:text-red-300">{error}</div> : null}
            <div className="rounded-2xl border border-neutral-200 bg-neutral-100 p-4 text-sm text-neutral-500 dark:border-white/10 dark:bg-black/30 dark:text-neutral-400">
              默认账号：`dataset / Dataset123!`
            </div>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}
