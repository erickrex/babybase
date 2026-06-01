import { useLocation, useNavigate } from 'react-router-dom';

interface NavTab {
  path: string;
  label: string;
  icon: string;
}

const tabs: NavTab[] = [
  { path: '/deck', label: 'Deck', icon: '💛' },
  { path: '/matches', label: 'Matches', icon: '✨' },
  { path: '/shortlist', label: 'Finalists', icon: '⭐' },
  { path: '/map', label: 'Map', icon: '🗺️' },
  { path: '/profile', label: 'Profile', icon: '👤' },
];

/**
 * Bottom tab navigation — fixed to bottom, matches portrait container width.
 */
export default function BottomNav() {
  const location = useLocation();
  const navigate = useNavigate();

  const isActive = (path: string) => location.pathname.startsWith(path);

  return (
    <nav className="bottom-nav">
      <div className="flex items-center justify-around h-14">
        {tabs.map((tab) => (
          <button
            key={tab.path}
            onClick={() => navigate(tab.path)}
            className={`flex flex-col items-center justify-center gap-0.5 flex-1 h-full transition-colors ${
              isActive(tab.path)
                ? 'text-primary'
                : 'text-text-muted hover:text-text-secondary'
            }`}
          >
            <span className="text-lg">{tab.icon}</span>
            <span className="text-xs font-medium">{tab.label}</span>
          </button>
        ))}
      </div>
    </nav>
  );
}
