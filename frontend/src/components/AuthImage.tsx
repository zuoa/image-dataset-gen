import { useEffect, useState } from "react";

import { API_BASE_URL, resolveApiUrl } from "../api/client";
import { useAuthStore } from "../store/auth";

type AuthImageProps = React.ImgHTMLAttributes<HTMLImageElement> & {
  src: string;
};

export function AuthImage({ src, alt, ...rest }: AuthImageProps) {
  const token = useAuthStore((state) => state.token);
  const [blobUrl, setBlobUrl] = useState<string>(() => {
    if (src.startsWith("data:") || src.startsWith("blob:")) return src;
    return "";
  });

  useEffect(() => {
    if (src.startsWith("data:") || src.startsWith("blob:")) {
      setBlobUrl(src);
      return;
    }

    const url = resolveApiUrl(src);
    // 外部直链（如 nginx 静态服务）不需要带 token fetch
    const isApiAsset = url.startsWith(API_BASE_URL) && url.includes("/preview");
    if (!isApiAsset) {
      setBlobUrl(url);
      return;
    }

    let cancelled = false;
    fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load image");
        return res.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        setBlobUrl(URL.createObjectURL(blob));
      })
      .catch(() => {
        if (cancelled) return;
        setBlobUrl("");
      });

    return () => {
      cancelled = true;
      if (blobUrl && blobUrl.startsWith("blob:")) {
        URL.revokeObjectURL(blobUrl);
      }
    };
  }, [src, token, blobUrl]);

  if (!blobUrl) {
    return (
      <div
        {...(rest as React.HTMLAttributes<HTMLDivElement>)}
        className={`bg-neutral-100 dark:bg-neutral-800 ${rest.className ?? ""}`}
      />
    );
  }

  return <img src={blobUrl} alt={alt} {...rest} />;
}
