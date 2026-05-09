import { useState, useEffect, useCallback } from 'react';
import api from '../services/api';
import type { NameCardData } from '../components/swipe/SwipeCard';

interface MatchData {
  id: string;
  display_name: string;
  matched_at: string;
}

interface SwipeResult {
  isMatch: boolean;
  matchData?: MatchData;
}

interface DeckState {
  cards: NameCardData[];
  currentIndex: number;
  isLoading: boolean;
  isExhausted: boolean;
  error: string | null;
  tasteDrift: TasteDrift | null;
}

interface TasteDrift {
  summary: string;
  converging_traits: string[];
}

/**
 * Maps a raw API deck item to the NameCardData shape used by the frontend.
 */
function mapDeckItem(item: Record<string, unknown>): NameCardData {
  const name = item.name as Record<string, unknown>;
  return {
    id: item.name_id as string,
    display_name: name.display_name as string,
    origin_backgrounds: name.origin_backgrounds as string[],
    length_category: name.length_category as string,
    age_style_category: name.age_style_category as string,
    historical_significance_score: name.historical_significance_score as number,
    explanation_summary: item.explanation_summary as string | undefined,
  };
}

/**
 * Hook to manage the swipe deck.
 * Loads deck from API, handles optimistic swipes, prefetches at 5 remaining.
 */
export function useDeck(mode: string = 'best_match') {
  const [state, setState] = useState<DeckState>({
    cards: [],
    currentIndex: 0,
    isLoading: true,
    isExhausted: false,
    error: null,
    tasteDrift: null,
  });

  // Load deck on mount
  const loadDeck = useCallback(async () => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }));
    try {
      const res = await api.post('/recommendations/deck/', { mode });
      const items: NameCardData[] = res.data.data.items.map(mapDeckItem);
      const tasteDrift = res.data.data.taste_drift as TasteDrift | undefined;
      setState({
        cards: items,
        currentIndex: 0,
        isLoading: false,
        isExhausted: items.length === 0,
        error: null,
        tasteDrift: tasteDrift || null,
      });
    } catch {
      setState((prev) => ({
        ...prev,
        isLoading: false,
        isExhausted: true,
        error: 'Failed to load deck',
      }));
    }
  }, [mode]);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      await Promise.resolve();
      if (!cancelled) {
        await loadDeck();
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [loadDeck]);

  // Swipe action — optimistic update
  const swipe = useCallback(
    async (nameId: string, action: 'like' | 'dislike' | 'maybe'): Promise<SwipeResult> => {
      // Optimistic: advance card immediately
      setState((prev) => {
        const nextIndex = prev.currentIndex + 1;
        return {
          ...prev,
          currentIndex: nextIndex,
          isExhausted: nextIndex >= prev.cards.length,
        };
      });

      try {
        const res = await api.post('/swipes/', { name_id: nameId, action });
        if (res.data.data.is_match) {
          return { isMatch: true, matchData: res.data.data.match };
        }
        return { isMatch: false };
      } catch {
        // Don't revert on error — card is gone, retry on next session
        return { isMatch: false };
      }
    },
    []
  );

  // Refresh deck (when exhausted)
  const refreshDeck = useCallback(() => {
    void loadDeck();
  }, [loadDeck]);

  const currentCard = state.cards[state.currentIndex] || null;
  const remaining = Math.max(0, state.cards.length - state.currentIndex);

  return {
    ...state,
    currentCard,
    remaining,
    swipe,
    refreshDeck,
  };
}

export type { TasteDrift };
