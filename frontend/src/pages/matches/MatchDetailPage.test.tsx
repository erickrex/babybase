import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MatchDetailPage from './MatchDetailPage';
import api from '../../services/api';

const navigateMock = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useParams: () => ({ nameId: 'name-1' }),
    useNavigate: () => navigateMock,
  };
});

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

const mockedApi = vi.mocked(api);

/**
 * Build a match-detail API response with a configurable anchor `audio_url`.
 * Defaults to `null` so tests opt in to an anchor play control explicitly.
 */
function buildMatchDetailResponse(audioUrl: string | null = null) {
  return {
    data: {
      data: {
        id: 'match-1',
        name: {
          id: 'name-1',
          display_name: 'Noah',
          canonical_name: 'Noah',
          origin_backgrounds: ['Hebrew'],
          length_category: 'short',
          age_style_category: 'classic',
          semantic_summary: 'A peaceful, timeless name.',
          historical_significance_score: 0.8,
          languages: ['Hebrew', 'English'],
        },
        matched_at: '2024-01-01T00:00:00Z',
        match_strength_score: 0.9,
        status: 'matched',
        audio_url: audioUrl,
        semantic_fit_breakdown: {
          style: 80,
          heritage: 70,
          local_fit: 60,
          historical: 50,
        },
      },
    },
  };
}

// First result has audio, second is null — exercises per-row control rendering.
const soundsLikeResponse = {
  data: {
    data: [
      {
        name_id: 'name-2',
        canonical_name: 'Joah',
        origin_backgrounds: ['Hebrew'],
        length_category: 'short',
        age_style_category: 'classic',
        audio_url: 'https://audio.example/joah.mp3',
      },
      {
        name_id: 'name-3',
        canonical_name: 'Noa',
        origin_backgrounds: ['Hebrew', 'Dutch'],
        length_category: 'short',
        age_style_category: 'modern',
        audio_url: null,
      },
    ],
  },
};

/** Wire the mocked api client to serve a given match-detail response. */
function mockApiGet(detailResponse: ReturnType<typeof buildMatchDetailResponse>) {
  mockedApi.get.mockReset();
  mockedApi.get.mockImplementation(async (url: string) => {
    if (url === '/matches/name-1/') {
      return detailResponse;
    }
    if (url === '/matches/name-1/sounds-like/') {
      return soundsLikeResponse;
    }
    throw new Error(`Unexpected URL ${url}`);
  });
}

const PLAY_LABEL = 'Play pronunciation';

describe('MatchDetailPage Sounds Like', () => {
  beforeEach(() => {
    navigateMock.mockReset();
    // Default: anchor without audio so existing assertions are unaffected.
    mockApiGet(buildMatchDetailResponse(null));
  });

  it('calls the sounds-like endpoint and renders the results when "Sounds Like" is selected', async () => {
    render(<MatchDetailPage />);

    // Wait for the match detail to load on mount.
    expect(await screen.findByRole('heading', { name: 'Noah' })).toBeInTheDocument();

    const soundsLikeButton = screen.getByRole('button', { name: 'Sounds Like' });
    fireEvent.click(soundsLikeButton);

    // The endpoint is hit and the returned names render.
    await waitFor(() => {
      expect(mockedApi.get).toHaveBeenCalledWith('/matches/name-1/sounds-like/');
    });

    expect(await screen.findByText('Joah')).toBeInTheDocument();
    expect(screen.getByText('Noa')).toBeInTheDocument();
  });
});

describe('MatchDetailPage pronunciation play control', () => {
  beforeEach(() => {
    navigateMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the anchor play control when the match detail has an audio_url (Req 7.4)', async () => {
    mockApiGet(buildMatchDetailResponse('https://audio.example/noah.mp3'));

    render(<MatchDetailPage />);

    expect(await screen.findByRole('heading', { name: 'Noah' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: PLAY_LABEL })).toBeInTheDocument();
  });

  it('renders no anchor play control when the match detail audio_url is null (Req 7.5, 11.5)', async () => {
    mockApiGet(buildMatchDetailResponse(null));

    render(<MatchDetailPage />);

    expect(await screen.findByRole('heading', { name: 'Noah' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: PLAY_LABEL })).not.toBeInTheDocument();
  });

  it('renders a play control only for Sounds Like results that have audio (Req 7.5)', async () => {
    // Anchor without audio so the only controls come from the result rows.
    mockApiGet(buildMatchDetailResponse(null));

    render(<MatchDetailPage />);

    expect(await screen.findByRole('heading', { name: 'Noah' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Sounds Like' }));

    // Joah has audio, Noa does not — exactly one play control.
    expect(await screen.findByText('Joah')).toBeInTheDocument();
    expect(screen.getByText('Noa')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: PLAY_LABEL })).toHaveLength(1);
  });

  it('does not break the view when audio playback fails (Req 7.5, 11.5)', async () => {
    const playMock = vi.fn(() => Promise.reject(new Error('no play')));
    const audioMock = vi.fn(function (this: { play: () => Promise<void> }) {
      this.play = playMock;
    });
    vi.stubGlobal('Audio', audioMock);

    mockApiGet(buildMatchDetailResponse('https://audio.example/noah.mp3'));

    render(<MatchDetailPage />);

    expect(await screen.findByRole('heading', { name: 'Noah' })).toBeInTheDocument();
    const playButton = screen.getByRole('button', { name: PLAY_LABEL });

    // Clicking must not throw even though play() rejects.
    expect(() => fireEvent.click(playButton)).not.toThrow();

    // The control hides itself after the rejection, while the surrounding view stays intact.
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: PLAY_LABEL })).not.toBeInTheDocument();
    });
    expect(audioMock).toHaveBeenCalledWith('https://audio.example/noah.mp3');
    expect(playMock).toHaveBeenCalled();
    expect(screen.getByRole('heading', { name: 'Noah' })).toBeInTheDocument();
  });
});
