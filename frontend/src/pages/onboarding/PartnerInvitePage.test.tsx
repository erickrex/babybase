import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import PartnerInvitePage from './PartnerInvitePage';
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

describe('PartnerInvitePage', () => {
  beforeEach(() => {
    navigateMock.mockReset();
    syncAfterMutationMock.mockReset();
    mockedApi.post.mockReset();
  });

  it('shows waiting state for a pending invite instead of the form', () => {
    mockedUseCouple.mockReturnValue({
      coupleState: {
        hasCouple: true,
        couple: { id: '1', status: 'pending', residence_country: null, created_at: '' },
        partner: null,
        onboardingComplete: { user: false, partner: false },
      },
      isLoading: false,
      isInitialized: true,
      refresh: vi.fn(),
      syncAfterMutation: syncAfterMutationMock,
    });

    render(
      <MemoryRouter>
        <PartnerInvitePage />
      </MemoryRouter>
    );

    expect(screen.getByText('Invite Sent')).toBeInTheDocument();
    expect(screen.queryByLabelText("Partner's Email")).not.toBeInTheDocument();
  });

  it('refreshes couple state after a successful invite before navigating', async () => {
    mockedApi.post.mockResolvedValue({ data: { status: 'success' } });
    syncAfterMutationMock.mockImplementation(async (operation: () => Promise<unknown>) => {
      const result = await operation();
      return {
        result,
        coupleState: {
          hasCouple: true,
          couple: { id: '1', status: 'pending', residence_country: null, created_at: '' },
          partner: null,
          onboardingComplete: { user: false, partner: false },
        },
      };
    });
    mockedUseCouple.mockReturnValue({
      coupleState: {
        hasCouple: false,
        couple: null,
        partner: null,
        onboardingComplete: { user: false, partner: false },
      },
      isLoading: false,
      isInitialized: true,
      refresh: vi.fn(),
      syncAfterMutation: syncAfterMutationMock,
    });

    render(
      <MemoryRouter>
        <PartnerInvitePage />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByLabelText("Partner's Email"), {
      target: { value: 'partner@example.com' },
    });
    fireEvent.click(screen.getByText('Send Invite'));

    await waitFor(() => {
      expect(syncAfterMutationMock).toHaveBeenCalledTimes(1);
      expect(mockedApi.post).toHaveBeenCalledWith('/couples/invite/', {
        partner_email: 'partner@example.com',
      });
      expect(navigateMock).toHaveBeenCalledWith('/onboarding/preferences');
    });
  });
});
