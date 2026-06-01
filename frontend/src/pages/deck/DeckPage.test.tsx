import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import DeckPage from './DeckPage';
import api from '../../services/api';

// Mock the heavy swipe children so the test stays focused on the mode toggle + badge.
vi.mock('../../components/swipe/SwipeDeck', () => ({
  default: () => <div data-testid="swipe-deck" />,
}));

vi.mock('../../components/swipe/MatchCelebration', () => ({
  default: () => <div data-testid="match-celebration" />,
}));

vi.mock('../../services/api', () => ({
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

describe('DeckPage focused deck modes', () => {
  beforeEach(() => {
    mockedApi.post.mockReset();
    mockedApi.post.mockImplementation(async (url: string) => {
      if (url === '/recommendations/deck/') {
        return deckResponse;
      }

      throw new Error(`Unexpected URL ${url}`);
    });
  });

  it('keeps secondary deck modes out of the primary demo selector', async () => {
    render(<DeckPage />);

    await screen.findByRole('button', { name: /Best Match/ });

    expect(mockedApi.post).toHaveBeenCalledWith('/recommendations/deck/', {
      mode: 'best_match',
      force_refresh: false,
    });
    expect(screen.queryByRole('button', { name: /Travels/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Bridge Names/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Wildcards/ })).not.toBeInTheDocument();
  });

  it('calls the deck API with mode "sounds_like" and renders its badge', async () => {
    render(<DeckPage />);

    const soundsLikeButton = await screen.findByRole('button', { name: /Sounds Like/ });
    fireEvent.click(soundsLikeButton);

    await waitFor(() => {
      expect(mockedApi.post).toHaveBeenCalledWith(
        '/recommendations/deck/',
        expect.objectContaining({ mode: 'sounds_like' })
      );
    });
    expect(
      await screen.findByText(/Names that sound like the ones you both liked/)
    ).toBeInTheDocument();
  });
});
