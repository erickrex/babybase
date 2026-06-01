import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ShortlistPage from './ShortlistPage';
import api from '../../services/api';

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'user-1' },
  }),
}));

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(),
    delete: vi.fn(),
  },
}));

const mockedApi = vi.mocked(api);

const shortlistResponse = {
  data: {
    data: [
      {
        id: 'match-1',
        name: {
          id: 'name-1',
          display_name: 'Sofia',
          canonical_name: 'Sofia',
          origin_backgrounds: ['Spanish'],
          length_category: 'short',
          age_style_category: 'classic',
          historical_significance_score: 0.8,
        },
        match_strength_score: 0.92,
        removal_pending: false,
        removal_requested_by: null,
      },
    ],
  },
};

describe('ShortlistPage error handling', () => {
  beforeEach(() => {
    mockedApi.get.mockReset();
    mockedApi.delete.mockReset();
    mockedApi.get.mockResolvedValue(shortlistResponse);
    mockedApi.delete.mockResolvedValue({
      data: {
        data: {
          status: 'removed',
          removal_pending: false,
          removal_requested_by: null,
        },
      },
    });
  });

  it('shows a retryable load error instead of an empty shortlist when loading fails', async () => {
    mockedApi.get.mockRejectedValueOnce({ request: {} });

    render(<ShortlistPage />);

    expect(await screen.findByText('Network error. Check your connection and try again.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try Again' })).toBeInTheDocument();
  });

  it('keeps the item visible and surfaces API messages when a shortlist update fails', async () => {
    mockedApi.delete.mockRejectedValueOnce({
      response: {
        status: 400,
        data: { message: 'Only matched names can be removed from the shortlist.' },
      },
    });

    render(<ShortlistPage />);

    expect(await screen.findByText('Sofia')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Request removal of Sofia' }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Only matched names can be removed from the shortlist.');
    });
    expect(screen.getByText('Sofia')).toBeInTheDocument();
  });
});
