/**
 * 文件说明：集中维护首页与问答页共用的制度问题入口，避免多个页面各自维护重复示例。
 * 这些问题仅用于前端快捷入口，不代表热度排序，也不会写入数据库。
 */
export const commonPolicyQuestions = [
  { key: 'conditions', label: '制度规定的申请条件是什么？' },
  { key: 'materials', label: '办理流程需要哪些材料？' },
  { key: 'exceptions', label: '哪些情形不适用该制度？' },
  { key: 'scope', label: '这项规定的适用范围是什么？' },
  { key: 'special-cases', label: '是否存在例外或特殊情形？' },
];
