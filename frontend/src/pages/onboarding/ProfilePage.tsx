import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';

export default function ProfilePage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [firstName, setFirstName] = useState(user?.first_name || '');
  const [role, setRole] = useState(user?.role_in_pregnancy || '');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!firstName.trim()) {
      setError('Please enter your name.');
      return;
    }
    if (!role) {
      setError('Please select your role.');
      return;
    }

    setIsLoading(true);
    try {
      await api.patch('/profile/me/', {
        first_name: firstName.trim(),
        role_in_pregnancy: role,
      });
      navigate('/onboarding/partner');
    } catch {
      setError('Failed to save profile. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="portrait-container min-h-screen flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <span className="text-5xl mb-4 block">👋</span>
          <h1 className="text-3xl font-bold text-text mb-2">
            About You
          </h1>
          <p className="text-base text-text-secondary">
            Let&apos;s get to know you a little better.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label htmlFor="firstName" className="block text-sm font-medium text-text mb-1.5">
              First Name
            </label>
            <input
              id="firstName"
              type="text"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              className="block w-full rounded-xl border border-border bg-bg-card px-4 py-3 text-base text-text shadow-sm placeholder:text-text-muted focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              placeholder="Your first name"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-text mb-1.5">
              Your Role
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setRole('mother')}
                className={`rounded-xl border px-4 py-4 text-base font-medium transition-colors ${
                  role === 'mother'
                    ? 'border-primary bg-primary-muted text-primary-dark'
                    : 'border-border bg-bg-card text-text hover:bg-bg-muted'
                }`}
              >
                Mother
              </button>
              <button
                type="button"
                onClick={() => setRole('father')}
                className={`rounded-xl border px-4 py-4 text-base font-medium transition-colors ${
                  role === 'father'
                    ? 'border-primary bg-primary-muted text-primary-dark'
                    : 'border-border bg-bg-card text-text hover:bg-bg-muted'
                }`}
              >
                Father
              </button>
            </div>
          </div>

          {error && (
            <div className="rounded-xl bg-error/10 border border-error/20 p-3 text-sm text-error">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={isLoading}
            className="w-full rounded-xl bg-primary px-6 py-4 text-base font-semibold text-white shadow-card hover:bg-primary-dark disabled:opacity-50 transition-colors"
          >
            {isLoading ? 'Saving...' : 'Continue'}
          </button>
        </form>
      </div>
    </div>
  );
}
