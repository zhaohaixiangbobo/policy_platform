/**
 * 文件说明：定义从首页等入口进入智能问答页时使用的一次性路由交接数据。
 * 问答请求仍由 Chat 页面统一执行，入口页面只负责传递用户已经确认的问题。
 */
export interface ChatLaunchState {
  source: 'home';
  question: string;
  autoSubmit: true;
}

export function createChatLaunchState(question: string): ChatLaunchState {
  return {
    source: 'home',
    question,
    autoSubmit: true,
  };
}

export function parseChatLaunchState(value: unknown): ChatLaunchState | null {
  if (!value || typeof value !== 'object') return null;
  const candidate = value as Partial<ChatLaunchState>;
  if (
    candidate.source !== 'home'
    || candidate.autoSubmit !== true
    || typeof candidate.question !== 'string'
    || !candidate.question.trim()
  ) return null;
  return {
    source: 'home',
    question: candidate.question.trim(),
    autoSubmit: true,
  };
}
