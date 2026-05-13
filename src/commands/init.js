const fs = require('fs');
const path = require('path');

const SRC = path.resolve(__dirname, '../../');
const PROJECT = process.cwd();

function run() {
  console.log('qabot init\n');

  installSkills();
  installHooks();
  wireSettings();
  scaffoldQa();
  updateGitignore();

  console.log('\nDone. Open Claude Code and run /qa to start.');
}

function installSkills() {
  const dst = path.join(PROJECT, '.claude', 'skills');
  fs.mkdirSync(dst, { recursive: true });

  const skillsDir = path.join(SRC, 'skills');
  const skills = fs.readdirSync(skillsDir).filter(d => d.startsWith('qa'));

  for (const skill of skills) {
    const skillDst = path.join(dst, skill);
    if (fs.existsSync(skillDst)) {
      console.log(`  ~ ${skill} (already present, skipped)`);
      continue;
    }
    copyDir(path.join(skillsDir, skill), skillDst);
    console.log(`  ✓ ${skill}`);
  }
}

function installHooks() {
  const dst = path.join(PROJECT, '.claude', 'hooks');
  fs.mkdirSync(dst, { recursive: true });

  for (const hook of ['pre_tool_use.py', 'post_tool_use.py']) {
    const src = path.join(SRC, 'hooks', hook);
    const target = path.join(dst, hook);
    if (!fs.existsSync(src)) continue;
    fs.copyFileSync(src, target);
    console.log(`  ✓ .claude/hooks/${hook}`);
  }
}

function wireSettings() {
  const settingsPath = path.join(PROJECT, '.claude', 'settings.json');
  let settings = {};
  if (fs.existsSync(settingsPath)) {
    try { settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8')); } catch {}
  }

  const hookEntry = (cmd) => ({ type: 'command', command: cmd });
  const preHook = 'python3 .claude/hooks/pre_tool_use.py';
  const postHook = 'python3 .claude/hooks/post_tool_use.py';

  // Idempotent — check before adding
  const preExists = JSON.stringify(settings).includes(preHook);
  if (!preExists) {
    settings.PreToolUse = settings.PreToolUse || [];
    settings.PreToolUse.push({
      matcher: 'Bash|WebFetch|Write|Edit|Read|Grep',
      hooks: [hookEntry(preHook)],
    });
    settings.PostToolUse = settings.PostToolUse || [];
    settings.PostToolUse.push({
      matcher: '*',
      hooks: [hookEntry(postHook)],
    });
    fs.mkdirSync(path.dirname(settingsPath), { recursive: true });
    fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2) + '\n');
    console.log('  ✓ .claude/settings.json (hook wiring added)');
  } else {
    console.log('  ~ .claude/settings.json (hooks already wired)');
  }
}

function scaffoldQa() {
  for (const dir of ['cases', 'docs', 'tests', 'reports', 'templates', '.context', '.trsync']) {
    const p = path.join(PROJECT, 'qa', dir);
    if (!fs.existsSync(p)) {
      fs.mkdirSync(p, { recursive: true });
      console.log(`  ✓ qa/${dir}/`);
    }
  }

  const configSrc = path.join(SRC, 'templates', 'qa-config.yml');
  const configDst = path.join(PROJECT, 'qa', 'qa-config.yml');
  if (!fs.existsSync(configDst) && fs.existsSync(configSrc)) {
    fs.copyFileSync(configSrc, configDst);
    console.log('  ✓ qa/qa-config.yml');
  }

  const tcSrc = path.join(SRC, 'templates', 'tc.yml');
  const tcDst = path.join(PROJECT, 'qa', 'templates', 'tc.yml');
  if (!fs.existsSync(tcDst) && fs.existsSync(tcSrc)) {
    fs.copyFileSync(tcSrc, tcDst);
    console.log('  ✓ qa/templates/tc.yml');
  }

  const syncLog = path.join(PROJECT, 'qa', 'sync-log.md');
  if (!fs.existsSync(syncLog)) {
    const date = new Date().toISOString().slice(0, 10);
    fs.writeFileSync(syncLog, `last_sync: ${date}\n--- sync history ---\n`);
    console.log('  ✓ qa/sync-log.md');
  }

  const envExample = path.join(PROJECT, 'qa', '.env.example');
  if (!fs.existsSync(envExample)) {
    fs.writeFileSync(envExample, [
      '# TestRail (only if testrail.enabled: true in qa-config.yml)',
      'TR_USER=""',
      'TR_API_KEY=""',
      'TR_PASSWORD=""',
      '',
      '# Anthropic — used by sub-agents invoked from skills',
      'ANTHROPIC_API_KEY=""',
      '',
      '# Stagehand (only if stagehand.enabled: true in qa-config.yml)',
      '# BROWSERBASE_API_KEY=""',
      '# STAGEHAND_ENV="LOCAL"',
    ].join('\n') + '\n');
    console.log('  ✓ qa/.env.example');
  }
}

function updateGitignore() {
  const gitignorePath = path.join(PROJECT, '.gitignore');
  const marker = '# --- qa-concise ---';
  const existing = fs.existsSync(gitignorePath) ? fs.readFileSync(gitignorePath, 'utf8') : '';

  if (existing.includes(marker)) {
    console.log('  ~ .gitignore (already installed)');
    return;
  }

  const block = `
# --- qa-concise ---
# qabot project-local install (reinstall via: npx qabot-cli init)
.claude/skills/qa*/
.claude/hooks/pre_tool_use.py
.claude/hooks/post_tool_use.py

# Everything under qa/ is local by default — only tests/ is committed
qa/
!qa/tests/
!qa/tests/**

# Exclude test runner build artifacts from qa/tests/
qa/tests/**/.playwright/
qa/tests/**/playwright-report/
qa/tests/**/test-results/
qa/tests/**/blob-report/
qa/tests/**/.maestro/
qa/tests/**/build/
qa/tests/**/DerivedData/
qa/tests/**/.gradle/
*.xcuserstate

# Stagehand (local cache — each user builds their own)
qa/.stagehand-cache.json

# Node / OS
node_modules/
.DS_Store
*.log
*.swp
.idea/
.vscode/
# --- /qa-concise ---
`;

  fs.writeFileSync(gitignorePath, existing + block);
  console.log('  ✓ .gitignore (qa rules appended)');
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
