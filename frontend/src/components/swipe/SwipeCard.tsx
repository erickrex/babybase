interface NameCardData {
  id: string;
  display_name: string;
  origin_backgrounds: string[];
  length_category: string;
  age_style_category: string;
  historical_significance_score: number;
  explanation_summary?: string;
}

interface SwipeCardProps {
  name: NameCardData;
  style?: React.CSSProperties;
  className?: string;
}

/**
 * Name card displayed in the swipe deck.
 * Shows: large name, origin chips, style tags, optional explanation.
 */
export default function SwipeCard({ name, style, className = '' }: SwipeCardProps) {
  const historicalLabel =
    name.historical_significance_score > 0.7
      ? 'Historical'
      : name.historical_significance_score > 0.3
        ? 'Notable'
        : null;

  return (
    <div
      className={`absolute inset-0 bg-bg-card rounded-2xl shadow-elevated border border-border flex flex-col items-center justify-center p-6 select-none ${className}`}
      style={style}
    >
      {/* Name display — large, centered */}
      <h1 className="text-4xl font-bold text-text text-center mb-6">
        {name.display_name}
      </h1>

      {/* Origin/background chips */}
      <div className="flex flex-wrap justify-center gap-2 mb-4">
        {name.origin_backgrounds.map((origin) => (
          <span
            key={origin}
            className="px-3 py-1 rounded-full bg-primary-muted text-primary-dark text-sm font-medium"
          >
            {origin}
          </span>
        ))}
      </div>

      {/* Tags: length, style, historical */}
      <div className="flex flex-wrap justify-center gap-2 mb-4">
        <span className="px-2.5 py-0.5 rounded-full bg-bg-muted text-text-secondary text-xs font-medium">
          {name.length_category}
        </span>
        <span className="px-2.5 py-0.5 rounded-full bg-bg-muted text-text-secondary text-xs font-medium">
          {name.age_style_category}
        </span>
        {historicalLabel && (
          <span className="px-2.5 py-0.5 rounded-full bg-coral-light text-coral-dark text-xs font-medium">
            {historicalLabel}
          </span>
        )}
      </div>

      {/* Optional explanation text */}
      {name.explanation_summary && (
        <p className="text-sm text-text-muted text-center mt-2 px-4 leading-relaxed">
          {name.explanation_summary}
        </p>
      )}

      {/* Swipe hint at bottom */}
      <div className="absolute bottom-6 left-0 right-0 flex justify-center gap-8 text-text-muted text-xs">
        <span>← Nope</span>
        <span>↑ Maybe</span>
        <span>Love →</span>
      </div>
    </div>
  );
}

export type { NameCardData };
