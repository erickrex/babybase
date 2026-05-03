import { useEffect, useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';

interface NamePoint {
  id: string;
  canonical_name: string;
  display_name: string;
  x: number;
  y: number;
  cluster: string;
  origin_backgrounds: string[];
  gender_usage: string[];
  age_style_category: string;
}

interface Cluster {
  label: string;
  centroid_x: number;
  centroid_y: number;
  count: number;
}

interface ParentCentroid {
  centroid_x: number;
  centroid_y: number;
  radius: number;
  liked_count: number;
}

interface ConstellationData {
  names: NamePoint[];
  clusters: Cluster[];
  couple_centroids: {
    parent_a: ParentCentroid | null;
    parent_b: ParentCentroid | null;
  };
  matched_name_ids: string[];
}

// Cluster color palette
const CLUSTER_COLORS: Record<string, string> = {
  Spanish: '#f59e0b',
  Latin: '#f59e0b',
  Italian: '#fb923c',
  Portuguese: '#fbbf24',
  French: '#f97316',
  Greek: '#a78bfa',
  Russian: '#60a5fa',
  Slavic: '#38bdf8',
  Ukrainian: '#7dd3fc',
  Polish: '#93c5fd',
  Germanic: '#34d399',
  German: '#34d399',
  English: '#6ee7b7',
  Scandinavian: '#2dd4bf',
  Norse: '#5eead4',
  Celtic: '#a3e635',
  Irish: '#bef264',
  Arabic: '#fb7185',
  Persian: '#f472b6',
  Turkish: '#e879f9',
  Hebrew: '#c084fc',
  Japanese: '#fda4af',
  Chinese: '#fca5a5',
  Hawaiian: '#fdba74',
  African: '#86efac',
};

const DEFAULT_COLOR = '#a8a29e';

function getClusterColor(cluster: string): string {
  return CLUSTER_COLORS[cluster] || DEFAULT_COLOR;
}

interface TooltipState {
  visible: boolean;
  name: NamePoint | null;
  screenX: number;
  screenY: number;
}

export default function ConstellationPage() {
  const [data, setData] = useState<ConstellationData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<TooltipState>({
    visible: false,
    name: null,
    screenX: 0,
    screenY: 0,
  });

  // Transform state for zoom/pan
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const [lastPinchDist, setLastPinchDist] = useState<number | null>(null);

  const svgRef = useRef<SVGSVGElement>(null);
  const navigate = useNavigate();

  // SVG viewport dimensions
  const WIDTH = 450;
  const HEIGHT = 520;
  const PADDING = 30;

  useEffect(() => {
    fetchConstellation();
  }, []);

  async function fetchConstellation() {
    try {
      setIsLoading(true);
      const res = await api.get('/constellation/');
      setData(res.data.data);
    } catch (err: unknown) {
      const message =
        typeof err === 'object' &&
        err !== null &&
        'response' in err &&
        typeof err.response === 'object' &&
        err.response !== null &&
        'data' in err.response &&
        typeof err.response.data === 'object' &&
        err.response.data !== null &&
        'message' in err.response.data &&
        typeof err.response.data.message === 'string'
          ? err.response.data.message
          : 'Failed to load constellation';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }

  // Convert data coordinates [0,1] to SVG coordinates
  const toSvgX = useCallback(
    (x: number) => PADDING + x * (WIDTH - 2 * PADDING),
    []
  );
  const toSvgY = useCallback(
    (y: number) => PADDING + y * (HEIGHT - 2 * PADDING),
    []
  );

  // Handle dot tap/click
  function handleDotClick(name: NamePoint, event: React.MouseEvent | React.TouchEvent) {
    event.stopPropagation();
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;

    let clientX: number, clientY: number;
    if ('touches' in event) {
      clientX = event.touches[0]?.clientX || 0;
      clientY = event.touches[0]?.clientY || 0;
    } else {
      clientX = event.clientX;
      clientY = event.clientY;
    }

    setTooltip({
      visible: true,
      name,
      screenX: clientX - rect.left,
      screenY: clientY - rect.top - 50,
    });
  }

  function dismissTooltip() {
    setTooltip({ visible: false, name: null, screenX: 0, screenY: 0 });
  }

  // Zoom with wheel
  function handleWheel(e: React.WheelEvent) {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    setTransform((prev) => ({
      ...prev,
      scale: Math.max(0.5, Math.min(5, prev.scale * delta)),
    }));
  }

  // Pan with mouse
  function handleMouseDown(e: React.MouseEvent) {
    if (e.button !== 0) return;
    setIsPanning(true);
    setPanStart({ x: e.clientX - transform.x, y: e.clientY - transform.y });
  }

  function handleMouseMove(e: React.MouseEvent) {
    if (!isPanning) return;
    setTransform((prev) => ({
      ...prev,
      x: e.clientX - panStart.x,
      y: e.clientY - panStart.y,
    }));
  }

  function handleMouseUp() {
    setIsPanning(false);
  }

  // Touch pan/pinch
  function handleTouchStart(e: React.TouchEvent) {
    if (e.touches.length === 1) {
      setIsPanning(true);
      setPanStart({
        x: e.touches[0].clientX - transform.x,
        y: e.touches[0].clientY - transform.y,
      });
    } else if (e.touches.length === 2) {
      const dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      setLastPinchDist(dist);
    }
  }

  function handleTouchMove(e: React.TouchEvent) {
    if (e.touches.length === 1 && isPanning) {
      setTransform((prev) => ({
        ...prev,
        x: e.touches[0].clientX - panStart.x,
        y: e.touches[0].clientY - panStart.y,
      }));
    } else if (e.touches.length === 2 && lastPinchDist !== null) {
      const dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      const delta = dist / lastPinchDist;
      setLastPinchDist(dist);
      setTransform((prev) => ({
        ...prev,
        scale: Math.max(0.5, Math.min(5, prev.scale * delta)),
      }));
    }
  }

  function handleTouchEnd() {
    setIsPanning(false);
    setLastPinchDist(null);
  }

  // Navigate to deck with cluster filter
  function handleExploreCluster(cluster: string) {
    navigate(`/deck?mode=style_first&cluster=${encodeURIComponent(cluster)}`);
  }

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
            className="mt-2 text-sm text-primary font-medium"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!data || data.names.length === 0) {
    return (
      <div className="px-4 pt-6 text-center">
        <p className="text-text-muted text-sm">
          No constellation data available yet. Names need projections computed.
        </p>
      </div>
    );
  }

  const matchedSet = new Set(data.matched_name_ids);

  return (
    <div className="px-2 pt-4">
      <h1 className="text-lg font-bold text-text mb-2 px-2">Name Constellation</h1>
      <p className="text-xs text-text-muted mb-3 px-2">
        Names clustered by style and origin. Tap a dot to explore.
      </p>

      {/* SVG Map */}
      <div
        className="relative bg-bg-card rounded-xl border border-border overflow-hidden shadow-card"
        style={{ touchAction: 'none' }}
      >
        <svg
          ref={svgRef}
          width="100%"
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="block"
          onWheel={handleWheel}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
          onClick={dismissTooltip}
        >
          <g
            transform={`translate(${transform.x}, ${transform.y}) scale(${transform.scale})`}
          >
            {/* Parent influence regions */}
            {data.couple_centroids.parent_a && (
              <circle
                cx={toSvgX(data.couple_centroids.parent_a.centroid_x)}
                cy={toSvgY(data.couple_centroids.parent_a.centroid_y)}
                r={Math.max(20, data.couple_centroids.parent_a.radius * (WIDTH - 2 * PADDING))}
                fill="rgba(96, 165, 250, 0.08)"
                stroke="rgba(96, 165, 250, 0.3)"
                strokeWidth="1.5"
                strokeDasharray="4 2"
              />
            )}
            {data.couple_centroids.parent_b && (
              <circle
                cx={toSvgX(data.couple_centroids.parent_b.centroid_x)}
                cy={toSvgY(data.couple_centroids.parent_b.centroid_y)}
                r={Math.max(20, data.couple_centroids.parent_b.radius * (WIDTH - 2 * PADDING))}
                fill="rgba(251, 113, 133, 0.08)"
                stroke="rgba(251, 113, 133, 0.3)"
                strokeWidth="1.5"
                strokeDasharray="4 2"
              />
            )}

            {/* Overlap zone highlight */}
            {data.couple_centroids.parent_a && data.couple_centroids.parent_b && (
              <OverlapHighlight
                a={data.couple_centroids.parent_a}
                b={data.couple_centroids.parent_b}
                toSvgX={toSvgX}
                toSvgY={toSvgY}
                width={WIDTH}
                padding={PADDING}
              />
            )}

            {/* Name dots */}
            {data.names.map((name) => {
              const isMatched = matchedSet.has(name.id);
              const color = getClusterColor(name.cluster);
              const r = isMatched ? 6 : 4;

              return (
                <circle
                  key={name.id}
                  cx={toSvgX(name.x)}
                  cy={toSvgY(name.y)}
                  r={r}
                  fill={isMatched ? '#fbbf24' : color}
                  stroke={isMatched ? '#f59e0b' : 'rgba(255,255,255,0.6)'}
                  strokeWidth={isMatched ? 2 : 0.5}
                  opacity={isMatched ? 1 : 0.8}
                  className="cursor-pointer"
                  onClick={(e) => handleDotClick(name, e)}
                  onTouchStart={(e) => {
                    if (e.touches.length === 1) {
                      e.stopPropagation();
                      handleDotClick(name, e);
                    }
                  }}
                />
              );
            })}

            {/* Cluster labels */}
            {data.clusters
              .filter((c) => c.count >= 3)
              .map((cluster) => (
                <text
                  key={cluster.label}
                  x={toSvgX(cluster.centroid_x)}
                  y={toSvgY(cluster.centroid_y) - 12}
                  textAnchor="middle"
                  fontSize="9"
                  fill="#a8a29e"
                  fontWeight="500"
                  className="pointer-events-none select-none"
                >
                  {cluster.label}
                </text>
              ))}
          </g>
        </svg>

        {/* Tooltip */}
        {tooltip.visible && tooltip.name && (
          <div
            className="absolute bg-white rounded-lg shadow-elevated border border-border p-3 z-10 min-w-[160px]"
            style={{
              left: Math.min(tooltip.screenX, WIDTH - 180),
              top: Math.max(tooltip.screenY, 10),
            }}
          >
            <p className="font-semibold text-text text-sm">
              {tooltip.name.display_name}
            </p>
            <p className="text-xs text-text-muted mt-0.5">
              {tooltip.name.origin_backgrounds.join(', ')}
            </p>
            <p className="text-xs text-text-muted">
              {tooltip.name.age_style_category} · {tooltip.name.gender_usage.join('/')}
            </p>
            <button
              onClick={() => handleExploreCluster(tooltip.name!.cluster)}
              className="mt-2 text-xs text-primary font-medium"
            >
              Explore Similar →
            </button>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="mt-3 px-2">
        <div className="flex flex-wrap gap-2">
          {data.clusters
            .filter((c) => c.count >= 2)
            .sort((a, b) => b.count - a.count)
            .slice(0, 8)
            .map((cluster) => (
              <button
                key={cluster.label}
                onClick={() => handleExploreCluster(cluster.label)}
                className="flex items-center gap-1 px-2 py-1 rounded-full bg-bg-muted border border-border text-xs text-text-secondary hover:border-primary transition-colors"
              >
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: getClusterColor(cluster.label) }}
                />
                {cluster.label} ({cluster.count})
              </button>
            ))}
        </div>
      </div>

      {/* Matched names indicator */}
      {data.matched_name_ids.length > 0 && (
        <div className="mt-3 px-2 flex items-center gap-2 text-xs text-text-muted">
          <span className="w-3 h-3 rounded-full bg-matchGold border border-primary" />
          <span>{data.matched_name_ids.length} matched names highlighted</span>
        </div>
      )}
    </div>
  );
}

/** Renders a subtle highlight where parent A and B regions overlap */
function OverlapHighlight({
  a,
  b,
  toSvgX,
  toSvgY,
  width,
  padding,
}: {
  a: ParentCentroid;
  b: ParentCentroid;
  toSvgX: (x: number) => number;
  toSvgY: (y: number) => number;
  width: number;
  padding: number;
}) {
  // Midpoint between the two centroids
  const mx = (a.centroid_x + b.centroid_x) / 2;
  const my = (a.centroid_y + b.centroid_y) / 2;

  // Distance between centroids
  const dist = Math.hypot(a.centroid_x - b.centroid_x, a.centroid_y - b.centroid_y);
  const rA = a.radius;
  const rB = b.radius;

  // Only show overlap if circles actually overlap
  if (dist > rA + rB) return null;

  // Overlap radius is approximate
  const overlapR = Math.max(10, ((rA + rB - dist) / 2) * (width - 2 * padding));

  return (
    <circle
      cx={toSvgX(mx)}
      cy={toSvgY(my)}
      r={overlapR}
      fill="rgba(251, 191, 36, 0.12)"
      stroke="rgba(251, 191, 36, 0.4)"
      strokeWidth="1"
      strokeDasharray="3 2"
    />
  );
}
