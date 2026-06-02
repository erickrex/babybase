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
  deckId: string | null;
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

interface ApiError {
  response?: {
    status?: number;
    data?: {
      message?: string;
    };
  };
  request?: unknown;
  code?: string;
}

function getApiMessage(error: unknown, fallback: string): string {
  const apiError = error as ApiError;
  return apiError.response?.data?.message || fallback;
}

function getDeckErrorMessage(error: unknown): string {
  const apiError = error as ApiError;
  const status = apiError.response?.status;

  // Axios sets code ECONNABORTED when the request exceeds its timeout.
  if (apiError.code === 'ECONNABORTED') {
    return 'Building your deck is taking longer than usual. Please try again.';
  }
  if (status === 503) {
    return 'The recommendation service is busy right now. Please try again in a moment.';
  }
  if (status === 401) {
    return 'Your session expired. Please sign in again.';
  }
  if (apiError.request && !apiError.response) {
    return 'Network error. Check your connection and try again.';
  }
  return getApiMessage(error, 'Failed to load deck. Please try again.');
}

function getSwipeErrorMessage(error: unknown): string {
  const apiError = error as ApiError;
  const status = apiError.response?.status;

  if (status === 400) {
    return getApiMessage(error, 'That swipe could not be saved. Refresh your deck and try again.');
  }
  if (status === 401) {
    return 'Your session expired. Please sign in again.';
  }
  if (status === 429) {
    return 'You are swiping too quickly. Wait a moment and try again.';
  }
  if (apiError.request && !apiError.response) {
    return 'Network error. Check your connection and try again.';
  }
  return getApiMessage(error, 'Failed to save swipe. Please try again.');
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
    deckId: null,
    cards: [],
    currentIndex: 0,
    isLoading: true,
    isExhausted: false,
    error: null,
    tasteDrift: null,
  });

  // Load deck on mount
  const loadDeck = useCallback(async (forceRefresh: boolean = false) => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }));
    try {
      const res = await api.post('/recommendations/deck/', { mode, force_refresh: forceRefresh });
      const items: NameCardData[] = res.data.data.items.map(mapDeckItem);
      const tasteDrift = res.data.data.taste_drift as TasteDrift | undefined;
      setState({
        deckId: res.data.data.id,
        cards: items,
        currentIndex: 0,
        isLoading: false,
        isExhausted: items.length === 0,
        error: null,
        tasteDrift: tasteDrift || null,
      });
    } catch (err: unknown) {
      const message = getDeckErrorMessage(err);
      setState((prev) => ({
        ...prev,
        deckId: null,
        isLoading: false,
        isExhausted: true,
        error: message,
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
      let previousIndex = 0;
      // Optimistic: advance card immediately
      setState((prev) => {
        previousIndex = prev.currentIndex;
        const nextIndex = prev.currentIndex + 1;
        return {
          ...prev,
          currentIndex: nextIndex,
          isExhausted: nextIndex >= prev.cards.length,
          error: null,
        };
      });

      try {
        const res = await api.post('/swipes/', { name_id: nameId, action, deck_id: state.deckId });
        if (res.data.data.is_match) {
          return { isMatch: true, matchData: res.data.data.match };
        }
        return { isMatch: false };
      } catch (err) {
        const message = getSwipeErrorMessage(err);
        setState((prev) => ({
          ...prev,
          currentIndex: Math.min(previousIndex, Math.max(prev.cards.length - 1, 0)),
          isExhausted: false,
          error: message,
        }));
        return { isMatch: false };
      }
    },
    [state.deckId]
  );

  // Refresh deck (when exhausted)
  const refreshDeck = useCallback(() => {
    void loadDeck(true);
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
