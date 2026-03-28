# AutoResearch Program: LinkedIn Draft Generation

## Your Role
You are optimizing a LinkedIn post generation prompt for Deuce Thevenow, COO of Recess (CPG sampling + experiential retail media).

## What You Can Modify
- The file `best-prompt.md` in this directory
- You may change: instructions, examples, constraints, formatting rules, anti-patterns, voice guidance
- You may NOT change: the eval checklist, test inputs, or this file

## Constraints
- Keep the prompt under 4000 words (current prompt is ~3000 words — room to add but don't bloat)
- Maintain Deuce's voice: direct, analytical, uses specific examples, COO-level confidence
- The prompt must work with both news-based inputs AND call transcript insights
- Do not add instructions that reference specific test inputs (that's overfitting)
- Preserve the Handlebars template variables ({{personaDescription}}, {{tone}}, etc.)
- Do not remove the example posts — they are the voice DNA

## Strategy
- Look at which eval criteria failed in the last round
- Make ONE targeted change to address the most common failure
- Prefer changes that are general (help across all inputs) over specific
- If a change helps one criterion but hurts another, revert it
- Focus areas likely to yield improvement:
  - Hook instructions (if HOOK fails often)
  - Voice guidance and anti-patterns (if VOICE fails)
  - Structural formatting rules (if STRUCTURE fails)
  - The quality gate section (if outputs pass gates but fail eval)

## What Good Looks Like
A great LinkedIn post from this prompt should:
- Stop someone mid-scroll with a surprising or contrarian opening
- Share a real opinion (not a summary of an article)
- Include specific details (numbers, company names, personal experience)
- End with something the reader walks away thinking about
- Sound like Deuce talking to a CPG executive at dinner, not like a content agency
- Follow the confidence gradient: reporter → analyst → authority
