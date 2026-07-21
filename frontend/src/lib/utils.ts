import { clsx, type ClassValue } from "clsx";

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export function generateLocalId(prefix = "id") {
  if (typeof crypto !== "undefined") {
    if (typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }

    if (typeof crypto.getRandomValues === "function") {
      const bytes = crypto.getRandomValues(new Uint8Array(16));
      const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
      return `${prefix}-${hex}`;
    }
  }

  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function formatCurrency(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatDate(value?: string | null) {
  if (!value) return "未开始";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function formatProviderLabel(providerId: string) {
  if (providerId === "gemini") return "Nano Banana 2";
  if (providerId === "jimeng") return "即梦 AI";
  if (providerId === "stability") return "Stability AI";
  if (providerId === "custom") return "Custom Adapter";
  return providerId;
}

export function formatImageSourceLabel(sourceType: string) {
  const labels: Record<string, string> = {
    generation: "AI 生成",
    augmentation: "数据增强",
    import: "文件导入",
    video: "视频导入",
    roboflow: "Roboflow 导入",
  };
  return labels[sourceType] ?? "其他来源";
}

export function formatAnnotationStatusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: "未标注",
    unannotated: "未标注",
    annotated: "已标注",
    empty: "空标注",
  };
  return labels[status] ?? "状态未知";
}

export function formatDatasetSplitLabel(split: string) {
  const labels: Record<string, string> = {
    train: "训练集",
    val: "验证集",
    test: "测试集",
    unselected: "不保留",
  };
  return labels[split] ?? "未划分";
}
