# BabyBase Hackathon Pitch

## Under-2-Minute Script

Hi, I am building BabyBase: a swipe-based baby-name discovery app for couples.

Choosing a baby name sounds simple, but it is really a messy recommendation problem. Each parent brings different cultures, languages, style preferences, and emotional reactions. Most baby-name apps give static lists. BabyBase turns naming into a shared, adaptive discovery workflow.

Parents onboard, then swipe through personalized decks. The first aha moment is the mutual match: both parents independently like the same name, and BabyBase turns private preferences into a shared decision.

The second aha moment is exploration. From a matched name, the couple can find names that mean similar things, names that sound similar, cross-cultural options, bridge names, and wildcard picks. This is not a chatbot. It is an interactive vector-search product.

Qdrant is central. Each name has multiple Bedrock embedding vectors in Qdrant: semantic, phonetic-style, and cross-cultural. The same name catalog can answer different similarity questions. "More like this" searches meaning and style. "Sounds like" searches sound shape. Cross-cultural mode searches international usability.

The third aha moment is the map. BabyBase projects semantic vectors into 2D, so couples can see matches, finalists, and recommendations as a landscape instead of a flat list.

After Qdrant retrieves candidates, BabyBase reranks them with product-specific signals: fit, cultural overlap, bridge potential, novelty, and diversity. As couples swipe, it builds taste vectors and uses them for fresh best-match decks once both partners have enough signal.

The result is a collaborative decision tool that helps couples discover, compare, and converge on names that fit both people.

## Three Strongest Points

1. **It is clearly beyond a chatbot.** BabyBase uses vector search inside a real interaction model: onboarding, swiping, matching, finalists, similar-name exploration, and a map.
2. **Qdrant is material to the product.** Named vectors power separate semantic, phonetic, and cross-cultural retrieval modes over the same name catalog.
3. **The user experience has emotional clarity.** The strongest demo moment is not technical jargon; it is two parents finding a mutual match and then exploring why nearby names fit.

## AHA Moments

### 1. The Mutual Match

Both parents swipe separately. When they independently like the same name, the app creates a match. This makes the recommendation system feel collaborative instead of passive.

Demo line:

> "This is the first moment the app becomes more than search: it found overlap between two people."

### 2. Same Name, Different Vector Spaces

Open a matched name and compare `More like this` with `Sounds like`.

- `More like this` uses the `semantic` vector.
- `Sounds like` uses the `phonetic_style` vector.
- `Cross-cultural` uses the `cross_cultural` vector.

Demo line:

> "The same database can answer different kinds of similarity because Qdrant stores multiple named vectors per name."

### 3. The Name Map

Show the map after there are matches, finalists, likes, and recommendations. The map makes vector space visible.

Demo line:

> "Instead of asking users to trust an invisible model, BabyBase shows the recommendation space as a map."

### 4. Taste Becomes A Shared Signal

After enough swipes, each parent has a taste vector. Fresh best-match decks can use the confidence-weighted midpoint of both parents' vectors.

Demo line:

> "The app does not just learn one user's taste. It learns where the couple overlaps."

## Demo Flow

1. Show onboarding preferences for two parents.
2. Generate a `best_match` deck.
3. Swipe through a few names.
4. Show a mutual match.
5. Open `More like this` and explain semantic vector search.
6. Open `Sounds like` and explain phonetic vector search.
7. Show `Finalists` as the couple's decision set.
8. Show the name map and explain PCA projection from semantic vectors.

## One-Sentence Version

BabyBase is a Qdrant-powered baby-name recommendation app that helps couples move from separate preferences and swipe behavior to shared matches, finalists, and explainable name discovery.

## Technical Claims To Emphasize

- Uses Qdrant named vectors for multiple search modes over the same names.
- Uses Bedrock Titan Embed V2 embeddings with 1024 dimensions.
- Separates semantic, phonetic, and cross-cultural retrieval.
- Excludes already-swiped names at retrieval time.
- Reranks vector candidates with domain-specific scoring.
- Learns taste vectors from swipe history once enough signal exists.
- Uses PCA over semantic vectors to power the name-map visualization.

## Be Honest About

- Taste learning is batched and conservative, not instant after every swipe.
- Cached decks can delay visible recommendation changes.
- The strongest demo moments are vector search modes, matching, finalists, and the map.
- For the hackathon, pitch this as an intelligent recommendation and discovery product, not as a chatbot.

## Closing Line

BabyBase shows how vector search can turn a deeply personal, subjective decision into an interactive recommendation system couples can actually use together.
