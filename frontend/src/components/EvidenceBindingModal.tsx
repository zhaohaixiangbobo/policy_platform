/**
 * 文件说明：供制度关系和流程共用的真实active制度Node证据选择器。
 */
import { Form, Input, Modal, Select, Typography, message } from 'antd';
import { useEffect, useMemo, useState } from 'react';

import { getEvidenceCatalog } from '../api/admin';
import type { EvidenceBindingInput, EvidenceCatalogDocument } from '../api/admin';

interface Props {
  open: boolean;
  ownerKind: 'NODE' | 'EDGE' | 'RELATION';
  cellId: string;
  onCancel: () => void;
  onSubmit: (payload: EvidenceBindingInput) => Promise<void>;
}

export function EvidenceBindingModal({ open, ownerKind, cellId, onCancel, onSubmit }: Props) {
  const [documents, setDocuments] = useState<EvidenceCatalogDocument[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<{ documentId: number; nodeId: number; quote: string }>();
  const documentId = Form.useWatch('documentId', form);
  const nodeId = Form.useWatch('nodeId', form);
  const document = useMemo(() => documents.find((item) => item.id === documentId), [documents, documentId]);
  const node = useMemo(() => document?.nodes.find((item) => item.id === nodeId), [document, nodeId]);

  useEffect(() => {
    if (!open) return;
    void getEvidenceCatalog().then(setDocuments).catch((error) => message.error(error.message));
  }, [open]);
  useEffect(() => {
    if (node) form.setFieldValue('quote', node.text);
  }, [node?.id]);

  const submit = async () => {
    const values = await form.validateFields();
    if (!document || !node) return;
    setSubmitting(true);
    try {
      await onSubmit({
        owner_kind: ownerKind, cell_id: cellId, document_id: document.id,
        parse_run_id: document.active_parse_run_id, primary_node_id: node.id,
        page_start: node.page_start, page_end: node.page_end, quote_snapshot: values.quote,
      });
      form.resetFields();
    } finally { setSubmitting(false); }
  };

  return (
    <Modal title="绑定制度证据" open={open} onCancel={onCancel} onOk={() => void submit()} confirmLoading={submitting} okText="绑定">
      <Typography.Paragraph type="secondary">仅列出当前active ParseRun中的真实Node；绑定后保存版本、页码和原文快照。</Typography.Paragraph>
      <Form form={form} layout="vertical">
        <Form.Item label="制度" name="documentId" rules={[{ required: true, message: '请选择制度' }]}><Select showSearch optionFilterProp="label" options={documents.map((item) => ({ value: item.id, label: item.document_code ? `${item.title}（${item.document_code}）` : item.title }))} onChange={() => form.setFieldsValue({ nodeId: undefined, quote: '' })} /></Form.Item>
        <Form.Item label="证据Node" name="nodeId" rules={[{ required: true, message: '请选择证据Node' }]}><Select showSearch optionFilterProp="label" options={(document?.nodes ?? []).map((item) => ({ value: item.id, label: `${item.path_text || item.title || `Node ${item.id}`} · 第${item.page_start ?? '-'}页` }))} /></Form.Item>
        <Form.Item label="原文快照" name="quote" rules={[{ required: true, message: '证据原文不能为空' }]}><Input.TextArea rows={7} /></Form.Item>
      </Form>
    </Modal>
  );
}
