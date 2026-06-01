interface MatchCelebrationProps {
  matchName: string;
  onDismiss: () => void;
}

/**
 * Celebration overlay shown when a mutual match is detected.
 * Pauses the deck, shows animation, resumes on dismiss.
 */
export default function MatchCelebration({ matchName, onDismiss }: MatchCelebrationProps) {
  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-[rgba(44,37,33,0.55)] animate-[fadeIn_0.3s_ease-out]"
      onClick={onDismiss}
    >
      <div
        className="bg-bg-card rounded-2xl p-8 mx-4 max-w-[340px] w-full text-center shadow-elevated animate-[scaleIn_0.4s_ease-out]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Celebration emoji */}
        <div className="text-6xl mb-4 animate-[bounce_0.6s_ease-in-out_infinite]">
          🎉
        </div>

        {/* Match text */}
        <h2 className="text-2xl font-bold text-text mb-2">
          It&apos;s a Match!
        </h2>
        <p className="text-text-secondary mb-2">
          You both love
        </p>
        <p className="text-3xl font-bold text-primary mb-6">
          {matchName}
        </p>

        {/* Glow ring */}
        <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-primary-muted flex items-center justify-center shadow-glow">
          <span className="text-3xl">💛</span>
        </div>

        {/* Dismiss button */}
        <button
          onClick={onDismiss}
          className="w-full py-3 rounded-xl bg-primary text-white font-semibold text-base hover:bg-primary-dark transition-colors"
        >
          Keep Swiping
        </button>
      </div>
    </div>
  );
}
