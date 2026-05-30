/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from 'react';
import api from '../services/api';
import { useAuth } from './AuthContext';

interface Partner {
  id: string;
  email: string;
  first_name: string;
  role_in_pregnancy: string;
}

interface CoupleInfo {
  id: string;
  status: string;
  residence_country: string | null;
  created_at: string;
}

interface OnboardingComplete {
  user: boolean;
  partner: boolean;
}

interface CoupleState {
  hasCouple: boolean;
  couple: CoupleInfo | null;
  partner: Partner | null;
  onboardingComplete: OnboardingComplete;
}

interface CoupleContextType {
  coupleState: CoupleState;
  isLoading: boolean;
  isInitialized: boolean;
  refresh: () => Promise<CoupleState>;
  syncAfterMutation: <T>(operation: () => Promise<T>) => Promise<{ result: T; coupleState: CoupleState }>;
}

const defaultState: CoupleState = {
  hasCouple: false,
  couple: null,
  partner: null,
  onboardingComplete: { user: false, partner: false },
};

const CoupleContext = createContext<CoupleContextType | undefined>(undefined);

export function CoupleProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  const [coupleState, setCoupleState] = useState<CoupleState>(defaultState);
  const [isLoading, setIsLoading] = useState(isAuthenticated);
  // True once couple state has been fetched at least once for the current
  // authenticated session. Guards must not route on the default empty state
  // before the first fetch resolves.
  const [isInitialized, setIsInitialized] = useState(false);

  const refresh = useCallback(async () => {
    // Read the token directly rather than relying on the `isAuthenticated`
    // closure, which can be stale immediately after login (before re-render).
    const hasToken = Boolean(localStorage.getItem('token'));
    if (!hasToken) {
      setCoupleState(defaultState);
      setIsInitialized(true);
      return defaultState;
    }

    setIsLoading(true);
    try {
      const response = await api.get('/couples/me/');
      const data = response.data.data;
      const nextState = {
        hasCouple: data.has_couple,
        couple: data.couple,
        partner: data.partner,
        onboardingComplete: data.onboarding_complete,
      };
      setCoupleState(nextState);
      return nextState;
    } catch {
      setCoupleState(defaultState);
      return defaultState;
    } finally {
      setIsLoading(false);
      setIsInitialized(true);
    }
  }, []);

  const syncAfterMutation = useCallback(
    async <T,>(operation: () => Promise<T>) => {
      const result = await operation();
      const nextCoupleState = await refresh();
      return { result, coupleState: nextCoupleState };
    },
    [refresh]
  );

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      await Promise.resolve();
      if (!cancelled) {
        await refresh();
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [refresh, isAuthenticated]);

  return (
    <CoupleContext.Provider value={{ coupleState, isLoading, isInitialized, refresh, syncAfterMutation }}>
      {children}
    </CoupleContext.Provider>
  );
}

export function useCouple(): CoupleContextType {
  const context = useContext(CoupleContext);
  if (context === undefined) {
    throw new Error('useCouple must be used within a CoupleProvider');
  }
  return context;
}
