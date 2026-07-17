import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { getLoginCaptcha, type LoginCaptcha } from "../api/auth";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { SectionCard } from "../components/ui/SectionCard";
import { useAuthStore } from "../store/auth";

export function AuthPage() {
  const { status, signIn, isSubmitting, error } = useAuthStore();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [captchaCode, setCaptchaCode] = useState("");
  const [captcha, setCaptcha] = useState<LoginCaptcha | null>(null);
  const [isCaptchaLoading, setIsCaptchaLoading] = useState(false);
  const [captchaError, setCaptchaError] = useState<string | null>(null);

  const loadCaptcha = useCallback(async () => {
    setIsCaptchaLoading(true);
    setCaptchaError(null);
    try {
      setCaptcha(await getLoginCaptcha());
    } catch (captchaLoadError) {
      setCaptcha(null);
      setCaptchaError((captchaLoadError as Error).message || "验证码加载失败");
    } finally {
      setIsCaptchaLoading(false);
    }
  }, []);

  useEffect(() => {
    if (status === "anonymous" && captcha === null && !isCaptchaLoading && !captchaError) {
      void loadCaptcha();
    }
  }, [captcha, captchaError, isCaptchaLoading, loadCaptcha, status]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!captcha) {
      await loadCaptcha();
      return;
    }
    const succeeded = await signIn(
      username.trim(),
      password,
      captcha.captchaId,
      captchaCode.trim(),
    );
    if (!succeeded) {
      setCaptchaCode("");
      setCaptcha(null);
    }
  };

  if (status === "checking") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-white text-sm text-neutral-500 dark:bg-neutral-950 dark:text-neutral-400">
        正在恢复登录状态…
      </div>
    );
  }

  if (status === "authenticated") {
    const requestedPath = (location.state as { from?: unknown } | null)?.from;
    const destination =
      typeof requestedPath === "string" && requestedPath.startsWith("/") && !requestedPath.startsWith("//")
        ? requestedPath
        : "/";
    return <Navigate to={destination} replace />;
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
          <div>
            <div className="text-xs font-medium uppercase tracking-[0.24em] text-neutral-400 dark:text-neutral-500">
              Secure access
            </div>
            <h2 className="mt-3 text-2xl font-medium">登录控制台</h2>
            <p className="mt-2 text-sm leading-6 text-neutral-500 dark:text-neutral-400">
              登录状态会在当前浏览器安全续期，无需在刷新后重新输入账号。
            </p>
          </div>

          <form className="mt-7 space-y-5" onSubmit={handleSubmit}>
            <label className="block space-y-2 text-sm text-neutral-600 dark:text-neutral-300">
              <span>账号</span>
              <Input
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="请输入账号"
                required
              />
            </label>
            <label className="block space-y-2 text-sm text-neutral-600 dark:text-neutral-300">
              <span>密码</span>
              <Input
                autoComplete="current-password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="请输入密码"
                required
              />
            </label>
            <div className="space-y-2">
              <label className="block text-sm text-neutral-600 dark:text-neutral-300" htmlFor="captcha-code">
                图片验证码
              </label>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_184px]">
                <Input
                  id="captcha-code"
                  autoComplete="one-time-code"
                  className="uppercase tracking-[0.24em]"
                  maxLength={8}
                  value={captchaCode}
                  onChange={(event) => setCaptchaCode(event.target.value.toUpperCase())}
                  placeholder="验证码"
                  required
                />
                <button
                  className="h-[58px] w-[184px] overflow-hidden rounded-xl border border-neutral-200 bg-neutral-50 transition hover:border-neutral-400 disabled:cursor-wait disabled:opacity-60 dark:border-white/12 dark:bg-neutral-900 dark:hover:border-white/30"
                  type="button"
                  onClick={() => {
                    setCaptchaCode("");
                    setCaptcha(null);
                  }}
                  disabled={isCaptchaLoading}
                  aria-label="换一张验证码"
                  title="点击换一张"
                >
                  {captcha ? (
                    <img className="h-full w-full object-cover" src={captcha.image} alt="图片验证码" />
                  ) : (
                    <span className="text-xs text-neutral-500">
                      {isCaptchaLoading ? "加载中…" : "重新加载"}
                    </span>
                  )}
                </button>
              </div>
              {captchaError ? (
                <button
                  className="text-xs text-red-600 underline underline-offset-2 dark:text-red-300"
                  type="button"
                  onClick={() => void loadCaptcha()}
                >
                  {captchaError}，点击重试
                </button>
              ) : null}
            </div>
            <Button
              className="w-full"
              type="submit"
              disabled={
                isSubmitting ||
                isCaptchaLoading ||
                !captcha ||
                !username.trim() ||
                !password ||
                !captchaCode.trim()
              }
            >
              {isSubmitting ? "验证中…" : "进入控制台"}
            </Button>
            {error ? (
              <div className="text-sm text-red-600 dark:text-red-300" role="alert">
                {error}
              </div>
            ) : null}
          </form>
        </SectionCard>
      </div>
    </div>
  );
}
