import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useMatches } from './useMatches';
import api from '../services/api';

vi.mock('../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

const mockedApi = vi.mocked(api);

const soundsLikeResponse = {
  data: {
    data: [
      {
        name_id: 'name-2',
        canonical_name: 'Liam',
        origin_backgrounds: ['Irish', 'English'],
        length_category: 'short',
        age_style_category: 'modern',
        audio_url: 'https://audio.example/liam.mp3',
      },
      {
        name_id: 'name-3',
        canonical_name: 'William',
        origin_backgrounds: ['English'],
        length_category: 'medium',
        age_style_category: 'classic',
        audio_url: null,
      },
    ],
  },
};

describe('useMatches.getSoundsLikeNames', () => {
  beforeEach(() => {
    mockedApi.get.mockReset();
    // useMatches calls loadMatches (GET /matches/) on mount; handle it here.
    mockedApi.get.mockImplementation(async (url: string) => {
      if (url === '/matches/') {
        return { data: { data: [] } };
      }
      if (url === '/matches/name-1/sounds-like/') {
        return soundsLikeResponse;
      }
      throw new Error(`Unexpected URL ${url}`);
    });
  });

  it('calls the sounds-like endpoint and returns the mapped results including audio_url', async () => {
    const { result } = renderHook(() => useMatches());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    const names = await result.current.getSoundsLikeNames('name-1');

    expect(mockedApi.get).toHaveBeenCalledWith('/matches/name-1/sounds-like/');
    expect(names).toEqual([
      {
        id: 'name-2',
        display_name: 'Liam',
        canonical_name: 'Liam',
        origin_backgrounds: ['Irish', 'English'],
        length_category: 'short',
        age_style_category: 'modern',
        audio_url: 'https://audio.example/liam.mp3',
      },
      {
        id: 'name-3',
        display_name: 'William',
        canonical_name: 'William',
        origin_backgrounds: ['English'],
        length_category: 'medium',
        age_style_category: 'classic',
        audio_url: null,
      },
    ]);
  });

  it('returns an empty array when the endpoint rejects', async () => {
    mockedApi.get.mockImplementation(async (url: string) => {
      if (url === '/matches/') {
        return { data: { data: [] } };
      }
      throw new Error('network error');
    });

    const { result } = renderHook(() => useMatches());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    const names = await result.current.getSoundsLikeNames('name-1');
    expect(names).toEqual([]);
  });
});
