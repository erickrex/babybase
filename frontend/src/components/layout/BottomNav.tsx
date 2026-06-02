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
      <div className="flex items-center justify-around h-[90px]">
        {tabs.map((tab) => (
          <button
            key={tab.path}
            onClick={() => navigate(tab.path)}
            className="flex items-center justify-center flex-1 h-full"
          >
            <span
              className={`flex flex-col items-center justify-center gap-1 px-3 py-2 rounded-2xl transition-all duration-200 ${
                isActive(tab.path)
                  ? 'text-primary bg-primary-muted shadow-card'
                  : 'text-text-muted hover:text-text-secondary hover:bg-bg-muted'
              }`}
            >
              <span className="text-2xl">{tab.icon}</span>
              <span className="text-xs font-medium">{tab.label}</span>
            </span>
          </button>
        ))}
      </div>
    </nav>
  );
}
