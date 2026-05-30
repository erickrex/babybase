import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import PreferencesPage from './PreferencesPage';
import api from '../../services/api';

const navigateMock = vi.fn();
const syncAfterMutationMock = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock('../../contexts/CoupleContext', () => ({
  useCouple: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  default: {
    post: vi.fn(),
  },
}));

import { useCouple } from '../../contexts/CoupleContext';

const mockedUseCouple = vi.mocked(useCouple);
const mockedApi = vi.mocked(api);

function completeQuestionnaire() {
  fireEvent.click(screen.getByText('Boy'));
  fireEvent.click(screen.getByText('Next'));
  fireEvent.click(screen.getByText('Modern'));
  fireEvent.click(screen.getByText('Next'));
  fireEvent.click(screen.getByText('Short'));
  fireEvent.click(screen.getByText('Next'));
  fireEvent.click(screen.getByText('Not important'));
  fireEvent.click(screen.getByText('Next'));
  fireEvent.click(screen.getByText('Spanish'));
  fireEvent.click(screen.getByText('Next'));
  fireEvent.change(screen.getByPlaceholderText('e.g. DE'), { target: { value: 'DE' } });
}

describe('PreferencesPage', () => {
  beforeEach(() => {
    navigateMock.mockReset();
    syncAfterMutationMock.mockReset();
    mockedApi.post.mockReset();
    mockedUseCouple.mockReturnValue({
      coupleState: {
        hasCouple: true,
        couple: { id: '1', status: 'active', residence_country: null, created_at: '' },
        partner: { id: '2', email: 'partner@test.com', first_name: 'Partner', role_in_pregnancy: 'other' },
        onboardingComplete: { user: false, partner: false },
      },
      isLoading: false,
      isInitialized: true,
      refresh: vi.fn(),
      syncAfterMutation: syncAfterMutationMock,
    });
  });

  it('routes back to the partner page when the partner still has onboarding left', async () => {
    mockedApi.post.mockResolvedValue({ data: { status: 'success' } });
    syncAfterMutationMock.mockImplementation(async (operation: () => Promise<unknown>) => {
      const result = await operation();
      return {
        result,
        coupleState: {
          hasCouple: true,
          couple: { id: '1', status: 'active', residence_country: 'DE', created_at: '' },
          partner: { id: '2', email: 'partner@test.com', first_name: 'Partner', role_in_pregnancy: 'other' },
          onboardingComplete: { user: true, partner: false },
        },
      };
    });

    render(
      <MemoryRouter>
        <PreferencesPage />
      </MemoryRouter>
    );

    completeQuestionnaire();
    fireEvent.click(screen.getByText('Finish'));

    await waitFor(() => {
      expect(mockedApi.post).toHaveBeenCalledWith('/onboarding/preferences/', {
        baby_gender_preference: 'boy',
        preferred_name_age: 'new',
        preferred_name_length: 'short',
        historical_importance: 'low',
        preferred_name_backgrounds: ['Spanish'],
        residence_country: 'DE',
      });
      expect(navigateMock).toHaveBeenCalledWith('/onboarding/partner');
    });
  });

  it('enters the app immediately when both partners are onboarded after save', async () => {
    mockedApi.post.mockResolvedValue({ data: { status: 'success' } });
    syncAfterMutationMock.mockImplementation(async (operation: () => Promise<unknown>) => {
      const result = await operation();
      return {
        result,
        coupleState: {
          hasCouple: true,
          couple: { id: '1', status: 'active', residence_country: 'DE', created_at: '' },
          partner: { id: '2', email: 'partner@test.com', first_name: 'Partner', role_in_pregnancy: 'other' },
          onboardingComplete: { user: true, partner: true },
        },
      };
    });

    render(
      <MemoryRouter>
        <PreferencesPage />
      </MemoryRouter>
    );

    completeQuestionnaire();
    fireEvent.click(screen.getByText('Finish'));

    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith('/deck');
    });
  });

  it('redirects an already-onboarded user to the deck without showing the questionnaire', async () => {
    mockedUseCouple.mockReturnValue({
      coupleState: {
        hasCouple: true,
        couple: { id: '1', status: 'active', residence_country: 'DE', created_at: '' },
        partner: { id: '2', email: 'partner@test.com', first_name: 'Partner', role_in_pregnancy: 'other' },
        onboardingComplete: { user: true, partner: true },
      },
      isLoading: false,
      isInitialized: true,
      refresh: vi.fn(),
      syncAfterMutation: syncAfterMutationMock,
    });

    render(
      <MemoryRouter>
        <PreferencesPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith('/deck', { replace: true });
    });
    // The questionnaire submit must never fire for an already-onboarded user
    expect(mockedApi.post).not.toHaveBeenCalled();
  });
});
