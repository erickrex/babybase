import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useDeck } from './useDeck';
import api from '../services/api';

vi.mock('../services/api', () => ({
  default: {
    post: vi.fn(),
  },
}));

const mockedApi = vi.mocked(api);

const deckResponse = {
  data: {
    data: {
      id: 'deck-1',
      items: [
        {
          id: 'item-1',
          name_id: 'name-1',
          explanation_summary: 'Explanation 1',
          name: {
            display_name: 'Sofia',
            origin_backgrounds: ['Spanish'],
            length_category: 'short',
            age_style_category: 'classic',
            historical_significance_score: 0.8,
          },
        },
        {
          id: 'item-2',
          name_id: 'name-2',
          explanation_summary: 'Explanation 2',
          name: {
            display_name: 'Mateo',
            origin_backgrounds: ['Spanish'],
            length_category: 'short',
            age_style_category: 'modern',
            historical_significance_score: 0.4,
          },
        },
      ],
    },
  },
};

describe('useDeck', () => {
  beforeEach(() => {
    mockedApi.post.mockReset();
    mockedApi.post.mockImplementation(async (url: string) => {
      if (url === '/recommendations/deck/') {
        return deckResponse;
      }

      if (url === '/swipes/') {
        return {
          data: {
            data: {
              is_match: false,
              match: null,
            },
          },
        };
      }

      throw new Error(`Unexpected URL ${url}`);
    });
  });

  it('does not prefetch another deck when only a few cards remain', async () => {
    const { result } = renderHook(() => useDeck('best_match'));

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
      expect(result.current.cards).toHaveLength(2);
    });

    await act(async () => {
      await result.current.swipe('name-1', 'like');
      await result.current.swipe('name-2', 'dislike');
    });

    await waitFor(() => {
      expect(result.current.isExhausted).toBe(true);
    });

    const deckCalls = mockedApi.post.mock.calls.filter(([url]) => url === '/recommendations/deck/');
    expect(deckCalls).toHaveLength(1);
    expect(deckCalls[0][1]).toEqual({ mode: 'best_match', force_refresh: false });
  });

  it('requests force refresh when refreshDeck is called', async () => {
    const { result } = renderHook(() => useDeck('best_match'));

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    act(() => {
      result.current.refreshDeck();
    });

    await waitFor(() => {
      const deckCalls = mockedApi.post.mock.calls.filter(([url]) => url === '/recommendations/deck/');
      expect(deckCalls).toHaveLength(2);
    });

    const deckCalls = mockedApi.post.mock.calls.filter(([url]) => url === '/recommendations/deck/');
    expect(deckCalls[0][1]).toEqual({ mode: 'best_match', force_refresh: false });
    expect(deckCalls[1][1]).toEqual({ mode: 'best_match', force_refresh: true });
  });

  it('passes the loaded deck id with swipe requests', async () => {
    const { result } = renderHook(() => useDeck('best_match'));

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.swipe('name-1', 'like');
    });

    const swipeCall = mockedApi.post.mock.calls.find(([url]) => url === '/swipes/');
    expect(swipeCall?.[1]).toEqual({ name_id: 'name-1', action: 'like', deck_id: 'deck-1' });
  });

  it('restores the current card and surfaces a message when a swipe fails', async () => {
    mockedApi.post.mockImplementation(async (url: string) => {
      if (url === '/recommendations/deck/') {
        return deckResponse;
      }

      if (url === '/swipes/') {
        throw {
          response: {
            status: 429,
          },
        };
      }

      throw new Error(`Unexpected URL ${url}`);
    });

    const { result } = renderHook(() => useDeck('best_match'));

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.swipe('name-1', 'like');
    });

    expect(result.current.currentIndex).toBe(0);
    expect(result.current.isExhausted).toBe(false);
    expect(result.current.error).toBe('You are swiping too quickly. Wait a moment and try again.');
  });
});
