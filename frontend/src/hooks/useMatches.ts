import { useState, useEffect, useCallback } from 'react';
import api from '../services/api';

interface MatchName {
  id: string;
  display_name: string;
  canonical_name: string;
  origin_backgrounds: string[];
  length_category: string;
  age_style_category: string;
}

interface Match {
  id: string;
  name: MatchName;
  matched_at: string;
  match_strength_score: number;
  status: string;
}

interface MatchDetail {
  id: string;
  name: MatchName & {
    semantic_summary: string;
    historical_significance_score: number;
    languages: string[];
  };
  matched_at: string;
  match_strength_score: number;
  status: string;
  audio_url: string | null;
  semantic_breakdown: {
    style_pct: number;
    heritage_pct: number;
    local_pct: number;
    historical_pct: number;
  };
}

interface SimilarName {
  id: string;
  display_name: string;
  canonical_name: string;
  origin_backgrounds: string[];
  length_category: string;
  age_style_category: string;
}

interface SoundsLikeName extends SimilarName {
  audio_url: string | null;
}

interface MatchDetailApiResponse {
  id: string;
  name: MatchName & {
    semantic_summary: string;
    historical_significance_score: number;
    languages: string[];
  };
  matched_at: string;
  match_strength_score: number;
  status: string;
  audio_url: string | null;
  semantic_fit_breakdown: {
    style: number;
    heritage: number;
    local_fit: number;
    historical: number;
  };
}

interface SimilarNameApiResponse {
  name_id: string;
  canonical_name: string;
  origin_backgrounds: string[];
  length_category: string;
  age_style_category: string;
}

interface SoundsLikeNameApiResponse extends SimilarNameApiResponse {
  audio_url: string | null;
}

function mapMatchDetail(data: MatchDetailApiResponse): MatchDetail {
  return {
    id: data.id,
    name: data.name,
    matched_at: data.matched_at,
    match_strength_score: data.match_strength_score,
    status: data.status,
    audio_url: data.audio_url ?? null,
    semantic_breakdown: {
      style_pct: data.semantic_fit_breakdown.style,
      heritage_pct: data.semantic_fit_breakdown.heritage,
      local_pct: data.semantic_fit_breakdown.local_fit,
      historical_pct: data.semantic_fit_breakdown.historical,
    },
  };
}

function mapSimilarName(data: SimilarNameApiResponse): SimilarName {
  return {
    id: data.name_id,
    display_name: data.canonical_name,
    canonical_name: data.canonical_name,
    origin_backgrounds: data.origin_backgrounds,
    length_category: data.length_category,
    age_style_category: data.age_style_category,
  };
}

function mapSoundsLikeName(data: SoundsLikeNameApiResponse): SoundsLikeName {
  return {
    ...mapSimilarName(data),
    audio_url: data.audio_url ?? null,
  };
}

/**
 * Hook to manage matches: list, detail, and similar names.
 */
export function useMatches() {
  const [matches, setMatches] = useState<Match[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadMatches = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.get('/matches/');
      setMatches(res.data.data || []);
    } catch {
      setError('Failed to load matches');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      await Promise.resolve();
      if (!cancelled) {
        await loadMatches();
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [loadMatches]);

  const getMatchDetail = useCallback(async (nameId: string): Promise<MatchDetail | null> => {
    try {
      const res = await api.get(`/matches/${nameId}/`);
      return mapMatchDetail(res.data.data as MatchDetailApiResponse);
    } catch {
      return null;
    }
  }, []);

  const getSimilarNames = useCallback(async (nameId: string): Promise<SimilarName[]> => {
    try {
      const res = await api.get(`/matches/${nameId}/similar/`);
      const names = (res.data.data || []) as SimilarNameApiResponse[];
      return names.map(mapSimilarName);
    } catch {
      return [];
    }
  }, []);

  const getSoundsLikeNames = useCallback(async (nameId: string): Promise<SoundsLikeName[]> => {
    try {
      const res = await api.get(`/matches/${nameId}/sounds-like/`);
      const names = (res.data.data || []) as SoundsLikeNameApiResponse[];
      return names.map(mapSoundsLikeName);
    } catch {
      return [];
    }
  }, []);

  const addToShortlist = useCallback(async (nameId: string): Promise<boolean> => {
    try {
      await api.post('/shortlist/', { name_id: nameId });
      return true;
    } catch {
      return false;
    }
  }, []);

  return {
    matches,
    isLoading,
    error,
    loadMatches,
    getMatchDetail,
    getSimilarNames,
    getSoundsLikeNames,
    addToShortlist,
  };
}

export type { Match, MatchDetail, SimilarName, SoundsLikeName, MatchName };
