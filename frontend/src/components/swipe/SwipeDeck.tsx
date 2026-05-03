import { useState, useRef, useCallback, useEffect } from 'react';
import SwipeCard from './SwipeCard';
import type { NameCardData } from './SwipeCard';

type SwipeAction = 'like' | 'dislike' | 'maybe';

interface SwipeDeckProps {
  cards: NameCardData[];
  currentIndex: number;
  onSwipe: (nameId: string, action: SwipeAction) => void;
}

const SWIPE_THRESHOLD = 80;
const SWIPE_UP_THRESHOLD = 60;

/**
 * Card stack with gesture handling.
 * Swipe left = dislike, right = like, up = maybe.
 * Shows next card peeking behind current card.
 */
export default function SwipeDeck({ cards, currentIndex, onSwipe }: SwipeDeckProps) {
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [isAnimatingOut, setIsAnimatingOut] = useState(false);
  const startPos = useRef({ x: 0, y: 0 });
  const containerRef = useRef<HTMLDivElement>(null);

  // Refs to avoid stale closures in callbacks during rapid swipes
  const dragOffsetRef = useRef({ x: 0, y: 0 });
  const currentCardRef = useRef<NameCardData | undefined>(undefined);

  const currentCard = cards[currentIndex];
  const nextCard = cards[currentIndex + 1];

  // Keep currentCardRef in sync with derived state
  useEffect(() => {
    currentCardRef.current = currentCard;
  }, [currentCard]);

  const handleStart = useCallback((clientX: number, clientY: number) => {
    if (isAnimatingOut) return;
    startPos.current = { x: clientX, y: clientY };
    setIsDragging(true);
  }, [isAnimatingOut]);

  const handleMove = useCallback((clientX: number, clientY: number) => {
    if (!isDragging || isAnimatingOut) return;
    const dx = clientX - startPos.current.x;
    const dy = clientY - startPos.current.y;
    // Update ref inline for immediate access in handleEnd
    dragOffsetRef.current = { x: dx, y: dy };
    setDragOffset({ x: dx, y: dy });
  }, [isDragging, isAnimatingOut]);

  const triggerSwipe = useCallback((action: SwipeAction) => {
    // Read from ref to avoid stale closure values
    const card = currentCardRef.current;
    if (!card || isAnimatingOut) return;

    setIsAnimatingOut(true);

    // Animate card off screen
    const exitX = action === 'like' ? 400 : action === 'dislike' ? -400 : 0;
    const exitY = action === 'maybe' ? -400 : 0;
    dragOffsetRef.current = { x: exitX, y: exitY };
    setDragOffset({ x: exitX, y: exitY });

    setTimeout(() => {
      onSwipe(card.id, action);
      dragOffsetRef.current = { x: 0, y: 0 };
      setDragOffset({ x: 0, y: 0 });
      setIsAnimatingOut(false);
    }, 250);
  }, [isAnimatingOut, onSwipe]);

  const handleEnd = useCallback(() => {
    if (!isDragging || isAnimatingOut) return;
    setIsDragging(false);

    // Read from ref to avoid stale closure values
    const { x, y } = dragOffsetRef.current;

    // Determine swipe direction
    if (y < -SWIPE_UP_THRESHOLD && Math.abs(x) < SWIPE_THRESHOLD) {
      // Swipe up = maybe
      triggerSwipe('maybe');
    } else if (x > SWIPE_THRESHOLD) {
      // Swipe right = like
      triggerSwipe('like');
    } else if (x < -SWIPE_THRESHOLD) {
      // Swipe left = dislike
      triggerSwipe('dislike');
    } else {
      // Snap back
      dragOffsetRef.current = { x: 0, y: 0 };
      setDragOffset({ x: 0, y: 0 });
    }
  }, [isDragging, isAnimatingOut, triggerSwipe]);

  // Touch event handlers
  const onTouchStart = (e: React.TouchEvent) => {
    const touch = e.touches[0];
    handleStart(touch.clientX, touch.clientY);
  };

  const onTouchMove = (e: React.TouchEvent) => {
    const touch = e.touches[0];
    handleMove(touch.clientX, touch.clientY);
  };

  const onTouchEnd = () => handleEnd();

  // Mouse event handlers (desktop)
  const onMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    handleStart(e.clientX, e.clientY);
  };

  const onMouseMove = (e: React.MouseEvent) => {
    handleMove(e.clientX, e.clientY);
  };

  const onMouseUp = () => handleEnd();
  const onMouseLeave = () => {
    if (isDragging) handleEnd();
  };

  if (!currentCard) return null;

  // Card rotation based on drag
  const rotation = dragOffset.x * 0.1;

  // Feedback color overlay
  const feedbackOpacity = Math.min(Math.abs(dragOffset.x) / 150, 0.4);
  const isLikeDirection = dragOffset.x > 30;
  const isDislikeDirection = dragOffset.x < -30;
  const isMaybeDirection = dragOffset.y < -30 && Math.abs(dragOffset.x) < 50;

  return (
    <div
      ref={containerRef}
      className="relative w-full h-[520px]"
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseLeave}
    >
      {/* Next card (peeking behind) */}
      {nextCard && (
        <SwipeCard
          name={nextCard}
          className="scale-[0.95] opacity-70"
        />
      )}

      {/* Current card (draggable) */}
      <div
        className="absolute inset-0 touch-none"
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        onMouseDown={onMouseDown}
      >
        <SwipeCard
          name={currentCard}
          style={{
            transform: `translate(${dragOffset.x}px, ${dragOffset.y}px) rotate(${rotation}deg)`,
            transition: isDragging ? 'none' : 'transform 0.25s ease-out',
          }}
        />

        {/* Swipe feedback overlays */}
        {isLikeDirection && (
          <div
            className="absolute inset-0 rounded-2xl border-4 border-swipe-like pointer-events-none flex items-center justify-center"
            style={{ opacity: feedbackOpacity }}
          >
            <span className="text-swipe-like text-4xl font-bold rotate-[-15deg]">LOVE</span>
          </div>
        )}
        {isDislikeDirection && (
          <div
            className="absolute inset-0 rounded-2xl border-4 border-swipe-dislike pointer-events-none flex items-center justify-center"
            style={{ opacity: feedbackOpacity }}
          >
            <span className="text-swipe-dislike text-4xl font-bold rotate-[15deg]">NOPE</span>
          </div>
        )}
        {isMaybeDirection && (
          <div
            className="absolute inset-0 rounded-2xl border-4 border-swipe-maybe pointer-events-none flex items-center justify-center"
            style={{ opacity: feedbackOpacity }}
          >
            <span className="text-swipe-maybe text-4xl font-bold">MAYBE</span>
          </div>
        )}
      </div>

      {/* Action buttons */}
      <div className="absolute -bottom-14 left-0 right-0 flex justify-center gap-6">
        <button
          onClick={() => triggerSwipe('dislike')}
          className="w-12 h-12 rounded-full bg-bg-card border border-border shadow-card flex items-center justify-center text-xl hover:border-swipe-dislike hover:text-swipe-dislike transition-colors"
          aria-label="Dislike"
        >
          ✕
        </button>
        <button
          onClick={() => triggerSwipe('maybe')}
          className="w-10 h-10 rounded-full bg-bg-card border border-border shadow-card flex items-center justify-center text-lg hover:border-swipe-maybe hover:text-swipe-maybe transition-colors"
          aria-label="Maybe"
        >
          ?
        </button>
        <button
          onClick={() => triggerSwipe('like')}
          className="w-12 h-12 rounded-full bg-bg-card border border-border shadow-card flex items-center justify-center text-xl hover:border-swipe-like hover:text-swipe-like transition-colors"
          aria-label="Like"
        >
          ♥
        </button>
      </div>
    </div>
  );
}
