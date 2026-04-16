import { startTransition, useDeferredValue, useEffect, useMemo, useState } from "react";
import { ArrowLeft, WandSparkles } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { assistDatasetSubject, createGenerationTask, getDataset, previewGenerationPrompt, startDatasetTask } from "../api/datasets";
import { getProviders } from "../api/system";
import { PromptPreviewCard } from "../components/PromptPreviewCard";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { Select } from "../components/ui/Select";
import { SectionCard } from "../components/ui/SectionCard";
import { Textarea } from "../components/ui/Textarea";
import { defaultTaskConfig } from "../lib/constants";
import {
  buildTaskConfigFromProfile,
  filterModelProfilesByType,
  resolveLlmProfile,
  resolveModelProfile,
} from "../lib/modelProfiles";
import type { Dataset, PromptPreview, ProviderInfo, TaskConfig } from "../lib/types";
import { formatCurrency } from "../lib/utils";
import { useAuthStore } from "../store/auth";
import { useModelProfilesStore } from "../store/modelProfiles";

const lightingOptions = [
  { value: "natural", label: "自然光" },
  { value: "indoor", label: "室内布光" },
  { value: "backlit", label: "逆光" },
  { value: "night", label: "夜景" },
] as const;

const backgroundOptions = [
  { value: "solid", label: "纯色背景" },
  { value: "indoor", label: "室内环境" },
  { value: "outdoor", label: "室外环境" },
  { value: "city", label: "城市街景" },
  { value: "nature", label: "自然场景" },
] as const;

function toggleValue(current: string[], value: string) {
  return current.includes(value) ? current.filter((item) => item !== value) : [...current, value];
}

export function GenerationTaskPage() {
  const { datasetId } = useParams();
  const navigate = useNavigate();
  const token = useAuthStore((state) => state.token);
  const profiles = useModelProfilesStore((state) => state.profiles);
  const profilesLoaded = useModelProfilesStore((state) => state.isLoaded);
  const fetchProfiles = useModelProfilesStore((state) => state.fetchProfiles);
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [draft, setDraft] = useState<TaskConfig>(defaultTaskConfig);
  const [preview, setPreview] = useState<PromptPreview | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isAssisting, setIsAssisting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const deferredDraft = useDeferredValue(draft);

  useEffect(() => {
    if (!token || !datasetId) return;
    void getDataset(datasetId, token)
      .then((response) => {
        setDataset(response.dataset);
        setDraft((current) => ({
          ...current,
          subject: current.subject === defaultTaskConfig.subject ? response.dataset.name : current.subject,
          categories: response.dataset.categories,
        }));
      })
      .catch((nextError) => setError((nextError as Error).message));
  }, [datasetId, token]);

  useEffect(() => {
    if (!token || profilesLoaded) return;
    void fetchProfiles(token);
  }, [fetchProfiles, profilesLoaded, token]);

  useEffect(() => {
    void getProviders()
      .then((data) => setProviders(data.providers))
      .catch(() => setProviders([]));
  }, []);

  const imageProfiles = useMemo(() => filterModelProfilesByType(profiles, "image"), [profiles]);
  const llmProfiles = useMemo(() => filterModelProfilesByType(profiles, "llm"), [profiles]);
  const activeProfile = useMemo(() => resolveModelProfile(profiles, draft), [draft, profiles]);
  const activeLlmProfile = useMemo(() => resolveLlmProfile(profiles, draft.llm_profile_id), [draft.llm_profile_id, profiles]);

  useEffect(() => {
    if (imageProfiles.length === 0) return;
    const fallbackProfile = activeProfile ?? imageProfiles[0];
    const nextConfig = buildTaskConfigFromProfile(fallbackProfile, draft);
    if (
      nextConfig.model_profile_id !== draft.model_profile_id ||
      nextConfig.api_provider !== draft.api_provider ||
      nextConfig.provider_model !== draft.provider_model ||
      nextConfig.api_key !== draft.api_key ||
      nextConfig.concurrency !== draft.concurrency ||
      nextConfig.batch_size !== draft.batch_size ||
      nextConfig.jimeng_watermark !== draft.jimeng_watermark ||
      nextConfig.format !== draft.format
    ) {
      setDraft((current) => ({ ...current, ...nextConfig, categories: dataset?.categories ?? current.categories }));
    }
  }, [activeProfile, dataset?.categories, draft, imageProfiles]);

  useEffect(() => {
    if (llmProfiles.length === 0) return;
    if (activeLlmProfile?.id === draft.llm_profile_id) return;
    setDraft((current) => ({ ...current, llm_profile_id: activeLlmProfile?.id ?? llmProfiles[0].id }));
  }, [activeLlmProfile, draft.llm_profile_id, llmProfiles]);

  useEffect(() => {
    if (!token || !dataset) return;
    const timeout = window.setTimeout(() => {
      void previewGenerationPrompt({ ...deferredDraft, categories: dataset.categories }, token)
        .then((data) => {
          startTransition(() => setPreview(data));
        })
        .catch(() => {
          startTransition(() => setPreview(null));
        });
    }, 250);

    return () => window.clearTimeout(timeout);
  }, [dataset, deferredDraft, token]);

  async function handleGenerate() {
    if (!token || !datasetId || !dataset) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const created = await createGenerationTask(datasetId, { ...draft, categories: dataset.categories }, token);
      const createdTaskId = (created.task as { id: string }).id;
      await startDatasetTask(datasetId, createdTaskId, token);
      navigate(`/datasets/${datasetId}`);
    } catch (nextError) {
      setError((nextError as Error).message);
    } finally {
      setIsSubmitting(false);
    }
  }

  if (!dataset) {
    return (
      <SectionCard>
        <div className="text-sm text-neutral-500 dark:text-neutral-400">加载数据集中...</div>
      </SectionCard>
    );
  }

  return (
    <div className="space-y-6">
      <SectionCard>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Generation Batch</div>
            <h2 className="mt-2 text-3xl text-neutral-900 dark:text-white">在 `{dataset.name}` 中创建生成批次</h2>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-neutral-500 dark:text-neutral-400">
              类别已绑定到当前数据集，批次只负责定义这一次生成要覆盖的主体、镜头、场景和模型配置。
            </p>
          </div>
          <Link to={`/datasets/${dataset.id}`}>
            <Button variant="secondary">
              <ArrowLeft className="mr-2 h-4 w-4" />
              返回数据集
            </Button>
          </Link>
        </div>
      </SectionCard>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-6">
          <SectionCard>
            <div className="grid gap-5 md:grid-cols-2">
              <div className="md:col-span-2">
                <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">批次主体</div>
                <Input value={draft.subject} onChange={(event) => setDraft((current) => ({ ...current, subject: event.target.value }))} />
              </div>

              <div className="md:col-span-2">
                <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">数据集类别</div>
                <div className="rounded-[20px] border border-neutral-200 bg-neutral-100 px-4 py-3 text-sm text-neutral-700 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-200">
                  {dataset.categories.join(", ")}
                </div>
              </div>

              <div>
                <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">图片数量</div>
                <Input
                  type="number"
                  min={5}
                  max={500}
                  value={draft.image_count}
                  onChange={(event) => setDraft((current) => ({ ...current, image_count: Number(event.target.value) }))}
                />
              </div>

              <div>
                <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">风格</div>
                <Select value={draft.style} onChange={(event) => setDraft((current) => ({ ...current, style: event.target.value as TaskConfig["style"] }))}>
                  <option value="surveillance">监控画面</option>
                  <option value="realistic">写实</option>
                  <option value="illustration">插画</option>
                  <option value="sketch">素描</option>
                  <option value="3d">3D</option>
                  <option value="cartoon">卡通</option>
                </Select>
              </div>

              <div>
                <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">镜头距离</div>
                <Select value={draft.distance} onChange={(event) => setDraft((current) => ({ ...current, distance: event.target.value as TaskConfig["distance"] }))}>
                  <option value="close">近景</option>
                  <option value="mid">中景</option>
                  <option value="far">远景</option>
                </Select>
              </div>

              <div>
                <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">拍摄角度</div>
                <Select value={draft.angle} onChange={(event) => setDraft((current) => ({ ...current, angle: event.target.value as TaskConfig["angle"] }))}>
                  <option value="front">正面</option>
                  <option value="side">侧面</option>
                  <option value="top">俯视</option>
                  <option value="bottom">仰视</option>
                  <option value="random">随机</option>
                </Select>
              </div>

              <div>
                <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">宽高比</div>
                <Select value={draft.aspect_ratio} onChange={(event) => setDraft((current) => ({ ...current, aspect_ratio: event.target.value as TaskConfig["aspect_ratio"] }))}>
                  <option value="1:1">1:1</option>
                  <option value="4:3">4:3</option>
                  <option value="3:4">3:4</option>
                  <option value="16:9">16:9</option>
                  <option value="9:16">9:16</option>
                </Select>
              </div>

              <div>
                <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">图像模型</div>
                <Select
                  value={draft.model_profile_id}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      ...buildTaskConfigFromProfile(
                        imageProfiles.find((profile) => profile.id === event.target.value) ?? imageProfiles[0],
                        current,
                      ),
                    }))
                  }
                >
                  {imageProfiles.map((profile) => (
                    <option key={profile.id} value={profile.id}>
                      {profile.name}
                    </option>
                  ))}
                </Select>
              </div>

              <div className="md:col-span-2">
                <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">光照</div>
                <div className="flex flex-wrap gap-2">
                  {lightingOptions.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setDraft((current) => ({ ...current, lighting: toggleValue(current.lighting, option.value) }))}
                      className={`rounded-full border px-3 py-1.5 text-sm transition ${
                        draft.lighting.includes(option.value)
                          ? "border-neutral-900 bg-neutral-900 text-white dark:border-white dark:bg-white dark:text-neutral-950"
                          : "border-neutral-200 bg-neutral-100 text-neutral-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-300"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="md:col-span-2">
                <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">背景</div>
                <div className="flex flex-wrap gap-2">
                  {backgroundOptions.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setDraft((current) => ({ ...current, background: toggleValue(current.background, option.value) }))}
                      className={`rounded-full border px-3 py-1.5 text-sm transition ${
                        draft.background.includes(option.value)
                          ? "border-neutral-900 bg-neutral-900 text-white dark:border-white dark:bg-white dark:text-neutral-950"
                          : "border-neutral-200 bg-neutral-100 text-neutral-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-300"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="md:col-span-2">
                <div className="mb-2 flex items-center justify-between text-[11px] uppercase tracking-[0.24em] text-neutral-500">
                  <span>补充描述</span>
                  <Button
                    variant="secondary"
                    disabled={!token || !draft.subject.trim() || !activeLlmProfile || isAssisting}
                    onClick={() => {
                      if (!token || !activeLlmProfile) return;
                      setIsAssisting(true);
                      setError(null);
                      void assistDatasetSubject(token, { subject: draft.subject, llmProfileId: activeLlmProfile.id })
                        .then((suggestion) => {
                          setDraft((current) => ({
                            ...current,
                            extra_desc: suggestion.extra_desc || current.extra_desc,
                          }));
                        })
                        .catch((nextError) => setError((nextError as Error).message))
                        .finally(() => setIsAssisting(false));
                    }}
                  >
                    <WandSparkles className="mr-2 h-4 w-4" />
                    AI 补全
                  </Button>
                </div>
                <Textarea
                  rows={5}
                  value={draft.extra_desc ?? ""}
                  onChange={(event) => setDraft((current) => ({ ...current, extra_desc: event.target.value }))}
                />
              </div>
            </div>
          </SectionCard>

          {error ? (
            <SectionCard className="border-red-300/40 bg-red-50 dark:border-red-400/20 dark:bg-red-950/20">
              <div className="text-sm text-red-700 dark:text-red-100">{error}</div>
            </SectionCard>
          ) : null}
        </div>

        <div className="space-y-6">
          <SectionCard>
            <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">批次上下文</div>
            <div className="mt-4 text-lg text-neutral-900 dark:text-white">{dataset.name}</div>
            <div className="mt-2 text-sm leading-7 text-neutral-500 dark:text-neutral-400">
              当前样本池 {dataset.imageCount}，已选样本 {dataset.selectedCount}，累计批次 {dataset.taskCount}。
            </div>
            <div className="mt-4 rounded-[20px] border border-neutral-200 bg-neutral-100 p-4 text-sm dark:border-white/10 dark:bg-white/[0.03]">
              <div className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">模型</div>
              <div className="mt-2 text-neutral-900 dark:text-white">{activeProfile?.name ?? "未选择"}</div>
              <div className="mt-1 text-neutral-500">{providers.find((provider) => provider.id === draft.api_provider)?.name ?? draft.api_provider}</div>
            </div>
          </SectionCard>

          <SectionCard>
            <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Prompt Preview</div>
            <div className="mt-4">
              <PromptPreviewCard
                preview={preview}
                compact
                onCopy={() => {
                  if (!preview?.positive_prompt) return;
                  void navigator.clipboard.writeText(preview.positive_prompt);
                }}
              />
            </div>
            <div className="mt-4 text-sm text-neutral-500 dark:text-neutral-400">
              当前预估成本：{formatCurrency(preview?.estimated_cost ?? 0)}
            </div>
            <div className="mt-5 flex flex-wrap gap-3">
              <Button disabled={isSubmitting} onClick={() => void handleGenerate()}>
                创建并开始生成
              </Button>
              <Link to={`/datasets/${dataset.id}`}>
                <Button variant="secondary">稍后再说</Button>
              </Link>
            </div>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
