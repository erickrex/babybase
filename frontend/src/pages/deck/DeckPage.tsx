import { useState } from 'react';
import SwipeDeck from '../../components/swipe/SwipeDeck';
import MatchCelebration from '../../components/swipe/MatchCelebration';
import { useDeck } from '../../hooks/useDeck';

type DeckModeOption =
  | 'best_match'
  | 'bridge_names'
  | 'wildcard'
  | 'cross_cultural'
  | 'sounds_like';

const MODE_OPTIONS: { value: DeckModeOption; label: string; icon: string }[] = [
  { value: 'best_match', label: 'Best Match', icon: '✨' },
  { value: 'bridge_names', label: 'Bridge Names', icon: '🌉' },
  { value: 'cross_cultural', label: 'Travels', icon: '🌍' },
  { value: 'sounds_like', label: 'Sounds Like', icon: '🔊' },
  { value: 'wildcard', label: 'Wildcards', icon: '🎲' },
];

/**
 * Main deck page — integrates useDeck + SwipeDeck + MatchCelebration.
 * Includes mode toggle for Best Match / Bridge Names / Travels / Sounds Like / Wildcards.
 */
export default function DeckPage() {
  const [selectedMode, setSelectedMode] = useState<DeckModeOption>('best_match');
  const { cards, currentIndex, isLoading, isExhausted, error, tasteDrift, swipe, refreshDeck } =
    useDeck(selectedMode);
  const [matchCelebration, setMatchCelebration] = useState<string | null>(null);

  const handleSwipe = async (nameId: string, action: 'like' | 'dislike' | 'maybe') => {
    const result = await swipe(nameId, action);
    if (result.isMatch && result.matchData) {
      setMatchCelebration(result.matchData.display_name);
    }
  };

  const dismissCelebration = () => {
    setMatchCelebration(null);
  };

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] px-4">
        <div className="w-10 h-10 border-3 border-primary border-t-transparent rounded-full animate-spin mb-4" />
        <p className="text-text-secondary text-sm">Loading names...</p>
      </div>
    );
  }

  if (error && cards.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] px-4 text-center">
        <span className="text-4xl mb-4">😔</span>
        <p className="text-text-secondary mb-4">{error}</p>
        <button
          onClick={refreshDeck}
          className="px-6 py-2.5 rounded-xl bg-primary text-white font-medium hover:bg-primary-dark transition-colors"
        >
          Try Again
        </button>
      </div>
    );
  }

  if (isExhausted) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] px-4 text-center">
        <span className="text-5xl mb-4">✨</span>
        <h2 className="text-xl font-bold text-text mb-2">All caught up!</h2>
        <p className="text-text-secondary text-sm mb-6">
          You&apos;ve seen all available names. Check back later for fresh picks.
        </p>
        {tasteDrift?.summary && (
          <div className="mb-4 px-4 py-3 rounded-xl bg-bg-muted border border-border">
            <p className="text-sm text-text-secondary">
              💡 {tasteDrift.summary}
            </p>
          </div>
        )}
        <button
          onClick={refreshDeck}
          className="px-6 py-2.5 rounded-xl bg-primary text-white font-medium hover:bg-primary-dark transition-colors"
        >
          Refresh Deck
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center pt-6 px-4">
      {/* Header */}
      <div className="w-full mb-4 text-center">
        <h1 className="text-lg font-semibold text-text">Baby Names</h1>
        <p className="text-xs text-text-muted">
          {cards.length - currentIndex} names remaining
        </p>
      </div>

      {/* Mode toggle */}
      <div className="w-full max-w-[420px] mb-4">
        <div className="grid grid-cols-2 sm:grid-cols-5 rounded-xl bg-bg-muted border border-border p-1 gap-1">
          {MODE_OPTIONS.map((option) => (
            <button
              key={option.value}
              onClick={() => setSelectedMode(option.value)}
              className={`min-h-10 px-2 py-2 rounded-lg text-xs font-medium transition-colors ${
                selectedMode === option.value
                  ? 'bg-primary text-white shadow-sm'
                  : 'text-text-secondary hover:text-text'
              }`}
            >
              <span className="block sm:inline sm:mr-1" aria-hidden="true">{option.icon}</span>
              <span>{option.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Taste drift insight */}
      {tasteDrift?.summary && (
        <div className="w-full max-w-[420px] mb-3 px-3 py-2 rounded-lg bg-bg-muted border border-border">
          <p className="text-xs text-text-muted text-center">
            💡 {tasteDrift.summary}
          </p>
        </div>
      )}

      {/* Mode-specific badge info */}
      {selectedMode === 'bridge_names' && (
        <div className="w-full max-w-[420px] mb-3 px-3 py-2 rounded-lg bg-primary-muted border border-primary/20">
          <p className="text-xs text-primary-dark text-center">
            🌉 Names that bridge both your backgrounds
          </p>
        </div>
      )}
      {selectedMode === 'cross_cultural' && (
        <div className="w-full max-w-[420px] mb-3 px-3 py-2 rounded-lg bg-primary-muted border border-primary/20">
          <p className="text-xs text-primary-dark text-center">
            🌍 Names that travel across languages and cultures
          </p>
        </div>
      )}
      {selectedMode === 'sounds_like' && (
        <div className="w-full max-w-[420px] mb-3 px-3 py-2 rounded-lg bg-primary-muted border border-primary/20">
          <p className="text-xs text-primary-dark text-center">
            🔊 Names that sound like the ones you both liked
          </p>
        </div>
      )}
      {selectedMode === 'wildcard' && (
        <div className="w-full max-w-[420px] mb-3 px-3 py-2 rounded-lg bg-coral-light border border-coral/20">
          <p className="text-xs text-coral-dark text-center">
            🎲 Surprising picks outside your usual taste
          </p>
        </div>
      )}

      {error && cards.length > 0 && (
        <div role="alert" className="w-full max-w-[420px] mb-3 px-3 py-2 rounded-lg bg-error/10 border border-error/20">
          <p className="text-xs text-error text-center">{error}</p>
        </div>
      )}

      {/* Swipe deck */}
      <div className="w-full max-w-[420px]">
        <SwipeDeck
          cards={cards}
          currentIndex={currentIndex}
          onSwipe={handleSwipe}
        />
      </div>

      {/* Match celebration overlay */}
      {matchCelebration && (
        <MatchCelebration
          matchName={matchCelebration}
          onDismiss={dismissCelebration}
        />
      )}
    </div>
  );
}
