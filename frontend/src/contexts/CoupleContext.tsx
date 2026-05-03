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
  refresh: () => Promise<void>;
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
  const [isLoading, setIsLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!isAuthenticated) {
      setCoupleState(defaultState);
      return;
    }

    setIsLoading(true);
    try {
      const response = await api.get('/couples/me/');
      const data = response.data.data;
      setCoupleState({
        hasCouple: data.has_couple,
        couple: data.couple,
        partner: data.partner,
        onboardingComplete: data.onboarding_complete,
      });
    } catch {
      setCoupleState(defaultState);
    } finally {
      setIsLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    queueMicrotask(() => {
      void refresh();
    });
  }, [refresh]);

  return (
    <CoupleContext.Provider value={{ coupleState, isLoading, refresh }}>
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
