import { useState, useEffect, useCallback } from 'react';
import api from '../../services/api';

interface ShortlistItem {
  id: string;
  name: {
    id: string;
    display_name: string;
    canonical_name: string;
    origin_backgrounds: string[];
    length_category: string;
    age_style_category: string;
    historical_significance_score: number;
  };
  match_strength_score: number;
}

/**
 * Shortlist page: ordered list of shortlisted names with reorder and compare.
 */
export default function ShortlistPage() {
  const [items, setItems] = useState<ShortlistItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [compareMode, setCompareMode] = useState(false);
  const [selectedForCompare, setSelectedForCompare] = useState<string[]>([]);

  const loadShortlist = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await api.get('/shortlist/');
      setItems(res.data.data || []);
    } catch {
      // Silently handle
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadShortlist();
    });
  }, [loadShortlist]);

  const moveItem = (index: number, direction: 'up' | 'down') => {
    const newItems = [...items];
    const targetIndex = direction === 'up' ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= newItems.length) return;

    [newItems[index], newItems[targetIndex]] = [newItems[targetIndex], newItems[index]];
    setItems(newItems);
  };

  const toggleCompareSelection = (id: string) => {
    setSelectedForCompare((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= 2) return [prev[1], id]; // Keep max 2
      return [...prev, id];
    });
  };

  const compareItems = items.filter((item) =>
    selectedForCompare.includes(item.id)
  );

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh]">
        <div className="w-10 h-10 border-3 border-primary border-t-transparent rounded-full animate-spin mb-4" />
        <p className="text-text-secondary text-sm">Loading shortlist...</p>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] px-4 text-center">
        <span className="text-5xl mb-4">⭐</span>
        <h2 className="text-xl font-bold text-text mb-2">No finalists yet</h2>
        <p className="text-text-secondary text-sm">
          Shortlist your favorite matches to compare them here.
        </p>
      </div>
    );
  }

  return (
    <div className="px-4 pt-6 pb-4">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold text-text">Shortlist</h1>
        <button
          onClick={() => {
            setCompareMode(!compareMode);
            setSelectedForCompare([]);
          }}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            compareMode
              ? 'bg-primary text-white'
              : 'bg-bg-muted text-text-secondary hover:bg-border'
          }`}
        >
          {compareMode ? 'Done' : 'Compare'}
        </button>
      </div>

      {compareMode && (
        <p className="text-xs text-text-muted mb-4">
          Select 2 names to compare side by side
        </p>
      )}

      {/* Ordered list */}
      <div className="space-y-2 mb-6">
        {items.map((item, index) => (
          <div
            key={item.id}
            className={`bg-bg-card rounded-xl border p-3 shadow-card flex items-center gap-3 transition-colors ${
              compareMode && selectedForCompare.includes(item.id)
                ? 'border-primary bg-primary-muted'
                : 'border-border'
            }`}
            onClick={compareMode ? () => toggleCompareSelection(item.id) : undefined}
          >
            {/* Rank number */}
            <span className="w-6 h-6 rounded-full bg-primary-muted text-primary-dark text-xs font-bold flex items-center justify-center shrink-0">
              {index + 1}
            </span>

            {/* Name info */}
            <div className="flex-1 min-w-0">
              <h3 className="font-semibold text-text truncate">
                {item.name.display_name}
              </h3>
              <div className="flex gap-1 mt-0.5">
                {item.name.origin_backgrounds.slice(0, 2).map((o) => (
                  <span
                    key={o}
                    className="text-xs text-text-muted"
                  >
                    {o}
                  </span>
                ))}
              </div>
            </div>

            {/* Reorder buttons (when not in compare mode) */}
            {!compareMode && (
              <div className="flex flex-col gap-0.5">
                <button
                  onClick={() => moveItem(index, 'up')}
                  disabled={index === 0}
                  className="w-6 h-6 rounded bg-bg-muted text-text-muted text-xs flex items-center justify-center disabled:opacity-30 hover:text-text-secondary"
                  aria-label="Move up"
                >
                  ↑
                </button>
                <button
                  onClick={() => moveItem(index, 'down')}
                  disabled={index === items.length - 1}
                  className="w-6 h-6 rounded bg-bg-muted text-text-muted text-xs flex items-center justify-center disabled:opacity-30 hover:text-text-secondary"
                  aria-label="Move down"
                >
                  ↓
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Compare view (side-by-side finalists) */}
      {compareMode && compareItems.length === 2 && (
        <div className="bg-bg-card rounded-xl border border-border p-4 shadow-elevated">
          <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-4 text-center">
            Comparison
          </h2>
          <div className="grid grid-cols-2 gap-4">
            {compareItems.map((item) => (
              <div key={item.id} className="text-center">
                <h3 className="text-lg font-bold text-text mb-2">
                  {item.name.display_name}
                </h3>
                <div className="space-y-1.5 text-xs">
                  <div>
                    <span className="text-text-muted block">Style</span>
                    <span className="text-text font-medium">{item.name.age_style_category}</span>
                  </div>
                  <div>
                    <span className="text-text-muted block">Length</span>
                    <span className="text-text font-medium">{item.name.length_category}</span>
                  </div>
                  <div>
                    <span className="text-text-muted block">Origins</span>
                    <span className="text-text font-medium">
                      {item.name.origin_backgrounds.join(', ')}
                    </span>
                  </div>
                  <div>
                    <span className="text-text-muted block">Fit</span>
                    <span className="text-primary font-bold">
                      {Math.round(item.match_strength_score * 100)}%
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
