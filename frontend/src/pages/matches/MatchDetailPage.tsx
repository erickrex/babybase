import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useMatches } from '../../hooks/useMatches';
import type { MatchDetail, SimilarName, SoundsLikeName } from '../../hooks/useMatches';

/**
 * Match detail page: name meaning, origin, semantic fit breakdown, "More Like This",
 * and "Sounds Like".
 */
export default function MatchDetailPage() {
  const { nameId } = useParams<{ nameId: string }>();
  const navigate = useNavigate();
  const { getMatchDetail, getSimilarNames, getSoundsLikeNames, addToShortlist } = useMatches();

  const [detail, setDetail] = useState<MatchDetail | null>(null);
  const [similarNames, setSimilarNames] = useState<SimilarName[]>([]);
  const [soundsLikeNames, setSoundsLikeNames] = useState<SoundsLikeName[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingSimilar, setIsLoadingSimilar] = useState(false);
  const [isLoadingSoundsLike, setIsLoadingSoundsLike] = useState(false);
  const [showSimilar, setShowSimilar] = useState(false);
  const [showSoundsLike, setShowSoundsLike] = useState(false);
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
    if (!nameId || isUpdatingShortlist || isShortlisted) return;
    setIsUpdatingShortlist(true);
    const ok = await addToShortlist(nameId);
    if (ok) {
      setIsShortlisted(true);
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

  const handleSoundsLike = async () => {
    if (!nameId) return;
    setShowSoundsLike(true);
    setIsLoadingSoundsLike(true);
    const names = await getSoundsLikeNames(nameId);
    setSoundsLikeNames(names);
    setIsLoadingSoundsLike(false);
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
        <div className="flex items-center justify-center gap-2 mb-2">
          <h1 className="text-3xl font-bold text-text">{name.display_name}</h1>
          <PronunciationButton audioUrl={detail.audio_url} />
        </div>
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

      {/* Finalists toggle */}
      <button
        onClick={handleToggleShortlist}
        disabled={isUpdatingShortlist || isShortlisted}
        className={`w-full py-3 rounded-xl font-semibold mb-4 transition-colors disabled:opacity-60 ${
          isShortlisted
            ? 'bg-primary-muted text-primary-dark border border-primary cursor-default'
            : 'bg-primary text-white hover:bg-primary-dark'
        }`}
      >
        {isShortlisted ? '★ In Finalists' : '☆ Add to Finalists'}
      </button>
      {isShortlisted && (
        <p className="text-xs text-text-muted text-center -mt-2 mb-4">
          Manage this shared finalist from the Finalists tab.
        </p>
      )}

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

      {/* More Like This / Sounds Like actions */}
      <div className="flex gap-3">
        <button
          onClick={handleMoreLikeThis}
          className="flex-1 py-3 rounded-xl bg-primary text-white font-semibold hover:bg-primary-dark transition-colors"
        >
          More Like This
        </button>
        <button
          onClick={handleSoundsLike}
          className="flex-1 py-3 rounded-xl bg-bg-card text-primary-dark font-semibold border border-primary hover:bg-primary-muted transition-colors"
        >
          Sounds Like
        </button>
      </div>

      {/* Similar Names results */}
      {showSimilar && (
        <div className="mt-6">
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
                <NameResultRow key={n.id} name={n} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Sounds Like results */}
      {showSoundsLike && (
        <div className="mt-6">
          <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-3">
            Sounds Like
          </h2>
          {isLoadingSoundsLike ? (
            <p className="text-text-muted text-sm">Loading similar-sounding names...</p>
          ) : soundsLikeNames.length === 0 ? (
            <p className="text-text-muted text-sm">No similar-sounding names available yet.</p>
          ) : (
            <div className="space-y-2">
              {soundsLikeNames.map((n) => (
                <NameResultRow key={n.id} name={n} audioUrl={n.audio_url} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Shared result row for Similar Names and Sounds Like lists: name + origin pills. */
function NameResultRow({
  name,
  audioUrl = null,
}: {
  name: SimilarName;
  audioUrl?: string | null;
}) {
  return (
    <div className="bg-bg-card rounded-lg border border-border p-3 flex items-center justify-between">
      <div className="flex items-center gap-2">
        <span className="font-medium text-text">{name.display_name}</span>
        <PronunciationButton audioUrl={audioUrl} />
      </div>
      <div className="flex gap-1">
        {name.origin_backgrounds.slice(0, 2).map((o) => (
          <span
            key={o}
            className="px-2 py-0.5 rounded-full bg-bg-muted text-text-secondary text-xs"
          >
            {o}
          </span>
        ))}
      </div>
    </div>
  );
}

/**
 * Accessible 🔊 play control for a name's pronunciation audio.
 * Renders nothing when no audio is available; on playback failure it hides
 * itself so the surrounding view is never broken (Req 7.4, 7.5, 11.5).
 */
function PronunciationButton({ audioUrl }: { audioUrl: string | null }) {
  const [hasFailed, setHasFailed] = useState(false);

  if (!audioUrl || hasFailed) {
    return null;
  }

  const handlePlay = () => {
    try {
      const audio = new Audio(audioUrl);
      void audio.play().catch(() => setHasFailed(true));
    } catch {
      setHasFailed(true);
    }
  };

  return (
    <button
      type="button"
      onClick={handlePlay}
      aria-label="Play pronunciation"
      className="inline-flex items-center justify-center w-8 h-8 rounded-full text-primary-dark hover:bg-primary-muted transition-colors"
    >
      <span aria-hidden="true">🔊</span>
    </button>
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
