/**
 * 文件说明：提供Platform API健康检查的类型化调用函数。
 */
import type { HealthResponse } from '../types/api';
import { requestJson } from './httpClient';

export function getPlatformReadiness(signal?: AbortSignal): Promise<HealthResponse> {
  return requestJson<HealthResponse>('/api/v1/health/ready', { signal });
}
