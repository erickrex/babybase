import { useState, type FormEvent } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { useCouple } from '../../contexts/CoupleContext';
import type { AxiosError } from 'axios';
import logoChick from '../../assets/logo-chick.gif';

interface ApiErrorResponse {
  status: string;
  message: string;
  errors?: Record<string, string[]>;
}

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { login } = useAuth();
  const { refresh } = useCouple();
  const navigate = useNavigate();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setIsSubmitting(true);

    try {
      await login(email, password);
      // Fetch couple state before routing so the OnboardingGuard decides
      // based on real data, not the default empty state. Already-onboarded
      // users go straight to the deck instead of back through onboarding.
      const nextState = await refresh();
      const needsOnboarding = !nextState.onboardingComplete.user;
      navigate(needsOnboarding ? '/onboarding/preferences' : '/deck');
    } catch (err) {
      const axiosError = err as AxiosError<ApiErrorResponse>;
      if (axiosError.response?.status === 429) {
        setError('Too many login attempts. Please wait a few minutes and try again.');
      } else {
        const data = axiosError.response?.data;
        if (data?.message) {
          setError(data.message);
        } else {
          setError('Invalid email or password.');
        }
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="portrait-container min-h-screen flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-md mx-auto space-y-8">
        {/* Branding */}
        <div className="text-center">
          <img
            src={logoChick}
            alt="BabyBase logo"
            className="mx-auto mb-4 h-20 w-20"
          />
          <h1 className="text-3xl font-bold text-text">Welcome Back</h1>
          <p className="mt-2 text-base text-text-secondary">
            Sign in to continue swiping on baby names
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          {error && (
            <div className="rounded-xl bg-error/10 border border-error/20 p-4 text-sm text-error">
              {error}
            </div>
          )}

          <div>
            <label htmlFor="email" className="block text-sm font-medium text-text mb-1.5">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="block w-full rounded-xl border border-border bg-bg-card px-4 py-3 text-base text-text shadow-sm placeholder:text-text-muted focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-text mb-1.5">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="block w-full rounded-xl border border-border bg-bg-card px-4 py-3 text-base text-text shadow-sm placeholder:text-text-muted focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              placeholder="••••••••"
            />
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-xl bg-primary px-6 py-4 text-base font-semibold text-white shadow-card hover:bg-primary-dark focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isSubmitting ? 'Signing in...' : 'Sign In'}
          </button>
        </form>

        <p className="text-center text-sm text-text-secondary">
          Don&apos;t have an account?{' '}
          <Link to="/register" className="font-semibold text-primary hover:text-primary-dark">
            Create one
          </Link>
        </p>
      </div>
    </div>
  );
}
