import { TutorConfig } from '../schemas/types';
import { prompt, promptList } from '../utils/prompt';

export interface InitTutorOptions {
  /** Pre-filled from CLI flags; skips prompt if provided */
  tutorName?: string;
  persona?: string;
  subject: string;
  /** Skip all prompts and use defaults/flags only (for non-interactive use) */
  nonInteractive?: boolean;
}

/**
 * Build a TutorConfig by prompting the user for each persona field.
 * CLI flags (passed via `opts`) pre-fill values and skip that prompt.
 * In non-interactive mode, all prompts are skipped and defaults are used.
 */
export async function buildInitTutorConfig(opts: InitTutorOptions): Promise<TutorConfig> {
  const subjectCap = opts.subject.charAt(0).toUpperCase() + opts.subject.slice(1);
  const interactive = !opts.nonInteractive && process.stdin.isTTY;

  // --- Persona fields ---
  const name = opts.tutorName
    ? `${opts.tutorName} of ${subjectCap}`
    : interactive
      ? await prompt({ message: 'Tutor name', defaultValue: `Professor of ${subjectCap}` })
      : `Professor of ${subjectCap}`;

  const style = opts.persona
    ?? (interactive
      ? await prompt({ message: 'Persona style (e.g. theoretical, socratic, practical)', defaultValue: 'theoretical' })
      : 'theoretical');

  const tone = interactive
    ? await prompt({ message: 'Tone (e.g. formal but supportive, casual, warm)', defaultValue: 'formal but supportive' })
    : 'formal but supportive';

  const role = interactive
    ? await prompt({ message: 'Role (e.g. private tutor, lecturer, mentor)', defaultValue: 'private tutor' })
    : 'private tutor';

  const specialization = interactive
    ? await promptList({ message: 'Specializations (comma-separated)', defaultValue: opts.subject })
    : [opts.subject];

  // --- Pedagogy ---
  const emphasize = interactive
    ? await promptList({ message: 'Emphasize (comma-separated)', defaultValue: 'proof techniques, abstraction, invariants, exact reasoning' })
    : ['proof techniques', 'abstraction', 'invariants', 'exact reasoning'];

  const avoid = interactive
    ? await promptList({ message: 'Avoid (comma-separated)', defaultValue: 'superficial intuition without formal grounding' })
    : ['superficial intuition without formal grounding'];

  return {
    name,
    persona: {
      style,
      tone,
      role,
      specialization: specialization.length ? specialization : [opts.subject],
    },
    pedagogy: {
      defaultStructure: [
        'motivation',
        'precise definitions',
        'theorem or principle',
        'proof sketch',
        'examples',
        'student exercise',
        'recap',
      ],
      emphasize,
      avoid,
    },
    adaptationRules: {
      askDiagnosticQuestions: true,
      slowDownOnConfusion: true,
      revisitPrerequisitesIfNeeded: true,
      weaveInMlConnections: 'occasionally',
    },
  };
}
