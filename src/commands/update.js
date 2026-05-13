const fs = require('fs');
const path = require('path');

const SRC = path.resolve(__dirname, '../../');
const PROJECT = process.cwd();

function run() {
  console.log('qabot update\n');

  const skillsDst = path.join(PROJECT, '.claude', 'skills');
  if (!fs.existsSync(skillsDst)) {
    console.log('Not initialized. Run: npx qabot-cli init');
    process.exit(1);
  }

  // Overwrite skills
  const skillsDir = path.join(SRC, 'skills');
  const skills = fs.readdirSync(skillsDir).filter(d => d.startsWith('qa'));
  for (const skill of skills) {
    const dst = path.join(skillsDst, skill);
    fs.rmSync(dst, { recursive: true, force: true });
    copyDir(path.join(skillsDir, skill), dst);
    console.log(`  ✓ ${skill} updated`);
  }

  // Overwrite hooks
  const hooksDst = path.join(PROJECT, '.claude', 'hooks');
  for (const hook of ['pre_tool_use.py', 'post_tool_use.py']) {
    const src = path.join(SRC, 'hooks', hook);
    if (!fs.existsSync(src)) continue;
    fs.copyFileSync(src, path.join(hooksDst, hook));
    console.log(`  ✓ .claude/hooks/${hook} updated`);
  }

  console.log('\nDone.');
}

function copyDir(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name);
    const d = path.join(dst, entry.name);
    entry.isDirectory() ? copyDir(s, d) : fs.copyFileSync(s, d);
  }
}

module.exports = { run };
