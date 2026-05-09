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

  if (!coupleState.hasCouple) {
    return <Navigate to="/onboarding/partner" replace />;
  }

  if (coupleStatus === 'pending') {
    return <Navigate to="/onboarding/partner" replace />;
  }

  if (coupleStatus !== 'active') {
    return <Navigate to="/onboarding/partner" replace />;
  }

  if (!coupleState.onboardingComplete.user) {
    return <Navigate to="/onboarding/preferences" replace />;
  }

  if (!coupleState.onboardingComplete.partner) {
    return <Navigate to="/onboarding/partner" replace />;
  }

  return <>{children}</>;
}
