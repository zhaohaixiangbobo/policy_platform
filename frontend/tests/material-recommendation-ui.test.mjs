/** 文件说明：隔离验证辅助资料分组、案例详情结构及资料库入口，不调用真实API。 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

function render(items, selected = 'IMAGE', endpoint) {
  const values = [items, null, selected];
  const updates = [];
  const element = (type, props) => ({ type, props });
  const context = { exports: {}, require(name) {
    if (name === 'react') return { useEffect() {}, useState() { const value = values.shift(); return [value, (next) => updates.push(next)]; } };
    if (name === 'react/jsx-runtime') return { jsx: element, jsxs: element, Fragment: 'fragment' };
    if (name === 'antd') return { Button: 'Button', Drawer: 'Drawer', Image: 'Image', Space: 'Space', Tabs: 'Tabs', Typography: { Paragraph: 'Paragraph', Text: 'Text' } };
    if (name === 'react-router-dom') return { Link: 'Link' };
    return {};
  } };
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/components/MaterialRecommendations.tsx', import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020 },
  }).outputText, context);
  return { tree: context.exports.MaterialRecommendations({ query: '信访举报流程和案例', endpoint }), updates };
}
function find(node, type) {
  if (!node || typeof node !== 'object') return undefined;
  if (node.type === type) return node;
  for (const child of [node.props?.children].flat(Infinity)) { const match = find(child, type); if (match) return match; }
}
const fixture = (kind) => ({ id: kind, kind, fields: { title: kind, summary: '摘要' } });
test('推荐展示明确区分命中原文与开头预览', () => {
  const source = readFileSync(new URL('../src/components/MaterialRecommendations.tsx', import.meta.url), 'utf8');
  assert.ok(source.includes('item.match_reason'));
  assert.ok(source.includes('相关原文：${item.match_excerpt}'));
  assert.ok(source.includes('原文预览：${item.preview_text}'));
});
test('学习模式呈现与制度依据同级的并列按钮，不展示问答卡片或Tab', () => {
  const { tree } = render([fixture('IMAGE'), fixture('CASE')], 'IMAGE', '/learning/question/materials');
  assert.equal(find(tree, 'Tabs'), undefined);
  assert.equal(find(tree, 'Link'), undefined);
  assert.equal(find(tree, 'Button').props.className, 'learning-material-button');
  assert.ok(find(tree, 'Button').props.icon);
  assert.equal(tree.props.style.display, 'inline-flex');
});
test('学习资料按钮不使用浅蓝底强调样式', () => {
  const css = readFileSync(new URL('../src/styles/material-recommendations.css', import.meta.url), 'utf8');
  const block = css.match(/\.learning-material-button\.ant-btn\s*\{([\s\S]*?)\}/)?.[1] || '';
  assert.ok(block.includes('background: #fff'));
  assert.ok(!block.includes('background: #eef4ff'));
});
test('双类使用Tab，切换仅更新展示状态，数量表示本次推荐', () => {
  const { tree, updates } = render([fixture('IMAGE'), fixture('CASE')]);
  const tabs = find(tree, 'Tabs');
  assert.equal(tabs.props.items.length, 2);
  assert.equal(tabs.props.activeKey, 'IMAGE');
  assert.equal(tabs.props.items[1].label, '案例（1）');
  tabs.props.onChange('CASE');
  assert.deepEqual(updates, ['CASE']);
  assert.equal(find(tree, 'Link').props.to, '/materials');
});
test('单类不用Tab，空结果隐藏，案例偏好可选中案例', () => {
  assert.equal(find(render([fixture('CASE')]).tree, 'Tabs'), undefined);
  assert.equal(render([]).tree, null);
  assert.equal(find(render([fixture('IMAGE'), fixture('CASE')], 'CASE').tree, 'Tabs').props.activeKey, 'CASE');
});
test('引用仅折叠列表，正文引用映射仍保留全集', () => {
  const source = readFileSync(new URL('../src/pages/ChatPage.tsx', import.meta.url), 'utf8');
  assert.ok(source.includes('citationsExpanded ? item.citations : item.citations.slice(0, 3)'));
  assert.ok(source.includes('new Map(item.citations.map('));
  assert.ok(source.includes('展开全部${item.citations.length}条'));
  assert.ok(source.includes('useEffect(() => setCitationsExpanded(false), [item.id])'));
});
test('案例详情只呈现三项业务内容，侧栏入口指向配套资料库', () => {
  const recommendationSource = readFileSync(new URL('../src/components/MaterialRecommendations.tsx', import.meta.url), 'utf8');
  const chatSource = readFileSync(new URL('../src/pages/ChatPage.tsx', import.meta.url), 'utf8');
  assert.ok(recommendationSource.includes('title="人员与问题信息"'));
  assert.ok(recommendationSource.includes('title="处理结果"'));
  assert.ok(recommendationSource.includes('title="案情描述"'));
  assert.ok(recommendationSource.includes('未公布'));
  assert.ok(recommendationSource.includes('recommendation-case-original'));
  assert.ok(chatSource.includes("navigate('/materials')}>配套资料库"));
  assert.ok(!chatSource.includes("navigate('/settings/about')}>服务说明"));
});
