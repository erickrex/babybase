import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ConstellationPage from './ConstellationPage';
import api from '../../services/api';

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(),
  },
}));

const mockedApi = vi.mocked(api);

const coupleMapResponse = {
  data: {
    data: {
      mode: 'couple',
      summary: {
        title: 'Shared name taste',
        body: '1 finalist is anchoring your shared taste. The clearest neighborhood right now is Classic Spanish.',
        stats: {
          matched_count: 1,
          shortlisted_count: 1,
          featured_count: 4,
          current_user_likes: 2,
          partner_likes: 2,
        },
      },
      taste_neighborhoods: [
        {
          id: 'classic-spanish',
          label: 'Classic Spanish',
          description: 'Classic names with Spanish roots.',
          count: 2,
          matched_count: 0,
          shortlisted_count: 1,
          traits: {
            origins: ['Spanish'],
            styles: ['classic'],
            genders: ['girl'],
          },
          representative_names: [
            {
              id: 'name-1',
              canonical_name: 'MapSofia',
              display_name: 'Sofia',
              origin_backgrounds: ['Spanish'],
              gender_usage: ['girl'],
              length_category: 'short',
              age_style_category: 'classic',
              historical_significance_score: 0.8,
              x: 0.2,
              y: 0.2,
              status: 'shortlisted',
              reasons: ['Finalist together'],
              score: 0.91,
              rank: null,
            },
            {
              id: 'name-2',
              canonical_name: 'MapAlma',
              display_name: 'Alma',
              origin_backgrounds: ['Spanish'],
              gender_usage: ['girl'],
              length_category: 'short',
              age_style_category: 'classic',
              historical_significance_score: 0.7,
              x: 0.25,
              y: 0.22,
              status: 'liked_by_you',
              reasons: ['Recently liked by you'],
              score: 0,
              rank: null,
            },
          ],
        },
      ],
      featured_names: [
        {
          id: 'name-1',
          canonical_name: 'MapSofia',
          display_name: 'Sofia',
          origin_backgrounds: ['Spanish'],
          gender_usage: ['girl'],
          length_category: 'short',
          age_style_category: 'classic',
          historical_significance_score: 0.8,
          x: 0.2,
          y: 0.2,
          status: 'shortlisted',
          reasons: ['Finalist together'],
          score: 0.91,
          rank: null,
        },
        {
          id: 'name-2',
          canonical_name: 'MapAlma',
          display_name: 'Alma',
          origin_backgrounds: ['Spanish'],
          gender_usage: ['girl'],
          length_category: 'short',
          age_style_category: 'classic',
          historical_significance_score: 0.7,
          x: 0.25,
          y: 0.22,
          status: 'liked_by_you',
          reasons: ['Recently liked by you'],
          score: 0,
          rank: null,
        },
        {
          id: 'name-3',
          canonical_name: 'MapHugo',
          display_name: 'Hugo',
          origin_backgrounds: ['German'],
          gender_usage: ['boy'],
          length_category: 'short',
          age_style_category: 'modern',
          historical_significance_score: 0.5,
          x: 0.75,
          y: 0.65,
          status: 'liked_by_partner',
          reasons: ['Recently liked by your partner'],
          score: 0,
          rank: null,
        },
        {
          id: 'name-4',
          canonical_name: 'MapNova',
          display_name: 'Nova',
          origin_backgrounds: ['Italian'],
          gender_usage: ['girl'],
          length_category: 'short',
          age_style_category: 'modern',
          historical_significance_score: 0.5,
          x: 0.55,
          y: 0.45,
          status: 'recommended',
          reasons: ['Balances your current taste.'],
          score: 0.82,
          rank: 1,
        },
      ],
      parents: {
        current_user: {
          label: 'You',
          liked_count: 2,
          top_origins: ['Spanish'],
          top_styles: ['classic'],
          centroid: { centroid_x: 0.225, centroid_y: 0.21, liked_count: 2 },
        },
        partner: {
          label: 'Partner',
          liked_count: 2,
          top_origins: ['Spanish', 'German'],
          top_styles: ['classic', 'modern'],
          centroid: { centroid_x: 0.475, centroid_y: 0.425, liked_count: 2 },
        },
      },
      explore: {
        bubbles: [
          {
            id: 'classic-spanish',
            label: 'Classic Spanish',
            count: 2,
            centroid_x: 0.225,
            centroid_y: 0.21,
            matched_count: 0,
            shortlisted_count: 1,
          },
        ],
      },
    },
  },
};

const soloMapResponse = {
  data: {
    data: {
      ...coupleMapResponse.data.data,
      mode: 'solo',
      summary: {
        title: 'Your name taste',
        body: 'Your starter map is centered on Classic English.',
        stats: {
          matched_count: 0,
          shortlisted_count: 0,
          featured_count: 1,
          current_user_likes: 0,
          partner_likes: 0,
        },
      },
      parents: {
        current_user: {
          label: 'You',
          liked_count: 0,
          top_origins: ['English'],
          top_styles: ['balanced'],
          centroid: null,
        },
        partner: null,
      },
      featured_names: [
        {
          ...coupleMapResponse.data.data.featured_names[0],
          id: 'solo-name-1',
          display_name: 'Ava',
          origin_backgrounds: ['English'],
          status: 'starter',
          reasons: ['Fits your stated preferences'],
        },
      ],
    },
  },
};

describe('ConstellationPage', () => {
  beforeEach(() => {
    mockedApi.get.mockReset();
    mockedApi.get.mockResolvedValue(coupleMapResponse);
  });

  it('renders shared taste insights, neighborhoods, and featured names', async () => {
    render(<ConstellationPage />);

    expect(await screen.findByText('Name Map')).toBeInTheDocument();
    expect(screen.getByText('Shared name taste')).toBeInTheDocument();
    expect(screen.getByText(/finalist is anchoring/)).toBeInTheDocument();
    expect(screen.getByText('Classic Spanish')).toBeInTheDocument();
    expect(screen.getAllByText('Sofia').length).toBeGreaterThan(0);
    expect(screen.getByText('Partner likes')).toBeInTheDocument();
    expect(mockedApi.get).toHaveBeenCalledWith('/constellation/');
  });

  it('renders explore as neighborhood bubbles only', async () => {
    render(<ConstellationPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Explore' }));
    expect(screen.getByText('Neighborhood Map')).toBeInTheDocument();
    expect(screen.getByText(/strongest taste groups/)).toBeInTheDocument();
    expect(screen.getByText('1 finalist · 2 names')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Individual Names' })).not.toBeInTheDocument();
    expect(screen.queryByText(/projected names/)).not.toBeInTheDocument();
  });

  it('renders solo maps without partner-only stats', async () => {
    mockedApi.get.mockResolvedValue(soloMapResponse);

    render(<ConstellationPage />);

    expect(await screen.findByText('Your name taste')).toBeInTheDocument();
    expect(screen.getByText('Your Signals')).toBeInTheDocument();
    expect(screen.queryByText('Partner likes')).not.toBeInTheDocument();
    expect(screen.getByText('Ava')).toBeInTheDocument();
  });

  it('surfaces API errors with retry', async () => {
    mockedApi.get.mockRejectedValue({
      response: { data: { message: 'Complete onboarding before viewing your name map.' } },
    });

    render(<ConstellationPage />);

    expect(
      await screen.findByText('Complete onboarding before viewing your name map.')
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});
