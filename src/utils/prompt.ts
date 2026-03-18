import * as readline from 'readline';

export interface PromptOptions {
  message: string;
  defaultValue?: string;
}

/**
 * Prompt the user for input on stdin. Returns the default if stdin is not a TTY
 * (e.g. in CI or piped input).
 */
export async function prompt(opts: PromptOptions): Promise<string> {
  const suffix = opts.defaultValue ? ` [${opts.defaultValue}]` : '';

  // Non-interactive: return default immediately
  if (!process.stdin.isTTY) {
    return opts.defaultValue ?? '';
  }

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  return new Promise<string>((resolve) => {
    rl.question(`${opts.message}${suffix}: `, (answer) => {
      rl.close();
      const trimmed = answer.trim();
      resolve(trimmed || opts.defaultValue || '');
    });
  });
}

/**
 * Prompt for a comma-separated list. Returns parsed array.
 */
export async function promptList(opts: PromptOptions): Promise<string[]> {
  const raw = await prompt(opts);
  if (!raw) return [];
  return raw.split(',').map((s) => s.trim()).filter(Boolean);
}

/**
 * Prompt for a yes/no boolean.
 */
export async function promptBool(opts: PromptOptions & { defaultValue: string }): Promise<boolean> {
  const raw = await prompt(opts);
  return raw.toLowerCase().startsWith('y');
}
