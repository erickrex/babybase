import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useMatches } from '../../hooks/useMatches';
import type { MatchDetail, SimilarName } from '../../hooks/useMatches';

/**
 * Match detail page: name meaning, origin, semantic fit breakdown, "More Like This".
 */
export default function MatchDetailPage() {
  const { nameId } = useParams<{ nameId: string }>();
  const navigate = useNavigate();
  const { getMatchDetail, getSimilarNames, addToShortlist, removeFromShortlist } = useMatches();

  const [detail, setDetail] = useState<MatchDetail | null>(null);
  const [similarNames, setSimilarNames] = useState<SimilarName[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingSimilar, setIsLoadingSimilar] = useState(false);
  const [showSimilar, setShowSimilar] = useState(false);
  const [isShortlisted, setIsShortlisted] = useState(false);
  const [isUpdatingShortlist, setIsUpdatingShortlist] = useState(false);

  useEffect(() => {
    if (!nameId) return;

    let isCancelled = false;

    const loadDetail = async () => {
      setIsLoading(true);
      const data = await getMatchDetail(nameId);
      if (!isCancelled) {
        setDetail(data);
        setIsShortlisted(data?.status === 'shortlisted');
        setIsLoading(false);
      }
    };

    void loadDetail();

    return () => {
      isCancelled = true;
    };
  }, [nameId, getMatchDetail]);

  const handleToggleShortlist = async () => {
    if (!nameId || isUpdatingShortlist) return;
    setIsUpdatingShortlist(true);
    const ok = isShortlisted
      ? await removeFromShortlist(nameId)
      : await addToShortlist(nameId);
    if (ok) {
      setIsShortlisted((prev) => !prev);
    }
    setIsUpdatingShortlist(false);
  };

  const handleMoreLikeThis = async () => {
    if (!nameId) return;
    setShowSimilar(true);
    setIsLoadingSimilar(true);
    const names = await getSimilarNames(nameId);
    setSimilarNames(names);
    setIsLoadingSimilar(false);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-10 h-10 border-3 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] px-4 text-center">
        <p className="text-text-secondary">Match not found</p>
        <button
          onClick={() => navigate('/matches')}
          className="mt-4 text-primary font-medium"
        >
          ← Back to Matches
        </button>
      </div>
    );
  }

  const { name, semantic_breakdown } = detail;

  return (
    <div className="px-4 pt-6 pb-8">
      {/* Back button */}
      <button
        onClick={() => navigate('/matches')}
        className="text-sm text-text-muted mb-4 hover:text-text-secondary"
      >
        ← Back
      </button>

      {/* Name header */}
      <div className="text-center mb-6">
        <h1 className="text-3xl font-bold text-text mb-2">{name.display_name}</h1>
        <div className="flex flex-wrap justify-center gap-2">
          {name.origin_backgrounds.map((origin) => (
            <span
              key={origin}
              className="px-3 py-1 rounded-full bg-primary-muted text-primary-dark text-sm font-medium"
            >
              {origin}
            </span>
          ))}
        </div>
      </div>

      {/* Shortlist toggle */}
      <button
        onClick={handleToggleShortlist}
        disabled={isUpdatingShortlist}
        className={`w-full py-3 rounded-xl font-semibold mb-4 transition-colors disabled:opacity-60 ${
          isShortlisted
            ? 'bg-primary-muted text-primary-dark border border-primary'
            : 'bg-primary text-white hover:bg-primary-dark'
        }`}
      >
        {isShortlisted ? '★ Shortlisted — tap to remove' : '☆ Add to Shortlist'}
      </button>

      {/* Name meaning & origin */}
      <div className="bg-bg-card rounded-xl border border-border p-4 shadow-card mb-4">
        <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-2">
          Meaning & Origin
        </h2>
        <p className="text-text text-sm leading-relaxed">
          {name.semantic_summary}
        </p>
      </div>

      {/* Historical notes */}
      <div className="bg-bg-card rounded-xl border border-border p-4 shadow-card mb-4">
        <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-2">
          Details
        </h2>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-text-muted">Style</span>
            <span className="text-text font-medium">{name.age_style_category}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-text-muted">Length</span>
            <span className="text-text font-medium">{name.length_category}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-text-muted">Historical significance</span>
            <span className="text-text font-medium">
              {name.historical_significance_score > 0.7
                ? 'High'
                : name.historical_significance_score > 0.3
                  ? 'Moderate'
                  : 'Low'}
            </span>
          </div>
          {name.languages.length > 0 && (
            <div className="flex justify-between">
              <span className="text-text-muted">Languages</span>
              <span className="text-text font-medium">{name.languages.join(', ')}</span>
            </div>
          )}
        </div>
      </div>

      {/* Semantic fit breakdown */}
      <div className="bg-bg-card rounded-xl border border-border p-4 shadow-card mb-6">
        <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-3">
          Why This Matches
        </h2>
        <div className="space-y-3">
          <FitBar label="Style fit" value={semantic_breakdown.style_pct} />
          <FitBar label="Heritage fit" value={semantic_breakdown.heritage_pct} />
          <FitBar label="Local fit" value={semantic_breakdown.local_pct} />
          <FitBar label="Historical fit" value={semantic_breakdown.historical_pct} />
        </div>
      </div>

      {/* More Like This */}
      {!showSimilar ? (
        <button
          onClick={handleMoreLikeThis}
          className="w-full py-3 rounded-xl bg-primary text-white font-semibold hover:bg-primary-dark transition-colors"
        >
          More Like This
        </button>
      ) : (
        <div>
          <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-3">
            Similar Names
          </h2>
          {isLoadingSimilar ? (
            <p className="text-text-muted text-sm">Loading similar names...</p>
          ) : similarNames.length === 0 ? (
            <p className="text-text-muted text-sm">No similar names available yet.</p>
          ) : (
            <div className="space-y-2">
              {similarNames.map((n) => (
                <div
                  key={n.id}
                  className="bg-bg-card rounded-lg border border-border p-3 flex items-center justify-between"
                >
                  <span className="font-medium text-text">{n.display_name}</span>
                  <div className="flex gap-1">
                    {n.origin_backgrounds.slice(0, 2).map((o) => (
                      <span
                        key={o}
                        className="px-2 py-0.5 rounded-full bg-bg-muted text-text-secondary text-xs"
                      >
                        {o}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Progress bar for semantic fit breakdown */
function FitBar({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-text-secondary">{label}</span>
        <span className="text-text font-medium">{value}%</span>
      </div>
      <div className="h-2 bg-bg-muted rounded-full overflow-hidden">
        <div
          className="h-full bg-primary rounded-full transition-all duration-500"
          style={{ width: `${value}%` }}
        />
      </div>
    </div>
  );
}
