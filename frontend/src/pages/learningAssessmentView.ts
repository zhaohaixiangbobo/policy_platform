/** 文件说明：学习页纯展示状态规则；不改变请求、持久化数据或后端状态机。 */
import type { LearningState } from '../api/learning';

export function resolveLearningNavigation(state: LearningState, pendingTaskId: string | null) {
  const pending = state.task?.status === 'GENERATING' ? state.task.task_id : pendingTaskId;
  if (state.task?.status === 'FAILED') return { pendingTaskId: null, openAnswer: false };
  if (state.assessment?.status === 'READY' && state.assessment.assessment_id === pending) {
    return { pendingTaskId: null, openAnswer: true };
  }
  return { pendingTaskId: pending, openAnswer: false };
}

export function visibleQuestionIndices(state: LearningState, onlyWrong: boolean): number[] {
  const current = state.assessment;
  if (!current) return [];
  return current.questions.flatMap((q, index) =>
    onlyWrong && current.status === 'SUBMITTED' && current.result?.details.find(d => d.question_id === q.question_id)?.correct ? [] : [index]);
}
