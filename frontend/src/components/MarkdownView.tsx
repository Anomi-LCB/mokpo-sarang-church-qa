import React from 'react';

interface Props {
  content: string;
}

function renderInline(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const regex = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) {
      parts.push(text.slice(last, m.index));
    }
    const token = m[0];
    if (token.startsWith('**') && token.endsWith('**')) {
      parts.push(
        <strong key={key++} className="font-semibold text-[#1d1d1f]">
          {token.slice(2, -2)}
        </strong>
      );
    } else if (token.startsWith('`') && token.endsWith('`')) {
      parts.push(
        <code key={key++} className="rounded-md bg-[#f5f5f7] px-1.5 py-0.5 text-[0.86em] text-[#1d1d1f]">
          {token.slice(1, -1)}
        </code>
      );
    }
    last = m.index + token.length;
  }
  if (last < text.length) {
    parts.push(text.slice(last));
  }
  return parts;
}

export const MarkdownView: React.FC<Props> = ({ content }) => {
  const lines = content.replace(/\r\n/g, '\n').split('\n');
  const blocks: React.ReactNode[] = [];
  let i = 0;
  let k = 0;

  while (i < lines.length) {
    const raw = lines[i];
    const line = raw.trim();

    if (!line) {
      i++;
      continue;
    }

    if (line.includes('|') && i + 1 < lines.length && /^\|?[\s:-]+\|[\s|:-]+$/.test(lines[i + 1].trim())) {
      const headerCells = line.replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
      i += 2;
      const bodyRows: string[][] = [];
      while (i < lines.length && lines[i].trim().includes('|')) {
        const rowCells = lines[i].trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
        bodyRows.push(rowCells);
        i++;
      }
      blocks.push(
        <div key={k++} className="my-3.5 overflow-x-auto rounded-xl border border-black/[0.08]">
          <table className="w-full border-collapse text-left text-xs sm:text-[13.5px]">
            <thead className="bg-[#f5f5f7] text-[#1d1d1f]">
              <tr>
                {headerCells.map((h, idx) => (
                  <th key={idx} className="border-b border-black/[0.08] px-3 py-2 font-semibold">
                    {renderInline(h)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-black/[0.05] bg-white">
              {bodyRows.map((row, rIdx) => (
                <tr key={rIdx}>
                  {row.map((cell, cIdx) => (
                    <td key={cIdx} className="px-3 py-2 text-[#3a3a3c]">
                      {renderInline(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    if (line.startsWith('### ')) {
      blocks.push(
        <h3 key={k++} className="mt-5 mb-1.5 text-[14px] font-semibold tracking-tight text-[#1d1d1f]">
          {renderInline(line.slice(4))}
        </h3>
      );
      i++;
      continue;
    }
    if (line.startsWith('## ')) {
      blocks.push(
        <h2 key={k++} className="mt-5 mb-2 border-b border-black/[0.07] pb-1.5 text-[15.5px] font-semibold tracking-tight text-[#1d1d1f]">
          {renderInline(line.slice(3))}
        </h2>
      );
      i++;
      continue;
    }
    if (line.startsWith('# ')) {
      blocks.push(
        <h1 key={k++} className="mt-4 mb-2 text-[17px] font-bold tracking-tight text-[#1d1d1f]">
          {renderInline(line.slice(2))}
        </h1>
      );
      i++;
      continue;
    }

    if (/^(-{3,}|\*{3,})$/.test(line)) {
      blocks.push(<hr key={k++} className="my-4 border-black/[0.07]" />);
      i++;
      continue;
    }

    if (line.startsWith('> ')) {
      const qLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('> ')) {
        qLines.push(lines[i].trim().slice(2));
        i++;
      }
      blocks.push(
        <blockquote
          key={k++}
          className="my-3 rounded-r-lg border-l-2 border-[#0f4c81] bg-[#f7f7f5] px-3.5 py-2.5 text-[13.5px] text-[#3f3f46]"
        >
          {qLines.map((ql, idx) => (
            <p key={idx} className="leading-relaxed">
              {renderInline(ql)}
            </p>
          ))}
        </blockquote>
      );
      continue;
    }

    if (/^[-*•]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*•]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*•]\s+/, ''));
        i++;
      }
      blocks.push(
        <ul key={k++} className="my-2 space-y-1.5 pl-4 text-[14px] leading-[1.7] text-[#2c2c2e] list-disc">
          {items.map((it, idx) => (
            <li key={idx}>{renderInline(it)}</li>
          ))}
        </ul>
      );
      continue;
    }

    if (/^(\d+\.|[①-⑮]|\d+\))\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^(\d+\.|[①-⑮]|\d+\))\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim());
        i++;
      }
      blocks.push(
        <div key={k++} className="my-2 space-y-1.5 text-[14px] leading-[1.7] text-[#2c2c2e]">
          {items.map((it, idx) => (
            <p key={idx} className="pl-1.5">
              {renderInline(it)}
            </p>
          ))}
        </div>
      );
      continue;
    }

    blocks.push(
      <p key={k++} className="my-1.5 text-[14px] leading-[1.72] text-[#2c2c2e]">
        {renderInline(line)}
      </p>
    );
    i++;
  }

  return <div className="min-w-0 space-y-0.5">{blocks}</div>;
};
