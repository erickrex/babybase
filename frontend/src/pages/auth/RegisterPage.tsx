import { useState, type FormEvent } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import type { AxiosError } from 'axios';

interface ApiErrorResponse {
  status: string;
  message: string;
  errors?: Record<string, string[]>;
}

export default function RegisterPage() {
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { register } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setFieldErrors({});

    if (!firstName.trim()) {
      setError('Please enter your first name');
      return;
    }

    if (password !== passwordConfirm) {
      setError('Passwords do not match');
      return;
    }

    setIsSubmitting(true);

    try {
      await register(email, password, passwordConfirm, firstName.trim(), lastName.trim());
      navigate('/deck');
    } catch (err) {
      const axiosError = err as AxiosError<ApiErrorResponse>;
      const data = axiosError.response?.data;
      if (data?.errors) {
        setFieldErrors(data.errors);
      } else if (data?.message) {
        setError(data.message);
      } else {
        setError('Registration failed. Please try again.');
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
          <span className="text-5xl mb-4 block">👶</span>
          <h1 className="text-3xl font-bold text-text">Create Account</h1>
          <p className="mt-2 text-base text-text-secondary">
            Find baby names you both love
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          {error && (
            <div className="rounded-xl bg-error/10 border border-error/20 p-4 text-sm text-error">
              {error}
            </div>
          )}

          <div>
            <label htmlFor="firstName" className="block text-sm font-medium text-text mb-1.5">
              First Name
            </label>
            <input
              id="firstName"
              type="text"
              required
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              className="block w-full rounded-xl border border-border bg-bg-card px-4 py-3 text-base text-text shadow-sm placeholder:text-text-muted focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              placeholder="Alex"
            />
            {fieldErrors.first_name && (
              <p className="mt-1.5 text-xs text-error">{fieldErrors.first_name[0]}</p>
            )}
          </div>

          <div>
            <label htmlFor="lastName" className="block text-sm font-medium text-text mb-1.5">
              Last Name
            </label>
            <input
              id="lastName"
              type="text"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              className="block w-full rounded-xl border border-border bg-bg-card px-4 py-3 text-base text-text shadow-sm placeholder:text-text-muted focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              placeholder="Rivera"
            />
            {fieldErrors.last_name && (
              <p className="mt-1.5 text-xs text-error">{fieldErrors.last_name[0]}</p>
            )}
          </div>

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
            {fieldErrors.email && (
              <p className="mt-1.5 text-xs text-error">{fieldErrors.email[0]}</p>
            )}
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
            {fieldErrors.password && (
              <p className="mt-1.5 text-xs text-error">{fieldErrors.password[0]}</p>
            )}
          </div>

          <div>
            <label htmlFor="passwordConfirm" className="block text-sm font-medium text-text mb-1.5">
              Confirm Password
            </label>
            <input
              id="passwordConfirm"
              type="password"
              required
              value={passwordConfirm}
              onChange={(e) => setPasswordConfirm(e.target.value)}
              className="block w-full rounded-xl border border-border bg-bg-card px-4 py-3 text-base text-text shadow-sm placeholder:text-text-muted focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              placeholder="••••••••"
            />
            {fieldErrors.password_confirm && (
              <p className="mt-1.5 text-xs text-error">{fieldErrors.password_confirm[0]}</p>
            )}
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-xl bg-primary px-6 py-4 text-base font-semibold text-white shadow-card hover:bg-primary-dark focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isSubmitting ? 'Creating account...' : 'Create Account'}
          </button>
        </form>

        <p className="text-center text-sm text-text-secondary">
          Already have an account?{' '}
          <Link to="/login" className="font-semibold text-primary hover:text-primary-dark">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
