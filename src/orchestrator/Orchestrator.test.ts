import { describe, test, expect } from 'bun:test';
import { buildTutorContract, classifyIntent } from './Orchestrator';

// ---------------------------------------------------------------------------
// classifyIntent
// ---------------------------------------------------------------------------

describe('classifyIntent', () => {
  test('lesson_progression for "next" / "move on" / "continue"', () => {
    expect(classifyIntent('Can we move on to the next topic?')).toBe('lesson_progression');
    expect(classifyIntent('next')).toBe('lesson_progression');
    expect(classifyIntent('Please continue')).toBe('lesson_progression');
  });

  test('clarification_question for "example" / "show me"', () => {
    expect(classifyIntent('Can you give me an example?')).toBe('clarification_question');
    expect(classifyIntent('Show me an illustration')).toBe('clarification_question');
  });

  test('proof_help for "proof" / "prove" / "why is"', () => {
    expect(classifyIntent('Can you prove this theorem?')).toBe('proof_help');
    expect(classifyIntent('I need help with this proof')).toBe('proof_help');
    expect(classifyIntent('Why is this true?')).toBe('proof_help');
  });

  test('exercise_attempt for "exercise" / "problem" / "homework"', () => {
    expect(classifyIntent('Here is my exercise attempt')).toBe('exercise_attempt');
    expect(classifyIntent('I have a problem with question 3')).toBe('exercise_attempt');
    expect(classifyIntent('Help with homework')).toBe('exercise_attempt');
  });

  test('meta_course_change for "change" / "setting" / "prefer"', () => {
    expect(classifyIntent('Can we change the pace?')).toBe('meta_course_change');
    expect(classifyIntent('I prefer a different approach')).toBe('meta_course_change');
    expect(classifyIntent('Update setting for rigor')).toBe('meta_course_change');
  });

  test('review_request for "review" / "recap" / "again"', () => {
    expect(classifyIntent('Can we review that topic?')).toBe('review_request');
    expect(classifyIntent('Quick recap please')).toBe('review_request');
    expect(classifyIntent('Explain again')).toBe('review_request');
  });

  test('search_request for "search" / "find" / "look up"', () => {
    expect(classifyIntent('Search for combinatorics')).toBe('search_request');
    expect(classifyIntent('Find the definition of a group')).toBe('search_request');
    expect(classifyIntent('Look up bijection')).toBe('search_request');
  });

  test('defaults to clarification_question for unrecognized input', () => {
    expect(classifyIntent('hello there')).toBe('clarification_question');
    expect(classifyIntent('What is a matrix?')).toBe('clarification_question');
  });
});

// ---------------------------------------------------------------------------
// buildTutorContract
// ---------------------------------------------------------------------------

describe('buildTutorContract', () => {
  const fullConfig = {
    name: 'Professor Euler',
    persona: {
      style: 'socratic',
      tone: 'formal but supportive',
      role: 'private tutor',
      specialization: ['combinatorics'],
    },
    pedagogy: {
      emphasize: ['proof techniques', 'abstraction'],
      avoid: ['hand-waving'],
    },
    adaptationRules: {
      slowDownOnConfusion: true,
    },
  };

  test('extracts identity from config', () => {
    const contract = buildTutorContract(fullConfig);
    expect(contract.identity.name).toBe('Professor Euler');
    expect(contract.identity.role).toBe('private tutor');
  });

  test('sets formality to formal when tone includes "formal"', () => {
    const contract = buildTutorContract(fullConfig);
    expect(contract.style.formality).toBe('formal');
  });

  test('sets formality to semi-formal when tone does not include "formal"', () => {
    const contract = buildTutorContract({
      ...fullConfig,
      persona: { ...fullConfig.persona, tone: 'warm and casual' },
    });
    expect(contract.style.formality).toBe('semi-formal');
  });

  test('detects proof emphasis from pedagogy', () => {
    const contract = buildTutorContract(fullConfig);
    expect(contract.teachingMethod.emphasizeProofs).toBe(true);
  });

  test('no proof emphasis when not in pedagogy', () => {
    const contract = buildTutorContract({
      ...fullConfig,
      pedagogy: { emphasize: ['examples'], avoid: [] },
    });
    expect(contract.teachingMethod.emphasizeProofs).toBe(false);
  });

  test('adaptToPace reflects slowDownOnConfusion', () => {
    expect(buildTutorContract(fullConfig).teachingMethod.adaptToPace).toBe(true);

    const contract = buildTutorContract({
      ...fullConfig,
      adaptationRules: { slowDownOnConfusion: false },
    });
    expect(contract.teachingMethod.adaptToPace).toBe(false);
  });

  test('handles missing/partial config gracefully', () => {
    const contract = buildTutorContract({});
    expect(contract.identity.name).toBe('Tutor');
    expect(contract.identity.role).toBe('tutor');
    expect(contract.style.formality).toBe('semi-formal');
    expect(contract.teachingMethod.emphasizeProofs).toBe(false);
    expect(contract.teachingMethod.adaptToPace).toBe(true);
    expect(contract.boundaries.alwaysEncourageQuestions).toBe(true);
  });
});
