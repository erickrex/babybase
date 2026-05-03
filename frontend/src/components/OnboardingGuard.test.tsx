import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import OnboardingGuard from './OnboardingGuard';

// Mock the CoupleContext module
vi.mock('../contexts/CoupleContext', () => ({
  useCouple: vi.fn(),
}));

import { useCouple } from '../contexts/CoupleContext';

const mockedUseCouple = vi.mocked(useCouple);

function renderWithRouter(initialRoute: string) {
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <Routes>
        <Route
          path="/deck"
          element={
            <OnboardingGuard>
              <div data-testid="deck-content">Deck Page</div>
            </OnboardingGuard>
          }
        />
        <Route
          path="/matches"
          element={
            <OnboardingGuard>
              <div data-testid="matches-content">Matches Page</div>
            </OnboardingGuard>
          }
        />
        <Route
          path="/shortlist"
          element={
            <OnboardingGuard>
              <div data-testid="shortlist-content">Shortlist Page</div>
            </OnboardingGuard>
          }
        />
        <Route
          path="/map"
          element={
            <OnboardingGuard>
              <div data-testid="map-content">Map Page</div>
            </OnboardingGuard>
          }
        />
        <Route path="/onboarding/partner" element={<div data-testid="partner-page">Partner Page</div>} />
        <Route path="/onboarding/preferences" element={<div data-testid="preferences-page">Preferences Page</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('OnboardingGuard', () => {
  it('shows loading spinner when couple data is loading', () => {
    mockedUseCouple.mockReturnValue({
      coupleState: {
        hasCouple: false,
        couple: null,
        partner: null,
        onboardingComplete: { user: false, partner: false },
      },
      isLoading: true,
      refresh: vi.fn(),
    });

    const { container } = renderWithRouter('/deck');
    // Should show spinner, not content or redirect targets
    expect(screen.queryByTestId('deck-content')).not.toBeInTheDocument();
    expect(screen.queryByTestId('partner-page')).not.toBeInTheDocument();
    expect(container.querySelector('.animate-spin')).toBeInTheDocument();
  });

  it('redirects to /onboarding/partner when user has no couple', () => {
    mockedUseCouple.mockReturnValue({
      coupleState: {
        hasCouple: false,
        couple: null,
        partner: null,
        onboardingComplete: { user: false, partner: false },
      },
      isLoading: false,
      refresh: vi.fn(),
    });

    renderWithRouter('/deck');
    expect(screen.getByTestId('partner-page')).toBeInTheDocument();
    expect(screen.queryByTestId('deck-content')).not.toBeInTheDocument();
  });

  it('redirects to /onboarding/preferences when user has couple but incomplete preferences', () => {
    mockedUseCouple.mockReturnValue({
      coupleState: {
        hasCouple: true,
        couple: { id: '1', status: 'active', residence_country: null, created_at: '' },
        partner: { id: '2', email: 'partner@test.com', first_name: 'Partner', role_in_pregnancy: 'other' },
        onboardingComplete: { user: false, partner: false },
      },
      isLoading: false,
      refresh: vi.fn(),
    });

    renderWithRouter('/deck');
    expect(screen.getByTestId('preferences-page')).toBeInTheDocument();
    expect(screen.queryByTestId('deck-content')).not.toBeInTheDocument();
  });

  it('renders children when onboarding is complete', () => {
    mockedUseCouple.mockReturnValue({
      coupleState: {
        hasCouple: true,
        couple: { id: '1', status: 'active', residence_country: 'US', created_at: '' },
        partner: { id: '2', email: 'partner@test.com', first_name: 'Partner', role_in_pregnancy: 'other' },
        onboardingComplete: { user: true, partner: true },
      },
      isLoading: false,
      refresh: vi.fn(),
    });

    renderWithRouter('/deck');
    expect(screen.getByTestId('deck-content')).toBeInTheDocument();
    expect(screen.queryByTestId('partner-page')).not.toBeInTheDocument();
    expect(screen.queryByTestId('preferences-page')).not.toBeInTheDocument();
  });

  it('redirects /matches to /onboarding/partner when no couple', () => {
    mockedUseCouple.mockReturnValue({
      coupleState: {
        hasCouple: false,
        couple: null,
        partner: null,
        onboardingComplete: { user: false, partner: false },
      },
      isLoading: false,
      refresh: vi.fn(),
    });

    renderWithRouter('/matches');
    expect(screen.getByTestId('partner-page')).toBeInTheDocument();
    expect(screen.queryByTestId('matches-content')).not.toBeInTheDocument();
  });

  it('redirects /shortlist to /onboarding/preferences when couple exists but no prefs', () => {
    mockedUseCouple.mockReturnValue({
      coupleState: {
        hasCouple: true,
        couple: { id: '1', status: 'active', residence_country: null, created_at: '' },
        partner: { id: '2', email: 'partner@test.com', first_name: 'Partner', role_in_pregnancy: 'other' },
        onboardingComplete: { user: false, partner: true },
      },
      isLoading: false,
      refresh: vi.fn(),
    });

    renderWithRouter('/shortlist');
    expect(screen.getByTestId('preferences-page')).toBeInTheDocument();
    expect(screen.queryByTestId('shortlist-content')).not.toBeInTheDocument();
  });

  it('redirects /map to /onboarding/partner when no couple', () => {
    mockedUseCouple.mockReturnValue({
      coupleState: {
        hasCouple: false,
        couple: null,
        partner: null,
        onboardingComplete: { user: false, partner: false },
      },
      isLoading: false,
      refresh: vi.fn(),
    });

    renderWithRouter('/map');
    expect(screen.getByTestId('partner-page')).toBeInTheDocument();
    expect(screen.queryByTestId('map-content')).not.toBeInTheDocument();
  });
});
