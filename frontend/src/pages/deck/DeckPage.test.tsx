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

describe('DeckPage cross-cultural mode', () => {
  beforeEach(() => {
    mockedApi.post.mockReset();
    mockedApi.post.mockImplementation(async (url: string) => {
      if (url === '/recommendations/deck/') {
        return deckResponse;
      }

      throw new Error(`Unexpected URL ${url}`);
    });
  });

  it('calls the deck API with mode "cross_cultural" when the Travels option is selected', async () => {
    render(<DeckPage />);

    // Wait for the initial best_match deck to load and the mode toggle to render.
    const travelsButton = await screen.findByRole('button', { name: /Travels/ });

    // Initial load uses the default best_match mode.
    expect(mockedApi.post).toHaveBeenCalledWith('/recommendations/deck/', {
      mode: 'best_match',
      force_refresh: false,
    });

    fireEvent.click(travelsButton);

    // Selecting cross-cultural re-runs useDeck with the new mode.
    await waitFor(() => {
      expect(mockedApi.post).toHaveBeenCalledWith(
        '/recommendations/deck/',
        expect.objectContaining({ mode: 'cross_cultural' })
      );
    });
  });

  it('renders the cross-cultural badge when the Travels option is selected', async () => {
    render(<DeckPage />);

    const travelsButton = await screen.findByRole('button', { name: /Travels/ });

    // Badge is not shown for the default best_match mode.
    expect(
      screen.queryByText(/Names that travel across languages and cultures/)
    ).not.toBeInTheDocument();

    fireEvent.click(travelsButton);

    expect(
      await screen.findByText(/Names that travel across languages and cultures/)
    ).toBeInTheDocument();
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
