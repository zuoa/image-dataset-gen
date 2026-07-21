import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  List,
  Row,
  Segmented,
  Select,
  Space,
  Switch,
  Typography,
} from "antd";

import { PageContainer } from "../components/common/PageContainer";
import { PageHeader } from "../components/common/PageHeader";
import { LoadingState } from "../components/common/LoadingState";
import { UserFacingError } from "../components/common/UserFacingError";
import { useConfirm } from "../hooks/useConfirm";
import { useModelProfiles } from "../hooks/useModelProfiles";
import { useProviders } from "../hooks/useProviders";
import { filterModelProfilesByType, getFallbackModelProfile } from "../lib/modelProfiles";
import type { ModelProfile, ModelProfileType } from "../lib/types";
import { generateLocalId } from "../lib/utils";
import { useAuthStore } from "../store/auth";
import { useModelProfilesStore } from "../store/modelProfiles";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

const llmProviders = [
  { value: "openai_compatible", label: "DeepSeek / OpenAI-Compatible" },
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
    hasApiKey: base?.hasApiKey ?? false,
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
  const confirm = useConfirm();
  const { data: profiles, isLoading: profilesLoading } = useModelProfiles();
  const { data: providers, isLoading: providersLoading } = useProviders();
  const isLoading = useModelProfilesStore((state) => state.isLoading);
  const error = useModelProfilesStore((state) => state.error);
  const saveProfile = useModelProfilesStore((state) => state.saveProfile);
  const removeProfile = useModelProfilesStore((state) => state.removeProfile);
  const [activeTab, setActiveTab] = useState<ModelProfileType>("image");
  const [selectedId, setSelectedId] = useState<string>("");
  const [draftProfile, setDraftProfile] = useState<ModelProfile>(() => createDraftProfile("image"));
  const [saveError, setSaveError] = useState<string | null>(null);

  const filteredProfiles = useMemo(
    () => filterModelProfilesByType(profiles ?? [], activeTab),
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
        ? providers?.find((provider) => provider.id === draftProfile.providerId) ?? null
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

    const provider = providers?.find((item) => item.id === providerId);
    setDraftProfile((current) => ({
      ...current,
      providerId,
      apiKey: providerId === current.providerId ? current.apiKey : "",
      hasApiKey: providerId === current.providerId ? current.hasApiKey : false,
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
      (!draftProfile.apiKey.trim() && !draftProfile.hasApiKey) ||
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

    const ok = await confirm({
      title: "删除模型配置",
      content: `确定要删除 "${draftProfile.name}" 吗？此操作不可撤销。`,
      okDanger: true,
      okText: "删除",
      cancelText: "取消",
    });
    if (!ok) return;

    setSaveError(null);
    try {
      await removeProfile(draftProfile.id, token);
    } catch (nextError) {
      setSaveError((nextError as Error).message);
    }
  }

  const tabOptions = [
    { value: "image", label: "图像生成" },
    { value: "llm", label: "大语言模型" },
  ];

  const providerOptions = useMemo(() => {
    if (draftProfile.profileType === "image") {
      return (providers ?? []).map((provider) => ({ value: provider.id, label: provider.name }));
    }
    return llmProviders;
  }, [draftProfile.profileType, providers]);

  const modelOptions = useMemo(
    () =>
      activeProvider?.models.map((model) => ({ value: model, label: model })) ?? [],
    [activeProvider],
  );

  if (profilesLoading || providersLoading) {
    return (
      <PageContainer>
        <LoadingState rows={8} />
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        eyebrow="模型配置"
        title="模型管理"
        description="保存常用模型和访问凭证，生成图片或使用 AI 助手时可以直接选择。"
        actions={
          <Segmented
            value={activeTab}
            onChange={(value) => handleTabChange(value as ModelProfileType)}
            options={tabOptions}
          />
        }
      />

      <Row gutter={[24, 24]} align="stretch">
        <Col xs={24} xl={8}>
          <Card className="h-full shadow-panel">
            <div className="mb-4 flex items-center justify-between">
              <Text className="font-medium">
                {activeTab === "image" ? "图像模型配置" : "文本模型配置"}
              </Text>
              <Text className="text-xs text-neutral-500">{filteredProfiles.length} 个</Text>
            </div>
            <List
              dataSource={filteredProfiles}
              locale={{
                emptyText: (
                  <div className="rounded-xl border border-dashed border-neutral-200 p-6 text-sm text-neutral-500 dark:border-white/10 dark:text-neutral-400">
                    当前没有可用配置，先新建一个。
                  </div>
                ),
              }}
              renderItem={(profile) => {
                const isActive = profile.id === selectedId;
                return (
                  <List.Item className="!px-0 !py-2">
                    <Button
                      type={isActive ? "primary" : "default"}
                      onClick={() => {
                        setSelectedId(profile.id);
                        setDraftProfile(createDraftProfile(activeTab, profile));
                      }}
                      className="h-auto w-full justify-start !px-4 !py-4 text-left"
                    >
                      <div className="w-full">
                        <div className="text-sm">{profile.name}</div>
                        <Text
                          className={`mt-1 block text-xs ${
                            isActive ? "text-white/75 dark:text-neutral-800" : "text-neutral-500"
                          }`}
                        >
                          {profile.providerId} · {profile.model}
                        </Text>
                      </div>
                    </Button>
                  </List.Item>
                );
              }}
            />
          </Card>
        </Col>

        <Col xs={24} xl={16}>
          <Card className="shadow-panel">
            <div className="mb-4 flex items-center justify-between">
              <Text className="font-medium">
                {draftProfile.profileType === "image" ? "编辑图像模型配置" : "编辑文本模型配置"}
              </Text>
              <Button onClick={handleCreate} disabled={isLoading}>新建配置</Button>
            </div>

            <Form layout="vertical" className="space-y-4">
              <Row gutter={[16, 0]}>
                <Col xs={24} md={12}>
                  <Form.Item label="配置名称" className="!mb-2">
                    <Input
                      value={draftProfile.name}
                      placeholder={
                        draftProfile.profileType === "image"
                          ? "例如：Nano Banana 2 · 通用写实"
                          : "例如：DeepSeek · 自动补全"
                      }
                      onChange={(event) =>
                        setDraftProfile((current) => ({ ...current, name: event.target.value }))
                      }
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item label="服务商" className="!mb-2">
                    <Select
                      value={draftProfile.providerId}
                      onChange={(value) => handleProviderChange(value)}
                      options={providerOptions}
                    />
                  </Form.Item>
                </Col>
              </Row>

              {draftProfile.profileType === "llm" ? (
                <Form.Item label="接口地址" className="!mb-2" extra="通常使用服务商提供的 API 地址。">
                  <Input
                    value={draftProfile.baseUrl ?? ""}
                    placeholder="例如：https://api.deepseek.com/v1"
                    onChange={(event) =>
                      setDraftProfile((current) => ({ ...current, baseUrl: event.target.value }))
                    }
                  />
                </Form.Item>
              ) : null}

              <Row gutter={[16, 0]}>
                <Col xs={24} md={12}>
                  <Form.Item label="模型版本" className="!mb-2">
                    {draftProfile.profileType === "image" && modelOptions.length > 0 ? (
                      <Select
                        value={draftProfile.model}
                        onChange={(value) =>
                          setDraftProfile((current) => ({ ...current, model: value }))
                        }
                        options={modelOptions}
                      />
                    ) : (
                      <Input
                        value={draftProfile.model}
                        placeholder={
                          draftProfile.profileType === "image"
                            ? "输入模型版本"
                            : "输入模型名称或标识"
                        }
                        onChange={(event) =>
                          setDraftProfile((current) => ({ ...current, model: event.target.value }))
                        }
                      />
                    )}
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item label="访问密钥（API Key）" className="!mb-2">
                    <Input.Password
                      value={draftProfile.apiKey}
                      placeholder={
                        draftProfile.hasApiKey
                          ? "已安全保存；留空保持不变"
                          : "输入服务商提供的访问密钥"
                      }
                      onChange={(event) =>
                        setDraftProfile((current) => ({ ...current, apiKey: event.target.value }))
                      }
                    />
                  </Form.Item>
                </Col>
              </Row>

              {draftProfile.profileType === "image" ? (
                <Row gutter={[16, 0]}>
                  <Col xs={24} md={12}>
                    <Form.Item label="同时处理数" className="!mb-2" extra="同时向模型发送的请求数量。">
                      <InputNumber
                        min={1}
                        max={10}
                        value={draftProfile.concurrency}
                        onChange={(value) =>
                          setDraftProfile((current) => ({ ...current, concurrency: Number(value) }))
                        }
                        className="w-full"
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={12}>
                    <Form.Item label="每批图片数" className="!mb-2" extra="每轮提交给模型的图片数量。">
                      <InputNumber
                        min={1}
                        max={50}
                        value={draftProfile.batchSize}
                        onChange={(value) =>
                          setDraftProfile((current) => ({ ...current, batchSize: Number(value) }))
                        }
                        className="w-full"
                      />
                    </Form.Item>
                  </Col>
                  {draftProfile.providerId === "jimeng" ? (
                    <Col xs={24}>
                      <Form.Item className="!mb-2">
                        <div className="flex items-center justify-between rounded-xl border border-neutral-200 bg-neutral-100 px-4 py-3 dark:border-white/10 dark:bg-black/20">
                          <span className="text-sm">默认添加 AI 水印</span>
                          <Switch
                            checked={draftProfile.jimengWatermark}
                            onChange={(checked) =>
                              setDraftProfile((current) => ({ ...current, jimengWatermark: checked }))
                            }
                          />
                        </div>
                      </Form.Item>
                    </Col>
                  ) : null}
                </Row>
              ) : (
                <div className="rounded-xl border border-neutral-200 bg-neutral-100 px-4 py-3 text-sm text-neutral-600 dark:border-white/10 dark:bg-black/20 dark:text-neutral-300">
                  该文本模型将用于建议目标类别、补充说明和优化生成描述。
                </div>
              )}

              <Form.Item label="备注" className="!mb-0">
                <TextArea
                  value={draftProfile.notes ?? ""}
                  placeholder={
                    draftProfile.profileType === "image"
                      ? "记录适用场景，例如中文写实、电商白底、快速试跑等。"
                      : "记录用途，例如目标对象补全、标题建议、标签清洗等。"
                  }
                  onChange={(event) =>
                    setDraftProfile((current) => ({ ...current, notes: event.target.value }))
                  }
                />
              </Form.Item>
            </Form>

            {draftProfile.profileType === "image" && activeProvider ? (
              <Alert
                className="mt-4"
                message={activeProvider.name}
                description={`推荐并发 ${activeProvider.recommendConcurrency}，${activeProvider.sizeHint}`}
                type="info"
                showIcon
              />
            ) : null}

            <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-neutral-200 pt-6 dark:border-white/10">
              <Link
                to="/datasets/new"
                className="text-sm text-neutral-500 transition hover:text-neutral-900 dark:text-neutral-300 dark:hover:text-white"
              >
                返回新建数据集
              </Link>
              <Space>
                <Button
                  danger
                  onClick={() => void handleDelete()}
                  disabled={isLoading || !filteredProfiles.some((profile) => profile.id === draftProfile.id)}
                >
                  删除
                </Button>
                <Button
                  type="primary"
                  loading={isLoading}
                  onClick={() => void handleSave()}
                  disabled={
                    isLoading ||
                    !draftProfile.name.trim() ||
                    !draftProfile.model.trim() ||
                    (!draftProfile.apiKey.trim() && !draftProfile.hasApiKey) ||
                    (draftProfile.profileType === "llm" && !(draftProfile.baseUrl ?? "").trim())
                  }
                >
                  保存配置
                </Button>
              </Space>
            </div>
            {saveError || error ? (
              <UserFacingError
                className="mt-4"
                title="无法保存模型配置"
                description="请检查模型名称、服务商、接口地址和访问密钥后重试。"
                error={saveError || error}
              />
            ) : null}
          </Card>
        </Col>
      </Row>
    </PageContainer>
  );
}
