const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const PROJECT = process.cwd();

function run() {
  console.log('qabot doctor\n');
  let ok = true;

  ok = check('Node >= 18', () => {
    const [major] = process.versions.node.split('.').map(Number);
    if (major < 18) throw new Error(`Node ${process.versions.node} — need 18+`);
  }) && ok;

  ok = check('qabot skills installed', () => {
    const p = path.join(PROJECT, '.claude', 'skills', 'qa');
    if (!fs.existsSync(p)) throw new Error('Run: npx qabot-cli init');
  }) && ok;

  ok = check('qabot hooks installed', () => {
    const p = path.join(PROJECT, '.claude', 'hooks', 'pre_tool_use.py');
    if (!fs.existsSync(p)) throw new Error('Run: npx qabot-cli init');
  }) && ok;

  ok = check('qa-config.yml exists', () => {
    const p = path.join(PROJECT, 'qa', 'qa-config.yml');
    if (!fs.existsSync(p)) throw new Error('Run /qa in Claude Code to scaffold');
  }) && ok;

  ok = check('rtk installed', () => {
    try { execFileSync('which', ['rtk'], { stdio: 'ignore' }); }
    catch { throw new Error('Install: https://github.com/rtk-ai/rtk'); }
  }) && ok;

  warn('ANTHROPIC_API_KEY set', () => {
    if (!process.env.ANTHROPIC_API_KEY) throw new Error('Set ANTHROPIC_API_KEY — subagent spawning will fail at runtime');
  });

  console.log(ok ? '\nAll checks passed.' : '\nFix errors above before running /qa.');
  process.exit(ok ? 0 : 1);
}

function check(label, fn) {
  try {
    fn();
    console.log(`  ✓ ${label}`);
    return true;
  } catch (e) {
    console.log(`  ✗ ${label} — ${e.message}`);
    return false;
  }
}

function warn(label, fn) {
  try {
    fn();
    console.log(`  ✓ ${label}`);
  } catch (e) {
    console.log(`  ⚠ ${label} — ${e.message}`);
  }
}

module.exports = { run };
