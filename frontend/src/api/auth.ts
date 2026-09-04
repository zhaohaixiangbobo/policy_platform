/**
 * 文件说明：封装本地登录、当前会话和4A预留能力查询。
 */
import { requestJson } from './httpClient';

export interface CurrentUser {
  id: string;
  username: string;
  display_name: string;
  roles: string[];
  permissions: string[];
  must_change_password: boolean;
  auth_provider: string;
}

export interface LoginResponse {
  user: CurrentUser;
  expires_at: string;
}

export function login(username: string, password: string) {
  return requestJson<LoginResponse>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
}

export function getCurrentUser() {
  return requestJson<CurrentUser>('/api/v1/auth/me');
}

export function logout() {
  return requestJson<void>('/api/v1/auth/logout', { method: 'POST' });
}

export function changePassword(currentPassword: string, newPassword: string) {
  return requestJson<void>('/api/v1/auth/change-password', {
    method: 'POST', body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}
