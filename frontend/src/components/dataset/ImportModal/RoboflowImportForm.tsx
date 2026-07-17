import { Download, Loader } from "lucide-react";
import { Button, Card, Input, Select, Space } from "antd";

import { confirm } from "../../../hooks/useConfirm";

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
              disabled={props.isLoadingRoboflowConnections || props.isImportingRoboflow}
              placeholder={
                props.isLoadingRoboflowConnections
                  ? "读取连接中..."
                  : "选择 Roboflow 连接"
              }
              options={props.roboflowConnections.map((connection) => ({
                value: connection.id,
                label: `${connection.name} · ${connection.status === "valid" ? "已验证" : "需验证"}`,
              }))}
            />
            <Button
              onClick={handleRemoveConnection}
              disabled={!props.selectedRoboflowConnectionId || props.isImportingRoboflow}
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
                API Key
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

        <div>
          <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            Workspace
          </div>
          <Input
            value={props.roboflowWorkspace}
            onChange={(event) => props.onRoboflowWorkspaceChange(event.target.value)}
            placeholder="workspace-id"
            disabled={props.isImportingRoboflow}
          />
        </div>
        <div>
          <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            Project
          </div>
          <Input
            value={props.roboflowProject}
            onChange={(event) => props.onRoboflowProjectChange(event.target.value)}
            placeholder="project-id"
            disabled={props.isImportingRoboflow}
          />
        </div>
        <div>
          <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            Version
          </div>
          <Input
            value={props.roboflowVersion}
            onChange={(event) => props.onRoboflowVersionChange(event.target.value)}
            placeholder="version"
            disabled={props.isImportingRoboflow}
          />
        </div>
        <div>
          <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            Format
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
        {props.isImportingRoboflow ? "下载导入中..." : "从 Roboflow 导入"}
      </Button>
    </Card>
  );
}
