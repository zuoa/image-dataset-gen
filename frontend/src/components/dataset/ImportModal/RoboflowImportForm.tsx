import { Download, Link2 } from "lucide-react";
import { AutoComplete, Button, Card, Input, Select, Space } from "antd";

import { useConfirm } from "../../../hooks/useConfirm";
import type { RoboflowProjectResolution } from "../../../lib/types";

interface RoboflowConnection {
  id: string;
  name: string;
  status: string;
}

interface RoboflowImportFormProps {
  roboflowConnections: RoboflowConnection[];
  selectedRoboflowConnectionId: string;
  onSelectedRoboflowConnectionIdChange: (id: string) => void;
  onLoadRoboflowConnections: () => Promise<void>;
  onSaveRoboflowConnection: () => Promise<void>;
  onRemoveSelectedRoboflowConnection: () => Promise<void>;
  newRoboflowConnectionName: string;
  onNewRoboflowConnectionNameChange: (value: string) => void;
  newRoboflowApiKey: string;
  onNewRoboflowApiKeyChange: (value: string) => void;
  showRoboflowConnectionForm: boolean;
  onShowRoboflowConnectionFormChange: (show: boolean) => void;
  isLoadingRoboflowConnections: boolean;
  isSavingRoboflowConnection: boolean;
  roboflowProjectUrl: string;
  onRoboflowProjectUrlChange: (value: string) => void;
  onResolveRoboflowProjectLink: () => Promise<void>;
  isResolvingRoboflowLink: boolean;
  resolvedRoboflowProject: RoboflowProjectResolution | null;
  roboflowWorkspace: string;
  onRoboflowWorkspaceChange: (value: string) => void;
  roboflowProject: string;
  onRoboflowProjectChange: (value: string) => void;
  roboflowVersion: string;
  onRoboflowVersionChange: (value: string) => void;
  onRoboflowImport: () => Promise<void>;
  isImportingRoboflow: boolean;
  isAnyImporting: boolean;
}

export function RoboflowImportForm(props: RoboflowImportFormProps) {
  const confirm = useConfirm();

  async function handleRemoveConnection() {
    if (
      !(await confirm({
        title: "删除 Roboflow 连接",
        content: "删除这个 Roboflow 连接？已导入的数据不会受到影响。",
        okDanger: true,
      }))
    )
      return;
    await props.onRemoveSelectedRoboflowConnection();
  }

  return (
    <Card className="bg-neutral-50 dark:bg-white/[0.03]">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Download className="h-4 w-4 text-neutral-500" />
        Roboflow
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="space-y-2 sm:col-span-2">
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs uppercase tracking-[0.2em] text-neutral-500">
              加密连接
            </span>
            <button
              type="button"
              className="text-xs text-neutral-500 hover:text-neutral-900 dark:hover:text-white"
              onClick={() =>
                props.onShowRoboflowConnectionFormChange(!props.showRoboflowConnectionForm)
              }
            >
              {props.showRoboflowConnectionForm ? "收起" : "添加连接"}
            </button>
          </div>
          <Space.Compact className="w-full">
            <Select
              className="flex-1"
              value={props.selectedRoboflowConnectionId || undefined}
              onChange={props.onSelectedRoboflowConnectionIdChange}
              disabled={
                props.isLoadingRoboflowConnections ||
                props.isImportingRoboflow ||
                props.isResolvingRoboflowLink
              }
              placeholder={
                props.isLoadingRoboflowConnections
                  ? "正在读取连接…"
                  : "选择 Roboflow 连接"
              }
              options={props.roboflowConnections.map((connection) => ({
                value: connection.id,
                label: `${connection.name} · ${connection.status === "valid" ? "已验证" : "需验证"}`,
              }))}
            />
            <Button
              onClick={handleRemoveConnection}
              disabled={
                !props.selectedRoboflowConnectionId ||
                props.isImportingRoboflow ||
                props.isResolvingRoboflowLink
              }
            >
              删除
            </Button>
          </Space.Compact>
        </div>

        {props.showRoboflowConnectionForm ? (
          <>
            <div className="sm:col-span-2">
              <div className="mb-2 text-xs uppercase tracking-[0.18em] text-neutral-500">
                连接名称
              </div>
              <Input
                value={props.newRoboflowConnectionName}
                onChange={(event) => props.onNewRoboflowConnectionNameChange(event.target.value)}
                placeholder="团队 Roboflow"
              />
            </div>
            <div className="sm:col-span-2">
              <div className="mb-2 text-xs uppercase tracking-[0.18em] text-neutral-500">
                访问密钥（API Key）
              </div>
              <Input
                type="password"
                value={props.newRoboflowApiKey}
                onChange={(event) => props.onNewRoboflowApiKeyChange(event.target.value)}
                placeholder="只在保存时发送"
                autoComplete="off"
              />
            </div>
            <div className="sm:col-span-2">
              <Button
                type="primary"
                className="w-full"
                onClick={() => void props.onSaveRoboflowConnection()}
                loading={props.isSavingRoboflowConnection}
                disabled={
                  !props.newRoboflowApiKey.trim() ||
                  !props.newRoboflowConnectionName.trim()
                }
              >
                验证并保存连接
              </Button>
            </div>
          </>
        ) : null}

        <div className="sm:col-span-2">
          <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            项目链接
          </div>
          <Space.Compact className="w-full">
            <Input
              value={props.roboflowProjectUrl}
              onChange={(event) =>
                props.onRoboflowProjectUrlChange(event.target.value)
              }
              onPressEnter={() => void props.onResolveRoboflowProjectLink()}
              placeholder="https://app.roboflow.com/workspace/project/browse"
              disabled={
                props.isImportingRoboflow || props.isResolvingRoboflowLink
              }
              prefix={<Link2 className="h-4 w-4 text-neutral-400" />}
            />
            <Button
              onClick={() => void props.onResolveRoboflowProjectLink()}
              loading={props.isResolvingRoboflowLink}
              disabled={
                props.isAnyImporting ||
                props.isImportingRoboflow ||
                !props.selectedRoboflowConnectionId ||
                !props.roboflowProjectUrl.trim()
              }
            >
              解析链接
            </Button>
          </Space.Compact>
          <div className="mt-2 text-xs leading-5 text-neutral-500">
            支持 Roboflow 项目的 browse 页面或明确的数据版本链接。
          </div>
        </div>

        {props.resolvedRoboflowProject ? (
          <div className="sm:col-span-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800 dark:border-emerald-400/20 dark:bg-emerald-950/30 dark:text-emerald-100">
            已识别 {props.resolvedRoboflowProject.projectName}
            {props.resolvedRoboflowProject.projectType
              ? ` · ${props.resolvedRoboflowProject.projectType}`
              : ""}
            {` · ${String(props.resolvedRoboflowProject.versions.length)} 个数据版本`}
          </div>
        ) : null}

        <div>
          <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            工作区标识
          </div>
          <Input
            value={props.roboflowWorkspace}
            onChange={(event) => props.onRoboflowWorkspaceChange(event.target.value)}
            placeholder="workspace-id"
            disabled={props.isImportingRoboflow || props.isResolvingRoboflowLink}
          />
        </div>
        <div>
          <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            项目标识
          </div>
          <Input
            value={props.roboflowProject}
            onChange={(event) => props.onRoboflowProjectChange(event.target.value)}
            placeholder="project-id"
            disabled={props.isImportingRoboflow || props.isResolvingRoboflowLink}
          />
        </div>
        <div>
          <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            数据版本
          </div>
          <AutoComplete
            className="w-full"
            value={props.roboflowVersion}
            onChange={props.onRoboflowVersionChange}
            options={(props.resolvedRoboflowProject?.versions ?? []).map(
              (version) => ({
                value: version.version,
                label:
                  `版本 ${version.version}` +
                  (version.name ? ` · ${version.name}` : "") +
                  ` · ${String(version.imageCount)} 张图片`,
              }),
            )}
            filterOption={(inputValue, option) =>
              String(option?.label ?? "")
                .toLowerCase()
                .includes(inputValue.toLowerCase())
            }
            placeholder="version"
            disabled={props.isImportingRoboflow || props.isResolvingRoboflowLink}
          />
        </div>
        <div>
          <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            导入格式
          </div>
          <Input value="YOLOv8" disabled />
        </div>
      </div>

      <Button
        type="primary"
        className="mt-4 w-full"
        onClick={() => void props.onRoboflowImport()}
        loading={props.isImportingRoboflow}
        disabled={
          props.isAnyImporting ||
          !props.selectedRoboflowConnectionId ||
          !props.roboflowWorkspace.trim() ||
          !props.roboflowProject.trim() ||
          !props.roboflowVersion.trim()
        }
        icon={
          props.isImportingRoboflow ? undefined : <Download className="h-4 w-4" />
        }
      >
        {props.isImportingRoboflow ? "正在从 Roboflow 导入…" : "从 Roboflow 导入"}
      </Button>
    </Card>
  );
}
