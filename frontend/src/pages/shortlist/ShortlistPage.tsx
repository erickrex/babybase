import { useState, useEffect, useCallback } from 'react';
import api from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';

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
  removal_pending: boolean;
  removal_requested_by: string | null;
}

/**
 * Shortlist page: ordered list of shortlisted names with reorder and compare.
 * Removing a name requires the partner's approval — one partner requests
 * removal, the other approves before the name leaves the shortlist.
 */
export default function ShortlistPage() {
  const { user } = useAuth();
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

  // Request removal (or approve the partner's request if one is already pending).
  const handleRequestOrApprove = useCallback(async (nameId: string) => {
    try {
      const res = await api.delete('/shortlist/', { data: { name_id: nameId } });
      const data = res.data.data;
      if (data.status !== 'shortlisted') {
        // Fully removed (approved, or solo couple) — drop from the list
        setItems((prev) => prev.filter((item) => item.name.id !== nameId));
      } else {
        // Still shortlisted but now pending removal — update the flag in place
        setItems((prev) =>
          prev.map((item) =>
            item.name.id === nameId
              ? { ...item, removal_pending: data.removal_pending, removal_requested_by: data.removal_requested_by }
              : item
          )
        );
      }
    } catch {
      // Silently handle
    }
  }, []);

  // Resolve a pending request without removing: "cancel" (by requester) or "reject" (by partner).
  const handleResolveRequest = useCallback(async (nameId: string, decision: 'cancel' | 'reject') => {
    try {
      const res = await api.delete('/shortlist/', { data: { name_id: nameId, decision } });
      const data = res.data.data;
      setItems((prev) =>
        prev.map((item) =>
          item.name.id === nameId
            ? { ...item, removal_pending: data.removal_pending, removal_requested_by: data.removal_requested_by }
            : item
        )
      );
    } catch {
      // Silently handle
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadShortlist();
    });
  }, [loadShortlist]);

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
      {!compareMode && (
        <p className="text-xs text-text-muted mb-4">
          Ranked by match strength
        </p>
      )}

      {/* Ordered list */}
      <div className="space-y-2 mb-6">
        {items.map((item, index) => {
          const requestedByMe = item.removal_requested_by === user?.id;
          return (
            <div
              key={item.id}
              className={`bg-bg-card rounded-xl border p-3 shadow-card transition-colors ${
                compareMode && selectedForCompare.includes(item.id)
                  ? 'border-primary bg-primary-muted'
                  : item.removal_pending
                    ? 'border-coral/40'
                    : 'border-border'
              }`}
              onClick={compareMode ? () => toggleCompareSelection(item.id) : undefined}
            >
              <div className="flex items-center gap-3">
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
                      <span key={o} className="text-xs text-text-muted">
                        {o}
                      </span>
                    ))}
                  </div>
                </div>

                {/* Request removal (only when no request pending and not comparing) */}
                {!compareMode && !item.removal_pending && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleRequestOrApprove(item.name.id);
                    }}
                    aria-label={`Request removal of ${item.name.display_name}`}
                    className="shrink-0 w-8 h-8 rounded-full text-text-muted hover:bg-bg-muted hover:text-error transition-colors flex items-center justify-center"
                  >
                    ✕
                  </button>
                )}
              </div>

              {/* Pending removal controls */}
              {!compareMode && item.removal_pending && (
                <div className="mt-3 pt-3 border-t border-border">
                  {requestedByMe ? (
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs text-text-secondary">
                        ⏳ Removal requested. Waiting for your partner.
                      </span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleResolveRequest(item.name.id, 'cancel');
                        }}
                        className="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium bg-bg-muted text-text-secondary hover:bg-border transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs text-coral-dark">
                        Your partner wants to remove this name.
                      </span>
                      <div className="flex gap-2 shrink-0">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            void handleResolveRequest(item.name.id, 'reject');
                          }}
                          className="px-3 py-1.5 rounded-lg text-xs font-medium bg-bg-muted text-text-secondary hover:bg-border transition-colors"
                        >
                          Keep
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            void handleRequestOrApprove(item.name.id);
                          }}
                          className="px-3 py-1.5 rounded-lg text-xs font-medium bg-error text-white hover:opacity-90 transition-opacity"
                        >
                          Approve removal
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
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
