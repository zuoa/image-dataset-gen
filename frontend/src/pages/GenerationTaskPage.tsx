import { startTransition, useDeferredValue, useEffect, useMemo, useState } from "react";
import { ArrowLeft, WandSparkles } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Button,
  Card,
  Col,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";

import { PromptPreviewCard } from "../components/PromptPreviewCard";
import { PageContainer } from "../components/common/PageContainer";
import { PageHeader } from "../components/common/PageHeader";
import { UserFacingError } from "../components/common/UserFacingError";
import { LoadingState } from "../components/common/LoadingState";
import { useDataset } from "../hooks/useDataset";
import { useModelProfiles } from "../hooks/useModelProfiles";
import { useProviders } from "../hooks/useProviders";
import { defaultTaskConfig } from "../lib/constants";
import {
  buildTaskConfigFromProfile,
  filterModelProfilesByType,
  resolveLlmProfile,
  resolveModelProfile,
} from "../lib/modelProfiles";
import type { PromptPreview, TaskConfig } from "../lib/types";
import { formatCurrency } from "../lib/utils";
import { useAuthStore } from "../store/auth";
import {
  assistDatasetSubject,
  createGenerationTask,
  previewGenerationPrompt,
  startDatasetTask,
} from "../api/datasets";

const { Title, Text } = Typography;
const { TextArea } = Input;

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

const cvTaskOptions = [
  { value: "detection", label: "目标检测" },
  { value: "segmentation", label: "语义分割" },
  { value: "classification", label: "图像分类" },
  { value: "instance_segmentation", label: "实例分割" },
];

const styleOptions = [
  { value: "surveillance", label: "监控画面" },
  { value: "realistic", label: "写实" },
  { value: "illustration", label: "插画" },
  { value: "sketch", label: "素描" },
  { value: "3d", label: "3D" },
  { value: "cartoon", label: "卡通" },
];

const distanceOptions = [
  { value: "close", label: "近景" },
  { value: "mid", label: "中景" },
  { value: "far", label: "远景" },
];

const angleOptions = [
  { value: "front", label: "正面" },
  { value: "side", label: "侧面" },
  { value: "top", label: "俯视" },
  { value: "bottom", label: "仰视" },
  { value: "random", label: "随机" },
];

const aspectRatioOptions = [
  { value: "1:1", label: "1:1" },
  { value: "4:3", label: "4:3" },
  { value: "3:4", label: "3:4" },
  { value: "16:9", label: "16:9" },
  { value: "9:16", label: "9:16" },
];

const PROMPT_PREVIEW_DEBOUNCE_MS = 800;

function toggleValue(current: string[], value: string) {
  return current.includes(value)
    ? current.filter((item) => item !== value)
    : [...current, value];
}

export function GenerationTaskPage() {
  const { datasetId } = useParams();
  const navigate = useNavigate();
  const token = useAuthStore((state) => state.token);
  const { data: datasetResponse, isLoading: datasetLoading } = useDataset(datasetId!);
  const dataset = datasetResponse?.dataset ?? null;
  const { data: profiles, isLoading: profilesLoading } = useModelProfiles();
  const { data: providers, isLoading: providersLoading } = useProviders();
  const [draft, setDraft] = useState<TaskConfig>(defaultTaskConfig);
  const [preview, setPreview] = useState<PromptPreview | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isAssisting, setIsAssisting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const deferredDraft = useDeferredValue(draft);

  useEffect(() => {
    if (!dataset) return;
    setDraft((current) => ({
      ...current,
      subject: current.subject === defaultTaskConfig.subject ? dataset.name : current.subject,
      categories: dataset.categories,
    }));
  }, [dataset]);

  const imageProfiles = useMemo(() => filterModelProfilesByType(profiles ?? [], "image"), [profiles]);
  const llmProfiles = useMemo(() => filterModelProfilesByType(profiles ?? [], "llm"), [profiles]);
  const activeProfile = useMemo(() => resolveModelProfile(profiles ?? [], draft), [draft, profiles]);
  const activeLlmProfile = useMemo(
    () => resolveLlmProfile(profiles ?? [], draft.llm_profile_id),
    [draft.llm_profile_id, profiles],
  );

  useEffect(() => {
    if (imageProfiles.length === 0) return;
    const fallbackProfile = activeProfile ?? imageProfiles[0];
    const nextConfig = buildTaskConfigFromProfile(fallbackProfile, draft);
    const needsUpdate =
      nextConfig.model_profile_id !== draft.model_profile_id ||
      nextConfig.api_provider !== draft.api_provider ||
      nextConfig.provider_model !== draft.provider_model ||
      nextConfig.api_key !== draft.api_key ||
      nextConfig.concurrency !== draft.concurrency ||
      nextConfig.batch_size !== draft.batch_size ||
      nextConfig.jimeng_watermark !== draft.jimeng_watermark ||
      nextConfig.format !== draft.format;
    if (needsUpdate) {
      setDraft((current) => ({
        ...current,
        ...nextConfig,
        categories: dataset?.categories ?? current.categories,
      }));
    }
  }, [activeProfile, dataset?.categories, draft, imageProfiles]);

  useEffect(() => {
    if (llmProfiles.length === 0) return;
    if (activeLlmProfile?.id === draft.llm_profile_id) return;
    setDraft((current) => ({ ...current, llm_profile_id: activeLlmProfile?.id ?? llmProfiles[0].id }));
  }, [activeLlmProfile, draft.llm_profile_id, llmProfiles]);

  useEffect(() => {
    if (!token || !dataset) return;
    let disposed = false;
    const timeout = window.setTimeout(() => {
      void previewGenerationPrompt({ ...deferredDraft, categories: dataset.categories }, token)
        .then((data) => {
          if (disposed) return;
          startTransition(() => setPreview(data));
        })
        .catch(() => {
          if (disposed) return;
          startTransition(() => setPreview(null));
        });
    }, PROMPT_PREVIEW_DEBOUNCE_MS);

    return () => {
      disposed = true;
      window.clearTimeout(timeout);
    };
  }, [dataset, deferredDraft, token]);

  async function handleGenerate() {
    if (!token || !datasetId || !dataset) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const created = await createGenerationTask(
        datasetId,
        { ...draft, categories: dataset.categories },
        token,
      );
      const createdTaskId = (created.task as { id: string }).id;
      await startDatasetTask(datasetId, createdTaskId, token);
      navigate(`/datasets/${datasetId}`);
    } catch (nextError) {
      setError((nextError as Error).message);
    } finally {
      setIsSubmitting(false);
    }
  }

  if (datasetLoading || profilesLoading || providersLoading) {
    return (
      <PageContainer>
        <LoadingState rows={8} />
      </PageContainer>
    );
  }

  if (!dataset) {
    return (
      <PageContainer>
        <Alert message="数据集加载失败" type="error" showIcon />
      </PageContainer>
    );
  }

  const providerName =
    providers?.find((provider) => provider.id === draft.api_provider)?.name ?? draft.api_provider;

  return (
    <PageContainer>
      <PageHeader
        eyebrow="生成图片"
        title={`为“${dataset.name}”生成图片`}
        description="选择图片数量、画面、场景和模型，生成结果会自动加入当前数据集。"
        actions={
          <Link to={`/datasets/${dataset.id}`}>
            <Button icon={<ArrowLeft className="h-4 w-4" />}>返回数据集</Button>
          </Link>
        }
      />

      <Row gutter={[24, 24]}>
        <Col xs={24} xl={16}>
          <Card className="shadow-panel">
            <Row gutter={[16, 16]}>
              <Col xs={24}>
                <FormItem label="要生成的内容">
                  <Input
                    value={draft.subject}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, subject: event.target.value }))
                    }
                  />
                </FormItem>
              </Col>

              <Col xs={24}>
                <FormItem label="数据集类别">
                  <div className="rounded-lg border border-neutral-200 bg-neutral-100 px-4 py-3 text-sm dark:border-white/10 dark:bg-white/[0.03]">
                    {dataset.categories.join(", ")}
                  </div>
                </FormItem>
              </Col>

              <Col xs={24} md={12}>
                <FormItem label="图片数量">
                  <InputNumber
                    min={5}
                    max={500}
                    value={draft.image_count}
                    onChange={(value) =>
                      setDraft((current) => ({ ...current, image_count: Number(value) }))
                    }
                    className="w-full"
                  />
                </FormItem>
              </Col>

              <Col xs={24} md={12}>
                <FormItem label="数据用途">
                  <Select
                    value={draft.cv_task ?? "detection"}
                    onChange={(value) =>
                      setDraft((current) => ({ ...current, cv_task: value as TaskConfig["cv_task"] }))
                    }
                    options={cvTaskOptions}
                  />
                </FormItem>
              </Col>

              <Col xs={24} md={12}>
                <FormItem label="风格">
                  <Select
                    value={draft.style}
                    onChange={(value) =>
                      setDraft((current) => ({ ...current, style: value as TaskConfig["style"] }))
                    }
                    options={styleOptions}
                  />
                </FormItem>
              </Col>

              <Col xs={24} md={12}>
                <FormItem label="镜头距离">
                  <Select
                    value={draft.distance}
                    onChange={(value) =>
                      setDraft((current) => ({ ...current, distance: value as TaskConfig["distance"] }))
                    }
                    options={distanceOptions}
                  />
                </FormItem>
              </Col>

              <Col xs={24} md={12}>
                <FormItem label="拍摄角度">
                  <Select
                    value={draft.angle}
                    onChange={(value) =>
                      setDraft((current) => ({ ...current, angle: value as TaskConfig["angle"] }))
                    }
                    options={angleOptions}
                  />
                </FormItem>
              </Col>

              <Col xs={24} md={12}>
                <FormItem label="宽高比">
                  <Select
                    value={draft.aspect_ratio}
                    onChange={(value) =>
                      setDraft((current) => ({
                        ...current,
                        aspect_ratio: value as TaskConfig["aspect_ratio"],
                      }))
                    }
                    options={aspectRatioOptions}
                  />
                </FormItem>
              </Col>

              <Col xs={24} md={12}>
                <FormItem label="图像模型">
                  <Select
                    value={draft.model_profile_id}
                    onChange={(value) =>
                      setDraft((current) => ({
                        ...current,
                        ...buildTaskConfigFromProfile(
                          imageProfiles.find((profile) => profile.id === value) ?? imageProfiles[0],
                          current,
                        ),
                      }))
                    }
                    options={imageProfiles.map((profile) => ({
                      value: profile.id,
                      label: profile.name,
                    }))}
                  />
                </FormItem>
              </Col>

              <Col xs={24}>
                <FormItem label="光照">
                  <Space wrap>
                    {lightingOptions.map((option) => (
                      <Tag.CheckableTag
                        key={option.value}
                        checked={draft.lighting.includes(option.value)}
                        onChange={() =>
                          setDraft((current) => ({
                            ...current,
                            lighting: toggleValue(current.lighting, option.value),
                          }))
                        }
                      >
                        {option.label}
                      </Tag.CheckableTag>
                    ))}
                  </Space>
                </FormItem>
              </Col>

              <Col xs={24}>
                <FormItem label="背景">
                  <Space wrap>
                    {backgroundOptions.map((option) => (
                      <Tag.CheckableTag
                        key={option.value}
                        checked={draft.background.includes(option.value)}
                        onChange={() =>
                          setDraft((current) => ({
                            ...current,
                            background: toggleValue(current.background, option.value),
                          }))
                        }
                      >
                        {option.label}
                      </Tag.CheckableTag>
                    ))}
                  </Space>
                </FormItem>
              </Col>

              <Col xs={24}>
                <FormItem
                  label="补充描述"
                  extra={
                    <Button
                      size="small"
                      icon={<WandSparkles className="h-3.5 w-3.5" />}
                      loading={isAssisting}
                      disabled={!token || !draft.subject.trim() || !activeLlmProfile}
                      onClick={() => {
                        if (!token || !activeLlmProfile) return;
                        setIsAssisting(true);
                        setError(null);
                        void assistDatasetSubject(token, {
                          subject: draft.subject,
                          llmProfileId: activeLlmProfile.id,
                        })
                          .then((suggestion) => {
                            setDraft((current) => ({
                              ...current,
                              extra_desc: suggestion.extra_desc || current.extra_desc,
                            }));
                          })
                          .catch((nextError) => setError((nextError as Error).message))
                          .finally(() => setIsAssisting(false));
                      }}
                      className="mt-2"
                    >
                      AI 补全
                    </Button>
                  }
                >
                  <TextArea
                    rows={5}
                    value={draft.extra_desc ?? ""}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, extra_desc: event.target.value }))
                    }
                  />
                </FormItem>
              </Col>
            </Row>
          </Card>

          {error ? (
            <UserFacingError
              className="mt-6"
              title="无法完成图片生成"
              description="请检查生成内容和模型配置，确认网络连接正常后重试。"
              error={error}
            />
          ) : null}
        </Col>

        <Col xs={24} xl={8}>
          <Space direction="vertical" className="w-full" size="large">
            <Card className="shadow-panel">
              <Text className="block text-xs uppercase tracking-[0.2em] text-neutral-500">
                当前数据集
              </Text>
              <Title level={4} className="mt-3 !mb-2 !text-lg">{dataset.name}</Title>
              <Text className="block text-sm leading-7 text-neutral-500 dark:text-neutral-400">
                当前共有 {dataset.imageCount} 张图片，已保留 {dataset.selectedCount} 张，累计任务{" "}
                {dataset.taskCount}。
              </Text>
              <div className="mt-4 rounded-lg border border-neutral-200 bg-neutral-100 p-4 dark:border-white/10 dark:bg-white/[0.03]">
                <Text className="block text-xs uppercase tracking-[0.2em] text-neutral-500">模型</Text>
                <Text className="mt-2 block font-medium">{activeProfile?.name ?? "未选择"}</Text>
                <Text className="text-sm text-neutral-500">{providerName}</Text>
              </div>
            </Card>

            <Card className="shadow-panel">
              <Text className="block text-xs uppercase tracking-[0.2em] text-neutral-500">
                生成描述预览
              </Text>
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
              <Text className="mt-4 block text-sm text-neutral-500 dark:text-neutral-400">
                当前预估成本：{formatCurrency(preview?.estimated_cost ?? 0)}
              </Text>
              <Space className="mt-5">
                <Button
                  type="primary"
                  loading={isSubmitting}
                  onClick={() => void handleGenerate()}
                >
                  创建并开始生成
                </Button>
                <Link to={`/datasets/${dataset.id}`}>
                  <Button>返回数据集</Button>
                </Link>
              </Space>
            </Card>
          </Space>
        </Col>
      </Row>
    </PageContainer>
  );
}

function FormItem({
  label,
  extra,
  children,
}: {
  label: React.ReactNode;
  extra?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Text className="text-xs uppercase tracking-[0.2em] text-neutral-500">{label}</Text>
        {extra}
      </div>
      {children}
    </div>
  );
}
