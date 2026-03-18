import readline from 'readline';
import { Orchestrator } from '../orchestrator/Orchestrator';

export class SimpleCLI {
  private orchestrator: Orchestrator;
  private rl: readline.Interface;

  constructor(orchestrator: Orchestrator) {
    this.orchestrator = orchestrator;
    this.rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
    });
  }

  async start(): Promise<void> {
    console.log('\n=== Tutor RLM CLI ===');
    console.log('Type your message, or :help for commands, :quit to exit.\n');

    while (true) {
      const prompt = await this.getInput();
      if (prompt === null) break;

      const cmd = prompt.trim();
      if (cmd === ':quit' || cmd === ':exit' || cmd === ':q') {
        break;
      }

      if (cmd.startsWith(':')) {
        await this.handleCommand(cmd.slice(1));
        continue;
      }

      try {
        console.log('\nTutor: ', end => {
          console.log('');
        });
        const result = await this.orchestrator.processTurn(cmd);
        console.log(result.response);
        console.log('');
      } catch (error) {
        console.error('Error:', error instanceof Error ? error.message : String(error));
        console.log('');
      }
    }

    this.rl.close();
    console.log('Goodbye!');
  }

  private getInput(): Promise<string | null> {
    return new Promise((resolve) => {
      this.rl.question('You> ', (answer) => {
        resolve(answer);
      });
    });
  }

  private async handleCommand(cmd: string): Promise<void> {
    const [command, ...args] = cmd.split(' ');
    switch (command) {
      case 'help':
        console.log(`
Commands:
  :help          - Show this help
  :syllabus      - Show syllabus
  :lesson next   - Advance to next lesson
  :search <q>    - Search course materials
  :context       - Show current retrieval context
  :quit          - Exit
        `.trim());
        break;
      case 'syllabus':
        console.log('Syllabus feature not implemented yet.');
        break;
      case 'lesson':
        if (args[0] === 'next') {
          console.log('Advance lesson not implemented yet.');
        } else {
          console.log('Lesson command. Use :lesson next');
        }
        break;
      case 'search':
        if (args.length > 0) {
          const query = args.join(' ');
          const results = this.orchestrator['retrieval'].search(query, { topK: 5 });
          console.log(`\nSearch results for "${query}":`);
          results.forEach((r, i) => {
            console.log(`${i + 1}. [${r.chunkKind}] ${r.heading || 'untitled'} (score: ${r.score?.toFixed(2)})`);
            console.log(`   ${r.contentPreview.substring(0, 150)}...\n`);
          });
        } else {
          console.log('Usage: :search <query>');
        }
        break;
      case 'context':
        // This would need to expose the last retrieval from orchestrator
        console.log('Context command - need to store last retrieval');
        break;
      default:
        console.log(`Unknown command: :${command}`);
    }
    console.log('');
  }
}
