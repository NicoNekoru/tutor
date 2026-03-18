import blessed from 'blessed';
import { Orchestrator } from '../orchestrator/Orchestrator';
import { WorkspaceManager } from '../workspace/WorkspaceManager';
import { SearchResult } from '../schemas/types';

export class TutorTUI {
  private screen: blessed.Widgets.Screen;
  private navigationBox!: blessed.Widgets.BoxElement;
  private contextBox!: blessed.Widgets.BoxElement;
  private toolsBox!: blessed.Widgets.BoxElement;
  private inputLine!: blessed.Widgets.TextareaElement;
  private chatBox!: blessed.Widgets.BoxElement;

  private orchestrator: Orchestrator;
  private ws: WorkspaceManager;
  private currentContext: SearchResult[] = [];

  constructor(orchestrator: Orchestrator, ws: WorkspaceManager) {
    this.orchestrator = orchestrator;
    this.ws = ws;

    this.screen = blessed.screen({
      smartCSR: true,
      fullUnicode: true,
    });

    this.screen.title = 'Tutor RLM';
    this.layout();
    this.setupKeybindings();

    this.chatBox.setContent('Welcome to the Tutor App!\n\nType a message to begin tutoring. Use :help for commands.');
  }

  private layout(): void {
    const width = this.screen.width as number;
    const height = this.screen.height as number;
    const navWidth = 25;
    const rightWidth = Math.floor(width * 0.3);
    const mainWidth = width - navWidth - rightWidth;

    // Navigation pane (left)
    this.navigationBox = blessed.box({
      top: 0,
      left: 0,
      width: navWidth,
      height: '70%',
      tags: true,
      border: { type: 'line' },
      label: ' Navigation ',
      style: {
        fg: 'white',
        border: { fg: 'cyan' },
      },
      scrollable: true,
    });
    this.navigationBox.setContent([
      '{bold}Course{/bold}',
      '',
      '{bold}Commands{/bold}',
      '  :help',
      '  :syllabus',
      '  :lesson next',
      '  :search <query>',
      '  :context',
      '  :quit',
    ].join('\n'));

    // Main dialogue pane (center)
    this.chatBox = blessed.box({
      top: 0,
      left: navWidth,
      width: mainWidth,
      height: '70%',
      border: { type: 'line' },
      label: ' Tutor Dialogue ',
      scrollable: true,
      alwaysScroll: true,
      mouse: true,
      keys: true,
      tags: true,
      style: {
        fg: 'white',
        border: { fg: 'green' },
      },
    });

    // Context inspector (right-top)
    this.contextBox = blessed.box({
      top: 0,
      left: navWidth + mainWidth,
      width: rightWidth,
      height: '40%',
      border: { type: 'line' },
      label: ' Context Inspector ',
      scrollable: true,
      tags: true,
      style: {
        fg: 'white',
        border: { fg: 'yellow' },
      },
    });
    this.contextBox.setContent('(no context yet)');

    // Scratch/tools pane (right-bottom)
    this.toolsBox = blessed.box({
      top: '40%',
      left: navWidth + mainWidth,
      width: rightWidth,
      height: '30%',
      border: { type: 'line' },
      label: ' Tools / Events ',
      scrollable: true,
      tags: true,
      style: {
        fg: 'white',
        border: { fg: 'magenta' },
      },
    });
    this.toolsBox.setContent('(waiting for actions...)');

    // Input line at bottom
    this.inputLine = blessed.textarea({
      bottom: 0,
      left: 0,
      width: '100%',
      height: 3,
      border: { type: 'line' },
      label: ' Input (Enter to send) ',
      inputOnFocus: true,
      tags: true,
      style: {
        fg: 'white',
        border: { fg: 'white' },
      },
    });

    this.screen.append(this.navigationBox);
    this.screen.append(this.chatBox);
    this.screen.append(this.contextBox);
    this.screen.append(this.toolsBox);
    this.screen.append(this.inputLine);

    this.inputLine.focus();
  }

  private setupKeybindings(): void {
    this.inputLine.key('enter', async () => {
      const message = this.inputLine.getValue().trim();
      if (!message) return;

      this.appendChat('You', message);
      this.inputLine.clearValue();
      this.screen.render();

      // Check for commands
      if (message.startsWith(':')) {
        await this.handleCommand(message.slice(1));
        return;
      }

      // Process through orchestrator
      this.appendChat('System', '(thinking...)');
      this.screen.render();

      try {
        const result = await this.orchestrator.processTurn(message);

        // Remove "(thinking...)" line
        const content = this.chatBox.getContent();
        this.chatBox.setContent(content.replace('\n{bold}System{/bold}: (thinking...)', ''));

        this.appendChat('Tutor', result.response);

        // Update context pane
        this.currentContext = result.retrievedContext;
        this.showContext();

        // Update tools pane
        if (result.toolCalls) {
          this.toolsBox.setContent(`Tool Calls:\n${JSON.stringify(result.toolCalls, null, 2)}`);
        }
      } catch (error) {
        const content = this.chatBox.getContent();
        this.chatBox.setContent(content.replace('\n{bold}System{/bold}: (thinking...)', ''));
        this.appendChat('System', `Error: ${error instanceof Error ? error.message : String(error)}`);
      }

      this.screen.render();
    });

    this.screen.key(['C-c'], () => {
      this.screen.destroy();
      process.exit(0);
    });

    // Tab to switch focus between input and chat
    this.screen.key(['tab'], () => {
      if ((this.screen as any).focused === this.inputLine) {
        this.chatBox.focus();
      } else {
        this.inputLine.focus();
      }
      this.screen.render();
    });
  }

  private async handleCommand(cmd: string): Promise<void> {
    const [command, ...args] = cmd.split(' ');

    switch (command) {
      case 'help':
        this.showHelp();
        break;
      case 'syllabus':
        await this.showSyllabus();
        break;
      case 'lesson':
        if (args[0] === 'next') {
          this.appendChat('System', 'Advancing to next lesson... (not implemented yet)');
        } else if (args[0] === 'open' && args[1]) {
          this.appendChat('System', `Opening lesson ${args[1]}... (not implemented yet)`);
        }
        break;
      case 'search':
        if (args.length > 0) {
          await this.doSearch(args.join(' '));
        } else {
          this.appendChat('System', 'Usage: :search <query>');
        }
        break;
      case 'context':
        this.showContext();
        break;
      case 'quit':
        this.screen.destroy();
        process.exit(0);
        break;
      default:
        this.appendChat('System', `Unknown command: :${command}. Try :help`);
    }

    this.screen.render();
  }

  private showHelp(): void {
    this.appendChat('System', [
      'Commands:',
      '  :help          - Show this help',
      '  :syllabus      - Show course syllabus',
      '  :lesson next   - Advance to next lesson',
      '  :lesson open <id> - Open specific lesson',
      '  :search <query> - Search course materials',
      '  :context       - Show current context',
      '  :quit          - Exit',
    ].join('\n'));
  }

  private async showSyllabus(): Promise<void> {
    try {
      const content = await this.ws.readFile('syllabus.md');
      this.appendChat('System', `Syllabus:\n${content.substring(0, 500)}`);
    } catch {
      this.appendChat('System', 'No syllabus found. Run initialization first.');
    }
  }

  private async doSearch(query: string): Promise<void> {
    try {
      const result = await this.orchestrator.processTurn(`:search ${query}`);
      this.currentContext = result.retrievedContext;
      this.showContext();
      this.appendChat('System', `Found ${this.currentContext.length} results for "${query}"`);
    } catch (error) {
      this.appendChat('System', `Search error: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private showContext(): void {
    if (this.currentContext.length === 0) {
      this.contextBox.setContent('(no context retrieved)');
      return;
    }

    const lines: string[] = [];
    for (const r of this.currentContext) {
      lines.push(`[${r.chunkKind}] ${r.heading || 'untitled'} (${r.score?.toFixed(2) ?? '?'})`);
      lines.push(r.contentPreview.substring(0, 120));
      lines.push('---');
    }
    this.contextBox.setContent(lines.join('\n'));
    this.screen.render();
  }

  private appendChat(speaker: string, message: string): void {
    const current = this.chatBox.getContent() || '';
    const entry = `{bold}${speaker}{/bold}: ${message}`;
    this.chatBox.setContent(current ? `${current}\n${entry}` : entry);
    this.chatBox.setScrollPerc(100);
  }

  start(): void {
    this.screen.render();
  }
}
