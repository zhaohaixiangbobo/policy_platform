/**
 * 文件说明：把公开的表格结构转换为 Reading View 单元格，并为旧数据保留制表符文本降级。
 * 真实结构优先使用 Parser 已保存的跨列、纵向合并信息，不修改 policy_node 或原文。
 */
import type { DocumentTableCell, DocumentTableStructure } from '../types/documents';

export interface DocumentTableCellView {
  text: string;
  colSpan: number;
  rowSpan: number;
}

export interface DocumentTableDataRow {
  kind: 'data';
  cells: DocumentTableCellView[];
  header: boolean;
}

export interface DocumentTableNoteRow {
  kind: 'note';
  text: string;
}

export type DocumentTableRow = DocumentTableDataRow | DocumentTableNoteRow;

export interface DocumentTableView {
  columnCount: number;
  leadingNotes: string[];
  rows: DocumentTableRow[];
  source: 'structure' | 'text';
}

interface PositionedCell {
  cell: DocumentTableCell;
  gridColumn: number;
}

const HEADER_CELL_PATTERN = /^(序号|编号|项目|分项|类别|类\s*别|名称|姓\s*名|性别|出生年月|日期|时间|单位|部门|职务|岗位|内容|标准|结果|等级|得分|法律依据|认定依据|处罚依据|违法情节|处罚幅度|处置措施|备注|牵头部门)$/;
const STANDALONE_NOTE_PATTERN = /^(备注(?:说明)?|说明|填表说明|检查日期|上架时间|评定等级|.*(?:签字|签名|盖章))[：:]?/;

function cleanCell(value: string): string {
  return value.replace(/[\u00a0 ]+/g, ' ').trim();
}

function rowLooksLikeHeader(values: string[]): boolean {
  const cells = values.map(cleanCell).filter(Boolean);
  if (cells.length < 2) return false;
  const headerCells = cells.filter((value) => HEADER_CELL_PATTERN.test(value.replace(/[：:]/g, ''))).length;
  return headerCells >= 2 || cells[0] === '序号';
}

function appendLine(value: string, continuation: string): string {
  return value ? `${value}\n${continuation}` : continuation;
}

function positionedRows(structure: DocumentTableStructure): PositionedCell[][] {
  return structure.rows.map((row) => {
    let gridColumn = 0;
    return row.map((cell) => {
      const positioned = { cell, gridColumn };
      gridColumn += Math.max(1, cell.grid_span);
      return positioned;
    });
  });
}

function mergedRowSpan(rows: PositionedCell[][], rowIndex: number, target: PositionedCell): number {
  if (target.cell.vertical_merge !== 'restart') return 1;
  let span = 1;
  for (let nextIndex = rowIndex + 1; nextIndex < rows.length; nextIndex += 1) {
    const continuation = rows[nextIndex].find((item) => item.gridColumn === target.gridColumn);
    if (continuation?.cell.vertical_merge !== 'continue') break;
    span += 1;
  }
  return span;
}

function fromStructure(structure: DocumentTableStructure): DocumentTableView | null {
  if (structure.rows.length === 0) return null;
  const rows = positionedRows(structure);
  const columnCount = Math.max(
    1,
    ...rows.map((row) => row.reduce(
      (count, item) => Math.max(count, item.gridColumn + Math.max(1, item.cell.grid_span)),
      0,
    )),
  );
  return {
    columnCount,
    leadingNotes: [],
    source: 'structure',
    rows: rows.map((row, rowIndex) => {
      const visibleCells = row.filter((item) => item.cell.vertical_merge !== 'continue');
      return {
        kind: 'data' as const,
        header: rowLooksLikeHeader(visibleCells.map((item) => item.cell.text)),
        cells: visibleCells.map((item) => ({
          text: cleanCell(item.cell.text),
          colSpan: Math.max(1, item.cell.grid_span),
          rowSpan: mergedRowSpan(rows, rowIndex, item),
        })),
      };
    }),
  };
}

function fromDelimitedText(text: string): DocumentTableView | null {
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  const structuredLines = lines.filter((line) => line.includes('\t'));
  if (structuredLines.length === 0) return null;

  const columnCount = Math.max(...structuredLines.map((line) => line.split('\t').length));
  if (columnCount < 2) return null;

  const leadingNotes: string[] = [];
  const rows: DocumentTableRow[] = [];
  let currentCells: string[] | null = null;
  let tableStarted = false;

  const flushCurrent = () => {
    if (!currentCells) return;
    const values = currentCells.map(cleanCell);
    const padded = [...values, ...Array.from({ length: Math.max(0, columnCount - values.length) }, () => '')];
    rows.push({
      kind: 'data',
      header: rowLooksLikeHeader(padded),
      cells: padded.map((value) => ({ text: value, colSpan: 1, rowSpan: 1 })),
    });
    currentCells = null;
  };

  lines.forEach((rawLine) => {
    const line = rawLine.trimEnd();
    if (!line.trim() && !line.includes('\t')) return;
    if (!line.includes('\t')) {
      const note = cleanCell(line);
      if (!tableStarted) {
        leadingNotes.push(note);
      } else if (STANDALONE_NOTE_PATTERN.test(note)) {
        flushCurrent();
        rows.push({ kind: 'note', text: note });
      } else if (currentCells) {
        const lastIndex = Math.max(0, currentCells.length - 1);
        currentCells[lastIndex] = appendLine(currentCells[lastIndex] ?? '', note);
      } else {
        rows.push({ kind: 'note', text: note });
      }
      return;
    }

    tableStarted = true;
    const parts = line.split('\t');
    if (currentCells && currentCells.length < columnCount && !line.startsWith('\t')) {
      const [continuation, ...remainingCells] = parts;
      const lastIndex = Math.max(0, currentCells.length - 1);
      currentCells[lastIndex] = appendLine(currentCells[lastIndex] ?? '', cleanCell(continuation));
      currentCells.push(...remainingCells);
      return;
    }
    flushCurrent();
    currentCells = parts;
  });

  flushCurrent();
  return rows.length > 0 ? { columnCount, leadingNotes, rows, source: 'text' } : null;
}

export function parseDocumentTable(
  text: string,
  structure: DocumentTableStructure | null,
): DocumentTableView | null {
  return (structure ? fromStructure(structure) : null) ?? fromDelimitedText(text);
}
