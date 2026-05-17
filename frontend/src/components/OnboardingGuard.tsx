import { Navigate } from 'react-router-dom';
import { useCouple } from '../contexts/CoupleContext';
import type { ReactNode } from 'react';

/**
 * Guards protected routes by checking onboarding status via CoupleContext.
 * Redirects to the appropriate onboarding step if the user hasn't completed setup.
 */
export default function OnboardingGuard({ children }: { children: ReactNode }) {
  const { coupleState, isLoading } = useCouple();
  const coupleStatus = coupleState.couple?.status;

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bg">
        <div className="w-10 h-10 border-3 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // Solo user (no couple at all) who completed onboarding can access the app
  if (!coupleState.hasCouple) {
    if (coupleState.onboardingComplete.user) {
      return <>{children}</>;
    }
    return <Navigate to="/onboarding/preferences" replace />;
  }

  // Has a couple but it's not active yet (pending invite)
  if (coupleStatus !== 'active') {
    return <Navigate to="/onboarding/partner" replace />;
  }

  // Active couple — user must have completed onboarding
  if (!coupleState.onboardingComplete.user) {
    return <Navigate to="/onboarding/preferences" replace />;
  }

  // Solo couple (no partner paired yet) — user can swipe alone
  if (!coupleState.partner) {
    return <>{children}</>;
  }

  // Has a partner — partner must also have onboarded
  if (!coupleState.onboardingComplete.partner) {
    return <Navigate to="/onboarding/partner" replace />;
  }

  return <>{children}</>;
}
