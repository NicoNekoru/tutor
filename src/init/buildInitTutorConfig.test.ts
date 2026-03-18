import { describe, test, expect } from 'bun:test';
import { buildInitTutorConfig } from './buildInitTutorConfig';

describe('buildInitTutorConfig', () => {
  test('non-interactive mode uses all defaults', async () => {
    const config = await buildInitTutorConfig({
      subject: 'algebra',
      nonInteractive: true,
    });

    expect(config.name).toBe('Professor of Algebra');
    expect(config.persona.style).toBe('theoretical');
    expect(config.persona.tone).toBe('formal but supportive');
    expect(config.persona.role).toBe('private tutor');
    expect(config.persona.specialization).toEqual(['algebra']);
    expect(config.pedagogy.emphasize).toContain('proof techniques');
    expect(config.pedagogy.avoid).toContain('superficial intuition without formal grounding');
    expect(config.adaptationRules.askDiagnosticQuestions).toBe(true);
  });

  test('CLI flags override defaults in non-interactive mode', async () => {
    const config = await buildInitTutorConfig({
      subject: 'physics',
      tutorName: 'Dr. Feynman',
      persona: 'socratic',
      nonInteractive: true,
    });

    expect(config.name).toBe('Dr. Feynman of Physics');
    expect(config.persona.style).toBe('socratic');
    // Other fields keep defaults
    expect(config.persona.tone).toBe('formal but supportive');
    expect(config.persona.specialization).toEqual(['physics']);
  });

  test('capitalizes subject in tutor name', async () => {
    const config = await buildInitTutorConfig({
      subject: 'combinatorics',
      nonInteractive: true,
    });
    expect(config.name).toBe('Professor of Combinatorics');
  });

  test('always includes default pedagogy structure', async () => {
    const config = await buildInitTutorConfig({
      subject: 'math',
      nonInteractive: true,
    });

    expect(config.pedagogy.defaultStructure).toEqual([
      'motivation',
      'precise definitions',
      'theorem or principle',
      'proof sketch',
      'examples',
      'student exercise',
      'recap',
    ]);
  });

  test('adaptation rules have sensible defaults', async () => {
    const config = await buildInitTutorConfig({
      subject: 'math',
      nonInteractive: true,
    });

    expect(config.adaptationRules).toEqual({
      askDiagnosticQuestions: true,
      slowDownOnConfusion: true,
      revisitPrerequisitesIfNeeded: true,
      weaveInMlConnections: 'occasionally',
    });
  });

  test('subject is used as fallback specialization', async () => {
    const config = await buildInitTutorConfig({
      subject: 'topology',
      nonInteractive: true,
    });
    expect(config.persona.specialization).toEqual(['topology']);
  });
});
