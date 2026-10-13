/** 文件说明：门户路由/开关/回跳/权限最小隔离测试，不登录真实账户。 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
const read = (path) => readFileSync(new URL('../src/' + path, import.meta.url), 'utf8');
function config(enabled) {
  const source = read('portal/config.ts').replace('import.meta.env.VITE_PORTAL_ENABLED', JSON.stringify(enabled));
  const context = { exports: {}, URL };
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, context);
  return context.exports;
}
test('门户六模块准确且可关闭，不含巡查', () => {
  const c = config('true');
  assert.equal(c.portalEnabled, true);
  assert.equal(config('false').portalEnabled, false);
  assert.equal(c.portalModules.length, 6);
  assert.equal(c.portalModules[0].path, '/');
  assert.equal(c.portalModules[3].title, '巡察工作流程管控模块');
  assert.equal(c.portalModules[4].lines[1], '监督问效 · 执纪问责');
  assert.equal(new Set(c.portalModules.map(m => m.path)).size, 6);
});
test('站内回跳保留参数，拒绝外部地址及登录循环', () => {
  const { safeReturn } = config('true');
  for (const value of ['https://evil.test', '//evil.test', '/\\evil.test', '/login', '/portal/login', '/change-password', '/../login', '/%2f%2fevil.test', null]) assert.equal(safeReturn(value, '/portal'), '/portal');
  assert.equal(safeReturn('/documents/12?node=810#text', '/portal'), '/documents/12?node=810#text');
});
function guard(name, user, loading = false) {
  const context = {
    exports: {}, window: {}, require(module) {
      if (module === 'react') return { createContext: () => ({}), useContext: () => ({ user, loading }) };
      if (module === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }) };
      if (module === 'antd') return { Result: 'Result', Spin: 'Spin' };
      if (module === 'react-router-dom') return { Navigate: 'Navigate', Outlet: 'Outlet', useLocation: () => ({ pathname: '/documents/12', search: '?node=810', hash: '#text' }) };
      if (module.includes('portal/config')) return { portalEnabled: true };
      return {};
    }
  };
  vm.runInNewContext(ts.transpileModule(read('auth/AuthContext.tsx'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, context);
  return context.exports[name]();
}
test('未登录与强制改密均保留目标，管理员守卫仍要求admin.access', () => {
  assert.equal(guard('RequireAuthenticated', null).props.to, '/login');
  assert.equal(guard('RequireAuthenticated', null).props.state.from, '/documents/12?node=810#text');
  assert.equal(guard('RequireAuthenticated', { must_change_password: true }).props.to, '/change-password');
  assert.equal(guard('RequireAdmin', { permissions: [] }).props.to, '/');
  assert.equal(guard('RequireAdmin', { permissions: ['admin.access'] }).type, 'Outlet');
  assert.equal(guard('RequirePolicy', { permissions: [] }).props.status, '403');
});
test('双入口与门户守卫存在，退出仍调用原认证API', () => {
  const routes = read('routes/router.tsx');
  assert.ok(routes.includes("path: '/login', element: portalEnabled ? <PortalLoginPage /> : <LoginPage />"));
  assert.ok(routes.includes("path: '/portal/login', element: <LoginPage />"));
  assert.ok(routes.includes("element: <RequireAuthenticated />, children:"));
  assert.ok(read('portal/PortalAccount.tsx').includes('auth.logout()'));
  assert.ok(read('api/httpClient.ts').includes("response.status === 401"));
});

test('运行时外链仅影响五个模块，制度与安全回跳保持原规则', () => {
  const c = config('true');
  const targets = c.parsePortalTargets({ version: 1, modules: {
    discipline: { enabled: true, url: 'https://discipline.example/path?a=1' },
    meetings: { enabled: true, url: 'http://10.0.0.1:8080/', openMode: 'sameTab' },
    policy: { enabled: true, url: 'https://other.example' },
  } });
  assert.equal(targets.discipline.openMode, 'newTab');
  assert.equal(targets.meetings.openMode, 'sameTab');
  assert.equal(targets.policy, undefined);
  assert.equal(c.safeReturn('https://discipline.example', '/portal'), '/portal');
});

test('禁用、空地址、缺省模块保留建设中入口', () => {
  const { parsePortalTargets } = config('true');
  for (const modules of [{}, { discipline: { enabled: false, url: 'https://example.test' } },
    { discipline: { enabled: true, url: '' } }]) {
    assert.equal(Object.keys(parsePortalTargets({ version: 1, modules })).length, 0);
  }
});

test('拒绝危险协议、相对地址、凭据、错误版本和错误打开方式', () => {
  const { parsePortalTargets } = config('true');
  for (const url of ['javascript:alert(1)', 'data:text/html,x', '//example.test', '/admin',
    'https://user:password@example.test', 'https://example.test\\x', 'https://example.test\nx']) {
    assert.throws(() => parsePortalTargets({ version: 1, modules: { discipline: { enabled: true, url } } }));
  }
  for (const value of [null, { version: 2, modules: {} }, { version: 1, modules: [] },
    { version: 1, modules: { discipline: { enabled: 'true', url: '' } } },
    { version: 1, modules: { discipline: { enabled: true, url: 'https://example.test', openMode: 'popup' } } }]) {
    assert.throws(() => parsePortalTargets(value));
  }
});

test('部署及开发配置默认关闭，外链禁用缓存和窗口引用', () => {
  for (const path of ['../deploy/portal/portal-config.json', 'public/runtime/portal-config.json']) {
    const value = JSON.parse(readFileSync(new URL('../' + path, import.meta.url), 'utf8'));
    assert.equal(Object.keys(config('true').parsePortalTargets(value)).length, 0);
  }
  const page = read('portal/PortalPages.tsx');
  assert.ok(page.includes("cache: 'no-store'"));
  assert.ok(page.includes('rel="noopener noreferrer"'));
  assert.ok(page.includes('referrerPolicy="no-referrer"'));
});
