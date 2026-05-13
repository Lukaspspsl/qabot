#!/usr/bin/env node
const [, , cmd, ...args] = process.argv;

const commands = {
  init: () => require('../src/commands/init').run(args),
  update: () => require('../src/commands/update').run(args),
  doctor: () => require('../src/commands/doctor').run(args),
};

if (!cmd || !commands[cmd]) {
  console.log('Usage: qabot <command>\n\nCommands:\n  init     Install qabot into current project\n  update   Update skills + hooks from qabot source\n  doctor   Check prerequisites');
  process.exit(cmd ? 1 : 0);
}

commands[cmd]();
