import { App } from "antd";

export function useToast() {
  const { message, notification } = App.useApp();
  return { message, notification };
}

export function useStaticApp() {
  return App.useApp();
}
