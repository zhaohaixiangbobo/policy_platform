/** 文件说明：学习自测公开接口；答题态类型不要求正确答案和证据字段。 */
import { useEffect, useState } from 'react';
import { requestJson } from './httpClient';

export interface Features { learning_assessment: boolean; learning_max_questions: number; learning_ttl_hours: number }
export function useFeatures() {
  const [features, setFeatures] = useState<Features | null>(null);
  useEffect(() => { let alive = true; requestJson<Features>('/api/v1/features').then(v => { if (alive) setFeatures(v); })
    .catch(() => { if (alive) setFeatures({ learning_assessment: false, learning_max_questions: 15, learning_ttl_hours: 24 }); });
    return () => { alive = false; }; }, []);
  return features;
}
export interface LearningQuestion {
  question_id: string; question_type: 'SINGLE' | 'MULTIPLE' | 'TRUE_FALSE'; question: string; options: string[];
  correct_answer?: number[]; explanation?: string; primary_node_id?: number; source_text_snapshot?: string; knowledge_point?: string;
}
export interface Assessment {
  assessment_id: string; document_id: number; document_title: string; document_code: string | null;
  parse_run_id: number; index_run_id: number; status: 'READY' | 'SUBMITTED'; expires_at: string;
  questions: LearningQuestion[]; user_answers: Record<string, number[]>; version_changed?: boolean;
  result?: { score: number; total: number; correct: number; unanswered: number;
    details: { question_id: string; correct: boolean; unanswered: boolean }[];
    weak_points: { primary_node_id: number; knowledge_point: string; total: number; wrong: number; unanswered: number }[] };
}
export interface LearningState {
  task: { task_id: string; status: string; progress: string; error: string | null } | null;
  assessment: Assessment | null;
}
export const getLearning = () => requestJson<LearningState>('/api/v1/learning-assessments/current');
export const createLearning = (body: object) => requestJson('/api/v1/learning-assessments', { method: 'POST', body: JSON.stringify(body) });
export const saveLearning = (id: string, answers: Record<string, number[]>) => requestJson(`/api/v1/learning-assessments/${id}/answers`, { method: 'PUT', body: JSON.stringify({ answers }) });
export const submitLearning = (id: string, answers: Record<string, number[]>) => requestJson<Assessment>(`/api/v1/learning-assessments/${id}/submit`, { method: 'POST', body: JSON.stringify({ answers }) });
