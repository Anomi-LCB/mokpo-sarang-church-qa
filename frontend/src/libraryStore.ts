import type { DocumentItem } from './types';

export interface ShelfState {
  /** Personal user-pinned doc IDs shown at the very top of the left Workspace Shelf */
  pinnedIds: string[];
  /** Personal loaded (non-pinned) doc IDs currently placed on the left Workspace Shelf */
  loadedIds: string[];
  /** Docs explicitly unloaded from the shelf by the user (only applies to non-admin-pinned docs) */
  unloadedIds: string[];
}

function shelfKey(notebookId: string): string {
  return `church_search_shelf_v3_${notebookId}`;
}

export function loadShelfState(notebookId: string): ShelfState {
  try {
    const raw = localStorage.getItem(shelfKey(notebookId));
    if (raw) {
      const p = JSON.parse(raw) as Partial<ShelfState>;
      return {
        pinnedIds: Array.isArray(p.pinnedIds) ? p.pinnedIds : [],
        loadedIds: Array.isArray(p.loadedIds) ? p.loadedIds : [],
        unloadedIds: Array.isArray(p.unloadedIds) ? p.unloadedIds : [],
      };
    }
  } catch {
    // ignore
  }
  return { pinnedIds: [], loadedIds: [], unloadedIds: [] };
}

export function saveShelfState(notebookId: string, st: ShelfState): void {
  try {
    localStorage.setItem(shelfKey(notebookId), JSON.stringify(st));
  } catch {
    // ignore
  }
}

/**
 * Compute which documents appear on the left Workspace Shelf:
 * 1. Pinned group (always on top): Admin-pinned (`is_pinned_default=1`) + User-pinned (`pinnedIds`)
 * 2. Loaded group: Explicitly loaded docs (`loadedIds`), OR if the notebook has <= 12 docs,
 *    auto-shows any doc not explicitly unloaded so small notebooks work effortlessly out-of-the-box!
 */
export function resolveShelfDocuments(
  documents: DocumentItem[],
  shelf: ShelfState
): { pinnedDocs: DocumentItem[]; loadedDocs: DocumentItem[]; allShelfDocs: DocumentItem[] } {
  const pinnedSet = new Set<string>(shelf.pinnedIds);
  const loadedSet = new Set<string>(shelf.loadedIds);
  const unloadedSet = new Set<string>(shelf.unloadedIds);

  const pinnedDocs: DocumentItem[] = [];
  const loadedDocs: DocumentItem[] = [];
  const autoShowSmall = documents.length <= 12;

  for (const d of documents) {
    const isAdminPin = Boolean(d.is_pinned_default);
    const isUserPin = pinnedSet.has(d.id);
    if (isAdminPin || isUserPin) {
      pinnedDocs.push(d);
    } else if (loadedSet.has(d.id)) {
      loadedDocs.push(d);
    } else if (autoShowSmall && !unloadedSet.has(d.id)) {
      loadedDocs.push(d);
    }
  }

  return {
    pinnedDocs,
    loadedDocs,
    allShelfDocs: [...pinnedDocs, ...loadedDocs],
  };
}
