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
    const isApiAsset = isProtectedPreviewUrl(url);
    if (!isApiAsset) {
      setBlobUrl(url);
      return;
    }
    if (!token) {
      setBlobUrl("");
      return;
    }

    let cancelled = false;
    let objectUrl = "";
    fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load image");
        return res.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setBlobUrl(objectUrl);
      })
      .catch(() => {
        if (cancelled) return;
        setBlobUrl("");
      });

    return () => {
      cancelled = true;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [src, token]);

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

function isProtectedPreviewUrl(url: string) {
  try {
    const parsed = new URL(url, window.location.origin);
    const apiPathPrefix = apiPathPrefixFromBase();
    return parsed.pathname.startsWith(apiPathPrefix) && parsed.pathname.includes("/preview");
  } catch {
    return false;
  }
}

function apiPathPrefixFromBase() {
  const trimmedBase = API_BASE_URL.replace(/\/$/, "");
  if (trimmedBase.startsWith("http://") || trimmedBase.startsWith("https://")) {
    return new URL(trimmedBase).pathname.replace(/\/$/, "") || "/";
  }
  return trimmedBase.startsWith("/") ? trimmedBase : `/${trimmedBase}`;
}
