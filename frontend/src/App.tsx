import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { CoupleProvider, useCouple } from './contexts/CoupleContext';
import RegisterPage from './pages/auth/RegisterPage';
import LoginPage from './pages/auth/LoginPage';
import ProfilePage from './pages/onboarding/ProfilePage';
import PartnerInvitePage from './pages/onboarding/PartnerInvitePage';
import PreferencesPage from './pages/onboarding/PreferencesPage';
import DeckPage from './pages/deck/DeckPage';
import MatchesPage from './pages/matches/MatchesPage';
import MatchDetailPage from './pages/matches/MatchDetailPage';
import ShortlistPage from './pages/shortlist/ShortlistPage';
import ConstellationPage from './pages/map/ConstellationPage';
import AppShell from './components/layout/AppShell';
import OnboardingGuard from './components/OnboardingGuard';
import type { ReactNode } from 'react';

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bg">
        <div className="w-10 h-10 border-3 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}

function PublicRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bg">
        <div className="w-10 h-10 border-3 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (isAuthenticated) {
    return <Navigate to="/deck" replace />;
  }

  return <>{children}</>;
}

/** Wraps authenticated main app routes in AppShell (PortraitContainer + BottomNav) */
function AuthenticatedLayout({ children }: { children: ReactNode }) {
  return (
    <ProtectedRoute>
      <AppShell>
        <OnboardingGuard>{children}</OnboardingGuard>
      </AppShell>
    </ProtectedRoute>
  );
}

/** Profile placeholder for the Profile tab */
function ProfileTabPage() {
  const { user, logout } = useAuth();
  const { coupleState } = useCouple();
  const navigate = useNavigate();

  const hasPartner = coupleState.partner !== null;
  const hasPendingInvite =
    !hasPartner && Boolean(coupleState.couple) && coupleState.couple?.status === 'pending';

  return (
    <div className="px-4 pt-6">
      <h1 className="text-xl font-bold text-text mb-4">Profile</h1>
      <div className="bg-bg-card rounded-xl border border-border p-4 shadow-card">
        <p className="text-text font-medium">{user?.email}</p>
        <p className="text-sm text-text-muted mt-1">{user?.first_name || 'No name set'}</p>
      </div>

      {/* Partner / invite section */}
      <div className="mt-6 bg-bg-card rounded-xl border border-border p-4 shadow-card">
        <h2 className="text-sm font-semibold text-text mb-2">Your Partner</h2>
        {hasPartner ? (
          <p className="text-sm text-text-secondary">
            Paired with {coupleState.partner?.first_name || coupleState.partner?.email}.
          </p>
        ) : (
          <>
            <p className="text-sm text-text-secondary mb-3">
              {hasPendingInvite
                ? 'Your invite is pending. Your partner will be connected once they sign up.'
                : 'Invite your partner so you can swipe together and match on names.'}
            </p>
            <button
              onClick={() => navigate('/onboarding/partner')}
              className="w-full py-2.5 rounded-xl bg-primary text-white font-medium hover:bg-primary-dark transition-colors"
            >
              {hasPendingInvite ? 'Manage Invite' : 'Invite Partner'}
            </button>
          </>
        )}
      </div>

      <button
        onClick={() => {
          void logout();
        }}
        className="mt-6 w-full py-2.5 rounded-xl border border-border text-text-secondary font-medium hover:bg-bg-muted transition-colors"
      >
        Sign Out
      </button>
    </div>
  );
}

function AppRoutes() {
  return (
    <Routes>
      {/* Public routes */}
      <Route
        path="/register"
        element={
          <PublicRoute>
            <RegisterPage />
          </PublicRoute>
        }
      />
      <Route
        path="/login"
        element={
          <PublicRoute>
            <LoginPage />
          </PublicRoute>
        }
      />

      {/* Onboarding routes (protected but no bottom nav) */}
      <Route
        path="/onboarding/profile"
        element={
          <ProtectedRoute>
            <ProfilePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/onboarding/partner"
        element={
          <ProtectedRoute>
            <PartnerInvitePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/onboarding/preferences"
        element={
          <ProtectedRoute>
            <PreferencesPage />
          </ProtectedRoute>
        }
      />

      {/* Main app routes (protected + AppShell with BottomNav) */}
      <Route
        path="/deck"
        element={
          <AuthenticatedLayout>
            <DeckPage />
          </AuthenticatedLayout>
        }
      />
      <Route
        path="/matches"
        element={
          <AuthenticatedLayout>
            <MatchesPage />
          </AuthenticatedLayout>
        }
      />
      <Route
        path="/matches/:nameId"
        element={
          <AuthenticatedLayout>
            <MatchDetailPage />
          </AuthenticatedLayout>
        }
      />
      <Route
        path="/shortlist"
        element={
          <AuthenticatedLayout>
            <ShortlistPage />
          </AuthenticatedLayout>
        }
      />
      <Route
        path="/map"
        element={
          <AuthenticatedLayout>
            <ConstellationPage />
          </AuthenticatedLayout>
        }
      />
      <Route
        path="/profile"
        element={
          <AuthenticatedLayout>
            <ProfileTabPage />
          </AuthenticatedLayout>
        }
      />

      {/* Redirects */}
      <Route path="/" element={<Navigate to="/deck" replace />} />
      <Route path="*" element={<Navigate to="/deck" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <CoupleProvider>
          <AppRoutes />
        </CoupleProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
