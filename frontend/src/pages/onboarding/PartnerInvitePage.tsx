import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';
import { useCouple } from '../../contexts/CoupleContext';

export default function PartnerInvitePage() {
  const navigate = useNavigate();
  const { coupleState, isLoading: isCoupleLoading, syncAfterMutation } = useCouple();
  const [partnerEmail, setPartnerEmail] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const isPendingInvite = coupleState.couple?.status === 'pending';
  const isWaitingForPartner =
    coupleState.couple?.status === 'active' &&
    coupleState.partner !== null &&
    coupleState.onboardingComplete.user &&
    !coupleState.onboardingComplete.partner;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!partnerEmail.trim()) {
      setError('Please enter your partner\'s email.');
      return;
    }

    setIsLoading(true);
    try {
      const { coupleState: nextState } = await syncAfterMutation(() =>
        api.post('/couples/invite/', {
          partner_email: partnerEmail.trim(),
        })
      );
      // Already-onboarded users (e.g. inviting from Profile) go to the deck;
      // users still in initial onboarding continue to preferences.
      navigate(nextState.onboardingComplete.user ? '/deck' : '/onboarding/preferences');
    } catch (err: unknown) {
      const error = err as { response?: { data?: { message?: string } } };
      const message = error.response?.data?.message || 'Failed to send invite. Please try again.';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSkip = () => {
    // If user already completed onboarding, go straight to deck
    if (coupleState.onboardingComplete.user) {
      navigate('/deck');
    } else {
      navigate('/onboarding/preferences');
    }
  };

  if (isCoupleLoading) {
    return (
      <div className="portrait-container min-h-screen flex flex-col items-center justify-center px-6">
        <div className="w-10 h-10 border-3 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (isPendingInvite || isWaitingForPartner) {
    const waitingTitle = isPendingInvite ? 'Invite Sent' : 'Waiting for Your Partner';
    const waitingBody = isPendingInvite
      ? 'Your invite is pending. You can finish your preferences while your partner signs up.'
      : 'You are all set. Once your partner finishes onboarding, the swipe deck will unlock.';

    return (
      <div className="portrait-container min-h-screen flex flex-col items-center justify-center px-6">
        <div className="w-full max-w-md text-center">
          <span className="text-5xl mb-4 block">{isPendingInvite ? '📨' : '⏳'}</span>
          <h1 className="text-3xl font-bold text-text mb-2">{waitingTitle}</h1>
          <p className="text-base text-text-secondary mb-8">{waitingBody}</p>

          {isPendingInvite && !coupleState.onboardingComplete.user && (
            <button
              type="button"
              onClick={() => navigate('/onboarding/preferences')}
              className="w-full rounded-xl bg-primary px-6 py-4 text-base font-semibold text-white shadow-card hover:bg-primary-dark transition-colors"
            >
              Continue to Preferences
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="portrait-container min-h-screen flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <span className="text-5xl mb-4 block">💑</span>
          <h1 className="text-3xl font-bold text-text mb-2">
            Invite Your Partner
          </h1>
          <p className="text-base text-text-secondary">
            BabyBase works best as a couple. Invite your partner to swipe together.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label htmlFor="partnerEmail" className="block text-sm font-medium text-text mb-1.5">
              Partner&apos;s Email
            </label>
            <input
              id="partnerEmail"
              type="email"
              value={partnerEmail}
              onChange={(e) => setPartnerEmail(e.target.value)}
              className="block w-full rounded-xl border border-border bg-bg-card px-4 py-3 text-base text-text shadow-sm placeholder:text-text-muted focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              placeholder="partner@example.com"
            />
          </div>

          {error && (
            <div className="rounded-xl bg-error/10 border border-error/20 p-4 text-sm text-error">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={isLoading}
            className="w-full rounded-xl bg-primary px-6 py-4 text-base font-semibold text-white shadow-card hover:bg-primary-dark disabled:opacity-50 transition-colors"
          >
            {isLoading ? 'Sending...' : 'Send Invite'}
          </button>

          <button
            type="button"
            onClick={handleSkip}
            className="w-full rounded-xl border border-border bg-bg-card px-6 py-3.5 text-base font-medium text-text-secondary hover:bg-bg-muted transition-colors"
          >
            Skip for Now
          </button>
        </form>
      </div>
    </div>
  );
}
