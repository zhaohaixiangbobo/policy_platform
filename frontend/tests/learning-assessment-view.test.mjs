/** 文件说明：使用Node内置测试验证学习页展示状态，不请求API或生成真实试题。 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../src/pages/learningAssessmentView.ts', import.meta.url), 'utf8');
const context = { exports: {}, require: createRequire(import.meta.url) };
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, context);
const { resolveLearningNavigation, visibleQuestionIndices } = context.exports;
const ready = id => ({ assessment_id: id, status: 'READY', questions: [{ question_id: 'q1' }, { question_id: 'q2' }, { question_id: 'q3' }] });

test('首次读取旧结果留在配置区', () => {
  assert.equal(resolveLearningNavigation({ task: { task_id: 'old', status: 'READY' }, assessment: ready('old') }, null).openAnswer, false);
});
test('观察生成任务后只自动进入一次，新旧结果替换期间不提前进入', () => {
  const pending = resolveLearningNavigation({ task: { task_id: 'new', status: 'GENERATING' }, assessment: ready('old') }, null);
  assert.equal(pending.openAnswer, false);
  assert.equal(pending.pendingTaskId, 'new');
  const state = { task: { task_id: 'new', status: 'READY' }, assessment: ready('new') };
  const completed = resolveLearningNavigation(state, pending.pendingTaskId);
  assert.equal(completed.openAnswer, true);
  assert.equal(resolveLearningNavigation(state, completed.pendingTaskId).openAnswer, false);
});
test('生成失败保持旧结果且不自动切换', () => {
  const result = resolveLearningNavigation({ task: { task_id: 'new', status: 'FAILED' }, assessment: ready('old') }, 'new');
  assert.equal(result.openAnswer, false);
  assert.equal(result.pendingTaskId, null);
});
test('创建后首次读取已就绪也可自动进入', () => {
  assert.equal(resolveLearningNavigation({ task: { task_id: 'new', status: 'READY' }, assessment: ready('new') }, 'new').openAnswer, true);
});
test('空缓存和未提交态不凭空推断错题', () => {
  assert.equal(visibleQuestionIndices({ assessment: null }, true).length, 0);
  assert.equal(visibleQuestionIndices({ assessment: ready('a') }, true).join(','), '0,1,2');
});
test('仅错题筛选保留未答题，且维持原题号', () => {
  const assessment = { ...ready('a'), status: 'SUBMITTED', result: { details: [
    { question_id: 'q1', correct: true, unanswered: false },
    { question_id: 'q2', correct: false, unanswered: false },
    { question_id: 'q3', correct: false, unanswered: true },
  ] } };
  assert.equal(visibleQuestionIndices({ assessment }, true).join(','), '1,2');
  assert.equal(visibleQuestionIndices({ assessment }, false).join(','), '0,1,2');
});
