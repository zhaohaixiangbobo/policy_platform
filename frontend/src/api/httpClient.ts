/**
 * 文件说明：封装浏览器到Platform API的同源JSON请求边界。
 */

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly requestId: string | null,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function createRequestId(): string {
  // Chrome 89不支持crypto.randomUUID，因此使用不依赖新浏览器API的本地关联ID。
  return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export async function requestJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const requestId = createRequestId();
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  headers.set('X-Request-ID', requestId);

  const method = (init.method ?? 'GET').toUpperCase();
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrfToken = document.cookie
      .split('; ')
      .find((item) => item.startsWith('policy_platform_csrf='))
      ?.split('=')[1];
    if (csrfToken) headers.set('X-CSRF-Token', decodeURIComponent(csrfToken));
  }

  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(path, { ...init, headers, credentials: 'same-origin' });
  const responseRequestId = response.headers.get('X-Request-ID') ?? requestId;

  if (!response.ok) {
    let message = '平台服务请求失败';
    try {
      const payload = (await response.json()) as {
        detail?: string;
        error?: { message?: string };
      };
      message = payload.error?.message ?? payload.detail ?? message;
    } catch {
      // 非JSON错误仍使用稳定的本地提示。
    }
    throw new ApiError(message, response.status, responseRequestId);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
