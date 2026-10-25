import { useCallback, useEffect, useState } from "react";
let bearer = "";
export function setBearer(token: string) {
  bearer = token.trim();
}
export function hasBearer() {
  return Boolean(bearer);
}
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(bearer ? { Authorization: `Bearer ${bearer}` } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : Array.isArray(body.detail)
          ? body.detail
              .map(
                (item: { loc?: string[]; msg?: string }) =>
                  `${item.loc?.slice(1).join(".") || "Field"}: ${item.msg || "Invalid value"}`,
              )
              .join("; ")
          : body.message;
    throw new ApiError(
      detail ||
        (response.status === 401
          ? "Connect a bearer session in Connections to access this workspace."
          : `The request could not be completed (${response.status}).`),
      response.status,
    );
  }
  return response.json();
}
export function useApi<T>(path: string, revision = 0) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api<T>(path, { signal: controller.signal })
      .then(setData)
      .catch((e) => {
        if (e.name !== "AbortError") {
          setError(e.message);
          setData(undefined);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, revision, nonce]);
  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload };
}
export const localDate = () => {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
};
export const displayDate = (
  value: string,
  options: Intl.DateTimeFormatOptions = {
    month: "short",
    day: "numeric",
    year: "numeric",
  },
) =>
  new Date(
    value.length === 10 ? `${value}T12:00:00` : value,
  ).toLocaleDateString("en-US", options);
export const time = (value: string) =>
  new Date(value).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
export const titleCase = (value: string) =>
  value.replace(/[_-]/g, " ").replace(/^\w/, (c) => c.toUpperCase());
