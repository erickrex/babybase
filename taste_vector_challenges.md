# Taste Vector Challenges (Option D)

Edge cases and failure modes to consider before implementing per-user taste vectors
as the primary signal for shared deck generation.

---

## Vector Quality Problems

### Imbalanced swipe counts
One partner has 200 swipes, the other has 3. The midpoint vector is dominated by the
person with more data — their taste vector is stable and well-defined, the other's is
essentially noise. The "shared" deck ends up being mostly one person's preferences with
a slight drift.

**Mitigation**: weight each user's vector by a confidence score (e.g. based on swipe
count) before taking the midpoint, rather than a naive 50/50 average.

---

### All likes, no dislikes
If someone likes everything (swipes right on 90% of names), their taste vector is just
the average of the whole corpus — it points toward the semantic center of all baby names,
which is meaningless. The midpoint then gets pulled toward that center and loses signal.

**Mitigation**: require a minimum like-rate threshold before trusting the vector, or
incorporate dislikes as a repulsion vector subtracted from the centroid.

---

### Likes clustered in one region
Someone likes 50 names but they're all short Anglo-Saxon names — Emma, Ella, Eva, Ava.
Their taste vector is extremely tight. The other partner likes a diverse spread. The
midpoint lands in a weird intermediate space that neither person actually wants.

**Mitigation**: measure vector variance as a quality signal. A very tight vector paired
with a diffuse one should use a weighted midpoint that respects the tighter signal more,
or fall back to C (stated preferences) for the diffuse partner.

---

### Early swipes poisoning the vector
A user's first few swipes are exploratory — they're clicking around, not sure what they
like yet. Those early likes get baked into the taste vector and persist. Later swipes
that reflect real taste get averaged in but can't fully override the early noise.

**Mitigation**: apply recency weighting (exponential decay on older swipes), or enforce
a minimum swipe count before the vector is used at all.

---

## Couple Formation Timing

### Asymmetric history at link time
Partner A has been solo-swiping for 2 weeks and has a rich taste vector. Partner B just
registered and has zero swipes. The midpoint is A's vector shifted slightly toward the
embedding origin — essentially A's preferences with a penalty. Partner B gets a deck
that reflects A's taste, not a genuine merge, and may disengage.

**Mitigation**: detect asymmetry at deck generation time. If one partner's vector has
low confidence, weight toward the stated-preference profile (Option C) for that partner
until enough swipes accumulate.

---

### Both users swiped on overlapping names before linking
If they both swiped on some of the same names independently, those names are already in
their swipe history and get excluded from the deck. But the taste vectors were built
including those names. The deck is generated from vectors that include signal from names
that can't appear in it — a subtle inconsistency that slightly misaligns the query
embedding with the actual candidate pool.

**Mitigation**: acceptable in practice (the signal is still directionally correct), but
worth documenting as a known approximation.

---

### Re-coupling after a break
A couple splits, both users swipe independently for a while (possibly with different
partners), then re-couple. Their taste vectors now include swipe history from outside
this relationship. The midpoint reflects preferences shaped by a different context.

**Mitigation**: scope taste vectors to a couple, not globally per user. This partially
reduces the benefit of Option D (solo pre-swiping no longer helps), but avoids
cross-relationship contamination.

---

## Semantic Space Problems

### Midpoint lands in a sparse region
The embedding space isn't uniformly dense. The midpoint of two taste vectors might land
in a region with very few names nearby in Qdrant. The search returns low-confidence
results — names that are "closest" to the midpoint but not actually close in absolute
terms.

**Mitigation**: check retrieval scores on the returned candidates. If the top result
scores below a threshold, fall back to Option C (stated preferences) for that deck
generation.

---

### Both partners like the same outlier names
Two people both like very unusual, rare names. Their taste vectors both point toward a
sparse corner of the embedding space. The midpoint is accurate but Qdrant has almost
nothing there — the candidate pool is tiny, diversity constraints can't be satisfied,
and the deck ends up thin or repetitive.

**Mitigation**: same retrieval score threshold check as above. Also consider relaxing
diversity constraints when the candidate pool is small.

---

### Gender filter interacts badly with the vector
The taste vector is built from liked names regardless of gender. If someone liked a mix
of boy and girl names during exploration, their vector points toward a gender-neutral
region. But the deck filter applies `gender_usage = "boy"` (or girl). The vector says
"go here" but the filter says "only these" — the intersection might be nearly empty,
forcing a fallback that ignores the vector entirely.

**Mitigation**: build separate taste vectors per gender, or filter swipe history by the
couple's stated gender preference before computing the taste vector.

---

## Behavioral Edge Cases

### Strategic swiping
One partner figures out that liking certain names influences the deck and starts liking
names they don't actually want in order to steer recommendations. The taste vector
becomes a manipulation tool rather than a genuine signal.

**Mitigation**: hard to fully prevent. Anomaly detection on like rate spikes or sudden
vector drift could flag it, but this is low priority for early-stage product.

---

### Spite dislikes / dishonest swipes
Someone dislikes every name their partner suggests in conversation, then swipes right on
them in the app (or vice versa). The taste vector reflects app behavior, not actual
preference.

**Mitigation**: no technical fix. The vector is only as honest as the user's swipes.
Acknowledged as an inherent limitation.

---

### One partner stops swiping
After 20 swipes, Partner B loses interest and stops. Their taste vector is frozen while
Partner A's keeps growing and evolving. Over time the midpoint drifts toward A's current
taste, but B's stale vector keeps pulling it back. The deck slowly becomes less relevant
for both.

**Mitigation**: track last-swipe timestamp per user. If a vector hasn't been updated in
N days, reduce its weight in the midpoint calculation and lean more on stated preferences.

---

## The Most Dangerous Failure Mode

### Silent degradation with no feedback
All of the above fail quietly. The deck just gets slightly worse — less relevant, less
exciting. Users swipe less, engagement drops, but there's no error, no log, no signal
that vector quality is the cause.

**Mitigation**: instrument taste vectors with explicit quality metrics:
- `swipe_count` — raw number of swipes contributing to the vector
- `like_rate` — ratio of likes to total swipes
- `vector_variance` — spread of the contributing vectors (tight vs. diffuse)
- `last_updated_at` — staleness indicator
- `confidence_score` — composite of the above, used to decide C vs D at runtime

Log which phase (C or D) was used for each deck generation so degradation can be
correlated with outcomes.

---

## Summary: When to Trust Option D

Use the taste vector (Option D) only when all of the following hold:

| Condition | Suggested threshold |
|---|---|
| Sufficient swipe history | ≥ 20 swipes per user |
| Reasonable like rate | between 10% and 80% |
| Retrieval quality is acceptable | top candidate score ≥ 0.6 |
| Vector is not stale | updated within last 30 days |

Otherwise fall back to Option C (stated preferences via onboarding profile).
