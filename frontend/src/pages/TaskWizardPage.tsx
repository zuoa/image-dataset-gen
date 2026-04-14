import { startTransition, useDeferredValue, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useNavigate } from "react-router-dom";

import { assistSubject, createTask, getProviders, previewPrompt, startTask, updateTask } from "../api/tasks";
import { PromptPreviewCard } from "../components/PromptPreviewCard";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { Select } from "../components/ui/Select";
import { SectionCard } from "../components/ui/SectionCard";
import { Textarea } from "../components/ui/Textarea";
import { defaultTaskConfig, wizardSteps } from "../lib/constants";
import {
  buildTaskConfigFromProfile,
  filterModelProfilesByType,
  resolveLlmProfile,
  resolveModelProfile,
} from "../lib/modelProfiles";
import type { PromptPreview, ProviderInfo } from "../lib/types";
import { formatCurrency } from "../lib/utils";
import { useAuthStore } from "../store/auth";
import { useModelProfilesStore } from "../store/modelProfiles";
import { useTaskDraftStore } from "../store/taskDraft";

const toggleValue = (current: string[], value: string) =>
  current.includes(value) ? current.filter((item) => item !== value) : [...current, value];

const lightingOptions = [
  { value: "natural", label: "自然光" },
  { value: "indoor", label: "室内布光" },
  { value: "backlit", label: "逆光" },
  { value: "night", label: "夜景" },
];

const backgroundOptions = [
  { value: "solid", label: "纯色背景" },
  { value: "indoor", label: "室内环境" },
  { value: "outdoor", label: "室外环境" },
  { value: "city", label: "城市街景" },
  { value: "nature", label: "自然场景" },
];

const aspectRatioOptions = [
  { value: "1:1", label: "1:1", caption: "方图" },
  { value: "4:3", label: "4:3", caption: "横向常规" },
  { value: "3:4", label: "3:4", caption: "纵向常规" },
  { value: "16:9", label: "16:9", caption: "宽屏横图" },
  { value: "9:16", label: "9:16", caption: "手机竖图" },
] as const;

const stepDescriptions = [
  "先说明要生成什么，系统会据此组织 Prompt 主体。",
  "补充镜头和场景，让画面更接近训练数据需求。",
  "设置尺寸、质量和风格，确定图片输出规格。",
  "从已管理的图像模型配置中选一个用于当前任务。",
  "最后检查 Prompt、预算和提交方式。",
];

const IMAGE_COUNT_MIN = 5;
const IMAGE_COUNT_MAX = 500;

function clampImageCount(value: number) {
  if (!Number.isFinite(value)) return IMAGE_COUNT_MIN;
  return Math.min(IMAGE_COUNT_MAX, Math.max(IMAGE_COUNT_MIN, Math.round(value)));
}

function normalizeAspectRatio(value?: string) {
  return aspectRatioOptions.find((option) => option.value === value)?.value ?? "1:1";
}

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor?: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <label htmlFor={htmlFor} className="block text-sm font-medium text-neutral-900 dark:text-white">
        {label}
      </label>
      {hint ? <p className="text-xs leading-6 text-neutral-500">{hint}</p> : null}
      {children}
    </div>
  );
}

export function TaskWizardPage() {
  const navigate = useNavigate();
  const token = useAuthStore((state) => state.token);
  const { draft, setDraft, taskId, setTaskId, resetDraft } = useTaskDraftStore();
  const modelProfiles = useModelProfilesStore((state) => state.profiles);
  const modelProfilesLoaded = useModelProfilesStore((state) => state.isLoaded);
  const modelProfilesError = useModelProfilesStore((state) => state.error);
  const fetchProfiles = useModelProfilesStore((state) => state.fetchProfiles);
  const deferredDraft = useDeferredValue(draft);
  const [preview, setPreview] = useState<PromptPreview | null>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isAssisting, setIsAssisting] = useState(false);
  const [assistError, setAssistError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    if (modelProfilesLoaded) return;
    void fetchProfiles(token);
  }, [fetchProfiles, modelProfilesLoaded, token]);

  useEffect(() => {
    void getProviders()
      .then((data) => setProviders(data.providers))
      .catch(() => setProviders([]));
  }, []);

  const activeProfile = useMemo(
    () => resolveModelProfile(modelProfiles, draft),
    [draft, modelProfiles],
  );
  const imageProfiles = useMemo(
    () => filterModelProfilesByType(modelProfiles, "image"),
    [modelProfiles],
  );
  const llmProfiles = useMemo(
    () => filterModelProfilesByType(modelProfiles, "llm"),
    [modelProfiles],
  );
  const activeLlmProfile = useMemo(
    () => resolveLlmProfile(modelProfiles, draft.llm_profile_id),
    [draft.llm_profile_id, modelProfiles],
  );
  const activeProvider = providers.find(
    (provider) => provider.id === (activeProfile?.providerId ?? draft.api_provider),
  ) ?? null;

  useEffect(() => {
    if (imageProfiles.length === 0) return;
    const fallbackProfile = activeProfile ?? imageProfiles[0];
    const nextConfig = buildTaskConfigFromProfile(fallbackProfile, draft);

    const isOutOfSync =
      draft.model_profile_id !== nextConfig.model_profile_id ||
      draft.api_provider !== nextConfig.api_provider ||
      draft.provider_model !== nextConfig.provider_model ||
      draft.api_key !== nextConfig.api_key ||
      draft.concurrency !== nextConfig.concurrency ||
      draft.batch_size !== nextConfig.batch_size ||
      draft.format !== nextConfig.format ||
      draft.jimeng_watermark !== nextConfig.jimeng_watermark;

    if (isOutOfSync) {
      setDraft(nextConfig);
    }
  }, [activeProfile, draft, imageProfiles, setDraft]);

  useEffect(() => {
    if (llmProfiles.length === 0) return;
    if (activeLlmProfile?.id === draft.llm_profile_id) return;
    setDraft({ llm_profile_id: activeLlmProfile?.id ?? llmProfiles[0].id });
  }, [activeLlmProfile, draft.llm_profile_id, llmProfiles, setDraft]);

  useEffect(() => {
    const nextImageCount = clampImageCount(draft.image_count);
    if (draft.image_count !== nextImageCount) {
      setDraft({ image_count: nextImageCount });
    }
  }, [draft.image_count, setDraft]);

  useEffect(() => {
    const nextAspectRatio = normalizeAspectRatio(draft.aspect_ratio);
    if (draft.aspect_ratio !== nextAspectRatio) {
      setDraft({ aspect_ratio: nextAspectRatio });
    }
  }, [draft.aspect_ratio, setDraft]);

  useEffect(() => {
    if (!token) return;
    const timeout = window.setTimeout(() => {
      void previewPrompt(deferredDraft, token)
        .then((data) => {
          startTransition(() => {
            setPreview(data);
          });
        })
        .catch(() => {
          startTransition(() => {
            setPreview(null);
          });
        });
    }, 250);

    return () => window.clearTimeout(timeout);
  }, [deferredDraft, token]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      localStorage.setItem("dataset-gen-draft-timestamp", new Date().toISOString());
    }, 30000);
    return () => window.clearTimeout(timeout);
  }, [draft]);

  const estimatedCost = preview?.estimated_cost ?? 0;
  const isConfirmStep = currentStep === wizardSteps.length - 1;

  const selectionCard = useMemo(() => {
    if (currentStep === 0) {
      return (
        <div className="space-y-4">
          <Field
            label="目标对象"
            htmlFor="subject"
            hint="写清主体类别和关键特征。"
          >
            <Input
              id="subject"
              placeholder="例如：戴黄色安全头盔的建筑工人"
              value={draft.subject}
              onChange={(event) => setDraft({ subject: event.target.value })}
            />
          </Field>
          <Field
            label="类别标签"
            htmlFor="categories"
            hint="多个标签请用逗号分隔。"
          >
            <Input
              id="categories"
              placeholder="例如：worker, helmet, construction"
              value={draft.categories.join(", ")}
              onChange={(event) =>
                setDraft({
                  categories: event.target.value
                    .split(",")
                    .map((item) => item.trim())
                    .filter(Boolean),
                })
              }
            />
          </Field>
          <div className="rounded-[24px] border border-neutral-200 bg-neutral-100 p-4 dark:border-white/10 dark:bg-black/20">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="text-sm text-neutral-900 dark:text-white">AI 生成建议</div>
                <div className="mt-1 text-xs leading-6 text-neutral-500">
                  使用模型管理中配置的 LLM，根据目标对象自动生成类别标签和补充描述。
                </div>
              </div>
              <Button
                type="button"
                variant="secondary"
                disabled={!token || !draft.subject.trim() || !activeLlmProfile || isAssisting}
                onClick={() => {
                  if (!token || !activeLlmProfile) return;
                  setIsAssisting(true);
                  setAssistError(null);
                  void assistSubject(token, {
                    subject: draft.subject,
                    llmProfileId: activeLlmProfile.id,
                  })
                    .then((suggestion) => {
                      setDraft({
                        llm_profile_id: activeLlmProfile.id,
                        categories: suggestion.categories,
                        extra_desc: suggestion.extra_desc,
                        llm_enhanced: true,
                      });
                    })
                    .catch((error) => setAssistError((error as Error).message))
                    .finally(() => setIsAssisting(false));
                }}
              >
                {isAssisting ? "生成中..." : "AI 生成建议"}
              </Button>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-[1fr_auto] md:items-center">
              <label className="space-y-2 text-sm text-neutral-500 dark:text-neutral-400">
                <span className="text-neutral-900 dark:text-white">大语言模型配置</span>
                <Select
                  value={activeLlmProfile?.id ?? ""}
                  onChange={(event) => setDraft({ llm_profile_id: event.target.value })}
                >
                  {llmProfiles.map((profile) => (
                    <option key={profile.id} value={profile.id}>
                      {profile.name}
                    </option>
                  ))}
                </Select>
              </label>
              <Link to="/models">
                <Button variant="ghost" type="button">
                  管理 LLM 配置
                </Button>
              </Link>
            </div>
            {assistError ? <div className="mt-3 text-sm text-red-600 dark:text-red-300">{assistError}</div> : null}
            {!activeLlmProfile ? (
              <div className="mt-3 text-sm text-amber-700 dark:text-amber-200">
                还没有可用的 LLM 配置。先到模型管理里新增一个“大语言模型”配置。
              </div>
            ) : null}
          </div>
          <Field
            label="生成数量"
            htmlFor="image-count"
            hint="范围 5-500，数量越大，预计费用越高。"
          >
            <Input
              id="image-count"
              type="number"
              min={IMAGE_COUNT_MIN}
              max={IMAGE_COUNT_MAX}
              value={draft.image_count}
              onChange={(event) => {
                setDraft({ image_count: clampImageCount(event.target.valueAsNumber) });
              }}
              onBlur={(event) => {
                setDraft({ image_count: clampImageCount(event.target.valueAsNumber) });
              }}
            />
          </Field>
          <Field
            label="补充描述"
            htmlFor="extra-desc"
            hint="补充动作、服饰、道具或使用场景。"
          >
            <Textarea
              id="extra-desc"
              placeholder="例如：正在工地巡检，穿反光背心，手持平板设备"
              value={draft.extra_desc}
              onChange={(event) => setDraft({ extra_desc: event.target.value })}
            />
          </Field>
        </div>
      );
    }

    if (currentStep === 1) {
      return (
        <div className="grid gap-4 md:grid-cols-2">
          <label className="space-y-2 text-sm text-neutral-500 dark:text-neutral-400">
            拍摄距离
            <Select
              value={draft.distance}
              onChange={(event) => setDraft({ distance: event.target.value as typeof draft.distance })}
            >
              <option value="close">近景</option>
              <option value="mid">中景</option>
              <option value="far">远景</option>
            </Select>
          </label>
          <label className="space-y-2 text-sm text-neutral-500 dark:text-neutral-400">
            视角
            <Select
              value={draft.angle}
              onChange={(event) => setDraft({ angle: event.target.value as typeof draft.angle })}
            >
              <option value="front">正面</option>
              <option value="side">侧面</option>
              <option value="top">俯视</option>
              <option value="bottom">仰视</option>
              <option value="random">随机</option>
            </Select>
          </label>

          <div>
            <div className="mb-2 text-sm text-neutral-900 dark:text-white">光线条件</div>
            <p className="mb-3 text-xs leading-6 text-neutral-500">
              决定画面的亮度和氛围，可多选。
            </p>
            <div className="flex flex-wrap gap-2">
              {lightingOptions.map((option) => (
                <button
                  key={option.value}
                  className={`rounded-full border px-3 py-2 text-sm transition ${draft.lighting.includes(option.value) ? "border-neutral-900 bg-neutral-900 text-white dark:border-white/12 dark:bg-neutral-100 dark:text-neutral-950" : "border-neutral-200 text-neutral-600 dark:border-white/10 dark:text-neutral-300 dark:hover:border-white/20 dark:hover:bg-white/[0.04]"}`}
                  onClick={() => setDraft({ lighting: toggleValue(draft.lighting, option.value) })}
                  type="button"
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="mb-2 text-sm text-neutral-900 dark:text-white">背景环境</div>
            <p className="mb-3 text-xs leading-6 text-neutral-500">
              控制主体所在的环境类型，可多选。
            </p>
            <div className="flex flex-wrap gap-2">
              {backgroundOptions.map((option) => (
                <button
                  key={option.value}
                  className={`rounded-full border px-3 py-2 text-sm transition ${draft.background.includes(option.value) ? "border-neutral-900 bg-neutral-900 text-white dark:border-white/12 dark:bg-neutral-100 dark:text-neutral-950" : "border-neutral-200 text-neutral-600 dark:border-white/10 dark:text-neutral-300 dark:hover:border-white/20 dark:hover:bg-white/[0.04]"}`}
                  onClick={() => setDraft({ background: toggleValue(draft.background, option.value) })}
                  type="button"
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      );
    }

    if (currentStep === 2) {
      return (
        <div className="grid gap-4 md:grid-cols-2">
          <Field
            label="宽高比例"
            hint="按比例生成，服务端会映射到默认像素尺寸。"
          >
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
              {aspectRatioOptions.map((option) => {
                const active = draft.aspect_ratio === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    className={`rounded-[22px] border px-4 py-4 text-left transition ${active ? "border-neutral-900 bg-neutral-900 text-white dark:border-white/12 dark:bg-neutral-100 dark:text-neutral-950" : "border-neutral-200 bg-white text-neutral-700 dark:border-white/10 dark:bg-neutral-900 dark:text-neutral-300 dark:hover:border-white/20 dark:hover:bg-white/[0.04]"}`}
                    onClick={() => setDraft({ aspect_ratio: option.value })}
                  >
                    <div className="text-base font-medium">{option.label}</div>
                    <div className={`mt-1 text-xs ${active ? "text-white/75 dark:text-neutral-700" : "text-neutral-500 dark:text-neutral-400"}`}>
                      {option.caption}
                    </div>
                  </button>
                );
              })}
            </div>
          </Field>
          <label className="space-y-2 text-sm text-neutral-500 dark:text-neutral-400">
            <span className="text-neutral-900 dark:text-white">图片格式</span>
            <span className="block text-xs leading-6 text-neutral-500">
              部分 Provider 会限制格式。
            </span>
            <Select
              id="format"
              value={draft.format}
              disabled={draft.api_provider === "jimeng"}
              onChange={(event) => setDraft({ format: event.target.value as typeof draft.format })}
            >
              <option value="jpg">JPG</option>
              <option value="png">PNG</option>
            </Select>
          </label>
          <label className="space-y-2 text-sm text-neutral-500 dark:text-neutral-400">
            <span className="text-neutral-900 dark:text-white">视觉风格</span>
            <span className="block text-xs leading-6 text-neutral-500">
              会直接写入 Prompt。
            </span>
            <Select
              id="style"
              value={draft.style}
              onChange={(event) => setDraft({ style: event.target.value as typeof draft.style })}
            >
              <option value="realistic">写实照片</option>
              <option value="illustration">插画</option>
              <option value="sketch">素描</option>
              <option value="3d">3D</option>
              <option value="cartoon">卡通</option>
            </Select>
          </label>
        </div>
      );
    }

    if (currentStep === 3) {
      return (
        <div className="space-y-4">
          <label className="space-y-2 text-sm text-neutral-500 dark:text-neutral-400">
            <span className="text-neutral-900 dark:text-white">图像模型配置</span>
            <span className="block text-xs leading-6 text-neutral-500">
              flow 里只做选择，Provider、模型版本、API Key 和运行参数统一在模型管理页维护。
            </span>
            <Select
              id="model-profile"
              value={activeProfile?.id ?? ""}
              onChange={(event) => {
                const nextProfile = modelProfiles.find((profile) => profile.id === event.target.value);
                if (!nextProfile) return;
                setDraft(buildTaskConfigFromProfile(nextProfile, draft));
              }}
            >
              {modelProfiles.map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.name}
                </option>
              ))}
            </Select>
          </label>

          {activeProfile ? (
            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-[24px] border border-neutral-200 bg-neutral-100 p-4 dark:border-white/10 dark:bg-black/20">
                <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Provider</div>
                <div className="mt-2 text-neutral-900 dark:text-white">{activeProvider?.name ?? activeProfile.providerId}</div>
                <div className="mt-3 text-xs leading-6 text-neutral-500">
                  {activeProvider?.sizeHint ?? "使用当前模型配置的默认规格建议。"}
                </div>
              </div>
              <div className="rounded-[24px] border border-neutral-200 bg-neutral-100 p-4 dark:border-white/10 dark:bg-black/20">
                <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">模型版本</div>
                <div className="mt-2 break-all text-neutral-900 dark:text-white">{activeProfile.model}</div>
                <div className="mt-3 text-xs leading-6 text-neutral-500">
                  并发 {activeProfile.concurrency} · 批次 {activeProfile.batchSize}
                </div>
              </div>
              <div className="rounded-[24px] border border-neutral-200 bg-neutral-100 p-4 dark:border-white/10 dark:bg-black/20">
                <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">鉴权状态</div>
                <div className="mt-2 text-neutral-900 dark:text-white">
                  {activeProfile.apiKey ? "已配置 API Key" : "缺少 API Key"}
                </div>
                <div className="mt-3 text-xs leading-6 text-neutral-500">
                  任务提交时会沿用该配置中的 Key。
                </div>
              </div>
              <div className="rounded-[24px] border border-neutral-200 bg-neutral-100 p-4 dark:border-white/10 dark:bg-black/20">
                <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">备注</div>
                <div className="mt-2 text-neutral-900 dark:text-white">{activeProfile.notes || "未填写备注"}</div>
                {activeProvider?.notes.length ? (
                  <div className="mt-3 text-xs leading-6 text-neutral-500">
                    {activeProvider.notes.join(" · ")}
                  </div>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="rounded-[24px] border border-dashed border-neutral-200 p-6 text-sm text-neutral-500 dark:border-white/10 dark:text-neutral-400">
              当前没有可用模型配置。先去模型管理页创建一个，再回来继续任务配置。
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[24px] border border-neutral-200 bg-neutral-100 p-4 dark:border-white/10 dark:bg-black/20">
            <div className="text-sm text-neutral-600 dark:text-neutral-300">
              需要切换 Provider、更新模型版本或更换 API Key 时，直接到模型管理页维护。
            </div>
            <Link to="/models">
              <Button variant="secondary" type="button">
                打开模型管理
              </Button>
            </Link>
          </div>
          {modelProfilesError ? <div className="text-sm text-red-600 dark:text-red-300">{modelProfilesError}</div> : null}
        </div>
      );
    }

    return (
      <div className="space-y-5">
        <div className="rounded-[24px] border border-neutral-200 bg-neutral-100 p-5 dark:border-white/10 dark:bg-black/30">
          <div className="text-sm text-neutral-500 dark:text-neutral-400">任务摘要</div>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <div>
              <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Subject</div>
              <div className="mt-2 text-neutral-900 dark:text-white">{draft.subject}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">数量与预算</div>
              <div className="mt-2 text-neutral-900 dark:text-white">
                {draft.image_count} 张 · {formatCurrency(estimatedCost)}
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">拍摄参数</div>
              <div className="mt-2 text-neutral-900 dark:text-white">
                {draft.distance} / {draft.angle}
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">图像模型</div>
              <div className="mt-2 text-neutral-900 dark:text-white">
                {activeProfile?.name ?? draft.api_provider}
              </div>
            </div>
          </div>
        </div>
        <label className="flex items-center justify-between rounded-[24px] border border-neutral-200 p-4 text-sm dark:border-white/10">
          <span className="text-neutral-600 dark:text-neutral-300">启用手动 Prompt 编辑</span>
          <input
            type="checkbox"
            checked={draft.is_manual_edited}
            onChange={(event) => setDraft({ is_manual_edited: event.target.checked })}
          />
        </label>
        {draft.is_manual_edited ? (
          <Field
            label="手动 Prompt"
            htmlFor="manual-prompt"
            hint="开启后，将优先使用这里的内容覆盖系统自动生成的主 Prompt。"
          >
            <Textarea
              id="manual-prompt"
              placeholder="输入你想直接用于生成的 Prompt"
              value={draft.manual_prompt}
              onChange={(event) => setDraft({ manual_prompt: event.target.value })}
            />
          </Field>
        ) : null}
      </div>
    );
  }, [activeLlmProfile, activeProfile, activeProvider, assistError, currentStep, draft, estimatedCost, isAssisting, llmProfiles, modelProfiles, setDraft, token]);

  async function upsertTask(status: "draft" | "running") {
    if (!token) return;
    setIsSubmitting(true);
    setSubmitError(null);
    try {
      const payload = { ...draft, status };
      let nextTaskId = taskId;

      if (nextTaskId) {
        const updated = await updateTask(nextTaskId, payload, token);
        nextTaskId = updated.task.id;
      } else {
        const created = await createTask(payload, token);
        nextTaskId = created.task.id;
        setTaskId(nextTaskId);
      }

      if (status === "running" && nextTaskId) {
        const started = await startTask(nextTaskId, token);
        setTaskId(null);
        navigate(`/tasks/${started.task.id}`);
        return;
      }
    } catch (error) {
      setSubmitError((error as Error).message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <SectionCard>
        <div className="mb-6 flex items-start justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Task Builder</div>
            <h2 className="mt-2 text-3xl text-neutral-900 dark:text-white">{wizardSteps[currentStep].label}</h2>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-neutral-500 dark:text-neutral-400">
              {stepDescriptions[currentStep]}
            </p>
          </div>
          <Button variant="secondary" onClick={() => resetDraft()}>
            重置
          </Button>
        </div>

        <div className="mb-6 flex flex-wrap gap-2">
          {wizardSteps.map((step, index) => {
            const active = index === currentStep;
            const completed = index < currentStep;
            return (
              <button
                key={step.id}
                type="button"
                onClick={() => startTransition(() => setCurrentStep(index))}
                className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm transition ${
                  active
                    ? "border-neutral-900 bg-neutral-900 text-white dark:border-white/12 dark:bg-neutral-100 dark:text-neutral-950"
                    : completed
                      ? "border-neutral-200 bg-neutral-100 text-neutral-900 dark:border-white/12 dark:bg-neutral-900 dark:text-white"
                      : "border-neutral-100 bg-white text-neutral-500 dark:border-white/10 dark:bg-white/[0.02] dark:text-neutral-400 dark:hover:border-white/20 dark:hover:bg-white/[0.04] dark:hover:text-white"
                }`}
              >
                <span className="text-xs">{index + 1}</span>
                <span>{step.label}</span>
              </button>
            );
          })}
        </div>

        {selectionCard}

        <div className="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-neutral-200 pt-6 dark:border-white/10">
          <div className="text-sm text-neutral-500">
            自动保存草稿中。费用预估 {formatCurrency(estimatedCost)}
          </div>
          <div className="flex gap-3">
            <Button
              variant="ghost"
              disabled={currentStep === 0}
              onClick={() => startTransition(() => setCurrentStep((step) => Math.max(0, step - 1)))}
            >
              上一步
            </Button>
            {currentStep < wizardSteps.length - 1 ? (
              <Button
                disabled={currentStep === 3 && !activeProfile}
                onClick={() => startTransition(() => setCurrentStep((step) => step + 1))}
              >
                下一步
              </Button>
            ) : (
              <>
                <Button variant="secondary" disabled={isSubmitting} onClick={() => void upsertTask("draft")}>
                  保存草稿
                </Button>
                <Button disabled={isSubmitting || !activeProfile} onClick={() => void upsertTask("running")}>
                  开始生成
                </Button>
              </>
            )}
          </div>
        </div>
        {submitError ? <div className="mt-4 text-sm text-red-600 dark:text-red-300">{submitError}</div> : null}
      </SectionCard>

      <PromptPreviewCard
        preview={preview}
        onCopy={() => navigator.clipboard.writeText(preview?.positive_prompt ?? "")}
        compact={!isConfirmStep}
      />
    </div>
  );
}
