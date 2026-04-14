import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getProviders } from "../api/tasks";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { Select } from "../components/ui/Select";
import { SectionCard } from "../components/ui/SectionCard";
import { segmentedButtonClasses, segmentedGroupClasses } from "../components/ui/segmentedStyles";
import { Textarea } from "../components/ui/Textarea";
import { filterModelProfilesByType, getFallbackModelProfile } from "../lib/modelProfiles";
import type { ModelProfile, ModelProfileType, ProviderInfo } from "../lib/types";
import { generateLocalId } from "../lib/utils";
import { useAuthStore } from "../store/auth";
import { useModelProfilesStore } from "../store/modelProfiles";

const llmProviders = [
  { id: "openai_compatible", name: "DeepSeek / OpenAI-Compatible" },
];

function createDraftProfile(
  profileType: ModelProfileType,
  base?: Partial<ModelProfile>,
): ModelProfile {
  const fallback = getFallbackModelProfile(profileType);
  return {
    id: base?.id ?? generateLocalId("model-profile"),
    profileType,
    name: base?.name ?? "",
    providerId: base?.providerId ?? fallback.providerId,
    baseUrl: base?.baseUrl ?? fallback.baseUrl ?? "",
    model: base?.model ?? fallback.model,
    apiKey: base?.apiKey ?? "",
    concurrency: base?.concurrency ?? fallback.concurrency,
    batchSize: base?.batchSize ?? fallback.batchSize,
    jimengWatermark: base?.jimengWatermark ?? fallback.jimengWatermark,
    notes: base?.notes ?? "",
    createdAt: base?.createdAt ?? null,
    updatedAt: base?.updatedAt ?? null,
  };
}

export function ModelManagementPage() {
  const token = useAuthStore((state) => state.token);
  const profiles = useModelProfilesStore((state) => state.profiles);
  const isLoading = useModelProfilesStore((state) => state.isLoading);
  const error = useModelProfilesStore((state) => state.error);
  const fetchProfiles = useModelProfilesStore((state) => state.fetchProfiles);
  const saveProfile = useModelProfilesStore((state) => state.saveProfile);
  const removeProfile = useModelProfilesStore((state) => state.removeProfile);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [activeTab, setActiveTab] = useState<ModelProfileType>("image");
  const [selectedId, setSelectedId] = useState<string>("");
  const [draftProfile, setDraftProfile] = useState<ModelProfile>(() => createDraftProfile("image"));
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    void fetchProfiles(token);
  }, [fetchProfiles, token]);

  useEffect(() => {
    void getProviders()
      .then((data) => setProviders(data.providers))
      .catch(() => setProviders([]));
  }, []);

  const filteredProfiles = useMemo(
    () => filterModelProfilesByType(profiles, activeTab),
    [activeTab, profiles],
  );

  useEffect(() => {
    if (filteredProfiles.length === 0) {
      const fallback = createDraftProfile(activeTab);
      setSelectedId(fallback.id);
      setDraftProfile(fallback);
      return;
    }

    const active = filteredProfiles.find((profile) => profile.id === selectedId);
    if (!active) {
      const fallback = filteredProfiles[0];
      setSelectedId(fallback.id);
      setDraftProfile(createDraftProfile(activeTab, fallback));
      return;
    }

    setSelectedId(active.id);
    setDraftProfile(createDraftProfile(activeTab, active));
  }, [activeTab, filteredProfiles, selectedId]);

  const activeProvider = useMemo(
    () =>
      draftProfile.profileType === "image"
        ? providers.find((provider) => provider.id === draftProfile.providerId) ?? null
        : null,
    [draftProfile.profileType, draftProfile.providerId, providers],
  );

  function handleTabChange(nextTab: ModelProfileType) {
    setSaveError(null);
    setActiveTab(nextTab);
  }

  function handleProviderChange(providerId: string) {
    if (draftProfile.profileType === "llm") {
      setDraftProfile((current) => ({
        ...current,
        providerId,
        baseUrl: current.baseUrl || "https://api.deepseek.com/v1",
      }));
      return;
    }

    const provider = providers.find((item) => item.id === providerId);
    setDraftProfile((current) => ({
      ...current,
      providerId,
      model: provider?.defaultModel || provider?.models[0] || "",
      concurrency: provider?.recommendConcurrency ?? current.concurrency,
      jimengWatermark: providerId === "jimeng" ? current.jimengWatermark : false,
    }));
  }

  function handleCreate() {
    const next = createDraftProfile(activeTab);
    setSaveError(null);
    setSelectedId(next.id);
    setDraftProfile(next);
  }

  async function handleSave() {
    if (!token) return;
    const missingBaseUrl = draftProfile.profileType === "llm" && !(draftProfile.baseUrl ?? "").trim();
    if (
      !draftProfile.name.trim() ||
      !draftProfile.model.trim() ||
      !draftProfile.apiKey.trim() ||
      missingBaseUrl
    ) {
      return;
    }
    setSaveError(null);
    try {
      const saved = await saveProfile(
        {
          ...draftProfile,
          name: draftProfile.name.trim(),
          baseUrl: draftProfile.profileType === "llm" ? (draftProfile.baseUrl ?? "").trim() : null,
          model: draftProfile.model.trim(),
          apiKey: draftProfile.apiKey.trim(),
          notes: draftProfile.notes?.trim() ?? "",
        },
        token,
      );
      setSelectedId(saved.id);
      setDraftProfile(saved);
    } catch (nextError) {
      setSaveError((nextError as Error).message);
    }
  }

  async function handleDelete() {
    if (!token) return;
    if (!filteredProfiles.some((profile) => profile.id === draftProfile.id)) return;
    setSaveError(null);
    try {
      await removeProfile(draftProfile.id, token);
    } catch (nextError) {
      setSaveError((nextError as Error).message);
    }
  }

  return (
    <div className="space-y-6">
      <SectionCard>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Model Registry</div>
            <h2 className="mt-2 text-3xl text-neutral-900 dark:text-white">模型管理</h2>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-neutral-500 dark:text-neutral-400">
              统一维护图像生成模型和大语言模型。任务 flow 里只做选择，不再手填底层接口参数。
            </p>
          </div>
          <div className={segmentedGroupClasses}>
            <button
              type="button"
              className={segmentedButtonClasses(activeTab === "image")}
              onClick={() => handleTabChange("image")}
            >
              图像生成
            </button>
            <button
              type="button"
              className={segmentedButtonClasses(activeTab === "llm")}
              onClick={() => handleTabChange("llm")}
            >
              大语言模型
            </button>
          </div>
        </div>
      </SectionCard>

      <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <SectionCard>
          <div className="mb-4 flex items-center justify-between">
            <div className="text-sm text-neutral-900 dark:text-white">
              {activeTab === "image" ? "图像模型配置" : "LLM 配置"}
            </div>
            <div className="text-xs text-neutral-500">{filteredProfiles.length} 个</div>
          </div>
          <div className="space-y-3">
            {filteredProfiles.map((profile) => {
              const isActive = profile.id === selectedId;
              return (
                <button
                  key={profile.id}
                  type="button"
                  onClick={() => {
                    setSelectedId(profile.id);
                    setDraftProfile(createDraftProfile(activeTab, profile));
                  }}
                  className={`w-full rounded-[24px] border px-4 py-4 text-left transition ${
                    isActive
                      ? "border-neutral-900 bg-neutral-900 text-white dark:border-white/12 dark:bg-neutral-100 dark:text-neutral-950"
                      : "border-neutral-200 bg-neutral-100 text-neutral-700 hover:border-neutral-300 hover:bg-white dark:border-white/10 dark:bg-black/20 dark:text-neutral-200 dark:hover:border-white/20 dark:hover:bg-black/30"
                  }`}
                >
                  <div className="text-sm">{profile.name}</div>
                  <div className={`mt-2 text-xs ${isActive ? "text-white/75 dark:text-neutral-700" : "text-neutral-500 dark:text-neutral-400"}`}>
                    {profile.providerId} · {profile.model}
                  </div>
                </button>
              );
            })}
            {filteredProfiles.length === 0 ? (
              <div className="rounded-[24px] border border-dashed border-neutral-200 p-6 text-sm text-neutral-500 dark:border-white/10 dark:text-neutral-400">
                当前没有可用配置，先新建一个。
              </div>
            ) : null}
          </div>
        </SectionCard>

        <SectionCard>
          <div className="mb-4 flex items-center justify-between">
            <div className="text-sm text-neutral-900 dark:text-white">
              {draftProfile.profileType === "image" ? "编辑图像模型配置" : "编辑 LLM 配置"}
            </div>
            <Button variant="secondary" onClick={handleCreate} type="button" disabled={isLoading}>
              新建配置
            </Button>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-2 text-sm text-neutral-500 dark:text-neutral-400">
              <span className="text-neutral-900 dark:text-white">配置名称</span>
              <Input
                value={draftProfile.name}
                placeholder={draftProfile.profileType === "image" ? "例如：Nano Banana 2 · 通用写实" : "例如：DeepSeek · 自动补全"}
                onChange={(event) => setDraftProfile((current) => ({ ...current, name: event.target.value }))}
              />
            </label>

            <label className="space-y-2 text-sm text-neutral-500 dark:text-neutral-400">
              <span className="text-neutral-900 dark:text-white">Provider</span>
              <Select
                value={draftProfile.providerId}
                onChange={(event) => handleProviderChange(event.target.value)}
              >
                {(draftProfile.profileType === "image" ? providers : llmProviders).map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.name}
                  </option>
                ))}
              </Select>
            </label>

            {draftProfile.profileType === "llm" ? (
              <label className="md:col-span-2 space-y-2 text-sm text-neutral-500 dark:text-neutral-400">
                <span className="text-neutral-900 dark:text-white">Base URL</span>
                <Input
                  value={draftProfile.baseUrl ?? ""}
                  placeholder="例如：https://api.deepseek.com/v1"
                  onChange={(event) => setDraftProfile((current) => ({ ...current, baseUrl: event.target.value }))}
                />
              </label>
            ) : null}

            <label className="space-y-2 text-sm text-neutral-500 dark:text-neutral-400">
              <span className="text-neutral-900 dark:text-white">模型版本</span>
              {draftProfile.profileType === "image" && activeProvider?.models.length ? (
                <Select
                  value={draftProfile.model}
                  onChange={(event) => setDraftProfile((current) => ({ ...current, model: event.target.value }))}
                >
                  {activeProvider.models.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input
                  value={draftProfile.model}
                  placeholder={draftProfile.profileType === "image" ? "输入模型版本" : "输入 OpenAI-compatible 模型 ID"}
                  onChange={(event) => setDraftProfile((current) => ({ ...current, model: event.target.value }))}
                />
              )}
            </label>

            <label className="space-y-2 text-sm text-neutral-500 dark:text-neutral-400">
              <span className="text-neutral-900 dark:text-white">API Key</span>
              <Input
                type="password"
                value={draftProfile.apiKey}
                placeholder="输入该配置对应的 API Key"
                onChange={(event) => setDraftProfile((current) => ({ ...current, apiKey: event.target.value }))}
              />
            </label>

            {draftProfile.profileType === "image" ? (
              <>
                <label className="space-y-2 text-sm text-neutral-500 dark:text-neutral-400">
                  <span className="text-neutral-900 dark:text-white">并发数</span>
                  <Input
                    type="number"
                    min={1}
                    max={10}
                    value={draftProfile.concurrency}
                    onChange={(event) =>
                      setDraftProfile((current) => ({ ...current, concurrency: Number(event.target.value) }))
                    }
                  />
                </label>

                <label className="space-y-2 text-sm text-neutral-500 dark:text-neutral-400">
                  <span className="text-neutral-900 dark:text-white">批次大小</span>
                  <Input
                    type="number"
                    min={1}
                    max={50}
                    value={draftProfile.batchSize}
                    onChange={(event) =>
                      setDraftProfile((current) => ({ ...current, batchSize: Number(event.target.value) }))
                    }
                  />
                </label>

                {draftProfile.providerId === "jimeng" ? (
                  <label className="md:col-span-2 flex items-center justify-between rounded-[20px] border border-neutral-200 bg-neutral-100 px-4 py-4 text-sm text-neutral-600 dark:border-white/10 dark:bg-black/20 dark:text-neutral-300">
                    <span>默认添加 AI 水印</span>
                    <input
                      type="checkbox"
                      checked={draftProfile.jimengWatermark}
                      onChange={(event) =>
                        setDraftProfile((current) => ({ ...current, jimengWatermark: event.target.checked }))
                      }
                    />
                  </label>
                ) : null}
              </>
            ) : (
              <div className="md:col-span-2 rounded-[20px] border border-neutral-200 bg-neutral-100 px-4 py-4 text-sm text-neutral-600 dark:border-white/10 dark:bg-black/20 dark:text-neutral-300">
                使用 OpenAI-compatible `/chat/completions` 接口，根据目标对象自动生成类别标签和补充描述。
              </div>
            )}

            <label className="md:col-span-2 space-y-2 text-sm text-neutral-500 dark:text-neutral-400">
              <span className="text-neutral-900 dark:text-white">备注</span>
              <Textarea
                value={draftProfile.notes ?? ""}
                placeholder={draftProfile.profileType === "image" ? "记录适用场景，例如中文写实、电商白底、快速试跑等。" : "记录用途，例如目标对象补全、标题建议、标签清洗等。"}
                onChange={(event) => setDraftProfile((current) => ({ ...current, notes: event.target.value }))}
              />
            </label>
          </div>

          {draftProfile.profileType === "image" && activeProvider ? (
            <div className="mt-6 rounded-[24px] border border-neutral-200 bg-neutral-100 p-4 text-sm text-neutral-600 dark:border-white/10 dark:bg-black/20 dark:text-neutral-300">
              <div className="text-neutral-900 dark:text-white">{activeProvider.name}</div>
              <div className="mt-2 leading-7">
                推荐并发 {activeProvider.recommendConcurrency}，{activeProvider.sizeHint}
              </div>
            </div>
          ) : null}

          <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-neutral-200 pt-6 dark:border-white/10">
            <Link to="/tasks/new" className="text-sm text-neutral-500 transition hover:text-neutral-900 dark:text-neutral-300 dark:hover:text-white">
              返回任务 flow
            </Link>
            <div className="flex gap-3">
              <Button
                variant="ghost"
                onClick={() => void handleDelete()}
                type="button"
                disabled={isLoading || !filteredProfiles.some((profile) => profile.id === draftProfile.id)}
              >
                删除
              </Button>
              <Button
                onClick={() => void handleSave()}
                type="button"
                disabled={
                  isLoading ||
                  !draftProfile.name.trim() ||
                  !draftProfile.model.trim() ||
                  !draftProfile.apiKey.trim() ||
                  (draftProfile.profileType === "llm" && !(draftProfile.baseUrl ?? "").trim())
                }
              >
                {isLoading ? "保存中..." : "保存配置"}
              </Button>
            </div>
          </div>
          {saveError || error ? <div className="mt-4 text-sm text-red-600 dark:text-red-300">{saveError || error}</div> : null}
        </SectionCard>
      </div>
    </div>
  );
}
