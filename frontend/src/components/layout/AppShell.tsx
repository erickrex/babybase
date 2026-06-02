import type { ReactNode } from 'react';
import PortraitContainer from './PortraitContainer';
import BottomNav from './BottomNav';

interface AppShellProps {
  children: ReactNode;
}

/**
 * App shell for authenticated screens.
 * Wraps content in PortraitContainer + BottomNav.
 * Adds bottom padding to prevent content from being hidden behind nav.
 */
export default function AppShell({ children }: AppShellProps) {
  return (
    <PortraitContainer>
      <div className="pb-24">
        {children}
      </div>
      <BottomNav />
    </PortraitContainer>
  );
}
