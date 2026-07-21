import { startTransition, useEffect, useMemo, useState } from "react";
import { ArrowLeft, FolderPlus, Tags, WandSparkles } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  Row,
  Select,
  Space,
  Typography,
} from "antd";

import { PageContainer } from "../components/common/PageContainer";
import { PageHeader } from "../components/common/PageHeader";
import { UserFacingError } from "../components/common/UserFacingError";
import { LoadingState } from "../components/common/LoadingState";
import { useModelProfiles } from "../hooks/useModelProfiles";
import { filterModelProfilesByType, resolveLlmProfile } from "../lib/modelProfiles";
import { useAuthStore } from "../store/auth";
import { assistDatasetSubject, createDataset } from "../api/datasets";

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

function normalizeCategories(input: string) {
  return input
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function DatasetCreatePage() {
  const navigate = useNavigate();
  const token = useAuthStore((state) => state.token);
  const { data: profiles, isLoading: profilesLoading } = useModelProfiles();
  const [name, setName] = useState("雨天城市道路行人检测");
  const [categories, setCategories] = useState("pedestrian, umbrella");
  const [description, setDescription] = useState(
    "面向检测训练的主数据集，后续会通过生成、导入和增强累计样本。",
  );
  const [selectedLlmProfileId, setSelectedLlmProfileId] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isAssisting, setIsAssisting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const llmProfiles = useMemo(() => filterModelProfilesByType(profiles ?? [], "llm"), [profiles]);
  const activeLlmProfile = useMemo(
    () => resolveLlmProfile(profiles ?? [], selectedLlmProfileId),
    [profiles, selectedLlmProfileId],
  );

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

  if (profilesLoading) {
    return (
      <PageContainer>
        <LoadingState rows={6} />
      </PageContainer>
    );
  }

  const llmOptions = llmProfiles.map((profile) => ({
    value: profile.id,
    label: profile.name,
  }));

  return (
    <PageContainer>
      <PageHeader
        eyebrow="新建数据集"
        title="创建一个数据集"
        description="填写名称和目标类别，创建后即可添加图片、完成标注并导出训练数据。"
        actions={
          <Link to="/">
            <Button icon={<ArrowLeft className="h-4 w-4" />}>返回列表</Button>
          </Link>
        }
      />

      <Row gutter={[24, 24]}>
        <Col xs={24} xl={16}>
          <Card className="shadow-panel">
            <Form layout="vertical" className="space-y-4">
              <Form.Item label="数据集名称" className="!mb-0">
                <Input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="例如：雨天城市道路行人检测"
                  size="large"
                />
              </Form.Item>

              <Form.Item label="目标类别" className="!mb-0">
                <Input
                  value={categories}
                  onChange={(event) => setCategories(event.target.value)}
                  placeholder="例如：pedestrian, umbrella, bicycle"
                  size="large"
                />
                <Text className="mt-2 block text-xs text-neutral-500">
                  用英文逗号分隔。这些类别将用于后续生成和标注。
                </Text>
              </Form.Item>

              <Form.Item label="说明" className="!mb-0">
                <TextArea
                  rows={6}
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="记录场景边界、目标覆盖范围、质量要求或标注约束。"
                />
              </Form.Item>

              <Row gutter={[16, 16]} className="mt-2">
                <Col xs={24} md={12}>
                  <Text className="block text-xs text-neutral-500">
                    AI 会基于数据集名称生成建议类别和说明，并直接回填到上面的两个字段。
                  </Text>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item label="AI 助手" className="!mb-0">
                    {llmProfiles.length > 0 ? (
                      <Select
                        value={selectedLlmProfileId}
                        onChange={(value) => setSelectedLlmProfileId(value)}
                        options={llmOptions}
                        placeholder="选择 AI 助手"
                        className="w-full"
                      />
                    ) : (
                      <div className="rounded-lg border border-neutral-200 bg-neutral-100 px-4 py-3 text-sm text-neutral-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-400">
                        请先在模型管理中添加文本模型。
                      </div>
                    )}
                  </Form.Item>
                </Col>
              </Row>

              {error ? (
                <UserFacingError
                  className="mt-2"
                  title="操作未完成"
                  description="请检查数据集名称、目标类别和 AI 助手配置后重试。"
                  error={error}
                />
              ) : null}

              <Space className="mt-4">
                <Button
                  type="primary"
                  size="large"
                  icon={<FolderPlus className="h-4 w-4" />}
                  loading={isSubmitting}
                  onClick={() => void handleSubmit()}
                >
                  创建数据集
                </Button>
                <Link to="/">
                  <Button size="large">取消</Button>
                </Link>
                <Button
                  size="large"
                  icon={<WandSparkles className="h-4 w-4" />}
                  loading={isAssisting}
                  disabled={!token || !name.trim() || !activeLlmProfile}
                  onClick={() => void handleAssist()}
                >
                  AI 生成类别和说明
                </Button>
              </Space>
            </Form>
          </Card>
        </Col>

        <Col xs={24} xl={8}>
          <Card className="shadow-panel">
            <div className="flex items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-neutral-900 text-white dark:bg-white dark:text-neutral-950">
                <Tags className="h-5 w-5" />
              </div>
              <div>
                <Title level={5} className="!m-0">创建后下一步</Title>
                <Text className="text-xs text-neutral-500">进入数据集详情，开始添加图片。</Text>
              </div>
            </div>

            <div className="mt-6 space-y-3">
              {[
                "生成新图片，或导入已有图片和标注。",
                "筛选需要保留的图片，并检查标注结果。",
                "训练模型，或导出为常用训练格式。",
              ].map((text, index) => (
                <div
                  key={index}
                  className="rounded-xl border border-black/5 bg-white/80 p-4 text-sm text-neutral-600 dark:border-white/10 dark:bg-black/20 dark:text-neutral-300"
                >
                  {index + 1}. {text}
                </div>
              ))}
            </div>
          </Card>
        </Col>
      </Row>
    </PageContainer>
  );
}
