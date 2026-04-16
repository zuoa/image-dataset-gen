import { startTransition, useEffect, useMemo, useState } from "react";
import { ArrowLeft, FolderPlus, Tags, WandSparkles } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { assistDatasetSubject, createDataset } from "../api/datasets";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { Select } from "../components/ui/Select";
import { SectionCard } from "../components/ui/SectionCard";
import { Textarea } from "../components/ui/Textarea";
import { filterModelProfilesByType, resolveLlmProfile } from "../lib/modelProfiles";
import { useAuthStore } from "../store/auth";
import { useModelProfilesStore } from "../store/modelProfiles";

function normalizeCategories(input: string) {
  return input
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function DatasetCreatePage() {
  const navigate = useNavigate();
  const token = useAuthStore((state) => state.token);
  const profiles = useModelProfilesStore((state) => state.profiles);
  const profilesLoaded = useModelProfilesStore((state) => state.isLoaded);
  const fetchProfiles = useModelProfilesStore((state) => state.fetchProfiles);
  const [name, setName] = useState("雨天城市道路行人检测");
  const [categories, setCategories] = useState("pedestrian, umbrella");
  const [description, setDescription] = useState("面向检测训练的主数据集，后续会通过生成、导入和增强累计样本。");
  const [selectedLlmProfileId, setSelectedLlmProfileId] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isAssisting, setIsAssisting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const llmProfiles = useMemo(() => filterModelProfilesByType(profiles, "llm"), [profiles]);
  const activeLlmProfile = useMemo(
    () => resolveLlmProfile(profiles, selectedLlmProfileId),
    [profiles, selectedLlmProfileId],
  );

  useEffect(() => {
    if (!token || profilesLoaded) return;
    void fetchProfiles(token);
  }, [fetchProfiles, profilesLoaded, token]);

  useEffect(() => {
    if (llmProfiles.length === 0) return;
    if (activeLlmProfile?.id === selectedLlmProfileId) return;
    setSelectedLlmProfileId(activeLlmProfile?.id ?? llmProfiles[0].id);
  }, [activeLlmProfile, llmProfiles, selectedLlmProfileId]);

  async function handleSubmit() {
    if (!token) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const response = await createDataset(
        {
          name: name.trim(),
          categories: normalizeCategories(categories),
          description: description.trim(),
        },
        token,
      );
      startTransition(() => {
        navigate(`/datasets/${response.dataset.id}`);
      });
    } catch (nextError) {
      setError((nextError as Error).message);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleAssist() {
    if (!token || !activeLlmProfile || !name.trim()) return;
    setIsAssisting(true);
    setError(null);
    try {
      const suggestion = await assistDatasetSubject(token, {
        subject: name.trim(),
        llmProfileId: activeLlmProfile.id,
      });
      startTransition(() => {
        if (suggestion.categories.length > 0) {
          setCategories(suggestion.categories.join(", "));
        }
        if (suggestion.extra_desc) {
          setDescription(suggestion.extra_desc);
        }
      });
    } catch (nextError) {
      setError((nextError as Error).message);
    } finally {
      setIsAssisting(false);
    }
  }

  return (
    <div className="space-y-6">
      <SectionCard>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-[0.24em] text-neutral-500">Create Dataset</div>
            <h2 className="mt-2 text-3xl text-neutral-900 dark:text-white">先定义数据集，再在里面创建批次</h2>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-neutral-500 dark:text-neutral-400">
              数据集只保留长期稳定的信息：名称、目标类别和说明。生成参数放到后续批次里，避免把一次性配置污染整体数据集。
            </p>
          </div>
          <Link to="/">
            <Button variant="secondary">
              <ArrowLeft className="mr-2 h-4 w-4" />
              返回列表
            </Button>
          </Link>
        </div>
      </SectionCard>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <SectionCard>
          <div className="grid gap-6">
            <div>
              <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">数据集名称</div>
              <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：雨天城市道路行人检测" />
            </div>

            <div>
              <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">目标类别</div>
              <Input
                value={categories}
                onChange={(event) => setCategories(event.target.value)}
                placeholder="例如：pedestrian, umbrella, bicycle"
              />
              <div className="mt-2 text-xs text-neutral-500">用英文逗号分隔。后续生成和标注流程会默认继承这些类别。</div>
            </div>

            <div>
              <div className="mb-2 flex items-center justify-between gap-3 text-[11px] uppercase tracking-[0.24em] text-neutral-500">
                <span>说明</span>
                <Button
                  variant="secondary"
                  disabled={!token || !name.trim() || !activeLlmProfile || isAssisting}
                  onClick={() => void handleAssist()}
                >
                  <WandSparkles className="mr-2 h-4 w-4" />
                  {isAssisting ? "生成中..." : "AI 生成类别和说明"}
                </Button>
              </div>
              <Textarea
                rows={6}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="记录场景边界、目标覆盖范围、质量要求或标注约束。"
              />
              <div className="mt-3 grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
                <div className="text-xs text-neutral-500">
                  AI 会基于数据集名称生成建议类别和说明，并直接回填到上面的两个字段。
                </div>
                <div>
                  <div className="mb-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">LLM 配置</div>
                  {llmProfiles.length > 0 ? (
                    <Select
                      value={selectedLlmProfileId}
                      onChange={(event) => setSelectedLlmProfileId(event.target.value)}
                    >
                      {llmProfiles.map((profile) => (
                        <option key={profile.id} value={profile.id}>
                          {profile.name}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <div className="rounded-[18px] border border-neutral-200 bg-neutral-100 px-4 py-3 text-sm text-neutral-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-400">
                      先在模型管理里配置 LLM。
                    </div>
                  )}
                </div>
              </div>
            </div>

            {error ? (
              <div className="rounded-[20px] border border-red-300/40 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-400/20 dark:bg-red-950/20 dark:text-red-100">
                {error}
              </div>
            ) : null}

            <div className="flex flex-wrap gap-3">
              <Button disabled={isSubmitting} onClick={() => void handleSubmit()}>
                <FolderPlus className="mr-2 h-4 w-4" />
                创建数据集
              </Button>
              <Link to="/">
                <Button variant="secondary">取消</Button>
              </Link>
            </div>
          </div>
        </SectionCard>

        <SectionCard className="bg-[linear-gradient(180deg,rgba(244,240,234,0.9),rgba(255,255,255,0.95))] dark:bg-[linear-gradient(180deg,rgba(255,255,255,0.04),rgba(255,255,255,0.02))]">
          <div className="flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-neutral-900 text-white dark:bg-white dark:text-neutral-950">
              <Tags className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm text-neutral-900 dark:text-white">创建后下一步</div>
              <div className="text-xs text-neutral-500">进入数据集详情，添加生成或导入批次。</div>
            </div>
          </div>

          <div className="mt-6 space-y-3 text-sm text-neutral-600 dark:text-neutral-300">
            <div className="rounded-[18px] border border-black/5 bg-white/80 p-4 dark:border-white/10 dark:bg-black/20">
              1. 数据集负责长期样本池和导出结果。
            </div>
            <div className="rounded-[18px] border border-black/5 bg-white/80 p-4 dark:border-white/10 dark:bg-black/20">
              2. 批次任务只负责某次生成、导入或增强。
            </div>
            <div className="rounded-[18px] border border-black/5 bg-white/80 p-4 dark:border-white/10 dark:bg-black/20">
              3. 标注、筛选和导出都在数据集层统一处理。
            </div>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}
