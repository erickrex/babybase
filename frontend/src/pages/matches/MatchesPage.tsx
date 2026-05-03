import { useNavigate } from 'react-router-dom';
import { useMatches } from '../../hooks/useMatches';

/**
 * List of mutual matches with name + origin chips + semantic fit badge.
 */
export default function MatchesPage() {
  const { matches, isLoading, error, loadMatches } = useMatches();
  const navigate = useNavigate();

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh]">
        <div className="w-10 h-10 border-3 border-primary border-t-transparent rounded-full animate-spin mb-4" />
        <p className="text-text-secondary text-sm">Loading matches...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] px-4 text-center">
        <span className="text-4xl mb-4">😔</span>
        <p className="text-text-secondary mb-4">{error}</p>
        <button
          onClick={loadMatches}
          className="px-6 py-2.5 rounded-xl bg-primary text-white font-medium hover:bg-primary-dark transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  if (matches.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] px-4 text-center">
        <span className="text-5xl mb-4">💛</span>
        <h2 className="text-xl font-bold text-text mb-2">No matches yet</h2>
        <p className="text-text-secondary text-sm">
          Keep swiping! When you and your partner both love a name, it&apos;ll appear here.
        </p>
      </div>
    );
  }

  return (
    <div className="px-4 pt-6 pb-4">
      <h1 className="text-xl font-bold text-text mb-4">Your Matches</h1>
      <p className="text-sm text-text-muted mb-6">
        Names you both love 💛
      </p>

      <div className="space-y-3">
        {matches.map((match) => (
          <button
            key={match.id}
            onClick={() => navigate(`/matches/${match.name.id}`)}
            className="w-full bg-bg-card rounded-xl border border-border p-4 shadow-card hover:shadow-elevated transition-shadow text-left"
          >
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-lg font-semibold text-text">
                {match.name.display_name}
              </h3>
              {/* Semantic fit badge */}
              <span className="px-2 py-0.5 rounded-full bg-primary-muted text-primary-dark text-xs font-medium">
                {Math.round(match.match_strength_score * 100)}% fit
              </span>
            </div>

            {/* Origin chips */}
            <div className="flex flex-wrap gap-1.5">
              {match.name.origin_backgrounds.map((origin) => (
                <span
                  key={origin}
                  className="px-2 py-0.5 rounded-full bg-bg-muted text-text-secondary text-xs"
                >
                  {origin}
                </span>
              ))}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
