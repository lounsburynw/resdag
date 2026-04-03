Review all claims being committed for structural quality.

Check each claim against the project profile (.resdag/profile.json):

1. **Hypothesis parent**: Every result claim must link to a hypothesis via --hypothesis.
   Fail if a result has no hypothesis parent.

2. **Claim structure**: Claim text must contain the template sections
   (Question/Finding/Implication for results, Prediction/Rationale/If wrong for hypotheses).
   Fail if sections are missing.

3. **Vocabulary**: All domain tags must be in .resdag/vocabulary.json.
   Fail on unknown tags.

4. **Audience**: Claims must be understandable to the stated audience without project context.
   Warn if claim text contains unexplained jargon or acronyms.

Output JSON: {"pass": true/false, "issues": [...], "severity": "critical|warning"}
