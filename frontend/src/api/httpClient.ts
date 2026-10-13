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

function errorText(value: unknown): string | null {
  if (typeof value === 'string') return value.trim() || null;
  if (Array.isArray(value)) return value.map(errorText).filter(Boolean).join('；') || null;
  if (value && typeof value === 'object') {
    const detail = value as { msg?: unknown; message?: unknown; loc?: unknown };
    const text = typeof detail.msg === 'string' ? detail.msg : typeof detail.message === 'string' ? detail.message : null;
    if (!text) return null;
    const path = Array.isArray(detail.loc) ? detail.loc.filter((part) => typeof part === 'string' || typeof part === 'number').join('.') : '';
    return path ? `${path}：${text}` : text;
  }
  return null;
}

/** 将FastAPI校验数组、业务错误与文本错误转换为可读消息，不展示请求原始值。 */
export function apiErrorMessage(payload: unknown): string {
  if (!payload || typeof payload !== 'object') return errorText(payload) ?? '平台服务请求失败';
  const body = payload as { error?: unknown; detail?: unknown };
  return errorText(body.error) ?? errorText(body.detail) ?? '平台服务请求失败';
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

  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(path, { ...init, headers, credentials: 'same-origin' });
  const responseRequestId = response.headers.get('X-Request-ID') ?? requestId;

  if (!response.ok) {
    if (response.status === 401 && path !== '/api/v1/auth/login' && typeof window !== 'undefined') {
      window.dispatchEvent(new Event('platform-session-expired'));
    }
    let message = '平台服务请求失败';
    try {
      message = apiErrorMessage(await response.json());
    } catch {
      // 非JSON错误仍使用稳定的本地提示。
    }
    throw new ApiError(message, response.status, responseRequestId);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
