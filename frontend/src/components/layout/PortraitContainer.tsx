import type { ReactNode } from 'react';

interface PortraitContainerProps {
  children: ReactNode;
}

/**
 * Portrait container — Instagram-style desktop layout.
 * Takes 50% of the screen on large displays, full-width on smaller screens.
 * Centered with blank sidebars and subtle border framing.
 */
export default function PortraitContainer({ children }: PortraitContainerProps) {
  return (
    <div className="portrait-container">
      {children}
    </div>
  );
}
