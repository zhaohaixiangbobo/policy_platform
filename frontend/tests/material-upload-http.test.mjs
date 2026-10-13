/** 文件说明：验证资料HTTP、应用上下文、详情分区和图片交互，全程隔离真实接口。 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

function client(response = {}) {
  const calls = [];
  const context = {
    exports: {}, FormData, Headers, document: { cookie: 'policy_platform_csrf=csrf-token' },
    fetch: async (path, options) => { calls.push({ path, options }); return { ok: true, status: 200, headers: new Headers(), json: async () => ({ ok: true }), ...response }; }
  };
  const source = readFileSync(new URL('../src/api/httpClient.ts', import.meta.url), 'utf8');
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, context);
  return { request: context.exports.requestJson, calls };
}
test('图片与Excel上传由浏览器设置multipart边界，同时携带CSRF', async () => {
  const { request, calls } = client();
  const body = new FormData(); body.append('metadata', '{}');
  await request('/api/v1/materials/images', { method: 'POST', body });
  assert.equal(calls[0].options.headers.has('Content-Type'), false);
  assert.equal(calls[0].options.headers.get('X-CSRF-Token'), 'csrf-token');
  assert.equal(calls[0].options.credentials, 'same-origin');
  assert.equal(calls[0].options.body, body);
});

test('FastAPI两条日期校验错误显示字段与消息，不显示object Object或原始输入', async () => {
  const { request } = client({
    ok: false, status: 422, json: async () => ({
      detail: [
        { loc: ['query', 'date_from'], msg: '日期不合法', input: 'private-value' },
        { loc: ['query', 'date_to'], msg: '日期不合法', input: 'private-value' },
      ]
    })
  });
  await assert.rejects(request('/api/v1/materials'), (error) => {
    assert.equal(error.status, 422);
    assert.equal(error.message, 'query.date_from：日期不合法；query.date_to：日期不合法');
    assert.equal(error.message.includes('private-value'), false);
    return true;
  });
});

test('业务文本错误与未知错误对象保留稳定提示', async () => {
  for (const [payload, expected] of [[{ detail: '权限不足' }, '权限不足'], [{ error: { message: '版本冲突' } }, '版本冲突'], [{ detail: { unknown: true } }, '平台服务请求失败']]) {
    const { request } = client({ ok: false, status: 400, json: async () => payload });
    await assert.rejects(request('/api/v1/materials'), (error) => error.message === expected);
  }
});

function materialClient() {
  const calls = [];
  const requests = [];
  const context = { exports: {}, URLSearchParams, FormData, require: () => ({ requestJson: async (url, options) => { calls.push(url); requests.push({ url, options }); return {}; } }) };
  const source = readFileSync(new URL('../src/api/materials.ts', import.meta.url), 'utf8');
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, context);
  return { list: context.exports.listMaterials, preview: context.exports.previewCases, action: context.exports.materialAction, calls, requests };
}

test('列表保留明确状态，使用新版筛选参数', async () => {
  const { list, calls } = materialClient();
  for (const state of ['PUBLISHED', 'DRAFT', '']) {
    await list({ state, domain: '', page: '1' });
    const query = new URL(calls.at(-1), 'http://localhost').searchParams;
    assert.equal(query.has('date_from'), false);
    assert.equal(query.has('date_to'), false);
    assert.equal(query.get('state'), state);
  }
});

test('案例预览只上传Excel，不附加公共来源信息', async () => {
  const { preview, requests } = materialClient();
  await preview(new File(['sample'], '案例.xlsx'));
  assert.deepEqual([...requests[0].options.body.keys()], ['file']);
});
test('既有JSON写请求保持原行为', async () => {
  const { request, calls } = client();
  await request('/api/v1/example', { method: 'PUT', body: '{}' });
  assert.equal(calls[0].options.headers.get('Content-Type'), 'application/json');
  assert.equal(calls[0].options.headers.get('X-CSRF-Token'), 'csrf-token');
});
test('GET请求不附加写入头', async () => {
  const { request, calls } = client();
  await request('/api/v1/materials');
  assert.equal(calls[0].options.headers.has('Content-Type'), false);
  assert.equal(calls[0].options.headers.has('X-CSRF-Token'), false);
});

test('真实入口向路由提供确认弹窗与消息API，且不增加布局包裹层', () => {
  const require = createRequire(import.meta.url);
  const React = require('react');
  const { App } = require('antd');
  const { renderToStaticMarkup } = require('react-dom/server');
  let root;
  let reachedRoute = false;
  function RouteProbe() {
    reachedRoute = true;
    const { modal, message } = App.useApp();
    assert.equal(typeof modal.confirm, 'function', '发布和下架都依赖App提供的modal.confirm');
    assert.equal(typeof message.success, 'function');
    assert.equal(typeof message.error, 'function');
    return React.createElement('main', null, '资料路由');
  }
  // 执行真实入口，替换认证和路由以阻止网络访问；保留真实React与Ant Design上下文。
  const context = {
    exports: {},
    document: { getElementById: () => ({}) },
    require: (name) => {
      if (name === 'react-dom/client') return { createRoot: () => ({ render: (tree) => { root = tree; } }) };
      if (name === 'react-router-dom') return { RouterProvider: RouteProbe };
      if (name === './routes/router') return { router: {} };
      if (name === './auth/AuthContext') return { AuthProvider: ({ children }) => children };
      if (name === './app/theme') return { appTheme: {} };
      if (name.endsWith('.css')) return {};
      return require(name);
    },
  };
  const source = readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8');
  vm.runInNewContext(ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
      jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
    }
  }).outputText, context);
  const html = renderToStaticMarkup(root);
  assert.equal(reachedRoute, true);
  assert.equal(html, '<main>资料路由</main>');
});

for (const operation of ['PUBLISH', 'OFFLINE']) {
  test(`${operation}批量操作保留全部资料ID和版本号`, async () => {
    const { action, requests } = materialClient();
    await action(operation, [{ id: 'material-1', version: 3 }, { id: 'material-2', version: 8 }]);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, '/api/v1/materials/actions');
    assert.equal(requests[0].options.method, 'POST');
    assert.deepEqual(JSON.parse(requests[0].options.body), {
      action: operation,
      items: [{ id: 'material-1', expected_version: 3 }, { id: 'material-2', expected_version: 8 }],
    });
  });
}

function detailModule(react) {
  const require = createRequire(import.meta.url);
  const React = require('react');
  const context = {
    exports: {},
    ResizeObserver: class { observe() { } disconnect() { } },
    require: (name) => {
      if (name === 'react') return react || React;
      if (name === '../auth/AuthContext' || name === '../api/materials' || name.endsWith('.css')) return {};
      if (name === '../components/UiIcon') return { UiIcon: () => React.createElement('span') };
      return require(name);
    },
  };
  // 仅在测试副本中导出内部组件，生产模块不增加对外接口。
  const source = readFileSync(new URL('../src/pages/MaterialsPage.tsx', import.meta.url), 'utf8') + '\nexport { MaterialDetailReading, MaterialImageViewer };';
  vm.runInNewContext(ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
    }
  }).outputText, context);
  return context.exports;
}

const detailFixture = {
  id: 'material-1', kind: 'CASE', state: 'PUBLISHED', revision_id: 'revision-1', revision_no: 1,
  fields: {
    title: '测试案例', domains: ['纪检监督'], tags: ['廉洁履职'], problem_types: ['测试问题'],
    person_category: '业务岗', position: '专管员', rank: '', political_status: '', age: '44', outcome: '测试处理结果',
    original: '原文第一行\n<script>不得执行</script>\n原文末行',
  },
  file_url: null, provenance: { filename: '案例.xlsx', sheet: '案例', row: 2 },
};

test('案例详情保留四个阅读分区、完整原文和导入记录', () => {
  const require = createRequire(import.meta.url);
  const { createElement } = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { MaterialDetailReading } = detailModule();
  const html = renderToStaticMarkup(createElement(MaterialDetailReading, { detail: detailFixture }));
  for (const key of ['info', 'problems', 'outcome', 'original']) assert.ok(html.includes(`id="material-section-${key}"`));
  for (const text of ['案例内容导航', '业务岗', '测试处理结果', '案例.xlsx', '专管员', '44', '未填写']) assert.ok(html.includes(text), text);
  assert.ok(html.includes('原文第一行\n&lt;script&gt;不得执行&lt;/script&gt;\n原文末行'));
  assert.equal(/相关资料|浏览量|收藏数/.test(html), false);
  assert.ok(html.includes('案例仅供学习参考，不替代制度依据或一般处理标准。'));
});

test('案例导航只滚动正文容器，短原文到达底部仍高亮最后一节', () => {
  const require = createRequire(import.meta.url);
  const React = require('react');
  let active = 'info';
  let scrolled;
  const root = {
    scrollTop: 30, clientHeight: 500, scrollHeight: 1000,
    getBoundingClientRect: () => ({ top: 100 }),
    querySelector: () => ({ getBoundingClientRect: () => ({ top: 900 }) }),
    scrollTo: (options) => { scrolled = options; },
  };
  const { MaterialDetailReading } = detailModule({
    ...React,
    useRef: () => ({ current: root }), useState: () => [active, (value) => { active = value; }],
  });
  const tree = MaterialDetailReading({ detail: detailFixture });
  const [nav, content] = tree.props.children;
  nav.props.children[3].props.onClick();
  assert.equal(scrolled.top, 810);
  assert.equal(scrolled.behavior, 'smooth');
  assert.equal(active, 'original');
  active = 'outcome'; root.scrollTop = 500;
  content.props.onScroll(); assert.equal(active, 'original');
  root.scrollTop = 0; content.props.onScroll(); assert.equal(active, 'info');
});

test('流程图详情展示图片与侧栏，缺少图片时明确提示', () => {
  const require = createRequire(import.meta.url);
  const { createElement } = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { MaterialDetailReading } = detailModule();
  const html = renderToStaticMarkup(createElement(MaterialDetailReading, { detail: { ...detailFixture, kind: 'IMAGE' } }));
  for (const text of ['流程图预览', '流程图资料信息', '内容简介', '该资料暂无可查看的图片']) assert.ok(html.includes(text), text);
  assert.equal(html.includes('案例内容导航'), false);
  assert.equal(html.includes('material-section-original'), false);
});

test('图片适配宽度与全屏状态，下载沿用受控地址', () => {
  const require = createRequire(import.meta.url);
  const React = require('react');
  const { Image, Button, Alert } = require('antd');
  const state = [];
  let cursor = 0;
  let effect;
  let measured = false;
  const scrolls = [];
  const viewport = { current: { clientWidth: 660, scrollTo: (value) => scrolls.push(value) } };
  const { MaterialImageViewer } = detailModule({
    ...React,
    useState: (initial) => {
      const slot = cursor++;
      if (!(slot in state)) state[slot] = initial;
      return [state[slot], (value) => { state[slot] = typeof value === 'function' ? value(state[slot]) : value; }];
    },
    useRef: () => viewport,
    useEffect: (callback) => { if (!measured) effect = callback; },
  });
  const detail = { ...detailFixture, kind: 'IMAGE', file_url: '/api/v1/materials/material-1/revisions/revision-1/file', file: { filename: '原始流程图.jpg' } };
  let tree;
  const render = () => { cursor = 0; tree = MaterialImageViewer({ detail }); };
  const find = (predicate) => {
    let result;
    const walk = (node) => {
      if (!React.isValidElement(node) || result) return;
      if (predicate(node)) { result = node; return; }
      React.Children.forEach(node.props.children, walk);
    };
    walk(tree);
    assert.ok(result, '目标控件必须存在');
    return result;
  };
  const image = () => find((node) => node.type === Image);
  const button = (text) => find((node) => node.type === Button && (node.props['aria-label'] === text || node.props.children === text));
  render(); effect(); measured = true; render();
  assert.equal(button('全屏查看').props.disabled, true);
  assert.equal(button('下载').props.href, undefined);
  image().props.onLoad({ currentTarget: { naturalWidth: 1200, naturalHeight: 2400 } }); render();
  assert.equal(Math.round(image().props.width), 620);
  button('全屏查看').props.onClick(); render(); assert.equal(image().props.preview.visible, true);
  image().props.preview.onVisibleChange(false); render(); assert.equal(image().props.preview.visible, false);
  assert.equal(button('下载').props.href, detail.file_url);
  assert.equal(button('下载').props.download, '原始流程图.jpg');
  image().props.onError(); render();
  assert.equal(button('全屏查看').props.disabled, true);
  assert.equal(button('下载').props.href, undefined);
  find((node) => node.type === Alert).props.action.props.onClick(); render();
  assert.equal(image().props.src, detail.file_url);
});
