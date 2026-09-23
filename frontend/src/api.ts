export type User = {
  id: string;
  email: string;
  role: "student" | "advisor" | "admin";
};
export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) {
    super(message);
    this.name = "ApiError";
  }
}
let access = "";
let refreshPending: Promise<void> | null = null;
export function setAccess(token: string) {
  access = token;
}
function expired() {
  access = '';
  window.dispatchEvent(new Event('advisor:session-expired'));
}
export async function api<T = any>(
  path: string,
  body?: unknown,
  method?: string,
  retry = true,
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    method: method || (body === undefined ? "GET" : "POST"),
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(access ? { Authorization: "Bearer " + access } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (
    response.status === 401 &&
    access &&
    !path.startsWith("/auth/") &&
    retry
  ) {
    if (!refreshPending)
      refreshPending = api<any>("/auth/refresh", {}, "POST", false)
        .then((data) => setAccess(data.access_token))
        .catch(() => { expired(); throw new Error('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.'); })
        .finally(() => {
          refreshPending = null;
        });
    await refreshPending;
    return api<T>(path, body, method, false);
  }
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error("Không kết nối được API. Kiểm tra stack Docker.");
  }
  if (response.status === 401 && !path.startsWith('/auth/')) expired();
  if (!response.ok)
    throw new ApiError(result.error?.code || "REQUEST_FAILED", result.error?.message || "Yêu cầu thất bại", response.status);
  return result.data;
}

export async function uploadImport(importType: string, file: File, dryRun: boolean) {
  const response = await fetch(
    "/api/v1/admin/imports/" + encodeURIComponent(importType) + "?dry_run=" + dryRun,
    {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "text/csv",
        Authorization: "Bearer " + access,
      },
      body: file,
    },
  );
  const result = await response.json();
  if (!response.ok) throw new Error(result.error?.message || "Import thất bại");
  return result.data;
}

export async function downloadImportTemplate(importType: string) {
  const response = await fetch("/api/v1/admin/imports/templates/" + encodeURIComponent(importType), {
    headers: access ? { Authorization: "Bearer " + access } : {}, credentials: "same-origin",
  });
  if (!response.ok) throw new Error("Không tải được template");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob); const link = document.createElement("a");
  link.href = url; link.download = importType + ".csv"; link.click(); URL.revokeObjectURL(url);
}

export async function importHistory() { return api<any[]>("/admin/imports/history"); }

export async function extractDocument(file: File, retry = true): Promise<any> {
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await fetch("/api/v1/admin/documents/extract", {
    method: "POST",
    credentials: "same-origin",
    headers: access ? { Authorization: "Bearer " + access } : {},
    body: form,
  });
  if (response.status === 401 && access && retry) {
    if (!refreshPending)
      refreshPending = api<any>("/auth/refresh", {}, "POST", false)
        .then((data) => setAccess(data.access_token))
        .finally(() => { refreshPending = null; });
    await refreshPending;
    return extractDocument(file, false);
  }
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error("Không đọc được phản hồi trích xuất tài liệu.");
  }
  if (!response.ok)
    throw new Error(result.error?.message || "Không thể trích xuất tài liệu");
  return result.data;
}
