import { useEffect, useState } from 'react';
import api from '../../services/api';
import { colors } from '../../theme/tokens';

type NameStatus =
  | 'shortlisted'
  | 'matched'
  | 'liked_by_you'
  | 'liked_by_partner'
  | 'recommended'
  | 'starter';

interface FeaturedName {
  id: string;
  canonical_name: string;
  display_name: string;
  origin_backgrounds: string[];
  gender_usage: string[];
  length_category: string;
  age_style_category: string;
  historical_significance_score: number;
  x: number | null;
  y: number | null;
  status: NameStatus;
  reasons: string[];
  score: number;
  rank: number | null;
}

interface TasteNeighborhood {
  id: string;
  label: string;
  description: string;
  count: number;
  matched_count: number;
  shortlisted_count: number;
  traits: {
    origins: string[];
    styles: string[];
    genders: string[];
  };
  representative_names: FeaturedName[];
}

interface ExploreBubble {
  id: string;
  label: string;
  count: number;
  centroid_x: number;
  centroid_y: number;
  matched_count: number;
  shortlisted_count: number;
}

interface ParentSummary {
  label: string;
  liked_count: number;
  top_origins: string[];
  top_styles: string[];
  centroid: {
    centroid_x: number;
    centroid_y: number;
    liked_count: number;
  } | null;
}

interface MapSummary {
  title: string;
  body: string;
  stats: {
    matched_count: number;
    shortlisted_count: number;
    featured_count: number;
    current_user_likes: number;
    partner_likes: number;
  };
}

interface ConstellationData {
  mode: 'couple' | 'solo' | 'solo_couple';
  summary: MapSummary;
  taste_neighborhoods: TasteNeighborhood[];
  featured_names: FeaturedName[];
  parents: {
    current_user: ParentSummary;
    partner: ParentSummary | null;
  };
  explore: {
    bubbles: ExploreBubble[];
  };
}

interface ApiError {
  response?: {
    data?: {
      message?: unknown;
    };
  };
}

const WIDTH = 450;
const HEIGHT = 300;
const PADDING = 28;

const BUBBLE_COLORS = [
  colors.primary,
  colors.coral,
  colors.success,
  colors.info,
  colors.primaryDark,
  colors.coralDark,
];

const STATUS_LABELS: Record<NameStatus, string> = {
  shortlisted: 'Shortlisted',
  matched: 'Match',
  liked_by_you: 'Your like',
  liked_by_partner: 'Partner like',
  recommended: 'Recommended',
  starter: 'Starter',
};

function getErrorMessage(err: unknown): string {
  const apiError = err as ApiError;
  const message = apiError.response?.data?.message;
  return typeof message === 'string' ? message : 'Failed to load name map';
}

function toSvgX(x: number): number {
  return PADDING + x * (WIDTH - 2 * PADDING);
}

function toSvgY(y: number): number {
  return PADDING + y * (HEIGHT - 2 * PADDING);
}

function colorForIndex(index: number): string {
  return BUBBLE_COLORS[index % BUBBLE_COLORS.length];
}

function displayLabel(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function bubbleSummary(bubble: ExploreBubble): string {
  const signals = [];
  if (bubble.shortlisted_count > 0) {
    signals.push(`${bubble.shortlisted_count} shortlisted`);
  }
  if (bubble.matched_count > 0) {
    signals.push(`${bubble.matched_count} matched`);
  }
  signals.push(`${bubble.count} names`);
  return signals.join(' · ');
}

function nameMeta(name: FeaturedName): string {
  const origins = name.origin_backgrounds.slice(0, 2).join(', ') || 'Global';
  const gender = name.gender_usage.join('/') || 'any';
  return `${origins} · ${displayLabel(name.age_style_category)} · ${gender}`;
}

export default function ConstellationPage() {
  const [data, setData] = useState<ConstellationData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<'insights' | 'explore'>('insights');

  useEffect(() => {
    void fetchConstellation();
  }, []);

  async function fetchConstellation() {
    try {
      setIsLoading(true);
      setError(null);
      const res = await api.get('/constellation/');
      setData(res.data.data);
    } catch (err: unknown) {
      setError(getErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  }

  const stats = data?.summary.stats;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-4rem)]">
        <div className="w-8 h-8 border-3 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="px-4 pt-6">
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-center">
          <p className="text-red-600 text-sm">{error}</p>
          <button
            onClick={fetchConstellation}
            className="mt-3 px-3 py-1.5 rounded-lg text-sm bg-primary text-white font-medium"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!data || data.featured_names.length === 0) {
    return (
      <div className="px-4 pt-6 text-center">
        <h1 className="text-xl font-bold text-text mb-2">Name Map</h1>
        <p className="text-text-muted text-sm">
          Like a few names to build your map.
        </p>
      </div>
    );
  }

  return (
    <div className="px-4 pt-5 pb-6">
      <div className="mb-4">
        <h1 className="text-xl font-bold text-text">Name Map</h1>
        <p className="text-sm text-text-secondary mt-1">
          {data.summary.title}
        </p>
      </div>

      <div className="flex rounded-lg bg-bg-muted border border-border p-1 mb-4">
        <button
          type="button"
          aria-pressed={view === 'insights'}
          onClick={() => setView('insights')}
          className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
            view === 'insights'
              ? 'bg-bg-card text-text shadow-sm'
              : 'text-text-secondary'
          }`}
        >
          Insights
        </button>
        <button
          type="button"
          aria-pressed={view === 'explore'}
          onClick={() => setView('explore')}
          className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
            view === 'explore'
              ? 'bg-bg-card text-text shadow-sm'
              : 'text-text-secondary'
          }`}
        >
          Explore
        </button>
      </div>

      {view === 'insights' ? (
        <InsightsView data={data} stats={stats} />
      ) : (
        <ExploreView data={data} />
      )}
    </div>
  );
}

function InsightsView({
  data,
  stats,
}: {
  data: ConstellationData;
  stats: MapSummary['stats'] | undefined;
}) {
  const statItems = [
    { label: 'Matches', value: stats?.matched_count ?? 0 },
    { label: 'Shortlist', value: stats?.shortlisted_count ?? 0 },
    { label: 'Your likes', value: stats?.current_user_likes ?? 0 },
    ...(data.parents.partner
      ? [{ label: 'Partner likes', value: stats?.partner_likes ?? 0 }]
      : []),
  ];

  return (
    <>
      <section className="rounded-xl border border-primary/25 bg-primary-muted px-4 py-4 mb-5">
        <p className="text-sm text-text-secondary leading-relaxed">
          {data.summary.body}
        </p>
        <div className="grid grid-cols-2 gap-2 mt-4">
          {statItems.map((item) => (
            <div key={item.label} className="rounded-lg bg-bg-card/70 px-3 py-2">
              <p className="text-lg font-bold text-text">{item.value}</p>
              <p className="text-xs text-text-muted">{item.label}</p>
            </div>
          ))}
        </div>
      </section>

      <ParentSignals parents={data.parents} mode={data.mode} />

      <section className="mb-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold text-text">Taste Neighborhoods</h2>
          <span className="text-xs text-text-muted">{data.taste_neighborhoods.length}</span>
        </div>
        <div className="space-y-3">
          {data.taste_neighborhoods.map((neighborhood, index) => (
            <NeighborhoodCard
              key={neighborhood.id}
              neighborhood={neighborhood}
              color={colorForIndex(index)}
            />
          ))}
        </div>
      </section>

      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold text-text">Names To Try Next</h2>
          <span className="text-xs text-text-muted">{data.featured_names.length}</span>
        </div>
        <div className="space-y-2">
          {data.featured_names.slice(0, 10).map((name) => (
            <FeaturedNameRow key={name.id} name={name} />
          ))}
        </div>
      </section>
    </>
  );
}

function ParentSignals({
  parents,
  mode,
}: {
  parents: ConstellationData['parents'];
  mode: ConstellationData['mode'];
}) {
  const summaries = [parents.current_user, parents.partner].filter(
    (summary): summary is ParentSummary => summary !== null
  );

  return (
    <section className="mb-5">
      <h2 className="text-base font-semibold text-text mb-3">
        {mode === 'couple' ? 'Parent Signals' : 'Your Signals'}
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {summaries.map((summary) => (
          <div
            key={summary.label}
            className="rounded-xl border border-border bg-bg-card px-4 py-3"
          >
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-text text-sm">{summary.label}</h3>
              <span className="text-xs text-text-muted">
                {summary.liked_count} likes
              </span>
            </div>
            <TraitList
              values={[...summary.top_origins, ...summary.top_styles.map(displayLabel)]}
              emptyLabel="No strong signal yet"
            />
          </div>
        ))}
      </div>
    </section>
  );
}

function NeighborhoodCard({
  neighborhood,
  color,
}: {
  neighborhood: TasteNeighborhood;
  color: string;
}) {
  return (
    <article className="rounded-xl border border-border bg-bg-card p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <span
          className="mt-1 h-3 w-3 rounded-full shrink-0"
          style={{ backgroundColor: color }}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <h3 className="font-semibold text-text">{neighborhood.label}</h3>
            <span className="shrink-0 rounded-full bg-bg-muted px-2 py-0.5 text-xs text-text-secondary">
              {neighborhood.count}
            </span>
          </div>
          <p className="mt-1 text-sm text-text-secondary leading-snug">
            {neighborhood.description}
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {neighborhood.representative_names.slice(0, 4).map((name) => (
              <span
                key={name.id}
                className="rounded-full bg-primary-muted px-2 py-1 text-xs text-primary-dark"
              >
                {name.display_name}
              </span>
            ))}
          </div>
        </div>
      </div>
    </article>
  );
}

function FeaturedNameRow({ name }: { name: FeaturedName }) {
  return (
    <article className="rounded-xl border border-border bg-bg-card px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-semibold text-text truncate">{name.display_name}</h3>
          <p className="text-xs text-text-muted mt-0.5">{nameMeta(name)}</p>
        </div>
        <span className="shrink-0 rounded-full bg-bg-muted px-2 py-1 text-xs text-text-secondary">
          {STATUS_LABELS[name.status]}
        </span>
      </div>
      {name.reasons.length > 0 && (
        <p className="mt-2 text-sm text-text-secondary leading-snug">
          {name.reasons[0]}
        </p>
      )}
    </article>
  );
}

function TraitList({
  values,
  emptyLabel,
}: {
  values: string[];
  emptyLabel: string;
}) {
  const visible = values.filter(Boolean).slice(0, 4);
  if (visible.length === 0) {
    return <p className="mt-2 text-xs text-text-muted">{emptyLabel}</p>;
  }

  return (
    <div className="mt-3 flex flex-wrap gap-1.5">
      {visible.map((value) => (
        <span
          key={value}
          className="rounded-full bg-bg-muted px-2 py-1 text-xs text-text-secondary"
        >
          {value}
        </span>
      ))}
    </div>
  );
}

function ExploreView({
  data,
}: {
  data: ConstellationData;
}) {
  const maxBubbleCount = Math.max(
    1,
    ...data.explore.bubbles.map((bubble) => bubble.count)
  );

  return (
    <section>
      <div className="mb-4">
        <h2 className="text-base font-semibold text-text">Neighborhood Map</h2>
        <p className="mt-1 text-sm text-text-secondary">
          A simpler view of where your strongest taste groups sit relative to each other.
        </p>
      </div>

      <div className="rounded-xl border border-border bg-bg-card overflow-hidden">
        <svg width="100%" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="block">
          <rect width={WIDTH} height={HEIGHT} fill={colors.bgCard} />
          {data.explore.bubbles.map((bubble, index) => {
            const radius = 18 + (bubble.count / maxBubbleCount) * 18;
            const fill = colorForIndex(index);
            return (
              <g key={bubble.id}>
                <circle
                  cx={toSvgX(bubble.centroid_x)}
                  cy={toSvgY(bubble.centroid_y)}
                  r={radius}
                  fill={fill}
                  opacity="0.22"
                  stroke={fill}
                  strokeWidth="2"
                />
                <text
                  x={toSvgX(bubble.centroid_x)}
                  y={toSvgY(bubble.centroid_y) + 4}
                  textAnchor="middle"
                  fontSize="12"
                  fontWeight="700"
                  fill={colors.text}
                >
                  {bubble.count}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="mt-4 space-y-2">
        {data.explore.bubbles.map((bubble, index) => (
          <div
            key={bubble.id}
            className="flex items-center justify-between rounded-xl border border-border bg-bg-card px-3 py-2"
          >
            <div className="flex items-center gap-2 min-w-0">
              <span
                className="h-2.5 w-2.5 rounded-full shrink-0"
                style={{ backgroundColor: colorForIndex(index) }}
              />
              <span className="text-sm font-medium text-text truncate">
                {bubble.label}
              </span>
            </div>
            <span className="text-xs text-text-muted shrink-0">
              {bubbleSummary(bubble)}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
