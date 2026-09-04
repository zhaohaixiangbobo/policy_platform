/**
 * 文件说明：定义Platform API在M1阶段公开的最小健康检查类型。
 */
export type ServiceState = 'ok' | 'unavailable';

export interface HealthComponent {
  status: ServiceState;
}

export interface HealthResponse {
  status: 'ok' | 'not_ready';
  service: string;
  version: string;
  request_id: string;
  components?: Record<string, HealthComponent>;
}
