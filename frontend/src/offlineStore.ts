import type { Citation, DocumentItem, FormItem, Notebook } from './types';

export interface OfflineChunk {
  id: number;
  doc_id: string;
  page_start: number;
  page_end: number;
  heading: string;
  section_path: string;
  content: string;
}

export interface OfflineBundle {
  version: number;
  generated_at: string;
  synced_at: string;
  notebook: {
    id: string;
    name: string;
    description: string;
  };
  documents: Array<{
    id: string;
    title: string;
    category: string;
    file_type: string;
    page_count: number;
    priority: number;
    status: string;
  }>;
  chunks: OfflineChunk[];
  forms: FormItem[];
}

export interface OfflineSearchOutput {
  hasEvidence: boolean;
  citations: Citation[];
  forms: FormItem[];
  markdown: string;
}

const DB_NAME = 'church_search_offline_db';
const DB_VERSION = 1;
const STORE_BUNDLES = 'bundles';
export const OFFLINE_PDF_CACHE = 'church-search-offline-pdfs-v1';

const SYNONYMS: Record<string, string[]> = {
  위임목사: ['위임 목사', '담임목사', '당회장'],
  담임목사: ['위임목사', '위임 목사', '당회장'],
  부목사: ['부교역자', '교역자'],
  징계: ['권징', '치리', '책벌', '시벌'],
  권징: ['징계', '치리', '재판', '책벌'],
  장로: ['치리장로', '시무장로', '무임장로', '협동장로'],
  임직: ['안수', '장립', '취임', '임명'],
  안수: ['임직', '장립', '안수집사'],
  휴가: ['휴직', '청원휴가', '연차', '안식월', '유급휴가'],
  휴직: ['복직', '청원서', '휴가'],
  재정: ['회계', '예산', '결산', '헌금', '지출'],
  셀지기: ['셀사역자', '셀리더', '지체지기', '교구지기'],
  유급직원: ['직원', '사무원', '관리집사', '복무'],
  청빙: ['위임', '초빙', '선임'],
  세례: ['학습', '입교', '유아세례', '세례교인'],
  서식: ['양식', '신청서', '청원서', '보고서', '소원장'],
};

const STOPWORDS = new Set([
  '알려줘',
  '정리해줘',
  '찾아줘',
  '무엇',
  '어떻게',
  '어떤',
  '있는',
  '있나요',
  '인가요',
  '해주세요',
  '해줘',
  '대한',
  '관련',
  '규정',
  '기준',
  '절차',
  '내용',
  '대해',
  '어디',
  '궁금',
  '알고',
]);

const PARTICLE_RE =
  /(으로서|으로써|에서부터|으로부터|에게는|에서는|으로는|이라도|까지도|에서|에게|으로|부터|까지|처럼|만큼|보다|라도|마저|조차|이나|든지|은|는|이|가|을|를|의|에|로|과|와|도|만|께|며|고|서)$/;

function openOfflineDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('IndexedDB unavailable'));
      return;
    }
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_BUNDLES)) {
        db.createObjectStore(STORE_BUNDLES, { keyPath: 'notebook_id' });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error('IndexedDB open error'));
  });
}

export async function saveOfflineBundle(bundle: OfflineBundle): Promise<void> {
  const db = await openOfflineDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_BUNDLES, 'readwrite');
    tx.objectStore(STORE_BUNDLES).put({
      notebook_id: bundle.notebook.id,
      ...bundle,
    });
    tx.oncomplete = () => {
      db.close();
      resolve();
    };
    tx.onerror = () => {
      db.close();
      reject(tx.error || new Error('IndexedDB write error'));
    };
  });
}

export async function loadOfflineBundle(notebookId: string): Promise<OfflineBundle | null> {
  try {
    const db = await openOfflineDb();
    return await new Promise((resolve) => {
      const tx = db.transaction(STORE_BUNDLES, 'readonly');
      const req = tx.objectStore(STORE_BUNDLES).get(notebookId);
      req.onsuccess = () => {
        db.close();
        resolve((req.result as OfflineBundle) || null);
      };
      req.onerror = () => {
        db.close();
        resolve(null);
      };
    });
  } catch {
    return null;
  }
}

export async function listOfflineBundles(): Promise<OfflineBundle[]> {
  try {
    const db = await openOfflineDb();
    return await new Promise((resolve) => {
      const tx = db.transaction(STORE_BUNDLES, 'readonly');
      const req = tx.objectStore(STORE_BUNDLES).getAll();
      req.onsuccess = () => {
        db.close();
        resolve((req.result as OfflineBundle[]) || []);
      };
      req.onerror = () => {
        db.close();
        resolve([]);
      };
    });
  } catch {
    return [];
  }
}

export function bundleToNotebook(bundle: OfflineBundle): Notebook {
  return {
    id: bundle.notebook.id,
    name: bundle.notebook.name,
    description: bundle.notebook.description,
    system_rules: '',
    doc_count: bundle.documents.length,
    form_count: bundle.forms.length,
    created_at: bundle.generated_at,
    updated_at: bundle.synced_at,
  };
}

export function bundleToDocuments(bundle: OfflineBundle): DocumentItem[] {
  return bundle.documents.map((d) => ({
    id: d.id,
    notebook_id: bundle.notebook.id,
    title: d.title,
    original_filename: `${d.title}.${d.file_type}`,
    file_type: d.file_type,
    category: d.category,
    priority: d.priority,
    page_count: d.page_count,
    ocr_pages: 0,
    total_chars: 0,
    chunk_count: bundle.chunks.filter((c) => c.doc_id === d.id).length,
    form_count: bundle.forms.filter((f) => f.doc_id === d.id).length,
    status: d.status,
    error_msg: '',
    created_at: bundle.generated_at,
  }));
}

function extractQueryTerms(query: string): { primary: string[]; expanded: string[]; articleNums: string[] } {
  const articleNums = Array.from(query.matchAll(/제\s*(\d+)\s*조/g)).map((m) => `제${m[1]}조`);
  const rawTokens = query.match(/[가-힣A-Za-z0-9]+/g) || [];
  const primarySet = new Set<string>();
  const expandedSet = new Set<string>();

  for (const raw of rawTokens) {
    const lower = raw.toLowerCase();
    const stem = lower.length >= 3 ? lower.replace(PARTICLE_RE, '') : lower;
    const candidate = stem.length >= 2 ? stem : lower;
    if (candidate.length < 2 || STOPWORDS.has(candidate)) continue;
    primarySet.add(candidate);
    expandedSet.add(candidate);
    const syns = SYNONYMS[candidate] || SYNONYMS[lower];
    if (syns) {
      syns.forEach((s) => expandedSet.add(s.replace(/\s+/g, '').toLowerCase()));
    }
  }
  articleNums.forEach((a) => {
    primarySet.add(a);
    expandedSet.add(a);
  });

  if (primarySet.size === 0) {
    rawTokens
      .filter((t) => t.length >= 2)
      .forEach((t) => {
        primarySet.add(t.toLowerCase());
        expandedSet.add(t.toLowerCase());
      });
  }

  return {
    primary: Array.from(primarySet),
    expanded: Array.from(expandedSet),
    articleNums,
  };
}

export function searchOfflineBundle(
  bundle: OfflineBundle,
  query: string,
  docIds?: string[],
  topK = 8
): OfflineSearchOutput {
  const allowed = docIds && docIds.length > 0 ? new Set(docIds) : null;
  const docMap = new Map(bundle.documents.map((d) => [d.id, d]));
  const { primary, expanded, articleNums } = extractQueryTerms(query);
  const compactQuery = query.replace(/\s+/g, '').toLowerCase();

  if (expanded.length === 0) {
    return {
      hasEvidence: false,
      citations: [],
      forms: [],
      markdown:
        '제공된 자료에서 해당 정보를 찾을 수 없습니다.\n\n검색 키워드를 조금 더 구체적으로 입력해 주세요.',
    };
  }

  const scored: Array<{ chunk: OfflineChunk; score: number; primaryHits: number }> = [];

  for (const ch of bundle.chunks) {
    if (allowed && !allowed.has(ch.doc_id)) continue;
    const doc = docMap.get(ch.doc_id);
    const headRaw = `${ch.section_path || ''} ${ch.heading || ''}`.toLowerCase();
    const headCompact = headRaw.replace(/\s+/g, '');
    const bodyRaw = ch.content.toLowerCase();
    const bodyCompact = bodyRaw.replace(/\s+/g, '');

    let score = 0;
    let primaryHits = 0;

    if (compactQuery.length >= 4 && bodyCompact.includes(compactQuery)) {
      score += 18;
    }

    for (const art of articleNums) {
      if (headCompact.includes(art) || bodyCompact.includes(art)) {
        score += 16;
        primaryHits += 1;
      }
    }

    for (const term of primary) {
      const compactTerm = term.replace(/\s+/g, '');
      const inHead = headCompact.includes(compactTerm);
      const inBody = bodyCompact.includes(compactTerm);
      if (inHead || inBody) {
        primaryHits += 1;
        score += inHead ? 10 : 0;
        if (inBody) {
          let count = 0;
          let pos = bodyCompact.indexOf(compactTerm);
          while (pos !== -1 && count < 5) {
            count += 1;
            pos = bodyCompact.indexOf(compactTerm, pos + compactTerm.length);
          }
          score += 5 + count * 1.4;
        }
      }
    }

    for (const syn of expanded) {
      if (primary.includes(syn)) continue;
      if (headCompact.includes(syn) || bodyCompact.includes(syn)) {
        score += 3.5;
      }
    }

    if (score > 0) {
      // Gentle document priority tie-breaker
      const prio = doc ? doc.priority : 50;
      score += prio * 0.015;
      scored.push({ chunk: ch, score, primaryHits });
    }
  }

  scored.sort((a, b) => b.score - a.score);
  const top = scored.slice(0, topK);

  // Grounding Gate: require at least one genuine primary hit or strong score
  const hasEvidence =
    top.length > 0 && (top[0].primaryHits >= 1 || top[0].score >= 8.5);

  if (!hasEvidence) {
    return {
      hasEvidence: false,
      citations: [],
      forms: [],
      markdown:
        '제공된 자료에서 해당 정보를 찾을 수 없습니다.\n\n현재 선택된 문서 범위를 확인하시거나 다른 핵심 단어로 다시 검색해 주세요.',
    };
  }

  const citations: Citation[] = top.map(({ chunk, score }) => {
    const doc = docMap.get(chunk.doc_id);
    return {
      chunk_id: chunk.id,
      doc_id: chunk.doc_id,
      doc_title: doc?.title || '문서',
      doc_category: doc?.category || '자료',
      heading: chunk.heading || '',
      section_path: chunk.section_path || '',
      page_start: chunk.page_start,
      page_end: chunk.page_end,
      excerpt: chunk.content.slice(0, 600),
      score: Math.round(score * 10) / 10,
    };
  });

  // Match related forms
  const matchedForms = bundle.forms
    .filter((f) => {
      if (allowed && !allowed.has(f.doc_id)) return false;
      const hay = `${f.title} ${f.category} ${f.sample_text || ''}`.replace(/\s+/g, '').toLowerCase();
      return expanded.some((t) => hay.includes(t.replace(/\s+/g, '')));
    })
    .slice(0, 4);

  const lines: string[] = [
    `> **오프라인 원문 검색 결과** — 인터넷·서버 연결 없이 기기에 저장된 색인에서 관련 조항 **${citations.length}건**을 즉시 추출했습니다.`,
    '',
  ];

  citations.slice(0, 5).forEach((c, idx) => {
    const loc = c.page_start === c.page_end ? `p.${c.page_start}` : `p.${c.page_start}~${c.page_end}`;
    const sec = [c.section_path, c.heading].filter(Boolean).join(' · ');
    lines.push(`### ${idx + 1}. ${c.doc_title} (${loc})`);
    if (sec) lines.push(`**${sec}**`);
    lines.push('');
    lines.push(c.excerpt);
    lines.push('');
  });

  if (matchedForms.length > 0) {
    lines.push('### 관련 서식 · 표');
    matchedForms.forEach((f) => {
      lines.push(`- **${f.title}** (${f.doc_title}, p.${f.page_start})`);
    });
  }

  return {
    hasEvidence: true,
    citations,
    forms: matchedForms,
    markdown: lines.join('\n'),
  };
}

export function getOfflinePageText(
  bundle: OfflineBundle,
  docId: string,
  pageNo: number
): {
  doc_id: string;
  doc_title: string;
  file_type: string;
  page_count: number;
  page_no: number;
  is_ocr: boolean;
  text: string;
} | null {
  const doc = bundle.documents.find((d) => d.id === docId);
  if (!doc) return null;
  const pageChunks = bundle.chunks.filter(
    (c) => c.doc_id === docId && c.page_start <= pageNo && c.page_end >= pageNo
  );
  const text =
    pageChunks.length > 0
      ? pageChunks.map((c) => c.content).join('\n\n')
      : '이 페이지의 텍스트 색인이 오프라인 캐시에 없습니다.';
  return {
    doc_id: doc.id,
    doc_title: doc.title,
    file_type: 'offline-text',
    page_count: doc.page_count,
    page_no: pageNo,
    is_ocr: false,
    text,
  };
}

export async function cacheFormPdfBlob(formId: string, blob: Blob, filename: string): Promise<void> {
  if (typeof caches === 'undefined') return;
  try {
    const cache = await caches.open(OFFLINE_PDF_CACHE);
    const key = `/offline-pdf/${encodeURIComponent(formId)}`;
    const res = new Response(blob, {
      headers: {
        'Content-Type': 'application/pdf',
        'X-Filename': encodeURIComponent(filename),
      },
    });
    await cache.put(key, res);
  } catch {
    // ignore quota errors
  }
}

export async function getCachedFormPdf(formId: string): Promise<{ blob: Blob; filename: string } | null> {
  if (typeof caches === 'undefined') return null;
  try {
    const cache = await caches.open(OFFLINE_PDF_CACHE);
    const res = await cache.match(`/offline-pdf/${encodeURIComponent(formId)}`);
    if (!res) return null;
    const blob = await res.blob();
    const rawName = res.headers.get('X-Filename');
    const filename = rawName ? decodeURIComponent(rawName) : `${formId}.pdf`;
    return { blob, filename };
  } catch {
    return null;
  }
}

export async function countCachedFormPdfs(): Promise<number> {
  if (typeof caches === 'undefined') return 0;
  try {
    const cache = await caches.open(OFFLINE_PDF_CACHE);
    const keys = await cache.keys();
    return keys.length;
  } catch {
    return 0;
  }
}
