import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';
import { useCouple } from '../../contexts/CoupleContext';

interface Question {
  key: string;
  title: string;
  description: string;
  type: 'choice' | 'multi' | 'text';
  options?: { value: string; label: string }[];
}

const QUESTIONS: Question[] = [
  {
    key: 'baby_gender_preference',
    title: 'Baby Gender',
    description: 'Are you looking for names for a boy, girl, or gender-neutral?',
    type: 'choice',
    options: [
      { value: 'boy', label: 'Boy' },
      { value: 'girl', label: 'Girl' },
      { value: 'non_binary', label: 'Gender-neutral' },
    ],
  },
  {
    key: 'preferred_name_age',
    title: 'Name Style',
    description: 'Do you prefer modern, classic, or a balanced mix?',
    type: 'choice',
    options: [
      { value: 'new', label: 'Modern' },
      { value: 'old', label: 'Classic' },
      { value: 'balanced', label: 'Balanced' },
    ],
  },
  {
    key: 'preferred_name_length',
    title: 'Name Length',
    description: 'Do you prefer short names, long names, or no preference?',
    type: 'choice',
    options: [
      { value: 'short', label: 'Short' },
      { value: 'long', label: 'Long' },
      { value: 'any', label: 'No preference' },
    ],
  },
  {
    key: 'historical_importance',
    title: 'Historical Significance',
    description: 'How important is historical or cultural significance to you?',
    type: 'choice',
    options: [
      { value: 'low', label: 'Not important' },
      { value: 'medium', label: 'Somewhat important' },
      { value: 'high', label: 'Very important' },
    ],
  },
  {
    key: 'preferred_name_backgrounds',
    title: 'Cultural Backgrounds',
    description: 'Which cultural backgrounds interest you? (Select all that apply)',
    type: 'multi',
    options: [
      { value: 'Spanish', label: 'Spanish' },
      { value: 'Russian', label: 'Russian' },
      { value: 'German', label: 'German' },
      { value: 'English', label: 'English' },
      { value: 'Italian', label: 'Italian' },
      { value: 'French', label: 'French' },
      { value: 'Greek', label: 'Greek' },
      { value: 'Scandinavian', label: 'Scandinavian' },
      { value: 'Arabic', label: 'Arabic' },
      { value: 'Japanese', label: 'Japanese' },
    ],
  },
  {
    key: 'residence_country',
    title: 'Country of Residence',
    description: 'Where does your family live? (2-letter country code, e.g. DE, US, MX)',
    type: 'text',
  },
];

export default function PreferencesPage() {
  const navigate = useNavigate();
  const { syncAfterMutation } = useCouple();
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({});
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const currentQuestion = QUESTIONS[step];
  const isLastStep = step === QUESTIONS.length - 1;

  const handleChoiceSelect = (value: string) => {
    setAnswers((prev) => ({ ...prev, [currentQuestion.key]: value }));
  };

  const handleMultiSelect = (value: string) => {
    const current = (answers[currentQuestion.key] as string[]) || [];
    const updated = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    setAnswers((prev) => ({ ...prev, [currentQuestion.key]: updated }));
  };

  const handleTextChange = (value: string) => {
    setAnswers((prev) => ({ ...prev, [currentQuestion.key]: value }));
  };

  const handleNext = async () => {
    setError('');

    const answer = answers[currentQuestion.key];
    if (!answer || (Array.isArray(answer) && answer.length === 0)) {
      setError('Please make a selection to continue.');
      return;
    }

    if (isLastStep) {
      setIsLoading(true);
      try {
        const { coupleState } = await syncAfterMutation(() =>
          api.post('/onboarding/preferences/', answers)
        );
        const hasCoupleReady =
          coupleState.couple?.status === 'active' &&
          coupleState.onboardingComplete.user &&
          coupleState.onboardingComplete.partner;
        const soloReady =
          !coupleState.hasCouple && coupleState.onboardingComplete.user;
        navigate(hasCoupleReady || soloReady ? '/deck' : '/onboarding/partner');
      } catch (err: unknown) {
        const error = err as { response?: { data?: { message?: string; errors?: Record<string, string[]> }; status?: number } };
        const message = error.response?.data?.message || 'Failed to save preferences.';
        setError(message);

        // Navigate back to the gender question if there's a gender conflict
        if (error.response?.status === 409 && error.response?.data?.errors?.baby_gender_preference) {
          const genderStepIndex = QUESTIONS.findIndex((q) => q.key === 'baby_gender_preference');
          if (genderStepIndex >= 0) {
            setStep(genderStepIndex);
          }
        }
      } finally {
        setIsLoading(false);
      }
    } else {
      setStep((prev) => prev + 1);
    }
  };

  const handleBack = () => {
    if (step > 0) {
      setStep((prev) => prev - 1);
      setError('');
    }
  };

  return (
    <div className="portrait-container min-h-screen flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-md">
        {/* Progress indicator */}
        <div className="flex gap-1.5 mb-8">
          {QUESTIONS.map((_, i) => (
            <div
              key={i}
              className={`h-1.5 flex-1 rounded-full transition-colors ${
                i <= step ? 'bg-primary' : 'bg-border'
              }`}
            />
          ))}
        </div>

        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-text mb-2">
            {currentQuestion.title}
          </h1>
          <p className="text-base text-text-secondary">
            {currentQuestion.description}
          </p>
        </div>

        {/* Choice question */}
        {currentQuestion.type === 'choice' && currentQuestion.options && (
          <div className="space-y-3">
            {currentQuestion.options.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => handleChoiceSelect(option.value)}
                className={`w-full rounded-xl border px-5 py-4 text-base font-medium text-left transition-colors ${
                  answers[currentQuestion.key] === option.value
                    ? 'border-primary bg-primary-muted text-primary-dark'
                    : 'border-border bg-bg-card text-text hover:bg-bg-muted'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        )}

        {/* Multi-select question */}
        {currentQuestion.type === 'multi' && currentQuestion.options && (
          <div className="grid grid-cols-2 gap-3">
            {currentQuestion.options.map((option) => {
              const selected = ((answers[currentQuestion.key] as string[]) || []).includes(option.value);
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => handleMultiSelect(option.value)}
                  className={`rounded-xl border px-4 py-3 text-sm font-medium transition-colors ${
                    selected
                      ? 'border-primary bg-primary-muted text-primary-dark'
                      : 'border-border bg-bg-card text-text hover:bg-bg-muted'
                  }`}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
        )}

        {/* Text input question */}
        {currentQuestion.type === 'text' && (
          <input
            type="text"
            value={(answers[currentQuestion.key] as string) || ''}
            onChange={(e) => handleTextChange(e.target.value.toUpperCase())}
            className="block w-full rounded-xl border border-border bg-bg-card px-4 py-3 text-base text-text shadow-sm placeholder:text-text-muted focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            placeholder="e.g. DE"
            maxLength={2}
          />
        )}

        {error && (
          <div className="mt-4 rounded-xl bg-error/10 border border-error/20 p-3 text-sm text-error">
            {error}
          </div>
        )}

        <div className="mt-8 flex gap-3">
          {step > 0 && (
            <button
              type="button"
              onClick={handleBack}
              className="flex-1 rounded-xl border border-border bg-bg-card px-4 py-3.5 text-base font-medium text-text-secondary hover:bg-bg-muted transition-colors"
            >
              Back
            </button>
          )}
          <button
            type="button"
            onClick={handleNext}
            disabled={isLoading}
            className="flex-1 rounded-xl bg-primary px-4 py-3.5 text-base font-semibold text-white hover:bg-primary-dark disabled:opacity-50 transition-colors"
          >
            {isLoading ? 'Saving...' : isLastStep ? 'Finish' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  );
}
