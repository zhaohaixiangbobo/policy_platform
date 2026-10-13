/**
 * 文件说明：集中维护服务端会话身份，供登录页、管理路由和用户菜单共享。
 */
import { Spin, Result } from 'antd';
import { portalEnabled } from '../portal/config';
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { PropsWithChildren } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { getCurrentUser, login as loginRequest, logout as logoutRequest } from '../api/auth';
import type { CurrentUser } from '../api/auth';

interface AuthState {
  user: CurrentUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<CurrentUser>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setUser(await getCurrentUser());
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    // 只响应后端确认的401；网络异常或403不注销本地身份。
    const expired = () => setUser(null);
    window.addEventListener('platform-session-expired', expired);
    return () => window.removeEventListener('platform-session-expired', expired);
  }, []);

  const value = useMemo<AuthState>(() => ({
    user,
    loading,
    login: async (username, password) => {
      const result = await loginRequest(username, password);
      setUser(result.user);
      return result.user;
    },
    logout: async () => {
      await logoutRequest();
      setUser(null);
    },
    refresh,
  }), [loading, refresh, user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth必须在AuthProvider内使用');
  return context;
}

export function RequireAdmin() {
  const auth = useAuth();
  const location = useLocation();
  if (auth.loading) return <div className="route-loading"><Spin size="large" /></div>;
  if (!auth.user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search + location.hash }} />;
  if (auth.user.must_change_password) return <Navigate to="/change-password" replace state={{ from: location.pathname + location.search + location.hash }} />;
  if (!auth.user.permissions.includes('admin.access')) return <Navigate to="/" replace />;
  return <Outlet />;
}

export function RequireAuthenticated() {
  const auth = useAuth();
  const location = useLocation();
  if (auth.loading) return <div className="route-loading"><Spin size="large" /></div>;
  if (!auth.user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search + location.hash }} />;
  if (auth.user.must_change_password && location.pathname !== '/change-password') return <Navigate to="/change-password" replace state={{ from: location.pathname + location.search + location.hash }} />;
  return <Outlet />;
}

export function RequirePolicy() {
  const auth = useAuth();
  if (portalEnabled && auth.user && !auth.user.must_change_password && !auth.user.permissions.includes('knowledge.document.read'))
    return <Result status="403" title="无制度模块访问权限" subTitle="请联系管理员确认现有账号权限" extra={<a href="/portal">返回工作台</a>} />;
  return <RequireAuthenticated />;
}
